"""Shared pieces for temper-pi-host's tests.

The helper script (scripts/pi_host/temper_pi_host.py) is loaded as a module.  Its own stub
writers make a stub Pi CLI and a stub Pi SDK, so the real auth bridge runs against a fake
SDK over a temp auth.json: no real login, no network, no model call.  Slot names are
synthetic (base ``acme``), never a real account's."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "pi_host" / "temper_pi_host.py"
BRIDGE = SCRIPT.with_name("temper_pi_host_bridge.mjs")
EXAMPLE = SCRIPT.with_name("temper-pi-host.example.json")
HERE = Path(__file__).resolve().parent
NODE = shutil.which("node")


def _load() -> Any:
    name = "temper_pi_host"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up while the file loads
    spec.loader.exec_module(module)
    return module


tph = _load()

BASE = "acme"
SLOT = "acme-2"
OTHER = "acme-3"
SDK_VERSION = "7.7.7-test"
PI_VERSION = "7.7.7-pi"
HOUR_MS = 3600 * 1000


def short_tmp(prefix: str = "tph") -> Path:
    """A private temp folder short enough for a Unix socket path."""
    return Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir="/tmp"))


def now_ms() -> int:
    return int(time.time() * 1000)


def login(access: str, refresh: str, expires_in_ms: int) -> dict:
    return {"type": "oauth", "access": access, "refresh": refresh, "expires": now_ms() + expires_in_ms}


class Host:
    """A temp host: socket and state folders, a Pi agent folder (auth.json, multi-pass.json),
    a stub Pi CLI and a stub Pi SDK.  ``config()`` is a helper config over them."""

    def __init__(self, root: Path | None = None):
        self.root = root or short_tmp()
        self.sock_dir = self.root / "sock"
        self.state = self.root / "state"
        self.agent = self.root / "agent"
        self.sdk_root = self.root / "sdk"
        self.auth = self.agent / "auth.json"
        self.stub_pi = self.root / "stub_pi.py"
        for folder in (self.sock_dir, self.state, self.agent):
            folder.mkdir(mode=0o700)
        tph.write_stub_sdk(self.sdk_root, base=BASE, version=SDK_VERSION)
        tph.write_stub_pi(self.stub_pi, PI_VERSION)
        self.register(2, 3)
        self.canary = "CANARY-ACCESS-" + os.urandom(8).hex()
        self.canary_refresh = "CANARY-REFRESH-" + os.urandom(8).hex()
        self.write_auth({SLOT: login(self.canary, self.canary_refresh, 2 * HOUR_MS)})

    # --- the Pi agent folder ---

    def register(self, *indexes: int) -> None:
        subs = [{"provider": BASE, "index": i} for i in indexes]
        (self.agent / "multi-pass.json").write_text(json.dumps({"subscriptions": subs}))

    def write_auth(self, data: dict) -> None:
        self.auth.write_text(json.dumps(data, indent=2))
        self.auth.chmod(0o600)

    def read_auth(self) -> dict:
        return json.loads(self.auth.read_text())

    def auth_state(self) -> tuple[bytes, int]:
        return self.auth.read_bytes(), self.auth.stat().st_mtime_ns

    # --- the stub SDK's records ---

    def control(self, **values: Any) -> None:
        (self.sdk_root / "stub-control.json").write_text(json.dumps(values))

    def events(self) -> list[str]:
        try:
            return (self.sdk_root / "stub-events.log").read_text().splitlines()
        except OSError:
            return []

    def refreshes(self) -> int:
        try:
            return len((self.sdk_root / "refresh-calls.log").read_text().splitlines())
        except OSError:
            return 0

    def forbidden_pi_calls(self) -> list[str]:
        try:
            return (self.root / "stub-pi-forbidden.log").read_text().splitlines()
        except OSError:
            return []

    # --- configs ---

    def config(self, **over: Any) -> dict:
        path = [d for d in os.environ.get("PATH", "").split(":") if tph.clean_abs_path(d)] or ["/usr/bin", "/bin"]
        raw: dict[str, Any] = {
            "socket": str(self.sock_dir / "h.sock"), "uid": os.getuid(),
            "pi_state_root": str(self.state), "home": str(self.root), "pi_agent_dir": str(self.agent),
            "path": path, "pi_cli": [sys.executable, str(self.stub_pi)],
            "base_provider": BASE, "allowed_slots": [SLOT, OTHER],
            "bridge": {"node": NODE or "node", "script": str(BRIDGE), "sdk_root": str(self.sdk_root),
                       "sdk_version": SDK_VERSION, "ai_version": SDK_VERSION,
                       "start_timeout_s": 20, "stop_grace_s": 10},
            "project_roots": [], "branch_enabled": False, "tokens_per_hour": 120, "token_timeout_s": 10,
        }
        raw.update(over)
        return raw

    def cfg(self, **over: Any) -> Any:
        return tph.parse_config(self.config(**over))

    def write_config(self, raw: dict, name: str = "config.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(raw, indent=2))
        return path

    def files_holding(self, text: str, *, skip: tuple[Path, ...] = ()) -> list[str]:
        """Every file under the temp host holding ``text`` (but those in ``skip``)."""
        needle = text.encode()
        return [str(p.relative_to(self.root)) for p in self.root.rglob("*")
                if p.is_file() and p not in skip and needle in p.read_bytes()]

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def ask_in_process(helper: Any, line: str) -> str:
    """One request to an in-process helper over a socket pair (its peer is this process)."""
    ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with ours, theirs:
        theirs.sendall((line + "\n").encode())
        theirs.shutdown(socket.SHUT_WR)
        helper.handle(ours)
        ours.shutdown(socket.SHUT_WR)
        theirs.settimeout(10)
        data = b""
        while True:
            chunk = theirs.recv(65536)
            if not chunk:
                break
            data += chunk
    return data.decode().split("\n", 1)[0]


class Served:
    """The helper run as its own process (``serve --config``), as the unit runs it."""

    def __init__(self, host: Host, raw: dict, name: str = "served"):
        self.host = host
        self.raw = raw
        self.socket = raw["socket"]
        self.log_file = host.root / f"{name}.log"
        config = host.write_config(raw, f"{name}.json")
        with open(self.log_file, "ab") as out:
            self.proc = subprocess.Popen([sys.executable, str(SCRIPT), "serve", "--config", str(config)],
                                         stdin=subprocess.DEVNULL, stdout=out, stderr=out)

    def wait_ready(self, timeout: float = 30) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(self.socket) and "serving" in self.log():
                return True
            if self.proc.poll() is not None:
                return False
            time.sleep(0.05)
        return False

    def ask(self, line: str) -> str:
        return tph.ask(self.socket, line, timeout=30)

    def log(self) -> str:
        try:
            return self.log_file.read_text(errors="replace")
        except OSError:
            return ""

    def stop(self) -> int:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
        try:
            return self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait(timeout=10)


# --- throwaway git repos ---------------------------------------------------------------

GIT_ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.devnull, "LC_ALL": "C",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@localhost",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@localhost"}


def git(*args: str, cwd: Path | None = None) -> str:
    done = subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def make_source(folder: Path) -> str:
    """A source repo with one commit; its HEAD commit."""
    folder.mkdir(parents=True)
    git("init", "-q", str(folder))
    (folder / "README.md").write_text("source\n")
    git("-C", str(folder), "add", "README.md")
    git("-C", str(folder), "commit", "-q", "-m", "start")
    return git("-C", str(folder), "rev-parse", "HEAD")


def make_leader(state_root: Path, source: Path, *, run: str = "run1", team: str = "team1",
                member: str = "lead", extra_bytes: int = 0) -> tuple[Path, str]:
    """A team member's git copy as Temper makes one (``<state>/<run>/<team>/git/<name>.git``,
    work tree beside it), with one new commit on top of the source; (git dir, commit)."""
    team_root = state_root / run / team
    git_dir = team_root / "git" / f"{member}.git"
    work = team_root / "members" / member / "workspace"
    work.mkdir(parents=True)
    git_dir.parent.mkdir(parents=True, exist_ok=True)
    gd = ["--git-dir", str(git_dir), "--work-tree", str(work)]
    git("--git-dir", str(git_dir), "init", "-q")
    git(*gd, "fetch", "-q", str(source), "HEAD")
    git(*gd, "reset", "-q", "--hard", "FETCH_HEAD")
    (work / "change.txt").write_text("a change by the team\n")
    if extra_bytes:
        (work / "big.bin").write_bytes(os.urandom(extra_bytes))
    git(*gd, "add", "-A")
    git(*gd, "commit", "-q", "-m", "the team's change")
    return git_dir, git("--git-dir", str(git_dir), "rev-parse", "HEAD")


def branch_of(repo: Path, trial_id: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/heads/team/{trial_id}"],
                          env=GIT_ENV, capture_output=True, text=True, check=False)
    return done.stdout.strip() if done.returncode == 0 else ""
