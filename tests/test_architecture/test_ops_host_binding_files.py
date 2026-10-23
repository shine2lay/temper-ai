"""P1 exact bounded file reader (ABI A2/A7), on synthetic temporary roots only.

Every fixture is built in this file, inside the test's own temporary directory.
Nothing reads a real publication, host_dir or private root, and no chmod, link
or rename touches anything outside that directory. The rows are the paper's F1
table (r4 CASE-REQUIREMENTS.md): row F1-X has test_f1_x_n (one deliberate fault
with its exact code) and test_f1_x_c (its own clean twin), and each variant of a
family has its own N id and its own C id. Known clean cases come first.

Where an ordinary user cannot arrange a case for real (another owner, a device
node, another dev number, a race at one exact step), a test-local wrapper around
one syscall changes one observation. That proves the reader's check, not OS
access control or same-UID isolation.
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
import errno
import hashlib
import importlib.util
import io
import os
import socket
import stat
import sys
import threading
import time
import traceback
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "configs" / "architecture" / "bin" / "ops_host_binding_files.py"
SPEC = importlib.util.spec_from_file_location("ops_host_binding_files", MODULE_PATH)
files = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = files
SPEC.loader.exec_module(files)

# The real calls, taken before any test wraps them; fixtures and race actions use these.
REAL = types.SimpleNamespace(
    open=os.open, close=os.close, read=os.read, write=os.write, stat=os.stat, fstat=os.fstat,
    listdir=os.listdir, unlink=os.unlink, rename=os.rename, mkfifo=os.mkfifo, mkdir=os.mkdir,
    chmod=os.chmod, utime=os.utime, link=os.link, symlink=os.symlink, readlink=os.readlink,
)

PI, SM = "TARGET_PUBLICATION_INVALID", "TARGET_SOURCE_MISSING"
SD, EI = "TARGET_SOURCE_DRIFT", "TARGET_EVIDENCE_INVALID"
CODE = {"private": PI, "release": SM}
ROUTES = ("private", "release")
UID = os.geteuid()
CAP = 65536
HARD_TIMEOUT = 3.0
SENTINEL = b"P1_SENTINEL_ENV=raw-env-5f2c-never-shown"
BODY = b'{"schema":"p1-fixture/1","env":"' + SENTINEL + b'"}\n'
LEAF = "a/b/leaf.json"
EXPECTED_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
EXPECTED_LEAF_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
STAT_FIELDS = ("st_mode", "st_ino", "st_dev", "st_nlink", "st_uid", "st_gid", "st_size",
               "st_atime_ns", "st_mtime_ns", "st_ctime_ns")
STAMP_INTS = ("dev", "ino", "uid", "mode", "size", "mtime_ns", "ctime_ns", "nlink")
EXPECTED_CODES = (
    "TARGET_CONTEXT_MISSING", "TARGET_ISSUER_UNTRUSTED", "TARGET_PUBLICATION_INVALID",
    "TARGET_SELECTOR_MISSING", "TARGET_SELECTOR_AMBIGUOUS", "TARGET_BINDING_INVALID",
    "TARGET_SCHEMA_MISMATCH", "TARGET_SOURCE_MISSING", "TARGET_SOURCE_DRIFT",
    "TARGET_REVIEW_MISSING", "TARGET_EVIDENCE_INVALID",
)
ROWS = (
    "F1-PATH-SYMLINK-ROOT", "F1-PATH-SYMLINK-DIR", "F1-PATH-SYMLINK-LEAF", "F1-PATH-FIFO",
    "F1-PATH-DEVICE", "F1-PATH-SOCKET", "F1-FLAGS", "F1-FD-IDENTITY", "F1-FIFO-RACE",
    "F1-DIR-OWNER", "F1-DIR-MODE", "F1-LEAF-OWNER", "F1-LEAF-MODE", "F1-LEAF-NLINK",
    "F1-FSTAT-CAP", "F1-SHORT", "F1-EOF", "F1-FULL-STAMP", "F1-FINAL-NAME", "F1-RECHECK-DIR",
    "F1-RECHECK-LEAF", "F1-HASH", "F1-ARG-TYPE", "F1-ARG-RANGE", "F1-ARG-PATH", "F1-ARG-REF",
    "F1-ARG-READS-CONTAINER", "F1-ARG-READS-ENTRY", "F1-ARG-READS-FIELD", "F1-ARG-READS-LATER",
    "F1-REPR", "F1-CLEANUP", "F1-BITE-HASH", "F1-BITE-STAMP",
)


class StrSub(str):
    pass


class IntSub(int):
    pass


class DictSub(dict):
    pass


class TupleSub(tuple):
    pass


class SubRead(files.FileRead):
    __slots__ = ()


class SubStamp(files.Stamp):
    __slots__ = ()


class FlagViolation(Exception):
    """Raised by the test-local flag assertion when an open lacks the required flags."""


# ---------------------------------------------------------------------------
# Synthetic fixtures (temporary roots only)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exists(path: Path) -> bool:
    try:
        REAL.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def put(path: Path, body: bytes, mode: int) -> None:
    """Create one synthetic regular file (exclusive create), then set its exact mode."""
    fd = REAL.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(body)
        while view:
            view = view[REAL.write(fd, view):]
    finally:
        REAL.close(fd)
    set_mode(path, mode)


def set_mode(path: Path, mode: int) -> None:
    REAL.chmod(path, mode)
    got = stat.S_IMODE(REAL.stat(path, follow_symlinks=False).st_mode)
    if got != mode:
        raise AssertionError(f"fixture precondition: mode {oct(mode)} did not stick ({oct(got)})")


def plant(root: Path, path: str, body: bytes, mode: int) -> None:
    """root/path with every missing directory at 0o700 and the leaf at mode."""
    node = root
    if not exists(node):
        REAL.mkdir(node, 0o700)
        set_mode(node, 0o700)
    parts = path.split("/")
    for name in parts[:-1]:
        node = node / name
        if not exists(node):
            REAL.mkdir(node, 0o700)
            set_mode(node, 0o700)
    put(node / parts[-1], body, mode)


@dataclasses.dataclass
class Tree:
    root: str
    path: str
    body: bytes
    route: str
    mode: int
    file_mode: int

    @property
    def ref(self) -> dict:
        return {"path": self.path, "sha256": sha(self.body), "byte_length": len(self.body)}

    def node(self, rel: str) -> Path:
        return Path(self.root) if rel == "." else Path(self.root, rel)

    @property
    def leaf(self) -> Path:
        return self.node(self.path)

    def walk(self) -> tuple[str, ...]:
        parts = self.path.split("/")
        return (".",) + tuple("/".join(parts[: i + 1]) for i in range(len(parts)))


def build(tmp_path: Path, route: str = "private", *, path: str = LEAF, body: bytes = BODY,
          leaf_mode: int | None = None, root_name: str = "root") -> Tree:
    set_mode(tmp_path, 0o755)  # an ordinary ancestor above the root, deliberately not 0o700
    default = 0o600 if route == "private" else 0o644
    file_mode = default if leaf_mode is None else leaf_mode
    root = tmp_path / root_name
    plant(root, path, body, file_mode)
    return Tree(root=str(root), path=path, body=body, route=route,
                mode=0o600 if route == "private" else file_mode, file_mode=file_mode)


def call(route: str, root, ref, *, uid=UID, cap=CAP, mode=0o644):
    if route == "private":
        return files.read_private_file(root, ref, uid=uid, cap=cap)
    return files.read_release_file(root, ref, uid=uid, mode=mode, cap=cap)


def read(tree: Tree, **over):
    args = {"root": tree.root, "ref": tree.ref, "uid": UID, "cap": CAP, "mode": tree.mode}
    args.update(over)
    return call(tree.route, args["root"], args["ref"], uid=args["uid"], cap=args["cap"], mode=args["mode"])


def two_reads(tmp_path: Path) -> tuple[Tree, object, object]:
    """The stable real fixture batch: one private and one release FileRead on one synthetic root."""
    tree = build(tmp_path)
    plant(Path(tree.root), "a/rel.json", b"release-body\n", 0o644)
    first = read(tree)
    second = files.read_release_file(tree.root, {"path": "a/rel.json", "sha256": sha(b"release-body\n"),
                                                 "byte_length": 13}, uid=UID, mode=0o644, cap=CAP)
    return tree, first, second


def assert_read(fr, tree: Tree) -> None:
    assert type(fr) is files.FileRead
    assert fr.root == tree.root and fr.ref == tree.ref
    assert sha(fr.raw) == sha(tree.body)  # digests only: raw never reaches a diagnostic
    assert tuple(item.path for item in fr.stamps) == tree.walk()


def forge(fr, **changes):
    fields = {"root": fr.root, "ref": fr.ref, "raw": fr.raw, "uid": fr.uid, "mode": fr.mode,
              "cap": fr.cap, "stamps": fr.stamps}
    fields.update(changes)
    return files.FileRead(**fields)


def forge_stamp(fr, index: int, **changes):
    stamps = list(fr.stamps)
    stamps[index] = dataclasses.replace(stamps[index], **changes)
    return forge(fr, stamps=tuple(stamps))


def replace_with_copy(path: Path, body: bytes, mode: int) -> None:
    """Give the name a new inode holding equal bytes (same mode, nlink 1)."""
    twin = path.with_name(path.name + ".new")
    put(twin, body, mode)
    REAL.rename(twin, path)


def append(path: Path, extra: bytes) -> None:
    fd = REAL.open(path, os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC)
    try:
        REAL.write(fd, extra)
    finally:
        REAL.close(fd)


def older(path: Path) -> None:
    """Move mtime back one second (an explicit, deterministic stamp change)."""
    st = REAL.stat(path, follow_symlinks=False)
    REAL.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns - 10**9), follow_symlinks=False)


def make_socket(path: Path) -> None:
    """A real socket node, bound through /proc/self/fd so the path length never matters."""
    dfd = REAL.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.bind(f"/proc/self/fd/{dfd}/{path.name}")
    finally:
        REAL.close(dfd)
    assert stat.S_ISSOCK(REAL.stat(path, follow_symlinks=False).st_mode)


# ---------------------------------------------------------------------------
# Outcomes and the intended-code assertion

def outcome(fn):
    try:
        return fn(), None
    except files.TargetRefused as exc:
        return None, exc


def must_refuse(result, exc, code: str):
    """The intended-code assertion: exactly this code, and nothing but the code."""
    if exc is None:
        raise AssertionError(f"accepted, expected {code}")
    if exc.code != code:
        raise AssertionError(f"refused {exc.code}, expected {code}")
    if exc.args != (code,) or str(exc) != code or repr(exc) != f"TargetRefused('{code}')":
        raise AssertionError("refusal carries more than its code")
    if exc.__cause__ is not None or exc.__context__ is not None:
        raise AssertionError("refusal chains another exception")
    return exc


def refused(fn, code: str):
    return must_refuse(*outcome(fn), code)


def assert_no_raw(*texts: str) -> None:
    """Fails when the sentinel's bytes appear in any text (in any common rendering)."""
    for text in texts:
        for needle in (SENTINEL.decode(), repr(SENTINEL)[2:-1], SENTINEL.hex()):
            if needle in text:
                raise AssertionError("raw bytes leaked")


# ---------------------------------------------------------------------------
# The filesystem-call spy: every entry point the module could reach

READ_POINTS = (
    (os, "open"), (os, "stat"), (os, "lstat"), (os, "fstat"), (os, "read"), (os, "pread"), (os, "readv"),
    (os, "preadv"), (os, "close"), (os, "access"), (os, "listdir"), (os, "scandir"), (os, "readlink"),
    (os, "walk"), (os, "fwalk"), (os, "statvfs"), (os, "fstatvfs"), (os, "getxattr"), (os, "listxattr"),
    (os, "sendfile"), (os, "dup"), (os, "getcwd"),
    (os.path, "realpath"), (os.path, "abspath"), (os.path, "exists"), (os.path, "lexists"),
    (os.path, "isfile"), (os.path, "isdir"), (os.path, "islink"), (os.path, "ismount"),
    (os.path, "getsize"), (os.path, "getmtime"), (os.path, "getatime"), (os.path, "getctime"),
    (os.path, "samefile"), (builtins, "open"), (io, "open"), (io, "open_code"),
)
CHANGE_POINTS = (
    (os, "write"), (os, "pwrite"), (os, "writev"), (os, "unlink"), (os, "remove"), (os, "rename"),
    (os, "replace"), (os, "chmod"), (os, "fchmod"), (os, "chown"), (os, "fchown"), (os, "lchown"),
    (os, "mkdir"), (os, "makedirs"), (os, "rmdir"), (os, "removedirs"), (os, "symlink"), (os, "link"),
    (os, "utime"), (os, "truncate"), (os, "ftruncate"), (os, "mkfifo"), (os, "mknod"), (os, "chdir"),
    (os, "fchdir"), (os, "setxattr"), (os, "removexattr"), (os, "system"), (os, "popen"), (os, "fork"),
    (os, "execv"), (os, "execve"), (os, "execvp"), (os, "posix_spawn"), (os, "posix_spawnp"), (os, "kill"),
)
CHANGE_LABELS = {f"{owner.__name__}.{name}" for owner, name in CHANGE_POINTS}


class FsSpy:
    """Counts calls to every reachable filesystem entry point (open/io.open, the stat
    family incl. dir_fd forms, reads, scandir/listdir, realpath and the os.path helpers)
    and every mutating, exec or spawn call, from this thread, inside counting() only."""

    def __init__(self, monkeypatch) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self._on = False
        self._thread = threading.get_ident()
        for owner, name in READ_POINTS + CHANGE_POINTS:
            real = getattr(owner, name, None)
            if callable(real):
                monkeypatch.setattr(owner, name, self._wrap(f"{owner.__name__}.{name}", real))

    def _wrap(self, label: str, real):
        def spy(*args, **kwargs):
            if self._on and threading.get_ident() == self._thread:
                first = args[0] if args and isinstance(args[0], (str, bytes, os.PathLike)) else None
                self.calls.append((label, None if first is None else os.fsdecode(first)))
            return real(*args, **kwargs)
        return spy

    @contextmanager
    def counting(self):
        self.calls.clear()
        self._on = True
        try:
            yield self
        finally:
            self._on = False


def refused_without_fs(spy: FsSpy, fn, code: str):
    with spy.counting():
        result = outcome(fn)
    calls = list(spy.calls)
    assert calls == [], f"filesystem calls before the refusal: {calls}"
    return must_refuse(*result, code)


# ---------------------------------------------------------------------------
# Controlled syscall observations and races

def fake(st, **changes):
    """One stat observation with some fields changed (the module reads st_* attributes only)."""
    fields = {name: getattr(st, name) for name in STAT_FIELDS}
    fields.update(changes)
    return types.SimpleNamespace(**fields)


def node_key(path: Path) -> tuple[int, int]:
    st = REAL.stat(path, follow_symlinks=False)
    return st.st_dev, st.st_ino


def nth_call(state: dict, nth: int, cycle: int | None) -> bool:
    """Count one matching call; true for the nth one (with cycle: the nth of every cycle calls)."""
    state["seen"] += 1
    position = state["seen"] if cycle is None else (state["seen"] - 1) % cycle + 1
    return position == nth


def patch_fstat(monkeypatch, node: Path, nth: int, *, cycle: int | None = None, error: int | None = None,
                **changes) -> dict:
    """Change (or fail) the nth fstat of one node's descriptor; other calls pass through.
    A read makes two fstat calls on its leaf, so cycle=2 hits the same step of every read."""
    key = node_key(node)
    state = {"seen": 0, "hit": 0}
    inner = os.fstat

    def fstat(fd):
        st = inner(fd)
        if (st.st_dev, st.st_ino) == key and nth_call(state, nth, cycle):
            state["hit"] += 1
            if error is not None:
                raise OSError(error, os.strerror(error))
            return fake(st, **changes)
        return st

    monkeypatch.setattr(os, "fstat", fstat)
    return state


def patch_name_stat(monkeypatch, parent: Path, name: str, nth: int, *, cycle: int | None = None,
                    error: int | None = None, **changes) -> dict:
    """Change (or fail) the nth no-follow stat of name relative to parent's descriptor.
    A read makes two: the precheck and the final name check (cycle=2: every read's nth)."""
    parent_key = node_key(parent)
    state = {"seen": 0, "hit": 0}
    inner = os.stat

    def stat_(path, *, dir_fd=None, follow_symlinks=True):
        if dir_fd is not None and path == name and not follow_symlinks:
            pst = REAL.fstat(dir_fd)
            if (pst.st_dev, pst.st_ino) == parent_key and nth_call(state, nth, cycle):
                state["hit"] += 1
                if error is not None:
                    raise OSError(error, os.strerror(error))
                return fake(inner(path, dir_fd=dir_fd, follow_symlinks=False), **changes)
        return inner(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "stat", stat_)
    return state


def before_open(monkeypatch, name: str, action) -> dict:
    """Run action(dir_fd) right before the first os.open of name: between precheck and open."""
    state = {"hit": 0}
    inner = os.open

    def open_(path, flags, mode=0o777, *, dir_fd=None):
        if path == name and dir_fd is not None and not state["hit"]:
            state["hit"] += 1
            action(dir_fd)
        return inner(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_)
    return state


def on_read(monkeypatch, node: Path, handler) -> dict:
    """handler(call_number, fd, n, real_read) answers every os.read of one node's descriptor."""
    key = node_key(node)
    state = {"calls": 0}
    inner = os.read

    def read_(fd, n):
        st = REAL.fstat(fd)
        if (st.st_dev, st.st_ino) == key:
            state["calls"] += 1
            return handler(state["calls"], fd, n, inner)
        return inner(fd, n)

    monkeypatch.setattr(os, "read", read_)
    return state


def record_opens(monkeypatch) -> list:
    opened = []
    inner = os.open

    def open_(path, flags, mode=0o777, *, dir_fd=None):
        opened.append(os.fsdecode(path))
        return inner(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_)
    return opened


def record_check(monkeypatch, name: str) -> list:
    """Record a module check's answers without changing them."""
    results = []
    inner = getattr(files, name)

    def check(*args):
        result = inner(*args)
        results.append(result)
        return result

    monkeypatch.setattr(files, name, check)
    return results


def assert_flags(monkeypatch) -> list:
    """The flag assertion: every open this thread makes must use exactly the required flags
    for its node type (another thread's opens pass through unchecked)."""
    seen = []
    inner = os.open
    me = threading.get_ident()

    def open_(path, flags, mode=0o777, *, dir_fd=None):
        if threading.get_ident() != me:
            return inner(path, flags, mode, dir_fd=dir_fd)
        st = REAL.stat(path, dir_fd=dir_fd, follow_symlinks=False)
        want = EXPECTED_DIR_FLAGS if stat.S_ISDIR(st.st_mode) else EXPECTED_LEAF_FLAGS
        seen.append(flags == want)
        if flags != want:
            raise FlagViolation("an open used other flags than the required set")
        return inner(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_)
    return seen


def open_count(tree: Tree) -> int:
    """Opens of one read: '/', each root component, each directory of the path and the leaf."""
    return 1 + len(tree.root.strip("/").split("/")) + len(tree.path.split("/"))


def to_fifo(name: str):
    def action(dir_fd: int) -> None:
        REAL.unlink(name, dir_fd=dir_fd)
        REAL.mkfifo(name, 0o600, dir_fd=dir_fd)
    return action


def bounded(fn, release=None):
    """Run fn under the hard timeout: (timed_out, value, error). A timeout is recorded
    first; only then is a still-blocked reader released so the test can finish."""
    box = {}

    def work():
        try:
            box["value"] = fn()
        except Exception as exc:
            box["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(HARD_TIMEOUT)
    timed_out = worker.is_alive()
    if timed_out and release is not None:
        release()
        worker.join(HARD_TIMEOUT)
    if worker.is_alive():
        raise AssertionError("reader still blocked after the hard timeout")
    return timed_out, box.get("value"), box.get("error")


def release_fifo(path: Path):
    def release() -> None:
        deadline = time.monotonic() + HARD_TIMEOUT
        while time.monotonic() < deadline:
            try:
                fd = REAL.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                time.sleep(0.02)
                continue
            REAL.close(fd)
            return
    return release


def in_area(target: str, area: Path) -> bool:
    """True for '/', an ancestor of area, area itself or anything under it (deleted too)."""
    top = str(area)
    return target == top or target.startswith(top + "/") or target in {str(p) for p in area.parents}


def open_fds(area: Path) -> set[int]:
    """This process's open descriptors on nodes the reader can open in a test: every walk
    runs from '/' through area's ancestors into area. Another thread's sockets, pipes or
    files elsewhere are not this test's descriptors, so they never count as its leak."""
    alive = set()
    for name in REAL.listdir("/proc/self/fd"):
        fd = int(name)
        try:
            REAL.fstat(fd)
            target = REAL.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue
        if in_area(target, area):
            alive.add(fd)
    return alive


@pytest.fixture(autouse=True)
def no_descriptor_leak(tmp_path):
    before = open_fds(tmp_path)
    yield
    leaked = open_fds(tmp_path) - before
    assert not leaked, f"descriptor leak: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# Known clean cases first

def test_happy_private_read_full_observation(tmp_path, monkeypatch):
    tree = build(tmp_path)
    spy = FsSpy(monkeypatch)
    with spy.counting():
        fr = read(tree)
    assert_read(fr, tree)
    assert (fr.uid, fr.mode, fr.cap) == (UID, 0o600, CAP)
    assert type(fr.raw) is bytes and type(fr.stamps) is tuple
    for item, rel in zip(fr.stamps, tree.walk(), strict=True):
        st = REAL.stat(tree.node(rel), follow_symlinks=False)
        assert type(item) is files.Stamp
        assert (item.dev, item.ino, item.uid, item.mode, item.size, item.mtime_ns, item.ctime_ns, item.nlink) == (
            st.st_dev, st.st_ino, st.st_uid, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)
    labels = [label for label, _ in spy.calls]
    assert labels.count("os.open") == open_count(tree)
    assert not set(labels) & CHANGE_LABELS


def test_happy_release_read(tmp_path):
    tree = build(tmp_path, "release")
    fr = read(tree)
    assert_read(fr, tree)
    assert (fr.uid, fr.mode, fr.cap) == (UID, 0o644, CAP)


def test_happy_zero_length_release_source(tmp_path):
    tree = build(tmp_path, "release", body=b"")
    fr = read(tree)
    assert_read(fr, tree)
    assert fr.ref["byte_length"] == 0 and fr.raw == b""
    assert files.recheck_files((fr,)) is None


def test_happy_recheck_stable_batch(tmp_path, monkeypatch):
    _, first, second = two_reads(tmp_path)
    spy = FsSpy(monkeypatch)
    with spy.counting():
        assert files.recheck_files((first, second)) is None
    assert not {label for label, _ in spy.calls} & CHANGE_LABELS


def test_happy_fileread_is_immutable_and_unaliased(tmp_path):
    tree = build(tmp_path)
    ref = tree.ref
    fr = files.read_private_file(tree.root, ref, uid=UID, cap=CAP)
    ref["path"] = "other"
    assert fr.ref == tree.ref  # no alias to the caller's dict
    view = fr.ref
    view["sha256"] = "0" * 64
    assert fr.ref == tree.ref  # every access is a fresh copy
    for name in ("root", "ref", "raw", "uid", "mode", "cap", "stamps", "_raw", "extra"):
        with pytest.raises(AttributeError):
            setattr(fr, name, None)
    with pytest.raises(AttributeError):
        del fr.raw
    with pytest.raises(dataclasses.FrozenInstanceError):
        fr.stamps[0].ino = 1
    assert files.recheck_files((fr,)) is None


def test_eleven_code_pin():
    assert files.CODES == EXPECTED_CODES
    assert issubclass(files.TargetRefused, ValueError)
    for code in EXPECTED_CODES:
        exc = files.TargetRefused(code)
        assert (exc.code, exc.args, str(exc), repr(exc)) == (code, (code,), code, f"TargetRefused('{code}')")
        with pytest.raises(AttributeError):
            exc.code = "TARGET_SOURCE_DRIFT"
    for bad in ("TARGET_OTHER", "", None, StrSub("TARGET_SOURCE_DRIFT"), 3):
        with pytest.raises(TypeError):
            files.TargetRefused(bad)


def test_static_surface_read_only_standard_library():
    module = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {"__future__", "hashlib", "os", "re", "stat", "dataclasses"}

    def attrs(owner: str) -> set[str]:
        return {node.attr for node in ast.walk(module)
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == owner}

    assert attrs("os") == {"open", "stat", "fstat", "read", "close", "stat_result", "O_RDONLY", "O_DIRECTORY",
                           "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC"}
    assert attrs("hashlib") == {"sha256"}
    assert attrs("stat") == {"S_ISDIR", "S_ISREG", "S_IFMT"}
    called = {node.func.id for node in ast.walk(module) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"open", "print", "exec", "eval", "compile", "__import__", "input", "breakpoint"}


def test_every_f1_row_has_its_own_n_and_c():
    assert len(ROWS) == 34 and len(set(ROWS)) == 34
    names = set(globals())
    for row in ROWS:
        base = "test_" + row.lower().replace("-", "_")
        assert base + "_n" in names and base + "_c" in names, row


# ---------------------------------------------------------------------------
# C1: typed nofollow opens, identity check, bounded FIFO race

ROOT_LINKS = ("root", "ancestor")


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("where", ROOT_LINKS)
def test_f1_path_symlink_root_n(tmp_path, monkeypatch, route, where):
    if where == "root":
        build(tmp_path, route, root_name="real")
        REAL.symlink("real", tmp_path / "root")
        root, link = str(tmp_path / "root"), "root"
    else:
        REAL.mkdir(tmp_path / "base", 0o755)
        plant(tmp_path / "base" / "root", LEAF, BODY, 0o600 if route == "private" else 0o644)
        REAL.symlink("base", tmp_path / "link")
        root, link = str(tmp_path / "link" / "root"), "link"
    opened = record_opens(monkeypatch)
    refused(lambda: call(route, root, build_ref(), mode=0o644), CODE[route])
    assert link not in opened  # rejected before open, never followed


def build_ref() -> dict:
    return {"path": LEAF, "sha256": sha(BODY), "byte_length": len(BODY)}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("where", ROOT_LINKS)
def test_f1_path_symlink_root_c(tmp_path, route, where):
    if where == "root":
        tree = build(tmp_path, route, root_name="real")
    else:
        REAL.mkdir(tmp_path / "base", 0o755)
        tree = build(tmp_path / "base", route)
    assert_read(read(tree), tree)


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_symlink_dir_n(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    REAL.rename(tree.node("a"), tree.node("a-real"))
    REAL.symlink("a-real", tree.node("a"))
    opened = record_opens(monkeypatch)
    refused(lambda: read(tree), CODE[route])
    assert "a" not in opened


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_symlink_dir_c(tmp_path, route):
    tree = build(tmp_path, route)
    assert_read(read(tree), tree)


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_symlink_leaf_n(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    REAL.rename(tree.leaf, tree.leaf.with_name("leaf-real.json"))
    REAL.symlink("leaf-real.json", tree.leaf)
    opened = record_opens(monkeypatch)
    refused(lambda: read(tree), CODE[route])
    assert "leaf.json" not in opened


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_symlink_leaf_c(tmp_path, route):
    tree = build(tmp_path, route)
    assert_read(read(tree), tree)


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_fifo_n(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    REAL.unlink(tree.leaf)
    REAL.mkfifo(tree.leaf, 0o600)
    opened = record_opens(monkeypatch)
    timed_out, value, error = bounded(lambda: read(tree), release_fifo(tree.leaf))
    assert not timed_out, "hard timeout: a FIFO leaf blocked the reader"
    must_refuse(value, error, CODE[route])
    assert "leaf.json" not in opened  # refused by the pre-open type check


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_fifo_c(tmp_path, route):
    tree = build(tmp_path, route)
    timed_out, value, error = bounded(lambda: read(tree))
    assert not timed_out and error is None
    assert_read(value, tree)


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_device_n(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    state = patch_name_stat(monkeypatch, tree.leaf.parent, "leaf.json", 1,
                            st_mode=stat.S_IFCHR | tree.file_mode)
    opened = record_opens(monkeypatch)
    refused(lambda: read(tree), CODE[route])
    assert state["hit"] == 1 and "leaf.json" not in opened  # refused before the leaf open


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_device_c(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    state = patch_name_stat(monkeypatch, tree.leaf.parent, "leaf.json", 1)
    assert_read(read(tree), tree)
    assert state["hit"] == 1


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_socket_n(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    REAL.unlink(tree.leaf)
    make_socket(tree.leaf)
    opened = record_opens(monkeypatch)
    refused(lambda: read(tree), CODE[route])
    assert "leaf.json" not in opened


@pytest.mark.parametrize("route", ROUTES)
def test_f1_path_socket_c(tmp_path, route):
    tree = build(tmp_path, route)
    assert_read(read(tree), tree)


FLAG_CASES = {
    "leaf-nofollow": ("_LEAF_FLAGS", os.O_NOFOLLOW),
    "leaf-nonblock": ("_LEAF_FLAGS", os.O_NONBLOCK),
    "leaf-cloexec": ("_LEAF_FLAGS", os.O_CLOEXEC),
    "dir-nofollow": ("_DIR_FLAGS", os.O_NOFOLLOW),
    "dir-nonblock": ("_DIR_FLAGS", os.O_NONBLOCK),
    "dir-cloexec": ("_DIR_FLAGS", os.O_CLOEXEC),
    "dir-directory": ("_DIR_FLAGS", os.O_DIRECTORY),
}


@pytest.mark.parametrize("case", FLAG_CASES)
def test_f1_flags_n(tmp_path, monkeypatch, case):
    tree = build(tmp_path)
    name, flag = FLAG_CASES[case]
    monkeypatch.setattr(files, name, getattr(files, name) & ~flag)
    seen = assert_flags(monkeypatch)
    with pytest.raises(FlagViolation):
        read(tree)  # the flag assertion fails, so no read is accepted
    assert seen and seen[-1] is False


@pytest.mark.parametrize("case", FLAG_CASES)
def test_f1_flags_c(tmp_path, monkeypatch, case):
    tree = build(tmp_path)
    seen = assert_flags(monkeypatch)
    assert_read(read(tree), tree)
    assert len(seen) == open_count(tree) and all(seen)


IDENTITY_CASES = ("dev", "ino", "type", "leaf-race", "dir-race")


def arrange_identity(monkeypatch, tree: Tree, case: str, fault: bool) -> dict:
    leaf = tree.leaf
    st = REAL.stat(leaf, follow_symlinks=False)
    if case in ("dev", "ino", "type"):
        changes = {"dev": {"st_dev": st.st_dev + 1}, "ino": {"st_ino": st.st_ino + 1},
                   "type": {"st_mode": stat.S_IFIFO | tree.file_mode}}[case]
        return patch_fstat(monkeypatch, leaf, 1, **(changes if fault else {}))
    if case == "leaf-race":
        return before_open(monkeypatch, "leaf.json",
                           (lambda _fd: replace_with_copy(leaf, tree.body, tree.file_mode)) if fault else (lambda _fd: None))

    def swap_dir(_fd: int) -> None:
        node = tree.node("a/b")
        REAL.rename(node, node.with_name("b-old"))
        plant(Path(tree.root), tree.path, tree.body, tree.file_mode)

    return before_open(monkeypatch, "b", swap_dir if fault else (lambda _fd: None))


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", IDENTITY_CASES)
def test_f1_fd_identity_n(tmp_path, monkeypatch, route, case):
    tree = build(tmp_path, route)
    state = arrange_identity(monkeypatch, tree, case, True)
    refused(lambda: read(tree), CODE[route])
    assert state["hit"] == 1


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", IDENTITY_CASES)
def test_f1_fd_identity_c(tmp_path, monkeypatch, route, case):
    tree = build(tmp_path, route)
    state = arrange_identity(monkeypatch, tree, case, False)
    assert_read(read(tree), tree)
    assert state["hit"] == 1


@pytest.mark.parametrize("route", ROUTES)
def test_f1_fifo_race_n(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    state = before_open(monkeypatch, "leaf.json", to_fifo("leaf.json"))
    checks = record_check(monkeypatch, "_same_node")
    timed_out, value, error = bounded(lambda: read(tree), release_fifo(tree.leaf))
    assert not timed_out, "hard timeout: the raced-in FIFO blocked the open"
    must_refuse(value, error, CODE[route])
    assert state["hit"] == 1 and checks[-1] is False  # refused by the opened-fd identity check


@pytest.mark.parametrize("route", ROUTES)
def test_f1_fifo_race_c(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    state = before_open(monkeypatch, "leaf.json", lambda _fd: None)
    timed_out, value, error = bounded(lambda: read(tree))
    assert not timed_out and error is None
    assert_read(value, tree)
    assert state["hit"] == 1


def test_fifo_race_watchdog_bite_without_nonblock(tmp_path, monkeypatch):
    """Bite: remove O_NONBLOCK and the raced FIFO open blocks; the watchdog must report it."""
    tree = build(tmp_path)
    monkeypatch.setattr(files, "_LEAF_FLAGS", files._LEAF_FLAGS & ~os.O_NONBLOCK)
    before_open(monkeypatch, "leaf.json", to_fifo("leaf.json"))
    timed_out, value, error = bounded(lambda: read(tree), release_fifo(tree.leaf))
    assert timed_out, "the hard timeout did not fire, so a blocked open would pass unnoticed"
    must_refuse(value, error, PI)


# ---------------------------------------------------------------------------
# C2: exact opened-fd owner, mode, type and nlink

OWNER_DIRS = (".", "a", "a/b")


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("where", OWNER_DIRS + ("uid-argument",))
def test_f1_dir_owner_n(tmp_path, monkeypatch, route, where):
    tree = build(tmp_path, route)
    if where == "uid-argument":
        refused(lambda: read(tree, uid=UID + 1), CODE[route])
        return
    state = patch_fstat(monkeypatch, tree.node(where), 1, st_uid=UID + 1)
    refused(lambda: read(tree), CODE[route])
    assert state["hit"] == 1


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("where", OWNER_DIRS + ("uid-argument",))
def test_f1_dir_owner_c(tmp_path, monkeypatch, route, where):
    tree = build(tmp_path, route)
    if where == "uid-argument":
        assert_read(read(tree, uid=UID), tree)
        return
    state = patch_fstat(monkeypatch, tree.node(where), 1)
    assert_read(read(tree), tree)
    assert state["hit"] == 1


DIR_MODES = (0o750, 0o755, 0o711, 0o500, 0o4700, 0o2700, 0o1700)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("mode", DIR_MODES, ids=oct)
@pytest.mark.parametrize("where", OWNER_DIRS)
def test_f1_dir_mode_n(tmp_path, route, mode, where):
    tree = build(tmp_path, route)
    set_mode(tree.node(where), mode)
    refused(lambda: read(tree), CODE[route])


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("mode", DIR_MODES, ids=oct)
@pytest.mark.parametrize("where", OWNER_DIRS)
def test_f1_dir_mode_c(tmp_path, route, mode, where):
    tree = build(tmp_path, route)
    set_mode(tree.node(where), 0o700)
    assert stat.S_IMODE(REAL.stat(tmp_path).st_mode) == 0o755  # ancestor not held to 0o700
    assert_read(read(tree), tree)


@pytest.mark.parametrize("route", ROUTES)
def test_f1_leaf_owner_n(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    state = patch_fstat(monkeypatch, tree.leaf, 1, st_uid=UID + 1)
    refused(lambda: read(tree), CODE[route])
    assert state["hit"] == 1


@pytest.mark.parametrize("route", ROUTES)
def test_f1_leaf_owner_c(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    state = patch_fstat(monkeypatch, tree.leaf, 1)
    assert_read(read(tree, uid=UID), tree)
    assert state["hit"] == 1


LEAF_MODES = [
    pytest.param(route, want, have, id=f"{route}-{oct(have)}-for-{oct(want)}")
    for route, want, have in (
        ("private", 0o600, 0o640), ("private", 0o600, 0o644), ("private", 0o600, 0o400),
        ("private", 0o600, 0o700), ("private", 0o600, 0o4600), ("private", 0o600, 0o2600),
        ("private", 0o600, 0o1600), ("release", 0o644, 0o640), ("release", 0o644, 0o664),
        ("release", 0o644, 0o4644), ("release", 0o644, 0o2644), ("release", 0o644, 0o1644),
        ("release", 0o2644, 0o644),
    )
]


@pytest.mark.parametrize(("route", "want", "have"), LEAF_MODES)
def test_f1_leaf_mode_n(tmp_path, route, want, have):
    tree = build(tmp_path, route, leaf_mode=have)
    refused(lambda: read(tree, mode=want), CODE[route])


@pytest.mark.parametrize(("route", "want", "have"), LEAF_MODES)
def test_f1_leaf_mode_c(tmp_path, route, want, have):
    tree = build(tmp_path, route, leaf_mode=want)
    fr = read(tree, mode=want)
    assert_read(fr, tree)
    assert fr.mode == want


@pytest.mark.parametrize("route", ROUTES)
def test_f1_leaf_nlink_n(tmp_path, route):
    tree = build(tmp_path, route)
    REAL.link(tree.leaf, tree.leaf.with_name("leaf-twin.json"))
    refused(lambda: read(tree), CODE[route])


@pytest.mark.parametrize("route", ROUTES)
def test_f1_leaf_nlink_c(tmp_path, route):
    tree = build(tmp_path, route)
    assert REAL.stat(tree.leaf).st_nlink == 1
    assert_read(read(tree), tree)


# ---------------------------------------------------------------------------
# C3: cap before allocation, exact size and EOF, full stamps, final name, recheck

@pytest.mark.parametrize("route", ROUTES)
def test_f1_fstat_cap_n(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route, body=b"123456789")
    state = on_read(monkeypatch, tree.leaf, lambda _n, fd, size, real: real(fd, size))
    ref = {"path": LEAF, "sha256": sha(b"12345678"), "byte_length": 8}
    refused(lambda: read(tree, ref=ref, cap=8), CODE[route])
    assert state["calls"] == 0  # refused before any body buffer was read


@pytest.mark.parametrize("route", ROUTES)
def test_f1_fstat_cap_c(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route, body=b"12345678")
    state = on_read(monkeypatch, tree.leaf, lambda _n, fd, size, real: real(fd, size))
    assert_read(read(tree, cap=8), tree)
    assert state["calls"] == 2  # the body, then the EOF read


SHORT_CASES = ("declared-longer", "read-loop")


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", SHORT_CASES)
def test_f1_short_n(tmp_path, monkeypatch, route, case):
    tree = build(tmp_path, route)
    if case == "declared-longer":
        ref = {"path": LEAF, "sha256": sha(BODY + b"?"), "byte_length": len(BODY) + 1}
        refused(lambda: read(tree, ref=ref), CODE[route])
        return

    def short(number, fd, size, real):
        return real(fd, size - 1) if number == 1 else b""

    state = on_read(monkeypatch, tree.leaf, short)
    refused(lambda: read(tree), CODE[route])
    assert state["calls"] == 2


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", SHORT_CASES)
def test_f1_short_c(tmp_path, monkeypatch, route, case):
    tree = build(tmp_path, route)
    state = on_read(monkeypatch, tree.leaf, lambda _n, fd, size, real: real(fd, size))
    assert_read(read(tree), tree)
    assert state["calls"] == 2


EOF_CASES = ("extra-byte", "growth")


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", EOF_CASES)
def test_f1_eof_n(tmp_path, monkeypatch, route, case):
    if case == "extra-byte":
        tree = build(tmp_path, route, body=BODY + b"!")
        refused(lambda: read(tree, ref=build_ref()), CODE[route])
        return
    tree = build(tmp_path, route)

    def grow(number, fd, size, real):
        if number == 2:
            append(tree.leaf, b"!")
        return real(fd, size)

    state = on_read(monkeypatch, tree.leaf, grow)
    refused(lambda: read(tree), CODE[route])  # never a prefix success
    assert state["calls"] == 2


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", EOF_CASES)
def test_f1_eof_c(tmp_path, monkeypatch, route, case):
    tree = build(tmp_path, route)
    state = on_read(monkeypatch, tree.leaf, lambda _n, fd, size, real: real(fd, size))
    assert_read(read(tree), tree)
    assert state["calls"] == 2


STAMP_CASES = STAMP_INTS + ("utime-during-read",)


def stamp_change(st, field: str) -> dict:
    if field == "mode":
        return {"st_mode": st.st_mode ^ 0o004}
    return {f"st_{field}": getattr(st, f"st_{field}") + 1}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("field", STAMP_CASES)
def test_f1_full_stamp_n(tmp_path, monkeypatch, route, field):
    tree = build(tmp_path, route)
    if field == "utime-during-read":
        state = on_read(monkeypatch, tree.leaf,
                        lambda number, fd, size, real: (older(tree.leaf) if number == 1 else None, real(fd, size))[1])
        refused(lambda: read(tree), SD)
        assert state["calls"] == 2
        return
    st = REAL.stat(tree.leaf)
    state = patch_fstat(monkeypatch, tree.leaf, 2, **stamp_change(st, field))
    refused(lambda: read(tree), SD)
    assert state["hit"] == 1


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("field", STAMP_CASES)
def test_f1_full_stamp_c(tmp_path, monkeypatch, route, field):
    tree = build(tmp_path, route)
    if field == "utime-during-read":
        state = on_read(monkeypatch, tree.leaf, lambda _n, fd, size, real: real(fd, size))
        assert_read(read(tree), tree)
        assert state["calls"] == 2
        return
    state = patch_fstat(monkeypatch, tree.leaf, 2)
    assert_read(read(tree), tree)
    assert state["hit"] == 1


NAME_CASES = ("other-inode", "other-dev", "missing", "real-replace")


def arrange_name(monkeypatch, tree: Tree, case: str, fault: bool) -> dict:
    if case == "real-replace":
        def handler(number, fd, size, real):
            if fault and number == 2:
                replace_with_copy(tree.leaf, tree.body, tree.file_mode)
            return real(fd, size)
        return on_read(monkeypatch, tree.leaf, handler)
    st = REAL.stat(tree.leaf)
    changes = {"other-inode": {"st_ino": st.st_ino + 1}, "other-dev": {"st_dev": st.st_dev + 1},
               "missing": {}}[case]
    if not fault:
        return patch_name_stat(monkeypatch, tree.leaf.parent, "leaf.json", 2)
    if case == "missing":
        return patch_name_stat(monkeypatch, tree.leaf.parent, "leaf.json", 2, error=errno.ENOENT)
    return patch_name_stat(monkeypatch, tree.leaf.parent, "leaf.json", 2, **changes)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", NAME_CASES)
def test_f1_final_name_n(tmp_path, monkeypatch, route, case):
    tree = build(tmp_path, route)
    state = arrange_name(monkeypatch, tree, case, True)
    refused(lambda: read(tree), SD)
    assert state["calls"] == 2 if case == "real-replace" else state["hit"] == 1


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", NAME_CASES)
def test_f1_final_name_c(tmp_path, monkeypatch, route, case):
    tree = build(tmp_path, route)
    state = arrange_name(monkeypatch, tree, case, False)
    assert_read(read(tree), tree)
    assert state["calls"] == 2 if case == "real-replace" else state["hit"] == 1


def swap_node(tree: Tree, rel: str) -> None:
    """Replace one directory by a new one holding the same tree (new inode, same bytes)."""
    node = tree.node(rel)
    REAL.rename(node, node.with_name(node.name + "-old"))
    plant(Path(tree.root), tree.path, tree.body, tree.file_mode)


RECHECK_DIRS = [pytest.param(where, change, id=f"{where}-{change}")
                for where in OWNER_DIRS for change in ("stamp", "identity")]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(("where", "change"), RECHECK_DIRS)
def test_f1_recheck_dir_n(tmp_path, route, where, change):
    tree = build(tmp_path, route)
    fr = read(tree)
    if change == "stamp":
        older(tree.node(where))
    else:
        swap_node(tree, where)
    refused(lambda: files.recheck_files((fr,)), SD)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(("where", "change"), RECHECK_DIRS)
def test_f1_recheck_dir_c(tmp_path, route, where, change):
    tree = build(tmp_path, route)
    fr = read(tree)
    assert files.recheck_files((fr,)) is None


RECHECK_LEAF = ("bytes", "hash", "length", "stamp", "name")


def change_leaf(tree: Tree, fr, change: str):
    if change == "bytes":
        fd = REAL.open(tree.leaf, os.O_WRONLY | os.O_CLOEXEC)
        try:
            REAL.write(fd, bytes([tree.body[0] ^ 1]))
        finally:
            REAL.close(fd)
    elif change == "hash":
        return forge(fr, ref={**fr.ref, "sha256": sha(b"another body")})
    elif change == "length":
        append(tree.leaf, b"!")
    elif change == "stamp":
        older(tree.leaf)
    else:
        replace_with_copy(tree.leaf, tree.body, tree.file_mode)  # equal bytes, new inode
    return fr


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("change", RECHECK_LEAF)
def test_f1_recheck_leaf_n(tmp_path, route, change):
    tree = build(tmp_path, route)
    held = change_leaf(tree, read(tree), change)
    refused(lambda: files.recheck_files((held,)), SD)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("change", RECHECK_LEAF)
def test_f1_recheck_leaf_c(tmp_path, route, change):
    tree = build(tmp_path, route)
    assert files.recheck_files((read(tree),)) is None


def flip(digest: str, index: int) -> str:
    return digest[:index] + ("1" if digest[index] == "0" else "0") + digest[index + 1:]


HASH_CASES = {"last-digit": lambda h: flip(h, 63), "first-digit": lambda h: flip(h, 0), "zeros": lambda h: "0" * 64}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", HASH_CASES)
def test_f1_hash_n(tmp_path, route, case):
    tree = build(tmp_path, route)
    refused(lambda: read(tree, ref={**tree.ref, "sha256": HASH_CASES[case](tree.ref["sha256"])}), CODE[route])


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", HASH_CASES)
def test_f1_hash_c(tmp_path, route, case):
    tree = build(tmp_path, route)
    assert_read(read(tree), tree)


def test_extra_negative_time_n(tmp_path, monkeypatch):
    """A stamp recheck_files would reject (time before 1970) is never handed out."""
    tree = build(tmp_path)
    state = patch_fstat(monkeypatch, tree.leaf, 1, st_mtime_ns=-1)
    refused(lambda: read(tree), PI)
    assert state["hit"] == 1


def test_extra_negative_time_c(tmp_path, monkeypatch):
    tree = build(tmp_path)
    state = patch_fstat(monkeypatch, tree.leaf, 1)
    assert_read(read(tree), tree)
    assert state["hit"] == 1


# ---------------------------------------------------------------------------
# C5: exact arguments before any filesystem call

ARG_TYPES = [
    ("root-bytes", "root", lambda t: t.root.encode()), ("root-path", "root", lambda t: Path(t.root)),
    ("root-subclass", "root", lambda t: StrSub(t.root)), ("root-none", "root", lambda t: None),
    ("ref-subclass", "ref", lambda t: DictSub(t.ref)), ("ref-proxy", "ref", lambda t: types.MappingProxyType(t.ref)),
    ("ref-pairs", "ref", lambda t: list(t.ref.items())), ("ref-none", "ref", lambda t: None),
    ("uid-true", "uid", lambda t: True), ("uid-false", "uid", lambda t: False),
    ("uid-float", "uid", lambda t: float(UID)), ("uid-str", "uid", lambda t: str(UID)),
    ("uid-subclass", "uid", lambda t: IntSub(UID)), ("uid-none", "uid", lambda t: None),
    ("cap-true", "cap", lambda t: True), ("cap-float", "cap", lambda t: float(CAP)),
    ("cap-str", "cap", lambda t: str(CAP)), ("cap-subclass", "cap", lambda t: IntSub(CAP)),
    ("mode-true", "mode", lambda t: True), ("mode-float", "mode", lambda t: float(t.mode)),
    ("mode-str", "mode", lambda t: oct(t.mode)), ("mode-subclass", "mode", lambda t: IntSub(t.mode)),
]
ARG_TYPE_CASES = [pytest.param(route, field, make, id=f"{route}-{name}")
                  for route in ROUTES for name, field, make in ARG_TYPES
                  if not (route == "private" and field == "mode")]


@pytest.mark.parametrize(("route", "field", "make"), ARG_TYPE_CASES)
def test_f1_arg_type_n(tmp_path, monkeypatch, route, field, make):
    tree = build(tmp_path, route)
    spy = FsSpy(monkeypatch)
    refused_without_fs(spy, lambda: read(tree, **{field: make(tree)}), CODE[route])


@pytest.mark.parametrize(("route", "field", "make"), ARG_TYPE_CASES)
def test_f1_arg_type_c(tmp_path, route, field, make):
    tree = build(tmp_path, route)
    assert_read(read(tree), tree)


ARG_RANGES = [
    ("uid-negative", {"uid": -1}, {"uid": UID}, None),
    ("cap-zero", {"cap": 0}, {"cap": len(BODY)}, None),
    ("cap-negative", {"cap": -1}, {"cap": len(BODY)}, None),
    ("cap-over-max", {"cap": files.MAX_CAP + 1}, {"cap": files.MAX_CAP}, None),
    ("length-over-cap", {"cap": len(BODY) - 1}, {"cap": len(BODY)}, None),
    ("mode-negative", {"mode": -1}, {"mode": 0o644}, 0o644),
    ("mode-over-max", {"mode": 0o10000}, {"mode": 0o7777}, 0o7777),
]
ARG_RANGE_CASES = [pytest.param(route, bad, good, leaf_mode, id=f"{route}-{name}")
                   for route in ROUTES for name, bad, good, leaf_mode in ARG_RANGES
                   if not (route == "private" and "mode" in bad)]


@pytest.mark.parametrize(("route", "bad", "good", "leaf_mode"), ARG_RANGE_CASES)
def test_f1_arg_range_n(tmp_path, monkeypatch, route, bad, good, leaf_mode):
    tree = build(tmp_path, route)
    spy = FsSpy(monkeypatch)
    refused_without_fs(spy, lambda: read(tree, **bad), CODE[route])


@pytest.mark.parametrize(("route", "bad", "good", "leaf_mode"), ARG_RANGE_CASES)
def test_f1_arg_range_c(tmp_path, route, bad, good, leaf_mode):
    tree = build(tmp_path, route, leaf_mode=leaf_mode)
    assert_read(read(tree, **good), tree)


LONG_1024 = "/".join(["x" * 127] * 7 + ["y" * 128])
ROOT_BAD = {
    "relative": lambda r: r[1:], "trailing-slash": lambda r: r + "/",
    "double-slash": lambda r: r.rsplit("/", 1)[0] + "//" + r.rsplit("/", 1)[1],
    "dot": lambda r: r.rsplit("/", 1)[0] + "/./" + r.rsplit("/", 1)[1],
    "dotdot": lambda r: r.rsplit("/", 1)[0] + "/../" + r.rsplit("/", 1)[1],
    "backslash": lambda r: r.rsplit("/", 1)[0] + "\\" + r.rsplit("/", 1)[1], "nul": lambda r: r + "\x00",
    "empty": lambda r: "", "surrogate": lambda r: r + "\udcff",
}
PATH_BAD = {
    "absolute": "/" + LEAF, "dot-first": "./" + LEAF, "dot-mid": "a/./b/leaf.json",
    "dotdot": "a/../a/b/leaf.json", "empty": "", "empty-component": "a//b/leaf.json",
    "trailing-slash": LEAF + "/", "backslash": "a\\b/leaf.json", "nul": LEAF + "\x00",
    "space": "a/b/leaf json", "non-ascii": "a/b/l\u00e9af.json", "component-129": "a/" + "x" * 129,
    "path-1025": "/".join(["x" * 127] * 8 + ["y"]),
}
PATH_GOOD = {"component-129": "a/" + "y" * 128, "path-1025": LONG_1024}
ARG_PATH_CASES = ([pytest.param(route, "root", name, id=f"{route}-root-{name}") for route in ROUTES for name in ROOT_BAD]
                  + [pytest.param(route, "path", name, id=f"{route}-path-{name}") for route in ROUTES for name in PATH_BAD])


@pytest.mark.parametrize(("route", "kind", "name"), ARG_PATH_CASES)
def test_f1_arg_path_n(tmp_path, monkeypatch, route, kind, name):
    tree = build(tmp_path, route)
    spy = FsSpy(monkeypatch)
    if kind == "root":
        refused_without_fs(spy, lambda: read(tree, root=ROOT_BAD[name](tree.root)), CODE[route])
    else:
        refused_without_fs(spy, lambda: read(tree, ref={**tree.ref, "path": PATH_BAD[name]}), CODE[route])


@pytest.mark.parametrize(("route", "kind", "name"), ARG_PATH_CASES)
def test_f1_arg_path_c(tmp_path, route, kind, name):
    tree = build(tmp_path, route, path=PATH_GOOD.get(name, LEAF) if kind == "path" else LEAF)
    assert len(tree.path.encode()) <= 1024
    assert_read(read(tree), tree)


REF_BAD = {
    "extra-key": lambda r: {**r, "note": "x"},
    "missing-key": lambda r: {k: v for k, v in r.items() if k != "sha256"},
    "key-subclass": lambda r: {StrSub("path"): r["path"], "sha256": r["sha256"], "byte_length": r["byte_length"]},
    "hash-upper": lambda r: {**r, "sha256": r["sha256"].upper()},
    "hash-short": lambda r: {**r, "sha256": r["sha256"][:63]},
    "hash-long": lambda r: {**r, "sha256": r["sha256"] + "0"},
    "hash-nonhex": lambda r: {**r, "sha256": "g" * 64},
    "hash-bytes": lambda r: {**r, "sha256": r["sha256"].encode()},
    "length-bool": lambda r: {**r, "byte_length": True},
    "length-negative": lambda r: {**r, "byte_length": -1},
    "length-float": lambda r: {**r, "byte_length": float(r["byte_length"])},
    "length-str": lambda r: {**r, "byte_length": str(r["byte_length"])},
    "length-over-max": lambda r: {**r, "byte_length": files.MAX_CAP + 1},
    "length-zero-control": lambda r: {**r, "byte_length": 0, "sha256": sha(b"")},
}
ARG_REF_CASES = [pytest.param(route, name, id=f"{route}-{name}") for route in ROUTES for name in REF_BAD
                 if not (route == "release" and name == "length-zero-control")]


@pytest.mark.parametrize(("route", "name"), ARG_REF_CASES)
def test_f1_arg_ref_n(tmp_path, monkeypatch, route, name):
    tree = build(tmp_path, route, body=b"" if name == "length-zero-control" else BODY)
    spy = FsSpy(monkeypatch)
    refused_without_fs(spy, lambda: read(tree, ref=REF_BAD[name](tree.ref)), CODE[route])


@pytest.mark.parametrize(("route", "name"), ARG_REF_CASES)
def test_f1_arg_ref_c(tmp_path, route, name):
    if name == "length-zero-control":  # explicit zero-length source is allowed, not a control file
        tree = build(tmp_path, "release", body=b"")
    else:
        tree = build(tmp_path, route)
    assert_read(read(tree), tree)


# ---------------------------------------------------------------------------
# C5: recheck_files validates its whole batch before the first filesystem call

CONTAINERS = {
    "list": lambda a, b: [a, b], "tuple-subclass": lambda a, b: TupleSub((a, b)),
    "empty": lambda a, b: (), "over-65536": lambda a, b: (a,) * (files.MAX_READS + 1),
}


@pytest.mark.parametrize("case", CONTAINERS)
def test_f1_arg_reads_container_n(tmp_path, monkeypatch, case):
    _, first, second = two_reads(tmp_path)
    spy = FsSpy(monkeypatch)
    refused_without_fs(spy, lambda: files.recheck_files(CONTAINERS[case](first, second)), EI)


@pytest.mark.parametrize("case", CONTAINERS)
def test_f1_arg_reads_container_c(tmp_path, monkeypatch, case):
    _, first, second = two_reads(tmp_path)
    assert files.recheck_files((first, second)) is None
    if case == "over-65536":  # the limit itself is accepted by the validator (pure, no recheck run)
        spy = FsSpy(monkeypatch)
        with spy.counting():
            assert files._validated_batch((first,) * files.MAX_READS) is not None
        assert spy.calls == []


def entry_like(fr, kind: str):
    fields = {"root": fr.root, "ref": fr.ref, "raw": fr.raw, "uid": fr.uid, "mode": fr.mode,
              "cap": fr.cap, "stamps": fr.stamps}
    if kind == "dict":
        return fields
    if kind == "tuple":
        return tuple(fields.values())
    if kind == "subclass":
        return SubRead(**fields)
    if kind == "duck":
        return types.SimpleNamespace(**fields, **{"_" + key: value for key, value in fields.items()})
    return object.__new__(files.FileRead)


ENTRY_KINDS = ("dict", "tuple", "subclass", "duck", "uninitialised")


@pytest.mark.parametrize("kind", ENTRY_KINDS)
def test_f1_arg_reads_entry_n(tmp_path, monkeypatch, kind):
    _, first, second = two_reads(tmp_path)
    spy = FsSpy(monkeypatch)
    refused_without_fs(spy, lambda: files.recheck_files((entry_like(first, kind),)), EI)


@pytest.mark.parametrize("kind", ENTRY_KINDS)
def test_f1_arg_reads_entry_c(tmp_path, kind):
    _, first, second = two_reads(tmp_path)
    assert files.recheck_files((first,)) is None


def walk_change(fr, case: str):
    stamps = fr.stamps
    changed = {
        "walk-missing": stamps[:1] + stamps[2:],
        "walk-extra": stamps + (stamps[-1],),
        "walk-reordered": (stamps[0], stamps[2], stamps[1]) + stamps[3:],
        "walk-renamed": (stamps[0], dataclasses.replace(stamps[1], path="x")) + stamps[2:],
        "walk-not-leaf": stamps[:-1],
    }[case]
    return forge(fr, stamps=changed)


FIELD_CASES = {
    "root-relative": lambda fr: forge(fr, root=fr.root[1:]),
    "root-trailing-slash": lambda fr: forge(fr, root=fr.root + "/"),
    "root-dotdot": lambda fr: forge(fr, root=fr.root + "/.."),
    "root-subclass": lambda fr: forge(fr, root=StrSub(fr.root)),
    "root-bytes": lambda fr: forge(fr, root=fr.root.encode()),
    "ref-subclass": lambda fr: forge(fr, ref=DictSub(fr.ref)),
    "ref-extra-key": lambda fr: forge(fr, ref={**fr.ref, "note": "x"}),
    "ref-missing-key": lambda fr: forge(fr, ref={k: v for k, v in fr.ref.items() if k != "sha256"}),
    "ref-path-dotdot": lambda fr: forge(fr, ref={**fr.ref, "path": "a/../a/b/leaf.json"}),
    "ref-hash-upper": lambda fr: forge(fr, ref={**fr.ref, "sha256": fr.ref["sha256"].upper()}),
    "ref-length-bool": lambda fr: forge(fr, ref={**fr.ref, "byte_length": True}),
    "ref-length-negative": lambda fr: forge(fr, ref={**fr.ref, "byte_length": -1}),
    "ref-length-over-cap": lambda fr: forge(fr, cap=fr.ref["byte_length"] - 1),
    "uid-bool": lambda fr: forge(fr, uid=True),
    "uid-negative": lambda fr: forge(fr, uid=-1),
    "uid-float": lambda fr: forge(fr, uid=float(fr.uid)),
    "mode-bool": lambda fr: forge(fr, mode=True),
    "mode-negative": lambda fr: forge(fr, mode=-1),
    "mode-over-max": lambda fr: forge(fr, mode=0o10000),
    "cap-bool": lambda fr: forge(fr, cap=True),
    "cap-zero": lambda fr: forge(fr, cap=0),
    "cap-over-max": lambda fr: forge(fr, cap=files.MAX_CAP + 1),
    "raw-bytearray": lambda fr: forge(fr, raw=bytearray(fr.raw)),
    "raw-memoryview": lambda fr: forge(fr, raw=memoryview(fr.raw)),
    "raw-str": lambda fr: forge(fr, raw=fr.raw.decode()),
    "raw-length": lambda fr: forge(fr, raw=fr.raw + b"!"),
    "stamps-list": lambda fr: forge(fr, stamps=list(fr.stamps)),
    "stamps-empty": lambda fr: forge(fr, stamps=()),
    "stamps-entry-tuple": lambda fr: forge(fr, stamps=(dataclasses.astuple(fr.stamps[0]),) + fr.stamps[1:]),
    "stamps-entry-subclass": lambda fr: forge(
        fr, stamps=(SubStamp(**dataclasses.asdict(fr.stamps[0])),) + fr.stamps[1:]),
    "stamp-path-bytes": lambda fr: forge_stamp(fr, 0, path=b"."),
    **{f"stamp-{name}-{kind}": (lambda fr, name=name, value=value: forge_stamp(fr, 3, **{name: value}))
       for name in STAMP_INTS for kind, value in (("str", "1"), ("bool", True), ("negative", -1))},
    **{case: (lambda fr, case=case: walk_change(fr, case))
       for case in ("walk-missing", "walk-extra", "walk-reordered", "walk-renamed", "walk-not-leaf")},
}


@pytest.mark.parametrize("case", FIELD_CASES)
def test_f1_arg_reads_field_n(tmp_path, monkeypatch, case):
    tree = build(tmp_path)
    fr = read(tree)
    held = FIELD_CASES[case](fr)
    spy = FsSpy(monkeypatch)
    refused_without_fs(spy, lambda: files.recheck_files((held,)), EI)


@pytest.mark.parametrize("case", FIELD_CASES)
def test_f1_arg_reads_field_c(tmp_path, case):
    tree = build(tmp_path)
    fr = read(tree)
    assert files.recheck_files((forge(fr),)) is None  # the same entry with every field exact


LATER_CASES = {
    "wrong-entry": lambda second: entry_like(second, "dict"),
    "wrong-field": lambda second: forge(second, raw=bytearray(second.raw)),
}


@pytest.mark.parametrize("case", LATER_CASES)
def test_f1_arg_reads_later_n(tmp_path, monkeypatch, case):
    _, first, second = two_reads(tmp_path)
    spy = FsSpy(monkeypatch)
    refused_without_fs(spy, lambda: files.recheck_files((first, LATER_CASES[case](second))), EI)
    # zero calls also means the valid first entry was not rechecked


@pytest.mark.parametrize("case", LATER_CASES)
def test_f1_arg_reads_later_c(tmp_path, monkeypatch, case):
    _, first, second = two_reads(tmp_path)
    spy = FsSpy(monkeypatch)
    with spy.counting():
        assert files.recheck_files((first, second)) is None
    opened = [arg for label, arg in spy.calls if label == "os.open"]
    assert "leaf.json" in opened and "rel.json" in opened  # the same spy counts both rechecks
    assert len(spy.calls) > 2 * len(opened) > 0


# ---------------------------------------------------------------------------
# C4: no raw bytes in repr, str, refusals or output

REPR_LEAKS = ("repr", "str", "exception", "output")


@pytest.mark.parametrize("leak", REPR_LEAKS)
def test_f1_repr_n(tmp_path, monkeypatch, capsys, leak):
    tree = build(tmp_path)
    fr = read(tree)
    if leak == "repr":
        monkeypatch.setattr(files.FileRead, "__repr__", lambda self: f"FileRead(raw={self.raw!r})")
        text = repr(fr)
    elif leak == "str":
        monkeypatch.setattr(files.FileRead, "__str__", lambda self: self.raw.decode())
        text = str(fr)
    elif leak == "exception":
        leaked = ValueError(fr.raw)
        text = "".join(traceback.format_exception(type(leaked), leaked, None))
    else:
        print(fr.raw)
        text = capsys.readouterr().out
    with pytest.raises(AssertionError, match="raw bytes leaked"):
        assert_no_raw(text)


@pytest.mark.parametrize("leak", REPR_LEAKS)
def test_f1_repr_c(tmp_path, monkeypatch, capsys, caplog, leak):
    tree = build(tmp_path)
    fr = read(tree)
    fixed = f"FileRead(path='{LEAF}', sha256='{sha(BODY)}', byte_length={len(BODY)})"
    assert repr(fr) == fixed and str(fr) == fixed and f"{fr}" == fixed
    assert repr(forge(fr, ref=None)) == "FileRead(ref=<invalid>)"
    texts = [repr(fr), str(fr), repr(fr.stamps), repr(fr.ref)]
    for fn in (lambda: read(tree, ref={**tree.ref, "sha256": "0" * 64}),
               lambda: files.recheck_files((forge(fr, ref={**fr.ref, "sha256": "0" * 64}),)),
               lambda: files.recheck_files((forge(fr, raw=bytearray(fr.raw)),))):
        _, exc = outcome(fn)
        assert exc is not None
        rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        texts += [str(exc), repr(exc), repr(exc.args), rendered]
        assert tree.root not in str(exc) + repr(exc) + repr(exc.args)
    captured = capsys.readouterr()
    texts += [captured.out, captured.err, caplog.text]
    assert_no_raw(*texts)


CLEANUP_STEPS = {
    "dir-fstat": PI, "leaf-fstat-first": PI, "leaf-read-body": PI, "leaf-read-eof": PI,
    "leaf-fstat-last": PI, "final-name-stat": PI, "predicate-refusal": PI, "recheck-leaf-read": SD,
    "success": None,
}


def inject(monkeypatch, tree: Tree, step: str):
    """Make one opened-descriptor step fail; returns the call to make."""
    leaf = tree.leaf
    if step == "dir-fstat":
        patch_fstat(monkeypatch, tree.node("a"), 1, error=errno.EIO)
    elif step == "leaf-fstat-first":
        patch_fstat(monkeypatch, leaf, 1, error=errno.EIO)
    elif step == "leaf-fstat-last":
        patch_fstat(monkeypatch, leaf, 2, error=errno.EIO)
    elif step in ("leaf-read-body", "leaf-read-eof"):
        failing = 1 if step == "leaf-read-body" else 2

        def fail(number, fd, size, real):
            if number == failing:
                raise OSError(errno.EIO, os.strerror(errno.EIO))
            return real(fd, size)

        on_read(monkeypatch, leaf, fail)
    elif step == "final-name-stat":
        patch_name_stat(monkeypatch, leaf.parent, "leaf.json", 2, error=errno.EIO)
    elif step == "predicate-refusal":
        set_mode(leaf, 0o640)
    elif step == "recheck-leaf-read":
        fr = read(tree)

        def fail_read(number, fd, size, real):
            raise OSError(errno.EIO, os.strerror(errno.EIO))

        on_read(monkeypatch, leaf, fail_read)
        return lambda: files.recheck_files((fr,))
    return lambda: read(tree)


@pytest.mark.parametrize("step", CLEANUP_STEPS)
def test_f1_cleanup_n(tmp_path, monkeypatch, step):
    """With closing switched off, the leak detector must see the same step's descriptors."""
    tree = build(tmp_path)
    fn = inject(monkeypatch, tree, step)
    kept = []
    monkeypatch.setattr(files, "_close", kept.append)
    before = open_fds(tmp_path)
    try:
        outcome(fn)
        leaked = open_fds(tmp_path) - before
        assert leaked and leaked == set(kept)  # the leak check goes red when a step leaks
    finally:
        for fd in kept:
            REAL.close(fd)


@pytest.mark.parametrize("step", CLEANUP_STEPS)
def test_f1_cleanup_c(tmp_path, monkeypatch, step):
    tree = build(tmp_path)
    fn = inject(monkeypatch, tree, step)
    before = open_fds(tmp_path)
    result, exc = outcome(fn)
    if CLEANUP_STEPS[step] is None:
        assert_read(result, tree)
    else:
        must_refuse(result, exc, CLEANUP_STEPS[step])
    assert open_fds(tmp_path) - before == set()


# ---------------------------------------------------------------------------
# Real check-disable bites (test-local; the module is untouched on disk)

@pytest.mark.parametrize("route", ROUTES)
def test_f1_bite_hash_n(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    wrong = {**tree.ref, "sha256": flip(tree.ref["sha256"], 63)}
    refused(lambda: read(tree, ref=wrong), CODE[route])  # enabled guard rejects N
    monkeypatch.setattr(files, "_digest_ok", lambda raw, sha256, length: True)
    with pytest.raises(AssertionError, match="accepted"):
        refused(lambda: read(tree, ref=wrong), CODE[route])  # disabled: intended-code assertion is red


@pytest.mark.parametrize("route", ROUTES)
def test_f1_bite_hash_c(tmp_path, monkeypatch, route):
    tree = build(tmp_path, route)
    assert_read(read(tree), tree)
    monkeypatch.setattr(files, "_digest_ok", lambda raw, sha256, length: True)
    assert_read(read(tree), tree)


BITE_STAMP_CASES = ("full-stamp", "final-name", "recheck-stamp")


def bite_stamp_case(monkeypatch, tree: Tree, case: str, fault: bool):
    """The call to make, and the counter of its injected observation (None for a real change).
    The injection hits every read, so the call made after the bite meets the same fault."""
    if case == "full-stamp":
        st = REAL.stat(tree.leaf)
        state = patch_fstat(monkeypatch, tree.leaf, 2, cycle=2,
                            **({"st_mtime_ns": st.st_mtime_ns + 1} if fault else {}))
        return (lambda: read(tree)), state
    if case == "final-name":
        st = REAL.stat(tree.leaf)
        state = patch_name_stat(monkeypatch, tree.leaf.parent, "leaf.json", 2, cycle=2,
                                **({"st_ino": st.st_ino + 1} if fault else {}))
        return (lambda: read(tree)), state
    fr = read(tree)
    if fault:
        older(tree.leaf)
    return (lambda: files.recheck_files((fr,))), None


@pytest.mark.parametrize("case", BITE_STAMP_CASES)
def test_f1_bite_stamp_n(tmp_path, monkeypatch, case):
    tree = build(tmp_path)
    fn, state = bite_stamp_case(monkeypatch, tree, case, True)
    refused(fn, SD)  # enabled guard rejects N
    check = "_same_name" if case == "final-name" else "_same_stamp"
    monkeypatch.setattr(files, check, lambda a, b: True)
    with pytest.raises(AssertionError, match="accepted"):
        refused(fn, SD)  # disabled: the intended SD goes missing
    assert state is None or state["hit"] == 2  # the same fault met both calls


@pytest.mark.parametrize("case", BITE_STAMP_CASES)
def test_f1_bite_stamp_c(tmp_path, monkeypatch, case):
    tree = build(tmp_path)
    fn, state = bite_stamp_case(monkeypatch, tree, case, False)
    first, exc = outcome(fn)
    assert exc is None
    check = "_same_name" if case == "final-name" else "_same_stamp"
    monkeypatch.setattr(files, check, lambda a, b: True)
    again, exc = outcome(fn)
    assert exc is None
    assert state is None or state["hit"] == 2
    if case != "recheck-stamp":
        assert_read(first, tree)
        assert_read(again, tree)
