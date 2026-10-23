"""Exact bounded file observations for the P3 host-client ABI (P1; ABI A2, A7).

This module only observes files. It walks every path component from '/' with a
no-follow type check, opens each one read-only relative to its parent
descriptor, and reads one bounded regular file. A FileRead is caller-held
evidence data: it is not a filesystem capability, an access grant, an issuer or
a verified target, and nothing here turns it into one.

What is guaranteed (ABI A2.2), exactly these five things:
1. a component whose observed type is not the required one (symlink, FIFO,
   device, socket, or a non-directory where a directory is required) is
   rejected before it is opened;
2. every open uses exactly O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC, plus
   O_DIRECTORY for directories;
3. an opened descriptor whose dev/ino/type differs from the precheck is refused;
4. a FIFO raced in after a regular precheck is opened without waiting for a
   writer (O_NONBLOCK) and then refused by (3);
5. every descriptor is closed on every outcome.

The precheck and the open are not one atomic step: the name can change between
them, and the identity check runs only after the open. A non-regular node raced
in after the precheck is refused after it has been opened, and no claim is made
about any side effect of that open. The reader issues no write, create, rename,
chmod or unlink call. Same-UID isolation is not claimed.
docs/architecture/ops-host-binding-files.md has the whole contract.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass

__all__ = [
    "CODES",
    "FileRead",
    "Stamp",
    "TargetRefused",
    "read_private_file",
    "read_release_file",
    "recheck_files",
]

# ABI A7: the exact closed vocabulary, owned by this module.
CODES = (
    "TARGET_CONTEXT_MISSING",
    "TARGET_ISSUER_UNTRUSTED",
    "TARGET_PUBLICATION_INVALID",
    "TARGET_SELECTOR_MISSING",
    "TARGET_SELECTOR_AMBIGUOUS",
    "TARGET_BINDING_INVALID",
    "TARGET_SCHEMA_MISMATCH",
    "TARGET_SOURCE_MISSING",
    "TARGET_SOURCE_DRIFT",
    "TARGET_REVIEW_MISSING",
    "TARGET_EVIDENCE_INVALID",
)
_PUBLICATION_INVALID = "TARGET_PUBLICATION_INVALID"
_SOURCE_MISSING = "TARGET_SOURCE_MISSING"
_SOURCE_DRIFT = "TARGET_SOURCE_DRIFT"
_EVIDENCE_INVALID = "TARGET_EVIDENCE_INVALID"

MAX_CAP = 16777216  # A1 document cap, and the largest byte_length
MAX_READS = 65536  # A1 files limit for one recheck batch
MAX_PATH_BYTES = 1024  # A1 P grammar
PRIVATE_MODE = 0o600  # A2.3 private leaf
DIRECTORY_MODE = 0o700  # A2.3 supplied root and every directory below it
_CHUNK = 1 << 20  # step of the bounded read loop

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_LEAF_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC

_COMPONENT = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REF_KEYS = frozenset(("path", "sha256", "byte_length"))
_STAMP_INTS = ("dev", "ino", "uid", "mode", "size", "mtime_ns", "ctime_ns", "nlink")


class TargetRefused(ValueError):
    """A fixed local refusal: args, str and repr hold exactly the code."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in CODES:
            raise TypeError("unknown refusal code")
        super().__init__(code)
        self.__code = code

    @property
    def code(self) -> str:
        return self.__code


@dataclass(frozen=True, slots=True)
class Stamp:
    """One node's full fstat observation; path is relative to the supplied root."""

    path: str
    dev: int
    ino: int
    uid: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    nlink: int


class FileRead:
    """One bounded file observation: plain, immutable, caller-held data.

    Fields: root, ref, raw, uid, mode, cap, stamps. No descriptor is kept.
    ref returns a fresh dict on every access, so nobody holds an alias.
    repr and str show only the Ref path, hash and length, never raw.
    The constructor stores what it is given; recheck_files validates it.
    """

    __slots__ = ("_root", "_ref", "_raw", "_uid", "_mode", "_cap", "_stamps")

    def __init__(self, *, root: str, ref: dict, raw: bytes, uid: int, mode: int, cap: int,
                 stamps: tuple[Stamp, ...]) -> None:
        if type(ref) is dict:
            ref = dict(ref)
        for name, value in (("_root", root), ("_ref", ref), ("_raw", raw), ("_uid", uid),
                            ("_mode", mode), ("_cap", cap), ("_stamps", stamps)):
            object.__setattr__(self, name, value)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("FileRead is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("FileRead is immutable")

    @property
    def root(self) -> str:
        return self._root

    @property
    def ref(self) -> dict:
        ref = self._ref
        return dict(ref) if type(ref) is dict else ref

    @property
    def raw(self) -> bytes:
        return self._raw

    @property
    def uid(self) -> int:
        return self._uid

    @property
    def mode(self) -> int:
        return self._mode

    @property
    def cap(self) -> int:
        return self._cap

    @property
    def stamps(self) -> tuple[Stamp, ...]:
        return self._stamps

    def __repr__(self) -> str:
        values = _ref_values(getattr(self, "_ref", None), min_length=0, cap=MAX_CAP)
        if values is None:
            return "FileRead(ref=<invalid>)"
        path, sha256, length = values
        return f"FileRead(path={path!r}, sha256={sha256!r}, byte_length={length})"

    __str__ = __repr__


def read_private_file(root: str, ref: dict, *, uid: int, cap: int) -> FileRead:
    """Observe a private publication file: 0o700 directories, leaf exactly 0o600.

    Every refusal of this route is TARGET_PUBLICATION_INVALID, except a change
    seen during the read itself (TARGET_SOURCE_DRIFT).
    """
    values = None
    if _root_ok(root) and _exact_int(uid, 0) and _exact_int(cap, 1, MAX_CAP):
        values = _ref_values(ref, min_length=1, cap=cap)
    if values is None:
        raise TargetRefused(_PUBLICATION_INVALID)
    return _read(root, values, uid, PRIVATE_MODE, cap, _PUBLICATION_INVALID)


def read_release_file(root: str, ref: dict, *, uid: int, mode: int, cap: int) -> FileRead:
    """Observe a release source file: 0o700 directories, leaf exactly mode.

    An explicit zero byte_length is allowed here (a source observation), never
    on the private route. Every refusal is TARGET_SOURCE_MISSING, except a
    change seen during the read itself (TARGET_SOURCE_DRIFT).
    """
    values = None
    if (_root_ok(root) and _exact_int(uid, 0) and _exact_int(mode, 0, 0o7777)
            and _exact_int(cap, 1, MAX_CAP)):
        values = _ref_values(ref, min_length=0, cap=cap)
    if values is None:
        raise TargetRefused(_SOURCE_MISSING)
    return _read(root, values, uid, mode, cap, _SOURCE_MISSING)


def recheck_files(reads: tuple[FileRead, ...]) -> None:
    """Re-observe earlier reads; return None only if nothing changed.

    The whole batch is validated before the first filesystem call; any invalid
    entry refuses TARGET_EVIDENCE_INVALID and no entry is rechecked. Then each
    entry is walked and read again; any difference in a stamp, the bytes, the
    hash or the length refuses TARGET_SOURCE_DRIFT.
    """
    batch = _validated_batch(reads)
    if batch is None:
        raise TargetRefused(_EVIDENCE_INVALID)
    for root, path, sha256, length, raw, uid, mode, cap, stamps in batch:
        fresh = None
        try:
            fresh = _observe(root, path, uid, mode, cap, length, _SOURCE_DRIFT, _SOURCE_DRIFT)
        except OSError:
            fresh = None
        if fresh is None or not _same_observation(fresh, raw, sha256, length, stamps):
            raise TargetRefused(_SOURCE_DRIFT)


# A2.1: argument and batch validation. Pure: no filesystem call.

def _exact_int(value: object, low: int, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def _root_ok(root: object) -> bool:
    if type(root) is not str or not root.startswith("/") or "\x00" in root or "\\" in root:
        return False
    try:
        root.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return root == "/" or all(part not in ("", ".", "..") for part in root[1:].split("/"))


def _path_ok(path: object) -> bool:
    if type(path) is not str or not path or len(path) > MAX_PATH_BYTES:
        return False
    return all(_COMPONENT.fullmatch(part) and part not in (".", "..") for part in path.split("/"))


def _ref_values(ref: object, *, min_length: int, cap: int) -> tuple[str, str, int] | None:
    if type(ref) is not dict or len(ref) != len(_REF_KEYS):
        return None
    if any(type(key) is not str for key in ref) or set(ref) != _REF_KEYS:
        return None
    path, sha256, length = ref["path"], ref["sha256"], ref["byte_length"]
    if not _path_ok(path) or type(sha256) is not str or not _SHA256.fullmatch(sha256):
        return None
    if not _exact_int(length, min_length, cap):
        return None
    return path, sha256, length


def _walk_names(path: str) -> tuple[str, ...]:
    """The A2 stamps walk: '.', then each '/'-joined prefix of path, ending with path."""
    parts = path.split("/")
    return (".",) + tuple("/".join(parts[: index + 1]) for index in range(len(parts)))


def _stamp_ok(item: object) -> bool:
    if type(item) is not Stamp or type(getattr(item, "path", None)) is not str:
        return False
    return all(_exact_int(getattr(item, name, None), 0) for name in _STAMP_INTS)


def _validated_entry(entry: object) -> tuple | None:
    if type(entry) is not FileRead:
        return None
    try:
        root, ref, raw = entry._root, entry._ref, entry._raw
        uid, mode, cap, stamps = entry._uid, entry._mode, entry._cap, entry._stamps
    except AttributeError:
        return None
    if not (_root_ok(root) and _exact_int(uid, 0) and _exact_int(mode, 0, 0o7777)
            and _exact_int(cap, 1, MAX_CAP)):
        return None
    values = _ref_values(ref, min_length=0, cap=cap)
    if values is None or type(raw) is not bytes or len(raw) != values[2]:
        return None
    if type(stamps) is not tuple or not stamps or not all(_stamp_ok(item) for item in stamps):
        return None
    if tuple(item.path for item in stamps) != _walk_names(values[0]):
        return None
    return (root, *values, raw, uid, mode, cap, stamps)


def _validated_batch(reads: object) -> list[tuple] | None:
    if type(reads) is not tuple or not 1 <= len(reads) <= MAX_READS:
        return None
    batch = []
    for entry in reads:
        record = _validated_entry(entry)
        if record is None:
            return None
        batch.append(record)
    return batch


# A2.2-A2.4: the walk and the bounded read. Read-only observations only.

def _read(root: str, values: tuple[str, str, int], uid: int, mode: int, cap: int,
          refused: str) -> FileRead:
    path, sha256, length = values
    observed = None
    try:
        observed = _observe(root, path, uid, mode, cap, length, refused, _SOURCE_DRIFT)
    except OSError:
        observed = None
    if observed is None:
        raise TargetRefused(refused)
    raw, stamps = observed
    if not _digest_ok(raw, sha256, length):
        raise TargetRefused(refused)
    return FileRead(root=root, ref={"path": path, "sha256": sha256, "byte_length": length},
                    raw=raw, uid=uid, mode=mode, cap=cap, stamps=stamps)


def _observe(root: str, path: str, uid: int, mode: int, cap: int, length: int, refused: str,
             drift: str) -> tuple[bytes, tuple[Stamp, ...]]:
    """Walk '/' -> root -> each directory of path -> leaf; return (raw, stamps).

    Ancestors above root are type- and identity-checked, not stamped and not
    held to 0o700. Stamps cover root ('.'), each directory below it and the leaf.
    """
    held: list[int] = []
    try:
        fd, st = _open_top(held, refused)
        for name in root[1:].split("/") if root != "/" else ():
            fd, st = _open_dir(held, fd, name, refused)
        stamps = [_dir_stamp(".", st, uid, refused)]
        parts = path.split("/")
        for index in range(len(parts) - 1):
            fd, st = _open_dir(held, fd, parts[index], refused)
            stamps.append(_dir_stamp("/".join(parts[: index + 1]), st, uid, refused))
        raw, last = _read_leaf(held, fd, parts[-1], uid, mode, cap, length, refused, drift)
        stamps.append(_stamp(path, last, refused))
        return raw, tuple(stamps)
    finally:
        while held:
            _close(held.pop())


def _open_top(held: list[int], refused: str) -> tuple[int, os.stat_result]:
    before = os.stat("/", follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise TargetRefused(refused)
    held.append(os.open("/", _DIR_FLAGS))
    st = os.fstat(held[-1])
    if not _same_node(before, st):
        raise TargetRefused(refused)
    return held[-1], st


def _open_dir(held: list[int], parent: int, name: str, refused: str) -> tuple[int, os.stat_result]:
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise TargetRefused(refused)
    held.append(os.open(name, _DIR_FLAGS, dir_fd=parent))
    fd = held[-1]
    st = os.fstat(fd)
    if not _same_node(before, st):
        raise TargetRefused(refused)
    held.remove(parent)
    _close(parent)
    return fd, st


def _dir_stamp(name: str, st: os.stat_result, uid: int, refused: str) -> Stamp:
    if not (stat.S_ISDIR(st.st_mode) and st.st_uid == uid and st.st_mode & 0o7777 == DIRECTORY_MODE):
        raise TargetRefused(refused)
    return _stamp(name, st, refused)


def _read_leaf(held: list[int], parent: int, name: str, uid: int, mode: int, cap: int, length: int,
               refused: str, drift: str) -> tuple[bytes, os.stat_result]:
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise TargetRefused(refused)
    held.append(os.open(name, _LEAF_FLAGS, dir_fd=parent))
    fd = held[-1]
    first = os.fstat(fd)
    if not _same_node(before, first) or not _leaf_ok(first, uid, mode):
        raise TargetRefused(refused)
    if first.st_size > cap or first.st_size != length:
        raise TargetRefused(refused)
    raw = _read_exact(fd, length, refused)
    last = os.fstat(fd)
    if not _same_stamp(_stamp(name, first, refused), _stamp(name, last, drift)):
        raise TargetRefused(drift)
    if not _leaf_ok(last, uid, mode):
        raise TargetRefused(drift)
    named = _named(parent, name)
    if named is None or not _same_name(named, last):
        raise TargetRefused(drift)
    return raw, last


def _named(parent: int, name: str) -> os.stat_result | None:
    """A2.4 final no-follow lookup of the leaf's name; None when the name is gone.

    The name was there at the precheck of this same read, so its loss is a change
    seen during the read (drift), not a missing file. Other errors stay errors.
    """
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _leaf_ok(st: os.stat_result, uid: int, mode: int) -> bool:
    return (stat.S_ISREG(st.st_mode) and st.st_uid == uid and st.st_mode & 0o7777 == mode
            and st.st_nlink == 1)


def _read_exact(fd: int, length: int, refused: str) -> bytes:
    """Read exactly length bytes in a bounded loop, then require EOF."""
    chunks = []
    remaining = length
    while remaining > 0:
        chunk = os.read(fd, min(remaining, _CHUNK))
        if not chunk:
            raise TargetRefused(refused)
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(fd, 1):
        raise TargetRefused(refused)
    return b"".join(chunks)


def _stamp(path: str, st: os.stat_result, refused: str) -> Stamp:
    item = Stamp(path=path, dev=st.st_dev, ino=st.st_ino, uid=st.st_uid, mode=st.st_mode,
                 size=st.st_size, mtime_ns=st.st_mtime_ns, ctime_ns=st.st_ctime_ns, nlink=st.st_nlink)
    if not _stamp_ok(item):
        raise TargetRefused(refused)
    return item


def _same_node(a: os.stat_result, b: os.stat_result) -> bool:
    """A2.2 identity: same dev, ino and file type."""
    return a.st_dev == b.st_dev and a.st_ino == b.st_ino and stat.S_IFMT(a.st_mode) == stat.S_IFMT(b.st_mode)


def _same_name(named: os.stat_result, held: os.stat_result) -> bool:
    """A2.4 final named identity: the name still names the inode that was read."""
    return _same_node(named, held)


def _same_stamp(a: Stamp, b: Stamp) -> bool:
    """A2.4 full stamp equality, field by field."""
    return ((a.path, a.dev, a.ino, a.uid, a.mode, a.size, a.mtime_ns, a.ctime_ns, a.nlink)
            == (b.path, b.dev, b.ino, b.uid, b.mode, b.size, b.mtime_ns, b.ctime_ns, b.nlink))


def _digest_ok(raw: bytes, sha256: str, length: int) -> bool:
    """A2.4 full raw SHA256 and exact length."""
    return len(raw) == length and hashlib.sha256(raw).hexdigest() == sha256


def _same_observation(fresh: tuple[bytes, tuple[Stamp, ...]], raw: bytes, sha256: str, length: int,
                      stamps: tuple[Stamp, ...]) -> bool:
    fresh_raw, fresh_stamps = fresh
    if len(fresh_stamps) != len(stamps):
        return False
    if not all(_same_stamp(old, new) for old, new in zip(stamps, fresh_stamps, strict=True)):
        return False
    return fresh_raw == raw and _digest_ok(fresh_raw, sha256, length)


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
