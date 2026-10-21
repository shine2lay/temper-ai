"""Private, unsigned ROW/TARGET positions; real anchors are checked in the DB.

Tokens contain no live database identity. They prove neither issuance nor
consumption. A feed principal can construct a token for another real row.
"""

from __future__ import annotations

import base64
import binascii
import re
import struct
import uuid
from dataclasses import dataclass

MAX_EPOCH = 2**63 - 1
MAX_SEQ = 2**63 - 1
MAX_REVISION = 2**31 - 1  # #125's PostgreSQL INTEGER, not a public sequence
MAX_TOKEN_LENGTH = 256
_EVENT_ID = re.compile(r"[A-Za-z0-9._:\-]{1,128}", re.ASCII)
_WIRE = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)
_HEADER = struct.Struct("!B16sQQIB")
_VERSION = 1


class CursorError(ValueError):
    def __init__(self) -> None:
        super().__init__("usage-cursor-invalid")


def _integer(value: int, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CursorError()


def canonical_uuid(value: str) -> str:
    """Validate, never normalize a supplied source/transition identifier."""
    try:
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise CursorError()
    except (ValueError, AttributeError, TypeError):
        raise CursorError() from None
    return value


@dataclass(frozen=True)
class FinalRowAnchor:
    seq: int
    event_id: str
    revision: int

    def __post_init__(self) -> None:
        _integer(self.seq, 1, MAX_SEQ)
        _integer(self.revision, 0, MAX_REVISION)
        if type(self.event_id) is not str or not _EVENT_ID.fullmatch(self.event_id):
            raise CursorError()


@dataclass(frozen=True)
class RowCursor:
    source_instance: str
    epoch: int
    anchor: FinalRowAnchor

    def __post_init__(self) -> None:
        canonical_uuid(self.source_instance)
        _integer(self.epoch, 1, MAX_EPOCH)
        if type(self.anchor) is not FinalRowAnchor:
            raise CursorError()


@dataclass(frozen=True)
class TargetCursor:
    """Nonempty fixed target ONLY. Authorized EMPTY is separately represented."""

    source_instance: str
    epoch: int
    anchor: FinalRowAnchor

    def __post_init__(self) -> None:
        canonical_uuid(self.source_instance)
        _integer(self.epoch, 1, MAX_EPOCH)
        if type(self.anchor) is not FinalRowAnchor:
            raise CursorError()


@dataclass(frozen=True)
class InitializedNoProgress:
    """Typed start position, NOT a row/seq-zero token or permission to initialize."""

    source_instance: str
    epoch: int

    def __post_init__(self) -> None:
        canonical_uuid(self.source_instance)
        _integer(self.epoch, 1, MAX_EPOCH)


def _encode(prefix: str, value: RowCursor | TargetCursor) -> str:
    event = value.anchor.event_id.encode("ascii")
    raw = _HEADER.pack(_VERSION, uuid.UUID(value.source_instance).bytes,
                       value.epoch, value.anchor.seq, value.anchor.revision, len(event)) + event
    return prefix + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def encode_row_cursor(value: RowCursor) -> str:
    if type(value) is not RowCursor:
        raise CursorError()
    return _encode("r1.", value)


def encode_target_cursor(value: TargetCursor) -> str:
    if type(value) is not TargetCursor:
        raise CursorError()
    return _encode("t1.", value)


def _decode(token: str, prefix: str) -> tuple[str, int, FinalRowAnchor]:
    if type(token) is not str or not 1 <= len(token) <= MAX_TOKEN_LENGTH or not token.startswith(prefix):
        raise CursorError()
    wire = token[len(prefix):]
    if not _WIRE.fullmatch(wire):
        raise CursorError()
    try:
        raw = base64.b64decode(wire + "=" * (-len(wire) % 4), altchars=b"-_", validate=True)
        # Reject noncanonical unused bits as well as padding/trailing bytes.
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != wire or len(raw) < _HEADER.size:
            raise CursorError()
        version, source, epoch, seq, revision, size = _HEADER.unpack(raw[:_HEADER.size])
        if version != _VERSION or len(raw) != _HEADER.size + size:
            raise CursorError()
        anchor = FinalRowAnchor(seq, raw[_HEADER.size:].decode("ascii"), revision)
        _integer(epoch, 1, MAX_EPOCH)
        return str(uuid.UUID(bytes=source)), epoch, anchor
    except (ValueError, UnicodeError, struct.error, binascii.Error):
        raise CursorError() from None


def decode_row_cursor(token: str) -> RowCursor:
    return RowCursor(*_decode(token, "r1."))


def decode_target_cursor(token: str) -> TargetCursor:
    return TargetCursor(*_decode(token, "t1."))
