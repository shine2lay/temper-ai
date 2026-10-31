"""M4 E process races/crashes: real databases, no shared in-memory lock."""

from __future__ import annotations

from copy import deepcopy

import pytest

from temper_ai.clarifications import contracts as c
from temper_ai.clarifications import delivery_models as dm
from temper_ai.clarifications import models as m
from temper_ai.integrations.telegram import clarifications as e
from tests.test_clarifications import composition_scenarios as s
from tests.test_clarifications import composition_vectors as v
from tests.test_clarifications import test_store as persistence
from tests.test_clarifications.composition_process import Child
from tests.test_clarifications.test_caller_integration import Composition

db = persistence.db


def cases(vector):
    return next(item for item in v.vectors() if item.id == vector).cases


class BeforeAdmission(Exception):
    pass


# D/#241 fixed expectations the actual composition cannot realize. They are
# reported NOT_REALIZED, never as passes, and D's data stays unchanged (temper
# lead decision for #242): M3 save_presentation of a known ID is a touch that
# keeps revision and record digest, C checks only those, and C's accepted doc
# leaves the final eligibility fence to M2/B.
NOT_REALIZED = {("V07", "generation_before_present"): {"stale_coordinator_refusal": True}}


def commit_rival(rig, rival):
    """Commit an independent eligibility change: a genuine answer to a known copy, or generation 2."""
    if rival == "answered":
        rig.db.store.record_copy(c.PresentationBinding(rig.initial.stream.stream_id, v.Q,
                                                       v.presentation().presentation_id, 1, "500"))
        assert rig.append(v.answer_receipt()).result.status == "applied"
    else:
        assert rig.db.store.save_presentation(v.presentation(2))


def send_attempts(db):
    return sorted((row.send_id, row.attempt_count) for row in db.rows(dm.ClarificationSend))


def assert_no_forbidden_send(provider_calls, attempts, expected_attempts):
    assert (provider_calls, attempts) == (0, expected_attempts), "forbidden send after a pre-admission rival commit"


def assert_fenced_application(status, code, added_events, expected_code):
    assert (status, code, added_events) == ("retained", expected_code, 0), \
        "stale or duplicate action added a human event"


def assert_m2_single_fence(rig, snapshots, expected):
    """No coordinator refusal; M2 alone answers not_current, sending and writing nothing."""
    calls, attempts, before = len(rig.provider.sent), send_attempts(rig.db), rig.db.dump()
    for caller in snapshots:
        states = [result.state for result in rig.present(caller)]
        assert states == [expected["edge_state"]], "M2 did not fence the superseded generation"
    direct = rig.edge.present(v.presentation(), s.COMPOSITION_UNKNOWN, v.QUESTION_TEXT).state
    assert direct == expected["edge_state"], "M2 did not fence the superseded generation"
    assert len(rig.provider.sent) - calls == expected["sends"]
    assert send_attempts(rig.db) == attempts and rig.db.dump() == before


def pending(rig, monkeypatch, kind="question"):
    """Execute actual preparation/intent commit, then stop before first admission."""
    if kind == "prompt":
        rig.ready()
    else:
        rig.coordinator.prepare(rig.initial)

    def stop(*args, **kwargs):
        raise BeforeAdmission

    with monkeypatch.context() as held:
        held.setattr(rig.transport_store, "start_attempt", stop)
        with pytest.raises(BeforeAdmission):
            if kind == "prompt":
                rig.pull(v.pulled_updates()[0])
            else:
                rig.present()
    rows = rig.db.rows(dm.ClarificationSend)
    return next(row.send_id for row in rows if (row.send_id.startswith("c-")) == (kind == "prompt"))


@pytest.mark.parametrize("case", cases("V04"), ids=lambda case: case.name)
def test_V04_atomic_cross_process_admission(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    send_id = pending(rig, monkeypatch, case.inputs.get("kind", "question"))
    inputs = case.inputs
    if inputs.get("attempts", inputs["expected_attempts"]):
        assert rig.ledger.start_attempt(send_id, expected_attempts=0, resend=False)[1]
    if inputs.get("delivery"):
        rig.ledger.record_delivery(send_id, inputs["delivery"])
    if inputs.get("processes"):
        with Child(db, "attempt", boundary="read_attempt", send_id=send_id, resend=inputs["resend"]) as a, \
                Child(db, "attempt", boundary="read_attempt", send_id=send_id, resend=inputs["resend"]) as b:
            a.at("read_attempt")
            b.at("read_attempt")
            a.release()
            b.release()
            outcomes = [a.finish(), b.finish()]
        assert sorted(row[1] for row in outcomes) == list(case.expected["wins"])
        assert sum(row[3] for row in outcomes) == case.expected["provider_calls"]
        assert {row[2] for row in outcomes} == {case.expected["attempts"]}
    else:
        before = db.dump()
        record, won = rig.ledger.start_attempt(send_id, expected_attempts=inputs["expected_attempts"],
                                                resend=inputs["resend"])
        assert won is case.expected["won"]
        if won:
            rig.provider.send(int(v.CHAT), record.intent.text)
            assert record.attempts == case.expected["attempts"]
        else:
            assert db.dump() == before
    rig.restart()
    assert rig.ledger.send(send_id, stream=rig.initial.stream).attempts == case.expected.get("attempts", 1)


@pytest.mark.parametrize("case", cases("V05"), ids=lambda case: case.name)
def test_V05_all_copies_reverse_completion_and_uncertainty(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    send_id = pending(rig, monkeypatch, "prompt" if case.name == "prompt_retired_copies" else "question")
    if case.name in ("reverse_completion", "prompt_retired_copies"):
        with Child(db, "send", boundary="after_send", send_id=send_id, message_ids=[501]) as first:
            first.at("after_send")
            with Child(db, "send", send_id=send_id, resend=True, message_ids=[502]) as second:
                assert second.finish() == ["send", "sent", "502", 1]
            first.release()
            assert first.finish() == ["send", "sent", "501", 1]
        if case.name == "prompt_retired_copies":
            db.store.save_presentation(v.presentation(2))
        rig.restart()
        intent = rig.ledger.send(send_id, stream=rig.initial.stream).intent
        for mid in ("501", "502"):
            assert rig.transport_store.delivery(v.TRANSPORT, v.CHAT, mid).intent == intent
        assert {"501", "502"} <= rig.transport_store.copies(v.presentation().presentation_id)
        before = db.dump()
        rig.ledger.record_delivery(send_id, "502")
        assert db.dump() == before
    else:
        index = 1 if case.name == "attempt_commit_then_raise" else 2
        with Child(db, "send", boundary="after_commit", commit_index=index, send_id=send_id) as child:
            child.at("after_commit")
            child.close()  # real process dies after commit, before the method returns
        rig.restart()
        record = rig.ledger.send(send_id, stream=rig.initial.stream)
        assert record.attempts == 1
        # SendRecord states: delivered once an ID is kept; uncertain with an
        # attempt and no ID. "sent" is only the winning call's SendResult.
        assert record.state == ("uncertain" if index == 1 else "delivered")
        if index == 2:
            assert rig.transport_store.delivery(v.TRANSPORT, v.CHAT, "501").intent == record.intent
    calls = len(rig.provider.sent)
    record = rig.ledger.send(send_id, stream=rig.initial.stream)
    before = db.dump()
    rig.edge._send(record.intent, record, resend=False)
    assert len(rig.provider.sent) == calls
    if "replay_new_rows" in case.expected:
        assert db.dump() == before


@pytest.mark.parametrize("case", cases("V06"), ids=lambda case: case.name)
def test_V06_lost_copy_ordinary_route_then_explicit_reconciliation(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    send_id = pending(rig, monkeypatch)
    with Child(db, "send", boundary="after_send", send_id=send_id, message_ids=[503]) as child:
        child.at("after_send")
        child.close()
    rig.restart()
    words = v.pulled_updates(reply_to=v.LOST_COPY)[0]
    assert rig.pull(words) == 1 and len(rig.ordinary) == 1
    assert rig.receipts() == {} and rig.row()["active_event_ids"] == []
    if case.name == "K1_lost_copy":
        # This synthetic trusted control supplies verified external evidence; a
        # production caller still needs its own authority to reconcile delivery.
        rig.ledger.record_delivery(send_id, v.LOST_COPY)
        assert rig.pull(words, replay=True) == 0
        assert len(rig.receipts()) == 1 and len(rig.ordinary) == 1
        assert next(iter(rig.receipts().values())).status == "retained"
    elif case.name == "ordinary_dict_replay":
        rig.ledger.record_delivery(send_id, v.LOST_COPY)
        rig.provider.updates = [deepcopy(words)]
        batch = rig.edge.pull(rig.provider, None, timeout=0, allowed=[])
        with pytest.raises(c.ContractRefusal) as caught:
            batch.claim(words)  # saved dict is not the object in this provider pull
        assert caught.value.guard == "edge.pulled"
        assert rig.receipts() == {}
    else:
        rig.ledger.record_delivery(send_id, v.LOST_COPY)
        assert rig.transport_store.delivery(c.TransportNamespace("telegram", "7002"), v.CHAT, v.LOST_COPY) is None
        assert rig.transport_store.delivery(v.TRANSPORT, "-1002", v.LOST_COPY) is None
        db.store.save_presentation(v.presentation(2))
        other = e.SendIntent(v.presentation(2).presentation_id, v.presentation(2), v.QUESTION_TEXT)
        rig.ledger.save_send(other)
        with pytest.raises(c.ContractRefusal) as caught:
            rig.ledger.record_delivery(other.send_id, v.LOST_COPY)
        assert caught.value.guard == "delivery.occupied"


@pytest.mark.parametrize("case", cases("V07"), ids=lambda case: case.name)
def test_V07_last_application_fence_wins_over_capture(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    if case.name == "answered_before_present":
        rig.answer()
        before = len(rig.provider.sent)
        with pytest.raises(Exception) as caught:
            rig.present()
        assert caught.value.guard == case.expected["m1_guard"]
        assert len(rig.provider.sent) == before
        return
    if case.name == "generation_before_present":
        divergent = NOT_REALIZED["V07", case.name]
        assert {key: case.expected[key] for key in divergent} == divergent  # D data unchanged
        rig.ready()
        stale = rig.context(ask=(v.Q,))
        assert db.store.save_presentation(v.presentation(2))
        fresh = rig.context(ask=(v.Q,))
        assert (stale.prior_revision, stale.prior_record_sha256) == (fresh.prior_revision, fresh.prior_record_sha256)
        assert_m2_single_fence(rig, (stale, fresh), case.expected)
        return
    if case.name == "after_confirmed_typed_action":
        rig.ready()
        rig.pull(v.pulled_updates()[0])
        receipt = v.confirmation_receipt(action_id="cb-second")
        with Child(db, "append", boundary="cas", receipt=c.receipt_json(receipt)) as child:
            child.at("cas")
            rig.pull(v.pulled_updates()[1])
            events = len(db.store.load(rig.initial.stream).record()["events"])
            child.release()
            outcome = child.finish()
        added = len(db.store.load(rig.initial.stream).record()["events"]) - events
        assert (outcome[0], outcome[2], events) == ("append", 2, 1)
        assert_fenced_application(outcome[1], outcome[3], added, case.expected["code"])
        return
    kind = case.inputs.get("kind", "question")
    send_id = pending(rig, monkeypatch, "prompt" if kind == "prompt" else "question")
    if kind == "retry":
        assert rig.ledger.start_attempt(send_id, expected_attempts=0, resend=False)[1]
    after = case.name.startswith("after_")
    boundary = "before_send" if after else "cas"
    with Child(db, "send", boundary=boundary, send_id=send_id, resend=kind == "retry") as child:
        child.at(boundary)
        # Before: the pending send's final admission has not acquired its
        # transaction. After: admitted, network send not yet made.
        commit_rival(rig, case.inputs["rival_commit"])
        child.release()
        outcome = child.finish()
    if after:
        assert outcome == ["send", "sent", "501", 1]
        events = len(db.store.load(rig.initial.stream).record()["events"])
        result = rig.append(v.answer_receipt(message_id="501")).result
        added = len(db.store.load(rig.initial.stream).record()["events"]) - events
        assert_fenced_application(result.status, result.code and result.code.value, added, case.expected["code"])
    else:
        attempts = rig.ledger.send(send_id, stream=rig.initial.stream).attempts
        assert_no_forbidden_send(outcome[3], attempts, int(kind == "retry"))


@pytest.mark.parametrize("case", cases("V11"), ids=lambda case: case.name)
def test_V11_two_real_processes_keep_both_histories(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    if case.name == "first_create":
        profiles = case.inputs["candidates"]
        with Child(db, "prepare", boundary="create", profile=profiles[0]) as a, \
                Child(db, "prepare", boundary="create", profile=profiles[1]) as b:
            a.at("create")
            b.at("create")
            a.release()
            b.release()
            results = [a.finish(), b.finish()]
        assert all(row[0] == "prepare" for row in results)
        rig.restart()
        ids = {row["question_id"] for row in db.store.load(rig.initial.stream).record()["questions"]}
        assert set(case.expected["question_ids_include"]) <= ids
        return
    rig.ready()
    first, second = case.inputs["receipts"]
    with Child(db, "append", boundary="cas", receipt=c.receipt_json(first)) as a, \
            Child(db, "append", boundary="cas", receipt=c.receipt_json(second)) as b:
        a.at("cas")
        b.at("cas")
        a.release()
        b.release()
        outcomes = [a.finish(), b.finish()]
    assert sorted(row[2] for row in outcomes) == [2, 3]
    assert all(row[1] == "applied" for row in outcomes)
    rig.restart()
    events = db.store.load(rig.initial.stream).record()["events"]
    assert {event["event_id"] for event in events} == case.expected["event_set"]
    assert {event["actor"]["ref"] for event in events} == set(case.expected["actors"])
    assert rig.row()["state"] == case.expected["state"]
    assert len(db.rows(dm.ClarificationIngress)) == len(rig.receipts()) == 2


@pytest.mark.parametrize("case", cases("V14"), ids=lambda case: case.name)
def test_V14_process_death_at_named_transaction_and_effect_boundaries(db, monkeypatch, case):
    rig = Composition(db, monkeypatch)
    point = case.name
    kwargs = {}
    if point.startswith("consumption.") or point.startswith("consumer."):
        rig.answer()
        operation = "ack"
        boundary = ("consumer_effect" if point.startswith("consumer.") else
                    "before_commit" if point.endswith("before_commit") else "after_commit")
    elif point.startswith("attempt.") or point.startswith("delivery."):
        send_id = pending(rig, monkeypatch)
        operation, boundary = "send", "after_commit"
        kwargs = {"send_id": send_id, "commit_index": 2 if point.startswith("delivery.") else 1}
    elif point.startswith("intent."):
        rig.coordinator.prepare(rig.initial)
        operation, boundary = "present", "after_commit"
        kwargs = {"commit_index": 2}  # presentation then immutable intent
    else:
        rig.ready()
        rig.pull(v.pulled_updates()[0])
        operation = "pull"
        boundary = {"ingress.before_commit": "before_commit", "ingress.after_commit_before_return": "after_commit",
                    "callback.before_ack": "before_ack", "poller.before_offset": "before_offset"}[point]
        kwargs = {"update": v.pulled_updates()[1]}
    before, offset = db.dump(), rig.offset()
    with Child(db, operation, boundary=boundary, **kwargs) as child:
        child.at(boundary)
        child.close()
    rig.restart()
    if point == "intent.after_commit":
        record = rig.ledger.send(v.presentation().presentation_id, stream=rig.initial.stream)
        assert record.attempts == 0 and record.state == "pending"
    elif point == "attempt.after_commit_before_return":
        record = rig.ledger.send(kwargs["send_id"], stream=rig.initial.stream)
        assert record.attempts == 1 and record.state == "uncertain"
        assert rig.provider.sent == []
    elif point == "delivery.after_commit_before_return":
        assert rig.transport_store.delivery(v.TRANSPORT, v.CHAT, "501") is not None
        assert "501" in rig.transport_store.copies(v.presentation().presentation_id)
    elif operation == "ack":
        committed = point == "consumption.after_commit_before_return"
        assert len(db.rows(m.ClarificationConsumption)) == int(committed)
        assert rig.coordinator.recover(rig.initial).supplement.consumed is committed
        checked = rig.check()
        assert rig.coordinator.acknowledge_consumption(rig.context(), checked=checked) is not committed
    else:
        assert rig.offset() == offset  # no premature offset despite written receipt/event
        if boundary == "before_commit":
            assert db.dump() == before
        else:
            assert len(db.store.load(rig.initial.stream).record()["events"]) == 1
            assert rig.transport_store.receipt(v.confirmation_receipt().action.key) == v.confirmation_receipt()
        assert rig.pull(v.pulled_updates()[1]) == 0
        assert rig.context().prior_revision == 2 and rig.offset() == "1003"
        assert len(db.rows(dm.ClarificationIngress)) == 2
    assert rig.ordinary == [] and not rig.poller.running
