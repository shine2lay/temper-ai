"""Model-free candidate tests. Every brief/profile/route/price here is newly synthetic.

Never open the existing answer keys, plants or answer-bearing tests. Never build,
print or capture a provider message/request body. No engine, credentials or model.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import socket
import uuid
from collections.abc import MutableMapping
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "configs/architecture/bin"


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r = load(BIN / "context_profile_candidate_report.py")
p = r.p
SCHEMA = (REPO / p.STAGE / "contract.v2.schema.json").read_bytes()


def store(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def description(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": p.sha(data)}


def evidence(path):
    return {"path": str(path), **description(path)}


def profile(brief):
    # Generic archival toy, unrelated to any known case. Silence is explicit everywhere.
    fields = json.loads(SCHEMA)["$defs"]["unknown"]["properties"]["field"]["enum"]
    return {
        "contract": "context_profile/v2", "brief_sha256": p.sha(brief),
        "product": {"summary": "Catalogs manuscripts", "source": {"kind": "quote", "quote": "catalogs manuscripts"}},
        "maturity": {"stage": "unknown", "evidence": []}, "current_system": {"state": "unknown", "items": []},
        "external_systems": [], "workload": {"observed": [], "projected": [], "peaks": []},
        "performance": {"targets": []},
        "reliability": {"availability": "unknown", "data_loss_tolerance": "unknown", "recovery_time": "unknown"},
        "privacy": {"data_categories": [], "sensitivity": "unknown", "retention": [], "sharing": [], "jurisdictions_or_rules": []},
        "security": {"requirements": [], "threats": [], "compliance": []},
        "team": {"size": "unknown", "skills": [], "operating_capacity": []},
        "budget": {"build": "unknown", "run_monthly": "unknown"}, "constraints": [], "goals": [],
        "unknowns": [{"field": field, "question": "What is stated?", "why_it_matters": "It is not given in this toy.",
                      "decisions_affected": ["deployment choice"], "material": False} for field in fields],
        "assumptions": [],
    }


def intercept_environment_writes(monkeypatch, mapping_type, direct_api):
    """Intercept writes, retaining operation labels only; never read environment values."""
    attempts = []

    def replace(target, name, key_position):
        original = getattr(target, name)

        def guarded(*args, **kwargs):
            key = args[key_position] if len(args) > key_position else kwargs.get("key")
            # Pytest labels its phases with this one key. Forward, do not inspect, its value.
            if type(key) in (str, bytes) and key in ("PYTEST_CURRENT_TEST", b"PYTEST_CURRENT_TEST"):
                return original(*args, **kwargs)
            attempts.append(name)
            raise AssertionError("environment_write_forbidden")

        monkeypatch.setattr(target, name, guarded)

    for name in ("__setitem__", "__delitem__"):
        replace(mapping_type, name, 1)
    for name in ("putenv", "unsetenv"):
        replace(direct_api, name, 0)
    return attempts


def environment_source_violations(source):
    """A source convention, not a sandbox: only the write-interception type reference is allowed."""
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def guard_call(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "intercept_environment_writes" and len(node.args) == 3 and not node.keywords)

    def type_reference(node):
        parent = parents.get(node)
        outer = parents.get(parent)
        return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "os" and node.attr == "environ"
                and isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name)
                and parent.func.id == "type" and parent.args == [node] and not parent.keywords
                and guard_call(outer) and outer.args[1] is parent)

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(item.name.split(".")[0] in ("os", "posix", "nt")
                   and (item.name != "os" or item.asname is not None) for item in node.names):
                violations.append("environment_import_alias")
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in ("os", "posix", "nt"):
            violations.append("environment_from_import")
        elif isinstance(node, ast.Attribute) and node.attr in ("environ", "environb", "getenv", "getenvb"):
            if not type_reference(node):
                violations.append("environment_value_access")
        elif isinstance(node, ast.Name) and node.id == "os":
            parent = parents.get(node)
            if not (type_reference(parent) or (guard_call(parent) and parent.args[2] is node)):
                violations.append("environment_module_use")
    return violations


@pytest.fixture(autouse=True)
def no_network_or_environment_change(monkeypatch):
    calls = []

    def blocked(*args, **kwargs):
        calls.append(1)
        raise AssertionError("network_forbidden")

    # The type reference does not enumerate or retrieve any environment value.
    environment_writes = intercept_environment_writes(monkeypatch, type(os.environ), os)
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield calls
    assert len(calls) == 0
    assert environment_writes == []


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    repo = tmp_path / "synthetic-checkout"
    root = tmp_path / "packets"
    root.mkdir(mode=0o700)
    engine_root = tmp_path / "synthetic-engine-root"
    engine_root.mkdir(mode=0o700)
    schema_path = store(repo / p.STAGE / "contract.v2.schema.json", SCHEMA)
    prompt = store(repo / p.STAGE / "PROMPT-CANDIDATE.md", b"Synthetic instructions; no examples or provider framing.\n")
    brief = store(repo / p.KNOWN / p.CASES[0] / "brief.md", b"The archive catalogs manuscripts.\n")
    # Test-only evidence hashes are computed from explicit synthetic evidence bytes.
    route_data = {
        "format": "context-profile-candidate-route/v1", "status": "RESOLVED", "agent_type": "single_call",
        "provider": "anthropic", "model": "claude-opus-5-5", "route": "anthropic-oauth-named-token",
        "auth_mode": "oauth", "family": "A", "output_bound_mode": "request_limit",
        "max_tokens": 8192, "deadline_s": 900, "framing_bytes": None, "framing_evidence_sha256": None,
        "route_evidence_sha256": p.sha(b"synthetic route evidence"),
        "request_limit_evidence_sha256": p.sha(b"synthetic request limit evidence"),
        "request_limit_evidence": "https://example.invalid/request-limits",
    }
    route = store(tmp_path / "route.json", p.json_bytes(route_data))
    pricing = store(tmp_path / "pricing.json", p.json_bytes({"currency": "USD", "models": {
        "claude-opus-5-5": {"input_usd_per_million": 4, "output_usd_per_million": 20,
                              "request_limit_evidence": "https://example.invalid/request-limits"}}}))
    binding = {"format": "context-profile-candidate-binding/v1", "root": str(root), "root_id": "synthetic-root",
               "packet_slot": p.CASES[0] + "-r1", "case_id": p.CASES[0], "repetition": 1,
               "output_root": str(engine_root), "slot": "A1", "family": "A", "cost_cap_usd": "1",
               "source_sha256": p.sha(b"synthetic source evidence"),
               "config_sha256": p.sha(b"synthetic offline config evidence"),
               "packet_sha256": p.sha(b"synthetic admission packet evidence"),
               "experiment_id": "synthetic-experiment", "binding_id": "synthetic-binding-1",
               "brief": description(brief), "instructions": description(prompt), "schema": description(schema_path),
               "route": description(route), "pricing": description(pricing)}
    monkeypatch.setattr(p, "REPO", repo)
    monkeypatch.setattr(p, "PROMPT_SHA256", p.sha(prompt.read_bytes()))
    return {"brief": brief, "instructions": prompt, "schema": schema_path, "route_path": route,
            "pricing_path": pricing, "root": root, "binding": binding}


def test_prepare_write_once_hashes_and_reservation(sandbox):
    result = p.prepare(**sandbox)
    assert result["status"] == "PREPARED"
    assert result["reservation_lower_usd"] == p.exact_cost(result["text_utf8_bytes"], 8192, "4", "20")
    assert result["reservation_upper_usd"] is None
    assert result["framing_bytes"] is None
    assert result["pool_reservation_usd"] is None
    assert result["sizing_status"] == "NATIVE_CAP_DECIDES"
    directory = sandbox["root"] / sandbox["binding"]["packet_slot"]
    manifest = p.verify_packet(directory, result["manifest_sha256"])
    assert manifest["semantic_status"] == "NOT_MEASURED"
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in directory.iterdir())
    assert directory.stat().st_mode & 0o777 == 0o700
    retained = p.sha((directory / "manifest.json").read_bytes())
    with pytest.raises(p.Refused):
        p.prepare(**sandbox)
    assert retained == p.sha((directory / "manifest.json").read_bytes())


@pytest.mark.parametrize("fault", ["unlisted", "byte", "digest", "prompt", "route", "framing", "price", "root", "slot", "cap", "symlink"])
def test_preparation_negative_is_side_effect_free(sandbox, fault, monkeypatch):
    calls = []
    monkeypatch.setattr(r.subprocess, "run", lambda *a, **kw: calls.append(1))
    if fault == "unlisted":
        sandbox["brief"] = sandbox["brief"].parent / "other.md"
    elif fault == "byte":
        sandbox["binding"]["brief"]["bytes"] += 1
    elif fault == "digest":
        sandbox["binding"]["brief"]["sha256"] = p.sha(b"different synthetic bytes")
    elif fault == "prompt":
        store(sandbox["instructions"], b"Changed but not accepted synthetic instructions.\n")
        sandbox["binding"]["instructions"] = description(sandbox["instructions"])
    elif fault in ("route", "framing"):
        metadata = p.strict_json(sandbox["route_path"].read_bytes())
        metadata["status" if fault == "route" else "framing_bytes"] = "PENDING" if fault == "route" else 0
        store(sandbox["route_path"], p.json_bytes(metadata))
        sandbox["binding"]["route"] = description(sandbox["route_path"])
    elif fault == "price":
        prices = p.strict_json(sandbox["pricing_path"].read_bytes())
        prices["models"]["claude-opus-5-5"]["input_usd_per_million"] = "UNKNOWN"
        store(sandbox["pricing_path"], p.json_bytes(prices))
        sandbox["binding"]["pricing"] = description(sandbox["pricing_path"])
    elif fault == "root":
        sandbox["binding"]["root"] += "-other"
    elif fault == "slot":
        sandbox["binding"]["slot"] = "alternative-slot"
    elif fault == "cap":
        sandbox["binding"]["cost_cap_usd"] = "0.000001"
    else:
        target = sandbox["brief"].with_name("synthetic-source.md")
        sandbox["brief"].rename(target)
        sandbox["brief"].symlink_to(target)
    before = set(sandbox["root"].iterdir())
    with pytest.raises(p.Refused):
        p.prepare(**sandbox)
    assert before == set(sandbox["root"].iterdir())
    assert len(calls) == 0


def test_failed_persistence_preserves_consumed_slot(sandbox, monkeypatch):
    original = p.os.open

    def fail(name, *args, **kwargs):
        if name == "schema.json":
            raise OSError("synthetic write failure")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(p.os, "open", fail)
    with pytest.raises(p.Refused):
        p.prepare(**sandbox)
    directory = sandbox["root"] / sandbox["binding"]["packet_slot"]
    assert directory.is_dir()
    assert (directory / "instructions.md").is_file()
    assert not (directory / "manifest.json").exists()
    with pytest.raises(p.Refused):
        p.prepare(**sandbox)
    assert (directory / "instructions.md").is_file()


@pytest.mark.parametrize("mutate", ["file", "sums", "move"])
def test_packet_mutation_or_root_retarget_is_refused(sandbox, mutate):
    result = p.prepare(**sandbox)
    directory = sandbox["root"] / sandbox["binding"]["packet_slot"]
    if mutate == "file":
        store(directory / "brief.md", b"Changed synthetic brief.\n")
    elif mutate == "sums":
        store(directory / "SHA256SUMS", b"changed\n")
    else:
        other = sandbox["root"].parent / "other-root"
        other.mkdir(mode=0o700)
        directory.rename(other / directory.name)
        directory = other / directory.name
    with pytest.raises(p.Refused):
        p.verify_packet(directory, result["manifest_sha256"])


@pytest.mark.parametrize("raw", [b"```json\n{}\n```", b'{"contract":"a","contract":"b"}', b"{} trailing",
                                b"[]", b'{"contract":"context_profile/v2","x":NaN}',
                                b'{"contract":"context_profile/v2","x":Infinity}',
                                b'{"contract":"context_profile/v2","x":1e999}'])
def test_strict_raw_json_refusal_never_calls_scripts(raw, monkeypatch):
    calls = []
    monkeypatch.setattr(r, "diagnostic", lambda *a, **kw: calls.append(1))
    with pytest.raises(p.Refused):
        r.validate_raw(raw, b"The archive catalogs manuscripts.\n", SCHEMA)
    assert len(calls) == 0


def test_no_response_rewriting():
    brief = b"The archive catalogs manuscripts.\n"
    raw = json.dumps(profile(brief), indent=3).encode() + b"  \n"
    before = p.sha(raw)
    result = r.validate_raw(raw, brief, SCHEMA)
    assert result["contract"] == "context_profile/v2"
    assert p.sha(raw) == before


@pytest.mark.parametrize("fault", ["quote", "unknown", "rank", "id", "source", "wrapper"])
def test_structural_self_checks(fault):
    brief = b"The archive catalogs manuscripts. Please favor economy. Please favor reliability.\n"
    document = profile(brief)
    if fault == "quote":
        document["product"]["source"]["quote"] = "invented unsupported text"
    elif fault == "unknown":
        document["unknowns"] = []
    elif fault in ("rank", "id"):
        document["goals"] = [
            {"id": "G1", "criterion": "cost", "rank": 1, "note": "Favor economy",
             "source": {"kind": "quote", "quote": "Please favor economy"}},
            {"id": "G1" if fault == "id" else "G2", "criterion": "reliability", "rank": 1 if fault == "rank" else 2,
             "note": "Favor reliability", "source": {"kind": "quote", "quote": "Please favor reliability"}},
        ]
    elif fault == "source":
        document["product"]["source"]["kind"] = "unknown"
    else:
        document = {"profile": document}
    with pytest.raises(p.Refused):
        r.validate_raw(p.json_bytes(document), brief, SCHEMA)


def grade(kind):
    return {"grading_output": "context_profile_grade/v3", "kind": kind, "status": "BLOCKED",
            "semantic_status": "NOT_MEASURED", "score_pct": None, "semantic_score_pct": None,
            "meets_bars": False, "clean": False, "structural_anchor": {}}


def test_completed_one_is_not_cannot_run_two():
    for kind in ("profile", "pool", "consistency"):
        data = p.json_bytes(grade(kind))
        assert r.completed(kind, 1, data)["status"] == "BLOCKED"
        with pytest.raises(p.Refused):
            r.completed(kind, 2, data)
        with pytest.raises(p.Refused):
            r.completed(kind, 0, data)
    for code in (0, 1):
        data = p.json_bytes({"ok": code == 0, "errors": [], "counts": {}})
        assert type(r.completed("checker", code, data)["ok"]) is bool
    with pytest.raises(p.Refused):
        r.completed("checker", 2, p.json_bytes({"ok": False, "error": "cannot run"}))
    meaning = {"format": "context_profile_meaning/v0-layers12", "summary": {
        "entries": 2, "contradicted": 0, "needs_judgment": 2, "numeric_limit_groups": 0, "numeric_limit_deferred": 0}}
    assert r.completed("meaning", 1, p.json_bytes(meaning))["summary"]["needs_judgment"] == 2
    with pytest.raises(p.Refused):
        r.completed("meaning", 2, p.json_bytes(meaning))


def test_full_position_set_and_duplicate_refusal(monkeypatch):
    index = {"format": "context-profile-candidate-index/v1", "experiment_id": "synthetic-experiment",
             "root_id": "synthetic-root", "packet_root": "/unused", "runs": [
        {"case_id": case, "repetition": rep, "packet": {}, "raw": {}, "attempt": {}, "call": {}, "claim": {}}
        for case, rep in r.POSITIONS]}
    assert len(r.positions(index)) == 42
    calls = []
    monkeypatch.setattr(r, "diagnostic", lambda *a, **kw: calls.append(1))
    incomplete = copy.deepcopy(index)
    incomplete["runs"].pop()
    with pytest.raises(p.Refused):
        r.preflight(incomplete)
    duplicate = copy.deepcopy(index)
    duplicate["runs"][1] = duplicate["runs"][0]
    with pytest.raises(p.Refused):
        r.preflight(duplicate)
    assert len(calls) == 0


def test_decimal_arithmetic_exposure_and_unknown():
    reservation = p.exact_cost(26416, 8192, "4", "20")
    assert reservation == Decimal("0.269504")  # Prompt-only lower bound, not B6.
    assert reservation * 42 == Decimal("11.319168")
    assert p.exact_cost(1, 1, "4", "20") == Decimal("0.000024")
    assert p.budget(None, reservation) == "STOP_UNKNOWN"
    assert p.budget("11.8", reservation) == "STOP_CAP"
    assert p.budget("11.730496", reservation) == "WITHIN_CAP"
    assert p.budget("11.730497", reservation) == "STOP_CAP"
    assert p.budget(0, None) == "STOP_UNKNOWN"
    assert r.median([Decimal("1"), Decimal("2")]) == Decimal("1.5")
    assert r.median([Decimal("1"), None]) is None


def test_native_size_bounds_unknown_and_certain_refusal():
    text = "Synthetic manuscript: α, newline\n and quote \"".encode()
    result = p.sizing(text, None, "1", "4", "20")
    assert result["text_utf8_bytes"] == len(text)
    assert result["text_json_bound_bytes"] == len(json.dumps(text.decode(), ensure_ascii=True))
    assert result["framing_bytes"] is None and result["reservation_upper_usd"] is None
    assert result["reservation_lower_usd"] == (Decimal(len(text)) * 4 + Decimal(8192) * 20) / 1000000
    assert result["sizing_status"] == "NATIVE_CAP_DECIDES"
    with pytest.raises(p.Refused):
        p.sizing(text, None, "0.01", "4", "20")
    with pytest.raises(p.Refused):
        p.sizing(text, 0, "1", "4", "20")
    bounded = p.sizing(text, 512, "1", "4", "20")
    assert bounded["reservation_upper_usd"] == p.exact_cost(result["text_json_bound_bytes"] + 512, 8192, "4", "20")
    assert not any("input_token" in name for name in result)


def receipts(packet, raw, ordinal=0):
    fixed = packet["single_call"]
    run, session, transmission = [str(uuid.UUID(int=ordinal * 3 + n)) for n in (1, 2, 3)]
    reservation = p.exact_cost(45000, 8192, "4", "20")
    price = p.exact_cost(100, 50, "4", "20")
    attempt = {"schema": "context-t1-attempt/v1", **{key: fixed[key] for key in (
        "slot", "family", "experiment_id", "binding_id", "source_sha256", "config_sha256", "pricing_sha256", "packet_sha256")},
        "session_id": session, "run_id": run, "route": fixed["route"], "provider": packet["provider"],
        "model": packet["model"], "auth_mode": fixed["auth_mode"], "input_sha256": fixed["prompt_sha256"],
        "raw_sha256": p.sha(raw), "terminal": "COMPLETED", "transmissions": 1, "transmission_ids": [transmission],
        "usage_state": "KNOWN", "cost_state": "KNOWN", "list_price_usd": price, "reservation_usd": reservation,
        "unknown_exposure_usd": Decimal(0), "cleanup": "CONFIRMED", "started_utc": "2026-01-01T00:00:00Z",
        "ended_utc": "2026-01-01T00:00:02.5Z", "cleanup_utc": "2026-01-01T00:00:03Z",
        "dispatch_monotonic_s": Decimal(100), "deadline_monotonic_s": Decimal(1000),
        "cleanup_monotonic_s": Decimal(103), "deadline_s": 900, "resumed": False, "fallback": False, "failure_reasons": []}
    call = {"schema": "context-t1-call/v1", "slot": fixed["slot"], "run_id": run, "session_id": session,
        "workflow_run_id": "synthetic-workflow", "provider": packet["provider"], "model": packet["model"],
        "route": fixed["route"], "auth_mode": fixed["auth_mode"], "pricing_sha256": fixed["pricing_sha256"],
        "output_bound_mode": "request_limit", "raw_path": str(Path(fixed["output_root"]) / (fixed["slot"] + ".raw")),
        "raw_bytes": len(raw), "raw_sha256": p.sha(raw), "output_bound_tokens": 8192,
        "output_bound_evidence_sha256": p.sha(b"synthetic output bound evidence"),
        "serialized_body_sha256": p.sha(b"opaque synthetic body metadata; not a provider message"), "serialized_body_bytes": 45000,
        "input_parts": [{"kind": "prompt", "ordinal": 0, "sha256": fixed["prompt_sha256"], "bytes": fixed["prompt_bytes"]}],
        "parameters": {"max_tokens": 8192, "stream": True},
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        "stop_reason": "end_turn", "response_id": "msg_synthetic", "error_class": None, "http_status": 200,
        "http_started_monotonic_s": Decimal("100.5"), "http_started_utc": "2026-01-01T00:00:00.5Z",
        "transport_ended_monotonic_s": Decimal("102.5"), "transport_ended_utc": "2026-01-01T00:00:02.5Z",
        "latency_ms": 2000, "dispatch_monotonic_s": Decimal(100), "started_utc": "2026-01-01T00:00:00Z",
        "deadline_monotonic_s": Decimal(1000), "deadline_s": 900, "usage_state": "KNOWN", "cost_state": "KNOWN",
        "list_price_usd": price, "reservation_usd": reservation, "unknown_exposure_usd": Decimal(0)}
    # Claim internals are not invented: completeness must stay UNKNOWN without a schema.
    return {"attempt": attempt, "call": call, "claim": b'{"schema":"context-t1-claim/v1"}'}


@pytest.fixture
def prepared(sandbox):
    result = p.prepare(**sandbox)
    directory = sandbox["root"] / sandbox["binding"]["packet_slot"]
    return p.verify_packet(directory, result["manifest_sha256"])


def test_native_receipt_arithmetic_time_and_no_mutation(prepared):
    raw = b"synthetic answer evidence"
    data = receipts(prepared, raw)
    before = p.sha(p.json_bytes({k: v for k, v in data.items() if k != "claim"}))
    row = r.audit_receipts(data, prepared, raw)
    assert row["independent_list_price_usd"] == Decimal("0.0014")
    assert row["list_price_usd"] == Decimal("0.0014")
    assert row["price_comparison"] == "MATCH"
    assert row["actual_elapsed_s"] == Decimal(3) and row["transport_elapsed_s"] == Decimal(2)
    assert row["run_wall_s"] == Decimal("2.5") and row["clock_delta_s"] == 0
    assert row["claim_completeness"] == "UNKNOWN"
    assert before == p.sha(p.json_bytes({k: v for k, v in data.items() if k != "claim"}))


@pytest.mark.parametrize("case", ["missing_usage", "unpriced_cache", "unknown_clock", "mismatch", "cleanup"])
def test_unknown_mismatch_and_failed_cleanup_are_preserved(prepared, case):
    raw = b"synthetic answer evidence"
    data = receipts(prepared, raw)
    attempt, call = data["attempt"], data["call"]
    if case == "missing_usage":
        call["usage"]["input_tokens"] = call["usage"]["total_tokens"] = None
        call["usage"]["cache_read_input_tokens"] = call["usage"]["cache_creation_input_tokens"] = None
        call["usage_state"] = attempt["usage_state"] = "UNKNOWN"
    elif case == "unpriced_cache":
        call["usage"]["cache_creation_input_tokens"] = 10
    elif case == "unknown_clock":
        attempt["cleanup_monotonic_s"] = attempt["cleanup_utc"] = None
    elif case == "mismatch":
        call["list_price_usd"] = attempt["list_price_usd"] = Decimal("0.0015")
    else:
        attempt["terminal"] = "FAILED"
        attempt["cleanup"] = "UNCERTAIN"
        attempt["failure_reasons"] = ["cancel"]
    if case in ("missing_usage", "unpriced_cache"):
        attempt["cost_state"] = call["cost_state"] = "UNKNOWN"
        attempt["list_price_usd"] = call["list_price_usd"] = None
        attempt["unknown_exposure_usd"] = call["unknown_exposure_usd"] = attempt["reservation_usd"]
    row = r.audit_receipts(data, prepared, raw)
    if case in ("missing_usage", "unpriced_cache"):
        assert row["independent_list_price_usd"] is None and row["list_price_usd"] is None
        assert row["unknown_exposure_usd"] == attempt["reservation_usd"]
        assert row["input_tokens"] is None if case == "missing_usage" else row["cache_creation_input_tokens"] == 10
    elif case == "unknown_clock":
        assert row["actual_elapsed_s"] is None and row["wall_elapsed_s"] is None
    elif case == "mismatch":
        assert row["price_comparison"] == "MISMATCH" and row["list_price_usd"] == Decimal("0.0015")
        assert row["independent_list_price_usd"] == Decimal("0.0014")
    else:
        assert row["terminal"] == "FAILED" and row["cleanup"] == "UNCERTAIN" and row["cancelled"] == 1
    assert row["stop"] != "WITHIN_EVIDENCE"


def test_subsets_are_not_added_or_discounted(prepared):
    call = receipts(prepared, b"synthetic answer evidence")["call"]
    call["usage"]["cache_read_input_tokens"] = None
    state, price = r.usage_arithmetic(call, "4", "20")
    assert state == "UNKNOWN_CACHE" and price is None
    assert call["usage"]["cache_read_input_tokens"] is None
    call["provider"] = "openai"
    call["usage"]["input_tokens_details"] = {"cached_tokens": 99}
    call["usage"]["output_tokens_details"] = {"reasoning_tokens": 25}
    state, price = r.usage_arithmetic(call, "4", "20")
    assert state == "KNOWN" and price == Decimal("0.0014")
    call["usage"]["input_tokens_details"]["cached_tokens"] = 101
    with pytest.raises(p.Refused):
        r.usage_arithmetic(call, "4", "20")


@pytest.mark.parametrize("case", ["keyword", "conditional", "format", "extra", "retry"])
def test_native_schema_refusal_before_any_diagnostic(prepared, case, monkeypatch):
    calls = []
    monkeypatch.setattr(r, "diagnostic", lambda *a, **kw: calls.append(1))
    data = receipts(prepared, b"synthetic answer evidence")
    if case == "keyword":
        with pytest.raises(p.Refused):
            r.ReceiptValidator({"type": "object", "dependentRequired": {}})
    else:
        if case == "conditional":
            data["attempt"]["cost_state"] = "UNKNOWN"  # Price must then be null, not a number.
        elif case == "format":
            data["call"]["run_id"] = "not-a-uuid"
        elif case == "extra":
            data["call"]["usage"]["unpriced_extra"] = 3
        else:
            data["attempt"]["transmissions"] = 2
        with pytest.raises(p.Refused):
            r.audit_receipts(data, prepared, b"synthetic answer evidence")
    assert len(calls) == 0


def test_missing_final_attempt_cannot_turn_claim_into_zero(prepared):
    row = r.audit_receipts({"claim": b'{"schema":"context-t1-claim/v1"}'}, prepared, b"")
    assert row["terminal"] == "FAILED" and row["cost_state"] == "UNKNOWN"
    assert row["list_price_usd"] is None and row["unknown_exposure_usd"] is None
    assert row["stop"] == "STOP_UNKNOWN"


def synthetic_key(case_id, brief):
    scorer = load(BIN / "context_profile_score.py")
    document = profile(brief)
    return {"key": "context_profile_key/v2", "case_id": case_id, "tests": "Synthetic archival toy only",
            "category": scorer.CATEGORIES[0], "brief_sha256": p.sha(brief), "profile": document,
            "maturity": {"accepted": [{"stage": "unknown", "quotes": ["catalogs manuscripts"]}]},
            "sensitivity": {"accepted": ["unknown"]}, "facts": [], "constraints": [], "goals": [], "unknowns": [], "traps": [],
            "fields_unknown": [{"field": field, "not_material_reason": "Synthetic test intentionally leaves this open"}
                               for field in scorer.OPEN_FIELDS if scorer.is_open(document, field)]}


def test_real_unchanged_diagnostic_cli_interfaces(tmp_path):
    brief = b"The archive catalogs manuscripts.\n"
    case_dir = tmp_path / "synthetic-case"
    store(case_dir / "brief.md", brief)
    store(case_dir / "key.json", p.json_bytes(synthetic_key("synthetic-case", brief)))
    raw_paths = [store(tmp_path / f"synthetic-{n}.json", p.json_bytes(profile(brief))) for n in (1, 2, 3)]
    before = [p.sha(path.read_bytes()) for path in raw_paths]
    schema_path = REPO / p.STAGE / "contract.v2.schema.json"
    result, _ = r.diagnostic("checker", "checker", ["--brief", str(case_dir / "brief.md"), "--schema", str(schema_path), str(raw_paths[0])])
    assert result["ok"] is True
    result, data = r.diagnostic("scorer", "profile", ["--case", str(case_dir), "--schema", str(schema_path), str(raw_paths[0])])
    assert result["status"] == "BLOCKED"
    score_path = store(tmp_path / "score.json", data)
    result, _ = r.diagnostic("scorer", "pool", ["--pool", str(score_path)])
    assert result["semantic_status"] == "NOT_MEASURED"
    result, _ = r.diagnostic("scorer", "consistency", ["--case", str(case_dir), "--schema", str(schema_path), "--runs", *(str(path) for path in raw_paths)])
    assert result["kind"] == "consistency" and result["semantic_status"] == "NOT_MEASURED"
    result, _ = r.diagnostic("meaning", "meaning", ["--case", str(case_dir), str(raw_paths[0])])
    assert result["summary"]["entries"] > 0
    assert before == [p.sha(path.read_bytes()) for path in raw_paths]


@pytest.fixture
def full_index(sandbox):
    index = {"format": "context-profile-candidate-index/v1", "experiment_id": "synthetic-experiment",
             "root_id": "synthetic-root", "packet_root": str(sandbox["root"]), "runs": []}
    for ordinal, (case_id, repetition) in enumerate(r.POSITIONS):
        options = copy.deepcopy(sandbox)
        binding = options["binding"]
        brief = b"The archive catalogs manuscripts.\n"
        options["brief"] = store(p.REPO / p.KNOWN / case_id / "brief.md", brief)
        binding.update(case_id=case_id, repetition=repetition, packet_slot=f"{case_id}-r{repetition}",
                       slot=f"A{repetition}", binding_id=f"synthetic-binding-{ordinal}", brief=description(options["brief"]))
        engine_root = sandbox["root"].parent / ("engine-" + case_id)
        engine_root.mkdir(mode=0o700, exist_ok=True)
        binding["output_root"] = str(engine_root)
        result = p.prepare(**options)
        directory = sandbox["root"] / binding["packet_slot"]
        packet = p.verify_packet(directory, result["manifest_sha256"])
        raw = p.json_bytes(profile(brief))
        receipt = receipts(packet, raw, ordinal)
        paths = {"raw": store(engine_root / f"A{repetition}.raw", raw),
                 "claim": store(engine_root / f"A{repetition}.claim", receipt["claim"]),
                 "attempt": store(engine_root / f"A{repetition}.attempt.json", p.json_bytes(receipt["attempt"])),
                 "call": store(engine_root / f"A{repetition}.call.json", p.json_bytes(receipt["call"]))}
        index["runs"].append({"case_id": case_id, "repetition": repetition,
            "packet": {"path": str(directory), "sha256": result["manifest_sha256"]},
            **{name: evidence(path) for name, path in paths.items()}})
    return index


def test_complete_three_pools_fourteen_comparisons_numeric_summary(full_index, tmp_path, monkeypatch):
    calls = []

    def fixed_diagnostic(script, kind, arguments):
        calls.append((kind, arguments))
        if kind == "checker":
            result = {"ok": True, "errors": [], "counts": {}}
        elif kind == "meaning":
            result = {"format": "context_profile_meaning/v0-layers12", "summary": {
                "entries": 1, "contradicted": 0, "needs_judgment": 1, "numeric_limit_groups": 0, "numeric_limit_deferred": 0}}
        else:
            result = grade(kind)
            if kind == "profile":
                result["case_id"] = Path(arguments[1]).name
        return result, p.json_bytes(result)

    monkeypatch.setattr(r, "diagnostic", fixed_diagnostic)
    root = tmp_path / "reports"
    root.mkdir(mode=0o700)
    result = r.report(full_index, root)
    assert result["profiles"] == 42 and result["pools"] == 3 and result["comparisons"] == 14
    pools = [args for kind, args in calls if kind == "pool"]
    comparisons = [args for kind, args in calls if kind == "consistency"]
    assert len(pools) == 3 and all(len(args) == 15 for args in pools)
    assert len(comparisons) == 14 and all(len(args[args.index("--runs") + 1:]) == 3 for args in comparisons)
    assert len(calls) == 143
    assert result["semantic_status"] == "NOT_MEASURED" and result["status"] == "BLOCKED"
    assert result["actual_list_price_usd"] == Decimal("0.0588")
    assert len(result["receipt_table"]) == 42
    assert all("attempt_id" not in row and "session_id" not in row for row in result["receipt_table"])
    numeric = p.json_bytes(result)
    assert p.strict_json(numeric, decimals=True)["actual_list_price_usd"] == Decimal("0.0588")
    for row in result["receipt_table"]:
        row.update(list_price_usd=Decimal("0.3"), unknown_exposure_usd=Decimal(0), stop="WITHIN_EVIDENCE")
    assert r.summarize(result["receipt_table"])["stop"] == "STOP_CAP"
    result["receipt_table"][0]["list_price_usd"] = None
    result["receipt_table"][0]["cost_state"] = "UNKNOWN"
    assert r.summarize(result["receipt_table"])["actual_list_price_usd"] is None
    with pytest.raises(p.Refused):
        r.report(full_index, root)  # Immutable report slot, no alternative root or overwrite.


def test_helpers_have_no_provider_network_or_settings_imports():
    forbidden = {"socket", "requests", "httpx", "urllib", "anthropic", "litellm", "temper_ai", "keyring"}
    for name in ("context_profile_candidate_prepare.py", "context_profile_candidate_report.py"):
        tree = ast.parse((BIN / name).read_text())
        imports = {item.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for item in node.names}
        imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert len(imports & forbidden) == 0
        assert not any(isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv") for node in ast.walk(tree))
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and node.func.attr in ("unlink", "rmdir", "rmtree") for node in ast.walk(tree))


class SyntheticEnvironment(MutableMapping):
    """Only fabricated data; inherited mutators dispatch like Python's environment mapping."""

    def __init__(self, key="SYNTHETIC"):
        self.data = {key: "fabricated"}
        self.mutations = []
        self.reads = []

    def __getitem__(self, key):
        self.reads.append(key)
        return self.data[key]

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)

    def __setitem__(self, key, value):
        self.mutations.append("set")
        self.data[key] = value

    def __delitem__(self, key):
        self.mutations.append("delete")
        del self.data[key]

    def __ior__(self, other):
        self.update(other)
        return self


class SyntheticEnvironmentAPI:
    def __init__(self):
        self.calls = []

    def putenv(self, key, value):
        self.calls.append(("putenv", key, value))

    def unsetenv(self, key):
        self.calls.append(("unsetenv", key))


@pytest.mark.parametrize("key", ["SYNTHETIC", b"SYNTHETIC"])
@pytest.mark.parametrize("operation", ["set", "delete", "update", "setdefault", "pop", "popitem", "clear", "ior"])
def test_environment_guard_blocks_mapping_writes(monkeypatch, key, operation):
    mapping, api = SyntheticEnvironment(key), SyntheticEnvironmentAPI()
    attempts = intercept_environment_writes(monkeypatch, SyntheticEnvironment, api)
    with pytest.raises(AssertionError, match="^environment_write_forbidden$"):
        if operation == "set":
            mapping[key] = "fabricated replacement"
        elif operation == "delete":
            del mapping[key]
        elif operation == "update":
            mapping.update({key: "fabricated replacement"})
        elif operation == "setdefault":
            mapping.setdefault(key + key, "fabricated replacement")
        elif operation == "pop":
            mapping.pop(key)
        elif operation == "popitem":
            mapping.popitem()
        elif operation == "clear":
            mapping.clear()
        else:
            mapping |= {key: "fabricated replacement"}
    expected = "__delitem__" if operation in ("delete", "pop", "popitem", "clear") else "__setitem__"
    assert attempts == [expected]
    assert mapping.data == {key: "fabricated"}
    assert mapping.mutations == [] and api.calls == []


@pytest.mark.parametrize("key", ["SYNTHETIC", b"SYNTHETIC"])
@pytest.mark.parametrize("operation", ["putenv", "unsetenv"])
def test_environment_guard_blocks_direct_writes(monkeypatch, key, operation):
    mapping, api = SyntheticEnvironment(key), SyntheticEnvironmentAPI()
    attempts = intercept_environment_writes(monkeypatch, SyntheticEnvironment, api)
    with pytest.raises(AssertionError, match="^environment_write_forbidden$"):
        if operation == "putenv":
            api.putenv(key, "fabricated replacement")
        else:
            api.unsetenv(key)
    assert attempts == [operation]
    assert mapping.data == {key: "fabricated"}
    assert mapping.mutations == [] and api.calls == []


def test_environment_guard_allows_no_write(monkeypatch):
    mapping, api = SyntheticEnvironment(), SyntheticEnvironmentAPI()
    attempts = intercept_environment_writes(monkeypatch, SyntheticEnvironment, api)
    mapping.update({})
    assert mapping.setdefault("SYNTHETIC", "unused fabricated default") == "fabricated"
    assert dict(mapping) == {"SYNTHETIC": "fabricated"}
    assert attempts == [] and mapping.mutations == [] and api.calls == []


@pytest.mark.parametrize("key", ["PYTEST_CURRENT_TEST", b"PYTEST_CURRENT_TEST"])
def test_environment_guard_bookkeeping_is_key_only(monkeypatch, key):
    class OpaqueValue:
        def unreadable(self, *args, **kwargs):
            raise AssertionError("synthetic_value_was_inspected")

        __repr__ = __str__ = __eq__ = __iter__ = encode = unreadable

    value = OpaqueValue()
    mapping, api = SyntheticEnvironment(), SyntheticEnvironmentAPI()
    attempts = intercept_environment_writes(monkeypatch, SyntheticEnvironment, api)
    mapping[key] = value
    api.putenv(key, value)
    assert mapping.data[key] is value and api.calls[0][2] is value
    del mapping[key]
    api.unsetenv(key)
    assert mapping.reads == []
    assert mapping.mutations == ["set", "delete"]
    assert [call[0] for call in api.calls] == ["putenv", "unsetenv"]
    assert attempts == []


@pytest.mark.parametrize("key", ["PYTEST_OTHER_SYNTHETIC", b"PYTEST_OTHER_SYNTHETIC"])
def test_environment_guard_has_no_pytest_prefix_exemption(monkeypatch, key):
    mapping, api = SyntheticEnvironment(), SyntheticEnvironmentAPI()
    attempts = intercept_environment_writes(monkeypatch, SyntheticEnvironment, api)
    with pytest.raises(AssertionError, match="^environment_write_forbidden$"):
        mapping[key] = "fabricated"
    with pytest.raises(AssertionError, match="^environment_write_forbidden$"):
        api.putenv(key, "fabricated")
    assert attempts == ["__setitem__", "putenv"]
    assert mapping.mutations == [] and api.calls == []


def test_environment_guard_retains_swallowed_attempt(monkeypatch):
    mapping, api = SyntheticEnvironment(), SyntheticEnvironmentAPI()
    attempts = intercept_environment_writes(monkeypatch, SyntheticEnvironment, api)
    try:
        api.unsetenv("SYNTHETIC")
    except AssertionError:
        pass
    assert attempts == ["unsetenv"]  # The fixture can still refuse a swallowed write.
    assert mapping.mutations == [] and api.calls == []


@pytest.mark.parametrize("source", [
    "os.environ.items()", "os.environ.values()", "os.environ.keys()",
    "os.environ.get('SYNTHETIC')", "os.environ['SYNTHETIC']", "list(os.environ)", "dict(os.environ)",
    "json.dumps(dict(os.environ))",
    "hashlib.sha256(json.dumps(dict(os.environ)).encode()).hexdigest()",
    "os.getenv('SYNTHETIC')", "os.getenvb(b'SYNTHETIC')", "os.environb[b'SYNTHETIC']",
    "from os import environ as values\nvalues['SYNTHETIC']",
    "import os as other\nother.environ.items()", "getattr(os, 'environ')", "alias = os",
    "type(os.environ).get('SYNTHETIC')", "import posix\nposix.environ",
])
def test_environment_source_guard_rejects_value_access_and_hashing(source):
    # These snippets are parsed only: no environment read, import or bad callable is executed.
    assert environment_source_violations(source)


def test_environment_source_guard_clean_and_current_source():
    assert environment_source_violations("mapping = {'SYNTHETIC': 'fabricated'}\nlist(mapping.items())") == []
    assert environment_source_violations("intercept_environment_writes(monkeypatch, type(os.environ), os)") == []
    assert environment_source_violations(Path(__file__).read_text()) == []
