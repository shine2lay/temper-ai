"""The Pi worker box: one sealed container per turn, started and torn down by the host.

What the box allows (and what L1 proved live on the same runtime):

* the container runs the pinned Pi runtime (mounted read-only) as the host user, with
  ``--network none``, a read-only root, every capability dropped, no new privileges, a pid,
  memory and CPU limit, no logging driver and docker's init;
* its only way out is an in-container relay on 127.0.0.1:3128 that pipes bytes to the
  host's egress proxy over a bind-mounted Unix socket; the proxy allows ``CONNECT`` to the
  route's provider host on port 443 and answers 403 to everything else;
* it holds no credential: Pi's ``apiKey`` command asks the host over a second Unix socket;
  the host hands over the token only while the turn's allowance lasts, after adding it to
  the turn's redactor, and stores nothing. With ``host_helper_socket`` set the token comes
  from the host helper's ``token`` verb for the run's pinned account slot (ADR-M4-15,
  :mod:`temper_ai.pi_agent.host_helper`); otherwise from the host Pi installation
  (``pi auth print-bearer-token --provider P --min-expiry 30m``). Either way the login and
  its refresh stay with the host's Pi;
* the host's own Pi settings, logins and memory are never mounted. The worker gets a
  generated agent folder, a private copy of its role (copied once per participant) and its
  participant folder (``/w``), which keeps the Pi session file between turns;
* Pi's ``grep`` and ``find`` run the static ``rg`` and ``fd`` pinned at the runtime folder's top
  level (``/pi-runtime``, first on the box ``PATH``; :mod:`temper_ai.pi_agent.search_tools`).
  The host checks their digests before every start, and refuses a worker given ``grep`` or
  ``find`` when the box config doesn't pin them, before any docker call.

Nothing here logs request bodies, prompts, tokens or captured process output.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from temper_ai.pi_agent import host_helper
from temper_ai.pi_agent.rpc import Rpc
from temper_ai.pi_agent.search_tools import PINS as SEARCH_PINS
from temper_ai.pi_agent.search_tools import search_tool_problems

ASSETS = Path(__file__).parent / "assets"
PROBE_DIR = ASSETS / "temper-box"
CONFIG_ENV = "TEMPER_PI_BOX_CONFIG"
CONTAINER_PYTHON = "/usr/local/bin/python3"
WORKDIR = "/w/workspace"
STATE_FILE = "/w/state/box-state.json"
BUDGET_SLACK = 2
FAULTS = ("deny_handoff", "kill_after_prompt")
ROLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
#: A Unix socket path's limit, kept as the host helper keeps it (ADR-M4-02).
HELPER_SOCKET_LIMIT = 100
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
ESTABLISHED = b"HTTP/1.1 200 Connection Established\r\n\r\n"
#: Pi settings for every worker: no telemetry, no packages, Pi's own retries and compaction off
#: (Temper decides what happens after a failure), the SSE transport L1 proved.
SETTINGS = {
    "enableInstallTelemetry": False, "quietStartup": True, "packages": [],
    "cacheWarming": "off", "retry": {"enabled": False, "provider": {"maxRetries": 0}},
    "compaction": {"enabled": False}, "transport": "sse",
}
DOCKER_ENV_KEYS = ("HOME", "LANG")


class BoxError(Exception):
    """A box failure with a static code and a plain message (never captured output)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Route:
    provider: str
    host: str
    #: A model catalog file copied into the agent folder as models-store.json (codex route).
    catalog: str | None = None
    #: A sealed login extension folder (anthropic route), mounted read-only at /ext/auth.
    extension: str | None = None
    extension_entry: str | None = None


@dataclass(frozen=True)
class AddOnPin:
    """A pinned copy of an allowed add-on: its folder, its entry file and the digest the folder
    must have (:func:`tree_sha256`). Never the owner's live ``~/.pi/agent``."""

    dir: str
    entry: str
    sha256: str


@dataclass(frozen=True)
class SearchToolPin:
    """A static search binary at the runtime folder's top level (``rg`` for Pi's grep, ``fd`` for
    its find): its version and the digest the file must have
    (:mod:`temper_ai.pi_agent.search_tools`)."""

    version: str
    sha256: str


@dataclass(frozen=True)
class BoxConfig:
    """Where the worker's runtime, role definitions and state live. Read from the JSON file
    named by ``TEMPER_PI_BOX_CONFIG`` when a Pi step runs; never read with the step off."""

    image: str
    runtime_dir: str
    pi_version: str
    identity_extension: str
    identity_config: str
    identities_dir: str
    state_root: str
    routes: dict[str, Route]
    #: The host's node and Pi CLI, for the hand-off without a host helper (host-process
    #: instances, tests); not needed when ``host_helper_socket`` is set.
    host_node: str = ""
    host_pi: str = ""
    socket_root: str = ""
    #: Home of the account whose host Pi login the handoff asks (default: this process's).
    host_home: str = ""
    #: The host helper's socket (M4 ADR-M4-02/12/15). Set: a worker's login token comes from
    #: the helper's ``token`` verb for the run's pinned slot (``BoxSpec.slot``), and a done
    #: trial's branch is made by its ``branch`` verb. Empty: both by this process.
    host_helper_socket: str = ""
    #: ``live`` or ``rehearsal`` (egress goes to a local TLS stand-in, tokens are synthetic).
    mode: str = "live"
    rehearsal: dict | None = None
    memory: str = "4g"
    cpus: str = "4"
    pids: int = 512
    turn_timeout_s: float = 900.0
    model_calls_per_turn: int = 6
    #: Proof-harness failure injection only: ``deny_handoff`` or ``kill_after_prompt``.
    fault: str | None = None
    #: The add-ons a member may load, each from a pinned copy (name -> :class:`AddOnPin`).
    add_ons: dict[str, AddOnPin] = field(default_factory=dict)
    #: The search binaries pinned in ``runtime_dir`` (name -> :class:`SearchToolPin`), as
    #: ``scripts/pi_search_tools.py`` prints them. Without ``rg`` a worker can't have Pi's grep,
    #: without ``fd`` its find.
    search_tools: dict[str, SearchToolPin] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | None = None) -> BoxConfig:
        path = path or os.environ.get(CONFIG_ENV, "")
        if not path:
            raise BoxError("box_not_configured",
                           f"the Pi worker box is not configured (set {CONFIG_ENV})")
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            routes = {name: Route(**value) for name, value in raw.pop("routes").items()}
            add_ons = {name: AddOnPin(**value)
                       for name, value in (raw.pop("add_ons", None) or {}).items()}
            search_tools = {name: SearchToolPin(**value)
                            for name, value in (raw.pop("search_tools", None) or {}).items()}
            cfg = cls(routes=routes, add_ons=add_ons, search_tools=search_tools, **raw)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise BoxError("box_config_invalid",
                           f"the Pi worker box config could not be read: {type(exc).__name__}"
                           ) from None
        cfg.check()
        return cfg

    def check(self) -> None:
        problems = []
        if self.mode not in ("live", "rehearsal"):
            problems.append("mode must be live or rehearsal")
        if self.mode == "rehearsal" and not (self.rehearsal or {}).get("upstream_port"):
            problems.append("rehearsal needs upstream_port")
        if not IMAGE_RE.match(self.image):
            problems.append("image must be a sha256 image id")
        if self.fault not in (None, *FAULTS):
            problems.append("unknown fault")
        runtime = Path(self.runtime_dir)
        if not (runtime / "node").is_file() or not (runtime / CLI_REL).is_file():
            problems.append("runtime_dir lacks node or the Pi cli")
        elif installed_pi_version(runtime) != self.pi_version:
            problems.append("installed Pi version differs from pi_version")
        if not (Path(self.identity_extension) / "index.ts").is_file():
            problems.append("identity_extension lacks index.ts")
        if not (Path(self.identity_config) / "pi-identity.json").is_file():
            problems.append("identity_config lacks pi-identity.json")
        if not Path(self.identities_dir).is_dir():
            problems.append("identities_dir missing")
        if not self.routes:
            problems.append("no routes")
        if self.host_helper_socket:
            if not os.path.isabs(self.host_helper_socket) \
                    or len(self.host_helper_socket.encode()) >= HELPER_SOCKET_LIMIT:
                problems.append("host_helper_socket must be an absolute path under "
                                f"{HELPER_SOCKET_LIMIT} bytes")
        elif self.mode == "live" and not (self.host_node and self.host_pi):
            problems.append("host_node and host_pi are needed without host_helper_socket")
        problems += self._add_on_problems()
        problems += self.search_tool_pin_problems()
        if problems:
            raise BoxError("box_config_invalid", "Pi worker box config: " + "; ".join(problems))

    def search_tool_pin_problems(self) -> list[str]:
        """Each pinned search binary: a name Temper pins (``rg``, ``fd``), a version and a digest,
        and at ``runtime_dir/<name>`` a plain executable file (not a link) with exactly that
        digest. Read on the host when the config loads and again before every start."""
        problems = []
        runtime = Path(self.runtime_dir)
        for name, pin in sorted(self.search_tools.items()):
            if name not in SEARCH_PINS:
                problems.append(f"search tool {name[:40]!r} is not one Temper pins "
                                f"({', '.join(sorted(SEARCH_PINS))})")
                continue
            if not isinstance(pin.version, str) or not pin.version.strip() \
                    or not isinstance(pin.sha256, str) or not SHA256_RE.match(pin.sha256):
                problems.append(f"search tool {name}: needs a version and a sha256 digest")
                continue
            binary = runtime / name
            if binary.is_symlink() or not binary.is_file():
                problems.append(f"search tool {name}: runtime_dir has no {name} file (a link "
                                "doesn't count)")
            elif not os.access(binary, os.X_OK):
                problems.append(f"search tool {name}: {name} in runtime_dir is not executable")
            elif file_sha256(binary) != pin.sha256:
                problems.append(f"search tool {name}: pinned binary changed (digest differs)")
        return problems

    def _add_on_problems(self) -> list[str]:
        """Each pinned add-on copy: present, outside the owner's live Pi folder, unchanged."""
        problems = []
        live = [Path(home).expanduser().resolve() / ".pi" / "agent"
                for home in {str(Path.home()), self.host_home} if home]
        for name, pin in sorted(self.add_ons.items()):
            folder = Path(pin.dir)
            if not ROLE_RE.match(name):
                problems.append(f"add-on name {name[:40]!r} is not a plain name")
            elif not folder.is_dir() or not (folder / pin.entry).is_file() \
                    or ".." in Path(pin.entry).parts or Path(pin.entry).is_absolute():
                problems.append(f"add-on {name}: pinned copy or its entry file missing")
            elif any(folder.resolve().is_relative_to(root) for root in live):
                problems.append(f"add-on {name}: must be a pinned copy, not the owner's "
                                "live ~/.pi/agent")
            elif tree_sha256(folder) != pin.sha256:
                problems.append(f"add-on {name}: pinned copy changed (digest differs)")
        return problems

    @property
    def sockets(self) -> Path:
        return Path(self.socket_root or f"/run/user/{os.getuid()}/temper-pi")


CLI_REL = "pi/dist/bundle/cli.js"


def installed_pi_version(runtime_dir: Path) -> str | None:
    try:
        return json.loads((runtime_dir / "pi" / "package.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return None


def _owner_writable(root: Path) -> None:
    """Give the owner write on a copied tree's folders and read on its files. A pinned copy may
    be read only on disk (copytree keeps the modes); this copy must still take the runtime link
    and stay removable. The box sees it read only all the same: it is mounted read only."""
    for path in [root, *root.rglob("*")]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & 0o7777 | (0o700 if path.is_dir() else 0o600))


def tree_sha256(root: Path) -> str:
    """One digest over a folder's regular files (relative path + content), node_modules and
    symlinks excluded -- the digest pinned for an extension."""
    h = hashlib.sha256()
    root = Path(root)
    files = sorted(p for p in root.rglob("*")
                   if p.is_file() and not p.is_symlink() and "node_modules" not in p.parts)
    for p in files:
        h.update(p.relative_to(root).as_posix().encode() + b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def jwt_account_ids(token: str) -> list[str]:
    """Account ids inside a JWT-shaped token: redacted with the token itself."""
    parts = token.split(".")
    if len(parts) < 2:
        return []
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, UnicodeError):
        return []
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if "account_id" in str(key).lower() and isinstance(item, str) and len(item) >= 6:
                    found.append(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return found


# --- sessions (checked before every start: R1 K6) ----------------------------------------


def check_session(sessions_dir: Path, session_id: str, *, must_exist: bool) -> dict:
    """The participant's one Pi session file: private, matching, and not stopped mid-turn.

    Raises :class:`BoxError` when the folder holds anything else, the header does not match,
    or a session that must exist is missing. Pi reopens a session at its last entry, so the
    active branch runs from that entry up its parents. ``settled`` is False when the branch's
    last message is not a finished assistant message (a dangling tool call or an unanswered
    prompt); ``settle_point`` is then the branch's last entry before the unfinished part --
    where the owner's decision about the cut-off turn moves the branch back to."""
    files = sorted(p for p in sessions_dir.iterdir()) if sessions_dir.is_dir() else []
    mine = [p for p in files if p.is_file() and p.name.endswith(f"_{session_id}.jsonl")]
    if [p for p in files if p not in mine] or len(mine) > 1:
        raise BoxError("session_folder_not_private",
                       "the participant's session folder holds other files")
    if not mine:
        if must_exist:
            raise BoxError("session_missing", "the participant's Pi session file is missing")
        return {"exists": False, "settled": True, "messages": 0}
    lines = mine[0].read_text(encoding="utf-8").splitlines()
    try:
        entries = [json.loads(line) for line in lines if line.strip()]
    except ValueError:
        raise BoxError("session_unreadable", "the Pi session file is not valid JSON lines") from None
    header = entries[0] if entries else {}
    if header.get("type") != "session" or header.get("id") != session_id \
            or header.get("cwd") != WORKDIR:
        raise BoxError("session_mismatch", "the Pi session header does not match the participant")
    branch = _active_branch(entries[1:])
    msgs = [e.get("message") or {} for e in branch if e.get("type") == "message"]
    last = msgs[-1] if msgs else None
    settle_point = None
    pending = False
    for entry in branch:
        if entry.get("type") == "message":
            pending = not _finished(entry.get("message") or {})
            if not pending:
                settle_point = entry.get("id")
        elif not pending:
            settle_point = entry.get("id")
    settled = not pending
    return {"exists": True, "file": mine[0].name, "entries": len(entries), "messages": len(msgs),
            "leaf_id": branch[-1].get("id") if branch else None,
            "settle_point": settle_point, "branch_entries": len(branch),
            "last_role": last.get("role") if last else None,
            "last_stop": last.get("stopReason") if last else None, "settled": settled,
            "identity_entries": sum(1 for e in branch if e.get("type") == "custom"
                                    and e.get("customType") == "identity")}


def _finished(message: dict) -> bool:
    return message.get("role") == "assistant" and message.get("stopReason") in (
        "stop", "error", "aborted", "length")


def _active_branch(entries: list[dict]) -> list[dict]:
    """Root-to-leaf entries of the branch Pi reopens: from the file's last entry up."""
    if not entries:
        return []
    by_id = {e.get("id"): e for e in entries if e.get("id")}
    out: list[dict] = []
    seen: set = set()
    node: dict | None = entries[-1]
    while node is not None and node.get("id") not in seen:
        seen.add(node.get("id"))
        out.append(node)
        parent = node.get("parentId")
        node = by_id.get(parent) if parent else None
    return list(reversed(out))


# --- host-side Unix socket servers --------------------------------------------------------


class UnixServer:
    """A Unix socket server, one thread per connection; handler errors are swallowed.

    :meth:`close` ends every thread it started -- the accept loop and each connection's -- so
    none is left behind in the process that ran the box (the server itself, in in-process
    mode: one box per turn, three servers per team turn; C7).
    """

    #: How long :meth:`close` waits for its threads to end, all together.
    JOIN_SECONDS = 5.0

    def __init__(self, path: Path, handler: Callable[[socket.socket], None]):
        self.path = path
        self.handler = handler
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        os.chmod(path, 0o600)
        self.sock.listen(32)
        self._lock = threading.Lock()
        self._closed = False
        self._conns: dict[socket.socket, threading.Thread] = {}
        self.thread = threading.Thread(target=self._serve, daemon=True,
                                       name=f"pi-box-{path.stem}-accept")
        self.thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with self._lock:
                if self._closed:
                    conn.close()
                    return
                worker = threading.Thread(target=self._one, args=(conn,), daemon=True,
                                          name=f"pi-box-{self.path.stem}-conn")
                self._conns[conn] = worker
            worker.start()

    def _one(self, conn: socket.socket) -> None:
        try:
            self.handler(conn)
        except Exception:  # noqa: BLE001 - a broken client never takes the host down
            pass
        finally:
            with self._lock:
                self._conns.pop(conn, None)
            try:
                conn.close()
            except OSError:
                pass

    def close(self, timeout: float | None = None) -> None:
        """Stop accepting, cut every open connection, and wait (at most ``timeout`` seconds,
        default :attr:`JOIN_SECONDS`) for the threads to end. Idempotent; never raises."""
        with self._lock:
            self._closed = True
            open_ = dict(self._conns)
        # On Linux closing a listening socket does not wake a thread blocked in accept();
        # shutting it down does. A connection's shutdown ends its handler's reads.
        for s in (self.sock, *open_):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        try:
            self.sock.close()
        except OSError:
            pass
        deadline = time.monotonic() + (self.JOIN_SECONDS if timeout is None else timeout)
        for thread in (self.thread, *open_.values()):
            if thread is not threading.current_thread():
                thread.join(max(0.0, deadline - time.monotonic()))


def read_line(conn: socket.socket, limit: int = 256, timeout: float = 30) -> str:
    conn.settimeout(timeout)
    buf = b""
    while b"\n" not in buf and len(buf) <= limit:
        data = conn.recv(64)
        if not data:
            break
        buf += data
    return buf.split(b"\n", 1)[0].decode("ascii", "replace").strip()


def read_json_line(conn: socket.socket, limit: int, timeout: float = 30) -> Any:
    """One UTF-8 JSON object on one line, at most ``limit`` bytes; None if it is not one."""
    conn.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        if len(buf) > limit:
            return None
        data = conn.recv(65536)
        if not data:
            break
        buf += data
    line = buf.split(b"\n", 1)[0]
    if len(line) > limit:
        return None
    try:
        return json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def pipe(src: socket.socket, dst: socket.socket, counter: Counter, key: str) -> None:
    try:
        while data := src.recv(65536):
            counter[key] += len(data)
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


# --- the box ----------------------------------------------------------------------------


@dataclass
class BoxSpec:
    """What one start of a participant's worker needs."""

    participant_dir: Path
    session_id: str
    role: str
    provider: str
    model: str
    thinking: str
    tools: list[str]
    labels: dict[str, str] = field(default_factory=dict)
    #: The member's add-ons, each loaded from its pinned copy (``BoxConfig.add_ons``).
    add_ons: list[str] = field(default_factory=list)
    #: A team member's message channel for this turn (``handle(payload) -> reply`` and
    #: ``reachable``, the names it may message), or None for a single Pi step. With it the
    #: box gets a third socket, ``team.sock``, and the send tool (``TEAM_TOOL``) in ``tools``.
    team: Any = None
    #: The run's pinned account slot label (ADR-M4-14/15, e.g. a pi-multi-pass alias of the
    #: route's provider), recorded exactly on the turn. The host helper is asked for this slot
    #: only; inside the box the provider stays the route's. Empty: the route's provider.
    slot: str = ""


#: The Pi tool name of Temper's team messaging (registered by the temper-box extension only
#: when the box has a team socket). Pi's ``--tools`` allowlist must name it to activate it.
TEAM_TOOL = "send_message"
#: The largest send the team socket reads: a 65536-character body, JSON-escaped, and the rest.
TEAM_LINE_LIMIT = 512 * 1024
#: A worker box's container name, and nothing else, is what a takeover may stop (C1).
BOX_NAME = re.compile(r"^temper-pi-[0-9a-f]{20}$")


def pi_extensions(cfg: BoxConfig, spec: BoxSpec, route: Route) -> list[str]:
    """The in-box entry of every extension a worker's Pi is started with, in order: Temper's
    identity and box extensions, the model route's sign-in extension, then the member's pinned
    add-ons."""
    out = ["/ext/identity/index.ts", "/ext/temper-box/index.ts"]
    if route.extension:
        out.append(f"/ext/auth/{route.extension_entry or 'index.ts'}")
    out += [f"/ext/addons/{name}/{cfg.add_ons[name].entry}" for name in spec.add_ons]
    return out


def extension_entries(argv: Sequence[str]) -> list[str]:
    """The entry after every ``--extension`` of a Pi command line, in order."""
    args = [str(a) for a in argv]
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--extension"]


def _docker_cli(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    env = {k: os.environ[k] for k in DOCKER_ENV_KEYS if k in os.environ}
    env["PATH"] = "/usr/bin:/bin:/usr/local/bin"
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout,
                          env=env)


def _no_such_container(answer: subprocess.CompletedProcess, name: str) -> bool:
    """True only for the Docker daemon's own answer that no container has exactly this name.
    Matched with the name in it, because an unreachable daemon also says "no such" ("dial unix
    /var/run/docker.sock: connect: no such file or directory") and must never count as gone."""
    if answer.returncode == 0:
        return False
    said = f"{answer.stdout or ''}\n{answer.stderr or ''}".lower()
    return f"no such container: {name}" in said or f"no such object: {name}" in said


def stop_leftover_box(name: str, docker: Callable[..., Any] | None = None) -> dict:
    """Confirm a cut-off turn's worker box is gone, stopping and removing it if it is not
    (R2 C1, A3 rule 4). ``confirmed`` is True only when the Docker daemon answers that no
    container of that exact name exists; anything else (Docker unreachable or erroring, the
    container still there after removal) is not confirmed, and the caller must not take the
    turn over."""
    run = docker or _docker_cli
    result: dict[str, Any] = {"box": name, "found": False, "was_running": False,
                              "removed": False, "confirmed": False, "error": None}
    if not BOX_NAME.match(name or ""):
        result["error"] = "not a worker box name"
        return result
    try:
        got = run("inspect", "--type", "container", "--format", "{{.State.Running}}", name,
                  timeout=30)
        if got.returncode != 0:
            if _no_such_container(got, name):
                result["confirmed"] = True
                return result
            result["error"] = "docker inspect failed"
            return result
        result["found"] = True
        result["was_running"] = got.stdout.strip() == "true"
        if result["was_running"]:
            run("kill", name, timeout=30)
        run("rm", "--force", name, timeout=60)
        # Asked again by its exact name, not with a name filter (a filter is a pattern, and an
        # empty listing could also be a failed or mismatched query).
        left = run("inspect", "--type", "container", "--format", "{{.Id}}", name, timeout=30)
        result["removed"] = _no_such_container(left, name)
        result["confirmed"] = result["removed"]
        if not result["confirmed"]:
            result["error"] = ("still there after removal" if left.returncode == 0
                               else "docker inspect failed after removal")
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = f"{type(exc).__name__}"
    return result


class WorkerBox:
    """One container and its two host-side sockets, for one turn. Not reused."""

    def __init__(self, cfg: BoxConfig, spec: BoxSpec, redactor: Any,
                 owner_token: Callable[[str], str] | None = None,
                 connector: Callable[[str], socket.socket] | None = None):
        self.cfg = cfg
        self.spec = spec
        self.route = cfg.routes[spec.provider]
        self.redactor = redactor
        self.owner_token = owner_token or self._host_pi_token
        self.connector = connector or self._connect_upstream
        #: The account slot this box's hand-offs are for, and the last plain refusal.
        self.slot = spec.slot or self.route.provider
        self.handoff_refused: str | None = None
        self.name = f"temper-pi-{uuid.uuid4().hex[:20]}"
        self.pdir = Path(spec.participant_dir)
        self.allowance = 0
        self.handoffs = 0
        self.denied = 0
        self.team_sends = 0
        self.team_refused = 0
        self.tunnels: list[dict] = []
        self.bytes: Counter[str] = Counter()
        self.live: set[socket.socket] = set()
        self.lock = threading.Lock()
        self.sock_dir: Path | None = None
        self.servers: list[UnixServer] = []
        self.created = False
        self.rpc: Rpc | None = None
        self.inspected: dict | None = None
        #: How the container was really started, read back from Docker: the ``--extension``
        #: entries of Pi's command line and the environment (the turn checks the add-ons).
        self.launched: dict | None = None

    # --- setup ---

    def _write_agent_dir(self) -> None:
        """A fresh agent folder at every start: settings, the login command and role config."""
        agent = self.pdir / "agent"
        if agent.exists():
            shutil.rmtree(agent)
        agent.mkdir(mode=0o700, parents=True)

        def put(name: str, data: bytes) -> None:
            fd = os.open(agent / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)

        put("settings.json", json.dumps(SETTINGS, indent=2).encode())
        command = f"!{CONTAINER_PYTHON} -B /box/handoff_client.py {self.route.provider}"
        put("models.json", json.dumps({"providers": {self.route.provider: {"apiKey": command}}},
                                      indent=2).encode())
        if self.route.catalog:
            put("models-store.json", Path(self.route.catalog).read_bytes())
        config = Path(self.cfg.identity_config)
        for name in ("pi-identity.json", "pi-identity-role.md"):
            if (config / name).is_file():
                put(name, (config / name).read_bytes())

    def _identity_copy(self) -> Path:
        """The identity extension without its node_modules, plus a link to the runtime's
        modules as seen inside the box. Content-addressed, made once per state root."""
        src = Path(self.cfg.identity_extension)
        return self._sealed_copy(src, "identity", tree_sha256(src))

    def _add_on_copy(self, name: str) -> Path:
        """An add-on's pinned copy, made the same way as the identity extension's; refused when
        the copy no longer has its pinned digest."""
        pin = self.cfg.add_ons[name]
        digest = tree_sha256(Path(pin.dir))
        if digest != pin.sha256:
            raise BoxError("add_on_changed", f"add-on {name}: pinned copy changed (digest differs)")
        return self._sealed_copy(Path(pin.dir), f"addon-{name}", digest)

    def _sealed_copy(self, src: Path, label: str, digest: str) -> Path:
        dst = Path(self.cfg.state_root) / "_ext" / f"{label}-{digest[:16]}"
        if dst.is_dir():
            return dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{label}-", dir=dst.parent))
        shutil.copytree(src, tmp, dirs_exist_ok=True, symlinks=True,
                        ignore=shutil.ignore_patterns("node_modules"))
        _owner_writable(tmp)
        os.symlink("/pi-runtime/pi/node_modules", tmp / "node_modules")
        try:
            os.rename(tmp, dst)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
        return dst

    def mounts(self) -> list[tuple[str, str, bool]]:
        """(source, target, writable)."""
        assert self.sock_dir is not None
        mounts = [
            (str(Path(self.cfg.runtime_dir).resolve()), "/pi-runtime", False),
            (str(ASSETS.resolve()), "/box", False),
            (str(self._identity_copy().resolve()), "/ext/identity", False),
            (str(PROBE_DIR.resolve()), "/ext/temper-box", False),
            (str(self.pdir.resolve()), "/w", True),
            (str(self.sock_dir), "/box-sock", False),
        ]
        if self.route.extension:
            mounts.append((str(Path(self.route.extension).resolve()), "/ext/auth", False))
        for name in self.spec.add_ons:
            mounts.append((str(self._add_on_copy(name).resolve()), f"/ext/addons/{name}", False))
        ca_pem = (self.cfg.rehearsal or {}).get("ca_pem")
        if self.cfg.mode == "rehearsal" and ca_pem:
            mounts.append((str(Path(ca_pem).resolve()),
                           "/box-ca/ca.pem", False))
        return mounts

    def env(self) -> dict[str, str]:
        env = {
            "HOME": "/w/home", "LANG": "C.UTF-8",
            "PATH": "/pi-runtime:/usr/local/bin:/usr/bin:/bin", "TMPDIR": "/w/tmp",
            "XDG_CACHE_HOME": "/w/cache", "PI_CODING_AGENT_DIR": "/w/agent",
            "PI_CODING_AGENT_SESSION_DIR": "/w/sessions", "NODE_DISABLE_COMPILE_CACHE": "1",
            "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0",
            "HTTPS_PROXY": "http://127.0.0.1:3128", "HTTP_PROXY": "http://127.0.0.1:3128",
            "TEMPER_BOX_OBSERVER_OUT": "/w/observer/events.jsonl",
            "TEMPER_BOX_STATE_OUT": STATE_FILE,
            "TEMPER_BOX_ROLE": self.spec.role, "TEMPER_BOX_TOOLS": ",".join(sorted(self.spec.tools)),
            "PI_MEMORY_DIR": "/w/memory", "PI_IDENTITY_DIR": "/w/memory/identities",
            "PI_IDENTITY_REINDEX": "0", "PI_TLDR_NUDGES": "off",
        }
        if self.spec.team is not None:
            # The names only: who sent a message is Temper's to say, never the box's.
            env["TEMPER_BOX_TEAM"] = "1"
            env["TEMPER_BOX_TEAM_MEMBERS"] = json.dumps(list(self.spec.team.reachable))
        if self.cfg.mode == "rehearsal":
            env["NODE_EXTRA_CA_CERTS"] = "/box-ca/ca.pem"
        return env

    def pi_args(self) -> list[str]:
        # ``--no-extensions`` and then only these: Pi 0.87.1 stops (exit 1) when any of them
        # fails to load, so a running Pi has loaded every one (the turn reads them back).
        args = ["--mode", "rpc", "--offline", "--no-approve", "--no-extensions", "--no-skills",
                "--no-prompt-templates", "--no-themes", "--no-context-files"]
        for entry in pi_extensions(self.cfg, self.spec, self.route):
            args += ["--extension", entry]
        args += ["--provider", self.spec.provider, "--model", self.spec.model,
                 "--thinking", self.spec.thinking, "--tools", ",".join(self.spec.tools),
                 "--session-dir", "/w/sessions", "--session-id", self.spec.session_id]
        return args

    def create_args(self, command: list[str] | None = None) -> list[str]:
        args = ["docker", "create", "--pull=never", "--interactive", "--init",
                "--name", self.name, "--label", "temper.pi.box=1"]
        for key, value in sorted(self.spec.labels.items()):
            args += ["--label", f"temper.pi.{key}={value}"]
        args += ["--network", "none", "--read-only", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--pids-limit", str(self.cfg.pids),
                 "--memory", self.cfg.memory, "--cpus", self.cfg.cpus,
                 "--user", f"{os.getuid()}:{os.getgid()}", "--log-driver", "none",
                 "--dns", "127.0.0.1", "--dns-search", ".", "--workdir", WORKDIR,
                 "--entrypoint", CONTAINER_PYTHON]
        for src, dst, writable in self.mounts():
            args += ["--mount", f"type=bind,source={src},target={dst}"
                     + ("" if writable else ",readonly")]
        for key, value in sorted(self.env().items()):
            args += ["--env", f"{key}={value}"]
        args += [self.cfg.image, "-B", "/box/entry.py", *self.pi_args()] if command is None \
            else [self.cfg.image, *command]
        return args

    def _docker(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        env = {k: os.environ[k] for k in DOCKER_ENV_KEYS if k in os.environ}
        env["PATH"] = "/usr/bin:/bin:/usr/local/bin"
        return subprocess.run(["docker", *args], capture_output=True, text=True,
                              timeout=timeout, env=env)

    def _open_sockets(self) -> None:
        root = self.cfg.sockets
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.sock_dir = Path(tempfile.mkdtemp(prefix="b", dir=root))
        os.chmod(self.sock_dir, 0o755)
        self.servers = [UnixServer(self.sock_dir / "handoff.sock", self._handoff),
                        UnixServer(self.sock_dir / "egress.sock", self._egress)]
        if self.spec.team is not None:
            self.servers.append(UnixServer(self.sock_dir / "team.sock", self._team))

    def _team(self, conn: socket.socket) -> None:
        """One send from the member's send tool: Temper stamps and routes it (R2 B2, B3).
        The socket is the binding -- this box, this turn -- so there is no token to leak."""
        payload = read_json_line(conn, TEAM_LINE_LIMIT)
        if payload is None:
            reply: dict[str, Any] = {"ok": False, "code": "invalid_message",
                                     "detail": "the message must be one JSON object"}
        else:
            try:
                reply = self.spec.team.handle(payload)
            except Exception:  # noqa: BLE001 - a send never takes the turn down
                reply = {"ok": False, "code": "invalid_channel",
                         "detail": "Temper could not take the message"}
        with self.lock:
            self.team_sends += 1 if reply.get("ok") else 0
            self.team_refused += 0 if reply.get("ok") else 1
        conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))

    def _check_search_tools(self) -> None:
        """Refuse a start, before any docker call: a Pi tool whose search binary the box config
        doesn't pin (grep needs rg, find needs fd), or a pinned binary that is no longer exactly
        the pinned one. Read on the host at every start, before the runtime's read-only mount."""
        missing = search_tool_problems(self.spec.tools, self.cfg)
        if missing:
            raise BoxError("search_tool_missing", "; ".join(missing))
        changed = self.cfg.search_tool_pin_problems()
        if changed:
            raise BoxError("search_tool_changed", "Pi worker box config: " + "; ".join(changed))

    def start(self, event_sink: Callable[[dict], None],
              command: list[str] | None = None) -> Rpc:
        """Create, check and start the container; its attached stdio is the RPC channel."""
        self._check_search_tools()
        for sub in ("sessions", "workspace", "home", "tmp", "cache", "state", "observer",
                    "memory/identities"):
            (self.pdir / sub).mkdir(parents=True, exist_ok=True)
        for stale in ("box-state.json", "box-blocked.json", "box-rewind.json"):
            (self.pdir / "state" / stale).unlink(missing_ok=True)
        self._write_agent_dir()
        self._open_sockets()
        made = self._docker(*self.create_args(command)[1:])
        if made.returncode != 0:
            raise BoxError("box_create_failed", "the worker container could not be created")
        self.created = True
        self.inspected = self._inspect()
        env = {k: os.environ[k] for k in DOCKER_ENV_KEYS if k in os.environ}
        env["PATH"] = "/usr/bin:/bin:/usr/local/bin"
        self.rpc = Rpc(["docker", "start", "--attach", "--interactive", self.name],
                       cwd=str(self.pdir), env=env, event_sink=event_sink)
        return self.rpc

    def _inspect(self) -> dict:
        """Refuse to start a container that is not sealed exactly as asked."""
        out = self._docker("inspect", self.name)
        if out.returncode != 0:
            raise BoxError("box_inspect_failed", "the worker container could not be inspected")
        info = json.loads(out.stdout)[0]
        hc = info.get("HostConfig") or {}
        binds = {(m.get("Source"), m.get("Destination"), bool(m.get("RW")))
                 for m in info.get("Mounts") or []}
        expected = set(self.mounts())
        owner_pi = str(Path.home() / ".pi")
        checks = {
            "network_none": hc.get("NetworkMode") == "none",
            "read_only_root": hc.get("ReadonlyRootfs") is True,
            "not_privileged": hc.get("Privileged") is False,
            "cap_drop_all": [c.upper() for c in hc.get("CapDrop") or []] in (["ALL"], ["CAP_ALL"]),
            "no_cap_add": not hc.get("CapAdd"),
            "no_new_privileges": any(str(o).startswith("no-new-privileges")
                                     for o in hc.get("SecurityOpt") or []),
            "own_pid_namespace": hc.get("PidMode") in ("", None),
            "no_devices": not hc.get("Devices"),
            "log_driver_none": (hc.get("LogConfig") or {}).get("Type") == "none",
            "init": hc.get("Init") is True,
            "image": info.get("Image") == self.cfg.image,
            "user": (info.get("Config") or {}).get("User") == f"{os.getuid()}:{os.getgid()}",
            "mounts_exact": binds == expected,
            "no_owner_pi_mount": not any(str(s).startswith(owner_pi) for s, _d, _w in binds),
        }
        failed = sorted(k for k, ok in checks.items() if not ok)
        if failed:
            raise BoxError("box_not_sealed", "worker container is not sealed: " + ", ".join(failed))
        config = info.get("Config") or {}
        self.launched = {"extensions": extension_entries(config.get("Cmd") or []),
                         "env": dict(str(e).partition("=")[::2] for e in config.get("Env") or [])}
        return checks

    def expected_extensions(self) -> list[str]:
        """The in-box entry of every extension Pi is started with, in order."""
        return pi_extensions(self.cfg, self.spec, self.route)

    # --- credentials and egress (host side) ---

    def allow(self, count: int) -> None:
        with self.lock:
            self.allowance = count

    def _host_pi_token(self, provider: str) -> str:
        if self.cfg.mode == "rehearsal":
            return str(((self.cfg.rehearsal or {}).get("tokens") or {}).get(provider) or "")
        if self.cfg.host_helper_socket:
            return self._helper_token()
        home = self.cfg.host_home or str(Path.home())
        env = {"HOME": home, "LANG": "C.UTF-8",
               "PATH": f"{Path(self.cfg.host_node).parent}:/usr/bin:/bin",
               "PI_CODING_AGENT_DIR": f"{home}/.pi/agent", "PI_OFFLINE": "1",
               "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"}
        try:
            got = subprocess.run([self.cfg.host_node, self.cfg.host_pi, "auth",
                                  "print-bearer-token", "--provider", provider,
                                  "--min-expiry", "30m"], capture_output=True, timeout=30,
                                 env=env)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return got.stdout.decode("utf-8", "replace").strip() if got.returncode == 0 else ""

    def _helper_token(self) -> str:
        """The run's pinned slot's token from the host helper, or "" with the plain refusal
        (naming the slot) kept for the turn's receipt. Never another slot, never a fallback."""
        if not self.spec.slot:
            why = ("no account slot is pinned for this run; the host helper serves only a "
                   "pinned slot and was not asked")
            token = ""
        else:
            token, why = host_helper.token(self.cfg.host_helper_socket, self.spec.slot)
        if not token:
            with self.lock:
                self.handoff_refused = why
        return token

    def _handoff(self, conn: socket.socket) -> None:
        provider = read_line(conn)
        with self.lock:
            ok = (provider == self.route.provider and self.allowance > 0
                  and self.cfg.fault != "deny_handoff")
            if ok:
                self.allowance -= 1
                self.handoffs += 1
            else:
                self.denied += 1
        if not ok:
            return
        token = self.owner_token(provider)
        if not token:
            with self.lock:
                self.denied += 1
            return
        # The redactor learns the token (and any account id inside it) before Pi has it.
        self.redactor.add(token, *jwt_account_ids(token))
        conn.sendall(token.encode())

    def _connect_upstream(self, host: str) -> socket.socket:
        if self.cfg.mode == "rehearsal":
            port = int((self.cfg.rehearsal or {})["upstream_port"])
            return socket.create_connection(("127.0.0.1", port), timeout=15)
        return socket.create_connection((host, 443), timeout=15)

    def _egress(self, conn: socket.socket) -> None:
        conn.settimeout(30)
        head = b""
        while b"\r\n\r\n" not in head and len(head) <= 8192:
            data = conn.recv(1024)
            if not data:
                break
            head += data
        first = head.split(b"\r\n", 1)[0].decode("latin-1", "replace").split()
        method = first[0] if first else ""
        target = first[1] if len(first) > 1 else ""
        host, _, port = target.rpartition(":")
        allowed = method == "CONNECT" and host == self.route.host and port == "443"
        with self.lock:
            self.tunnels.append({"host": self.route.host if host == self.route.host else "other",
                                 "allowed": allowed})
        if not allowed:
            conn.sendall(FORBIDDEN)
            return
        upstream = self.connector(host)
        conn.settimeout(None)
        upstream.settimeout(None)
        with self.lock:
            self.live.update((conn, upstream))
        conn.sendall(ESTABLISHED)
        rest = head.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in head else b""
        if rest:
            upstream.sendall(rest)
        threads = [threading.Thread(target=pipe, args=(conn, upstream, self.bytes, "up"),
                                    daemon=True),
                   threading.Thread(target=pipe, args=(upstream, conn, self.bytes, "down"),
                                    daemon=True)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with self.lock:
            self.live.difference_update((conn, upstream))
        upstream.close()

    # --- fault injection (proof harness only) and teardown ---

    def kill(self) -> None:
        if self.created:
            self._docker("kill", self.name, timeout=30)

    def close(self) -> dict:
        """Stop Pi, remove the container, close the sockets. Idempotent; never raises."""
        receipt: dict[str, Any] = {"container": self.name[-8:], "created": self.created,
                                   "sealed_checks": self.inspected}
        try:
            if self.rpc is not None:
                receipt["rpc"] = self.rpc.close()
        except Exception:  # noqa: BLE001
            receipt["rpc"] = {"errors": ["rpc_close_failed"]}
        removed = not self.created
        if self.created:
            try:
                self._docker("rm", "--force", self.name, timeout=60)
                left = self._docker("ps", "-a", "--filter", f"name=^{self.name}$",
                                    "--format", "{{.ID}}", timeout=30)
                removed = left.returncode == 0 and not left.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                removed = False
        receipt["container_removed"] = removed
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with self.lock:
                if not self.live:
                    break
            time.sleep(0.05)
        with self.lock:
            cut = len(self.live)
            for s in list(self.live):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        for server in self.servers:
            server.close()
        if self.sock_dir is not None:
            shutil.rmtree(self.sock_dir, ignore_errors=True)
        with self.lock:
            receipt.update({
                "handoff_slot": self.slot, "handoffs": self.handoffs,
                "handoffs_denied": self.denied,
                "tunnels": len(self.tunnels),
                "tunnels_allowed": sum(1 for t in self.tunnels if t["allowed"]),
                "tunnels_refused": sum(1 for t in self.tunnels if not t["allowed"]),
                "tunnels_cut_at_close": cut, "bytes_up": self.bytes["up"],
                "bytes_down": self.bytes["down"],
            })
            if self.handoff_refused:
                receipt["handoff_refused"] = self.handoff_refused
            if self.spec.team is not None:
                receipt.update({"team_sends": self.team_sends,
                                "team_refused": self.team_refused})
        return receipt
