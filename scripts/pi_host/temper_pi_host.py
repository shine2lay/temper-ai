#!/usr/bin/env python3
"""temper-pi-host: the host helper for Temper's Pi team members (ADR-M4-02, -12, -15).

Stdlib-only Python, one file plus its auth bridge ``temper_pi_host_bridge.mjs`` (a small
Node script, delivered beside it).  It serves one Unix socket: one request line per
connection, one answer line back, one request at a time.

    token <slot>                                         ok <token> | denied <why>
    status                                               ok <json>  | denied <why>
    branch <repo> <leader git dir> <commit> <trial id>   made | exists | denied <why>

Everything deployment-specific (the socket, the served uid, the Pi state root, the allowed
slots, the bridge and the Pi SDK it must load, the project roots, branch on/off, the hourly
token ceiling) comes from a private JSON config file given with ``--config``.

What it can touch (docs/pi-host-helper.md says the same, in more words):
- it reads its config file;
- it binds the socket named there, inside a folder that must already exist, belong to this
  user and be mode 0700 (it never creates, chmods or chowns a folder);
- it runs the host ``pi`` CLI for its version and the read-only ``auth check --no-refresh``;
- it runs the auth bridge, which reads (and, when a login is due, refreshes) Pi logins
  through the pinned Pi SDK's own auth storage, for the allowed multi-pass alias slots only;
- with the branch verb on, it runs hardened git to create one branch
  ``refs/heads/team/<trial id>`` in a source repo under the project roots, from a leader's
  git copy under the Pi state root.  Never checkout, push or force.

It stores nothing.  It logs one line per request to stderr (the journal, under systemd):
never a token, a fingerprint of one, an account id or any content.

Subcommands: ``serve`` (the service), ``check`` (config and bridge start check, no socket),
``ask`` (ask a running helper for its status), ``selftest`` (an isolated run with a stub Pi
CLI and a stub Pi SDK: no real login, no model call).
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import select
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NAME = "temper-pi-host"
PROTOCOL = 1
DEFAULT_BASE_PROVIDER = "anthropic"
DEFAULT_SDK_PACKAGE = "@earendil-works/pi-coding-agent"
AI_PACKAGE = "@earendil-works/pi-ai"
MIN_VALIDITY_MS = 30 * 60 * 1000  # a handed-out login stays good for at least 30 minutes
SOCKET_PATH_LIMIT = 100  # bytes; the socket path must be shorter
MAX_REQUEST = 4096
MAX_BRIDGE_LINE = 1 << 16
REQUEST_READ_TIMEOUT_S = 5.0
CLI_TIMEOUT_S = 20.0
GIT_TIMEOUT_S = 120.0
HOUR_S = 3600.0
ZERO_ID = "0" * 40
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TRIAL_ID_RE = re.compile(r"^[0-9a-f]{12}$")
WORD_RE = re.compile(r"^[A-Za-z0-9_.+:-]{1,64}$")
PACKAGE_RE = re.compile(r"^(@[a-z0-9_.-]+/)?[a-z0-9_.-]+$")
BASE_RE = re.compile(r"^[a-z][a-z0-9_.]{0,39}$")
TOKEN_RE = re.compile(r"^[\x21-\x7e]{1,8192}$")
BAD_PATH_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")

TOP_KEYS = {"socket", "uid", "pi_state_root", "home", "pi_agent_dir", "path", "pi_cli",
            "base_provider", "allowed_slots", "bridge", "project_roots", "branch_enabled",
            "branch_max_bytes", "tokens_per_hour", "token_timeout_s"}
BRIDGE_KEYS = {"node", "script", "sdk_root", "sdk_package", "sdk_version", "ai_version",
               "start_timeout_s", "stop_grace_s"}

# What a token refusal says.  Every one names the slot; none carries text from the Pi SDK.
REFUSALS = {
    "bad_slot": "the slot name is missing or malformed",
    "account_1": "slot {slot} is account 1 and is never served",
    "not_alias": "slot {slot} is not an alias of {base}",
    "not_served": "slot {slot} is not one this helper serves",
    "not_registered": "slot {slot} is not registered in Pi's multi-pass subscriptions",
    "registry_unreadable": "slot {slot}: Pi's multi-pass subscriptions could not be read",
    "no_login": "slot {slot} has no stored login",
    "not_oauth": "slot {slot} has no OAuth login",
    "refresh_failed": "slot {slot}: its login could not be refreshed",
    "no_token": "slot {slot}: the login gave no token",
    "auth_failed": "slot {slot}: Pi's auth storage could not be used",
    "no_flow": "slot {slot}: the Pi SDK has no {base} login flow",
    "sdk_changed": ("slot {slot}: the Pi SDK on disk changed since the helper started (now "
                    "{found}, expected {expected}); auth.json was not read or written"),
    "sdk_unreadable": "slot {slot}: the Pi SDK could not be read; auth.json was not read or written",
    "sdk_version_mismatch": "slot {slot}: the Pi SDK is {found}, expected {expected}",
    "timeout": "slot {slot}: no token within {timeout} s",
    "ceiling": "slot {slot}: the hourly token ceiling ({limit}) is reached",
    "no_bridge": "slot {slot}: no auth bridge is configured",
    "bridge_down": "slot {slot}: the auth bridge stopped",
    "bad_answer": "slot {slot}: the auth bridge gave an unusable answer",
}


# --- config ----------------------------------------------------------------------------


class ConfigError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class BridgeConfig:
    script: str
    sdk_root: str
    sdk_version: str
    sdk_package: str = DEFAULT_SDK_PACKAGE
    ai_version: str = ""
    node: str = "node"
    start_timeout_s: float = 20.0
    stop_grace_s: float = 120.0


@dataclass(frozen=True)
class Config:
    socket: str
    pi_state_root: str
    uid: int
    home: str
    pi_agent_dir: str
    path: tuple[str, ...]
    pi_cli: tuple[str, ...] = ("pi",)
    base_provider: str = DEFAULT_BASE_PROVIDER
    allowed_slots: tuple[str, ...] = ()
    bridge: BridgeConfig | None = None
    project_roots: tuple[str, ...] = ()
    branch_enabled: bool = False
    branch_max_bytes: int = 100 * 1024 * 1024
    tokens_per_hour: int = 120
    token_timeout_s: float = 30.0


def alias_pattern(base: str) -> re.Pattern[str]:
    """A multi-pass alias of ``base``: ``<base>-<n>`` with n >= 2 (n = 1 is the base slot)."""
    return re.compile(rf"^{re.escape(base)}-([2-9]|[1-9][0-9]+)$")


def clean_abs_path(value: Any) -> bool:
    """An absolute, normalized path without whitespace or control characters."""
    return (isinstance(value, str) and value.startswith("/") and not BAD_PATH_CHARS.search(value)
            and os.path.normpath(value) == value)


def load_config(path: str) -> Config:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError([f"the config {path} could not be read ({type(exc).__name__})"]) from None
    return parse_config(raw)


def parse_config(raw: Any) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError(["the config must be a JSON object"])
    problems: list[str] = []
    for key in sorted(k for k in raw if k not in TOP_KEYS and not k.startswith("_")):
        problems.append(f"unknown key {key!r}")

    def path_value(key: str, default: str | None = None) -> str:
        value = raw.get(key, default)
        if not clean_abs_path(value):
            problems.append(f"{key} must be an absolute, normalized path")
            return ""
        return str(value)

    def int_value(key: str, default: int, low: int, high: int) -> int:
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            problems.append(f"{key} must be a whole number from {low} to {high}")
            return default
        return value

    sock = path_value("socket")
    if sock and len(sock.encode()) >= SOCKET_PATH_LIMIT:
        problems.append(f"socket must be shorter than {SOCKET_PATH_LIMIT} bytes")
    home = path_value("home", os.path.expanduser("~"))
    agent_dir = path_value("pi_agent_dir", os.path.join(home or "/", ".pi", "agent"))
    state_root = path_value("pi_state_root")
    uid = int_value("uid", os.getuid(), 0, 2**31 - 1)

    path_dirs = raw.get("path", [d for d in os.environ.get("PATH", "").split(":") if clean_abs_path(d)])
    if not isinstance(path_dirs, list) or not path_dirs or not all(clean_abs_path(d) for d in path_dirs):
        problems.append("path must be a list of absolute folders")
        path_dirs = []

    pi_cli = raw.get("pi_cli", ["pi"])
    if (not isinstance(pi_cli, list) or not pi_cli
            or not all(isinstance(a, str) and a and not BAD_PATH_CHARS.search(a) for a in pi_cli)):
        problems.append("pi_cli must be a list of words (the command that runs Pi)")
        pi_cli = ["pi"]

    base = raw.get("base_provider", DEFAULT_BASE_PROVIDER)
    if not isinstance(base, str) or not BASE_RE.match(base):
        problems.append("base_provider must be a provider id like the default")
        base = DEFAULT_BASE_PROVIDER
    slots = raw.get("allowed_slots", [])
    if not isinstance(slots, list) or not all(isinstance(s, str) for s in slots):
        problems.append("allowed_slots must be a list of slot names")
        slots = []
    for slot in slots:
        if slot == base:
            problems.append(f"allowed_slots can't hold {slot}: it is account 1, never served")
        elif not alias_pattern(base).match(slot):
            problems.append(f"allowed_slots: {slot!r} is not an alias of {base} like {base}-2")
    if len(set(slots)) != len(slots):
        problems.append("allowed_slots lists a slot twice")

    bridge = None
    braw = raw.get("bridge")
    if braw is not None:
        if isinstance(braw, dict):
            bridge = _parse_bridge(braw, problems)
        else:
            problems.append("bridge must be an object")

    roots = raw.get("project_roots", [])
    if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
        problems.append("project_roots must be a list of folders")
        roots = []
    for root in roots:
        base_dir = root[:-2] if root.endswith("/*") else root
        if not clean_abs_path(base_dir) or base_dir == "/":
            problems.append(f"project_roots: {root!r} must be an absolute folder or folder/*")

    branch_enabled = raw.get("branch_enabled", False)
    if not isinstance(branch_enabled, bool):
        problems.append("branch_enabled must be true or false")
        branch_enabled = False
    branch_max = int_value("branch_max_bytes", 100 * 1024 * 1024, 1, 2**40)
    per_hour = int_value("tokens_per_hour", 120, 1, 100_000)
    timeout = raw.get("token_timeout_s", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not 1 <= timeout <= 120:
        problems.append("token_timeout_s must be a number of seconds from 1 to 120")
        timeout = 30
    if problems:
        raise ConfigError(problems)
    return Config(socket=sock, pi_state_root=state_root, uid=uid, home=home, pi_agent_dir=agent_dir,
                  path=tuple(path_dirs), pi_cli=tuple(pi_cli), base_provider=base,
                  allowed_slots=tuple(slots), bridge=bridge, project_roots=tuple(roots),
                  branch_enabled=branch_enabled, branch_max_bytes=branch_max,
                  tokens_per_hour=per_hour, token_timeout_s=float(timeout))


def _parse_bridge(braw: dict, problems: list[str]) -> BridgeConfig | None:
    before = len(problems)
    for key in sorted(k for k in braw if k not in BRIDGE_KEYS and not k.startswith("_")):
        problems.append(f"unknown key bridge.{key}")
    script, sdk_root = braw.get("script"), braw.get("sdk_root")
    for key, value in (("script", script), ("sdk_root", sdk_root)):
        if not clean_abs_path(value):
            problems.append(f"bridge.{key} must be an absolute, normalized path")
    version = braw.get("sdk_version")
    if not isinstance(version, str) or not WORD_RE.match(version):
        problems.append("bridge.sdk_version must be the exact Pi SDK version the chats use")
    package = braw.get("sdk_package", DEFAULT_SDK_PACKAGE)
    if not isinstance(package, str) or not PACKAGE_RE.match(package):
        problems.append("bridge.sdk_package must be an npm package name")
    ai_version = braw.get("ai_version", "")
    if not isinstance(ai_version, str) or (ai_version and not WORD_RE.match(ai_version)):
        problems.append("bridge.ai_version must be a version or empty")
    node = braw.get("node", "node")
    if not isinstance(node, str) or not node or BAD_PATH_CHARS.search(node):
        problems.append("bridge.node must be the node command or its path")
    start_timeout = braw.get("start_timeout_s", 20)
    grace = braw.get("stop_grace_s", 120)
    for key, value in (("start_timeout_s", start_timeout), ("stop_grace_s", grace)):
        if isinstance(value, bool) or not isinstance(value, int | float) or not 1 <= value <= 600:
            problems.append(f"bridge.{key} must be a number of seconds from 1 to 600")
    if len(problems) > before:
        return None
    return BridgeConfig(script=str(script), sdk_root=str(sdk_root), sdk_version=str(version),
                        sdk_package=str(package), ai_version=str(ai_version), node=str(node),
                        start_timeout_s=float(start_timeout), stop_grace_s=float(grace))


# --- small pieces ----------------------------------------------------------------------


def log(**fields: Any) -> None:
    """One request line on stderr: words only, never a token or any content."""
    parts = [f"{NAME}:"]
    for key, value in fields.items():
        text = re.sub(r"[\s\x00-\x1f\x7f]+", "_", str(value))[:240] or "-"
        parts.append(f"{key}={text}")
    print(" ".join(parts), file=sys.stderr, flush=True)


def say(text: str) -> None:
    """A start, stop or refusal-to-start line (never request data)."""
    print(f"{NAME}: {text}", file=sys.stderr, flush=True)


def word(value: Any, default: str = "unknown") -> str:
    return value if isinstance(value, str) and WORD_RE.match(value) else default


def package_word(value: Any) -> str:
    return value if isinstance(value, str) and PACKAGE_RE.match(value) else "unknown"


def child_env(cfg: Config) -> dict[str, str]:
    """The environment of the Pi CLI and the bridge: a fixed list, no keys."""
    return {"HOME": cfg.home, "PATH": ":".join(cfg.path), "LANG": "C.UTF-8",
            "PI_CODING_AGENT_DIR": cfg.pi_agent_dir, "PI_OFFLINE": "1",
            "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"}


def run(argv: list[str], *, env: dict[str, str], timeout: float, cwd: str = "/",
        input_text: str | None = None) -> tuple[int, str]:
    """Run a command; (exit code, stdout).  stderr is dropped unread: it may carry content."""
    try:
        done = subprocess.run(argv, env=env, cwd=cwd, timeout=timeout, check=False,
                              input=None if input_text is None else input_text.encode(),
                              stdin=subprocess.DEVNULL if input_text is None else None,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, PermissionError):
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    return done.returncode, done.stdout.decode("utf-8", "replace")


def pi_version(cfg: Config) -> str:
    code, out = run([*cfg.pi_cli, "--version"], env=child_env(cfg), timeout=CLI_TIMEOUT_S)
    lines = out.strip().splitlines()
    return word(lines[0].strip() if code == 0 and lines else "")


def pi_check_words(cfg: Config, slot: str) -> str:
    """The stock CLI's read-only auth check for one slot, as two words (status, reason)."""
    _, out = run([*cfg.pi_cli, "auth", "check", "--provider", slot, "--json", "--no-refresh"],
                 env=child_env(cfg), timeout=CLI_TIMEOUT_S)
    data = _json_object(out)
    if data is None:
        return "unknown"
    words = [word(data.get("status"), ""), word(data.get("reason"), "")]
    return " ".join(w for w in words if w) or "unknown"


def git_env(cfg: Config) -> dict[str, str]:
    return {"PATH": ":".join(cfg.path), "HOME": os.devnull, "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0"}


# Hardened git: no system or global config, no hooks, no fsmonitor, objects checked on
# fetch, the local transport only, no automatic maintenance.  The -c values also reach the
# upload-pack that git starts in the leader's copy.
GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
       "-c", "fetch.fsckObjects=true", "-c", "transfer.fsckObjects=true",
       "-c", "protocol.allow=never", "-c", "protocol.file.allow=always",
       "-c", "submodule.recurse=false", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
       "-c", "core.autocrlf=false")


def git_version(cfg: Config) -> str:
    code, out = run(["git", "--version"], env=git_env(cfg), timeout=CLI_TIMEOUT_S)
    parts = out.split()
    return word(parts[-1] if code == 0 and parts else "")


class Ceiling:
    """The hourly token ceiling: a tripwire that refuses past N hand-offs in any hour."""

    def __init__(self, per_hour: int, clock: Callable[[], float] = time.monotonic):
        self.per_hour = per_hour
        self.clock = clock
        self.times: collections.deque[float] = collections.deque()

    def _trim(self) -> None:
        now = self.clock()
        while self.times and now - self.times[0] >= HOUR_S:
            self.times.popleft()

    def used(self) -> int:
        self._trim()
        return len(self.times)

    def take(self) -> bool:
        self._trim()
        if len(self.times) >= self.per_hour:
            return False
        self.times.append(self.clock())
        return True


def _json_object(line: str | None) -> dict | None:
    try:
        value = json.loads(line or "")
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# --- the auth bridge -------------------------------------------------------------------


class BridgeRefused(Exception):
    """The bridge would not start (wrong or unreadable Pi SDK), or it stopped."""

    def __init__(self, code: str, hello: dict | None = None):
        super().__init__(code)
        self.code = code
        self.hello = hello or {}


class BridgeTimeout(Exception):
    pass


class Bridge:
    """The Node auth bridge: a child process talking JSON lines on its stdin and stdout.

    Its stderr goes nowhere (it might carry SDK text).  It starts with a hello naming the Pi
    SDK it loaded; a start whose SDK is not the configured one is refused before the bridge
    did any authentication."""

    def __init__(self, cfg: Config):
        assert cfg.bridge is not None
        self.cfg = cfg
        self.bcfg: BridgeConfig = cfg.bridge
        self.proc: subprocess.Popen[bytes] | None = None
        self.buf = b""
        self.hello: dict = {}
        self.next_id = 0
        self.retiring: list[tuple[subprocess.Popen[bytes], float]] = []

    def argv(self) -> list[str]:
        b = self.bcfg
        timeout_ms = int(max(1.0, self.cfg.token_timeout_s * 0.8) * 1000)
        return [b.node, b.script, "--sdk-root", b.sdk_root, "--sdk-package", b.sdk_package,
                "--sdk-version", b.sdk_version, "--ai-version", b.ai_version or "-",
                "--agent-dir", self.cfg.pi_agent_dir, "--base-provider", self.cfg.base_provider,
                "--slots", ",".join(self.cfg.allowed_slots) or "-",
                "--min-validity-ms", str(MIN_VALIDITY_MS), "--timeout-ms", str(timeout_ms)]

    def start(self) -> dict:
        self.stop_now()
        self.hello = {}
        try:
            self.proc = subprocess.Popen(self.argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, env=child_env(self.cfg), cwd="/",
                                         close_fds=True, start_new_session=True)
        except OSError:
            self.proc = None
            raise BridgeRefused("bridge_unstartable") from None
        line = self._read_line(time.monotonic() + self.bcfg.start_timeout_s)
        hello = _json_object(line)
        if hello is None:
            self.stop_now()
            raise BridgeRefused("no_hello")
        if hello.get("ok") is not True:
            self.stop_now()
            raise BridgeRefused(word(hello.get("reason"), "refused"), hello)
        wrong_sdk = hello.get("package") != self.bcfg.sdk_package or hello.get("version") != self.bcfg.sdk_version
        wrong_ai = bool(self.bcfg.ai_version) and hello.get("ai_version") != self.bcfg.ai_version
        if wrong_sdk or wrong_ai:
            self.stop_now()
            raise BridgeRefused("sdk_version_mismatch", hello)
        self.hello = hello
        return hello

    def request(self, op: str, slot: str, timeout: float) -> dict:
        self.reap()
        if self.proc is None or self.proc.poll() is not None:
            self.start()
        proc = self.proc
        assert proc is not None and proc.stdin is not None
        self.next_id += 1
        rid = self.next_id
        try:
            proc.stdin.write((json.dumps({"id": rid, "op": op, "slot": slot}) + "\n").encode())
            proc.stdin.flush()
        except OSError:
            self.stop_now()
            raise BridgeRefused("bridge_down") from None
        deadline = time.monotonic() + timeout
        while True:
            line = self._read_line(deadline)
            if line is None:
                if proc.poll() is None:
                    self.retire()
                    raise BridgeTimeout()
                self.stop_now()
                raise BridgeRefused("bridge_down")
            answer = _json_object(line)
            if answer is not None and answer.get("id") == rid:
                return answer
            # Anything else (a late answer to a request that timed out) is dropped unread.

    def _read_line(self, deadline: float) -> str | None:
        """The bridge's next line, or None on timeout or end of its output."""
        assert self.proc is not None and self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([fd], [], [], left)
            if not ready:
                return None
            chunk = os.read(fd, 65536)
            if not chunk:
                return None
            self.buf += chunk
            if len(self.buf) > MAX_BRIDGE_LINE and b"\n" not in self.buf:
                self.buf = b""
                return ""
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode("utf-8", "replace")

    def retire(self) -> None:
        """Let a late bridge go: ask it to stop at its next safe point (never in the middle of
        a request: Pi writes auth.json in place) and stop reading what it says."""
        proc, self.proc = self.proc, None
        self.buf = b""
        if proc is None:
            return
        _close_pipes(proc)
        try:
            proc.send_signal(signal.SIGTERM)
        except OSError:
            pass
        self.retiring.append((proc, time.monotonic()))

    def reap(self) -> None:
        keep = []
        for proc, since in self.retiring:
            if proc.poll() is not None:
                continue
            if time.monotonic() - since > self.bcfg.stop_grace_s:
                proc.kill()
                proc.wait(timeout=5)
                continue
            keep.append((proc, since))
        self.retiring = keep

    def stop_now(self) -> None:
        """Stop the current bridge: end its input; it finishes what it is doing, then exits."""
        proc, self.proc = self.proc, None
        self.buf = b""
        if proc is None:
            return
        _close_pipes(proc)
        try:
            proc.wait(timeout=self.bcfg.stop_grace_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def stop_all(self) -> None:
        self.stop_now()
        for proc, since in self.retiring:
            try:
                proc.wait(timeout=max(1.0, self.bcfg.stop_grace_s - (time.monotonic() - since)))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        self.retiring = []


def _close_pipes(proc: subprocess.Popen[bytes]) -> None:
    for pipe in (proc.stdin, proc.stdout):
        try:
            if pipe is not None:
                pipe.close()
        except OSError:
            pass


def start_refusal(cfg: Config, exc: BridgeRefused) -> str:
    """What a refused bridge start says (versions and paths only)."""
    b = cfg.bridge
    assert b is not None
    hello = exc.hello
    if exc.code == "sdk_version_mismatch":
        found = f"{package_word(hello.get('package'))} {word(hello.get('version'))}"
        expected = f"{b.sdk_package} {b.sdk_version}"
        if b.ai_version:
            found += f" with {AI_PACKAGE} {word(hello.get('ai_version'))}"
            expected += f" with {AI_PACKAGE} {b.ai_version}"
        return f"the Pi SDK the bridge found is {found}, expected {expected}"
    if exc.code == "sdk_unreadable":
        return f"the Pi SDK {b.sdk_package} under {b.sdk_root} could not be read"
    if exc.code == "sdk_surface":
        return f"the Pi SDK {b.sdk_package} under {b.sdk_root} lacks what the bridge uses"
    if exc.code in ("no_hello", "bridge_unstartable"):
        return f"the auth bridge did not start ({b.node} {b.script})"
    return f"the auth bridge refused ({exc.code})"


# --- the branch verb -------------------------------------------------------------------


@dataclass(frozen=True)
class Root:
    """A project root: a folder (``/a/b``), or every folder directly in one (``/a/*``)."""

    text: str
    base: str
    children: bool

    @classmethod
    def parse(cls, text: str) -> Root:
        children = text.endswith("/*")
        return cls(text, text[:-2] if children else text, children)

    def holds(self, path: str, base: str | None = None) -> bool:
        base = self.base if base is None else base
        return os.path.dirname(path) == base if self.children else path == base


def inside(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip("/") + "/")


def repo_problem(cfg: Config, repo: str) -> str | None:
    """Why ``repo`` is not a source repo this helper may branch in (None: it may)."""
    if not clean_abs_path(repo):
        return "is not an absolute, normalized path"
    roots = [Root.parse(r) for r in cfg.project_roots]
    if not any(r.holds(repo) for r in roots):
        return "is not under the project roots"
    real = os.path.realpath(repo)
    real_bases = [os.path.realpath(r.base) for r in roots]
    if not any(r.holds(real, b) for r, b in zip(roots, real_bases, strict=True)):
        return "resolves outside the project roots"
    env = git_env(cfg)
    code, top = run([*GIT, "-C", real, "rev-parse", "--show-toplevel"], env=env, timeout=CLI_TIMEOUT_S)
    if code != 0 or os.path.realpath(top.strip()) != real:
        return "is not the top of a git work tree"
    code, out = run([*GIT, "-C", real, "rev-parse", "--absolute-git-dir", "--git-common-dir"],
                    env=env, timeout=CLI_TIMEOUT_S)
    dirs = out.strip().splitlines()
    if code != 0 or len(dirs) != 2:
        return "has no readable git folder"
    for d in dirs:
        if not any(inside(os.path.realpath(os.path.join(real, d)), b) for b in real_bases):
            return "keeps its git folder outside the project roots"
    return None


def leader_problem(cfg: Config, leader: str) -> str | None:
    """Why ``leader`` is not a team member's git copy under the Pi state root (None: it is)."""
    if not clean_abs_path(leader):
        return "is not an absolute, normalized path"
    state = os.path.realpath(cfg.pi_state_root)
    if not inside(leader, cfg.pi_state_root) and not inside(leader, state):
        return "is not under the Pi state root"
    real = os.path.realpath(leader)
    rel = os.path.relpath(real, state)
    parts = rel.split("/")
    if (rel.startswith("..") or len(parts) != 4 or parts[2] != "git" or not parts[3].endswith(".git")
            or len(parts[3]) <= 4 or any(p.startswith(".") for p in parts)):
        return "is not a team member's git copy (<run>/<team>/git/<name>.git) under the Pi state root"
    if not (os.path.isfile(os.path.join(real, "HEAD")) and os.path.isdir(os.path.join(real, "objects"))):
        return "is not a git folder"
    for name in ("alternates", "http-alternates"):
        if os.path.lexists(os.path.join(real, "objects", "info", name)):
            return "borrows objects from elsewhere (alternates)"
    return None


def new_objects_size(cfg: Config, repo: str, leader: str, commit: str) -> int | None:
    """Bytes on disk of the leader's objects behind ``commit`` that the source repo lacks."""
    env = git_env(cfg)
    code, out = run([*GIT, "-C", repo, "for-each-ref", "--format=%(objectname)",
                     "refs/heads", "refs/tags", "refs/remotes"], env=env, timeout=GIT_TIMEOUT_S)
    if code != 0:
        return None
    tips = sorted(set(out.split()))[:20000]
    present: list[str] = []
    if tips:
        code, out = run([*GIT, "--git-dir", leader, "cat-file", "--batch-check=%(objectname) %(objecttype)"],
                        env=env, timeout=GIT_TIMEOUT_S, input_text="\n".join(tips) + "\n")
        if code != 0:
            return None
        for line in out.splitlines():
            sha, _, kind = line.partition(" ")
            if kind in ("commit", "tag") and COMMIT_RE.match(sha):
                present.append(sha)
    stdin = commit + "\n" + "".join(f"^{sha}\n" for sha in present)
    code, out = run([*GIT, "--git-dir", leader, "rev-list", "--objects", "--disk-usage", "--stdin"],
                    env=env, timeout=GIT_TIMEOUT_S, input_text=stdin)
    try:
        return int(out.strip()) if code == 0 else None
    except ValueError:
        return None


def branch_at(cfg: Config, repo: str, ref: str) -> str:
    code, out = run([*GIT, "-C", repo, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}"],
                    env=git_env(cfg), timeout=CLI_TIMEOUT_S)
    sha = out.strip()
    return sha if code == 0 and COMMIT_RE.match(sha) else ""


def make_branch(cfg: Config, repo: str, leader: str, commit: str, trial_id: str) -> tuple[str, dict]:
    """Create ``refs/heads/team/<trial_id>`` at ``commit`` in ``repo``, fetched from ``leader``.

    Create-only: an existing branch is never moved (one already at ``commit`` counts as made,
    as in Temper's in-process path).  Answers made, exists or denied."""
    fields: dict[str, Any] = {"repo": repo if clean_abs_path(repo) else "-",
                              "ref": f"team/{trial_id}" if TRIAL_ID_RE.match(trial_id) else "-"}

    def denied(why: str, code: str) -> tuple[str, dict]:
        return f"denied {why}", {**fields, "result": "denied", "why": code}

    if not cfg.branch_enabled:
        return denied("the branch verb is off", "off")
    if not TRIAL_ID_RE.match(trial_id):
        return denied("the trial id is malformed", "trial_id")
    if not COMMIT_RE.match(commit):
        return denied("the commit is not a full 40-character id", "commit")
    problem = repo_problem(cfg, repo)
    if problem:
        return denied(f"{fields['repo']} {problem}", "repo")
    problem = leader_problem(cfg, leader)
    if problem:
        return denied(f"{leader if clean_abs_path(leader) else 'the leader copy'} {problem}", "leader")
    real_repo, real_leader = os.path.realpath(repo), os.path.realpath(leader)
    env = git_env(cfg)
    code, _ = run([*GIT, "--git-dir", real_leader, "cat-file", "-e", f"{commit}^{{commit}}"],
                  env=env, timeout=CLI_TIMEOUT_S)
    if code != 0:
        return denied("the commit is not in the leader's copy", "no_commit")
    ref = f"refs/heads/team/{trial_id}"
    existing = branch_at(cfg, real_repo, ref)
    if existing == commit:
        return "made", {**fields, "result": "made", "why": "already"}
    if existing:
        return "exists", {**fields, "result": "exists"}
    size = new_objects_size(cfg, real_repo, real_leader, commit)
    if size is None:
        return denied("the branch's size could not be measured", "size_unknown")
    if size > cfg.branch_max_bytes:
        return denied(f"branch not made: too large ({size} bytes, cap {cfg.branch_max_bytes})", "too_large")
    tmp = f"refs/temper/branch-tmp/{trial_id}"
    try:
        run([*GIT, "-C", real_repo, "update-ref", "-d", tmp], env=env, timeout=CLI_TIMEOUT_S)
        code, _ = run([*GIT, "-C", real_repo, "fetch", "-q", "--no-tags", "--no-write-fetch-head",
                       "--no-recurse-submodules", real_leader, f"{commit}:{tmp}"],
                      env=env, timeout=GIT_TIMEOUT_S)
        if code != 0:
            return denied("the leader's commit could not be fetched", "fetch")
        code, _ = run([*GIT, "-C", real_repo, "update-ref", ref, commit, ZERO_ID],
                      env=env, timeout=CLI_TIMEOUT_S)
        if code == 0:
            return "made", {**fields, "result": "made"}
        existing = branch_at(cfg, real_repo, ref)
        if existing == commit:
            return "made", {**fields, "result": "made", "why": "already"}
        if existing:
            return "exists", {**fields, "result": "exists"}
        return denied("the branch could not be created", "update_ref")
    finally:
        run([*GIT, "-C", real_repo, "update-ref", "-d", tmp], env=env, timeout=CLI_TIMEOUT_S)


# --- the helper ------------------------------------------------------------------------


def refusal(code: str, slot: str, cfg: Config, **extra: Any) -> str:
    values: dict[str, Any] = {"slot": slot, "base": cfg.base_provider, "found": "unknown",
                              "expected": "unknown", "timeout": int(cfg.token_timeout_s),
                              "limit": cfg.tokens_per_hour}
    values.update({k: v for k, v in extra.items() if v is not None})
    return REFUSALS.get(code, "slot {slot}: refused").format(**values)


def slot_problem(cfg: Config, slot: str) -> str | None:
    """The helper's own slot check, before the bridge (which checks the same again)."""
    if not WORD_RE.match(slot):
        return "bad_slot"
    if slot == cfg.base_provider:
        return "account_1"
    if not alias_pattern(cfg.base_provider).match(slot):
        return "not_alias"
    if slot not in cfg.allowed_slots:
        return "not_served"
    return None


def peer_cred(conn: socket.socket) -> tuple[int, int]:
    """(pid, uid) of the process at the other end of a Unix socket (SO_PEERCRED)."""
    fmt = "3i"
    pid, uid, _gid = struct.unpack(fmt, conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                        struct.calcsize(fmt)))
    return pid, uid


def read_request(conn: socket.socket) -> str | None:
    data = b""
    try:
        while b"\n" not in data and len(data) <= MAX_REQUEST:
            chunk = conn.recv(MAX_REQUEST + 1)
            if not chunk:
                break
            data += chunk
    except OSError:
        return None
    line = data.split(b"\n", 1)[0]
    if not line or len(line) > MAX_REQUEST:
        return None
    try:
        return line.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _send(conn: socket.socket, answer: str) -> None:
    try:
        conn.sendall((answer + "\n").encode())
    except OSError:
        pass


class Helper:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.bridge = Bridge(cfg) if cfg.bridge is not None else None
        self.ceiling = Ceiling(cfg.tokens_per_hour)
        self.pi = "unknown"

    def sdk_word(self) -> str:
        return word(self.bridge.hello.get("version"), "-") if self.bridge else "-"

    def handle(self, conn: socket.socket) -> None:
        started = time.monotonic()
        conn.settimeout(REQUEST_READ_TIMEOUT_S)
        try:
            pid, uid = peer_cred(conn)
        except OSError:
            log(verb="-", result="denied", why="no_peer")
            return
        if uid != self.cfg.uid:
            _send(conn, f"denied uid {uid} is not served")
            log(verb="-", result="denied", why="uid", uid=uid, peer=pid)
            return
        line = read_request(conn)
        parts = line.split(" ") if line else []
        verb = parts[0] if parts and parts[0] in ("token", "status", "branch") else "-"
        if verb == "token" and len(parts) == 2:
            answer, fields = self.token(parts[1])
        elif verb == "status" and len(parts) == 1:
            answer, fields = self.status()
        elif verb == "branch" and len(parts) == 5:
            answer, fields = make_branch(self.cfg, parts[1], parts[2], parts[3], parts[4])
        else:
            answer, fields = "denied the request is not one this helper knows", {"result": "denied", "why": "request"}
        conn.settimeout(REQUEST_READ_TIMEOUT_S)
        _send(conn, answer)
        log(verb=verb, **fields, ms=int((time.monotonic() - started) * 1000), pi=self.pi,
            sdk=self.sdk_word(), peer=pid)

    def token(self, slot: str) -> tuple[str, dict]:
        cfg = self.cfg
        shown = slot if WORD_RE.match(slot) else "-"
        fields: dict[str, Any] = {"slot": shown}

        def denied(code: str, **extra: Any) -> tuple[str, dict]:
            return "denied " + refusal(code, shown, cfg, **extra), {**fields, "result": "denied", "why": code}

        problem = slot_problem(cfg, slot)
        if problem:
            return denied(problem)
        if self.bridge is None:
            return denied("no_bridge")
        if not self.ceiling.take():
            say(f"tripwire: the hourly token ceiling ({cfg.tokens_per_hour}) is reached; hand-offs are refused")
            return denied("ceiling")
        expected = self.bridge.bcfg.sdk_version
        try:
            answer = self.bridge.request("token", slot, cfg.token_timeout_s)
        except BridgeTimeout:
            return denied("timeout")
        except BridgeRefused as exc:
            code = exc.code if exc.code in REFUSALS else "bridge_down"
            return denied(code, found=word(exc.hello.get("version")) if exc.hello else None, expected=expected)
        if answer.get("ok") is True:
            token = answer.get("token")
            if answer.get("slot") == slot and isinstance(token, str) and TOKEN_RE.match(token):
                return "ok " + token, {**fields, "result": "ok"}
            return denied("bad_answer")
        code = word(answer.get("reason"), "bad_answer")
        return denied(code if code in REFUSALS else "bad_answer",
                      found=word(answer.get("found_version")), expected=expected)

    def status(self) -> tuple[str, dict]:
        cfg = self.cfg
        self.pi = pi_version(cfg)
        words: dict[str, Any] = {"helper": NAME, "protocol": PROTOCOL, "uid": cfg.uid, "pi": self.pi,
                                 "git": git_version(cfg), "branch": "on" if cfg.branch_enabled else "off",
                                 "tokens_last_hour": self.ceiling.used(),
                                 "tokens_per_hour": cfg.tokens_per_hour}
        bridge_slots: dict[str, str] = {}
        words["bridge"] = self._bridge_words(bridge_slots) if self.bridge else {"state": "not_configured"}
        words["slots"] = {slot: {"pi": pi_check_words(cfg, slot), "bridge": bridge_slots.get(slot, "unknown")}
                          for slot in cfg.allowed_slots}
        return "ok " + json.dumps(words, sort_keys=True), {"result": "ok"}

    def _bridge_words(self, slot_words: dict[str, str]) -> dict:
        assert self.bridge is not None
        out: dict[str, Any] = {"expected": self.bridge.bcfg.sdk_version}
        try:
            answer = self.bridge.request("status", "", min(20.0, self.cfg.token_timeout_s))
        except BridgeTimeout:
            return {**out, "state": "no_answer"}
        except BridgeRefused as exc:
            out.update({"state": "refused", "why": word(exc.code)})
            if exc.hello:
                out["found"] = word(exc.hello.get("version"))
            return out
        hello = self.bridge.hello
        state = word(answer.get("state"))
        out.update({"state": state, "package": package_word(hello.get("package")),
                    "version": word(hello.get("version")), "ai_package": package_word(hello.get("ai_package")),
                    "ai_version": word(hello.get("ai_version")), "node": word(hello.get("node"))})
        if state != "ready":
            out["found"] = word(answer.get("found_version"))
        slots = answer.get("slots")
        slots = slots if isinstance(slots, dict) else {}
        for slot in self.cfg.allowed_slots:
            text = slots.get(slot)
            parts = [w for w in text.split(" ") if WORD_RE.match(w)][:4] if isinstance(text, str) else []
            slot_words[slot] = state if state != "ready" else (" ".join(parts) or "unknown")
        return out


# --- serve, check, ask -----------------------------------------------------------------


class StartError(Exception):
    pass


def socket_dir_problem(path: str) -> str | None:
    folder = os.path.dirname(path)
    try:
        st = os.lstat(folder)
    except OSError:
        return f"the socket folder {folder} does not exist"
    if not stat.S_ISDIR(st.st_mode):
        return f"the socket folder {folder} is not a folder"
    if st.st_uid != os.getuid():
        return f"the socket folder {folder} does not belong to this user"
    if st.st_mode & 0o077:
        return f"the socket folder {folder} must be mode 0700 (it is {stat.S_IMODE(st.st_mode):04o})"
    return None


def bind_socket(path: str) -> socket.socket:
    if os.path.lexists(path):
        if not stat.S_ISSOCK(os.lstat(path).st_mode):
            raise StartError(f"{path} exists and is not a socket")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(2)
        try:
            probe.connect(path)
        except (ConnectionRefusedError, FileNotFoundError):
            os.unlink(path)  # a stale socket, left by a helper that died
        except OSError:
            raise StartError(f"{path} could not be checked") from None
        else:
            raise StartError(f"another helper is serving {path}")
        finally:
            probe.close()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        listener.bind(path)
    finally:
        os.umask(old)
    os.chmod(path, 0o600)
    listener.listen(16)
    listener.settimeout(0.5)
    return listener


def serve(config_path: str) -> int:
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        say("refused to start: " + "; ".join(exc.problems))
        return 2
    problem = socket_dir_problem(cfg.socket)
    if problem:
        say(f"refused to start: {problem}")
        return 2
    helper = Helper(cfg)
    helper.pi = pi_version(cfg)
    if helper.bridge is not None:
        try:
            helper.bridge.start()
        except BridgeRefused as exc:
            say(f"refused to start: {start_refusal(cfg, exc)}; the bridge stopped before reading any login")
            return 2
    try:
        listener = bind_socket(cfg.socket)
    except (StartError, OSError) as exc:
        if helper.bridge is not None:
            helper.bridge.stop_all()
        say(f"refused to start: {exc if isinstance(exc, StartError) else 'the socket could not be bound'}")
        return 2
    stopping: list[int] = []
    signal.signal(signal.SIGTERM, lambda signum, _frame: stopping.append(signum))
    signal.signal(signal.SIGINT, lambda signum, _frame: stopping.append(signum))
    inode = os.stat(cfg.socket).st_ino
    say(f"serving {cfg.socket} for uid {cfg.uid}: pi {helper.pi}, sdk "
        f"{cfg.bridge.sdk_package + ' ' + helper.sdk_word() if cfg.bridge else 'none'}, slots "
        f"{','.join(cfg.allowed_slots) or '-'}, branch {'on' if cfg.branch_enabled else 'off'}, "
        f"ceiling {cfg.tokens_per_hour}/h")
    try:
        while not stopping:
            try:
                conn, _ = listener.accept()
            except (TimeoutError, InterruptedError):
                continue
            with conn:
                try:
                    helper.handle(conn)
                except Exception as exc:  # one bad request never stops the helper
                    log(verb="-", result="error", why=type(exc).__name__)
    finally:
        listener.close()
        try:
            if os.stat(cfg.socket).st_ino == inode:
                os.unlink(cfg.socket)
        except OSError:
            pass
        if helper.bridge is not None:
            helper.bridge.stop_all()
        say("stopped")
    return 0


def check_config(config_path: str) -> int:
    """Check the config and the bridge's Pi SDK (the start check), without serving."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print(json.dumps({"ok": False, "problems": exc.problems}, indent=2))
        return 1
    report: dict[str, Any] = {"ok": True, "socket": cfg.socket,
                              "socket_folder": socket_dir_problem(cfg.socket) or "ok",
                              "pi": pi_version(cfg), "git": git_version(cfg),
                              "slots": list(cfg.allowed_slots),
                              "branch": "on" if cfg.branch_enabled else "off",
                              "tokens_per_hour": cfg.tokens_per_hour}
    if report["socket_folder"] != "ok":
        report["ok"] = False
    if cfg.bridge is None:
        report["bridge"] = {"state": "not_configured"}
    else:
        bridge = Bridge(cfg)
        try:
            hello = bridge.start()
            report["bridge"] = {"state": "ready", "package": package_word(hello.get("package")),
                                "version": word(hello.get("version")),
                                "ai_package": package_word(hello.get("ai_package")),
                                "ai_version": word(hello.get("ai_version")), "node": word(hello.get("node"))}
        except BridgeRefused as exc:
            report["ok"] = False
            report["bridge"] = {"state": "refused", "why": start_refusal(cfg, exc)}
        finally:
            bridge.stop_all()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


def ask(socket_path: str, request: str, timeout: float = 60.0) -> str:
    """Send one request line to a helper; its answer line."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(socket_path)
        conn.sendall((request + "\n").encode())
        conn.shutdown(socket.SHUT_WR)
        data = b""
        while b"\n" not in data and len(data) < 1 << 20:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
    return data.split(b"\n", 1)[0].decode("utf-8", "replace")


# --- stubs for the selftest and the tests ------------------------------------------------

STUB_SDK_INDEX = r"""// A stub of the Pi SDK for temper-pi-host's selftest and tests: no network, no real login.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../../../../", import.meta.url));
const note = (event) => fs.appendFileSync(path.join(ROOT, "stub-events.log"), event + "\n");
const control = () => {
  try { return JSON.parse(fs.readFileSync(path.join(ROOT, "stub-control.json"), "utf8")); } catch { return {}; }
};
const readAuth = (file) => {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return {}; }
};
note("imported");

export const VERSION = __VERSION__;

export function readStoredCredential(providerId, authPath) {
  note("read-stored " + providerId);
  return readAuth(authPath)[providerId];
}

function bumpVersionOnDisk() {
  const file = fileURLToPath(new URL("../package.json", import.meta.url));
  const pkg = JSON.parse(fs.readFileSync(file, "utf8"));
  pkg.version = pkg.version + "-bumped";
  fs.writeFileSync(file, JSON.stringify(pkg));
}

export class ModelRuntime {
  static async create(options) {
    note("runtime-created");
    return new ModelRuntime(options);
  }
  constructor(options) {
    this.authPath = options.authPath;
    this.providers = new Map();
  }
  registerProvider(id, config) {
    if (typeof config?.oauth?.refreshToken !== "function") throw new Error("no oauth flow");
    note("register " + id);
    this.providers.set(id, config);
  }
  getProvider(id) {
    return this.providers.get(id);
  }
  async listCredentials() {
    note("list-credentials");
    return Object.entries(readAuth(this.authPath)).map(([providerId, c]) => ({ providerId, type: c?.type }));
  }
  async getAuth(id, options = {}) {
    note("get-auth " + id);
    const provider = this.providers.get(id);
    if (!provider) throw new Error("Unknown provider " + id);
    const stored = readAuth(this.authPath)[id];
    if (!stored || stored.type !== "oauth") return undefined;
    const minimum = Math.max(5 * 60_000, options.minOAuthValidityMs ?? 0);
    let current = stored;
    if (Date.now() + minimum >= stored.expires) {
      if (control().refresh === "bump-before-refresh") bumpVersionOnDisk();
      try {
        current = { ...(await provider.oauth.refreshToken(stored, options.signal)), type: "oauth" };
      } catch (error) {
        throw new Error("OAuth refresh failed for " + id, { cause: error });
      }
      const data = readAuth(this.authPath);
      data[id] = current;
      fs.writeFileSync(this.authPath, JSON.stringify(data, null, 2), { mode: 0o600 });
      note("write-auth " + id);
      if (Date.now() + minimum >= current.expires) throw new Error("OAuth refresh returned a token that expires too soon");
    }
    return { auth: { apiKey: provider.oauth.getApiKey(current) }, source: "OAuth" };
  }
}
"""

STUB_AI_ALL = r"""// A stub of the Pi SDK's providers for temper-pi-host's selftest and tests.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../../../../../", import.meta.url));
const BASE = __BASE__;
const control = () => {
  try { return JSON.parse(fs.readFileSync(path.join(ROOT, "stub-control.json"), "utf8")); } catch { return {}; }
};

export function builtinProviders() {
  return [{ id: BASE, name: "Stub", baseUrl: "https://stub.invalid", auth: { oauth: {
    name: "Stub login",
    isSubscription: true,
    login: async () => { throw new Error("the stub has no login"); },
    refresh: async (credential, signal) => {
      fs.appendFileSync(path.join(ROOT, "refresh-calls.log"), "refresh\n");
      const c = control();
      if (c.refresh === "fail") throw new Error("stub refresh failed: body=STUB-SECRET-BODY");
      if (c.refresh === "hang") await new Promise(() => {});
      if (c.delay_ms) await new Promise((resolve) => setTimeout(resolve, c.delay_ms));
      return { type: "oauth", access: c.next_access ?? "stub-access-next", refresh: c.next_refresh ?? "stub-refresh-next",
               expires: Date.now() + (c.expires_in_s ?? 3600) * 1000 };
    },
  } } }];
}

export function getBuiltinModels(provider) {
  return provider === BASE ? [{ id: "stub-model", provider: BASE, api: "stub-messages", baseUrl: "https://stub.invalid" }] : [];
}
"""

STUB_PI = r'''"""A stub of the host pi CLI for temper-pi-host's selftest and tests: it answers --version
and the read-only auth check, and records any other call as forbidden (no login, no model)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(os.path.join(HERE, "stub-pi-calls.log"), "a") as calls:
    calls.write(" ".join(args) + "\n")
if args == ["--version"]:
    print(__VERSION__)
    sys.exit(0)
if args[:2] == ["auth", "check"] and "--json" in args and "--no-refresh" in args and "--provider" in args:
    provider = args[args.index("--provider") + 1]
    print(json.dumps({"status": "not_ready", "provider": provider, "reason": "provider_not_found"}))
    sys.exit(1)
with open(os.path.join(HERE, "stub-pi-forbidden.log"), "a") as forbidden:
    forbidden.write(" ".join(args) + "\n")
sys.exit(99)
'''


def sdk_package_dir(sdk_root: Path, package: str = DEFAULT_SDK_PACKAGE) -> Path:
    return sdk_root.joinpath("node_modules", *package.split("/"))


def write_stub_sdk(sdk_root: Path, *, base: str, version: str, ai_version: str | None = None) -> None:
    """A stub Pi SDK (the pinned package and its providers package) under ``sdk_root``."""
    sdk = sdk_package_dir(sdk_root)
    ai = sdk_package_dir(sdk_root, AI_PACKAGE)
    (sdk / "dist").mkdir(parents=True, exist_ok=True)
    (ai / "dist" / "providers").mkdir(parents=True, exist_ok=True)
    (sdk / "package.json").write_text(json.dumps({
        "name": DEFAULT_SDK_PACKAGE, "version": version, "type": "module",
        "exports": {".": {"import": "./dist/index.js"}},
        "dependencies": {AI_PACKAGE: ai_version or version}}))
    (sdk / "dist" / "index.js").write_text(STUB_SDK_INDEX.replace("__VERSION__", json.dumps(version)))
    (ai / "package.json").write_text(json.dumps({
        "name": AI_PACKAGE, "version": ai_version or version, "type": "module",
        "exports": {".": {"import": "./dist/index.js"}, "./providers/*": {"import": "./dist/providers/*.js"}}}))
    (ai / "dist" / "index.js").write_text("export {};\n")
    (ai / "dist" / "providers" / "all.js").write_text(STUB_AI_ALL.replace("__BASE__", json.dumps(base)))


def set_stub_version(sdk_root: Path, version: str, package: str = DEFAULT_SDK_PACKAGE) -> None:
    """Change a stub package's version on disk (what an SDK upgrade under a running helper does)."""
    file = sdk_package_dir(sdk_root, package) / "package.json"
    data = json.loads(file.read_text())
    data["version"] = version
    file.write_text(json.dumps(data))


def write_stub_pi(path: Path, version: str) -> None:
    path.write_text(STUB_PI.replace("__VERSION__", json.dumps(version)))


# --- selftest --------------------------------------------------------------------------

SELFTEST_BASE = "selftest"
SELFTEST_SLOT = "selftest-2"
SELFTEST_SDK_VERSION = "0.0.0-selftest"
SELFTEST_PI_VERSION = "0.0.0-stub"


class Selftest:
    """An isolated run of this script: a temp folder, a stub Pi CLI, the real bridge loading
    a stub Pi SDK, a canary login in a temp auth.json.  No real login, no model call."""

    def __init__(self, bridge: str, node: str, journald: bool):
        self.bridge = os.path.abspath(bridge)
        self.node = shutil.which(node) or node
        self.journald = journald
        self.results: list[bool] = []
        self.tmp = Path(tempfile.mkdtemp(prefix="tph-"))  # mode 0700, short enough for a socket
        self.tag = f"{NAME}-selftest-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.canary = "SELFTEST-CANARY-" + uuid.uuid4().hex
        self.canary_refresh = "SELFTEST-CANARY-R-" + uuid.uuid4().hex
        self.sdk_root = self.tmp / "sdk"
        self.agent = self.tmp / "agent"
        self.auth = self.agent / "auth.json"
        self.log_file = self.tmp / "helper.log"

    def check(self, ok: bool, text: str) -> bool:
        print(("PASS " if ok else "FAIL ") + text, flush=True)
        self.results.append(bool(ok))
        return bool(ok)

    def setup(self) -> dict:
        (self.tmp / "sock").mkdir(mode=0o700)
        (self.tmp / "state").mkdir(mode=0o700)
        self.agent.mkdir(mode=0o700)
        write_stub_sdk(self.sdk_root, base=SELFTEST_BASE, version=SELFTEST_SDK_VERSION)
        (self.agent / "multi-pass.json").write_text(json.dumps(
            {"subscriptions": [{"provider": SELFTEST_BASE, "index": 2}]}))
        expires = int(time.time() * 1000) + 2 * 3600 * 1000
        self.auth.write_text(json.dumps({SELFTEST_SLOT: {"type": "oauth", "access": self.canary,
                                                         "refresh": self.canary_refresh, "expires": expires}}))
        self.auth.chmod(0o600)
        write_stub_pi(self.tmp / "stub_pi.py", SELFTEST_PI_VERSION)
        path = [d for d in os.environ.get("PATH", "").split(":") if clean_abs_path(d)] or ["/usr/bin", "/bin"]
        return {"socket": str(self.tmp / "sock" / "helper.sock"), "uid": os.getuid(),
                "pi_state_root": str(self.tmp / "state"), "home": str(self.tmp),
                "pi_agent_dir": str(self.agent), "path": path,
                "pi_cli": [sys.executable, str(self.tmp / "stub_pi.py")],
                "base_provider": SELFTEST_BASE, "allowed_slots": [SELFTEST_SLOT],
                "bridge": {"node": self.node, "script": self.bridge, "sdk_root": str(self.sdk_root),
                           "sdk_version": SELFTEST_SDK_VERSION, "ai_version": SELFTEST_SDK_VERSION},
                "branch_enabled": False, "tokens_per_hour": 120, "token_timeout_s": 30}

    def start(self, config: dict, name: str) -> subprocess.Popen[bytes]:
        cfg_file = self.tmp / f"{name}.json"
        cfg_file.write_text(json.dumps(config, indent=2))
        argv = [sys.executable, os.path.abspath(__file__), "serve", "--config", str(cfg_file)]
        if self.journald:
            argv = ["systemd-cat", "-t", self.tag, "--", *argv]
        with open(self.log_file, "ab") as out:
            return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=out)

    def helper_log(self) -> str:
        if not self.journald:
            return self.log_file.read_text(errors="replace")
        deadline = time.monotonic() + 10
        out = ""
        while time.monotonic() < deadline:
            _, out = run(["journalctl", "--user", "-t", self.tag, "-o", "cat", "--no-pager"],
                         env=dict(os.environ), timeout=20)
            if "stopped" in out or " refused to start" in out:
                break
            time.sleep(0.5)
        return out

    def auth_state(self) -> tuple[bytes, int]:
        return self.auth.read_bytes(), self.auth.stat().st_mtime_ns

    def events(self) -> list[str]:
        try:
            return (self.sdk_root / "stub-events.log").read_text().splitlines()
        except OSError:
            return []

    def run(self) -> int:
        try:
            self.phases()
        finally:
            passed = bool(self.results) and all(self.results)
            print(f"selftest: {'PASS' if passed else 'FAIL'} ({sum(self.results)}/{len(self.results)} checks)")
            if passed:
                shutil.rmtree(self.tmp, ignore_errors=True)
            else:
                print(f"selftest: kept {self.tmp} (stub data only)")
        return 0 if passed else 1

    def phases(self) -> None:
        config = self.setup()
        sock = config["socket"]
        before = self.auth_state()
        proc = self.start(config, "config")
        deadline = time.monotonic() + 30
        while not os.path.exists(sock) and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if not self.check(os.path.exists(sock), f"socket: the helper serves {sock}"):
            proc.terminate()
            proc.wait(timeout=30)
            print(self.helper_log())
            return
        requests = 0

        def asked(line: str) -> str:
            nonlocal requests
            requests += 1
            return ask(sock, line)

        answer = asked("status")
        words = _json_object(answer[3:]) if answer.startswith("ok ") else None
        self.check(words is not None, "status: the socket answers 'ok <json>'")
        words = words or {}
        bridge = words.get("bridge") or {}
        slot = (words.get("slots") or {}).get(SELFTEST_SLOT) or {}
        self.check(words.get("pi") == SELFTEST_PI_VERSION, f"status: host pi version {SELFTEST_PI_VERSION} (stub CLI)")
        self.check(bridge.get("state") == "ready" and bridge.get("package") == DEFAULT_SDK_PACKAGE
                   and bridge.get("version") == SELFTEST_SDK_VERSION,
                   f"status: the bridge loaded {DEFAULT_SDK_PACKAGE} {SELFTEST_SDK_VERSION} (stub SDK)")
        self.check(slot.get("pi") == "not_ready provider_not_found" and slot.get("bridge") == "registered login_ready",
                   "status: slot words from the stock CLI and from the bridge")
        self.check(self.canary not in answer and self.canary_refresh not in answer,
                   "status: no login text in the answer")
        self.check(asked(f"token {SELFTEST_SLOT}") == "ok " + self.canary,
                   "token: the stub login comes back on the socket only (not printed here)")
        self.check(asked(f"token {SELFTEST_BASE}").startswith(f"denied slot {SELFTEST_BASE} is account 1"),
                   "token: the base slot (account 1) is refused")

        mark = len(self.events())
        set_stub_version(self.sdk_root, SELFTEST_SDK_VERSION + "-changed")
        answer = asked(f"token {SELFTEST_SLOT}")
        self.check(answer.startswith(f"denied slot {SELFTEST_SLOT}: the Pi SDK on disk changed"),
                   "version check per request: an SDK change on disk refuses the next token")
        answer = asked("status")
        words = _json_object(answer[3:]) if answer.startswith("ok ") else {}
        self.check(((words or {}).get("bridge") or {}).get("state") == "sdk_changed",
                   "version check per request: status says sdk_changed")
        touched = [e for e in self.events()[mark:] if not e.startswith("register")]
        self.check(not touched and self.auth_state() == before,
                   "version check per request: auth.json not read or written (bytes and mtime unchanged)")
        set_stub_version(self.sdk_root, SELFTEST_SDK_VERSION)

        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=60)
        self.check(code == 0 and not os.path.exists(sock), "stop: SIGTERM stops the helper and removes its socket")
        text = self.helper_log()
        lines = [ln for ln in text.splitlines() if " verb=" in ln]
        self.check(len(lines) == requests, f"log: one line per request ({len(lines)} for {requests})")
        self.check(any(" verb=status result=ok " in ln for ln in lines),
                   "journald: the status request's line reached the journal" if self.journald
                   else "log: the status request's line is there (add --journald to check the journal)")
        self.check(self.canary not in text and self.canary_refresh not in text, "log: no login text")

        mark = len(self.events())
        wrong = json.loads(json.dumps(config))
        wrong["socket"] = str(self.tmp / "sock" / "wrong.sock")
        wrong["bridge"]["sdk_version"] = "9.9.9-expected"
        proc = self.start(wrong, "wrong")
        try:
            code = proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = -1
        text = self.helper_log()
        self.check(code == 2 and not os.path.exists(wrong["socket"]),
                   "version check at start: a different expected version refuses startup (exit 2, no socket)")
        self.check("refused to start: the Pi SDK the bridge found is" in text and "9.9.9-expected" in text,
                   "version check at start: the refusal names the found and the expected version")
        self.check("imported" not in self.events()[mark:] and self.auth_state() == before,
                   "version check at start: the SDK was not loaded and auth.json is unchanged")

        self.check(not (self.tmp / "stub-pi-forbidden.log").exists(),
                   "stub pi CLI: no login, refresh or model call was asked of it")
        leaks = [str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*")
                 if p.is_file() and p != self.auth and self.canary.encode() in p.read_bytes()]
        self.check(not leaks, "no file but the temp auth.json holds the canary login" + (f" ({leaks})" if leaks else ""))


# --- main ------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="temper_pi_host.py",
                                     description="temper-pi-host: the host helper for Temper's Pi team members")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("serve", help="serve the socket named in the config")
    p.add_argument("--config", required=True)
    p = sub.add_parser("check", help="check the config and the bridge's Pi SDK, without serving")
    p.add_argument("--config", required=True)
    p = sub.add_parser("ask", help="ask a running helper for its status")
    p.add_argument("--socket", required=True)
    p.add_argument("request", choices=["status"])
    p = sub.add_parser("selftest", help="an isolated run with a stub Pi CLI and a stub Pi SDK")
    p.add_argument("--bridge", default=str(Path(__file__).resolve().with_name("temper_pi_host_bridge.mjs")))
    p.add_argument("--node", default="node")
    p.add_argument("--journald", action="store_true", help="run the helper under systemd-cat and read the journal")
    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve(args.config)
    if args.command == "check":
        return check_config(args.config)
    if args.command == "ask":
        try:
            answer = ask(args.socket, args.request)
        except OSError as exc:
            print(f"no answer from {args.socket} ({type(exc).__name__})")
            return 1
        print(answer)
        return 0 if answer.startswith("ok") else 1
    return Selftest(args.bridge, args.node, args.journald).run()


if __name__ == "__main__":
    sys.exit(main())
