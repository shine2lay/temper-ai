"""M4 A only: real M1 bridge and shared representations, not durable composition."""

from __future__ import annotations

import ast
import builtins
import copy
import inspect
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict, fields, replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import sqlalchemy

from configs.architecture.bin import context_profile_clarification_caller as m1
from configs.architecture.bin import context_profile_clarified_check as clarified
from temper_ai.clarifications import caller_contracts as ports
from temper_ai.clarifications import contracts as m0
from temper_ai.clarifications import preparation_adapter as adapter
from temper_ai.clarifications import store as m3
from tests.test_clarifications.composition_scenarios import (
    BRIEF,
    BRIEF_SHA,
    COMPOSITION_ANSWER,
    COMPOSITION_UNKNOWN,
    SyntheticResponderPolicy,
    SyntheticTelegram,
    clarified_candidate,
    clarified_validator,
    composition_profile,
    inputs,
    receipt_event,
    row,
    sha,
)

Q = m0.question_id(BRIEF_SHA, COMPOSITION_UNKNOWN)
ENTRIES = ("prepare", "compose_supplement")


def committed_input():
    """Supplied synthetic revision, not a database write or commit claim."""
    candidate = composition_profile()
    record = m1.clarifications.create_record(candidate, BRIEF)
    return inputs(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        revision=7, record=json.dumps(record, ensure_ascii=False, indent=3) + "\n",
        ask=(Q,), candidate_brief_sha256=BRIEF_SHA,
        affected_decisions=("offline storage", " café 東京 \r\n"),
    )


# The first test combines both real public entries, exact answers and identities.
def test_combined_canonical_prepare_answer_reprepare_compose_and_fresh_outputs():
    first_in = inputs(composition_profile(), ask=(Q,))
    first = adapter.prepare(first_in)
    assert (first["expected_revision"], first["ask"]) == (0, [Q])
    assert row(first, Q)["state"] == "unanswered"
    event = receipt_event(first_in, first, Q, COMPOSITION_ANSWER, "601")
    record = m1.clarifications.append_event(json.loads(first["record_json"]), event)
    record_text = json.dumps(record, ensure_ascii=False, indent=3) + "\n"
    supplied = inputs(composition_profile(), revision=2, record=record_text)
    before = asdict(supplied)
    shown, composed = adapter.prepare(supplied), adapter.compose_supplement(supplied)
    answered = row(shown, Q)
    assert (answered["state"], answered["answer"]) == ("answered", COMPOSITION_ANSWER)
    assert answered["active_event_ids"] == answered["history_event_ids"] == [event["event_id"]]
    assert Q not in shown["unresolved_question_ids"]
    assert shown["ask"] == [] and json.loads(shown["record_json"]) == record
    assert composed["original_text"] == BRIEF and composed["original_sha256"] == BRIEF_SHA
    assert composed["record_json_sha256"] == sha(record_text)
    expected = m1.clarifications.compose_supplement(record, BRIEF)
    assert composed["source_mapping"] == expected["source_mapping"]
    assert composed["supplement"] == expected["supplement"]
    assert json.loads(composed["supplement"])["answers"][0]["answer"] == COMPOSITION_ANSWER
    assert composed["source_mapping"]["entries"][0]["event_ids"] == [event["event_id"]]
    assert composed["consumption_id"] == m0.consumption_id(
        supplied.stream.stream_id, 2, composed["supplement_sha256"],
    )
    assert len({composed[key] for key in ("original_sha256", "record_sha256", "supplement_sha256")}) == 3
    assert shown["meaning_status"] == composed["meaning_status"] == "NOT_EVALUATED"
    baseline = copy.deepcopy((shown, composed))
    answered["active"][0]["answer"] = "caller edited its display"
    composed["source_mapping"]["entries"][0]["event_ids"].append("e-caller-edit")
    assert asdict(supplied) == before
    assert (adapter.prepare(supplied), adapter.compose_supplement(supplied)) == baseline


@pytest.mark.parametrize("entry", ENTRIES)
def test_every_field_reaches_real_public_m1_unchanged(monkeypatch, entry):
    supplied = committed_input()
    before = asdict(supplied)
    seen = []
    real = getattr(m1, entry)

    def observe(local):
        seen.append(local)
        return real(local)

    monkeypatch.setattr(m1, entry, observe)
    result = getattr(adapter, entry)(supplied)
    assert len(seen) == 1
    local = seen[0]
    assert type(local) is m1.contracts.CallerInput and type(local) is not m0.CallerInput
    assert type(local.stream) is m1.contracts.StreamKey
    assert type(local.transport) is m1.contracts.TransportNamespace
    assert asdict(local) == before == asdict(supplied)
    assert {field.name for field in fields(local)} == {field.name for field in fields(supplied)}
    assert local.stream.stream_id == supplied.stream.stream_id
    assert result["candidate_ref"] == supplied.candidate_ref
    assert result["candidate_sha256"] == sha(supplied.candidate_json)
    assert result["meaning_status"] == "NOT_EVALUATED"


def assert_type_refusal(operation, value):
    try:
        operation(value)
    except m1.CallerRefusal as error:
        assert error.guard == "caller.type", "exact canonical type refusal"
        return
    raise AssertionError("exact canonical type refusal")


@pytest.mark.parametrize("entry", ENTRIES)
def test_exact_types_remain_distinct_no_lookalikes_or_subclasses(entry):
    canonical = committed_input()
    assert_type_refusal(getattr(m1, entry), canonical)

    class DerivedInput(m0.CallerInput):
        pass

    derived = DerivedInput(**{field.name: getattr(canonical, field.name) for field in fields(canonical)})
    local = inputs(composition_profile(), contracts=m1.contracts)
    values = (local, derived, SimpleNamespace(**asdict(canonical)), asdict(canonical), None)
    for value in values:
        assert_type_refusal(getattr(adapter, entry), value)
    assert getattr(adapter, entry)(canonical)["meaning_status"] == "NOT_EVALUATED"


def malformed_profile(case):
    candidate = composition_profile()
    cases = ("missing", "unknown_list", "constraint_list", "goal_object") if case == "combined" else (case,)
    for variant in cases:
        if variant == "missing":
            del candidate["budget"]
        elif variant == "unknown_list":
            candidate["unknowns"][0]["field"] = []
        elif variant == "constraint_list":
            candidate["constraints"] = [{"id": [], "text": "Use the clinic tool",
                                         "source": {"kind": "assumption", "why": "Synthetic assumption"}}]
        elif variant == "goal_object":
            candidate["goals"] = [{"id": {}, "criterion": "cost", "rank": 1, "note": "Keep costs low",
                                  "source": {"kind": "assumption", "why": "Synthetic assumption"}}]
    return candidate


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("case", ("missing", "unknown_list", "constraint_list", "goal_object", "combined"))
def test_v02_full_checker_first_real_diagnostics_no_record_work(monkeypatch, entry, case):
    candidate = malformed_profile(case)
    supplied = replace(committed_input(), candidate_json=json.dumps(candidate),
                       candidate_sha256=sha(json.dumps(candidate)))
    expected = m1.VALIDATOR.errors(candidate)
    assert expected  # Independent actual schema evidence, before installing the spies.
    calls = []
    real_check, real_schema = m1.checker.check, m1.VALIDATOR.errors

    def check(*args, **kwargs):
        calls.append("complete")
        return real_check(*args, **kwargs)

    def schema(value, node=None, path="$"):
        if node is None:
            calls.append("schema")
        return real_schema(value, node, path)

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid candidate reached record or state work")

    monkeypatch.setattr(m1.checker, "check", check)
    monkeypatch.setattr(m1.VALIDATOR, "errors", schema)
    monkeypatch.setattr(m1.contracts.CallerInput, "prior_record", forbidden)
    for name in ("create_record", "project_states", "compose_supplement"):
        monkeypatch.setattr(m1.clarifications, name, forbidden)
    monkeypatch.setattr(m3.ClarificationStore, "load", forbidden)
    monkeypatch.setattr(m3.ClarificationStore, "merge_candidate", forbidden)
    with pytest.raises(m1.CallerRefusal) as caught:
        getattr(adapter, entry)(supplied)
    assert caught.value.guard == "candidate.complete"
    assert caught.value.meaning_status == "NOT_EVALUATED"
    assert {item["path"]: item["detail"] for item in caught.value.errors} == {
        path: detail for _keyword, path, detail in expected
    }
    assert calls == (["complete", "schema"] if case == "missing" else ["complete", "schema", "schema"])


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("error_type,invalid", [(TypeError, False), (ValueError, False),
                                               (ValueError, True), (RuntimeError, True)])
def test_unexpected_checker_errors_propagate_unchanged(monkeypatch, entry, error_type, invalid):
    candidate = malformed_profile("unknown_list") if invalid else composition_profile()
    supplied = inputs(candidate)
    failure = error_type("synthetic checker failure")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(m1.checker, "check", fail)
    with pytest.raises(error_type) as caught:
        getattr(adapter, entry)(supplied)
    assert caught.value is failure


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("code", tuple(m0.RefusalCode))
def test_only_local_contract_refusal_is_translated_with_same_code_guard_location(monkeypatch, entry, code):
    supplied = committed_input()
    failure = m1.contracts.ContractRefusal(m1.contracts.RefusalCode(code.value), "synthetic.guard", "synthetic.field")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(m1, entry, fail)
    with pytest.raises(m0.ContractRefusal) as caught:
        getattr(adapter, entry)(supplied)
    assert type(caught.value) is m0.ContractRefusal
    assert (caught.value.code, caught.value.guard, caught.value.where) == (code, failure.guard, failure.where)
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("origin", ("StreamKey", "TransportNamespace", "CallerInput"))
def test_local_constructor_refusals_are_also_canonical(monkeypatch, entry, origin):
    supplied = committed_input()
    failure = m1.contracts.ContractRefusal(m1.contracts.RefusalCode.HASH_MISMATCH, "synthetic.binding", origin)

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(m1.contracts, origin, fail)
    with pytest.raises(m0.ContractRefusal) as caught:
        getattr(adapter, entry)(supplied)
    assert (caught.value.code, caught.value.guard, caught.value.where) == (
        m0.RefusalCode.HASH_MISMATCH, "synthetic.binding", origin,
    )


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("failure", [m1.CallerRefusal("ask.current", "synthetic"),
                                     m1.clarifications.ClarificationError("synthetic history"),
                                     m0.ContractRefusal(m0.RefusalCode.MISSING_RECORD, "synthetic.record"),
                                     TypeError("synthetic type"), RuntimeError("synthetic internal")])
def test_other_refusals_and_internal_failures_keep_identity(monkeypatch, entry, failure):
    supplied = committed_input()

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(m1, entry, fail)
    with pytest.raises(type(failure)) as caught:
        getattr(adapter, entry)(supplied)
    assert caught.value is failure


@pytest.mark.parametrize("changes,code,guard", [
    ({"original_sha256": "0" * 64}, m0.RefusalCode.HASH_MISMATCH, "caller.original_hash"),
    ({"candidate_sha256": "0" * 64}, m0.RefusalCode.HASH_MISMATCH, "caller.candidate_hash"),
    ({"prior_record_sha256": "0" * 64}, m0.RefusalCode.HASH_MISMATCH, "caller.record_hash"),
    ({"prior_record_json": None}, m0.RefusalCode.MISSING_RECORD, "caller.record_missing"),
    ({"source_authority_ref": None}, m0.RefusalCode.MISSING_AUTHORITY, "caller.authority_missing"),
])
def test_v03_canonical_construction_refuses_bindings_before_bridge(changes, code, guard):
    with pytest.raises(m0.ContractRefusal) as caught:
        replace(committed_input(), **changes)
    assert (caught.value.code, caught.value.guard) == (code, guard)


def test_namespace_is_preserved_not_an_authority_grant():
    original = committed_input()
    other = replace(original, stream=m0.StreamKey("project:another-synthetic", BRIEF_SHA))
    assert adapter.prepare(other)["stream_id"] == other.stream.stream_id != original.stream.stream_id
    assert adapter.compose_supplement(other)["consumption_id"] != adapter.compose_supplement(original)["consumption_id"]


@pytest.mark.parametrize("entry", ENTRIES)
def test_public_operations_do_not_open_sources_or_touch_services(monkeypatch, entry):
    supplied = committed_input()

    def forbidden(*args, **kwargs):
        raise AssertionError("adapter operation attempted I/O or reloaded a module")

    with monkeypatch.context() as patches:
        for target, name in ((builtins, "open"), (io, "open"), (os, "getenv"), (socket, "socket"),
                             (sqlite3, "connect"), (sqlalchemy, "create_engine"), (subprocess, "Popen"),
                             (m1, "_load_contracts_by_path")):
            patches.setattr(target, name, forbidden)
        result = getattr(adapter, entry)(supplied)
    assert result["meaning_status"] == "NOT_EVALUATED"


def snapshots(module=ports):
    supplied = committed_input()
    display, composed = adapter.prepare(supplied), adapter.compose_supplement(supplied)
    result = m3.RecordResult(supplied.stream.stream_id, 7, supplied.prior_record_json,
                            composed["record_sha256"], False)
    stored = m3.StoredStream(supplied.stream, supplied.source_authority_ref, 7, result.record_json,
                             result.record_sha256, (), (), 7)
    supplement = m3.Supplement(
        stored.stream.stream_id, 7, composed["consumption_id"], composed["supplement_sha256"],
        composed["record_sha256"], BRIEF, composed["supplement"], composed["source_mapping"], False,
    )
    report = {"references_ok": False, "errors": [{"reason": "synthetic"}], "counts": {},
              "unresolved_questions": [], "meaning_status": "NOT_EVALUATED"}
    prepared = module.PreparedClarification(result, display)
    recovered = module.RecoveredClarification(stored, display, supplement)
    checked = module.CheckedClarification(
        supplied.stream, 7, composed["record_sha256"], BRIEF_SHA, "candidate:synthetic/checked",
        "{}", sha("{}"), BRIEF, composed["supplement"], composed["source_mapping"],
        composed["consumption_id"], report,
    )
    return prepared, recovered, checked, display, supplement, report


def test_shared_results_use_actual_m3_types_and_no_mutable_aliases():
    prepared, recovered, checked, display, supplement, report = snapshots()
    assert type(prepared.record) is m3.RecordResult and type(recovered.stored) is m3.StoredStream
    assert type(recovered.supplement) is m3.Supplement
    for result in (prepared, recovered, checked):
        assert result.meaning_status == "NOT_EVALUATED"
        with pytest.raises(FrozenInstanceError):
            result.meaning_status = "PASS"
    display["questions"][0]["decisions_affected"].append("edit")
    supplement.source_mapping["entries"].append({"edited": True})
    report["errors"][0]["reason"] = "edit"
    assert prepared.display["questions"][0]["decisions_affected"] != display["questions"][0]["decisions_affected"]
    assert recovered.display == prepared.display
    assert recovered.supplement.source_mapping["entries"] == []
    assert checked.source_mapping["entries"] == [] and checked.report["errors"][0]["reason"] == "synthetic"
    prepared.display["questions"].clear()
    recovered.supplement.source_mapping["entries"].append({"own edit": True})
    assert recovered.display["questions"] and checked.source_mapping["entries"] == []


def test_presentation_request_and_synchronous_ports_match_real_operations():
    supplied = committed_input()
    presentation = supplied.presentation(Q, m0.metadata_sha256(COMPOSITION_UNKNOWN), 1)
    request = ports.PresentationRequest(presentation, " exact café 東京\r\n")
    assert request.presentation is presentation and request.text == " exact café 東京\r\n"
    with pytest.raises(FrozenInstanceError):
        request.text = "changed"
    for name in ("merge_candidate", "save_presentation", "record_copy", "append_receipt", "load",
                 "supplement", "mark_consumed"):
        assert inspect.signature(getattr(ports.CoordinatorStore, name)) == inspect.signature(
            getattr(m3.ClarificationStore, name),
        )
    assert not inspect.iscoroutinefunction(ports.QuestionTransport.present)


def test_shared_f0_f1_constructors_use_real_schema_and_exact_event_bindings():
    candidate = composition_profile()
    supplied = inputs(candidate, ask=(Q,))
    display = adapter.prepare(supplied)
    event = receipt_event(supplied, display, Q, COMPOSITION_ANSWER, "601")
    record = m1.clarifications.append_event(json.loads(display["record_json"]), event)
    composed = adapter.compose_supplement(inputs(candidate, revision=2, record=record))
    profile = clarified_candidate(
        candidate, source_mapping=composed["source_mapping"], question_id=Q,
        question=COMPOSITION_UNKNOWN["question"], answer=COMPOSITION_ANSWER, event_ids=[event["event_id"]],
    )
    report = clarified.check_clarified_profile(profile, BRIEF, record, clarified_validator())
    assert report["references_ok"] is True and report["meaning_status"] == "NOT_EVALUATED"
    assert candidate == composition_profile()
    assert profile["constraints"][0]["source"]["answer"] == COMPOSITION_ANSWER
    policy = SyntheticResponderPolicy({("policy:synthetic", "-1001", "5001")})
    assert policy.decide(policy_ref="policy:synthetic", chat_id="-1001", sender_id="5001") == "authorised"
    assert policy.decide(policy_ref="policy:synthetic", chat_id="-1001", sender_id="5002") == "denied"
    assert SyntheticTelegram().get_me()["id"] == 7001


def mutated_module(monkeypatch, module, old, new):
    """One in-memory source mutation, importing the existing components, never M0 again."""
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert source.count(old) == 1
    name = module.__name__ + "_bite"
    result = ModuleType(name)
    monkeypatch.setitem(sys.modules, name, result)
    exec(compile(source.replace(old, new), module.__file__, "exec"), result.__dict__)
    return result


def test_exact_type_guard_has_assertion_specific_bites(monkeypatch):
    class DerivedInput(m0.CallerInput):
        pass

    supplied = committed_input()
    derived = DerivedInput(**{field.name: getattr(supplied, field.name) for field in fields(supplied)})
    lookalike = SimpleNamespace(**{field.name: getattr(supplied, field.name) for field in fields(supplied)})
    for replacement, bad in (("False", lookalike), ("not isinstance(caller, CallerInput)", derived)):
        mutant = mutated_module(monkeypatch, adapter, "type(caller) is not CallerInput", replacement)
        assert_type_refusal(adapter.prepare, bad)
        with pytest.raises(AssertionError, match="exact canonical type refusal"):
            assert_type_refusal(mutant.prepare, bad)


def test_local_translation_and_narrow_exception_scope_have_specific_bites(monkeypatch):
    supplied = committed_input()
    local = m1.contracts.ContractRefusal(m1.contracts.RefusalCode.MISSING_RECORD, "synthetic.record", "synthetic")

    def fail_local(*args, **kwargs):
        raise local

    monkeypatch.setattr(m1, "prepare", fail_local)
    untranslated = mutated_module(
        monkeypatch, adapter, "except local.ContractRefusal as refusal:", "except ContractRefusal as refusal:",
    )

    def assert_canonical(module):
        try:
            module.prepare(supplied)
        except (m0.ContractRefusal, m1.contracts.ContractRefusal) as error:
            assert type(error) is m0.ContractRefusal, "path-local refusal escaped canonical boundary"
            assert (error.code, error.guard, error.where) == (
                m0.RefusalCode.MISSING_RECORD, "synthetic.record", "synthetic",
            )
            return
        raise AssertionError("expected contract refusal")

    assert_canonical(adapter)
    with pytest.raises(AssertionError, match="path-local refusal escaped canonical boundary"):
        assert_canonical(untranslated)

    canonical = m0.ContractRefusal(m0.RefusalCode.MISSING_RECORD, "synthetic.record")

    def fail_canonical(*args, **kwargs):
        raise canonical

    monkeypatch.setattr(m1, "prepare", fail_canonical)
    widened = mutated_module(
        monkeypatch, adapter, "except local.ContractRefusal as refusal:", "except Exception as refusal:",
    )

    def assert_unchanged(module):
        with pytest.raises(m0.ContractRefusal) as caught:
            module.prepare(supplied)
        assert caught.value is canonical, "unrelated refusal identity changed"

    assert_unchanged(adapter)
    with pytest.raises(AssertionError, match="unrelated refusal identity changed"):
        assert_unchanged(widened)


@pytest.mark.parametrize("field_name", ("display", "supplement", "source_mapping", "report"))
def test_returned_container_copy_has_assertion_specific_bites(monkeypatch, field_name):
    # display occurs in two classes: mutate each separately, never count a setup failure.
    for class_name in ({"display": ("PreparedClarification", "RecoveredClarification"),
                        "supplement": ("RecoveredClarification",),
                        "source_mapping": ("CheckedClarification",), "report": ("CheckedClarification",)}[field_name]):
        source = Path(ports.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        old = ast.get_source_segment(source, node)
        new = old.replace(f"deepcopy(self.{field_name})", f"self.{field_name}")
        assert new != old
        mutant = mutated_module(monkeypatch, ports, old, new)
        for module, expected in ((ports, False), (mutant, True)):
            prepared, recovered, checked, display, supplement, report = snapshots(module)
            result = {"PreparedClarification": prepared, "RecoveredClarification": recovered,
                      "CheckedClarification": checked}[class_name]
            original = {"display": display, "supplement": supplement,
                        "source_mapping": supplement.source_mapping, "report": report}[field_name]
            assert (getattr(result, field_name) is original) is expected
            if expected:
                with pytest.raises(AssertionError, match="returned container aliases its input"):
                    assert getattr(result, field_name) is not original, "returned container aliases its input"
