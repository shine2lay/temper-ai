"""ONE isolated stdlib suite; newly authored synthetic metadata only.

Imports no pytest/conftest helpers, provider, server, credentials or T1 helpers, and
reads no real inputs; under pytest, tests/conftest.py's autouse fixtures still apply.
Reads only the new module/schema/contract; executes verified source bytes directly.
"""

import argparse
import ast
import contextlib
import copy
import decimal
import hashlib
import io
import json
import os
import re
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "configs/architecture/bin/context_t1_preflight.py"
SCHEMA_PATH = ROOT / "configs/architecture/stages/context_profile/t1/preflight.v1.schema.json"
CONTRACT_PATH = ROOT / "configs/architecture/stages/context_profile/t1/PREFLIGHT.md"
# Expected source SHA256s; setUpModule binds them when no CLI arguments did (pytest, hook, CI).
PINNED_MODULE_SHA256 = "3f21873b43f22486401dd63d560dad30c5801c6550b28583e50977e8dee83ca7"
PINNED_SCHEMA_SHA256 = "30e59f22e3badac42dfa8a860cdd494b37c192808bc41086fb31e6c8a90f9699"
PINNED_CONTRACT_SHA256 = "57032cb078ddf72dd7c35716c311c6203f5860379d82a0c26f510ab124266b38"
NOW = "2001-01-01T00:10:00Z"
SLOT_NAMES = ("A1", "A2", "A3", "B1", "B2", "B3")
PIN_NAMES = ("source_sha256", "config_sha256", "pricing_sha256", "input_sha256", "packet_sha256", "projection_sha256", "freeze_sha256", "plan_sha256")
EVIDENCE_NAMES = ("admission", "loaded_route", "request_shape", "projection_provenance", "pricing", "cache", "output_bound", "containment", "observer", "budget", "quota", "custody")
SETTING_NAMES = ("provider", "model", "route", "auth_mode", "credential_policy", "output_bound_mode", "config_sha256", "body_sha256", "body_bytes", "input_length_basis", "output_bound", "output_bound_enforced", "reasoning_included", "cache_policy", "input_category", "output_category", "currency", "input_rate_usd_per_million", "output_rate_usd_per_million")
ERROR_CODES = set("INPUT_TYPE INPUT_SIZE UTF8 JSON_SYNTAX DUPLICATE_KEY NONFINITE JSON_NUMBER NUMBER_BOUND JSON_LIMIT FIELDS SCHEMA IDENTITY TYPE UTC WINDOW EVIDENCE ROUTE SETTINGS PRICE BINDING SLOTS UUID UUID_REUSE USED_SLOT DRIFT TOTAL_CAP SLOT_CAP FRONTIER ACTIVE_CAP RESERVATION".split())
MODULE_BYTES = b""
SCHEMA = {}
CANDIDATE = None
OBSERVED = {"core": 0, "closure": 0, "positive_core": 0, "negative_core": 0}


def encode(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def fixture():
    """Toy declarations, not bytes/identities/rates from any real packet."""
    window = {"not_before_utc": "2001-01-01T00:00:00Z", "expires_utc": "2001-01-01T01:00:00Z"}
    families = {}
    for family in ("A", "B"):
        a = family == "A"
        families[family] = {
            "provider": "anthropic" if a else "openai",
            "model": "claude-opus-5-5" if a else "gpt-6.1-sol",
            "route": "anthropic-oauth-named-token" if a else "openai-codex-oauth",
            "auth_mode": "oauth", "credential_policy": "named-token" if a else "Codex",
            "output_bound_mode": "request_limit" if a else "documented_max",
            "config_sha256": ("c" if a else "d") * 64,
            "body_sha256": ("a" if a else "b") * 64,
            "body_bytes": 1000, "input_length_basis": "final_serialized_input_utf8",
            "output_bound": 1000, "output_bound_enforced": True, "reasoning_included": True,
            "cache_policy": "no_cache" if a else "cached_input_at_most_base",
            "input_category": "base", "output_category": "all_output_including_reasoning",
            "currency": "USD", "input_rate_usd_per_million": "1", "output_rate_usd_per_million": "1",
        }
    expected = {
        "schema": "context-t1-preflight-expected/v1", "scope": "SYNTHETIC_ONLY",
        "experiment_id": "synthetic-experiment", "binding_id": "synthetic-binding",
        "pins": {name: f"{index + 1:064x}" for index, name in enumerate(PIN_NAMES)},
        "window": copy.deepcopy(window),
        "evidence": {name: dict(state="COMPLETE", sha256=f"{index + 100:064x}", **window)
                     for index, name in enumerate(EVIDENCE_NAMES)},
        "families": families,
    }
    plan = {name: copy.deepcopy(value) for name, value in expected.items() if name != "families"}
    plan["schema"] = "context-t1-preflight-plan/v1"
    plan["slots"] = [{
        "slot": name, "family": name[0],
        "session_id": f"{index + 1:08x}-0000-4000-8000-000000000001",
        "run_id": f"{index + 11:08x}-0000-4000-8000-000000000001",
        "settings": copy.deepcopy(families[name[0]]),
        "root_state": "IDLE", "claim_state": "ABSENT", "output_state": "ABSENT",
        "reservation_usd": "0.002",
    } for index, name in enumerate(SLOT_NAMES)]
    plan["total_reservation_usd"] = "0.012"
    plan["frontier"] = {"active_slots": ["A1", "B1"], "reservation_usd": "0.004"}
    return plan, expected


def settings_for_all(plan, expected, **changes):
    for settings in expected["families"].values():
        settings.update(changes)
    for slot in plan["slots"]:
        slot["settings"].update(changes)


def set_amounts(plan, each, total, active):
    for slot in plan["slots"]:
        slot["reservation_usd"] = each
    plan["total_reservation_usd"] = total
    plan["frontier"]["reservation_usd"] = active


def positive_cases():
    cases = []
    for number in range(1, 11):
        plan, expected = fixture()
        now = NOW
        if number == 2:
            plan["frontier"] = {"active_slots": [], "reservation_usd": "0"}
        elif number == 3:
            plan["frontier"] = {"active_slots": ["A2"], "reservation_usd": "0.002"}
        elif number == 4:
            settings_for_all(plan, expected, body_bytes=1000000, output_bound=1000000,
                             input_rate_usd_per_million="2", output_rate_usd_per_million="3")
            set_amounts(plan, "5", "30", "10")
        elif number == 5:
            settings_for_all(plan, expected, input_rate_usd_per_million="0", output_rate_usd_per_million="0")
            set_amounts(plan, "0", "0", "0")
        elif number == 6:
            settings_for_all(plan, expected, body_bytes=1, output_bound=1,
                             input_rate_usd_per_million="0.123456789012345678901234", output_rate_usd_per_million="0")
            # Independent literal arithmetic answers frozen before the implementation.
            set_amounts(plan, "0.000000123456789012345678901234",
                        "0.000000740740734074074073407404", "0.000000246913578024691357802468")
        elif number == 7:
            plan["slots"].reverse()
        elif number == 8:
            now = "2001-01-01T00:00:00Z"
        elif number == 9:
            now = "2001-01-01T00:59:59Z"
        elif number == 10:
            for doc in (plan, expected):
                doc["binding_id"] = "synthetic-other-binding"
                doc["experiment_id"] = "synthetic-other-experiment"
                doc["pins"] = {name: f"{index + 301:064x}" for index, name in enumerate(PIN_NAMES)}
            for index, slot in enumerate(plan["slots"]):
                slot["session_id"] = f"{index + 101:08x}-0000-4000-8000-000000000002"
                slot["run_id"] = f"{index + 111:08x}-0000-4000-8000-000000000002"
        cases.append((f"P{number:02d}", plan, expected, now))
    return cases


class BytesSubclass(bytes):
    pass


def negative_cases():
    """Literal known negatives, not expectations derived from the candidate."""
    cases = []

    def add(number, code, change=None, raw_plan=None, raw_expected=None, now=NOW):
        plan, expected = fixture()
        if change is not None:
            change(plan, expected)
        cases.append((f"N{number:02d}", encode(plan) if raw_plan is None else raw_plan,
                      encode(expected) if raw_expected is None else raw_expected, now, code))

    base_plan, base_expected = fixture()
    raw = encode(base_plan)
    add(1, "INPUT_TYPE", raw_plan=raw.decode())
    add(2, "INPUT_TYPE", raw_plan=bytearray(raw))
    add(3, "INPUT_TYPE", raw_plan=BytesSubclass(raw))
    add(4, "INPUT_TYPE", raw_expected=encode(base_expected).decode())
    add(5, "INPUT_SIZE", raw_plan=b" " * 65537)
    add(6, "INPUT_SIZE", raw_expected=b" " * 65537)
    add(7, "UTF8", raw_plan=b"\xff")
    add(8, "UTF8", raw_expected=b"\xff")
    for number, bad in enumerate((b'{"schema":', raw + b" false", b"\xef\xbb\xbf" + raw, b""), 9):
        add(number, "JSON_SYNTAX", raw_plan=bad)
    add(13, "DUPLICATE_KEY", raw_plan=b'{"schema":1,"schema":2}')
    add(14, "DUPLICATE_KEY", raw_plan=b'{"x":{"y":1,"y":2}}')
    add(15, "DUPLICATE_KEY", raw_plan=b'{"schema":1,"sch\\u0065ma":2}')
    for number, token in enumerate((b"NaN", b"Infinity", b"-Infinity"), 16):
        add(number, "NONFINITE", raw_plan=token)
    add(19, "JSON_NUMBER", raw_plan=b"1.0")
    add(20, "JSON_NUMBER", raw_plan=b"1e999")
    add(21, "NUMBER_BOUND", raw_plan=b"10000000000")
    add(22, "NUMBER_BOUND", raw_plan=b"1000000001")
    add(23, "JSON_LIMIT", raw_plan=b"[" * 17 + b"0" + b"]" * 17)
    add(24, "JSON_LIMIT", raw_plan=encode([0] * 4097))
    add(25, "JSON_LIMIT", raw_plan=encode("x" * 513))
    add(26, "UTF8", raw_plan=b'{"x":"\\ud800"}')
    add(27, "UTF8", raw_plan=b'{"\\udfff":1}')
    add(28, "FIELDS", raw_plan=b"[]")
    add(29, "FIELDS", raw_plan=b"null")
    add(30, "SCHEMA", lambda p, e: p.update(schema="wrong"))
    add(31, "SCHEMA", lambda p, e: p.update(scope="REAL"))
    add(32, "UUID", lambda p, e: p["slots"][0].update(session_id="not-a-uuid"))
    add(33, "UUID", lambda p, e: p["slots"][0].update(run_id="00000000-0000-0000-0000-000000000000"))
    add(34, "UUID_REUSE", lambda p, e: p["slots"][1].update(session_id=p["slots"][0]["session_id"]))
    add(35, "UUID_REUSE", lambda p, e: p["slots"][1].update(run_id=p["slots"][0]["run_id"]))
    add(36, "UUID_REUSE", lambda p, e: p["slots"][0].update(run_id=p["slots"][0]["session_id"]))
    add(37, "SLOTS", lambda p, e: p["slots"].pop())
    add(38, "SLOTS", lambda p, e: p["slots"][1].update(slot="A1"))
    add(39, "SLOTS", lambda p, e: p["slots"].append(copy.deepcopy(p["slots"][0])))
    add(40, "SLOTS", lambda p, e: p["slots"][0].update(family="B"))
    route_fields = ("provider", "model", "route", "auth_mode", "credential_policy", "output_bound_mode")
    for number, field in enumerate(route_fields, 41):
        add(number, "ROUTE", lambda p, e, field=field: p["slots"][0]["settings"].update({field: "wrong"}))
    for number, field in enumerate(route_fields, 47):
        add(number, "ROUTE", lambda p, e, field=field: p["slots"][3]["settings"].update({field: "wrong"}))
    add(53, "ROUTE", lambda p, e: p["slots"][3]["settings"].update(provider="openai_codex"))
    add(54, "FIELDS", lambda p, e: p["slots"][3]["settings"].update(token="SYNTHETIC_CANARY_ONLY"))
    add(55, "FIELDS", lambda p, e: p["slots"][0]["settings"].update(token_selector="SYNTHETIC_CANARY_ONLY"))
    add(56, "FIELDS", lambda p, e: p["slots"][3]["settings"].update(max_output_tokens=1000))
    for number, (field, value) in enumerate((
        ("cache_policy", "UNKNOWN"), ("input_category", "UNKNOWN"), ("output_category", "UNKNOWN"),
        ("input_length_basis", "prompt_length"), ("output_bound_enforced", False),
        ("reasoning_included", False), ("currency", "UNKNOWN"),
    ), 57):
        add(number, "SETTINGS", lambda p, e, field=field, value=value: p["slots"][0]["settings"].update({field: value}))
    for number, field, value, code in (
        (64, "body_bytes", True, "TYPE"), (65, "output_bound", True, "TYPE"),
        (66, "body_bytes", 0, "TYPE"), (67, "output_bound", -1, "TYPE"),
        (68, "body_bytes", 1000000001, "NUMBER_BOUND"),
    ):
        add(number, code, lambda p, e, field=field, value=value: p["slots"][0]["settings"].update({field: value}))
    add(69, "DRIFT", lambda p, e: p["slots"][1]["settings"].update(body_sha256="e" * 64))
    add(70, "DRIFT", lambda p, e: p["slots"][1]["settings"].update(input_rate_usd_per_million="1.1"))
    add(71, "BINDING", lambda p, e: p.update(binding_id="synthetic-drift"))
    add(72, "BINDING", lambda p, e: p["pins"].update(source_sha256="e" * 64))
    add(73, "BINDING", lambda p, e: p["window"].update(not_before_utc="2001-01-01T00:01:00Z"))
    add(74, "BINDING", lambda p, e: p["evidence"]["quota"].update(sha256="e" * 64))
    add(75, "WINDOW", lambda p, e: p["window"].update(expires_utc="2001-01-01T00:09:59Z"))
    add(76, "WINDOW", lambda p, e: p["window"].update(not_before_utc="2001-01-01T00:10:01Z"))
    add(77, "WINDOW", lambda p, e: p["window"].update(not_before_utc="2001-01-01T02:00:00Z"))
    add(78, "WINDOW", lambda p, e: p["window"].update(expires_utc=p["window"]["not_before_utc"]))
    add(79, "UTC", now="2001-02-30T00:10:00Z")
    add(80, "UTC", now="2001-01-01T00:10:00+00:00")
    add(81, "EVIDENCE", lambda p, e: p["evidence"]["quota"].update(state="UNKNOWN"))
    add(82, "EVIDENCE", lambda p, e: p["evidence"]["cache"].update(not_before_utc="2001-01-01T00:01:00Z"))
    add(83, "EVIDENCE", lambda p, e: p["evidence"]["pricing"].update(expires_utc="2001-01-01T00:09:59Z"))
    rate_negatives = (None, 1.25, "UNKNOWN", "NaN", "Infinity", "-1", "1e-3", "0." + "1" * 25, "01", " 1")
    for number, value in enumerate(rate_negatives, 84):
        code = "JSON_NUMBER" if number == 85 else "PRICE"
        add(number, code, lambda p, e, value=value: p["slots"][0]["settings"].update(input_rate_usd_per_million=value))
    add(94, "RESERVATION", lambda p, e: p["slots"][0].update(reservation_usd="0.003"))
    add(95, "RESERVATION", lambda p, e: p.update(total_reservation_usd="0.013"))
    add(96, "RESERVATION", lambda p, e: p["frontier"].update(reservation_usd="0.005"))

    def individual_cap(p, e):
        # H-D0-N97-2 (#212, from #200's H-D0-META-2): rates consistent within each
        # family, so no earlier DRIFT. All A (A1-A3 and expected A) compute/claim 6,
        # all B 1, total 21, frontier A1+B1 7; only the individual cap (5) fails.
        # Known answer unchanged.
        settings_for_all(p, e, body_bytes=1000000, output_bound=1000000,
                         input_rate_usd_per_million="0.5", output_rate_usd_per_million="0.5")
        set_amounts(p, "1", "21", "7")
        e["families"]["A"].update(input_rate_usd_per_million="3", output_rate_usd_per_million="3")
        for slot in p["slots"]:
            if slot["family"] == "A":
                slot["settings"].update(input_rate_usd_per_million="3", output_rate_usd_per_million="3")
                slot["reservation_usd"] = "6"

    add(97, "SLOT_CAP", individual_cap)

    def total_cap(p, e):
        settings_for_all(p, e, body_bytes=1000000, output_bound=1000000,
                         input_rate_usd_per_million="3", output_rate_usd_per_million="3")
        set_amounts(p, "6", "36", "12")

    add(98, "TOTAL_CAP", total_cap)
    add(99, "TOTAL_CAP", lambda p, e: p.update(total_reservation_usd="30.000001"))
    add(100, "ACTIVE_CAP", lambda p, e: p["frontier"].update(reservation_usd="10.000001"))
    for number, active in enumerate((["A1", "B1", "A2"], ["A1", "A1"], ["A1", "A2"], ["X1"]), 101):
        add(number, "FRONTIER", lambda p, e, active=active: p["frontier"].update(active_slots=active))
    for number, field, value in ((105, "root_state", "USED"), (106, "claim_state", "PRESENT"),
                                  (107, "output_state", "PRESENT"), (108, "root_state", "UNKNOWN")):
        add(number, "USED_SLOT", lambda p, e, field=field, value=value: p["slots"][0].update({field: value}))
    add(109, "PRICE", lambda p, e: p["slots"][0]["settings"].update(input_rate_usd_per_million=1))
    add(110, "PRICE", lambda p, e: p["slots"][0]["settings"].update(input_rate_usd_per_million="0." + "0" * 31 + "1"))
    add(111, "ROUTE", lambda p, e: p["slots"][3]["settings"].update(output_bound_mode="unknown"))
    add(112, "DUPLICATE_KEY", raw_expected=b'{"x":1,"x":2}')
    add(113, "NONFINITE", raw_expected=b"NaN")
    add(114, "PRICE", lambda p, e: p["slots"][0].update(reservation_usd="0." + "1" * 31))
    # None is a raw now value here, not the raw-input sentinel used by add().
    add(115, "UTC", now=None)
    add(116, "UTC", now=1)
    add(117, "WINDOW", now="2001-01-01T01:00:00Z")
    add(118, "EVIDENCE", lambda p, e: p["evidence"]["cache"].update(not_before_utc="2001-01-01T02:00:00Z"))
    add(119, "NUMBER_BOUND", raw_plan=b"1" * 5000)
    add(120, "JSON_LIMIT", raw_plan=b"[" * 5000 + b"0" + b"]" * 5000)
    add(121, "FIELDS", lambda p, e: p["evidence"].update(unknown=copy.deepcopy(p["evidence"]["quota"])))
    add(122, "UUID", lambda p, e: p["slots"][0].update(session_id="AAAAAAAA-0000-4000-8000-000000000001"))
    add(123, "FIELDS", lambda p, e: e["families"].update(C=copy.deepcopy(e["families"]["A"])))
    add(124, "SLOTS", lambda p, e: p.update(slots=[]))
    add(125, "FIELDS", lambda p, e: p["slots"][0]["settings"].update(registry_alias="synthetic"))
    add(126, "TYPE", lambda p, e: p["slots"][0]["settings"].update(body_bytes=None))
    add(127, "PRICE", lambda p, e: p["slots"][0].update(reservation_usd=None))
    add(128, "PRICE", lambda p, e: p["slots"][0].update(reservation_usd=True))

    # H-D0-CAPS-1 (#224, from #220's M1): N129-N131 each go over one cap on one side
    # only (computed or claimed); with that side off, a later check gives another code.
    def slot_cap_computed_only(p, e):
        # N97's settings: A1-A3 and expected A compute 6, all B 1. Every slot claims 1,
        # total 6, frontier A1+B1 2. Without SLOT_CAP's computed side: RESERVATION.
        settings_for_all(p, e, body_bytes=1000000, output_bound=1000000,
                         input_rate_usd_per_million="0.5", output_rate_usd_per_million="0.5")
        e["families"]["A"].update(input_rate_usd_per_million="3", output_rate_usd_per_million="3")
        for slot in p["slots"]:
            if slot["family"] == "A":
                slot["settings"].update(input_rate_usd_per_million="3", output_rate_usd_per_million="3")
        set_amounts(p, "1", "6", "2")

    add(129, "SLOT_CAP", slot_cap_computed_only)

    def total_cap_computed_only(p, e):
        # N98's settings: all six compute 6, computed total 36. Every slot claims 5,
        # total 30, frontier 10. Without TOTAL_CAP's computed side: SLOT_CAP.
        settings_for_all(p, e, body_bytes=1000000, output_bound=1000000,
                         input_rate_usd_per_million="3", output_rate_usd_per_million="3")
        set_amounts(p, "5", "30", "10")

    add(130, "TOTAL_CAP", total_cap_computed_only)

    def slot_cap_claimed_only(p, e):
        # Base settings: each slot computes 0.002. A1 (slot 0) claims 6, so the total
        # and frontier (A1+B1) claims rise by the same 5.998 and stay within 30 and 10.
        # Without SLOT_CAP's claimed side: RESERVATION.
        p["slots"][0]["reservation_usd"] = "6"
        p["total_reservation_usd"] = "6.010"
        p["frontier"]["reservation_usd"] = "6.002"

    add(131, "SLOT_CAP", slot_cap_claimed_only)
    return cases


def resolve(shape):
    while "$ref" in shape:
        shape = SCHEMA["$defs"][shape["$ref"].split("/")[-1]]
    return shape


def closed_shape(shape):
    shape = resolve(shape)
    if shape.get("additionalProperties") is False:
        return shape
    for component in shape.get("allOf", []):
        answer = closed_shape(component)
        if answer is not None:
            return answer
    return None


def objects(value, shape, path=()):
    """Inventory comes from frozen schema and toy data, never candidate constants."""
    if type(value) is dict:
        closed = closed_shape(shape)
        if closed is None:
            raise AssertionError("object lacks closed schema")
        yield path, closed
        for key in value:
            yield from objects(value[key], closed["properties"][key], path + (key,))
    elif type(value) is list:
        shape = resolve(shape)
        for index, child in enumerate(value):
            yield from objects(child, shape["items"], path + (index,))


def at(value, path):
    for component in path:
        value = value[component]
    return value


def wrong_type(value):
    if type(value) is str:
        return []
    if type(value) is bool:
        return 1
    if type(value) is int:
        return "1"
    if type(value) is dict:
        return []
    if type(value) is list:
        return {}
    raise AssertionError("unexpected fixture type")


def closure_cases():
    for side, definition in ((0, "plan"), (1, "expected")):
        baseline = fixture()
        for path, shape in objects(baseline[side], SCHEMA["$defs"][definition]):
            for field in shape["required"]:
                for operation in ("missing", "null", "wrong_type"):
                    pair = fixture()
                    target = at(pair[side], path)
                    if operation == "missing":
                        del target[field]
                    elif operation == "null":
                        target[field] = None
                    else:
                        target[field] = wrong_type(target[field])
                    name = f"C:{definition}:{'/'.join(map(str, path))}:{field}:{operation}"
                    yield name, pair[0], pair[1]
            pair = fixture()
            at(pair[side], path)["unknown_field"] = "SYNTHETIC_CANARY_ONLY"
            yield f"C:{definition}:{'/'.join(map(str, path))}:extra", pair[0], pair[1]


def exact_equal(a, b):
    return type(a) is type(b) and a == b


def schema_accepts(value, shape):
    """Independent evaluator of ONLY the keywords in this frozen schema.

    Not advertised as a general JSON Schema implementation. It imports neither
    candidate code nor a schema library, and treats bool/int distinctly.
    """
    shape = resolve(shape)
    if "oneOf" in shape and sum(schema_accepts(value, item) for item in shape["oneOf"]) != 1:
        return False
    if "allOf" in shape and not all(schema_accepts(value, item) for item in shape["allOf"]):
        return False
    if "if" in shape:
        branch = "then" if schema_accepts(value, shape["if"]) else "else"
        if branch in shape and not schema_accepts(value, shape[branch]):
            return False
    if "not" in shape and schema_accepts(value, shape["not"]):
        return False
    if "const" in shape and not exact_equal(value, shape["const"]):
        return False
    if "enum" in shape and not any(exact_equal(value, item) for item in shape["enum"]):
        return False
    kinds = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if "type" in shape and type(value) is not kinds[shape["type"]]:
        return False
    if type(value) is dict:
        properties = shape.get("properties", {})
        if any(field not in value for field in shape.get("required", [])):
            return False
        if shape.get("additionalProperties") is False and set(value) - set(properties):
            return False
        if any(not schema_accepts(value[key], child) for key, child in properties.items() if key in value):
            return False
    if type(value) is list:
        if len(value) < shape.get("minItems", 0) or len(value) > shape.get("maxItems", 1000000):
            return False
        if shape.get("uniqueItems") and len({encode(item) for item in value}) != len(value):
            return False
        if "items" in shape and not all(schema_accepts(item, shape["items"]) for item in value):
            return False
    if type(value) is str:
        if "pattern" in shape and re.fullmatch(shape["pattern"], value) is None:
            return False
        if shape.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return False
    if type(value) is int and not (shape.get("minimum", value) <= value <= shape.get("maximum", value)):
        return False
    return True


class PreflightTests(unittest.TestCase):
    def call(self, plan, expected, now=NOW):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            answer = CANDIDATE.check_plan(plan, expected, now)
        self.assertEqual(stdout.getvalue(), "", "unexpected stdout")
        self.assertEqual(stderr.getvalue(), "", "unexpected stderr")
        self.assertEqual(set(answer), {"schema", "status", "error_codes", "metadata_only", "authorizes_dispatch", "authorizes_later_stage"})
        self.assertEqual(answer["schema"], "context-t1-preflight/v1")
        self.assertIs(answer["metadata_only"], True)
        self.assertIs(answer["authorizes_dispatch"], False)
        self.assertIs(answer["authorizes_later_stage"], False)
        self.assertTrue(schema_accepts(answer, SCHEMA["$defs"]["result"]))
        self.assertTrue(all(code in ERROR_CODES for code in answer["error_codes"]))
        # Exact output field/value closure means there is no channel for metadata echo.
        return answer

    def test_01_frozen_core(self):
        positives = positive_cases()
        negatives = negative_cases()
        self.assertEqual([case[0] for case in positives], [f"P{i:02d}" for i in range(1, 11)])
        self.assertEqual([case[0] for case in negatives], [f"N{i:02d}" for i in range(1, 132)])
        for name, plan, expected, now in positives:
            with self.subTest(case=name):
                OBSERVED["core"] += 1
                OBSERVED["positive_core"] += 1
                answer = self.call(encode(plan), encode(expected), now)
                self.assertEqual(answer["status"], "METADATA_PASS")
                self.assertEqual(answer["error_codes"], [])
        for name, plan, expected, now, code in negatives:
            with self.subTest(case=name):
                OBSERVED["core"] += 1
                OBSERVED["negative_core"] += 1
                answer = self.call(plan, expected, now)
                self.assertEqual(answer["status"], "REJECT")
                self.assertEqual(answer["error_codes"], [code])

    def test_02_frozen_closure_cross_products(self):
        count = 0
        for name, plan, expected in closure_cases():
            with self.subTest(case=name):
                count += 1
                OBSERVED["closure"] += 1
                answer = self.call(encode(plan), encode(expected))
                self.assertEqual(answer["status"], "REJECT")
                self.assertEqual(len(answer["error_codes"]), 1)
        self.assertEqual(count, 1152)

    def test_03_schema_independent_contract_walk(self):
        definitions = SCHEMA["$defs"]
        fields = {
            "plan": "schema scope experiment_id binding_id pins window evidence slots total_reservation_usd frontier".split(),
            "expected": "schema scope experiment_id binding_id pins window evidence families".split(),
            "pins": PIN_NAMES, "window": ("not_before_utc", "expires_utc"), "evidence": EVIDENCE_NAMES,
            "evidence_record": ("state", "sha256", "not_before_utc", "expires_utc"),
            "families": ("A", "B"), "settings": SETTING_NAMES,
            "slot": "slot family session_id run_id settings root_state claim_state output_state reservation_usd".split(),
            "frontier": ("active_slots", "reservation_usd"),
            "result": "schema status error_codes metadata_only authorizes_dispatch authorizes_later_stage".split(),
        }
        for name, required in fields.items():
            with self.subTest(definition=name):
                shape = definitions[name]
                self.assertIs(shape["additionalProperties"], False)
                self.assertEqual(set(shape["required"]), set(required))
                self.assertEqual(set(shape["properties"]), set(required))
        self.assertEqual(set(definitions["result"]["properties"]["error_codes"]["items"]["enum"]), ERROR_CODES)
        self.assertEqual(definitions["plan"]["properties"]["schema"]["const"], "context-t1-preflight-plan/v1")
        self.assertEqual(definitions["expected"]["properties"]["schema"]["const"], "context-t1-preflight-expected/v1")
        self.assertEqual(definitions["result"]["properties"]["schema"]["const"], "context-t1-preflight/v1")
        self.assertEqual(definitions["settings"]["properties"]["provider"]["enum"], ["anthropic", "openai"])
        self.assertEqual(definitions["settings"]["properties"]["model"]["enum"], ["claude-opus-5-5", "gpt-6.1-sol"])
        self.assertEqual(definitions["positive_integer"], {"type": "integer", "minimum": 1, "maximum": 1000000000})
        self.assertEqual(definitions["rate"]["pattern"], r"^(0|[1-9][0-9]{0,11})(\.[0-9]{1,24})?$")
        self.assertEqual(definitions["amount"]["pattern"], r"^(0|[1-9][0-9]{0,11})(\.[0-9]{1,30})?$")
        for name, plan, expected, now in positive_cases():
            with self.subTest(schema_positive=name):
                self.assertTrue(schema_accepts(plan, definitions["plan"]))
                self.assertTrue(schema_accepts(expected, definitions["expected"]))
        for name, plan, expected in closure_cases():
            with self.subTest(schema_negative=name):
                self.assertFalse(schema_accepts(plan, definitions["plan"]) and schema_accepts(expected, definitions["expected"]))
        pair = fixture()
        inventory = [(side, path, shape) for side, definition in ((0, "plan"), (1, "expected"))
                     for path, shape in objects(pair[side], definitions[definition])]
        self.assertEqual(len(inventory), 48)
        self.assertEqual(sum(len(shape["required"]) for _, _, shape in inventory), 368)

    def test_04_no_operational_dependencies_ast(self):
        tree = ast.parse(MODULE_BYTES, filename=str(MODULE_PATH))
        allowed = {"json", "re", "datetime", "decimal"}
        forbidden_names = {"open", "input", "print", "eval", "exec", "compile", "__import__", "getattr", "setattr", "globals", "locals", "breakpoint"}
        forbidden_attributes = {"open", "read", "write", "environ", "getenv", "putenv", "system", "spawn", "connect", "socket", "Popen", "request", "post", "now", "utcnow", "today", "strptime"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name in allowed for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed)
                self.assertEqual(node.level, 0)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, forbidden_names)
            elif isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden_attributes)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                self.fail("mutable external state")
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Import, ast.ImportFrom, ast.Assign, ast.ClassDef, ast.FunctionDef))
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)
            if isinstance(node, ast.Assign):
                for call in (item for item in ast.walk(node.value) if isinstance(item, ast.Call)):
                    self.assertIsInstance(call.func, ast.Name)
                    self.assertEqual(call.func.id, "frozenset")
        self.assertEqual(CANDIDATE.check_plan.__annotations__, {"plan_json": bytes, "expected_json": bytes, "now_utc": str, "return": dict})

    def test_05_runtime_tripwires_and_non_authorizing_idempotence(self):
        plan, expected = fixture()
        plan_raw, expected_raw = encode(plan), encode(expected)
        before = copy.deepcopy((plan, expected))
        canary_plan = copy.deepcopy(plan)
        canary_plan["unknown_field"] = "SYNTHETIC_CANARY_ONLY"
        bad_raw = encode(canary_plan)

        class ForbiddenEnvironment:
            def __getitem__(self, key):
                raise AssertionError("environment read")

            def __iter__(self):
                raise AssertionError("environment iteration")

            def get(self, *args):
                raise AssertionError("environment read")

        with contextlib.ExitStack() as stack:
            for entry in ("builtins.open", "io.open", "os.getenv", "os.putenv", "socket.socket", "socket.create_connection", "subprocess.Popen"):
                stack.enter_context(mock.patch(entry, side_effect=AssertionError("operational dependency")))
            stack.enter_context(mock.patch.object(os, "environ", ForbiddenEnvironment()))
            one = self.call(plan_raw, expected_raw)
            two = self.call(plan_raw, expected_raw)
            rejected = self.call(bad_raw, expected_raw)
        self.assertEqual(one, two)
        self.assertEqual(one["status"], "METADATA_PASS")
        self.assertEqual(rejected["status"], "REJECT")
        self.assertNotIn("SYNTHETIC_CANARY_ONLY", json.dumps(rejected))
        self.assertEqual((plan, expected), before)
        self.assertEqual(plan_raw, encode(plan))
        self.assertEqual(expected_raw, encode(expected))

    def test_06_exact_decimal_independent_of_caller_context(self):
        _, plan, expected, now = positive_cases()[5]
        with decimal.localcontext() as external:
            external.prec = 2
            external.Emax = 5
            external.Emin = -5
            external.traps[decimal.Inexact] = True
            external.traps[decimal.Rounded] = True
            before = str(external)
            answer = self.call(encode(plan), encode(expected), now)
            self.assertEqual(answer["status"], "METADATA_PASS")
            bad = copy.deepcopy(plan)
            bad["slots"][0]["reservation_usd"] = "0.000000123456789012345678901235"
            answer = self.call(encode(bad), encode(expected), now)
            self.assertEqual(answer["error_codes"], ["RESERVATION"])
            self.assertEqual(str(external), before)


def bind_candidate(module_sha256, schema_sha256, contract_sha256):
    global MODULE_BYTES, SCHEMA, CANDIDATE
    bindings = {}
    source_files = ((MODULE_PATH, module_sha256), (SCHEMA_PATH, schema_sha256),
                    (CONTRACT_PATH, contract_sha256))
    data = []
    for path, expected in source_files:
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise SystemExit("SOURCE_BINDING_MISMATCH: " + str(path))
        bindings[str(path)] = {"sha256": actual, "bytes": len(raw)}
        data.append(raw)
    MODULE_BYTES = data[0]
    SCHEMA = json.loads(data[1])
    # No importlib source/pyc fallback. Compile exactly the already hashed bytes.
    CANDIDATE = types.ModuleType("synthetic_context_t1_preflight_candidate")
    CANDIDATE.__file__ = str(MODULE_PATH)
    exec(compile(MODULE_BYTES, str(MODULE_PATH), "exec", dont_inherit=True), CANDIDATE.__dict__)
    return bindings


def setUpModule():
    # pytest, the commit hook and CI give no CLI arguments: bind the in-file pins.
    # A CLI run has already bound its own arguments in main(), so this does nothing there.
    # A mismatch raises SystemExit (SOURCE_BINDING_MISMATCH): an error, never a skip.
    if CANDIDATE is None:
        bind_candidate(PINNED_MODULE_SHA256, PINNED_SCHEMA_SHA256, PINNED_CONTRACT_SHA256)


def main():
    parser = argparse.ArgumentParser(description="Single final synthetic candidate suite")
    parser.add_argument("--module-sha256", required=True)
    parser.add_argument("--schema-sha256", required=True)
    parser.add_argument("--contract-sha256", required=True)
    args = parser.parse_args()
    bindings = bind_candidate(args.module_sha256, args.schema_sha256, args.contract_sha256)
    print("SOURCE_BINDINGS " + json.dumps(bindings, sort_keys=True), flush=True)
    print("PLANNED_DENOMINATORS core=141 (positive=10 negative=131) closure=1152 total=1293 harness_methods=4", flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PreflightTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("OBSERVED_DENOMINATORS " + json.dumps(OBSERVED, sort_keys=True), flush=True)
    print("ORIGINAL_RESULT " + json.dumps({"testsRun": result.testsRun, "failures": len(result.failures),
                                         "errors": len(result.errors), "successful": result.wasSuccessful()}, sort_keys=True), flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
