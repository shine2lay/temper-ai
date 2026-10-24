#!/usr/bin/env python3
"""Offline report orchestration, strict answers and native receipts; never a runner.

No response rewriting, repair, retry, model/network call or credential access. The
existing diagnostic CLIs keep their BLOCKED / NOT_MEASURED behavior and formats.
Only numeric/enum aggregates go to stdout; full diagnostics remain private.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p = _module("context_profile_candidate_prepare")
cpc = _module("context_profile_check")
SCRIPTS = {
    "checker": (HERE / "context_profile_check.py", "f49f759d1f91b69e3f02fb9c36bc272d838f7e11ea2651550550687320a67c46"),
    "scorer": (HERE / "context_profile_score.py", "ed866e0efa9345b7bf88ea827fbb069cb80d5246a58419b0211629883c9562e1"),
    "meaning": (HERE / "context_profile_meaning.py", "0f836cb18c27445aed6b24ed005ff07a0e078f2eee5123b99516f8b789067526"),
}
POSITIONS = tuple((case_id, repetition) for repetition in (1, 2, 3) for case_id in p.CASES)
FORMAT = "context-profile-candidate-report/v1"


def validate_raw(data: bytes, brief: bytes, schema: bytes) -> dict:
    """No fences, wrappers, duplicate keys, non-finite values, stripping or repair."""
    result = p.strict_json(data)
    p.need(isinstance(result, dict) and result.get("contract") == "context_profile/v2", "raw_not_profile")
    p.need(p.sha(schema) == p.SCHEMA_SHA256, "schema_not_frozen_v2")
    validator = cpc.Validator(p.strict_json(schema))
    checked = cpc.check(result, brief.decode("utf-8"), p.sha(brief), validator)
    p.need(checked["ok"] is True, "raw_structural_self_check_failed")
    # The optional v2 hash is not made mandatory and no field is ever inserted.
    return result


def positions(index: dict) -> list[dict]:
    p.fields(index, {"format", "experiment_id", "root_id", "packet_root", "runs"}, "index_shape")
    p.need(index["format"] == "context-profile-candidate-index/v1", "index_version")
    p.identifier(index["experiment_id"])
    p.identifier(index["root_id"])
    rows = index["runs"]
    p.need(isinstance(rows, list) and len(rows) == p.CALLS, "incomplete_pool")
    seen = set()
    for row in rows:
        p.fields(row, {"case_id", "repetition", "packet", "raw", "attempt", "call", "claim"}, "run_shape")
        p.need(type(row["repetition"]) is int, "invalid_position")
        pair = (row["case_id"], row["repetition"])
        p.need(pair in POSITIONS and pair not in seen, "duplicate_or_unknown_position")
        seen.add(pair)
    p.need(seen == set(POSITIONS), "incomplete_pool")
    return sorted(rows, key=lambda row: POSITIONS.index((row["case_id"], row["repetition"])))


def descriptor_file(descriptor: dict, *, maximum: int = 1048576) -> tuple[Path, bytes]:
    p.fields(descriptor, {"path", "bytes", "sha256"}, "evidence_descriptor")
    path = p.absolute(Path(descriptor["path"]))
    data = p.read_file(path, private=True, maximum=maximum)
    p.need(len(data) == p.count(descriptor["bytes"]) and p.sha(data) == p.digest(descriptor["sha256"]),
           "evidence_changed")
    return path, data


def completed(kind: str, exit_code: int, data: bytes) -> dict:
    """An expected exit 1 is a completed negative diagnostic, never cannot-run."""
    result = p.strict_json(data, decimals=True)
    p.need(isinstance(result, dict), "diagnostic_shape")
    if kind == "checker":
        p.need(exit_code in (0, 1) and type(result.get("ok")) is bool
               and result["ok"] is (exit_code == 0) and isinstance(result.get("errors"), list)
               and isinstance(result.get("counts"), dict), "checker_cannot_run")
    elif kind == "meaning":
        p.need(exit_code == 1 and result.get("format") == "context_profile_meaning/v0-layers12"
               and "error" not in result, "meaning_cannot_run")
        summary = p.fields(result.get("summary"), {"entries", "contradicted", "needs_judgment",
                                                  "numeric_limit_groups", "numeric_limit_deferred"}, "meaning_summary")
        for value in summary.values():
            p.count(value)
        p.need(summary["contradicted"] + summary["needs_judgment"] == summary["entries"]
               and summary["numeric_limit_deferred"] <= summary["numeric_limit_groups"], "meaning_summary")
    else:
        p.need(kind in ("profile", "pool", "consistency") and exit_code == 1
               and result.get("grading_output") == "context_profile_grade/v3" and result.get("kind") == kind
               and result.get("status") == "BLOCKED" and result.get("semantic_status") == "NOT_MEASURED"
               and result.get("score_pct", "missing") is None and result.get("semantic_score_pct", "missing") is None
               and result.get("meets_bars") is False and result.get("clean") is False
               and isinstance(result.get("structural_anchor"), dict) and "error" not in result,
               "scorer_cannot_run")
    return result


def diagnostic(script: str, kind: str, arguments: list[str]) -> tuple[dict, bytes]:
    path, expected = SCRIPTS[script]
    p.need(p.sha(p.read_file(path)) == expected, "diagnostic_source_changed")
    try:
        process = subprocess.run([sys.executable, "-I", str(path), *arguments], shell=False, check=False,
                                 cwd=HERE, env={"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"},
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise p.Refused("diagnostic_unavailable") from None
    p.need(len(process.stdout) <= 8 * 1048576, "diagnostic_too_large")
    return completed(kind, process.returncode, process.stdout), process.stdout


def write_evidence(fd: int, name: str, data: bytes) -> dict:
    p.need(Path(name).name == name and name not in (".", ".."), "evidence_name")
    target = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        os.fchmod(target, 0o600)
        with os.fdopen(os.dup(target), "wb") as stream:
            p.need(stream.write(data) == len(data), "short_write")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(target)
    os.fsync(fd)
    return {"bytes": len(data), "sha256": p.sha(data)}


def median(values: list[Decimal]) -> Decimal | None:
    if not values or any(value is None for value in values):
        return None
    values = sorted(values)
    n = len(values)
    with localcontext() as context:
        context.prec = 100
        return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2


RECEIPT_SCHEMAS = {
    "call": (p.REPO / "docs/schemas/context-t1-call.v1.schema.json",
             "6600452d0d24785b755b865b70718faf22205306d1b6f4d3a653bf23e53c854e"),
    "attempt": (p.REPO / p.STAGE / "t1/attempt.v1.schema.json",
                "ec678b1e6eaf653c0fa9a078a1d3ad11f4e8540c8d72af0f8a5ac4ae85e2d974"),
}


def utc_seconds(value) -> Decimal | None:
    if value is None:
        return None
    p.need(isinstance(value, str), "utc_type")
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,18}))?(?:Z|\+00:00)", value)
    p.need(match is not None, "utc_format")
    try:
        instant = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        raise p.Refused("utc_format") from None
    delta = instant - datetime(1970, 1, 1, tzinfo=UTC)
    with localcontext() as context:
        context.prec = 100
        return Decimal(delta.days * 86400 + delta.seconds) + Decimal("0." + (match[2] or "0"))


def canonical_uuid(value) -> str:
    try:
        parsed = uuid.UUID(value)
        p.need(str(parsed) == value and parsed.int != 0, "uuid_format")
    except (ValueError, TypeError, AttributeError):
        raise p.Refused("uuid_format") from None
    return value


class ReceiptValidator:
    """Closed subset for the two pinned native schemas, including conditionals/formats.

    Unknown keywords/formats/refs are refused at construction, NEVER ignored.
    Separate from the unmodified profile validator, whose keyword set is smaller.
    """
    KEYWORDS = {"$schema", "$id", "title", "description", "$defs", "$ref", "type", "additionalProperties",
                "required", "properties", "const", "enum", "items", "minLength", "pattern", "minimum", "maximum",
                "format", "uniqueItems", "allOf", "if", "then", "else"}

    def __init__(self, schema):
        self.schema = schema
        self._inspect(schema)

    def _inspect(self, schema):
        p.need(isinstance(schema, dict) and set(schema) <= self.KEYWORDS, "unsupported_schema_keyword")
        if "$ref" in schema:
            self._ref(schema["$ref"])
        if "format" in schema:
            p.need(schema["format"] in ("uuid", "date-time"), "unsupported_schema_format")
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            p.need(set(types) <= {"object", "array", "string", "number", "integer", "boolean", "null"}, "unsupported_schema_type")
        for keyword in ("properties", "$defs"):
            for child in schema.get(keyword, {}).values():
                self._inspect(child)
        for keyword in ("items", "if", "then", "else"):
            if keyword in schema:
                self._inspect(schema[keyword])
        for child in schema.get("allOf", []):
            self._inspect(child)
        if "additionalProperties" in schema:
            p.need(type(schema["additionalProperties"]) is bool, "unsupported_additional_properties")
        if "pattern" in schema:
            try:
                re.compile(schema["pattern"])
            except (TypeError, re.error):
                raise p.Refused("schema_pattern") from None

    def _ref(self, reference):
        p.need(isinstance(reference, str) and reference.startswith("#/$defs/"), "unsupported_schema_ref")
        name = reference[len("#/$defs/"):]
        p.need(name in self.schema.get("$defs", {}), "unsupported_schema_ref")
        return self.schema["$defs"][name]

    @staticmethod
    def _type(value, kind):
        number = type(value) is int or isinstance(value, Decimal) and value.is_finite()
        return {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
                "number": number, "integer": number and value == int(value), "boolean": type(value) is bool,
                "null": value is None}[kind]

    @staticmethod
    def _same(left, right):
        return (type(left) is bool) == (type(right) is bool) and left == right

    def matches(self, value, schema, depth=0):
        p.need(depth < 64, "schema_depth")
        if "$ref" in schema and not self.matches(value, self._ref(schema["$ref"]), depth + 1):
            return False
        types = schema.get("type")
        if types and not any(self._type(value, kind) for kind in (types if isinstance(types, list) else [types])):
            return False
        if "const" in schema and not self._same(value, schema["const"]):
            return False
        if "enum" in schema and not any(self._same(value, option) for option in schema["enum"]):
            return False
        if isinstance(value, dict):
            props = schema.get("properties", {})
            if not set(schema.get("required", [])) <= set(value):
                return False
            if schema.get("additionalProperties") is False and not set(value) <= set(props):
                return False
            if not all(self.matches(child, props[key], depth + 1) for key, child in value.items() if key in props):
                return False
        if isinstance(value, list):
            if schema.get("uniqueItems") and any(self._same(x, y) for n, x in enumerate(value) for y in value[:n]):
                return False
            if "items" in schema and not all(self.matches(child, schema["items"], depth + 1) for child in value):
                return False
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0) or "pattern" in schema and re.search(schema["pattern"], value) is None:
                return False
            if "format" in schema:
                try:
                    canonical_uuid(value) if schema["format"] == "uuid" else utc_seconds(value)
                except p.Refused:
                    return False
        if type(value) is int or isinstance(value, Decimal):
            if "minimum" in schema and value < schema["minimum"] or "maximum" in schema and value > schema["maximum"]:
                return False
        if not all(self.matches(value, child, depth + 1) for child in schema.get("allOf", [])):
            return False
        if "if" in schema:
            branch = "then" if self.matches(value, schema["if"], depth + 1) else "else"
            if branch in schema and not self.matches(value, schema[branch], depth + 1):
                return False
        return True

    def validate(self, value):
        p.need(self.matches(value, self.schema), "receipt_schema_failed")


def native_validator(kind: str) -> ReceiptValidator:
    path, expected = RECEIPT_SCHEMAS[kind]
    data = p.read_file(path)
    p.need(p.sha(data) == expected, "receipt_schema_changed")
    return ReceiptValidator(p.strict_json(data, decimals=True))


def usage_arithmetic(call: dict, input_rate, output_rate) -> tuple[str, Decimal | None]:
    """Documented pure base-total pricing; nullable counters are NEVER replaced by 0."""
    usage = call["usage"]
    for key in ("input_tokens", "output_tokens", "total_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        if usage[key] is not None:
            p.count(usage[key])
    incoming, outgoing = usage["input_tokens"], usage["output_tokens"]
    for key, subset, total in (("input_tokens_details", "cached_tokens", incoming),
                               ("output_tokens_details", "reasoning_tokens", outgoing)):
        details = usage.get(key)
        if details is not None and details.get(subset) is not None:
            p.count(details[subset])
            p.need(total is not None and details[subset] <= total, "invalid_usage_subset")
    if incoming is None or outgoing is None:
        return "UNKNOWN", None
    if usage["total_tokens"] is not None:
        p.need(usage["total_tokens"] == incoming + outgoing, "invalid_usage_total")
    if call["provider"] == "anthropic":
        caches = [usage[key] for key in ("cache_read_input_tokens", "cache_creation_input_tokens")]
        if any(value is None for value in caches):
            return "UNKNOWN_CACHE", None
        if any(value > 0 for value in caches):
            return "UNPRICED_CACHE", None
    return "KNOWN", p.exact_cost(incoming, outgoing, input_rate, output_rate)


def difference(end, start):
    if end is None or start is None:
        return None
    with localcontext() as context:
        context.prec = 100
        result = Decimal(end) - Decimal(start)
    p.need(result >= 0, "reversed_clock")
    return result


def compare(left, right):
    return "UNKNOWN" if left is None or right is None else "MATCH" if left == right else "MISMATCH"


def claim_observation(data: bytes | None) -> dict:
    # No published claim schema exists. Do not infer undocumented internals/completeness.
    return {"claim_presence": "MISSING" if data is None else "PRESENT",
            "claim_completeness": "INCOMPLETE" if data is not None and not data.strip() else "UNKNOWN"}


def audit_receipts(evidence: dict, packet: dict, raw_data: bytes, *, raw_path: Path | None = None) -> dict:
    attempt, call = evidence.get("attempt"), evidence.get("call")
    claim = claim_observation(evidence.get("claim"))
    if attempt is None or call is None:
        # A present claim cannot establish complete/validity without its schema. Retain UNKNOWN.
        return {"attempt_id": None, "terminal": "FAILED", "usage_state": "UNKNOWN", "cost_state": "UNKNOWN",
                "list_price_usd": None, "reservation_usd": None, "unknown_exposure_usd": None,
                "stop": "STOP_UNKNOWN", **claim}
    native_validator("attempt").validate(attempt)
    native_validator("call").validate(call)
    fixed = packet["single_call"]
    for name in ("slot", "experiment_id", "binding_id", "source_sha256", "config_sha256", "packet_sha256"):
        p.need(attempt[name] == fixed[name], "attempt_binding")
    for name, value in (("provider", packet["provider"]), ("model", packet["model"]),
                        ("route", fixed["route"]), ("auth_mode", fixed["auth_mode"]),
                        ("pricing_sha256", fixed["pricing_sha256"]), ("slot", fixed["slot"])):
        p.need(attempt[name] == value and call[name] == value, "receipt_route_binding")
    p.need(attempt["family"] == fixed["family"] and attempt["input_sha256"] == fixed["prompt_sha256"], "attempt_input_binding")
    p.need(attempt["raw_sha256"] == call["raw_sha256"] == p.sha(raw_data)
           and call["raw_bytes"] == len(raw_data), "raw_receipt_binding")
    if raw_path is not None:
        p.need(call["raw_path"] == str(raw_path), "raw_path_binding")
    run_id, session_id = canonical_uuid(attempt["run_id"]), canonical_uuid(attempt["session_id"])
    p.need(run_id != session_id and call["run_id"] == run_id and call["session_id"] == session_id, "receipt_identity")
    p.need(attempt["transmissions"] == 1 and len(attempt["transmission_ids"]) == 1
           and not attempt["resumed"] and not attempt["fallback"] and "retry" not in attempt["failure_reasons"], "reused_or_retried_attempt")
    canonical_uuid(attempt["transmission_ids"][0])
    parts = [part for part in call["input_parts"] if part["kind"] == "prompt"]
    p.need(len(parts) == 1 and parts[0]["sha256"] == fixed["prompt_sha256"]
           and parts[0]["bytes"] == fixed["prompt_bytes"], "receipt_prompt_binding")
    p.need(call["output_bound_mode"] == "request_limit" and call["output_bound_tokens"] == fixed["max_tokens"]
           and call["parameters"].get("max_tokens") == fixed["max_tokens"], "receipt_output_bound")
    p.digest(call["serialized_body_sha256"])
    p.digest(call["output_bound_evidence_sha256"])
    input_rate, output_rate = packet["input_usd_per_million"], packet["output_usd_per_million"]
    native_reservation = None if call["serialized_body_bytes"] is None else p.exact_cost(
        call["serialized_body_bytes"], call["output_bound_tokens"], input_rate, output_rate)
    for key in ("dispatch_monotonic_s", "deadline_monotonic_s", "deadline_s", "started_utc"):
        p.need(call[key] == attempt[key], "receipt_clock_binding")
    difference(call["http_started_monotonic_s"], attempt["dispatch_monotonic_s"])
    difference(attempt["cleanup_monotonic_s"], call["transport_ended_monotonic_s"])
    usage_state, independent_price = usage_arithmetic(call, input_rate, output_rate)
    price_comparison = compare(attempt["list_price_usd"], independent_price)
    reservation_comparison = compare(attempt["reservation_usd"], native_reservation)
    started, ended, cleaned = (utc_seconds(attempt[key]) for key in ("started_utc", "ended_utc", "cleanup_utc"))
    elapsed = difference(attempt["cleanup_monotonic_s"], attempt["dispatch_monotonic_s"])
    wall = difference(cleaned, started)
    run_wall = difference(ended, started)
    transport = difference(call["transport_ended_monotonic_s"], call["http_started_monotonic_s"])
    deadline = difference(attempt["deadline_monotonic_s"], attempt["dispatch_monotonic_s"])
    p.need(deadline in (None, Decimal(900)), "deadline_binding")
    deadline_met = "UNKNOWN" if elapsed is None or wall is None else "YES" if max(elapsed, wall) <= 900 else "NO"
    mismatch = (native_reservation is not None and native_reservation > p.money(fixed["cost_cap_usd"])) or any(
        value == "MISMATCH" for value in (price_comparison, reservation_comparison,
            compare(call["list_price_usd"], attempt["list_price_usd"]), compare(call["reservation_usd"], attempt["reservation_usd"])))
    failed = (attempt["terminal"] != "COMPLETED" or attempt["cleanup"] != "CONFIRMED" or bool(attempt["failure_reasons"])
              or deadline_met == "NO" or call["error_class"] is not None
              or call["stop_reason"] not in ("end_turn", "stop_sequence", "stop"))
    unknown = (usage_state != "KNOWN" or attempt["usage_state"] != "KNOWN" or attempt["cost_state"] != "KNOWN"
               or call["usage_state"] != "KNOWN" or call["cost_state"] != "KNOWN"
               or price_comparison == "UNKNOWN" or reservation_comparison == "UNKNOWN"
               or attempt["unknown_exposure_usd"] is None or deadline_met == "UNKNOWN")
    stop = "STOP_MISMATCH" if mismatch else "STOP_FAILURE" if failed else "STOP_UNKNOWN" if unknown else "WITHIN_EVIDENCE"
    return {"attempt_id": run_id, "session_id": session_id, "transmission_id": attempt["transmission_ids"][0],
            **claim, "terminal": attempt["terminal"], "cleanup": attempt["cleanup"],
            "transmissions": attempt["transmissions"], "cancelled": int("cancel" in attempt["failure_reasons"]),
            "usage_state": attempt["usage_state"], "cost_state": attempt["cost_state"],
            "independent_price_state": usage_state, "independent_list_price_usd": independent_price,
            "list_price_usd": attempt["list_price_usd"], "call_list_price_usd": call["list_price_usd"],
            "price_comparison": price_comparison, "call_price_comparison": compare(call["list_price_usd"], attempt["list_price_usd"]),
            "reservation_usd": attempt["reservation_usd"], "native_reservation_usd": native_reservation,
            "serialized_body_bytes": call["serialized_body_bytes"],
            "reservation_comparison": reservation_comparison, "call_reservation_comparison": compare(call["reservation_usd"], attempt["reservation_usd"]),
            "unknown_exposure_usd": attempt["unknown_exposure_usd"], "stop": stop,
            "actual_elapsed_s": elapsed, "wall_elapsed_s": wall, "run_wall_s": run_wall,
            "transport_elapsed_s": transport, "clock_delta_s": None if elapsed is None or wall is None else wall - elapsed,
            "deadline_met": deadline_met,
            **{key: call["usage"][key] for key in ("input_tokens", "output_tokens", "total_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}}


def summarize(table: list[dict]) -> dict:
    p.need(len(table) == p.CALLS, "incomplete_receipt_table")
    known = all(row["cost_state"] == "KNOWN" and row["list_price_usd"] is not None for row in table)
    exposure_known = known and all(row["unknown_exposure_usd"] is not None and row["stop"] == "WITHIN_EVIDENCE" for row in table)
    with localcontext() as context:
        context.prec = 100
        total = sum((row["list_price_usd"] for row in table), Decimal(0)) if known else None
        exposure = (sum((row["list_price_usd"] + row["unknown_exposure_usd"] for row in table), Decimal(0))
                    if exposure_known else None)
    caps = [row["stop"] for row in table]
    stop = p.budget(exposure, 0)
    if any(value != "WITHIN_EVIDENCE" for value in caps):
        stop = "STOP_EVIDENCE"
    return {"format": FORMAT, "status": "BLOCKED", "semantic_status": "NOT_MEASURED", "acceptance": "NOT_GRANTED",
            "profiles": p.CALLS, "pools": 3, "comparisons": 14, "requested": p.CALLS,
            "attempted": sum(row["transmissions"] > 0 for row in table),
            "completed": sum(row["terminal"] == "COMPLETED" for row in table),
            "failed": sum(row["terminal"] == "FAILED" for row in table),
            "not_measured": sum(row["terminal"] == "NOT_MEASURED" for row in table),
            "cancelled": sum(row["cancelled"] for row in table),
            "cleanup_uncertain": sum(row["cleanup"] == "UNCERTAIN" for row in table),
            "actual_price_state": "KNOWN" if known else "UNKNOWN", "actual_list_price_usd": total,
            "maximum_exposure_usd": exposure, "exposure_cap_usd": p.EXPOSURE_CAP, "stop": stop,
            "median_actual_elapsed_s": median([row["actual_elapsed_s"] for row in table]),
            "median_actual_list_price_usd": median([row["list_price_usd"] for row in table]),
            "maximum_actual_list_price_usd": max((row["list_price_usd"] for row in table), default=None) if known else None,
            "receipt_table": table}


def preflight(index: dict) -> list[dict]:
    """No external diagnostic is called until the entire 42-position pool is valid."""
    rows = positions(index)
    packet_root = p.absolute(Path(index["packet_root"]))
    root = p.root_fd(packet_root)
    os.close(root)
    checked, bindings, attempt_ids, receipt_paths, native_slots = [], set(), set(), set(), set()
    common = None
    for row in rows:
        p.fields(row["packet"], {"path", "sha256"}, "packet_descriptor")
        directory = p.absolute(Path(row["packet"]["path"]))
        p.need(directory == packet_root / f"{row['case_id']}-r{row['repetition']}", "packet_position")
        packet = p.verify_packet(directory, row["packet"]["sha256"])
        binding = packet["binding"]
        p.need(binding["root_id"] == index["root_id"] and binding["experiment_id"] == index["experiment_id"]
               and binding["case_id"] == row["case_id"] and binding["repetition"] == row["repetition"]
               and binding["binding_id"] not in bindings, "experiment_binding")
        bindings.add(binding["binding_id"])
        signature = tuple(packet["files"][name]["sha256"] for name in ("instructions.md", "schema.json", "route.json", "pricing.json"))
        if common is None:
            common = signature
        p.need(signature == common, "mixed_experiment_inputs")
        raw_path, raw_data = descriptor_file(row["raw"])
        brief_data = p.read_file(directory / "brief.md", private=True)
        schema_data = p.read_file(directory / "schema.json", private=True)
        validate_raw(raw_data, brief_data, schema_data)
        evidence = {}
        native = packet["single_call"]
        engine_root = p.absolute(Path(native["output_root"]))
        engine_fd = p.root_fd(engine_root)
        os.close(engine_fd)
        native_slot = (str(engine_root), native["slot"])
        p.need(native_slot not in native_slots, "duplicate_native_slot")
        native_slots.add(native_slot)
        p.need(raw_path == engine_root / f"{native['slot']}.raw", "raw_path_binding")
        for name in ("attempt", "call", "claim"):
            path, data = descriptor_file(row[name])
            expected = engine_root / (native["slot"] + (".claim" if name == "claim" else f".{name}.json"))
            p.need(path == expected and path not in receipt_paths, "duplicate_or_retargeted_receipt")
            receipt_paths.add(path)
            evidence[name] = data if name == "claim" else p.strict_json(data, decimals=True)
        table = audit_receipts(evidence, packet, raw_data, raw_path=raw_path)
        for identity in (table["attempt_id"], table["session_id"], table["transmission_id"]):
            p.need(identity not in attempt_ids, "duplicate_attempt_identity")
            attempt_ids.add(identity)
        # Fixed known directories only. Tests substitute a synthetic REPO; never existing answer fixtures.
        case_dir = p.REPO / p.KNOWN / row["case_id"]
        p.need(p.sha(p.read_file(case_dir / "brief.md")) == p.sha(brief_data), "case_brief_changed")
        checked.append({"row": row, "packet": packet, "directory": directory, "raw_path": raw_path,
                        "raw_sha256": p.sha(raw_data), "case_dir": case_dir, "table": table})
    return checked


def report(index: dict, root: Path) -> dict:
    checked = preflight(index)
    root = p.absolute(root)
    fd = p.root_fd(root)
    slot = p.identifier(index["experiment_id"]) + ".report"
    slot_fd = None
    manifests, profiles, table = {}, {}, []
    try:
        # No fallback or overwrite; a failed diagnostic leaves this report slot consumed.
        os.mkdir(slot, 0o700, dir_fd=fd)
        os.fsync(fd)
        slot_fd = os.open(slot, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.fchmod(slot_fd, 0o700)
        output = root / slot
        for item in checked:
            row = item["row"]
            position = p.CASES.index(row["case_id"]) + 1
            repetition = row["repetition"]
            prefix = f"p{position:02d}-r{repetition}"
            schema_path = item["directory"] / "schema.json"
            _, check_bytes = diagnostic("checker", "checker", ["--brief", str(item["directory"] / "brief.md"),
                                                                 "--schema", str(schema_path), str(item["raw_path"])])
            manifests[prefix + "-check.json"] = write_evidence(slot_fd, prefix + "-check.json", check_bytes)
            grade, grade_bytes = diagnostic("scorer", "profile", ["--case", str(item["case_dir"]), "--schema",
                                                                    str(schema_path), str(item["raw_path"])])
            p.need(grade.get("case_id") == row["case_id"], "diagnostic_case_mismatch")
            score_name = prefix + "-score.json"
            manifests[score_name] = write_evidence(slot_fd, score_name, grade_bytes)
            profiles[(row["case_id"], repetition)] = str(output / score_name)
            _, meaning_bytes = diagnostic("meaning", "meaning", ["--case", str(item["case_dir"]), str(item["raw_path"])])
            manifests[prefix + "-meaning.json"] = write_evidence(slot_fd, prefix + "-meaning.json", meaning_bytes)
            # Recheck original answer after all diagnostics: do not create a rewritten copy.
            p.need(p.sha(p.read_file(item["raw_path"], private=True)) == item["raw_sha256"], "raw_answer_changed")
            table.append({"position": position, "repetition": repetition,
                          **{key: value for key, value in item["table"].items()
                             if key not in ("attempt_id", "session_id", "transmission_id")}})
        for repetition in (1, 2, 3):
            _, data = diagnostic("scorer", "pool", ["--pool", *(profiles[(case, repetition)] for case in p.CASES)])
            name = f"pool-r{repetition}.json"
            manifests[name] = write_evidence(slot_fd, name, data)
        for position, case in enumerate(p.CASES, 1):
            items = [item for item in checked if item["row"]["case_id"] == case]
            _, data = diagnostic("scorer", "consistency", ["--case", str(items[0]["case_dir"]), "--schema",
                            str(items[0]["directory"] / "schema.json"), "--runs", *(str(x["raw_path"]) for x in items)])
            name = f"consistency-p{position:02d}.json"
            manifests[name] = write_evidence(slot_fd, name, data)
        # Recheck every immutable source hash after diagnostics, not just answers.
        for item in checked:
            p.verify_packet(item["directory"], item["row"]["packet"]["sha256"])
            for name in ("raw", "attempt", "call", "claim"):
                descriptor_file(item["row"][name])
        summary = summarize(table)
        manifests["SUMMARY.json"] = write_evidence(slot_fd, "SUMMARY.json", p.json_bytes(summary))
        manifests["SOURCE-INDEX.json"] = write_evidence(slot_fd, "SOURCE-INDEX.json", p.json_bytes(index))
        write_evidence(slot_fd, "MANIFEST.json", p.json_bytes({"format": FORMAT, "files": manifests}))
        return summary
    except OSError:
        raise p.Refused("report_persistence_refused") from None
    finally:
        if slot_fd is not None:
            os.close(slot_fd)
        os.close(fd)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        index = p.strict_json(p.read_file(args.index, private=True), decimals=True)
        summary = report(index, args.root)
    except (p.Refused, OSError, KeyError, TypeError, ArithmeticError, cpc.SchemaError):
        print('{"status":"REFUSED","semantic_status":"NOT_MEASURED"}')
        return 2
    print(p.json_bytes(summary).decode("utf-8"), end="")
    return 1  # Completed diagnostics, never semantic/Stage 1 acceptance.


if __name__ == "__main__":
    sys.exit(main())
