"""Actual-store history vectors. Direct receipt controls are trusted-port only.

Provider-capture cases use the actual M2 pull. No history, result or persistence
port is replaced. Each vector case keeps its source name for evidence joins.
"""

from dataclasses import replace

import pytest

from temper_ai.clarifications import contracts as c
from temper_ai.clarifications import models as m
from tests.test_clarifications import composition_vectors as v
from tests.test_clarifications.test_caller_integration import Composition
from tests.test_clarifications.test_caller_integration import db as db


def cases(vector):
    return next(item.cases for item in v.vectors() if item.id == vector)


def prompt_copy(rig):
    rig.ledger.record_delivery(rig.data["presentation"].presentation_id, v.PROMPT_COPY)


@pytest.mark.parametrize("case", cases("V09"), ids=lambda case: case.name)
def test_V09_exact_text_and_confirmation(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    rig.ready()
    name = case.name
    if "updates" in case.inputs:
        words, press = case.inputs["updates"]
        assert rig.pull(words) == 0
        held = rig.transport_store.receipt(v.typed_receipt(words["message"]["text"]).action.key)
        assert held.text.encode("utf-8") == words["message"]["text"].encode("utf-8")
        assert rig.row()["state"] == "unanswered"
        assert rig.pull(press) == 0
        row = rig.row()
        if name in ("exact", "unicode", "yes", "no"):
            assert row["answer"].encode("utf-8") == case.expected["confirmed_answer"].encode("utf-8")
            assert len(row["active_event_ids"]) == 1
        elif name in ("deferred", "unknown"):
            assert row["state"] == case.expected["state"] and not row["resolved"]
        else:
            assert not row["resolved"] and db.store.load(rig.initial.stream).record()["events"] == []
            if name == "denied_confirmer_pull":
                assert db.rows(m.ClarificationRefusal)[0].code == case.expected["code"]
        return
    if name == "model_suggestion":
        outcome = rig.append(replace(v.answer_receipt(text=case.inputs["suggested_text"]), ingress=c.MODEL_INGRESS))
        assert outcome.result.status == "refused" and outcome.held is None
        assert not rig.row()["resolved"] and db.rows(m.ClarificationReceipt) == []
        return
    prompt_copy(rig)
    words = case.inputs.get("typed", case.inputs.get("words", v.typed_receipt()))
    assert rig.append(words).result.status == "retained"
    press = case.inputs.get("press", v.confirmation_receipt(words))
    if name == "changed_digest":
        press = replace(press, confirms=case.inputs["confirms"])
    if name == "second_press":
        first, press = case.inputs["presses"]
        assert rig.append(first).result.status == "applied"
    outcome = rig.append(press)
    if name == "second_press":
        assert outcome.result.status == "retained" and outcome.guard == "confirmation.once"
        assert len(db.store.load(rig.initial.stream).record()["events"]) == 1
    else:
        assert outcome.result.status != "applied"
        assert not rig.row()["resolved"] and db.store.load(rig.initial.stream).record()["events"] == []
        if "code" in case.expected:
            assert outcome.result.code.value == case.expected["code"]
        if "guard" in case.expected:
            assert outcome.guard == case.expected["guard"]


@pytest.mark.parametrize("case", cases("V10"), ids=lambda case: case.name)
def test_V10_immutable_replay_and_key_recovery(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    rig.ready()
    prompt_copy(rig)
    words, press = v.typed_receipt(), v.confirmation_receipt()
    if case.name == "forged_then_genuine":
        assert rig.append(case.inputs["forged"]).result.status == "refused"
        assert db.rows(m.ClarificationReceipt) == []
        assert rig.append(case.inputs["genuine"]).result.status == "retained"
        assert len(db.rows(m.ClarificationReceipt)) == 1
        return
    results = [rig.append(item).result for item in (words, press)]
    before = db.dump()
    assert [rig.append(item).result for item in (words, press)] == results
    assert db.dump() == before
    if case.name == "changed_body":
        for changed in case.inputs["variants"]:
            outcome = rig.append(changed)
            assert outcome.result.status == "refused" and outcome.result.code == c.RefusalCode.CHANGED_BODY
            assert outcome.held is None
        assert {r.action_key: r.receipt_json for r in db.rows(m.ClarificationReceipt)} == {
            item.action.key: c.receipt_json(item) for item in (words, press)}
    else:
        assert rig.append(case.inputs["correction"]).result.status == "applied"
        corrected = db.dump()
        assert [rig.append(item).result for item in (words, press)] == results
        assert db.dump() == corrected and rig.row()["answer"] == "No: online only."


def correction_setup(rig, state):
    """D's full fixed correction state, including the previously missed retained cases."""
    rig.ready()
    prompt_copy(rig)
    own, other = v.answer_receipt("602"), v.answer_receipt("604", sender=v.OTHER)
    assert rig.append(own).result.status == rig.append(other).result.status == "applied"
    words = v.typed_receipt(" \u200b " if state == "press_blank_text" else v.ANSWER)
    if state.startswith("press"):
        assert rig.append(words).result.status == "retained"
    if state == "press_already_confirmed":
        assert rig.append(v.confirmation_receipt(words, action_id="cb-prior")).result.status == "applied"
    if "retired" in state:
        rig.db.store.save_presentation(v.presentation(2))
    return own, other, words


@pytest.mark.parametrize("case", cases("V12"), ids=lambda case: case.name)
def test_V12_correction_precedence_and_durable_privacy(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    if case.name.startswith("precedence_"):
        state = case.inputs["state"]
        own, other, words = correction_setup(rig, state)
        changes = dict(case.inputs["changes"])
        common = dict(intent="correct", supersedes=case.inputs["targets"], reason="Typo.")
        if "no_disposition" in state:
            common["disposition"] = None
        attempt = (v.confirmation_receipt(words, **common) if state.startswith("press") else
                   v.answer_receipt("603", " \u200b " if state == "blank_text" else "No: online only.", **common))
        if "message_id" in changes:
            changes["binding"] = replace(attempt.binding, message_id=changes.pop("message_id"))
        attempt = replace(attempt, **changes)
    else:
        # Names with two target terms must not change the setup's state.
        state = next(state for state in ("press_already_confirmed", "press_no_disposition", "press_blank_text",
                                        "press_retired", "no_disposition", "blank_text", "retired", "message", "press")
                     if case.name.startswith(state + "_"))
        own, other, words = correction_setup(rig, state)
        attempt = case.inputs["attempt"]
    before = db.store.load(rig.initial.stream).record()["events"]
    keys = {row.action_key for row in db.rows(m.ClarificationReceipt)}
    outcome = rig.append(attempt)
    assert outcome.result.status == case.expected["status"]
    if case.expected["code_guard"] is not None:
        code, guard = case.expected["code_guard"]
        assert (outcome.result.code.value, outcome.guard) == (code, guard)
    kept = {row.action_key for row in db.rows(m.ClarificationReceipt)}
    assert kept == keys | ({attempt.action.key} if case.expected["authoritative_key_kept"] else set())
    after = db.store.load(rig.initial.stream).record()["events"]
    assert after[:len(before)] == before  # never rewrite old history
    assert len(after) == len(before) + int(outcome.result.status == "applied")
    if not case.expected["authoritative_key_kept"]:
        assert outcome.held is None
        assert all(row.receipt_json != c.receipt_json(attempt) for row in db.rows(m.ClarificationReceipt))
        if case.expected.get("same_key_genuine_recovery"):
            genuine = replace(attempt, supersedes=(c.event_id(own),))
            recovered = rig.append(genuine)
            assert recovered.result.status in ("applied", "retained") and recovered.held == genuine
    rig.restart()
    assert db.store.load(rig.initial.stream).record()["events"][:len(before)] == before


@pytest.mark.parametrize("case", cases("V13"), ids=lambda case: case.name)
def test_V13_reopen_and_final_application_fences(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    rig.answer()
    before = db.store.load(rig.initial.stream).record()["events"]
    if case.name == "stale_reopen":
        assert rig.append(case.inputs["rival"]).result.status == "applied"
    elif case.name == "late_generation":
        db.store.save_presentation(v.presentation(2))
    if case.name == "second_confirmation":
        attempt = case.inputs["presses"][1]
    else:
        attempt = case.inputs.get("receipt", case.inputs.get("reopen"))
    outcome = rig.append(attempt)
    if case.name in ("fresh_reopen", "answer_after_reopen"):
        assert outcome.result.status == "applied" and rig.row()["state"] == "reopened"
        if case.name == "answer_after_reopen":
            assert rig.append(case.inputs["next"]).result.status == "applied"
            assert rig.row()["state"] == "answered"
    else:
        assert outcome.result.status == "retained"
        if case.name == "stale_reopen":
            assert outcome.result.code == c.RefusalCode.STALE_REOPEN
            assert c.event_id(case.inputs["rival"]) in rig.row()["active_event_ids"]
        elif "code" in case.expected:
            assert outcome.result.code.value == case.expected["code"]
        else:
            assert outcome.guard == case.expected["guard"]
    assert db.store.load(rig.initial.stream).record()["events"][:len(before)] == before
