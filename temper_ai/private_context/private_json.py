"""Volatile JSON ownership and strict decoding, not a Python memory sandbox.

Only explicitly named private accessors expose content. Generic repr, JSON,
copy/deepcopy and pickle paths cannot serialize it. close() drops our reference;
this does not claim secure erasure or revoke copies a private consumer obtained.
"""
from __future__ import annotations

import json
import math
from typing import Any, NoReturn, SupportsIndex

from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    raise ValueError("nonfinite")


def _json_scalars(value: Any) -> None:
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite")
    elif isinstance(value, dict):
        for key, item in value.items():
            _json_scalars(key)
            _json_scalars(item)
    elif isinstance(value, list):
        for item in value:
            _json_scalars(item)


def decode_object(raw: bytes, code: Code = Code.CONTEXT_INVALID) -> dict[str, Any]:
    """JSON UTF-8 object, no duplicate keys, nonfinite numbers, BOM or surrogates.

    Fixed failure raised *after* leaving the handler: no JSON exception chain.
    No discretionary byte/depth caps; transport limits belong to the capability.
    """
    try:
        if type(raw) is not bytes:
            raise ValueError("type")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        if type(value) is not dict:
            raise ValueError("object")
        _json_scalars(value)
        return value
    except (ValueError, TypeError, RecursionError, OverflowError):
        pass
    raise PrivateDraftFailure(code)


def encode_private(value: Any) -> bytes:
    """Explicit content-bearing encoding; use only inside the private boundary."""
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError):
        pass
    raise PrivateDraftFailure(Code.CONTEXT_INVALID)


class PrivateJSON:
    """Owned immutable snapshot. No dict/dataclass/Pydantic serialization surface."""

    __slots__ = ("__raw",)

    def __init__(self, raw: bytes) -> None:
        decode_object(raw)
        self.__raw: bytes | None = raw

    def __repr__(self) -> str:
        return "<PrivateJSON>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("private serialization forbidden")

    def open_private(self) -> dict[str, Any]:
        """Independent decoded copy, solely for the authorized private consumer."""
        return decode_object(self.to_private_json())

    def to_private_json(self) -> bytes:
        """Content-bearing bytes, never for logs, events, checkpoints or public routes."""
        if self.__raw is None:
            raise PrivateDraftFailure(Code.CONTEXT_LOST)
        return self.__raw

    def close(self) -> None:
        self.__raw = None
