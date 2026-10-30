"""M1 requirements preparation (Temper #205): synthetic data only, no model, no store.

The combined happy path runs first, then the refusals and edge cases, then one bite
per guard: each bite disables exactly one guard in an in-memory copy of the module
(never a file) and shows the unsafe outcome that guard prevents.
"""

from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import importlib.util
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from configs.architecture.bin import context_profile_clarification_caller as caller

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "configs/architecture/bin/context_profile_clarification_caller.py"
CONTRACTS = ROOT / "temper_ai/clarifications/contracts.py"
c = caller.clarifications
k = caller.contracts

BRIEF = "Synthetic brief: a small booking tool for one clinic.\nKeep exact text: café, 東京.\r\n"
BRIEF_SHA = hashlib.sha256(BRIEF.encode("utf-8")).hexdigest()
# Explicit independent list: every field an unknown may name, except current_system.items.
BASE_FIELDS = (
    "maturity.stage", "current_system.state", "external_systems",
    "workload.observed", "workload.projected", "workload.peaks", "performance.targets",
    "reliability.availability", "reliability.data_loss_tolerance", "reliability.recovery_time",
    "privacy.data_categories", "privacy.sensitivity", "privacy.retention", "privacy.sharing",
    "privacy.jurisdictions_or_rules", "security.requirements", "security.threats",
    "security.compliance", "team.size", "team.skills", "team.operating_capacity",
    "budget.build", "budget.run_monthly", "constraints", "goals",
)
OFFLINE = {
    "question": "Must the booking tool work offline?", "why_it_matters": "It changes storage and sync.",
    "decisions_affected": ["client storage", "sync design"], "material": True, "field": "constraints",
}
REGION = {
    "question": "Which country's privacy rules apply?", "why_it_matters": "It changes where data may live.",
    "decisions_affected": ["hosting region"], "material": True, "field": "privacy.jurisdictions_or_rules",
}
USERS = {
    "question": "How many staff will book at once?", "why_it_matters": "It sizes the server.",
    "decisions_affected": ["server size"], "material": False, "field": "workload.projected",
}
PROBES = (OFFLINE, REGION, USERS)
EXACT = "Yes, offline first.\r\n  Keep café 東京 bookings local."


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def qid(unknown: dict) -> str:
    return k.question_id(BRIEF_SHA, unknown)


def base_unknown(field: str) -> dict:
    return {
        "question": f"What is the {field} for this synthetic tool?", "why_it_matters": f"It changes the {field} design.",
        "decisions_affected": [f"{field} plan"], "material": False, "field": field,
    }


def profile(*probes: dict, reverse: bool = False, quote: str = "a small booking tool for one clinic") -> dict:
    """A complete synthetic v2 candidate: everything unknown, each field named."""
    unknowns = [base_unknown(field) for field in BASE_FIELDS] + [copy.deepcopy(probe) for probe in probes]
    if reverse:
        unknowns.reverse()
    return {
        "contract": "context_profile/v2", "brief_sha256": BRIEF_SHA,
        "product": {"summary": "Synthetic booking tool", "source": {"kind": "quote", "quote": quote}},
        "maturity": {"stage": "unknown", "evidence": []}, "current_system": {"state": "unknown", "items": []},
        "external_systems": [], "workload": {"observed": [], "projected": [], "peaks": []},
        "performance": {"targets": []},
        "reliability": {"availability": "unknown", "data_loss_tolerance": "unknown", "recovery_time": "unknown"},
        "privacy": {"data_categories": [], "sensitivity": "unknown", "retention": [], "sharing": [],
                    "jurisdictions_or_rules": []},
        "security": {"requirements": [], "threats": [], "compliance": []},
        "team": {"size": "unknown", "skills": [], "operating_capacity": []},
        "budget": {"build": "unknown", "run_monthly": "unknown"},
        "constraints": [], "goals": [], "assumptions": [], "unknowns": unknowns,
    }


def inputs(candidate, *, revision=0, record=None, ask=(), contracts=k, **changes):
    """A CallerInput (M0's contract) for the synthetic stream; text inputs stay exact."""
    text = candidate if isinstance(candidate, str) else json.dumps(candidate, ensure_ascii=False)
    record_json = record if record is None or isinstance(record, str) else json.dumps(record, ensure_ascii=False)
    fields = {
        "stream": contracts.StreamKey("project:synthetic-clinic", BRIEF_SHA),
        "original_text": BRIEF, "original_sha256": BRIEF_SHA,
        "candidate_json": text, "candidate_sha256": sha(text), "candidate_ref": "candidate:synthetic/1",
        "candidate_brief_sha256": None, "prior_revision": revision, "prior_record_json": record_json,
        "prior_record_sha256": None if record_json is None else sha(record_json),
        "question_ids": tuple(ask), "source_authority_ref": "authority:synthetic/clinic",
        "transport": contracts.TransportNamespace("telegram", "7001"), "chat_id": "-1001",
        "responder_policy_ref": "responder-policy:synthetic/owner-only",
    }
    fields.update(changes)
    return contracts.CallerInput(**fields)


def receipt(event_id: str) -> dict:
    return {"kind": "human_response", "ref": f"clarification-receipt:{sha(event_id)}"}


def human(question_id, answer, event_id, *, disposition="answered", actor="telegram-user:5001", supersedes=(),
          reason=None) -> dict:
    event = {
        "event_id": event_id, "question_id": question_id, "kind": "answer", "answer": answer,
        "disposition": disposition, "supersedes": list(supersedes), "actor": {"kind": "human", "ref": actor},
        "source": receipt(event_id),
    }
    if reason is not None:
        event["reason"] = reason
    return event


def reopen(question_id, event_id, *, actor="telegram-user:5001") -> dict:
    return {
        "event_id": event_id, "question_id": question_id, "kind": "reopen", "reason": "The clinic changed its plans.",
        "actor": {"kind": "human", "ref": actor}, "source": receipt(event_id),
    }


def model(question_id, answer, event_id, **changes) -> dict:
    event = {
        "event_id": event_id, "question_id": question_id, "kind": "answer", "answer": answer,
        "disposition": "answered", "supersedes": [], "actor": {"kind": "model", "ref": "model:synthetic-suggester"},
        "source": {"kind": "model_output", "ref": "run:synthetic/1"},
    }
    event.update(changes)
    return event


def record_with(*events, candidate=None) -> dict:
    """A foundation record built without M1, then the events appended in order."""
    record = c.create_record(candidate or profile(*PROBES), BRIEF)
    for event in events:
        record = c.append_event(record, event)
    return record


def receipt_event(caller_input, prepared, question_id, text, message_id, *, disposition="answered") -> dict:
    """An accepted M0 receipt's #308 event, as M2's provider-pull edge would build it."""
    metadata = row(prepared, question_id)["metadata_sha256"]
    presentation = caller_input.presentation(question_id, metadata, 1)
    copy_id = str(int(message_id) + 100)
    action = k.ActionReceipt(
        ingress="provider_pull",
        action=k.ActionIdentity(caller_input.transport, caller_input.chat_id, "message", message_id),
        update_id=int(message_id) + 1000, sender_id="5001", sender_is_bot=False, forwarded=False,
        text=text, text_sha256=sha(text),
        binding=k.PresentationBinding(caller_input.stream.stream_id, question_id, presentation.presentation_id, 1,
                                      copy_id),
        responder=k.ResponderDecision(caller_input.responder_policy_ref, "5001", "authorised", "responder_policy"),
        intent="answer", disposition=disposition,
    )
    result = k.validate_receipt(
        action, presentation=presentation, copies={copy_id}, current_generation=1, question_ids={question_id},
    )
    assert result.status == "accepted"
    return result.event()


def row(prepared: dict, question_id: str) -> dict:
    return next(item for item in prepared["questions"] if item["question_id"] == question_id)


def pointer(document, path: str):
    node = document
    for part in path.split("/")[1:]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def refused(guard: str, call, *args) -> caller.CallerRefusal:
    with pytest.raises(caller.CallerRefusal) as info:
        call(*args)
    assert info.value.guard == guard
    assert isinstance(info.value, c.ClarificationError)
    return info.value


Q_OFF, Q_REGION, Q_USERS = (qid(probe) for probe in PROBES)


# --- combined happy path ------------------------------------------------------


def test_combined_happy_path_prepare_answer_reprepare_compose():
    first_in = inputs(profile(*PROBES), ask=(Q_OFF, Q_REGION, Q_USERS))
    first = caller.prepare(first_in)
    assert first["format"] == caller.FORMAT and first["meaning_status"] == "NOT_EVALUATED"
    assert first["structural_check"] == {"ok": True, "counts": {"items": 1, "quoted": 1, "assumed": 0}}
    assert (first["expected_revision"], first["prior_record_sha256"]) == (0, None)
    assert first["stream_id"] == first_in.stream.stream_id and first["original_sha256"] == BRIEF_SHA
    assert json.loads(first["record_json"]) == c.create_record(profile(*PROBES), BRIEF)
    assert first["record_json_sha256"] == sha(first["record_json"])
    assert len(first["questions"]) == 28 and {item["change"] for item in first["questions"]} == {"new"}
    assert first["unresolved_question_ids"] == [item["question_id"] for item in first["questions"]]
    assert first["ask"] == [Q_OFF, Q_REGION, Q_USERS]
    offline = row(first, Q_OFF)
    assert {key: offline[key] for key in OFFLINE} == OFFLINE
    assert offline["metadata_sha256"] == k.metadata_sha256(OFFLINE)
    assert (offline["state"], offline["resolved"], offline["answer"], offline["active"]) == ("unanswered", False, None, [])

    # The store (M3, not built here) commits revision 1; a person and a model respond.
    record = json.loads(first["record_json"])
    record = c.append_event(record, receipt_event(first_in, first, Q_OFF, EXACT, "42"))
    record = c.append_event(record, receipt_event(first_in, first, Q_REGION, "Not decided yet.", "43",
                                                  disposition="deferred"))
    record = c.append_event(record, model(Q_USERS, "About five staff at once.", "e-model-1"))

    # Revision 2: a re-evaluated candidate lists the same unknowns in another order.
    second_in = inputs(profile(*PROBES, reverse=True), revision=2, record=record, ask=(Q_REGION, Q_USERS))
    second = caller.prepare(second_in)
    assert json.loads(second["record_json"]) == record  # same IDs, nothing new, history kept
    assert second["expected_revision"] == 2 and second["prior_record_sha256"] == second_in.prior_record_sha256
    assert {item["change"] for item in second["questions"]} == {"repeated"}
    offline = row(second, Q_OFF)
    assert (offline["state"], offline["resolved"], offline["answer"]) == ("answered", True, EXACT)
    assert offline["active"][0]["actor"] == {"kind": "human", "ref": "telegram-user:5001"}
    assert offline["active"][0]["source"]["ref"].startswith("clarification-receipt:")
    assert offline["active_event_ids"] == offline["history_event_ids"] == [offline["active"][0]["event_id"]]
    region = row(second, Q_REGION)
    assert (region["state"], region["resolved"], region["answer"]) == ("deferred", False, None)
    assert [(e["disposition"], e["answer"]) for e in region["active"]] == [("deferred", "Not decided yet.")]
    users = row(second, Q_USERS)
    assert (users["state"], users["active"], users["active_event_ids"]) == ("unanswered", [], [])
    assert [(e["event_id"], e["actor"]["kind"]) for e in users["model_suggestions"]] == [("e-model-1", "model")]
    assert Q_OFF not in second["unresolved_question_ids"]
    assert {Q_REGION, Q_USERS} <= set(second["unresolved_question_ids"])
    assert second["ask"] == [Q_REGION, Q_USERS]

    composed = caller.compose_supplement(inputs(profile(*PROBES, reverse=True), revision=2, record=record))
    assert composed["original_text"] == BRIEF and sha(composed["original_text"]) == composed["original_sha256"] == BRIEF_SHA
    supplement = json.loads(composed["supplement"])
    assert [answer["question"]["question_id"] for answer in supplement["answers"]] == [Q_OFF]
    assert supplement["answers"][0]["answer"] == EXACT
    assert [a["actor"]["kind"] for a in supplement["answers"][0]["attributions"]] == ["human"]
    mapping = composed["source_mapping"]
    assert mapping == c.compose_supplement(record, BRIEF)["source_mapping"]  # the foundation's exact mapping
    (entry,) = mapping["entries"]
    assert pointer(supplement, entry["question_pointer"]) == OFFLINE["question"]
    assert pointer(supplement, entry["answer_pointer"]) == EXACT
    assert [a["event_id"] for a in pointer(supplement, entry["attributions_pointer"])] == entry["event_ids"]
    assert entry["event_ids"] == offline["active_event_ids"]
    identities = (composed["original_sha256"], composed["record_sha256"], composed["supplement_sha256"])
    assert len(set(identities)) == 3
    assert (supplement["original_brief_sha256"], supplement["record_sha256"]) == identities[:2]
    assert composed["supplement_sha256"] == sha(composed["supplement"])
    assert mapping["source_id"] == "clarifications-sha256:" + composed["supplement_sha256"]
    assert composed["consumption_id"] == k.consumption_id(second_in.stream.stream_id, 2, composed["supplement_sha256"])
    assert composed["record_json_sha256"] == second_in.prior_record_sha256 and composed["revision"] == 2
    states = {state["question_id"]: state["state"] for state in composed["unresolved_questions"]}
    assert (states[Q_REGION], states[Q_USERS]) == ("deferred", "unanswered") and Q_OFF not in states
    assert BRIEF not in composed["supplement"] and composed["meaning_status"] == "NOT_EVALUATED"
    assert "PASS" not in json.dumps([first, second, composed], ensure_ascii=False)


# --- the complete checker comes first ----------------------------------------


def _envelope(p):
    return {"contract": p["contract"], "brief_sha256": p["brief_sha256"], "unknowns": p["unknowns"]}


def _without(section):
    def change(p):
        del p[section]
        return p
    return change


def _setting(path, value):
    def change(p):
        node = p
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
        return p
    return change


def _unnamed(field):
    def change(p):
        p["unknowns"] = [u for u in p["unknowns"] if u.get("field") != field]
        return p
    return change


BROKEN = {
    "envelope_only": (_envelope, "missing_section"),
    "missing_section": (_without("budget"), "missing_section"),
    "bad_enum": (_setting(("maturity", "stage"), "galactic"), "bad_enum"),
    "schema": (_setting(("unknowns", 0, "decisions_affected"), []), "schema"),
    "anchor_not_in_original": (_setting(("product", "source", "quote"), "a large booking tool for many clinics"),
                               "quote_not_in_brief"),
    "unnamed_unknown_field": (_unnamed("team.size"), "unknown_field_unnamed"),
    # T15's fabricated old-v2 quote: an answer cited as if the original said it (no concatenation).
    "answer_cited_as_original_quote": (_setting(("product", "source", "quote"), "Keep café 東京 bookings local"),
                                       "quote_not_in_brief"),
    "quote_padded_to_length": (_setting(("product", "source", "quote"), "yes"), "quote_too_short"),
}


UNHASHABLE_SHAPES = {
    "unknown_list": (_setting(("unknowns", 0, "field"), []), "$.unknowns[0].field", "bad_enum"),
    "unknown_object": (_setting(("unknowns", 1, "field"), {}), "$.unknowns[1].field", "bad_enum"),
    "constraint_list": (_setting(("constraints",), [
        {"id": [], "text": "Use the clinic tool",
         "source": {"kind": "assumption", "why": "Synthetic assumption"}},
    ]), "$.constraints[0].id", "schema"),
    "goal_object": (_setting(("goals",), [
        {"id": {}, "criterion": "cost", "rank": 1, "note": "Keep costs low",
         "source": {"kind": "assumption", "why": "Synthetic assumption"}},
    ]), "$.goals[0].id", "schema"),
}


def _unhashable_profile(*cases):
    candidate = profile(*PROBES)
    for case in cases:
        change, _path, _reason = UNHASHABLE_SHAPES[case]
        candidate = change(candidate)
    return candidate


@pytest.mark.parametrize("entry", ["prepare", "compose_supplement"])
@pytest.mark.parametrize("case", ["combined", *UNHASHABLE_SHAPES, "mixed_diagnostics"])
def test_schema_invalid_checker_crash_is_a_diagnostic_refusal_before_record_work(monkeypatch, case, entry):
    cases = tuple(UNHASHABLE_SHAPES) if case in ("combined", "mixed_diagnostics") else (case,)
    candidate = _unhashable_profile(*cases)
    expected_reasons = {UNHASHABLE_SHAPES[name][1]: UNHASHABLE_SHAPES[name][2] for name in cases}
    if case == "mixed_diagnostics":
        del candidate["budget"]
        del candidate["team"]["size"]
        expected_reasons.update({"$": "missing_section", "$.team": "schema"})
    # Actual schema diagnostics, not a fabricated checker result. M0 accepts these
    # finite JSON shapes; the real checker then reaches its unsafe set/map operations.
    expected_details = {path: detail for _keyword, path, detail in caller.VALIDATOR.errors(candidate)}
    assert set(expected_details) == set(expected_reasons)
    bound = inputs(candidate, revision=1, record=record_with())
    calls = []
    real_check, real_schema = caller.checker.check, caller.VALIDATOR.errors

    def check(*args, **kwargs):
        calls.append("complete_check")
        return real_check(*args, **kwargs)

    def schema(value, node=None, path="$"):
        if node is None:
            calls.append("schema_errors")
        return real_schema(value, node, path)

    def no_record_work(*args, **kwargs):
        raise AssertionError("malformed candidate reached prior-record work")

    monkeypatch.setattr(caller.checker, "check", check)
    monkeypatch.setattr(caller.VALIDATOR, "errors", schema)
    monkeypatch.setattr(k.CallerInput, "prior_record", no_record_work)
    monkeypatch.setattr(c, "create_record", no_record_work)
    monkeypatch.setattr(c, "project_states", no_record_work)
    error = refused("candidate.complete", getattr(caller, entry), bound)
    assert {item["path"]: item["reason"] for item in error.errors} == expected_reasons
    assert {item["path"]: item["detail"] for item in error.errors} == expected_details
    assert bound.candidate_ref in str(error) and error.meaning_status == "NOT_EVALUATED"
    # One full check (including its schema pass), then recovery's real schema pass.
    assert calls == ["complete_check", "schema_errors", "schema_errors"]


@pytest.mark.parametrize("entry", ["prepare", "compose_supplement"])
@pytest.mark.parametrize("schema_invalid,error_type", [(False, TypeError), (True, ValueError), (True, RuntimeError)])
def test_unexplained_checker_errors_are_not_disguised_as_candidate_refusals(monkeypatch, entry,
                                                                          schema_invalid, error_type):
    candidate = _unhashable_profile("unknown_list") if schema_invalid else profile(*PROBES)
    assert bool(caller.VALIDATOR.errors(candidate)) is schema_invalid
    bound = inputs(candidate, revision=1, record=record_with())
    failure = error_type("synthetic internal checker failure")

    def broken_check(*args, **kwargs):
        raise failure

    def no_record_work(*args, **kwargs):
        raise AssertionError("internal failure reached prior-record work")

    monkeypatch.setattr(caller.checker, "check", broken_check)
    monkeypatch.setattr(k.CallerInput, "prior_record", no_record_work)
    with pytest.raises(error_type) as caught:
        getattr(caller, entry)(bound)
    assert caught.value is failure


@pytest.mark.parametrize("entry", ["prepare", "compose_supplement"])
@pytest.mark.parametrize("case", sorted(BROKEN))
def test_incomplete_or_mismatched_candidate_is_refused_with_diagnostics(case, entry):
    change, reason = BROKEN[case]
    candidate = change(profile(*PROBES))
    error = refused("candidate.complete", getattr(caller, entry), inputs(candidate, revision=1, record=record_with()))
    assert reason in {item["reason"] for item in error.errors}
    assert "candidate:synthetic/1" in str(error)  # the diagnostic names the refused source
    assert error.meaning_status == "NOT_EVALUATED"


def test_foundation_envelope_check_is_not_a_replacement_for_the_complete_checker():
    envelope = _envelope(profile(OFFLINE))
    assert [q["question_id"] for q in c.derive_questions(envelope, BRIEF) if q["question_id"] == Q_OFF] == [Q_OFF]
    error = refused("candidate.complete", caller.prepare, inputs(envelope, ask=(Q_OFF,)))
    assert {item["reason"] for item in error.errors} == {"missing_section"}


def test_deep_candidate_is_a_checker_refusal_not_a_crash():
    deep = []
    node = deep
    for _ in range(800):
        node.append([])
        node = node[0]
    candidate = _setting(("unknowns", 0, "decisions_affected"), deep)(profile())
    error = refused("candidate.complete", caller.prepare, inputs(candidate))
    assert {item["reason"] for item in error.errors} == {"schema"}


def test_checker_runs_before_any_record_work(monkeypatch):
    broken_record = record_with(human(Q_OFF, "Yes.", "e-1"))
    broken_record["events"][0]["question_id"] = "q-" + "0" * 64  # names a question the record lacks
    calls = []

    def spy(profile_, original, *, previous=None):
        calls.append(previous)
        return create_record(profile_, original, previous=previous)

    create_record = c.create_record
    monkeypatch.setattr(c, "create_record", spy)
    bad = inputs(_envelope(profile(*PROBES)), revision=4, record=broken_record)
    refused("candidate.complete", caller.prepare, bad)
    refused("candidate.complete", caller.compose_supplement, bad)
    assert calls == []
    complete = inputs(profile(*PROBES), revision=4, record=broken_record)  # M0 accepts it
    with pytest.raises(c.ClarificationError, match="event names missing question"):
        caller.prepare(complete)
    assert calls == [broken_record]  # the checker passed, then the foundation refused the record
    good = record_with(human(Q_OFF, "Yes.", "e-1"))
    caller.prepare(inputs(profile(*PROBES), revision=4, record=good))
    assert calls[-1] == good  # create_record(previous=<the exact prior record>)


def _second_contracts_load():
    spec = importlib.util.spec_from_file_location("another_contracts_load", CONTRACTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("entry", ["prepare", "compose_supplement"])
def test_only_this_modules_caller_input_is_accepted(entry):
    foreign = inputs(profile(*PROBES), revision=1, record=record_with(), contracts=_second_contracts_load())
    fields = {name: getattr(foreign, name) for name in foreign.__dataclass_fields__}
    for value in (foreign, SimpleNamespace(**fields), fields, None):
        refused("caller.type", getattr(caller, entry), value)


# --- prior record: M0's binding refusals, then the foundation's history checks ---


UNBOUND = json.dumps({key: value for key, value in profile(*PROBES).items() if key != "brief_sha256"},
                     ensure_ascii=False)
M0_REFUSALS = {
    "wrong_original_hash": ({"original_sha256": "0" * 64}, "hash_mismatch"),
    "unbound_candidate": ({"candidate_json": UNBOUND}, "missing_binding"),
    "missing_prior_record": ({"prior_revision": 3, "prior_record_json": None, "prior_record_sha256": None},
                             "missing_record"),
    "altered_record_hash": ({"prior_record_sha256": "1" * 64}, "hash_mismatch"),
    "truncated_record_text": ("truncate", "malformed"),
    "fresh_history_at_a_later_revision": ({"prior_revision": 0}, "malformed"),
}


@pytest.mark.parametrize("case", sorted(M0_REFUSALS))
def test_m0_refuses_bad_bindings_before_m1_can_run(case):
    changes, code = M0_REFUSALS[case]
    record_json = json.dumps(record_with(human(Q_OFF, "Yes.", "e-1")), ensure_ascii=False)
    if changes == "truncate":
        changes = {"prior_record_json": record_json[:-40], "prior_record_sha256": sha(record_json[:-40])}
    if "candidate_json" in changes:
        changes["candidate_sha256"] = sha(changes["candidate_json"])
    with pytest.raises(k.ContractRefusal) as info:
        inputs(profile(*PROBES), revision=2, record=record_json, **changes)
    assert info.value.code == code


def _truncated_correction():
    record = record_with(human(Q_OFF, "Yes.", "e-1"),
                         human(Q_OFF, "Yes, offline.", "e-2", supersedes=["e-1"], reason="More exact."))
    record["events"] = record["events"][1:]
    return record


def _orphan_event():
    record = record_with(human(Q_OFF, "Yes.", "e-1"))
    record["questions"] = [q for q in record["questions"] if q["question_id"] != Q_OFF]
    return record


def _changed_replay():
    record = record_with(human(Q_OFF, "Yes.", "e-1"))
    record["events"].append(human(Q_OFF, "No.", "e-1"))
    return record


def _cross_actor_correction():
    record = record_with(human(Q_OFF, "Yes.", "e-1"))
    record["events"].append(human(Q_OFF, "No.", "e-2", actor="telegram-user:5002", supersedes=["e-1"], reason="Other."))
    return record


def _model_revision():
    record = record_with(model(Q_OFF, "Probably.", "e-model-1"))
    record["events"].append(model(Q_OFF, "Surely.", "e-model-2", supersedes=["e-model-1"], reason="Sure."))
    return record


def _model_labelled_human_source():
    record = record_with()
    record["events"].append(model(Q_OFF, "Yes.", "e-model-1", source=receipt("e-model-1")))
    return record


def _altered_question():
    record = record_with()
    question = next(q for q in record["questions"] if q["question_id"] == Q_OFF)
    question["question"] = "Must the booking tool work offline, really?"
    return record


def _deep_question():
    record = record_with()
    deep = []
    node = deep
    for _ in range(600):
        node.append([])
        node = node[0]
    next(q for q in record["questions"] if q["question_id"] == Q_OFF)["decisions_affected"] = [deep]
    return record


INVALID_HISTORY = {
    "truncated_history": (_truncated_correction, "supersession must name an earlier event"),
    "event_without_its_question": (_orphan_event, "event names missing question"),
    "changed_content_under_one_id": (_changed_replay, "event ID reused with changed content"),
    "cross_actor_correction": (_cross_actor_correction, "supersession must name the same actor's answer"),
    "model_revision": (_model_revision, "model output cannot revise or reopen"),
    "model_with_human_source": (_model_labelled_human_source, "actor/source kind mismatch"),
    "question_metadata_altered_in_place": (_altered_question, "question ID binding mismatch"),
    "deep_record": (_deep_question, "invalid text"),
}


@pytest.mark.parametrize("entry", ["prepare", "compose_supplement"])
@pytest.mark.parametrize("case", sorted(INVALID_HISTORY))
def test_invalid_prior_history_is_refused_never_replaced(case, entry):
    build, message = INVALID_HISTORY[case]
    later = inputs(profile(*PROBES), revision=5, record=build())  # M0's binding checks pass
    with pytest.raises(c.ClarificationError) as info:
        getattr(caller, entry)(later)
    assert str(info.value) == message and not isinstance(info.value, caller.CallerRefusal)  # the foundation's own


# --- question identity --------------------------------------------------------


def _reordered_keys(unknown):
    return dict(reversed(list(unknown.items())))


def test_exact_repeat_and_reorder_keep_ids_history_and_are_not_asked_again():
    record = record_with(human(Q_OFF, EXACT, "e-1"))
    candidate = profile(*(_reordered_keys(p) for p in PROBES), reverse=True)
    prepared = caller.prepare(inputs(candidate, revision=2, record=record))
    assert json.loads(prepared["record_json"]) == record
    offline = row(prepared, Q_OFF)
    assert (offline["change"], offline["state"], offline["answer"], offline["history_event_ids"]) == (
        "repeated", "answered", EXACT, ["e-1"])
    refused("ask.unresolved", caller.prepare, inputs(candidate, revision=2, record=record, ask=(Q_OFF,)))


def _changed(**changes):
    unknown = {**copy.deepcopy(OFFLINE), **changes}
    return {key: value for key, value in unknown.items() if value is not None}


METADATA_CHANGES = {
    "question_text": _changed(question="Must the booking tool work offline?\u00a0"),
    "why_it_matters": _changed(why_it_matters="It changes storage, sync and cost."),
    "decision_order": _changed(decisions_affected=["sync design", "client storage"]),
    "decision_added": _changed(decisions_affected=["client storage", "sync design", "cost"]),
    "material_flipped": _changed(material=False),
    "field_removed": _changed(field=None),
    "field_changed": _changed(field="goals"),
}


@pytest.mark.parametrize("case", sorted(METADATA_CHANGES))
def test_any_metadata_change_is_a_new_question_and_the_old_keeps_its_history(case):
    changed = METADATA_CHANGES[case]
    new_id = qid(changed)
    assert new_id != Q_OFF
    record = record_with(human(Q_OFF, EXACT, "e-1"))
    candidate = profile(changed, REGION, USERS)
    prepared = caller.prepare(inputs(candidate, revision=2, record=record, ask=(new_id,)))
    old, new = row(prepared, Q_OFF), row(prepared, new_id)
    assert (old["change"], old["state"], old["answer"], old["history_event_ids"]) == ("absent", "answered", EXACT, ["e-1"])
    assert (new["change"], new["state"], new["answer"], new["history_event_ids"]) == ("new", "unanswered", None, [])
    assert {key: new[key] for key in changed} == changed and ("field" in new) == ("field" in changed)
    assert json.loads(prepared["record_json"])["events"] == record["events"]  # no answer migrated
    assert new_id in prepared["unresolved_question_ids"] and prepared["ask"] == [new_id]
    refused("ask.current", caller.prepare, inputs(candidate, revision=2, record=record, ask=(Q_OFF,)))


def test_dropped_then_reintroduced_question_keeps_its_id_and_history():
    record = record_with(human(Q_OFF, EXACT, "e-1"))
    dropped = caller.prepare(inputs(profile(REGION, USERS), revision=2, record=record))
    assert (row(dropped, Q_OFF)["change"], row(dropped, Q_OFF)["state"]) == ("absent", "answered")
    kept = json.loads(dropped["record_json"])
    back = caller.prepare(inputs(profile(USERS, OFFLINE, REGION), revision=3, record=kept))
    assert (row(back, Q_OFF)["change"], row(back, Q_OFF)["answer"]) == ("repeated", EXACT)
    assert row(back, Q_OFF)["history_event_ids"] == ["e-1"] and json.loads(back["record_json"]) == record


def test_unanswered_old_questions_stay_visible_but_only_current_ones_are_asked():
    record = record_with(human(Q_REGION, "Ask the lawyer first.", "e-1", disposition="deferred"))
    prepared = caller.prepare(inputs(profile(USERS), revision=2, record=record, ask=(Q_USERS,)))
    for question_id, state in ((Q_OFF, "unanswered"), (Q_REGION, "deferred")):
        old = row(prepared, question_id)
        assert (old["change"], old["state"], old["resolved"]) == ("absent", state, False)
        assert question_id in prepared["unresolved_question_ids"]
        refused("ask.current", caller.prepare, inputs(profile(USERS), revision=2, record=record, ask=(question_id,)))


def test_duplicate_unknowns_in_one_candidate_are_one_question():
    prepared = caller.prepare(inputs(profile(OFFLINE, OFFLINE, REGION, USERS)))
    assert [item["question_id"] for item in prepared["questions"]].count(Q_OFF) == 1
    assert len(prepared["questions"]) == 28


def test_new_questions_join_the_prior_record_without_touching_old_ones():
    record = record_with(human(Q_OFF, EXACT, "e-1"), candidate=profile(OFFLINE))
    prepared = caller.prepare(inputs(profile(*PROBES), revision=2, record=record, ask=(Q_REGION, Q_USERS)))
    assert {row(prepared, q)["change"] for q in (Q_REGION, Q_USERS)} == {"new"}
    assert row(prepared, Q_OFF)["change"] == "repeated"
    assert json.loads(prepared["record_json"]) == c.create_record(profile(*PROBES), BRIEF, previous=record)


# --- unresolved display -------------------------------------------------------


def test_every_unresolved_state_stays_visible_and_askable_answered_is_shown_not_asked():
    agreed = {**copy.deepcopy(OFFLINE), "question": "Is a paper backup needed?"}
    unknown = {**copy.deepcopy(OFFLINE), "question": "Is there a second clinic later?"}
    candidate = profile(*PROBES, agreed, unknown)
    q_agreed, q_unknown = qid(agreed), qid(unknown)
    record = record_with(
        human(Q_OFF, "Yes.", "e-1"), human(Q_OFF, "No.", "e-2", actor="telegram-user:5002"),  # conflicting
        human(Q_REGION, "Ask the lawyer first.", "e-3", disposition="deferred"),
        human(q_unknown, "Nobody knows yet.", "e-4", disposition="unknown"),
        human(Q_USERS, "Five.", "e-5"), reopen(Q_USERS, "e-6"),
        human(q_agreed, "Yes.", "e-7"), human(q_agreed, "Yes.", "e-8", actor="telegram-user:5002"),
        candidate=candidate,
    )
    prepared = caller.prepare(inputs(candidate, revision=8, record=record))
    states = {q: row(prepared, q)["state"] for q in (Q_OFF, Q_REGION, q_unknown, Q_USERS, q_agreed)}
    assert states == {Q_OFF: "conflicting", Q_REGION: "deferred", q_unknown: "unknown", Q_USERS: "reopened",
                      q_agreed: "answered"}
    unresolved = {Q_OFF, Q_REGION, q_unknown, Q_USERS}
    assert unresolved <= set(prepared["unresolved_question_ids"]) and q_agreed not in prepared["unresolved_question_ids"]
    agreed_row = row(prepared, q_agreed)
    assert (agreed_row["answer"], [e["actor"]["ref"] for e in agreed_row["active"]]) == (
        "Yes.", ["telegram-user:5001", "telegram-user:5002"])
    assert [e["answer"] for e in row(prepared, Q_OFF)["active"]] == ["Yes.", "No."]
    assert row(prepared, Q_USERS)["active"] == [] and row(prepared, Q_USERS)["history_event_ids"] == ["e-5", "e-6"]
    assert {item["material"] for item in prepared["questions"]} == {True, False}  # shown, not a global block
    asked = caller.prepare(inputs(candidate, revision=8, record=record, ask=tuple(sorted(unresolved))))
    assert asked["ask"] == sorted(unresolved)
    refused("ask.unresolved", caller.prepare, inputs(candidate, revision=8, record=record, ask=(q_agreed,)))


def test_correction_and_reopen_keep_history_and_show_the_active_snapshot():
    corrected = record_with(human(Q_OFF, "Yes.", "e-1"),
                            human(Q_OFF, EXACT, "e-2", supersedes=["e-1"], reason="More exact."))
    prepared = caller.prepare(inputs(profile(*PROBES), revision=3, record=corrected))
    offline = row(prepared, Q_OFF)
    assert (offline["state"], offline["answer"]) == ("answered", EXACT)
    assert (offline["active_event_ids"], offline["history_event_ids"]) == (["e-2"], ["e-1", "e-2"])
    reopened = c.append_event(corrected, reopen(Q_OFF, "e-3"))
    prepared = caller.prepare(inputs(profile(*PROBES), revision=4, record=reopened, ask=(Q_OFF,)))
    offline = row(prepared, Q_OFF)
    assert (offline["state"], offline["answer"], offline["active"]) == ("reopened", None, [])
    assert offline["history_event_ids"] == ["e-1", "e-2", "e-3"] and prepared["ask"] == [Q_OFF]


def test_model_suggestions_stay_model_attributed_and_resolve_nothing():
    suggested = record_with(model(Q_OFF, "Probably offline.", "e-model-1"))
    prepared = caller.prepare(inputs(profile(*PROBES), revision=2, record=suggested, ask=(Q_OFF,)))
    offline = row(prepared, Q_OFF)
    assert (offline["state"], offline["resolved"], offline["answer"], offline["active"]) == (
        "unanswered", False, None, [])
    assert offline["model_suggestions"] == [{
        "event_id": "e-model-1", "disposition": "answered", "answer": "Probably offline.",
        "actor": {"kind": "model", "ref": "model:synthetic-suggester"},
        "source": {"kind": "model_output", "ref": "run:synthetic/1"},
    }]
    composed = caller.compose_supplement(inputs(profile(*PROBES), revision=2, record=suggested))
    assert json.loads(composed["supplement"])["answers"] == [] and "Probably offline." not in composed["supplement"]
    agreeing = c.append_event(suggested, human(Q_OFF, "Probably offline.", "e-1"))
    composed = caller.compose_supplement(inputs(profile(*PROBES), revision=3, record=agreeing))
    (answer,) = json.loads(composed["supplement"])["answers"]
    assert [a["event_id"] for a in answer["attributions"]] == ["e-1"]  # the person's answer only
    with pytest.raises(c.ClarificationError, match="model output cannot revise or reopen"):
        c.append_event(agreeing, model(Q_OFF, "Not offline.", "e-model-2", supersedes=["e-1"], reason="Changed."))


# --- composing for re-evaluation ----------------------------------------------


def test_compose_needs_a_committed_record():
    refused("compose.committed", caller.compose_supplement, inputs(profile(*PROBES)))


def test_compose_refuses_a_record_that_lacks_the_candidates_questions():
    record = record_with(human(Q_OFF, EXACT, "e-1"), candidate=profile(OFFLINE))
    refused("compose.covers_candidate", caller.compose_supplement, inputs(profile(*PROBES), revision=2, record=record))


@pytest.mark.parametrize("answer", ["Yes", "No", "5", "  Yes.\r\n", "はい", "Ja\u200b."])
def test_compose_keeps_short_and_exact_answers_unpadded_and_the_original_separate(answer):
    record = record_with(human(Q_OFF, answer, "e-1"))
    composed = caller.compose_supplement(inputs(profile(*PROBES), revision=2, record=record))
    supplement = json.loads(composed["supplement"])
    assert supplement["answers"][0]["answer"] == answer  # exact, never padded or stripped
    assert composed["original_text"] == BRIEF and BRIEF not in composed["supplement"]
    assert composed["supplement"] == c.compose_supplement(record, BRIEF)["supplement"]
    assert not composed["supplement"].startswith(BRIEF) and not composed["original_text"].endswith(composed["supplement"])


def test_empty_supplement_lists_everything_unresolved():
    composed = caller.compose_supplement(inputs(profile(*PROBES), revision=1, record=record_with()))
    assert json.loads(composed["supplement"])["answers"] == [] and composed["source_mapping"]["entries"] == []
    assert len(composed["unresolved_questions"]) == 28
    assert {state["state"] for state in composed["unresolved_questions"]} == {"unanswered"}


# --- purity, determinism, imports ---------------------------------------------


def test_public_operations_need_no_ambient_access(monkeypatch):
    record = record_with(human(Q_OFF, EXACT, "e-1"), model(Q_USERS, "Five.", "e-model-1"))
    first = inputs(profile(*PROBES))
    later = inputs(profile(*PROBES, reverse=True), revision=2, record=record, ask=(Q_REGION,))
    expected = (caller.prepare(first), caller.prepare(later), caller.compose_supplement(later))

    def deny(*args, **kwargs):
        raise AssertionError("public operation attempted ambient access")

    class NoEnvironment:
        __getitem__ = __iter__ = __contains__ = get = deny

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", deny)
        patch.setattr(io, "open", deny)
        for name in ("open", "stat", "listdir", "scandir", "getenv", "getcwd", "urandom", "system"):
            patch.setattr(os, name, deny)
        patch.setattr(os, "environ", NoEnvironment())
        for name in ("open", "read_text", "read_bytes", "resolve", "exists", "stat"):
            patch.setattr(Path, name, deny)
        for name in ("time", "monotonic", "perf_counter", "time_ns", "sleep"):
            patch.setattr(time, name, deny)
        for name in ("socket", "create_connection", "getaddrinfo"):
            patch.setattr(socket, name, deny)
        patch.setattr(subprocess, "Popen", deny)
        patch.setattr(subprocess, "run", deny)
        patch.setattr(sqlite3, "connect", deny)
        patch.setattr(builtins, "__import__", deny)  # last: nothing is imported lazily
        outputs = (caller.prepare(first), caller.prepare(later), caller.compose_supplement(later))
    assert outputs == expected


def test_outputs_are_deterministic_and_never_alias():
    later = inputs(profile(*PROBES), revision=2, record=record_with(human(Q_OFF, EXACT, "e-1")))
    first = caller.prepare(later)
    first["questions"][0]["decisions_affected"].append("caller-only change")
    first["questions"][0]["active_event_ids"].append("e-fake")
    composed = caller.compose_supplement(later)
    composed["source_mapping"]["entries"][0]["event_ids"].append("e-fake")
    composed["unresolved_questions"][0]["decisions_affected"].append("caller-only change")
    assert caller.prepare(later) == caller.prepare(later) != first
    assert caller.compose_supplement(later) == caller.compose_supplement(later) != composed


def test_module_imports_only_the_frozen_pieces_and_never_the_temper_ai_package():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imported == {"__future__", "hashlib", "importlib.util", "json", "pathlib", "configs.architecture.bin"}
    pieces = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
              and node.module == "configs.architecture.bin" for alias in node.names}
    assert pieces == {"context_profile_check", "context_profile_clarifications"}  # no score module: NOT_MEASURED kept
    assert Path(k.__file__) == CONTRACTS and not k.__name__.startswith("temper_ai")
    before = set(sys.modules)
    namespace = {"__name__": "fresh_clarification_caller", "__file__": str(MODULE)}
    exec(compile(tree, str(MODULE), "exec"), namespace)
    assert not {name for name in set(sys.modules) - before if name.startswith("temper_ai")}
    assert namespace["MEANING_STATUS"] == "NOT_EVALUATED" and namespace["clarifications"] is c


# --- every guard bites --------------------------------------------------------


def _mutated(transform):
    """An in-memory copy of the module with one change; never written to a file."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    assert transform(tree) == 1
    ast.fix_missing_locations(tree)
    namespace = {"__name__": "mutated_clarification_caller", "__file__": str(MODULE)}
    exec(compile(tree, "mutated-clarification-caller", "exec"), namespace)
    return SimpleNamespace(**namespace)


def _guard_calls(tree):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "_refuse_unless"]


def _disable(label):
    def transform(tree):
        hits = [call for call in _guard_calls(tree) if ast.literal_eval(call.args[1]) == label]
        for call in hits:
            call.args[0] = ast.Constant(True)
        return len(hits)
    return transform


def _forget_previous(tree):
    hits = [keyword for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_record" for keyword in node.keywords if keyword.arg == "previous"]
    for keyword in hits:
        keyword.value = ast.Constant(None)
    return len(hits)


def _look_alike(**changes):
    real = inputs(profile(*PROBES))
    fields = {name: getattr(real, name) for name in real.__dataclass_fields__}
    return SimpleNamespace(**{**fields, **changes}, candidate=real.candidate, prior_record=real.prior_record)


def _bite_caller_type(mod):
    with pytest.raises(k.ContractRefusal):
        inputs(profile(*PROBES), candidate_sha256="0" * 64)  # M0 refuses this binding
    out = mod.prepare(_look_alike(candidate_sha256="0" * 64))
    assert out["candidate_sha256"] == "0" * 64  # unguarded: a look-alike's false hash is bound as the candidate's
    return out


def _bite_candidate_complete(mod):
    out = mod.prepare(inputs(_envelope(profile(OFFLINE)), contracts=mod.contracts))
    assert len(out["questions"]) == 26  # unguarded: an envelope-only candidate became questions
    return out


def _bite_ask_current(mod):
    changed = METADATA_CHANGES["question_text"]
    out = mod.prepare(inputs(profile(changed, REGION, USERS), revision=1, record=record_with(), ask=(Q_OFF,),
                             contracts=mod.contracts))
    assert out["ask"] == [Q_OFF]  # unguarded: the stale old question would be asked
    return out


def _bite_ask_unresolved(mod):
    record = record_with(human(Q_OFF, EXACT, "e-1"))
    out = mod.prepare(inputs(profile(*PROBES), revision=2, record=record, ask=(Q_OFF,), contracts=mod.contracts))
    assert out["ask"] == [Q_OFF]  # unguarded: an answered question would be asked again
    return out


def _bite_compose_committed(mod):
    return mod.compose_supplement(inputs(profile(*PROBES), contracts=mod.contracts))


def _bite_compose_covers_candidate(mod):
    record = record_with(human(Q_OFF, EXACT, "e-1"), candidate=profile(OFFLINE))
    out = mod.compose_supplement(inputs(profile(*PROBES), revision=2, record=record, contracts=mod.contracts))
    hidden = {Q_REGION, Q_USERS} - {state["question_id"] for state in out["unresolved_questions"]}
    assert hidden == {Q_REGION, Q_USERS}  # unguarded: the new questions vanish from the unresolved list
    return out


GUARD_BITES = {
    "caller.type": _bite_caller_type,
    "candidate.complete": _bite_candidate_complete,
    "ask.current": _bite_ask_current,
    "ask.unresolved": _bite_ask_unresolved,
    "compose.committed": _bite_compose_committed,
    "compose.covers_candidate": _bite_compose_covers_candidate,
}


def test_guard_table_names_every_guard_in_the_module():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    labels = [ast.literal_eval(call.args[1]) for call in _guard_calls(tree) if len(call.args) > 1]
    assert sorted(labels) == sorted(GUARD_BITES) and len(labels) == len(set(labels))


@pytest.mark.parametrize("label", sorted(GUARD_BITES))
def test_each_guard_bites(label):
    scenario = GUARD_BITES[label]
    refused(label, scenario, caller)
    mutated = _mutated(_disable(label))
    if label == "compose.committed":
        with pytest.raises(c.ClarificationError) as info:
            scenario(mutated)
        # Unguarded: composing too early is the foundation's bare "expected object", the
        # same refusal a non-object record gets; the caller can no longer tell them apart.
        assert not isinstance(info.value, mutated.CallerRefusal) and str(info.value) == "expected object"
    else:
        scenario(mutated)


def test_previous_record_is_always_passed_to_create_record():
    record = record_with(human(Q_OFF, EXACT, "e-1"))
    scenario = lambda mod: mod.prepare(  # noqa: E731
        inputs(profile(REGION, USERS), revision=2, record=record, contracts=mod.contracts))
    kept = scenario(caller)
    assert row(kept, Q_OFF)["history_event_ids"] == ["e-1"]
    forgot = scenario(_mutated(_forget_previous))
    assert Q_OFF not in {item["question_id"] for item in forgot["questions"]}  # unguarded: history lost
    assert json.loads(forgot["record_json"])["events"] == []


def _recovery_handler(tree):
    adapter = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "_check_with_schema_error_recovery")
    return [node for node in ast.walk(adapter) if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name) and node.type.id == "TypeError"]


def _remove_checker_typeerror_recovery(tree):
    handlers = _recovery_handler(tree)
    for handler in handlers:
        handler.type = ast.Name(id="LookupError", ctx=ast.Load())
    return len(handlers)


def _widen_checker_error_recovery(tree):
    handlers = _recovery_handler(tree)
    for handler in handlers:
        handler.type = ast.Name(id="Exception", ctx=ast.Load())
    return len(handlers)


def _remove_schema_error_evidence(tree):
    conditions = [node for node in ast.walk(tree) if isinstance(node, ast.If)
                  and isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not)
                  and isinstance(node.test.operand, ast.Name) and node.test.operand.id == "schema_errors"]
    for condition in conditions:
        condition.test = ast.Constant(False)
    return len(conditions)


def test_schema_error_recovery_bites():
    candidate = _unhashable_profile("unknown_list")
    refused("candidate.complete", caller.prepare, inputs(candidate))
    mutated = _mutated(_remove_checker_typeerror_recovery)
    with pytest.raises(TypeError, match="unhashable type"):
        mutated.prepare(inputs(candidate, contracts=mutated.contracts))


@pytest.mark.parametrize("change,error_type,schema_invalid", [
    (_remove_schema_error_evidence, TypeError, False),
    (_widen_checker_error_recovery, RuntimeError, True),
])
def test_schema_error_recovery_scope_bites(monkeypatch, change, error_type, schema_invalid):
    candidate = _unhashable_profile("unknown_list") if schema_invalid else profile(*PROBES)
    failure = error_type("synthetic internal checker failure")

    def broken_check(*args, **kwargs):
        raise failure

    monkeypatch.setattr(caller.checker, "check", broken_check)
    with pytest.raises(error_type) as caught:
        caller.prepare(inputs(candidate))
    assert caught.value is failure
    mutated = _mutated(change)
    with pytest.raises(mutated.CallerRefusal) as caught:
        mutated.prepare(inputs(candidate, contracts=mutated.contracts))
    # Unguarded: an unexplained failure is hidden as an ordinary candidate refusal.
    assert caught.value.guard == "candidate.complete"
