"""Bounded trusted-host history. No default path, provisioning, repair or caller.

This is not an authorization or malicious-admin boundary. The mandatory semantic
validator owns the closed protocol payloads; this module owns custody, envelope
validation, full writes and synchronization. A missing file is never virgin.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from temper_ai.observability.usage_feed_cursor import CursorError, canonical_uuid

MAX_RECORD_BYTES = 65536
MAX_HISTORY_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 4096
ZERO_DIGEST = "0" * 64
KINDS = frozenset({"ADMISSION", "INTENT", "PREPARED-RECEIPT", "COMPLETE", "ABANDONED"})
_DIGEST = re.compile(r"[0-9a-f]{64}", re.ASCII)
SemanticValidator = Callable[[tuple["JournalRecord", ...]], None]


class JournalError(RuntimeError):
    """Fixed errors only: paths, payloads and OS exception strings stay private."""

    def __init__(self, code: str = "epoch-history-blocked") -> None:
        self.code = code
        super().__init__(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise JournalError() from None


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def require_digest(value: Any) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise JournalError()
    return value


def closed(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise JournalError()
    return value


@dataclass(frozen=True)
class JournalHead:
    sequence: int
    checksum: str

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or not 0 <= self.sequence <= MAX_RECORDS:
            raise JournalError()
        require_digest(self.checksum)
        if (self.sequence == 0) != (self.checksum == ZERO_DIGEST):
            raise JournalError()

    def payload(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "checksum": self.checksum}

    @classmethod
    def parse(cls, value: Any) -> JournalHead:
        row = closed(value, {"sequence", "checksum"})
        return cls(row["sequence"], row["checksum"])


EMPTY_HEAD = JournalHead(0, ZERO_DIGEST)


@dataclass(frozen=True, repr=False)
class JournalRecord:
    sequence: int
    checksum: str
    previous: str
    source_instance: str
    kind: str
    # Stored as canonical bytes, never a mutable caller-owned dictionary.
    _payload: bytes

    @property
    def data(self) -> dict[str, Any]:
        return json.loads(self._payload)

    @property
    def head(self) -> JournalHead:
        return JournalHead(self.sequence, self.checksum)

    def body(self) -> dict[str, Any]:
        return {"version": 1, "sequence": self.sequence, "previous": self.previous,
                "source_instance": self.source_instance, "kind": self.kind, "data": self.data}

    def wire(self) -> bytes:
        return canonical_bytes({**self.body(), "checksum": self.checksum}) + b"\n"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JournalError()
        result[key] = value
    return result


def validate_bytes(raw: bytes, source_instance: str, validator: SemanticValidator) -> tuple[JournalRecord, ...]:
    """No torn suffix, duplicate keys, noncanonical encoding or partial salvage."""
    if not raw or len(raw) > MAX_HISTORY_BYTES or not raw.endswith(b"\n"):
        raise JournalError()
    records: list[JournalRecord] = []
    for line in raw.splitlines(keepends=True):
        if len(line) > MAX_RECORD_BYTES or len(records) >= MAX_RECORDS:
            raise JournalError()
        try:
            row = closed(json.loads(line, object_pairs_hook=_unique_object),
                         {"version", "sequence", "previous", "source_instance", "kind", "data", "checksum"})
            if (type(row["version"]) is not int or row["version"] != 1
                    or type(row["sequence"]) is not int or row["sequence"] != len(records) + 1
                    or row["source_instance"] != source_instance or row["kind"] not in KINDS
                    or type(row["data"]) is not dict
                    or row["previous"] != (records[-1].checksum if records else ZERO_DIGEST)):
                raise JournalError()
            checksum = require_digest(row["checksum"])
            body = {key: value for key, value in row.items() if key != "checksum"}
            if digest(body) != checksum or canonical_bytes(row) + b"\n" != line:
                raise JournalError()
            records.append(JournalRecord(row["sequence"], checksum, row["previous"],
                                         source_instance, row["kind"], canonical_bytes(row["data"])))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise JournalError() from None
    result = tuple(records)
    validator(result)
    return result


def _protected(fd: int, directory: bool = False) -> None:
    info = os.fstat(fd)
    right_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not right_type or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or (not directory and info.st_nlink != 1)):
        raise JournalError()


def _same_inode(parent: int, name: str, fd: int) -> None:
    actual, held = os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(fd)
    if (actual.st_dev, actual.st_ino) != (held.st_dev, held.st_ino):
        raise JournalError()
    _protected(fd)


def _open_file(parent: int, name: str, *, create: bool) -> tuple[int, bool]:
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_APPEND
    created = False
    try:
        if create:
            try:
                fd = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
                created = True
            except FileExistsError:
                fd = os.open(name, flags, dir_fd=parent)
        else:
            fd = os.open(name, flags, dir_fd=parent)
        try:
            _protected(fd)
            _same_inode(parent, name, fd)
            if created:
                os.fsync(fd)
                os.fsync(parent)
            return fd, created
        except BaseException:
            os.close(fd)
            raise
    except OSError:
        raise JournalError() from None


class JournalSession:
    """A held source-journal mutex. Any write/sync failure poisons this session."""

    def __init__(self, parent: int, fd: int, lock: int, name: str, source: str,
                 records: tuple[JournalRecord, ...], size: int, validator: SemanticValidator) -> None:
        self._parent, self._fd, self._lock, self._name = parent, fd, lock, name
        self.source_instance = source
        self._records, self._size, self._validator = records, size, validator
        self._active, self._confirmed = True, False

    def _require(self) -> None:
        if not self._active:
            raise JournalError()
        _same_inode(self._parent, self._name, self._fd)
        _same_inode(self._parent, self._name + ".lock", self._lock)
        if os.fstat(self._fd).st_size != self._size:
            raise JournalError()

    @property
    def records(self) -> tuple[JournalRecord, ...]:
        self._require()
        return self._records

    @property
    def head(self) -> JournalHead:
        self._require()
        return self._records[-1].head if self._records else EMPTY_HEAD

    def confirm_history(self) -> None:
        """Explicitly sync validated bytes AFTER authority/head/control verification.

        This does not repair/truncate anything. After uncertain synchronization a
        new exact-head recovery authorization is needed, never an automatic retry.
        """
        self._require()
        try:
            os.fsync(self._fd)
            os.fsync(self._parent)
            self._confirmed = True
        except OSError:
            self._active = False
            raise JournalError("epoch-history-sync-failed") from None

    def append(self, kind: str, data: Mapping[str, Any]) -> JournalRecord:
        self._require()
        if not self._confirmed or kind not in KINDS or len(self._records) >= MAX_RECORDS:
            raise JournalError()
        body: dict[str, Any] = {"version": 1, "source_instance": self.source_instance,
                "sequence": self.head.sequence + 1, "previous": self.head.checksum,
                "kind": kind, "data": dict(data)}
        record = JournalRecord(body["sequence"], digest(body), body["previous"],
                               self.source_instance, kind, canonical_bytes(body["data"]))
        wire = record.wire()
        if len(wire) > MAX_RECORD_BYTES or self._size + len(wire) > MAX_HISTORY_BYTES:
            raise JournalError("epoch-history-full")
        self._validator((*self._records, record))
        try:
            view = memoryview(wire)
            while view:
                written = os.write(self._fd, view)
                if written <= 0:
                    raise OSError()
                view = view[written:]
            os.fsync(self._fd)
        except OSError:
            self._active = False
            raise JournalError("epoch-history-sync-failed") from None
        self._size += len(wire)
        self._records = (*self._records, record)
        return record


class HostJournal:
    """One approved canonical file per source, shared by EVERY supported operator.

    Parent must already be protected/provisioned; there is no default production
    path. Separate aliases/copies do not form a mutex and are NOT supported.
    A single fixed lock inode serializes all uses, including wrong-source attempts.
    """

    def __init__(self, path: Path, source_instance: str, validator: SemanticValidator) -> None:
        try:
            canonical_uuid(source_instance)
        except CursorError:
            raise JournalError() from None
        self.path, self.source_instance, self.validator = path.absolute(), source_instance, validator

    @contextmanager
    def locked(self, expected: JournalHead, *, virgin: bool = False,
               timeout: float = 2.0) -> Iterator[JournalSession]:
        """Creation requires a separately validated explicit ADMISSION, never absence.

        `virgin` is internal plumbing only: the transition layer checks a closed
        external VirginAdmission/authority before using it. An existing empty file
        still refuses. Caller must append that ADMISSION before yielding custody.
        """
        parent = lock = fd = None
        session = None
        try:
            if (self.path.parent.resolve(strict=True) != self.path.parent
                    or type(timeout) not in (int, float) or not 0 < timeout <= 3):
                raise JournalError()
            parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            _protected(parent, directory=True)
            may_create = virgin and expected == EMPTY_HEAD
            lock, _ = _open_file(parent, self.path.name + ".lock", create=may_create)
            end = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= end:
                        raise JournalError("epoch-host-busy") from None
                    time.sleep(min(0.01, max(0, end - time.monotonic())))
            fd, created = _open_file(parent, self.path.name, create=may_create)
            size = os.fstat(fd).st_size
            if size > MAX_HISTORY_BYTES:
                raise JournalError()
            raw = bytearray()
            while len(raw) <= MAX_HISTORY_BYTES:
                block = os.read(fd, min(65536, MAX_HISTORY_BYTES + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            if len(raw) != size:
                raise JournalError()
            records = validate_bytes(bytes(raw), self.source_instance, self.validator) if raw else ()
            if not records and not (created and virgin and expected == EMPTY_HEAD):
                raise JournalError()
            session = JournalSession(parent, fd, lock, self.path.name, self.source_instance, records, size, self.validator)
            if session.head != expected:
                raise JournalError("epoch-history-head-changed")
            yield session
            session._require()
            if not session.records:
                raise JournalError()
        except OSError:
            raise JournalError() from None
        finally:
            if session is not None:
                session._active = False
            for opened in (fd, lock, parent):
                if opened is not None:
                    os.close(opened)
