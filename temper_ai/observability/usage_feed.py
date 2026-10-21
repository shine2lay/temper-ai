"""Pure, closed usage-feed items from already materialized numeric observations.

No database, event payload, runtime lookup, pricing or I/O. The caller must load
all named row columns first; an expired ORM object is not a materialized row.
See docs/usage-feed.md for the source evidence and intentionally unproven claims.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

MAX_SAFE_INTEGER = 2**53 - 1
MAX_ITEM_BYTES = 2048
_LABEL = re.compile(r"[A-Za-z0-9._:/@+\-]{1,128}", re.ASCII)
# Retain the producer's native-label policy, not merely its character allowlist.
_UNSAFE_LABEL = re.compile(r"^(?:/|\.{1,2}/|[A-Za-z]:/)|[A-Za-z][A-Za-z0-9+.-]*:/|[^/]+:[^/]*@", re.ASCII)
_EVENTS = {"llm.call.started": "call_started", "llm.call.completed": "call_completed",
           "llm.call.failed": "call_failed"}
_FIELDS = {"prompt": "prompt_tokens", "completion": "completion_tokens", "total": "total_tokens",
           "cache_read": "cache_read_tokens", "cache_write": "cache_write_tokens"}
_TOKEN_FAULTS = {"prompt": "prompt-invalid", "completion": "completion-invalid", "total": "total-invalid",
                 "cache_read": "cache-read-invalid", "cache_write": "cache-write-invalid"}
_COMPONENTS = ("prompt", "completion", "cache_read", "cache_write")
# Deliberately independent of usage_rows: importing the serializer imports no DB.
ROW_FAULT_CODES = frozenset({
    *_TOKEN_FAULTS.values(), "provider-invalid", "provider-unproven", "model-invalid",
    "model-unproven", "kind-invalid", "id-invalid", "cost-invalid", "lost-invalid",
    "link-unproven", "usage-missing", "ordering-deferred", "call-unended",
})
FAULT_CODES = frozenset({
    *(ROW_FAULT_CODES - {"ordering-deferred"}), "faults-invalid", "call-unlinked",
    "token-overlap", "exclusive-unavailable", "pi-convention-unverified",
    "pi-zero-or-absent", "pi-count-unreported", "pi-total-unverified",
    "usage-absent", "legacy-cost-invalid",
})


def _get(row: Any, key: str) -> Any:
    return row.get(key) if isinstance(row, Mapping) else getattr(row, key, None)


def _count(value: Any, fault: str, faults: set[str]) -> int | None:
    if value is None:
        return None
    if type(value) is int and 0 <= value <= MAX_SAFE_INTEGER:
        return value
    faults.add(fault)
    return None


def _label(value: Any, fault: str, faults: set[str], *, native_label: bool = False) -> str | None:
    if value is None:
        if native_label:
            faults.add(fault.replace("invalid", "unproven"))
        return None
    if (isinstance(value, str) and _LABEL.fullmatch(value)
            and (not native_label or not _UNSAFE_LABEL.search(value))):
        return value
    faults.add(fault)
    return None


def _row_faults(value: Any) -> set[str]:
    if not isinstance(value, str) or len(value) > 256:
        return {"faults-invalid"}
    faults = set(filter(None, value.split(",")))
    invalid = bool(faults - ROW_FAULT_CODES)
    faults.intersection_update(ROW_FAULT_CODES)
    faults.discard("ordering-deferred")
    if invalid:
        faults.add("faults-invalid")
    return faults


def _closed(value: Any, allowed: tuple[str, ...], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"usage item {field} invalid")
    return value


def _occurred_at(value: Any) -> str:
    if not isinstance(value, datetime):
        raise ValueError("usage item occurred-at invalid")
    # SQLite/old TIMESTAMP columns yield naive UTC (shared.clock's convention).
    utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _legacy_cost(row: Any, faults: set[str]) -> dict[str, Any]:
    value = _get(row, "legacy_cost_usd")
    valid = type(value) is float and math.isfinite(value) and value >= 0
    if not valid:
        faults.add("legacy-cost-invalid")
    source = _get(row, "legacy_cost_source")
    if source is not None and (not isinstance(source, str) or source not in ("pi_estimate", "service")):
        source = None
        faults.add("legacy-cost-invalid")
    return {"text": repr(value) if valid else None, "source": source, "basis": "unproven"}


def _tokens(row: Any, pi: bool, faults: set[str]) -> dict[str, int | None]:
    raw = {key: _get(row, field) for key, field in _FIELDS.items()}
    tokens = {key: _count(value, _TOKEN_FAULTS[key], faults) for key, value in raw.items()}
    if pi:
        if all(type(raw[key]) is int and raw[key] == 0 for key in _COMPONENTS):
            tokens = dict.fromkeys(_FIELDS)
            faults.add("usage-absent")
        else:
            for key in _COMPONENTS:
                if tokens[key] == 0:
                    tokens[key] = None
                    faults.add("pi-zero-or-absent")
                elif raw[key] is None:
                    faults.add("pi-count-unreported")
            components = [tokens[key] for key in _COMPONENTS]
            if (any(count is None for count in components)
                    or tokens["total"] != sum(count for count in components if count is not None)):
                tokens["total"] = None
                faults.add("pi-total-unverified")
    if all(value is None for value in tokens.values()):
        faults.add("usage-absent")
    return tokens


def to_item(row: Any) -> dict[str, Any]:
    """Serialize one materialized UsageObservation or mapping; never mutate it.

    Optional invalid values become null with closed faults. Invalid required
    enums/revision/time, or an oversized item, fail closed with a fixed error.
    Pi convention remains unverified: token_source alone proves no API contract.
    """
    faults = _row_faults(_get(row, "fault_codes"))
    ids = {key: _label(_get(row, key), "id-invalid", faults) for key in
           ("event_id", "execution_id", "parent_id", "llm_call_id", "started_event_id")}
    revision = _get(row, "revision")
    if type(revision) is not int or not 0 <= revision <= MAX_SAFE_INTEGER:
        raise ValueError("usage item revision invalid")
    event_type = _closed(_get(row, "event_type"), tuple(_EVENTS), "event")
    origin = _closed(_get(row, "origin"), ("live", "reconciled"), "origin")
    token_source = _closed(_get(row, "token_source"), ("pi", "service"), "token-source")
    basis = _closed(_get(row, "occurrence_basis"), ("call_start", "call_end"), "occurrence-basis")
    # #126 stores the marker as a fault: the SQL basis stays call_start (no DDL).
    if event_type == "llm.call.started" and "call-unended" in faults:
        basis = "call_start_unended"
    kind = _get(row, "call_kind")
    if kind is not None and (not isinstance(kind, str) or kind not in ("model", "compaction")):
        kind = None
        faults.add("kind-invalid")
    provider = _label(_get(row, "provider"), "provider-invalid", faults, native_label=True)
    model = _label(_get(row, "model"), "model-invalid", faults, native_label=True)
    pi = token_source == "pi"
    if pi:
        call_key = f"pi:{ids['llm_call_id']}" if ids["llm_call_id"] is not None else None
    else:
        start = ids["event_id"] if event_type == "llm.call.started" else ids["started_event_id"]
        call_key = f"svc:{start}" if start is not None else None
    if call_key is None:
        faults.add("call-unlinked")
    tokens = _tokens(row, pi, faults)
    exclusive = None
    convention = "pi-unverified" if pi else "service-unverified"
    if pi:
        faults.add("pi-convention-unverified")
    elif provider == "anthropic":
        convention = "service-inclusive-prompt"
        prompt, completion, read, write = (tokens[key] for key in _COMPONENTS)
        if prompt is not None and completion is not None and read is not None and write is not None:
            fresh = prompt - read - write
            if fresh < 0:
                faults.add("token-overlap")
            else:
                exclusive = {"input": fresh, "output": completion, "cache_read": read, "cache_write": write}
    if not pi and exclusive is None:
        faults.add("exclusive-unavailable")
    cost = _legacy_cost(row, faults)
    lost = _count(_get(row, "lost_attempts"), "lost-invalid", faults)
    item = {
        "event_id": ids["event_id"], "revision": revision, "call_key": call_key,
        "origin": origin, "execution_id": ids["execution_id"], "agent_event_id": ids["parent_id"],
        "event": _EVENTS[event_type], "call_kind": kind, "llm_call_id": ids["llm_call_id"],
        "started_event_id": ids["started_event_id"], "provider": provider, "model": model,
        "occurred_at": _occurred_at(_get(row, "occurred_at")), "occurrence_basis": basis,
        "observed_tokens": tokens, "token_convention": convention, "exclusive_tokens": exclusive,
        "legacy_cost": cost, "lost_attempts": lost, "faults": sorted(faults),
    }
    encoded = json.dumps(item, allow_nan=False, ensure_ascii=True)
    if len(encoded.encode("ascii")) > MAX_ITEM_BYTES:
        raise ValueError("usage item exceeds byte bound")
    return item
