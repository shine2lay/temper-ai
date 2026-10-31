"""Coordinator-only proof with NON-DURABLE recording ports and fixed replies.

No fake persistence implementation: mocks record calls, never merge history,
validate a receipt, arbitrate a send or implement CAS. Fixture snapshots are
explicit synthetic values built by real pure components. B/E must separately
prove actual-store V01, ingress, durability, races and network ordering.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import socket
import sqlite3
import subprocess
from copy import deepcopy
from dataclasses import dataclass, replace
from unittest.mock import Mock

import pytest
import sqlalchemy

from configs.architecture.bin import context_profile_clarification_caller as m1
from configs.architecture.bin import (
    context_profile_clarified_check as reference_checker,
)
from temper_ai.clarifications import caller as coordinator
from temper_ai.clarifications import contracts as m0
from temper_ai.clarifications import preparation_adapter as adapter
from temper_ai.clarifications.caller_contracts import (
    ClarificationAuthority,
    CoordinatorStore,
    PresentationRequest,
    QuestionTransport,
)
from temper_ai.clarifications.store import (
    ClarificationIntegrityError,
    RecordResult,
    StoredStream,
    Supplement,
)
from temper_ai.integrations.telegram.clarifications import SendResult
from tests.test_clarifications.composition_scenarios import (
    BRIEF,
    BRIEF_SHA,
    COMPOSITION_ANSWER,
    COMPOSITION_UNKNOWN,
    clarified_candidate,
    clarified_validator,
    composition_profile,
    inputs,
    receipt_event,
    row,
    sha,
)
from tests.test_clarifications.test_preparation_adapter import mutated_module

Q = m0.question_id(BRIEF_SHA, COMPOSITION_UNKNOWN)
TEXT = " Exact display: café 東京\r\n"
ENTRIES = ("prepare", "present", "recover", "check_candidate")


@dataclass
class Snapshot:
    context: m0.CallerInput
    stored: StoredStream
    result: RecordResult
    supplement: Supplement
    profile: dict


def snapshot(*, answered=True, candidate=None, previous=None, revision=None, answer=COMPOSITION_ANSWER):
    """Construct declared port replies, not a store or simulated transaction."""
    candidate = composition_profile() if candidate is None else candidate
    initial = inputs(candidate, revision=0 if previous is None else previous.context.prior_revision,
                     record=None if previous is None else previous.context.prior_record_json)
    display = adapter.prepare(initial)
    record = json.loads(display["record_json"])
    if answered:
        selected = replace(initial, question_ids=(Q,))
        event = receipt_event(selected, display, Q, answer, "601")
        record = m1.clarifications.append_event(record, event)
    revision = (2 if answered else 1) if revision is None else revision
    text = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    context = inputs(candidate, revision=revision, record=text)
    composed = adapter.compose_supplement(context)
    stored = StoredStream(context.stream, context.source_authority_ref, revision, text, sha(text), (), (), revision)
    result = RecordResult(context.stream.stream_id, revision, text, sha(text), True)
    supplement = Supplement(context.stream.stream_id, revision, composed["consumption_id"],
                            composed["supplement_sha256"], sha(text), BRIEF, composed["supplement"],
                            composed["source_mapping"], False)
    state = row(adapter.prepare(context), Q) if answered else None
    profile = (clarified_candidate(candidate, source_mapping=composed["source_mapping"], question_id=Q,
                                   question=COMPOSITION_UNKNOWN["question"], answer=answer,
                                   event_ids=state["active_event_ids"]) if answered else candidate)
    return Snapshot(context, stored, result, supplement, profile)


class RecordingPorts:
    """Named mocks with configurable fixed replies; explicitly NON-DURABLE."""

    def __init__(self, state=None, *, module=coordinator):
        self.state = snapshot() if state is None else state
        self.events = []
        self.store = Mock(spec=CoordinatorStore)
        self.transport = Mock(spec=QuestionTransport)
        self.authority = Mock(spec=ClarificationAuthority)
        self.denied = None
        for name in ("load", "merge_candidate", "supplement", "save_presentation", "mark_current_consumed"):
            method = getattr(self.store, name)
            method.side_effect = self.record(name, method)
        self.store.load.return_value = self.state.stored
        self.store.merge_candidate.return_value = self.state.result
        self.store.supplement.return_value = self.state.supplement
        self.store.save_presentation.return_value = True
        self.store.mark_current_consumed.return_value = True
        self.transport.present.side_effect = self.record("transport.present", self.transport.present)
        self.transport.present.return_value = SendResult("sent", "synthetic-send", "500")
        self.authority.require.side_effect = self.permit
        self.instance = module.ClarificationCoordinator(store=self.store, transport=self.transport,
                                                       authority=self.authority,
                                                       clarified_validator=clarified_validator())

    def record(self, name, method):
        def called(*args, **kwargs):
            self.events.append(name)
            return method.return_value
        return called

    def permit(self, **scope):
        self.events.append("permit." + scope["operation"])
        assert scope["stream"] == self.state.context.stream
        assert scope["source_authority_ref"] == self.state.context.source_authority_ref
        assert scope["responder_policy_ref"] == self.state.context.responder_policy_ref
        if scope["operation"] == self.denied:
            raise PermissionError("synthetic denial")

    def check(self, profile=None):
        return self.instance.check_candidate(self.state.context,
                                             profile=self.state.profile if profile is None else profile,
                                             candidate_ref="candidate:synthetic/clarified")

    def clear(self):
        self.events.clear()
        self.store.reset_mock()
        self.transport.reset_mock()
        self.authority.reset_mock()


def request(context):
    selected = replace(context, question_ids=(Q,))
    presentation = selected.presentation(Q, m0.metadata_sha256(COMPOSITION_UNKNOWN), 1)
    return selected, PresentationRequest(presentation, TEXT)


def invoke(rig, entry, context=None):
    context = rig.state.context if context is None else context
    if entry == "present":
        selected, supplied = request(context)
        return rig.instance.present(selected, presentations=(supplied,))
    if entry == "check_candidate":
        return rig.instance.check_candidate(context, profile=rig.state.profile, candidate_ref="candidate:synthetic/f1")
    return getattr(rig.instance, entry)(context)


def test_combined_coordinator_happy_path_real_pure_components_nondurable_recording_ports():
    initial = snapshot(answered=False)
    rig = RecordingPorts(initial)
    assert rig.events == []  # constructor does not invoke injected ports
    prepared = rig.instance.prepare(inputs(composition_profile(), ask=(Q,)))
    assert rig.events == ["permit.read", "permit.write", "merge_candidate"]
    assert prepared.record == initial.result and prepared.display["ask"] == []
    assert prepared.display["expected_revision"] == 1
    selected, supplied = request(initial.context)
    rig.clear()
    sent = rig.instance.present(selected, presentations=(supplied,))
    assert rig.events == ["permit.read", "permit.write", "permit.send", "load", "load",
                          "save_presentation", "transport.present"]
    rig.store.save_presentation.assert_called_once_with(supplied.presentation)
    rig.transport.present.assert_called_once_with(supplied.presentation, COMPOSITION_UNKNOWN, TEXT, resend=False)
    assert sent == (SendResult("sent", "synthetic-send", "500"),)

    # Explicit new fixture reply: NOT an ingress/appending/durability simulation.
    answered = snapshot()
    rig = RecordingPorts(answered)
    rig.store.supplement.side_effect = [initial.supplement, answered.supplement]
    recovered = rig.instance.recover(initial.context)
    rig.store.supplement.side_effect = rig.record("supplement", rig.store.supplement)
    assert recovered.stored == answered.stored
    assert row(recovered.display, Q)["answer"] == COMPOSITION_ANSWER
    assert recovered.display["ask"] == [] and recovered.supplement.original_brief == BRIEF
    checked = rig.check()
    assert checked.report["references_ok"] is True
    assert checked.report["unresolved_questions"]  # no universal block-all rule
    assert checked.report["meaning_status"] == checked.meaning_status == "NOT_EVALUATED"
    assert checked.original_text == BRIEF and checked.original_sha256 == BRIEF_SHA
    assert checked.source_mapping == answered.supplement.source_mapping
    assert checked.consumption_id == answered.supplement.consumption_id
    rig.clear()
    assert rig.instance.acknowledge_consumption(answered.context, checked=checked) is True
    assert rig.events == ["permit.read", "permit.acknowledge", "load", "supplement", "supplement",
                          "mark_current_consumed"]
    rig.store.mark_current_consumed.assert_called_once_with(
        answered.context.stream, revision=2, record_sha256=answered.stored.record_sha256,
        consumption_id=answered.supplement.consumption_id, original_brief=BRIEF)
    rig.store.supplement.return_value = replace(answered.supplement, consumed=True)
    rig.clear()
    assert rig.instance.acknowledge_consumption(answered.context, checked=checked) is False
    assert rig.events == ["permit.read", "permit.acknowledge", "load", "supplement"]
    rig.transport.assert_not_called()
    rig.transport.present.assert_not_called()
    for name in ("append_receipt", "record_copy", "mark_consumed", "merge_candidate", "save_presentation"):
        getattr(rig.store, name).assert_not_called()


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("variant", ["missing", "field", "constraint", "goal", "combined"])
def test_v02_real_full_checker_first_before_any_port(monkeypatch, entry, variant):
    rig = RecordingPorts(snapshot(answered=False))
    candidate = composition_profile()
    if variant in ("missing", "combined"):
        candidate.pop("team")
    if variant in ("field", "combined"):
        candidate["unknowns"][0]["field"] = []
    if variant in ("constraint", "combined"):
        candidate["constraints"] = [{"id": [], "text": "synthetic"}]
    if variant in ("goal", "combined"):
        candidate["goals"] = [{"id": {}, "text": "synthetic"}]
    full = Mock(wraps=m1.checker.check)
    monkeypatch.setattr(m1.checker, "check", full)
    with pytest.raises(m1.CallerRefusal) as caught:
        invoke(rig, entry, inputs(candidate))
    assert caught.value.guard == "candidate.complete" and caught.value.errors
    assert full.call_count == 1 and rig.events == []


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("error", [TypeError("internal checker"), ValueError("internal checker")])
def test_v02_schema_valid_internal_checker_errors_propagate(monkeypatch, entry, error):
    rig = RecordingPorts(snapshot(answered=False))
    monkeypatch.setattr(m1.checker, "check", Mock(side_effect=error))
    with pytest.raises(type(error)) as caught:
        invoke(rig, entry)
    assert caught.value is error and rig.events == []


@pytest.mark.parametrize("entry", ENTRIES)
def test_exact_canonical_type_required_at_all_ordinary_entries(entry):
    rig = RecordingPorts(snapshot(answered=False))
    local = inputs(composition_profile(), contracts=m1.contracts)
    with pytest.raises(m1.CallerRefusal, match="caller.type"):
        invoke(rig, entry, local)
    assert rig.events == []


@pytest.mark.parametrize("entry,operation", [("prepare", "read"), ("prepare", "write"),
                                             ("present", "read"), ("present", "write"), ("present", "send"),
                                             ("recover", "read"), ("check_candidate", "read"),
                                             ("ack", "read"), ("ack", "acknowledge")])
def test_denial_precedes_every_corresponding_port(entry, operation):
    rig = RecordingPorts(snapshot(answered=entry != "present"))
    checked = rig.check() if entry == "ack" else None
    rig.clear()
    rig.denied = operation
    with pytest.raises(PermissionError, match="synthetic denial"):
        if entry == "ack":
            rig.instance.acknowledge_consumption(rig.state.context, checked=checked)
        else:
            invoke(rig, entry)
    assert rig.store.mock_calls == [] and rig.transport.mock_calls == []


@pytest.mark.parametrize("state", ["sent", "delivered", "uncertain", "answered", "not_current", "pending"])
def test_send_states_and_explicit_resend_are_not_promoted(state):
    rig = RecordingPorts(snapshot(answered=False))
    selected, supplied = request(rig.state.context)
    result = SendResult(state, supplied.presentation.presentation_id, error="synthetic status")
    rig.transport.present.return_value = result
    assert rig.instance.present(selected, presentations=(supplied,), resend=True) == (result,)
    assert rig.transport.present.call_args.kwargs == {"resend": True}


@pytest.mark.parametrize("failure", [m0.ContractRefusal(m0.RefusalCode.STALE_PRESENTATION, "store.generation"),
                                      ClarificationIntegrityError("synthetic", "copy", "synthetic damage"),
                                      PermissionError("policy down"), sqlalchemy.exc.SQLAlchemyError("DB down"),
                                      TypeError("programming error"), RuntimeError("unexpected error")])
def test_errors_remain_distinct_and_no_send_after_presentation_failure(failure):
    rig = RecordingPorts(snapshot(answered=False))
    rig.store.save_presentation.side_effect = failure
    with pytest.raises(type(failure)) as caught:
        invoke(rig, "present")
    assert caught.value is failure
    rig.transport.present.assert_not_called()


def test_newly_answered_selection_is_shown_after_merge_not_reasked():
    rig = RecordingPorts()
    initial = snapshot(answered=False)
    selected, _ = request(initial.context)
    prepared = rig.instance.prepare(selected)
    assert row(prepared.display, Q)["answer"] == COMPOSITION_ANSWER
    assert prepared.display["ask"] == [] and selected.question_ids == (Q,)
    rig.clear()
    with pytest.raises(m1.CallerRefusal) as caught:
        invoke(rig, "present")
    assert caught.value.guard == "ask.unresolved" and rig.events == []


def test_stale_present_and_movement_between_presentations_never_send_next():
    rig = RecordingPorts(snapshot(answered=False))
    selected, supplied = request(rig.state.context)
    later = replace(rig.state.stored, revision=2)
    rig.store.load.side_effect = [rig.state.stored, rig.state.stored, later]
    with pytest.raises(m0.ContractRefusal) as caught:
        rig.instance.present(selected, presentations=(supplied, supplied))
    assert caught.value.code is m0.RefusalCode.REVISION_CONFLICT
    assert rig.store.save_presentation.call_count == rig.transport.present.call_count == 1


@pytest.mark.parametrize("variant", ["reordered", "changed", "decisions", "field", "absent", "reintroduced"])
def test_v16_explicit_candidate_history_not_answer_migration(variant):
    before = snapshot()
    candidate = composition_profile()
    if variant == "reordered":
        candidate["unknowns"].reverse()
    elif variant in ("changed", "decisions", "field"):
        probe = candidate["unknowns"][-1]
        if variant == "changed":
            probe["question"] += " Always?"
        elif variant == "decisions":
            probe["decisions_affected"] = ["another decision", "offline storage"]
        else:
            probe.pop("field")
    elif variant == "absent":
        candidate["unknowns"].pop()
    previous = before
    if variant == "reintroduced":
        absent = composition_profile()
        absent["unknowns"].pop()
        previous = snapshot(answered=False, candidate=absent, previous=before, revision=3)
    result = snapshot(answered=False, candidate=candidate, previous=previous, revision=4)
    rig = RecordingPorts(result)
    provided = inputs(candidate, revision=previous.context.prior_revision, record=previous.context.prior_record_json)
    prepared = rig.instance.prepare(provided)
    assert row(prepared.display, Q)["answer"] == COMPOSITION_ANSWER
    assert len(json.loads(prepared.record.record_json)["events"]) == 1
    if variant in ("changed", "decisions", "field"):
        new_q = m0.question_id(BRIEF_SHA, candidate["unknowns"][-1])
        assert new_q != Q and row(prepared.display, new_q)["answer"] is None
    assert row(prepared.display, Q)["change"] == ("absent" if variant in
                                                 ("changed", "decisions", "field", "absent") else "repeated")
    assert rig.transport.mock_calls == []


@pytest.mark.parametrize("entry", ["recover", "check_candidate", "present"])
def test_uncommitted_changed_candidate_is_not_inferred_into_store(entry):
    rig = RecordingPorts(snapshot(answered=False))
    candidate = composition_profile()
    candidate["unknowns"].append({**COMPOSITION_UNKNOWN, "question": "A different supplied question?"})
    provided = inputs(candidate, revision=1, record=rig.state.context.prior_record_json)
    with pytest.raises(m1.CallerRefusal) as caught:
        invoke(rig, entry, provided)
    assert caught.value.guard == "compose.covers_candidate"
    rig.store.save_presentation.assert_not_called()
    rig.transport.present.assert_not_called()


@pytest.mark.parametrize("variant,reason", [("source", "clarification_source_mismatch"),
                                            ("record", "record_hash_mismatch"),
                                            ("event", "clarification_events_mismatch"),
                                            ("empty", "clarification_events_mismatch"),
                                            ("duplicate", "clarification_events_mismatch"),
                                            ("answer", "clarification_answer_mismatch"),
                                            ("question", "clarification_question_mismatch")])
def test_v17_real_checker_refuses_changed_mapping_and_exact_text(variant, reason):
    rig = RecordingPorts()
    candidate = deepcopy(rig.state.profile)
    source = candidate["constraints"][0]["source"]
    if variant in ("source", "record"):
        candidate["clarification_source"]["source_id" if variant == "source" else "record_sha256"] = "0" * 64
    elif variant == "event":
        source["event_ids"] = ["e-" + "0" * 64]
    elif variant == "empty":
        source["event_ids"] = []
    elif variant == "duplicate":
        source["event_ids"] *= 2
    elif variant == "answer":
        source["answer"] = COMPOSITION_ANSWER.strip()
    else:
        source["question"] += " changed"
    checked = rig.check(candidate)
    assert checked.report["references_ok"] is False
    assert reason in {error["reason"] for error in checked.report["errors"]}
    assert checked.report["meaning_status"] == "NOT_EVALUATED"
    with pytest.raises(m0.ContractRefusal) as caught:
        rig.instance.acknowledge_consumption(rig.state.context, checked=checked)
    assert caught.value.guard == "coordinator.checked_report"
    rig.store.mark_current_consumed.assert_not_called()


def test_reference_success_does_not_evaluate_negative_answer_meaning():
    rig = RecordingPorts(snapshot(answer="No, do not build offline storage.\n"))
    checked = rig.check()
    assert checked.report["references_ok"] is True
    assert checked.report["meaning_status"] == "NOT_EVALUATED"
    assert "accepted" not in checked.report and "resumed" not in checked.report


@pytest.mark.parametrize("validator", [m1.VALIDATOR, object()])
def test_wrong_preloaded_validator_is_reported_not_replaced(validator):
    rig = RecordingPorts()
    rig.instance._validator = validator
    checked = rig.check()
    assert checked.report["references_ok"] is False
    assert "validator_contract_mismatch" in {error["reason"] for error in checked.report["errors"]}


def test_record_movement_during_check_is_not_rebound(monkeypatch):
    rig = RecordingPorts()
    actual = reference_checker.check_clarified_profile
    def moving(*args):
        result = actual(*args)
        rig.store.load.return_value = replace(rig.state.stored, revision=3)
        return result
    monkeypatch.setattr(coordinator, "check_clarified_profile", moving)
    with pytest.raises(m0.ContractRefusal) as caught:
        rig.check()
    assert (caught.value.code, caught.value.guard) == (m0.RefusalCode.REVISION_CONFLICT, "coordinator.current")
    assert rig.store.load.call_count == 2


def test_new_ack_movement_during_checker_reaches_current_only_cas_and_keeps_refusal(monkeypatch):
    rig = RecordingPorts()
    checked = rig.check()
    actual = reference_checker.check_clarified_profile
    refusal = m0.ContractRefusal(m0.RefusalCode.REVISION_CONFLICT, "consume.current")
    def moving(*args):
        rig.store.mark_current_consumed.side_effect = refusal
        return actual(*args)
    monkeypatch.setattr(coordinator, "check_clarified_profile", moving)
    with pytest.raises(m0.ContractRefusal) as caught:
        rig.instance.acknowledge_consumption(rig.state.context, checked=checked)
    assert caught.value is refusal
    rig.store.mark_consumed.assert_not_called()


def test_saved_duplicate_after_movement_needs_no_new_candidate_acceptance(monkeypatch):
    rig = RecordingPorts()
    checked = rig.check()
    rig.store.load.return_value = replace(rig.state.stored, revision=3)
    rig.store.supplement.return_value = replace(rig.state.supplement, consumed=True)
    malformed = composition_profile()
    malformed.pop("team")
    context = inputs(malformed, revision=2, record=rig.state.context.prior_record_json)
    monkeypatch.setattr(m1.checker, "check", Mock(side_effect=AssertionError("renewed candidate validation")))
    monkeypatch.setattr(coordinator, "check_clarified_profile", Mock(side_effect=AssertionError("renewed acceptance")))
    rig.clear()
    assert rig.instance.acknowledge_consumption(context, checked=checked) is False
    assert rig.events == ["permit.read", "permit.acknowledge", "load", "supplement"]
    rig.store.mark_current_consumed.assert_not_called()


def test_returned_containers_never_alias_supplied_or_store_values():
    rig = RecordingPorts()
    supplied = deepcopy(rig.state.profile)
    recovered = rig.instance.recover(rig.state.context)
    checked = rig.check(supplied)
    again = rig.check(supplied)
    recovered.display["questions"].clear()
    recovered.supplement.source_mapping["entries"].clear()
    checked.source_mapping["entries"].clear()
    checked.report["unresolved_questions"].clear()
    supplied["constraints"][0]["source"]["event_ids"].clear()
    assert rig.state.supplement.source_mapping["entries"]
    assert again.source_mapping["entries"] and again.report["unresolved_questions"]
    assert json.loads(checked.candidate_json)["constraints"][0]["source"]["event_ids"]
    assert rig.state.context.prior_record() == rig.state.stored.record()


@pytest.mark.parametrize("entry", ENTRIES)
def test_no_operational_io_or_runtime_defaults_beyond_injected_ports(monkeypatch, entry):
    rig = RecordingPorts(snapshot(answered=entry != "present"))
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected operational I/O")
    with monkeypatch.context() as patch:
        for target, name in ((builtins, "open"), (io, "open"), (os, "getenv"), (socket, "socket"),
                             (sqlite3, "connect"), (sqlalchemy, "create_engine"), (subprocess, "Popen"),
                             (m1, "_load_contracts_by_path")):
            patch.setattr(target, name, forbidden)
        invoke(rig, entry)
    for name in ("record_copy", "append_receipt", "mark_consumed", "mark_current_consumed"):
        getattr(rig.store, name).assert_not_called()


def test_module_has_only_explicit_public_operations_not_ingress_or_registration():
    assert coordinator.__all__ == ["ClarificationCoordinator"]
    assert {name for name in vars(coordinator.ClarificationCoordinator) if not name.startswith("_")} == {
        "prepare", "present", "recover", "check_candidate", "acknowledge_consumption"}


# Each case observes a particular refusal before effects. The paired bite drops
# just that guard; the SAME assertion must fail, and the mutation must be reached.
GUARDS = {
    "authority": "authority", "store": "ports", "transport": "ports", "validator": "ports",
    "missing": "record_missing", "namespace": "scope", "authority_scope": "scope",
    "stale": "current", "digest": "record", "requests_type": "presentations",
    "request_type": "presentations", "resend_type": "resend", "presentation_type": "presentation_shape",
    "text_type": "presentation_shape", "unselected": "selection", "binding": "presentation_binding",
    "recovery_digest": "recovery_record", "checked_type": "checked_type", "checked_stream": "checked_context",
    "checked_original": "checked_context", "checked_brief_hash": "checked_context",
    "checked_revision": "checked_record", "checked_bool_revision": "checked_record",
    "checked_hash": "checked_record", "checked_source": "checked_source",
    "checked_supplement": "checked_source", "checked_consumption": "checked_source",
    "checked_candidate_hash": "checked_candidate", "checked_candidate_canonical": "checked_candidate",
    "checked_report": "checked_report",
}


def guard_case(case, module=coordinator):
    rig = RecordingPorts(snapshot(answered=False) if case in {
        "requests_type", "request_type", "resend_type", "presentation_type", "text_type", "unselected", "binding",
    } else None, module=module)
    if case == "checked_bool_revision":
        rig = RecordingPorts(snapshot(revision=1), module=module)
    context = rig.state.context
    if case in ("authority", "store", "transport", "validator"):
        ports = dict(store=rig.store, transport=rig.transport, authority=rig.authority,
                     clarified_validator=clarified_validator())
        ports["clarified_validator" if case == "validator" else case] = None
        return rig, lambda: module.ClarificationCoordinator(**ports)
    if case in ("missing", "namespace", "authority_scope", "stale", "digest"):
        if case == "missing":
            rig.store.load.return_value = None
        elif case == "namespace":
            rig.store.load.return_value = replace(rig.state.stored, stream=m0.StreamKey("project:other", BRIEF_SHA))
        elif case == "authority_scope":
            rig.store.load.return_value = replace(rig.state.stored, source_authority_ref="authority:other")
        elif case == "stale":
            rig.store.load.return_value = replace(rig.state.stored, revision=3)
        else:
            rig.store.load.return_value = replace(rig.state.stored, record_sha256="0" * 64)
        return rig, rig.check
    if case == "recovery_digest":
        rig.store.supplement.side_effect = [replace(rig.state.supplement, record_sha256="0" * 64), rig.state.supplement]
        return rig, lambda: rig.instance.recover(context)
    if case.startswith("checked_"):
        checked = rig.check()
        rig.clear()
        changes = {
            "checked_stream": {"stream": m0.StreamKey("project:other", BRIEF_SHA)},
            "checked_original": {"original_text": BRIEF + " "},
            "checked_brief_hash": {"original_sha256": "0" * 64},
            "checked_revision": {"revision": 3},
            "checked_bool_revision": {"revision": True},
            "checked_hash": {"record_sha256": "0" * 64},
            "checked_source": {"source_mapping": {}},
            "checked_supplement": {"supplement": checked.supplement + " "},
            "checked_consumption": {"consumption_id": "consume-other"},
            "checked_candidate_hash": {"candidate_sha256": "0" * 64},
            "checked_candidate_canonical": {"candidate_json": checked.candidate_json + " "},
            "checked_report": {"report": {**checked.report, "meaning_status": "PASS"}},
        }
        supplied = object() if case == "checked_type" else replace(checked, **changes[case])
        return rig, lambda: rig.instance.acknowledge_consumption(context, checked=supplied)
    selected, supplied = request(context)
    presentations, resend = (supplied,), False
    if case == "requests_type":
        presentations = [supplied]
    elif case == "request_type":
        presentations = (object(),)
    elif case == "resend_type":
        resend = 1
    elif case == "presentation_type":
        presentations = (replace(supplied, presentation=object()),)
    elif case == "text_type":
        presentations = (replace(supplied, text={}),)
    elif case == "unselected":
        selected = context
    else:
        presentations = (replace(supplied, presentation=replace(supplied.presentation, chat_id="-1002")),)
    return rig, lambda: rig.instance.present(selected, presentations=presentations, resend=resend)


def assert_refusal(call, guard):
    try:
        call()
    except m0.ContractRefusal as error:
        observed = error.guard
    except Exception as error:  # test oracle: distinguish wrong exception, never count it as success
        observed = type(error).__name__
    else:
        observed = "no refusal"
    assert observed == guard, f"guard outcome: expected {guard}, got {observed}"


@pytest.mark.parametrize("case,guard", GUARDS.items())
def test_guard_refusals_and_assertion_specific_bites(monkeypatch, case, guard):
    rig, call = guard_case(case)
    assert_refusal(call, "coordinator." + guard)
    rig.store.mark_current_consumed.assert_not_called()
    rig.store.save_presentation.assert_not_called()
    rig.transport.present.assert_not_called()
    # Build every fixture BEFORE installing the mutation, so setup errors never
    # qualify as a bite. Count the exact guard reached with a false condition.
    _mutant_rig, mutated_call = guard_case(case)
    reached = []
    original = coordinator._require
    def drop_one(ok, code, current):
        if current == "coordinator." + guard:
            reached.append(ok)
            return
        original(ok, code, current)
    monkeypatch.setattr(coordinator, "_require", drop_one)
    with pytest.raises(AssertionError, match="guard outcome: expected coordinator\\."):
        assert_refusal(mutated_call, "coordinator." + guard)
    assert False in reached, "mutation did not reach the named false guard"


@pytest.mark.parametrize("field", ["stream_id", "revision", "record_sha256", "consumption_id", "original_brief",
                                    "supplement", "supplement_sha256", "source_mapping"])
def test_composition_integrity_fields_have_specific_bites(monkeypatch, field):
    def assert_binding(module):
        rig = RecordingPorts(module=module)
        value = 9 if field == "revision" else {} if field == "source_mapping" else "changed"
        rig.store.supplement.return_value = replace(rig.state.supplement, **{field: value})
        try:
            rig.check()
        except ClarificationIntegrityError as error:
            assert error.guard == "coordinator.supplement"
            return
        raise AssertionError("stored composition mismatch accepted")
    assert_binding(coordinator)
    mutant = mutated_module(monkeypatch, coordinator, "if actual != expected:", "if False:")
    with pytest.raises(AssertionError, match="stored composition mismatch accepted"):
        assert_binding(mutant)


def test_merge_scope_has_specific_bite(monkeypatch):
    def assert_binding(module):
        rig = RecordingPorts(module=module)
        rig.store.merge_candidate.return_value = replace(rig.state.result, stream_id="different")
        try:
            rig.instance.prepare(inputs(composition_profile()))
        except ClarificationIntegrityError as error:
            assert error.guard == "coordinator.merge_stream"
            return
        raise AssertionError("cross-stream merge result accepted")
    assert_binding(coordinator)
    mutant = mutated_module(monkeypatch, coordinator,
                            "if committed.stream_id != caller.stream.stream_id:", "if False:")
    with pytest.raises(AssertionError, match="cross-stream merge result accepted"):
        assert_binding(mutant)


def test_current_only_ack_and_after_checker_fence_have_specific_bites(monkeypatch):
    def assert_current_port(module):
        rig = RecordingPorts(module=module)
        checked = rig.check()
        rig.instance.acknowledge_consumption(rig.state.context, checked=checked)
        assert rig.store.mark_current_consumed.call_count == 1, "current-only port not invoked"
    assert_current_port(coordinator)
    mutant = mutated_module(monkeypatch, coordinator, "return self._store.mark_current_consumed(",
                            "return self._store.mark_consumed(")
    with pytest.raises(AssertionError, match="current-only port not invoked"):
        assert_current_port(mutant)
    mutant = mutated_module(monkeypatch, coordinator,
                            "        self._current(context, self._load(context))\n        return CheckedClarification(",
                            "        return CheckedClarification(")
    def assert_second_read(module):
        rig = RecordingPorts(module=module)
        rig.store.load.side_effect = [rig.state.stored, replace(rig.state.stored, revision=3)]
        assert_refusal(rig.check, "coordinator.current")
    assert_second_read(coordinator)
    with pytest.raises(AssertionError, match="guard outcome: expected coordinator.current"):
        assert_second_read(mutant)


def test_ack_json_failures_are_narrow_and_do_not_hide_programming_errors(monkeypatch):
    rig = RecordingPorts()
    checked = rig.check()
    with pytest.raises(m0.ContractRefusal) as caught:
        rig.instance.acknowledge_consumption(rig.state.context, checked=replace(checked, candidate_json="{"))
    assert caught.value.guard == "coordinator.checked_json"
    failure = RuntimeError("synthetic internal checker failure")
    monkeypatch.setattr(coordinator, "check_clarified_profile", Mock(side_effect=failure))
    with pytest.raises(RuntimeError) as caught:
        rig.instance.acknowledge_consumption(rig.state.context, checked=checked)
    assert caught.value is failure
    rig.store.mark_current_consumed.assert_not_called()


def test_stale_new_ack_refuses_but_cas_kept_duplicate_returns_false():
    rig = RecordingPorts()
    checked = rig.check()
    rig.store.load.return_value = replace(rig.state.stored, revision=3)
    assert_refusal(lambda: rig.instance.acknowledge_consumption(rig.state.context, checked=checked),
                   "coordinator.current")
    rig.store.mark_current_consumed.assert_not_called()
    rig.store.load.return_value = rig.state.stored
    rig.store.mark_current_consumed.return_value = False  # another caller already acknowledged in the CAS
    assert rig.instance.acknowledge_consumption(rig.state.context, checked=checked) is False


@pytest.mark.parametrize("entry", ["prepare", "present"])
def test_full_checker_before_effect_has_order_specific_bite(monkeypatch, entry):
    def assert_order(module):
        rig = RecordingPorts(snapshot(answered=False), module=module)
        candidate = composition_profile()
        candidate.pop("team")
        try:
            invoke(rig, entry, inputs(candidate))
        except m1.CallerRefusal as error:
            assert error.guard == "candidate.complete"
        assert rig.events == [], "invalid candidate reached a port before full checker"
    assert_order(coordinator)
    if entry == "prepare":
        old = "        preparation_adapter.prepare(caller)\n        self._permit(caller, \"read\", \"write\")"
        new = "        self._permit(caller, \"read\", \"write\")"
    else:
        old = "        display = preparation_adapter.prepare(caller)\n        self._permit(caller, \"read\", \"write\", \"send\")"
        new = "        self._permit(caller, \"read\", \"write\", \"send\")\n        display = preparation_adapter.prepare(caller)"
    mutant = mutated_module(monkeypatch, coordinator, old, new)
    with pytest.raises(AssertionError, match="invalid candidate reached a port before full checker"):
        assert_order(mutant)


def test_presentation_before_transport_has_order_specific_bite(monkeypatch):
    def assert_order(module):
        rig = RecordingPorts(snapshot(answered=False), module=module)
        invoke(rig, "present")
        assert rig.events.index("save_presentation") < rig.events.index("transport.present"), "send before presentation"
    assert_order(coordinator)
    old = ("            self._store.save_presentation(request.presentation)\n"
           "            results.append(self._transport.present(request.presentation, unknown, request.text, resend=resend))")
    new = ("            results.append(self._transport.present(request.presentation, unknown, request.text, resend=resend))\n"
           "            self._store.save_presentation(request.presentation)")
    mutant = mutated_module(monkeypatch, coordinator, old, new)
    with pytest.raises(AssertionError, match="send before presentation"):
        assert_order(mutant)


@pytest.mark.parametrize("entry,operation", [("prepare", "write"), ("present", "send"),
                                             ("recover", "read"), ("ack", "acknowledge")])
def test_permission_checks_have_no_effect_specific_bites(monkeypatch, entry, operation):
    def assert_denied(module):
        rig = RecordingPorts(snapshot(answered=entry != "present"), module=module)
        checked = rig.check() if entry == "ack" else None
        rig.clear()
        rig.denied = operation
        denied = False
        try:
            if entry == "ack":
                rig.instance.acknowledge_consumption(rig.state.context, checked=checked)
            else:
                invoke(rig, entry)
        except PermissionError:
            denied = True
        assert denied and not rig.store.mock_calls and not rig.transport.mock_calls, "denied operation reached a port"
    assert_denied(coordinator)
    mutant = mutated_module(monkeypatch, coordinator,
                            "            self._authority.require(operation=operation, stream=caller.stream,\n"
                            "                                    source_authority_ref=cast(str, caller.source_authority_ref),\n"
                            "                                    responder_policy_ref=caller.responder_policy_ref)",
                            "            pass")
    with pytest.raises(AssertionError, match="denied operation reached a port"):
        assert_denied(mutant)


@pytest.mark.parametrize("profile", [{"bad": float("nan")}, {"bad": object()}])
def test_non_json_candidate_refused_without_invented_snapshot(monkeypatch, profile):
    rig = RecordingPorts()
    real = Mock(wraps=reference_checker.check_clarified_profile)
    monkeypatch.setattr(coordinator, "check_clarified_profile", real)
    with pytest.raises(m1.CallerRefusal) as caught:
        rig.check(profile)
    assert caught.value.guard == "candidate.json" and caught.value.errors
    assert real.call_count == 1
    rig.store.mark_current_consumed.assert_not_called()
