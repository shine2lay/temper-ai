"""Fixed ops-host-inspect/2 decoder for future-contract data; Python stdlib only.

H-P3-INSPECT2-1 (Architecture #218, project three-passing-projects)
- Wrong (evidence): nothing decodes ops-host-inspect/2 at a pure boundary. Ops
  #429 found no standalone target/window/container/structural-time guard
  (M1) and no local TARGET_* mapping (M2); the actual producer still emits
  /1 with the 23 runtime members (C1), so clean /2 data is future-contract only.
- Change: one fixed bounded decoder, parse_inspect2, written from the received
  contract, with its own closed eleven-code TargetRefused.
- Expected: every F3 negative refuses with its fixed code, every clean twin is
  accepted, and each guard's bite shows its own negative depends on it.
- Disproved if: any clean twin refuses, any negative is accepted or gets the
  wrong code, or a refusal carries anything except the code.

Contract (HOME-adopted r3 packet, SHA256SUMS caa690894dbb0802c728b11ba2c65587464f1503fca7ccfe0d51d552f6afdc20):
- ABI.md A1 (strict grammar and limits), A4 (A4.1-A4.4) and A7;
- CASE-REQUIREMENTS.md F3; SOURCE-PLANS.md and source-plans.json plans.P3;
- Ops #429 REVIEW (R3 field audit) 2bef4a0d0c1be049a8b911db5750583d1cc4008980dc2a388255d8ee1ee4ceb0;
- Ops #440 REVIEW (P3-C1/M1/M2) 886dd07386bda01a6507fd784e6a74caaf103b2e67d60f16a0a0b8c075572718.

What this is not: not compatibility with any actual producer, validator or
corpus (they emit /1), not image/argv/mount/network equality, not operation
chronology, TTL or health, and not native authenticity. All of those stay with
P5 or native checks. No I/O, clock, field-count dispatch or retagging.
docs/architecture/ops-host-inspect.md has the API, error mapping and limits.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

# ─── Fixed local errors (ABI A7) ────────────────────────────────────────────

TARGET_CONTEXT_MISSING = "TARGET_CONTEXT_MISSING"
TARGET_ISSUER_UNTRUSTED = "TARGET_ISSUER_UNTRUSTED"
TARGET_PUBLICATION_INVALID = "TARGET_PUBLICATION_INVALID"
TARGET_SELECTOR_MISSING = "TARGET_SELECTOR_MISSING"
TARGET_SELECTOR_AMBIGUOUS = "TARGET_SELECTOR_AMBIGUOUS"
TARGET_BINDING_INVALID = "TARGET_BINDING_INVALID"
TARGET_SCHEMA_MISMATCH = "TARGET_SCHEMA_MISMATCH"
TARGET_SOURCE_MISSING = "TARGET_SOURCE_MISSING"
TARGET_SOURCE_DRIFT = "TARGET_SOURCE_DRIFT"
TARGET_REVIEW_MISSING = "TARGET_REVIEW_MISSING"
TARGET_EVIDENCE_INVALID = "TARGET_EVIDENCE_INVALID"

TARGET_CODES = (
    TARGET_CONTEXT_MISSING,
    TARGET_ISSUER_UNTRUSTED,
    TARGET_PUBLICATION_INVALID,
    TARGET_SELECTOR_MISSING,
    TARGET_SELECTOR_AMBIGUOUS,
    TARGET_BINDING_INVALID,
    TARGET_SCHEMA_MISMATCH,
    TARGET_SOURCE_MISSING,
    TARGET_SOURCE_DRIFT,
    TARGET_REVIEW_MISSING,
    TARGET_EVIDENCE_INVALID,
)

# The only two codes this decoder ever raises (ABI A4.3).
_SI = TARGET_SCHEMA_MISMATCH
_EI = TARGET_EVIDENCE_INVALID


class TargetRefused(ValueError):
    """A fixed local refusal: args, str and repr hold the code and nothing else."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in TARGET_CODES:
            raise ValueError("TargetRefused needs one of the eleven TARGET_* codes")
        super().__init__(code)
        self.__code = code

    @property
    def code(self) -> str:
        return self.__code


# ─── Result ─────────────────────────────────────────────────────────────────

UNTRUSTED = "UNTRUSTED"


@dataclass(frozen=True, eq=False)
class Inspect2Data:
    """Decoded /2 data: always UNTRUSTED; snapshot is a fresh read-only copy.

    Only parse_inspect2 makes a meaningful one. The repr never shows the
    snapshot, so raw Env never reaches a log through it.
    """

    snapshot: MappingProxyType[str, Any]
    trust: str = field(default=UNTRUSTED, init=False)

    def __repr__(self) -> str:
        return "Inspect2Data(trust='UNTRUSTED')"


# ─── Fixed contract constants ───────────────────────────────────────────────

SCHEMA = "ops-host-inspect/2"
MAX_INSPECT_BYTES = 16384
MAX_DEPTH = 32
TARGETS = ("app", "forwarder")

OUTER_KEYS = frozenset(
    ("schema", "window_id", "container_id", "runtime", "state", "observed_at")
)
# The exact runtime 23 and state 7 member names are the keys of RUNTIME_RULES
# and STATE_RULES below, in contract order.

# ─── Parse ──────────────────────────────────────────────────────────────────


def parse_inspect2(
    raw: bytes, *, window_id: str, container_id: str, target: str
) -> Inspect2Data:
    """Decode fixed ops-host-inspect/2 bytes for one expected window, container and target.

    Raises TargetRefused(TARGET_SCHEMA_MISMATCH) when a closed, typed outer
    object carries another schema string, and TargetRefused(TARGET_EVIDENCE_INVALID)
    for everything else that is invalid. Nothing else escapes: any other error
    while decoding is mapped to TARGET_EVIDENCE_INVALID, and the refusal is
    raised fresh, with no message, cause or context.
    """
    code = _EI
    try:
        return _decode(raw, window_id, container_id, target)
    except TargetRefused as exc:
        if type(exc) is TargetRefused and exc.code == _SI:
            code = _SI
    except Exception:  # every unexpected error is invalid evidence, never passed through
        pass
    raise TargetRefused(code)  # outside the except blocks: no cause, no context


def _decode(raw: Any, window_id: Any, container_id: Any, target: Any) -> Inspect2Data:
    _check_arguments(raw, window_id, container_id, target)  # all four exact types, first
    doc = _load(raw)
    _check_outer_shape(doc)
    _guard_schema(doc["schema"])
    _check_outer_members(doc)
    _guard_window(doc["window_id"], window_id)
    _guard_container(doc["container_id"], container_id)
    _check_runtime(doc["runtime"])
    _check_state(doc["state"])
    _guard_time_order(doc["state"], doc["observed_at"])
    _guard_target_bind(target, doc["runtime"]["data_bind"])
    return Inspect2Data(snapshot=_freeze(doc))


def _invalid() -> TargetRefused:
    return TargetRefused(_EI)


# ─── Arguments ──────────────────────────────────────────────────────────────


def _check_arguments(raw: object, window_id: object, container_id: object, target: object) -> None:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_INSPECT_BYTES:
        raise _invalid()
    if not _is_text(window_id):
        raise _invalid()
    if not _is_hex64(container_id):
        raise _invalid()
    if type(target) is not str or target not in TARGETS:
        raise _invalid()


# ─── Strict JSON ────────────────────────────────────────────────────────────


class _Float:
    """Stands in for a JSON number with a fraction or exponent: no member is one."""

    __slots__ = ()


_FLOAT = _Float()


def _load(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise _invalid() from None
    _check_depth(text)
    return json.loads(
        text,
        object_pairs_hook=_closed_pairs,
        parse_float=_parse_float,
        parse_constant=_refuse_constant,
    )


def _closed_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out = dict(pairs)
    if len(out) != len(pairs):
        raise _invalid()  # duplicate JSON name at any depth
    return out


def _parse_float(_text: str) -> _Float:
    return _FLOAT


def _refuse_constant(_text: str) -> Any:
    raise _invalid()  # NaN, Infinity, -Infinity


def _check_depth(text: str) -> None:
    """Refuse nesting deeper than MAX_DEPTH before json recurses into it."""
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise _invalid()
        elif char in "]}":
            depth -= 1


# ─── Outer object and guards ────────────────────────────────────────────────


def _check_outer_shape(doc: Any) -> None:
    if type(doc) is not dict or doc.keys() != OUTER_KEYS:
        raise _invalid()
    if type(doc["schema"]) is not str:
        raise _invalid()


def _guard_schema(schema: str) -> None:
    """The fixed version guard: only the /2 literal; never retag or dispatch."""
    if schema != SCHEMA:
        raise TargetRefused(_SI)


def _check_outer_members(doc: dict[str, Any]) -> None:
    if not _is_text(doc["window_id"]) or not _is_hex64(doc["container_id"]):
        raise _invalid()
    if not _observed_at(doc["observed_at"]):
        raise _invalid()


def _guard_window(observed: str, expected: str) -> None:
    if observed != expected:
        raise _invalid()


def _guard_container(observed: str, expected: str) -> None:
    if observed != expected:
        raise _invalid()


def _guard_target_bind(target: str, data_bind: Any) -> None:
    """app needs its data bind; only forwarder may have none (shape checked already)."""
    if target == "app" and data_bind is None:
        raise _invalid()


# ─── Text and small types ───────────────────────────────────────────────────

_FORBIDDEN_CHAR = re.compile(r"[\x00\ud800-\udfff]")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _is_text_or_empty(value: Any) -> bool:
    return type(value) is str and _FORBIDDEN_CHAR.search(value) is None


def _is_text(value: Any) -> bool:
    return _is_text_or_empty(value) and value != ""


def _is_hex64(value: Any) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _is_bool(value: Any) -> bool:
    return type(value) is bool


def _is_int(value: Any, low: int, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def _closed(value: Any, rules: dict[str, Callable[[Any], bool]]) -> bool:
    return (
        type(value) is dict
        and value.keys() == rules.keys()
        and all(rules[key](value[key]) for key in rules)
    )


def _strictly_increasing(keys: list[Any]) -> bool:
    return all(keys[i] < keys[i + 1] for i in range(len(keys) - 1))


def _sorted_unique_text(value: Any) -> bool:
    return (
        type(value) is list
        and all(_is_text(item) for item in value)
        and _strictly_increasing(value)
    )


def _canonical(member: Any) -> bytes:
    return json.dumps(
        member, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sorted_unique_members(value: Any, member: Callable[[Any], bool]) -> bool:
    if type(value) is not list or not all(member(item) for item in value):
        return False
    return _strictly_increasing([_canonical(item) for item in value])


# ─── Runtime (23 members, ABI A4.1 and the Ops #429 R3 field audit) ─────────

_DIGEST = r"sha256:[0-9a-f]{64}"
_REPOSITORY = r"[a-z0-9]+(?:[._/:-]+[a-z0-9]+)*"
_IMAGE_ID = re.compile(rf"(?:{_REPOSITORY}@)?{_DIGEST}")
_MAX_IMAGE_ID = 255


def _image_id(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) <= _MAX_IMAGE_ID
        and _IMAGE_ID.fullmatch(value) is not None
    )


def _command(value: Any) -> bool:
    return type(value) is list and len(value) > 0 and all(_is_text(item) for item in value)


def _env_key(token: Any) -> str | None:
    """KEY=VALUE split at the first '='; key nonempty; value may be empty."""
    if not _is_text(token) or "=" not in token:
        return None
    key = token.split("=", 1)[0]
    return key if key else None


def _env(value: Any) -> bool:
    """Observed container env: ordered; well-formed duplicates are kept."""
    return type(value) is list and all(_env_key(item) is not None for item in value)


def _image_env(value: Any) -> bool:
    """Pinned-image env baseline: ordered, keys unique."""
    if type(value) is not list:
        return False
    keys = [_env_key(item) for item in value]
    return None not in keys and len(set(keys)) == len(keys)


_MOUNT = {
    "type": _is_text_or_empty,
    "source": _is_text_or_empty,
    "destination": _is_text_or_empty,
    "rw": _is_bool,
    "propagation": _is_text_or_empty,
}
_DEVICE = {
    "path_on_host": _is_text,
    "path_in_container": _is_text,
    "cgroup_permissions": _is_text,
}
_LIMITS = {
    "pids": lambda v: _is_int(v, 0),
    "memory_bytes": lambda v: _is_int(v, 0),
    "nano_cpus": lambda v: _is_int(v, 0),
}
_RESTART_POLICY = {
    "name": _is_text,
    "maximum_retry_count": lambda v: _is_int(v, 0),
}
_PORT = {
    "host_ip": _is_text,
    "host_port": lambda v: _is_int(v, 1, 65535),
    "container_port": lambda v: _is_int(v, 1, 65535),
    "protocol": lambda v: type(v) is str and v in ("tcp", "udp"),
}
_NETWORK = {
    "network_id": _is_hex64,
    "network_name": _is_text,
    "aliases": _sorted_unique_text,
}


def _absolute_canonical(value: Any) -> bool:
    if not _is_text(value) or not value.startswith("/"):
        return False
    if value == "/":
        return True
    return all(part not in ("", ".", "..") for part in value[1:].split("/"))


_DATA_BIND = {
    "source": _absolute_canonical,
    "destination": _absolute_canonical,
    "rw": _is_bool,
}


def _tmpfs(value: Any) -> bool:
    return type(value) is dict and all(
        _is_text(key) and _is_text_or_empty(item) for key, item in value.items()
    )


RUNTIME_RULES: dict[str, Callable[[Any], bool]] = {
    "image_id": _image_id,
    "command": _command,
    "workdir": _is_text_or_empty,
    "env": _env,
    "user": _is_text_or_empty,
    "mounts": lambda v: _sorted_unique_members(v, lambda m: _closed(m, _MOUNT)),
    "tmpfs": _tmpfs,
    "read_only_root": _is_bool,
    "cap_drop": _sorted_unique_text,
    "cap_add": _sorted_unique_text,
    "security_options": _sorted_unique_text,
    "privileged": _is_bool,
    "devices": lambda v: _sorted_unique_members(v, lambda m: _closed(m, _DEVICE)),
    "pid_mode": _is_text_or_empty,
    "ipc_mode": _is_text_or_empty,
    "uts_mode": _is_text_or_empty,
    "init": _is_bool,
    "limits": lambda v: _closed(v, _LIMITS),
    "restart_policy": lambda v: _closed(v, _RESTART_POLICY),
    "ports": lambda v: _sorted_unique_members(v, lambda m: _closed(m, _PORT)),
    "networks": lambda v: _sorted_unique_members(v, lambda m: _closed(m, _NETWORK)),
    "data_bind": lambda v: v is None or _closed(v, _DATA_BIND),
    "image_env": _image_env,
}


def _check_runtime(runtime: Any) -> None:
    if type(runtime) is not dict or runtime.keys() != RUNTIME_RULES.keys():
        raise _invalid()
    for key, rule in RUNTIME_RULES.items():
        if not rule(runtime[key]):
            raise _invalid()


# ─── State (7 members) ──────────────────────────────────────────────────────

STATE_RULES: dict[str, Callable[[Any], bool]] = {
    "running": _is_bool,
    "status": _is_text,
    "started_at": lambda v: _instant(v) is not None,  # an event or the zero sentinel
    "finished_at": lambda v: _instant(v) is not None,  # an event or the zero sentinel
    "exit_code": lambda v: _is_int(v, 0),
    "oom_killed": _is_bool,
    "restart_count": lambda v: _is_int(v, 0),
}


def _check_state(state: Any) -> None:
    if type(state) is not dict or state.keys() != STATE_RULES.keys():
        raise _invalid()
    for key, rule in STATE_RULES.items():
        if not rule(state[key]):
            raise _invalid()


# ─── Structural time (ABI A4.2 subset only) ─────────────────────────────────

_TIMESTAMP = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(?:(Z)|([+-])(\d{2}):(\d{2}))",
    re.ASCII,  # \d is 0-9 only, never another script's digits
)
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_NANOS_PER_SECOND = 1_000_000_000


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_from_civil(year: int, month: int, day: int) -> int:
    """Days since 1970-01-01 in the proleptic Gregorian calendar (integer only)."""
    if month <= 2:
        year -= 1
    era = year // 400
    year_of_era = year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def _instant(value: Any, min_fraction: int = 0) -> int | None:
    """Offset-aware RFC 3339 timestamp -> integer nanoseconds since 1970 UTC, or None."""
    if type(value) is not str:
        return None
    match = _TIMESTAMP.fullmatch(value)
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    fraction = match.group(7) or ""
    if len(fraction) < min_fraction:
        return None
    if year < 1 or not 1 <= month <= 12:
        return None
    month_days = 29 if month == 2 and _is_leap(year) else _MONTH_DAYS[month - 1]
    if not 1 <= day <= month_days or hour > 23 or minute > 59 or second > 59:
        return None
    offset = 0
    if match.group(8) is None:
        sign, off_hour, off_minute = match.group(9), int(match.group(10)), int(match.group(11))
        if off_hour > 23 or off_minute > 59:
            return None
        if sign == "-" and off_hour == 0 and off_minute == 0:
            return None  # -00:00 means an unknown offset (RFC 3339 4.3)
        offset = (off_hour * 60 + off_minute) * 60 * (1 if sign == "+" else -1)
    seconds = _days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second
    nanos = int(fraction.ljust(9, "0")) if fraction else 0
    return (seconds - offset) * _NANOS_PER_SECOND + nanos


_ZERO_INSTANT = _instant("0001-01-01T00:00:00Z")


def _is_zero_sentinel(value: Any) -> bool:
    """Docker's zero time: the disclosed 'no event' value for started_at/finished_at."""
    instant = _instant(value)
    return instant is not None and instant == _ZERO_INSTANT


def _observed_at(value: Any) -> bool:
    """observed_at: offset, at least milliseconds, and an ordinary instant (never the sentinel)."""
    return _instant(value, min_fraction=3) is not None and not _is_zero_sentinel(value)


def _event(value: Any) -> int | None:
    """An actual event's instant; None for the zero sentinel (no event)."""
    return None if _is_zero_sentinel(value) else _instant(value)


def _guard_time_order(state: dict[str, Any], observed_at: str) -> None:
    """Compare only actual events, and only against observed: started/finished <= observed.

    No start/finish order judgment (r5): Docker keeps the previous exit's
    finished_at when a container starts again, so either order is normal data.
    P5 judges start/finish order per leg, with the operation context.
    No clock, TTL, deadline, operation or health judgment: those stay with P5.
    """
    observed = _instant(observed_at, min_fraction=3)
    started = _event(state["started_at"])
    finished = _event(state["finished_at"])
    if observed is None:
        raise _invalid()
    if started is not None and started > observed:
        raise _invalid()
    if finished is not None and finished > observed:
        raise _invalid()


# ─── Fresh read-only copy ───────────────────────────────────────────────────


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value
