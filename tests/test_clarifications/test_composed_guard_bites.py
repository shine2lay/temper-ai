"""Named guard mutations exercise actual composed stores, never recording ports."""

from dataclasses import replace

import pytest

from temper_ai.clarifications import caller as coordinator
from temper_ai.clarifications import contracts, delivery_store
from temper_ai.clarifications import models as m
from temper_ai.integrations.telegram import poller
from tests.test_clarifications import composition_vectors as v
from tests.test_clarifications import test_composed_transactions as composed
from tests.test_clarifications.test_caller_integration import Composition
from tests.test_clarifications.test_caller_integration import db as db
from tests.test_clarifications.test_coordinator import assert_refusal
from tests.test_clarifications.test_preparation_adapter import mutated_module

ADMISSION_CHECK = "and p.generation == loaded.generation(p.question_id) and not answered)"
WITHOUT_ADMISSION_CHECK = {
    "generation_2": "and not answered)",
    "answered": "and p.generation == loaded.generation(p.question_id))",
}
APPLICATION_FENCE = {"generation_2": "binding.stale", "confirmed_typed_action": "confirmation.once"}


def vector_case(vector, name):
    return next(case for case in composed.cases(vector) if case.name == name)


def events(rig):
    return rig.db.store.load(rig.initial.stream).record()["events"]


@pytest.mark.parametrize("guard", ("checked_source", "checked_candidate", "checked_report"))
def test_actual_consumption_refusal_has_its_specific_guard_bite(db, monkeypatch, guard):
    rig = Composition(db, monkeypatch)
    rig.answer()
    checked, context = rig.check(), rig.context()
    changes = {
        "checked_source": {"supplement": checked.supplement + " "},
        "checked_candidate": {"candidate_sha256": "0" * 64},
        "checked_report": {"report": {**checked.report, "meaning_status": "PASS"}},
    }
    supplied = replace(checked, **changes[guard])

    def call():
        return rig.coordinator.acknowledge_consumption(context, checked=supplied)

    name = "coordinator." + guard
    before = db.dump()
    assert_refusal(call, name)
    assert db.dump() == before and db.rows(m.ClarificationConsumption) == []
    reached = []
    require = coordinator._require

    def drop_one(ok, code, current):
        if current == name:
            reached.append(ok)
            return
        require(ok, code, current)

    monkeypatch.setattr(coordinator, "_require", drop_one)
    with pytest.raises(AssertionError, match="guard outcome: expected coordinator\\." + guard + ", got no refusal"):
        assert_refusal(call, name)
    assert reached == [False]
    assert len(db.rows(m.ClarificationConsumption)) == 1
    assert len(rig.provider.sent) == 2 and rig.ordinary == []


@pytest.mark.parametrize("mutant", (False, True), ids=("control", "admission_check_removed"))
@pytest.mark.parametrize("rival", ("generation_2", "answered"))
@pytest.mark.parametrize("kind", ("question", "prompt", "retry"))
def test_V07_atomic_admission_check_is_the_fence_after_a_pre_admission_rival(db, monkeypatch, kind, rival, mutant):
    """M2/B's locked eligibility read alone stops the send once the edge's pre-check has passed."""
    rig = Composition(db, monkeypatch)
    send_id = composed.pending(rig, monkeypatch, "prompt" if kind == "prompt" else "question")
    if kind == "retry":
        assert rig.ledger.start_attempt(send_id, expected_attempts=0, resend=False)[1]
    composed.commit_rival(rig, rival)
    if mutant:
        changed = mutated_module(monkeypatch, delivery_store, ADMISSION_CHECK, WITHOUT_ADMISSION_CHECK[rival])
        monkeypatch.setattr(delivery_store.ClarificationDeliveryStore, "start_attempt",
                            changed.ClarificationDeliveryStore.start_attempt)
    record = rig.ledger.send(send_id, stream=rig.initial.stream)
    calls = len(rig.provider.sent)
    rig.edge._send(record.intent, record, resend=kind == "retry")

    def check():
        attempts = rig.ledger.send(send_id, stream=rig.initial.stream).attempts
        composed.assert_no_forbidden_send(len(rig.provider.sent) - calls, attempts, int(kind == "retry"))

    if mutant:
        with pytest.raises(AssertionError, match="forbidden send after a pre-admission rival commit"):
            check()
        assert len(rig.provider.sent) - calls == 1
    else:
        check()


@pytest.mark.parametrize("mutant", (False, True), ids=("control", "final_fence_removed"))
@pytest.mark.parametrize("rival", ("generation_2", "confirmed_typed_action"))
def test_V07_final_application_fence_decides_over_capture_validation(db, monkeypatch, rival, mutant):
    """Capture validated while current; the rival lands before the store append (K5)."""
    rig = Composition(db, monkeypatch)
    rig.ready()
    words, press = v.pulled_updates()
    if rival == "confirmed_typed_action":
        assert rig.pull(words) == 0
        late = v.confirmation_receipt(action_id="cb-second")
    else:
        late = v.answer_receipt()
    reached = []
    refuse_unless = contracts._refuse_unless

    def drop_fence(ok, code, guard, where=""):
        if guard == APPLICATION_FENCE[rival]:
            reached.append(ok)
            return
        refuse_unless(ok, code, guard, where)

    def rival_commits():
        if rival == "confirmed_typed_action":
            assert rig.pull(press) == 0
        else:
            assert db.store.save_presentation(v.presentation(2))
        before.append(len(events(rig)))
        if mutant:
            monkeypatch.setattr(contracts, "_refuse_unless", drop_fence)

    before = []
    result = rig.append(late, after_capture=rival_commits).result
    added = len(events(rig)) - before[0]
    expected = vector_case("V07", "after_" + rival).expected["code"]

    def check():
        composed.assert_fenced_application(result.status, result.code and result.code.value, added, expected)

    if mutant:
        with pytest.raises(AssertionError, match="stale or duplicate action added a human event"):
            check()
        # Exactly one dropped refusal; later passing reads of the same guard
        # (history checks at the kept generation) are not the fence.
        assert reached.count(False) == 1 and (result.status, added) == ("applied", 1)
    else:
        check()


def test_V07_fences_keep_distinct_same_generation_genuine_answers(db, monkeypatch):
    """Clean control: the generation/confirmation fences are not first-answer-wins."""
    rig = Composition(db, monkeypatch)
    rig.ready()
    case = vector_case("V11", "same_text")
    for receipt in case.inputs["receipts"]:
        assert rig.append(receipt).result.status == "applied"
    assert {event["event_id"] for event in events(rig)} == case.expected["event_set"]
    assert {event["actor"]["ref"] for event in events(rig)} == set(case.expected["actors"])


@pytest.mark.parametrize("mutant", (False, True), ids=("control", "generation_check_reads_stale"))
def test_V07_m2_generation_check_is_the_single_fence_before_present(db, monkeypatch, mutant):
    rig = Composition(db, monkeypatch)
    rig.ready()
    assert db.store.save_presentation(v.presentation(2))
    expected = vector_case("V07", "generation_before_present").expected
    if mutant:
        monkeypatch.setattr(rig.transport_store, "current_generation", lambda stream_id, question_id: 1)
        with pytest.raises(AssertionError, match="M2 did not fence the superseded generation"):
            composed.assert_m2_single_fence(rig, (rig.context(ask=(v.Q,)),), expected)
    else:
        composed.assert_m2_single_fence(rig, (rig.context(ask=(v.Q,)),), expected)
    assert len(rig.provider.sent) == 1


@pytest.mark.parametrize("mutant", (False, True), ids=("control", "application_commit_suppressed"))
def test_V01_suppressed_application_commit_fails_the_revision_assertion(db, monkeypatch, mutant):
    """Plan V01 control: suppressing the actual store's application commit must fail
    the named before-acknowledgement revision assertion, not an arbitrary exception."""
    rig = Composition(db, monkeypatch)
    rig.ready()
    words, press = rig.data["updates"]
    assert rig.pull(words) == 0 and rig.offset() == "1002"
    rig.before_ack = rig.assert_confirmed_committed
    confirmed = rig.data["confirmed_receipt"].action.key
    if mutant:
        # The same suppression as B's own bite, applied to the actual composed store.
        monkeypatch.setattr(db.store, "_commit_receipt", lambda session, outcome: session.rollback())
        with pytest.raises(AssertionError, match="application commit before ack"):
            rig.pull(press)
        assert len(rig.observer_errors) == 1
        assert db.other().load(rig.initial.stream).revision == 1 and events(rig) == []
        assert confirmed not in rig.receipts() and len(rig.receipts()) == 1
    else:
        assert rig.pull(press) == 0 and rig.observer_errors == []
        assert db.other().load(rig.initial.stream).revision == 2 and rig.offset() == "1003"
        assert rig.receipts()[confirmed].status == "applied"
    assert rig.ordinary == [] and not rig.poller.running


@pytest.mark.parametrize("early_offset", (False, True), ids=("control", "early_offset_mutant"))
def test_real_poll_offset_order_has_a_prompt_observer_bite(db, monkeypatch, early_offset):
    rig = Composition(db, monkeypatch)
    rig.ready()
    rig.before_send = rig.assert_typed_committed
    if early_offset:
        changed = mutated_module(
            monkeypatch, poller, "        for update in updates:",
            "        store.set_state(OFFSET_KEY, str(top))\n        for update in updates:",
        )
        rig.poller = changed.Poller(rig.provider, rig.ordinary.append, timeout=0,
                                   clock=lambda: 1700000001, clarifications=rig.edge)
        with pytest.raises(AssertionError, match="typed offset advanced before prompt"):
            rig.pull(v.pulled_updates()[0])
        assert rig.offset() == "1002" and len(rig.provider.sent) == 1
        assert len(rig.observer_errors) == 1
    else:
        assert rig.pull(v.pulled_updates()[0]) == 0
        assert rig.offset() == "1002" and len(rig.provider.sent) == 2
        assert rig.observer_errors == []
    retained = rig.receipts()[rig.data["typed_receipt"].action.key]
    assert (retained.status, retained.code) == ("retained", "no_explicit_disposition")
    assert rig.ordinary == [] and rig.context().prior_revision == 1
