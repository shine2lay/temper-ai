"""Closed N3 record decoding and deterministic content identities (no I/O)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields
from types import UnionType
from typing import Literal, get_args, get_origin, get_type_hints

from . import records as t
from .validation import _refuse

# Existing R2 receiving limits, not a new native/runtime quota.
MAX_DOCUMENT = 16777216
MAX_DEPTH = 32
MAX_GRAPH = 65536


def wire_name(cls: type, name: str) -> str:
    if cls is t.SourceEdge:
        return {"source": "from", "target": "to"}.get(name, name)
    return name


def to_wire(value: object) -> object:
    """Canonical data encoding, including the wire's from/to edge names."""
    if isinstance(value, t.Record):
        return {wire_name(type(value), f.name): to_wire(getattr(value, f.name)) for f in fields(value)}
    if type(value) is tuple:
        return [to_wire(item) for item in value]
    return value


def canonical_bytes(value: object) -> bytes:
    result = None
    try:
        result = json.dumps(to_wire(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (ValueError, TypeError, RecursionError):
        pass
    if result is None:
        _refuse("TARGET_BINDING_INVALID")
    return result


def byte_identity(raw: bytes) -> t.ContentIdentity:
    return t.ContentIdentity(hashlib.sha256(raw).hexdigest(), len(raw))


def claim_identity(value: object) -> t.ContentIdentity:
    """Identity of a purpose-specific claim; not evidence of its origin."""
    return byte_identity(canonical_bytes(value))


def _decode(value: object, annotation: object, depth: int = 0) -> object:
    if depth > MAX_DEPTH:
        _refuse("TARGET_BINDING_INVALID")
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is UnionType:
        for item in args:
            if item in (str, int, bool, type(None)) and t._typed(value, item):
                return value
        records = [a for a in args if isinstance(a, type) and issubclass(a, t.Record)]
        for cls in records:
            hints = get_type_hints(cls)
            if "tag" not in hints or (type(value) is dict and type(value.get("tag")) is str and value["tag"] in get_args(hints["tag"])):
                return _decode(value, cls, depth + 1)
        _refuse("TARGET_BINDING_INVALID")
    if origin is tuple:
        if type(value) is not list or len(value) > MAX_GRAPH:
            _refuse("TARGET_BINDING_INVALID")
        return tuple(_decode(item, args[0], depth + 1) for item in value)
    if isinstance(annotation, type) and issubclass(annotation, t.Record):
        hints = get_type_hints(annotation)
        expected_fields = {wire_name(annotation, f.name) for f in fields(annotation)}
        if (type(value) is not dict or any(type(key) is not str for key in value)
                or value.keys() != expected_fields):
            _refuse("TARGET_BINDING_INVALID")
        if "schema" in hints and get_origin(hints["schema"]) is Literal:
            if type(value["schema"]) is not str:
                _refuse("TARGET_BINDING_INVALID")
            if value["schema"] not in get_args(hints["schema"]):
                _refuse("TARGET_SCHEMA_MISMATCH")
        result = annotation(**{f.name: _decode(value[wire_name(annotation, f.name)], hints[f.name], depth + 1) for f in fields(annotation)})
        if type(result) is t.ContentIdentity and re.fullmatch(r"[0-9a-f]{64}", result.sha256) is None:
            _refuse("TARGET_BINDING_INVALID")
        return result
    if not t._typed(value, annotation):
        _refuse("TARGET_BINDING_INVALID")
    return value


def decode_record(value: object, cls: type[t.Record]) -> t.Record:
    """Used for wire parsing and revalidation of public Python records."""
    result = _decode(value, cls)
    refs = {}
    pending = [result]
    while pending:
        item = pending.pop()
        if type(item) is t.EvidenceRef:
            key = (item.schema, item.supplier, item.record_id)
            if key in refs and refs[key] != item:
                _refuse("TARGET_BINDING_INVALID")
            refs[key] = item
        if isinstance(item, t.Record):
            pending.extend(getattr(item, f.name) for f in fields(item))
        elif type(item) is tuple:
            pending.extend(item)
    return result


def _object_fields(pairs: list) -> dict:
    """Closed N3 JSON cannot hide an earlier value behind a duplicate field."""
    values = dict(pairs)
    if len(values) != len(pairs):
        _refuse("TARGET_BINDING_INVALID")
    return values


def document(value: object, cls: type[t.Record]) -> tuple[t.Record, t.ContentIdentity]:
    raw = value if type(value) is bytes else None
    valid = True
    if raw is not None:
        if not 0 < len(raw) <= MAX_DOCUMENT:
            _refuse("TARGET_BINDING_INVALID")
        try:
            # Every N3 number is an exact int; the decoder rejects float/NaN/Infinity.
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_fields)
        except (ValueError, RecursionError):
            valid = False
        # Raise outside the exception handler: never retain secret input in cause/context.
        if not valid:
            _refuse("TARGET_BINDING_INVALID")
    result = decode_record(value, cls)
    if raw is None:
        raw = canonical_bytes(result)
        if len(raw) > MAX_DOCUMENT:
            _refuse("TARGET_BINDING_INVALID")
    return result, byte_identity(raw)


def unique(values: tuple) -> None:
    if len(set(values)) != len(values):
        _refuse("TARGET_BINDING_INVALID")


def named(values: tuple) -> dict:
    unique(tuple(value.id for value in values))
    return {value.id: value for value in values}


def references(values: tuple[str, ...], targets: dict) -> None:
    unique(values)
    if not set(values) <= targets.keys():
        _refuse("TARGET_BINDING_INVALID")


def object_id(value: str, format: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{40}" if format == "sha1" else r"[0-9a-f]{64}", value) is not None


def repository_path(value: str) -> bool:
    return not any(part in ("", ".", "..") for part in value.split("/")) and "\\" not in value and all(ord(c) >= 32 and ord(c) != 127 for c in value)
