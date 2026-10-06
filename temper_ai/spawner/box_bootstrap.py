"""A oneshot box's secrets: handed once to a runner that other processes can't read (BS2).

Box secrets step BS2 (docs/boxes.md, "One-shot secret delivery"), on with
TEMPER_BOX_SECRET_BOOTSTRAP=oneshot in a sealed install (BS1). Without it a box's
secrets are its environment: docker inspect shows them, and docker-init (PID 1), the
runner and every same-user process in the box can read them in /proc/<pid>/environ.
With it:

1. The worker starts the box with non-secret variables only: the names the box list
   declares safe for tools, and the spawner's own settings. docker inspect, the init's
   environment and the runner's start environment hold nothing secret.
2. The runner (`python -I -m temper_ai.cli.main run-workflow`, the box's final
   interpreter) calls receive() before anything else. It makes itself non-dumpable
   (PR_SET_DUMPABLE 0: other processes can't read its environ, memory or descriptors,
   and can't ptrace it) and turns core dumps off; then it checks its private 0700
   tmpfs (/run/temper-boot) and says it is waiting.
3. The worker runs this file's writer in the box (`docker exec -i`, the envelope on
   its stdin, never on disk outside the box). The writer makes itself non-dumpable
   too, waits for the runner, writes the envelope as one fixed 0600 leaf and waits for
   the runner's acknowledgement.
4. The runner checks the leaf (a regular 0600 file of its own, one name, not a link,
   in bounds) and reads its non-secret header: run, profile, generation, expiry and
   schema are checked before the secret part is read. One read, the descriptor closed,
   the leaf removed; only then a non-secret acknowledgement, and tools may start.

Anything else refuses: a wrong, stale, oversized or malformed envelope, a wrong mode
or a link, a deadline passed, a failed prctl or clean-up. The runner exits, and the
worker stops the box and records the delivery as revoked. Status says what went wrong
in fixed words, never a value.

The values then live in the runner's os.environ mapping only, not in its C
environment (no putenv): readers in the runner find them as before, a child started
without an explicit environment gets none of them, and tools get the scrubbed
environment (shared/agent_env.py) as before. What this does not protect: a token the
runner deliberately hands to a child (the Claude CLI's model token sits in that child's
environment until BS6), code injected into the runner itself, and memory after use
(non-dumpable is not erasure).

Standard library only: the writer runs as source the worker holds
(`python -I -S -c <this file> --deliver ...`), like the box check (box_view.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

MODE_ENV = "TEMPER_BOX_SECRET_BOOTSTRAP"
ENV = "env"
ONESHOT = "oneshot"
PROTOCOL = "box-delivery/1"
KIND = "temper-box-delivery"
SCHEMA = 1

#: The runner's private tmpfs, and the fixed names in it.
BOOT_DIR = "/run/temper-boot"
LEAF = "delivery"
WAITING = "waiting"
ACK = "ack"
#: The writer read a refusal: the runner may end now (its box ends with it, and a writer
#: still reading would be killed without a word for the worker).
SEEN = "seen"
#: How long a refusing runner waits for the writer to have read why (seconds).
REFUSAL_LINGER = 3.0
#: The envelope's non-secret header: JSON, padded with spaces to this many bytes, the
#: last one a newline. The secret part (JSON, ASCII) follows it.
HEADER_BYTES = 1024

#: Bounds and deadlines (seconds) a oneshot profile carries unless the worker says otherwise.
LIMITS: dict[str, int] = {"max_bytes": 262144, "ready": 60, "delivery": 60, "ack": 30,
                          "expires_after": 120}
#: How far a header's issue time may be ahead of the runner's clock (same host, same clock).
CLOCK_SLACK = 5.0
#: What the runner exits with when it refuses its delivery (box_view's refusal is 3).
REFUSED_EXIT = 4

#: What a profile that doesn't deliver says about itself.
ENV_SECTION = {"mode": ENV,
               "what": "the box's secrets are in its environment, as before BS2"}
#: Fields a oneshot section can't do without.
MANDATORY = ("protocol", "dir", "leaf", "owner", "header_bytes", "max_bytes", "deadlines",
             "expires_after", "consumption", "names")

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_POLL = 0.02

PR_GET_DUMPABLE = 3
PR_SET_DUMPABLE = 4


class DeliveryRefused(Exception):
    """The delivery can't be taken. The text is safe to show: fixed words, never a value."""


# -- the profile's part (the worker writes it, the runner obeys it) ----------------------------


def section(*, names: Iterable[str], uid: int, gid: int,
            limits: Mapping[str, int] | None = None) -> dict:
    """A oneshot profile's "bootstrap" section: where, how big, how long, which names."""
    lim = {**LIMITS, **(limits or {})}
    return {
        "mode": ONESHOT, "protocol": PROTOCOL, "dir": BOOT_DIR, "leaf": LEAF,
        "owner": {"uid": int(uid), "gid": int(gid)}, "dir_mode": "0700", "leaf_mode": "0600",
        "header_bytes": HEADER_BYTES, "max_bytes": int(lim["max_bytes"]),
        "deadlines": {"ready": int(lim["ready"]), "delivery": int(lim["delivery"]),
                      "ack": int(lim["ack"])},
        "expires_after": int(lim["expires_after"]), "consumption": "once",
        "names": sorted(set(names)),
        "children": "scrubbed (shared/agent_env.py); a child started without an "
                    "environment gets none of the delivered values",
    }


def tmpfs_spec(boot: Mapping[str, Any]) -> str:
    """The box's --tmpfs for the delivery folder: private to the runner's user."""
    owner = boot["owner"]
    size = max(1 << 20, 2 * (int(boot["max_bytes"]) + HEADER_BYTES) + (64 << 10))
    return (f"{boot['dir']}:rw,noexec,nosuid,nodev,size={size},mode=0700,"
            f"uid={int(owner['uid'])},gid={int(owner['gid'])}")


def section_problems(boot: Mapping[str, Any] | None) -> list[str]:
    """What a oneshot section lacks or gets wrong ([] = complete)."""
    if not isinstance(boot, Mapping) or boot.get("mode") != ONESHOT:
        return ["the profile has no oneshot section"]
    problems = [f"bootstrap.{key} is missing" for key in MANDATORY if boot.get(key) in (None, "")]
    if problems:
        return problems
    deadlines = boot.get("deadlines") or {}
    for key in ("ready", "delivery", "ack"):
        if not isinstance(deadlines.get(key), int) or deadlines[key] <= 0:
            problems.append(f"bootstrap.deadlines.{key} is not a positive number of seconds")
    for key in ("max_bytes", "expires_after", "header_bytes"):
        if not isinstance(boot.get(key), int) or boot[key] <= 0:
            problems.append(f"bootstrap.{key} is not a positive number")
    if boot.get("header_bytes") != HEADER_BYTES:
        problems.append("bootstrap.header_bytes is not this protocol's")
    if boot.get("protocol") != PROTOCOL:
        problems.append(f"bootstrap.protocol is {boot.get('protocol')!r}, not {PROTOCOL}")
    if boot.get("consumption") != "once":
        problems.append("bootstrap.consumption is not 'once'")
    if not str(boot.get("dir") or "").startswith("/") or "/" in str(boot.get("leaf") or "/"):
        problems.append("bootstrap.dir or bootstrap.leaf is not a fixed path")
    names = boot.get("names")
    if not isinstance(names, list) or not all(isinstance(n, str) and _NAME.match(n)
                                              for n in names):
        problems.append("bootstrap.names is not a list of variable names")
    owner = boot.get("owner") or {}
    if not all(isinstance(owner.get(k), int) and owner[k] > 0 for k in ("uid", "gid")):
        problems.append("bootstrap.owner is not an unprivileged uid and gid")
    return problems


@dataclass(frozen=True)
class Params:
    """A oneshot section, checked."""

    dir: str
    leaf: str
    max_bytes: int
    ready: int
    delivery: int
    ack: int
    expires_after: int
    names: tuple[str, ...]

    @classmethod
    def of(cls, boot: Mapping[str, Any]) -> Params:
        problems = section_problems(boot)
        if problems:
            raise DeliveryRefused("the box profile's delivery section is incomplete: "
                                  + "; ".join(problems))
        deadlines = boot["deadlines"]
        return cls(dir=boot["dir"], leaf=boot["leaf"], max_bytes=boot["max_bytes"],
                   ready=deadlines["ready"], delivery=deadlines["delivery"],
                   ack=deadlines["ack"], expires_after=boot["expires_after"],
                   names=tuple(boot["names"]))


# -- the envelope (the worker builds it, the writer carries it, the runner opens it) ------------


def envelope(doc: Mapping[str, Any], digest: str, values: Mapping[str, str], *,
             now: float | None = None) -> bytearray:
    """Header and secret part, as the bytes the writer delivers. The caller zeroes it after."""
    boot = doc["bootstrap"]
    issued = time.time() if now is None else now
    body = bytearray(json.dumps({str(k): str(v) for k, v in values.items()}, sort_keys=True,
                                separators=(",", ":"), ensure_ascii=True).encode("ascii"))
    header = {"kind": KIND, "schema": SCHEMA, "execution_id": doc["execution_id"],
              "generation": doc["generation"], "profile": digest, "issued_at": issued,
              "expires_at": issued + int(boot["expires_after"]),
              "nonce": os.urandom(16).hex(), "names": sorted(values), "length": len(body)}
    head = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(head) > HEADER_BYTES - 1:
        raise DeliveryRefused("the delivery's header is too long (too many names)")
    if len(body) > int(boot["max_bytes"]):
        raise DeliveryRefused("the delivery is larger than the profile allows")
    out = bytearray(head.ljust(HEADER_BYTES - 1, b" ") + b"\n")
    out += body
    zero(body)
    return out


def zero(buf: bytearray) -> None:
    """Overwrite a buffer in place (best effort: copies made from it are not reached)."""
    buf[:] = bytes(len(buf))


def nonce_digest(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("ascii")).hexdigest()[:16]


def header_of(data: bytes | bytearray) -> dict:
    """The envelope's header, parsed (DeliveryRefused when it isn't one)."""
    head = bytes(data[:HEADER_BYTES])
    if len(head) != HEADER_BYTES or not head.endswith(b"\n"):
        raise DeliveryRefused("malformed envelope: no complete header")
    try:
        header = json.loads(head.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise DeliveryRefused("malformed envelope: the header is not JSON") from None
    if not isinstance(header, dict):
        raise DeliveryRefused("malformed envelope: the header is not a document")
    if header.get("kind") != KIND:
        raise DeliveryRefused("malformed envelope: not a box delivery")
    if header.get("schema") != SCHEMA:
        raise DeliveryRefused(f"wrong envelope: schema {header.get('schema')!r}, "
                              f"this runner knows {SCHEMA}")
    if not isinstance(header.get("nonce"), str) or not _NONCE.match(header["nonce"]):
        raise DeliveryRefused("malformed envelope: no nonce")
    if not isinstance(header.get("length"), int) or header["length"] < 2:
        raise DeliveryRefused("malformed envelope: no length")
    for key in ("issued_at", "expires_at"):
        if not isinstance(header.get(key), (int, float)) or isinstance(header.get(key), bool):
            raise DeliveryRefused(f"malformed envelope: no {key}")
    return header


def check_header(header: Mapping[str, Any], *, doc: Mapping[str, Any], digest: str,
                 params: Params, size: int, now: float) -> None:
    """Run, profile, generation, expiry, names and length, before any secret is read."""
    if header.get("execution_id") != doc.get("execution_id"):
        raise DeliveryRefused("wrong envelope: it is for another run")
    if header.get("profile") != digest:
        raise DeliveryRefused("wrong envelope: it is for another box profile")
    generation = header.get("generation")
    if generation != doc.get("generation"):
        word = ("stale" if isinstance(generation, int) and generation < doc["generation"]
                else "wrong")
        raise DeliveryRefused(f"{word} envelope: generation {generation!r}, this box is "
                              f"{doc.get('generation')}")
    issued, expires = float(header["issued_at"]), float(header["expires_at"])
    if issued > now + CLOCK_SLACK or expires - issued > params.expires_after or expires < issued:
        raise DeliveryRefused("wrong envelope: its times are not the profile's")
    if now > expires:
        raise DeliveryRefused("stale envelope: it expired before it was read")
    if list(header.get("names") or []) != sorted(params.names):
        raise DeliveryRefused("wrong envelope: its names are not the profile's")
    if header["length"] != size - HEADER_BYTES or header["length"] > params.max_bytes:
        raise DeliveryRefused("malformed envelope: its length is not the leaf's")


def values_of(body: bytearray, names: Iterable[str]) -> dict[str, str]:
    """The secret part, parsed and checked against the profile's names."""
    try:
        values = json.loads(body.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise DeliveryRefused("malformed envelope: the secret part is not JSON") from None
    if not isinstance(values, dict) or sorted(values) != sorted(names):
        raise DeliveryRefused("malformed envelope: the secret part's names are not the profile's")
    for name, value in values.items():
        if not isinstance(value, str) or "\x00" in value or not _NAME.match(name):
            raise DeliveryRefused("malformed envelope: a value is not a plain string")
    return values


# -- this process: non-dumpable, no core --------------------------------------------------------


def protect_process() -> None:
    """PR_SET_DUMPABLE 0 and no core dumps, checked; DeliveryRefused when either fails.

    A non-dumpable process's /proc/<pid>/environ, mem and fd belong to root, and other
    processes of its user can't ptrace it (they would need CAP_SYS_PTRACE, which a box
    never has). It holds across fork and is reset by exec: a process that execs another
    program has to do this again (the reason a wrapper can't take the secrets for the
    runner it starts).
    """
    import ctypes
    import resource

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
            raise DeliveryRefused(f"prctl failed: the runner could not make itself unreadable "
                                  f"(errno {ctypes.get_errno()})")
        if libc.prctl(PR_GET_DUMPABLE, 0, 0, 0, 0) != 0:
            raise DeliveryRefused("prctl failed: the runner is still dumpable")
    except (OSError, AttributeError) as exc:
        raise DeliveryRefused(f"prctl failed: libc can't be called ({type(exc).__name__})") from None
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (OSError, ValueError) as exc:
        raise DeliveryRefused(f"core dumps could not be turned off ({type(exc).__name__})") from None


# -- small file helpers -------------------------------------------------------------------------


def _publish(folder: str, name: str, doc: Mapping[str, Any]) -> None:
    """Write a small non-secret marker atomically (a 0600 file of this user, then renamed)."""
    tmp = os.path.join(folder, f".{name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, json.dumps(doc, sort_keys=True).encode("ascii"))
    finally:
        os.close(fd)
    os.rename(tmp, os.path.join(folder, name))


def _read_marker(path: str) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        raw = os.read(fd, 65536)
    finally:
        os.close(fd)
    try:
        doc = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _wait_for(path: str, seconds: float, *, clock: Callable[[], float],
              sleep: Callable[[float], None]) -> bool:
    return _wait_for_any((path,), seconds, clock=clock, sleep=sleep) is not None


def _wait_for_any(paths: tuple[str, ...], seconds: float, *, clock: Callable[[], float],
                  sleep: Callable[[float], None]) -> str | None:
    """The first of ``paths`` that exists (checked in order), or None at the deadline."""
    deadline = clock() + seconds
    while True:
        for path in paths:
            if os.path.lexists(path):
                return path
        if clock() >= deadline:
            return None
        sleep(_POLL)


def _mounts(path: str = "/proc/self/mountinfo") -> list[dict]:
    found = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            left, _, right = line.rstrip("\n").partition(" - ")
            parts, tail = left.split(" "), right.split(" ")
            if len(parts) >= 6 and len(tail) >= 3:
                found.append({"target": parts[4], "options": set(parts[5].split(",")),
                              "fstype": tail[0], "super": set(tail[2].split(","))})
    return found


# -- the runner's side --------------------------------------------------------------------------

#: This process's state: mode None (never asked: not a box runner), env or oneshot.
_STATE: dict[str, Any] = {"mode": None, "allowed": False, "taken": None}


def tools_allowed() -> bool:
    """Whether this process may start tools: always, except a oneshot runner before receipt.

    A process that never called receive() looks at its own profile once: one whose
    profile asks for a oneshot delivery may start nothing until it has taken it.
    """
    if _STATE["mode"] is None:
        _STATE["mode"] = ONESHOT if oneshot_doc() is not None else ENV
    return _STATE["mode"] != ONESHOT or bool(_STATE["allowed"])


def require_tools_allowed(what: str) -> None:
    """Refuse ``what`` (a tool, an agent's child process) before the delivery is taken."""
    if not tools_allowed():
        raise DeliveryRefused(f"{what} can't start before the box's one-shot delivery is "
                              "taken and acknowledged")


def taken() -> dict | None:
    """What this process received: generation and names (never values). None before."""
    return _STATE["taken"]


def oneshot_doc(environ: Mapping[str, str] | None = None) -> dict | None:
    """The box's profile when it asks for a oneshot delivery, else None.

    A profile that can't be read is not a oneshot one here: a sealed box with one is
    refused by its boot check before the runner starts (box_view.py), and a legacy box
    goes on without one (cli/run_workflow.py), as before BS2.
    """
    from temper_ai.spawner.box_view import BoxStartRefused, profile_from_env

    try:
        doc = profile_from_env(environ)
    except BoxStartRefused:
        return None
    if doc is None or (doc.get("bootstrap") or {}).get("mode") != ONESHOT:
        return None
    return doc


def require_received(environ: Mapping[str, str] | None = None) -> None:
    """A oneshot box's runner that didn't take its delivery first is refused (DeliveryRefused)."""
    if oneshot_doc(environ) is not None and not _STATE["allowed"]:
        raise DeliveryRefused("this box's profile asks for a one-shot delivery and this process "
                              "has not taken one: refused (every runner takes its own)")


def receive(environ: Mapping[str, str] | None = None, *,
            protect: Callable[[], None] = protect_process,
            mounts: Callable[[], list[dict]] = _mounts,
            unlink: Callable[[str], None] = os.unlink,
            clock: Callable[[], float] = time.monotonic,
            wall: Callable[[], float] = time.time,
            sleep: Callable[[float], None] = time.sleep,
            target: Any = None, linger: float = REFUSAL_LINGER) -> dict | None:
    """Take this box's one-shot delivery, the first thing the runner does. None: not oneshot.

    Blocks until the delivery is taken (bounded by the profile's delivery deadline).
    On any problem it removes what it can, acknowledges a refusal and raises
    DeliveryRefused; the runner must then exit (cli/main.py does). ``target`` is where
    the values go (os.environ when None; tests give a dict).
    """
    if _STATE["allowed"]:
        return _STATE["taken"]
    env = os.environ if environ is None else environ
    doc = oneshot_doc(env)
    if doc is None:
        _STATE.update(mode=_STATE["mode"] or ENV)
        return None
    _STATE.update(mode=ONESHOT, allowed=False)
    from temper_ai.spawner.box_view import DIGEST_ENV

    digest = env.get(DIGEST_ENV) or ""
    params = Params.of(doc["bootstrap"])
    folder = params.dir
    refused = {"state": "refused", "execution_id": doc["execution_id"],
               "generation": doc["generation"], "nonce": None}
    try:
        protect()  # before anything secret can be in this process
    except DeliveryRefused as exc:
        try:  # say so, if the folder is fit to say it in
            _check_folder(folder, mounts())
            _acknowledge(folder, {**refused, "reason": str(exc)})
            _wait_for(os.path.join(folder, SEEN), linger, clock=clock, sleep=sleep)
        except (DeliveryRefused, OSError):
            pass
        raise
    _check_folder(folder, mounts())
    leaf = os.path.join(folder, params.leaf)
    nonce = None
    try:
        try:
            _publish(folder, WAITING, {"pid": os.getpid(), "execution_id": doc["execution_id"],
                                       "generation": doc["generation"], "profile": digest})
            if not _wait_for(leaf, params.delivery, clock=clock, sleep=sleep):
                raise DeliveryRefused(f"timeout: no delivery within {params.delivery}s")
            values, nonce = _take(leaf, doc=doc, digest=digest, params=params, unlink=unlink,
                                  now=wall())
        except OSError as exc:
            raise DeliveryRefused(f"the delivery folder can't be used ({type(exc).__name__}, "
                                  f"errno {exc.errno})") from None
    except DeliveryRefused as exc:
        _clear(folder, params, unlink=unlink)
        _acknowledge(folder, {**refused, "reason": str(exc),
                              "nonce": nonce_digest(nonce) if nonce else None})
        _wait_for(os.path.join(folder, SEEN), linger, clock=clock, sleep=sleep)
        raise
    _install(values, os.environ if target is None else target)
    names = sorted(values)
    values.clear()
    _remove(os.path.join(folder, WAITING))
    _acknowledge(folder, {"state": "consumed", "execution_id": doc["execution_id"],
                          "generation": doc["generation"], "nonce": nonce_digest(nonce),
                          "names": len(names), "pid": os.getpid()})
    _STATE.update(allowed=True, taken={"generation": doc["generation"], "names": names})
    return _STATE["taken"]


def _check_folder(folder: str, mounts: list[dict]) -> None:
    """The delivery folder: this user's own 0700 tmpfs, not a link, and empty."""
    try:
        st = os.lstat(folder)
    except OSError:
        raise DeliveryRefused(f"the delivery folder {folder} is missing") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise DeliveryRefused(f"the delivery folder {folder} is not a folder (a link?)")
    if st.st_uid != os.getuid():
        raise DeliveryRefused(f"the delivery folder {folder} belongs to another user")
    if stat.S_IMODE(st.st_mode) != 0o700:
        raise DeliveryRefused(f"the delivery folder {folder} has mode "
                              f"{stat.S_IMODE(st.st_mode):04o}, not 0700")
    here = [m for m in mounts if m["target"] == folder]
    if not here or here[-1]["fstype"] != "tmpfs":
        raise DeliveryRefused(f"the delivery folder {folder} is not its own tmpfs")
    if not {"nosuid", "nodev", "noexec"} <= here[-1]["options"]:
        raise DeliveryRefused(f"the delivery folder {folder} is not nosuid, nodev, noexec")
    if os.listdir(folder):
        raise DeliveryRefused("the delivery folder is not empty: this box took a delivery "
                              "already (one consumption per box), or something else wrote there")


def _take(leaf: str, *, doc: Mapping[str, Any], digest: str, params: Params,
          unlink: Callable[[str], None], now: float) -> tuple[dict[str, str], str]:
    """Check, read once, close, remove. Values and the header's nonce."""
    try:
        st = os.lstat(leaf)
    except OSError:
        raise DeliveryRefused("the delivery vanished before it was read") from None
    if stat.S_ISLNK(st.st_mode):
        raise DeliveryRefused("the delivery is a link")
    if not stat.S_ISREG(st.st_mode):
        raise DeliveryRefused("the delivery is not a regular file")
    if st.st_uid != os.getuid():
        raise DeliveryRefused("the delivery belongs to another user")
    if stat.S_IMODE(st.st_mode) != 0o600:
        raise DeliveryRefused(f"the delivery has mode {stat.S_IMODE(st.st_mode):04o}, not 0600")
    if st.st_nlink != 1:
        raise DeliveryRefused("the delivery has other names (hard links)")
    if st.st_size > HEADER_BYTES + params.max_bytes:
        raise DeliveryRefused("oversized envelope: larger than the profile allows")
    if st.st_size <= HEADER_BYTES:
        raise DeliveryRefused("malformed envelope: no secret part")
    body = bytearray()
    try:
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError:
        raise DeliveryRefused("the delivery could not be opened (a link?)") from None
    try:
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino, fst.st_size) != (st.st_dev, st.st_ino, st.st_size):
            raise DeliveryRefused("the delivery changed between its check and its read")
        head = _read_exactly(fd, HEADER_BYTES)
        header = header_of(head)
        check_header(header, doc=doc, digest=digest, params=params, size=st.st_size, now=now)
        body = bytearray(header["length"])
        if _read_into(fd, body) != len(body) or os.read(fd, 1):
            raise DeliveryRefused("the delivery changed while it was read")
    finally:
        os.close(fd)
        try:
            unlink(leaf)
        except OSError:
            zero(body)
            raise DeliveryRefused("cleanup failed: the delivery could not be removed") from None
    if os.path.lexists(leaf):
        zero(body)
        raise DeliveryRefused("cleanup failed: the delivery is still there after removal")
    try:
        return values_of(body, params.names), header["nonce"]
    finally:
        zero(body)


def _read_exactly(fd: int, count: int) -> bytes:
    chunks, got = [], 0
    while got < count:
        chunk = os.read(fd, count - got)
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def _read_into(fd: int, buf: bytearray) -> int:
    view, got = memoryview(buf), 0
    try:
        while got < len(buf):
            n = os.readv(fd, [view[got:]])
            if n == 0:
                break
            got += n
    finally:
        view.release()
    return got


def _clear(folder: str, params: Params, *, unlink: Callable[[str], None]) -> None:
    """Remove the leaf, the writer's temporary and the waiting marker (best effort)."""
    for name in (params.leaf, f".{params.leaf}.tmp", WAITING):
        try:
            unlink(os.path.join(folder, name))
        except OSError:
            pass


def _acknowledge(folder: str, doc: Mapping[str, Any]) -> None:
    try:
        _publish(folder, ACK, doc)
    except OSError:
        pass  # the worker's deadline covers an acknowledgement that can't be written


def _install(values: Mapping[str, str], target: Any) -> None:
    """The values into the runner's environment mapping, not its C environment.

    os.environ[name] = value would also putenv() it, and every child started without
    an explicit environment (and /proc/<pid>/environ of a later exec) would carry it.
    Writing the mapping's own store keeps them where Python readers look and nowhere
    else. Then children_start_from_the_c_environment().
    """
    if target is os.environ:
        store = getattr(os.environ, "_data", None)
        if not isinstance(store, dict):
            raise DeliveryRefused("this Python can't hold values outside its C environment")
        for name, value in values.items():
            store[os.environ.encodekey(name)] = os.environ.encodevalue(value)
        children_start_from_the_c_environment()
    else:
        target.update(values)


def children_start_from_the_c_environment() -> None:
    """subprocess never passes the os.environ mapping to posix_spawn (it would carry the values).

    With no env given, subprocess starts a child either through fork and exec, which
    hands it the C environment (none of the delivered values), or through posix_spawn,
    which it hands os.environ itself. Python picks posix_spawn by its own rules, which
    change between versions (3.12: close_fds=False; 3.13: also by default), so a oneshot
    runner turns that path off for the whole process.
    """
    import subprocess

    if getattr(subprocess, "_USE_POSIX_SPAWN", False):
        setattr(subprocess, "_USE_POSIX_SPAWN", False)  # noqa: B010 - private and Final, see above


def reset() -> None:
    """Forget this process's state (tests)."""
    _STATE.update(mode=None, allowed=False, taken=None)


# -- the writer (run by the worker in the box: python -I -S -c <this file> --deliver ...) -------


def deliver(args: list[str], *, stdin: int = 0, out: Any = None,
            protect: Callable[[], None] = protect_process,
            clock: Callable[[], float] = time.monotonic,
            sleep: Callable[[float], None] = time.sleep) -> int:
    """Carry the envelope on ``stdin`` to the runner; one JSON status line on ``out``.

    Exit 0 only when the runner acknowledged this very envelope as consumed.
    """
    out = sys.stdout if out is None else out
    opts = dict(zip(args[::2], args[1::2], strict=False))
    status: dict[str, Any] = {"state": "error", "reason": "the writer did not finish"}
    data = bytearray()
    folder = leaf = ""
    try:
        folder, leaf = opts["--dir"], opts["--leaf"]
        limit = HEADER_BYTES + int(opts["--max"])
        protect()
        data = _read_all(stdin, limit + 1)
        if len(data) > limit:
            raise DeliveryRefused("oversized envelope: larger than the profile allows")
        header = header_of(data)
        if (header.get("execution_id") != opts["--execution"]
                or str(header.get("generation")) != opts["--generation"]):
            raise DeliveryRefused("wrong envelope: not this box's run and generation")
        ack_path = os.path.join(folder, ACK)
        found = _wait_for_any((os.path.join(folder, WAITING), ack_path), int(opts["--ready"]),
                              clock=clock, sleep=sleep)
        if found is None:
            raise DeliveryRefused(f"timeout: the runner was not waiting within {opts['--ready']}s")
        if found == ack_path:  # it refused before it could wait (prctl, its folder)
            ack = _read_marker(ack_path) or {}
            _seen(folder)
            raise DeliveryRefused(str(ack.get("reason") or "the runner refused before waiting")[:300])
        waiting = _read_marker(os.path.join(folder, WAITING)) or {}
        if (waiting.get("execution_id") != header["execution_id"]
                or waiting.get("generation") != header["generation"]):
            raise DeliveryRefused("the waiting runner is another run's or generation's")
        if os.path.lexists(ack_path):
            raise DeliveryRefused("the box has acknowledged a delivery already")
        tmp = os.path.join(folder, f".{leaf}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600)
        try:
            os.fchmod(fd, 0o600)
            view, done = memoryview(data), 0
            try:
                while done < len(data):
                    done += os.write(fd, view[done:])
            finally:
                view.release()
        finally:
            os.close(fd)
        os.rename(tmp, os.path.join(folder, leaf))
        zero(data)
        if not _wait_for(ack_path, int(opts["--ack"]), clock=clock, sleep=sleep):
            raise DeliveryRefused(f"timeout: no acknowledgement within {opts['--ack']}s")
        ack = _read_marker(ack_path) or {}  # renamed into place whole: complete when seen
        if ack.get("nonce") not in (None, nonce_digest(header["nonce"])):
            raise DeliveryRefused("the acknowledgement is for another delivery")
        if ack.get("state") == "consumed" and ack.get("nonce"):
            status = {"state": "consumed", "names": ack.get("names"),
                      "generation": ack.get("generation")}
        else:
            _seen(folder)
            status = {"state": "refused",
                      "reason": str(ack.get("reason") or "the runner refused the delivery")[:300]}
    except DeliveryRefused as exc:
        status = {"state": "refused" if not str(exc).startswith("timeout") else "timeout",
                  "reason": str(exc)}
    except (KeyError, ValueError):
        status = {"state": "error", "reason": "the writer was started with bad arguments"}
    except OSError as exc:
        status = {"state": "error", "reason": f"the delivery could not be written "
                                              f"({type(exc).__name__}, errno {exc.errno})"}
    finally:
        zero(data)
        if status.get("state") != "consumed" and folder and leaf:
            for name in (leaf, f".{leaf}.tmp"):
                _remove(os.path.join(folder, name))
        out.write(json.dumps(status, sort_keys=True) + "\n")
        out.flush()
    return 0 if status.get("state") == "consumed" else 1


def _seen(folder: str) -> None:
    """Tell a refusing runner its reason was read (it waits REFUSAL_LINGER at most)."""
    try:
        _publish(folder, SEEN, {"state": "seen"})
    except OSError:
        pass


def _read_all(fd: int, limit: int) -> bytearray:
    buf = bytearray()
    while len(buf) < limit:
        chunk = os.read(fd, min(65536, limit - len(buf)))
        if not chunk:
            break
        buf += chunk
    return buf


def writer_program() -> str:
    """This file's source: what the worker runs in the box to deliver."""
    with open(__file__, encoding="utf-8") as fh:
        return fh.read()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--deliver"]:
        return deliver(args[1:])
    print("usage: box_bootstrap.py --deliver --dir D --leaf L --max N --ready S --ack S "
          "--execution ID --generation G  (the envelope on stdin)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
