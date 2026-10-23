"""Synthetic D0 metadata candidate: declarations only, never authorization.

No CLI, I/O, environment, registry, existing T1 helper or operational dependency.
The caller supplies bytes and time; even a positive answer grants no permission.
The frozen contract and known answers are in ../stages/context_profile/t1/PREFLIGHT.md.
"""

import json
import re
from datetime import datetime
from decimal import (
    Context,
    Decimal,
    DecimalException,
    Inexact,
    Overflow,
    Rounded,
    localcontext,
)

_MAX_BYTES = 65536
_MAX_INTEGER = 1000000000
_SLOTS = ("A1", "A2", "A3", "B1", "B2", "B3")
_PLAN_FIELDS = frozenset(("schema", "scope", "experiment_id", "binding_id", "pins", "window", "evidence", "slots", "total_reservation_usd", "frontier"))
_EXPECTED_FIELDS = frozenset(("schema", "scope", "experiment_id", "binding_id", "pins", "window", "evidence", "families"))
_PIN_FIELDS = frozenset(("source_sha256", "config_sha256", "pricing_sha256", "input_sha256", "packet_sha256", "projection_sha256", "freeze_sha256", "plan_sha256"))
_WINDOW_FIELDS = frozenset(("not_before_utc", "expires_utc"))
_EVIDENCE_FIELDS = ("admission", "loaded_route", "request_shape", "projection_provenance", "pricing", "cache", "output_bound", "containment", "observer", "budget", "quota", "custody")
_EVIDENCE_RECORD_FIELDS = frozenset(("state", "sha256", "not_before_utc", "expires_utc"))
_SLOT_FIELDS = frozenset(("slot", "family", "session_id", "run_id", "settings", "root_state", "claim_state", "output_state", "reservation_usd"))
_SETTINGS_FIELDS = frozenset(("provider", "model", "route", "auth_mode", "credential_policy", "output_bound_mode", "config_sha256", "body_sha256", "body_bytes", "input_length_basis", "output_bound", "output_bound_enforced", "reasoning_included", "cache_policy", "input_category", "output_category", "currency", "input_rate_usd_per_million", "output_rate_usd_per_million"))
_ROUTE_FIELDS = ("provider", "model", "route", "auth_mode", "credential_policy", "output_bound_mode")
_ROUTES = {
    "A": ("anthropic", "claude-opus-5-5", "anthropic-oauth-named-token", "oauth", "named-token", "request_limit"),
    "B": ("openai", "gpt-6.1-sol", "openai-codex-oauth", "oauth", "Codex", "documented_max"),
}
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
_UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_RATE_PATTERN = r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,24})?"
_AMOUNT_PATTERN = r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,30})?"


class _Reject(Exception):
    """Only a finite literal code is retained; no input or exception text."""


def _require(condition, code):
    if not condition:
        raise _Reject(code)


def _fields(value, names):
    _require(type(value) is dict and set(value) == set(names), "FIELDS")


def _matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "DUPLICATE_KEY")
        result[key] = value
    return result


def _integer(token):
    _require(len(token.lstrip("-")) <= 10, "NUMBER_BOUND")
    value = int(token)
    _require(abs(value) <= _MAX_INTEGER, "NUMBER_BOUND")
    return value


def _float_number(token):
    raise _Reject("JSON_NUMBER")


def _nonfinite(token):
    raise _Reject("NONFINITE")


def _text_bound(value):
    _require(len(value) <= 512, "JSON_LIMIT")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise _Reject("UTF8") from None


def _tree_bound(value, depth=0):
    _require(depth <= 16, "JSON_LIMIT")
    count = 1
    if type(value) is str:
        _text_bound(value)
    elif type(value) is dict:
        for key, child in value.items():
            _text_bound(key)
            count += _tree_bound(child, depth + 1)
            _require(count <= 4096, "JSON_LIMIT")
    elif type(value) is list:
        for child in value:
            count += _tree_bound(child, depth + 1)
            _require(count <= 4096, "JSON_LIMIT")
    return count


def _decode(raw):
    _require(type(raw) is bytes, "INPUT_TYPE")
    _require(len(raw) <= _MAX_BYTES, "INPUT_SIZE")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise _Reject("UTF8") from None
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_int=_integer,
                           parse_float=_float_number, parse_constant=_nonfinite)
    except json.JSONDecodeError:
        raise _Reject("JSON_SYNTAX") from None
    except RecursionError:
        raise _Reject("JSON_LIMIT") from None
    _tree_bound(value)
    return value


def _utc(value):
    _require(_matches(value, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"), "UTC")
    try:
        # Literal Z has already been required. Naive arithmetic here is UTC-only;
        # no local timezone lookup, strptime import, clock or environment access.
        return datetime.fromisoformat(value[:-1])
    except ValueError:
        raise _Reject("UTC") from None


def _digest(value):
    _require(_matches(value, r"[0-9a-f]{64}"), "IDENTITY")


def _window(value, now):
    _fields(value, _WINDOW_FIELDS)
    start, end = _utc(value["not_before_utc"]), _utc(value["expires_utc"])
    _require(start < end and start <= now < end, "WINDOW")
    return start, end


def _evidence(value, window):
    _fields(value, _EVIDENCE_FIELDS)
    for name in _EVIDENCE_FIELDS:
        record = value[name]
        _fields(record, _EVIDENCE_RECORD_FIELDS)
        _require(record["state"] == "COMPLETE", "EVIDENCE")
        _digest(record["sha256"])
        start = _utc(record["not_before_utc"])
        end = _utc(record["expires_utc"])
        _require(start < end and start <= window[0] and window[1] <= end, "EVIDENCE")


def _shared(value, schema, now):
    _require(value["schema"] == schema and value["scope"] == "SYNTHETIC_ONLY", "SCHEMA")
    for name in ("experiment_id", "binding_id"):
        _require(_matches(value[name], r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"), "IDENTITY")
    _fields(value["pins"], _PIN_FIELDS)
    for pin in value["pins"].values():
        _digest(pin)
    window = _window(value["window"], now)
    _evidence(value["evidence"], window)


def _decimal(value, pattern):
    _require(_matches(value, pattern), "PRICE")
    return Decimal(value)


def _settings(value, family):
    _fields(value, _SETTINGS_FIELDS)
    for name, required in zip(_ROUTE_FIELDS, _ROUTES[family], strict=True):
        _require(value[name] == required, "ROUTE")
    _digest(value["config_sha256"])
    _digest(value["body_sha256"])
    for name in ("body_bytes", "output_bound"):
        _require(type(value[name]) is int and 1 <= value[name] <= _MAX_INTEGER, "TYPE")
    cache = "no_cache" if family == "A" else "cached_input_at_most_base"
    _require(value["input_length_basis"] == "final_serialized_input_utf8"
             and value["output_bound_enforced"] is True
             and value["reasoning_included"] is True
             and value["cache_policy"] == cache
             and value["input_category"] == "base"
             and value["output_category"] == "all_output_including_reasoning"
             and value["currency"] == "USD", "SETTINGS")
    input_rate = _decimal(value["input_rate_usd_per_million"], _RATE_PATTERN)
    output_rate = _decimal(value["output_rate_usd_per_million"], _RATE_PATTERN)
    return (Decimal(value["body_bytes"]) * input_rate
            + Decimal(value["output_bound"]) * output_rate) / Decimal(1000000)


def _check(plan, expected, now):
    _fields(expected, _EXPECTED_FIELDS)
    _shared(expected, "context-t1-preflight-expected/v1", now)
    _fields(expected["families"], ("A", "B"))
    for family in ("A", "B"):
        _settings(expected["families"][family], family)

    _fields(plan, _PLAN_FIELDS)
    _shared(plan, "context-t1-preflight-plan/v1", now)
    for name in ("experiment_id", "binding_id", "pins", "window", "evidence"):
        _require(plan[name] == expected[name], "BINDING")
    slots = plan["slots"]
    _require(type(slots) is list and len(slots) == 6, "SLOTS")
    identities = set()
    computed, claimed = {}, {}
    for slot in slots:
        _fields(slot, _SLOT_FIELDS)
        name = slot["slot"]
        _require(type(name) is str and name in _SLOTS and name not in computed, "SLOTS")
        family = name[0]
        _require(slot["family"] == family, "SLOTS")
        for field in ("session_id", "run_id"):
            identity = slot[field]
            _require(_matches(identity, _UUID_PATTERN) and identity != _ZERO_UUID, "UUID")
            _require(identity not in identities, "UUID_REUSE")
            identities.add(identity)
        reservation = _settings(slot["settings"], family)
        _require(slot["root_state"] == "IDLE" and slot["claim_state"] == "ABSENT"
                 and slot["output_state"] == "ABSENT", "USED_SLOT")
        _require(slot["settings"] == expected["families"][family], "DRIFT")
        computed[name] = reservation
        claimed[name] = _decimal(slot["reservation_usd"], _AMOUNT_PATTERN)
    _require(set(computed) == set(_SLOTS), "SLOTS")

    total_claim = _decimal(plan["total_reservation_usd"], _AMOUNT_PATTERN)
    frontier = plan["frontier"]
    _fields(frontier, ("active_slots", "reservation_usd"))
    active_claim = _decimal(frontier["reservation_usd"], _AMOUNT_PATTERN)
    active = frontier["active_slots"]
    _require(type(active) is list and len(active) <= 2, "FRONTIER")
    _require(all(type(name) is str and name in computed for name in active), "FRONTIER")
    _require(len(set(active)) == len(active) and len({name[0] for name in active}) == len(active), "FRONTIER")

    total = sum(computed.values(), Decimal(0))
    active_total = sum((computed[name] for name in active), Decimal(0))
    # Check computed AND claimed aggregates; do not clamp or repair any claim.
    _require(total <= 30 and total_claim <= 30, "TOTAL_CAP")
    _require(all(computed[name] <= 5 and claimed[name] <= 5 for name in _SLOTS), "SLOT_CAP")
    _require(active_total <= 10 and active_claim <= 10, "ACTIVE_CAP")
    _require(all(claimed[name] == computed[name] for name in _SLOTS)
             and total_claim == total and active_claim == active_total, "RESERVATION")


def _result(code=None):
    return {
        "schema": "context-t1-preflight/v1",
        "status": "METADATA_PASS" if code is None else "REJECT",
        "error_codes": [] if code is None else [code],
        "metadata_only": True,
        "authorizes_dispatch": False,
        "authorizes_later_stage": False,
    }


def check_plan(plan_json: bytes, expected_json: bytes, now_utc: str) -> dict:
    """Check closed synthetic declarations only; return no input content/authority."""
    try:
        plan = _decode(plan_json)
        expected = _decode(expected_json)
        now = _utc(now_utc)
        with localcontext(Context(prec=96)) as context:
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            context.traps[Overflow] = True
            _check(plan, expected, now)
    except _Reject as refusal:
        return _result(refusal.args[0])
    except DecimalException:
        # Defensive fail-closed arithmetic guard; never expose exception text.
        return _result("PRICE")
    return _result()
