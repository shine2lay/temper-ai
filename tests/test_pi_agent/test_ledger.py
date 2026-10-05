"""The Pi step's ledger on a private SQLite file: participants, delivery, turns, waits."""

from __future__ import annotations

import threading

import pytest
import sqlalchemy as sa

from temper_ai.pi_agent.ledger import TABLES, Ledger, LedgerConflict, gate_name_for

RUN, HOST, ROLE = "run-1", "talk", "scout"
NO_BOX = {"confirmed": True}


@pytest.fixture
def led(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = Ledger(engine)
    ledger.ensure()
    yield ledger
    engine.dispose()


def _attach(led, role=ROLE, attempt="a1"):
    return led.attach_participant(RUN, HOST, role, session_root="/state/run-1/talk",
                                  pin={"model": "m"}, attempt_id=attempt)


def _claim(led, attempt="a1"):
    return led.claim_turn(RUN, HOST, attempt_id=attempt)


def test_tables_are_pi_prefixed():
    assert sorted(t.name for t in TABLES) == ["pi_messages", "pi_participants", "pi_reviews",
                                              "pi_team_acts", "pi_turns", "pi_waits"]


def test_a_participant_is_attached_once_with_one_session(led):
    p, created = _attach(led)
    again, created2 = _attach(led, attempt="a2")
    assert created and not created2
    assert again["participant_id"] == p["participant_id"]
    assert again["session_id"] == p["session_id"]
    assert p["session_dir"] == f"/state/run-1/talk/{p['participant_id']}/sessions"


def test_delivery_is_idempotent_and_never_drops(led):
    p, _ = _attach(led)
    m1 = led.post(RUN, HOST, ROLE, "hello", dedupe_key="k1")
    m2 = led.post(RUN, HOST, ROLE, "hello", dedupe_key="k1")
    assert m2["duplicate"] and m2["message_id"] == m1["message_id"]
    with pytest.raises(LedgerConflict):
        led.post(RUN, HOST, ROLE, "a different hello", dedupe_key="k1")
    lost = led.post(RUN, HOST, "nobody", "to no one")
    assert (lost["state"], lost["undelivered_reason"]) == ("undelivered", "recipient_unknown")
    assert [m["body"] for m in led.pending_for(p["participant_id"])] == ["hello"]


def test_a_turn_takes_every_pending_message_and_none_starts_while_a_wait_is_open(led):
    _attach(led)
    led.post(RUN, HOST, ROLE, "one")
    led.post(RUN, HOST, ROLE, "two")
    turn, batch = _claim(led)
    assert [m["body"] for m in batch] == ["one", "two"] and turn["turn_no"] == 1
    assert _claim(led) is None, "the participant is busy"
    res = led.finish_turn(turn["turn_id"], epoch=turn["epoch"], output="ok",
                          model_call_ids=["c1"], worker={},
                          ask_owner={"question": "next?", "options": ["done"]}, attempt_id="a1")
    wait = res["wait"]
    assert wait["gate_name"] == gate_name_for(HOST, wait["wait_id"])
    led.post(RUN, HOST, ROLE, "three")
    assert _claim(led) is None, "no turn while the owner is asked"


def test_a_decision_applies_exactly_once(led):
    p, _ = _attach(led)
    wait = led.open_wait(RUN, HOST, "owner", {"participant_id": p["participant_id"]}, "a1")
    results: list[bool] = []
    barrier = threading.Barrier(8)

    def decide(i):
        barrier.wait()
        results.append(led.decide_wait(wait["wait_id"], {"owner": "message"}, f"a{i}",
                                       deliveries=[(ROLE, "the reply")]))
    threads = [threading.Thread(target=decide, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 7 + [True]
    assert [m["body"] for m in led.pending_for(p["participant_id"])] == ["the reply"]
    assert led.open_waits(RUN, HOST) == []


def test_turn_numbers_never_repeat_after_a_failed_turn(led):
    _attach(led)
    first = led.post(RUN, HOST, ROLE, "one")
    t1, _ = _claim(led)
    assert led.fail_turn(t1["turn_id"], "boom", [], epoch=t1["epoch"])
    opened = led.open_recovery_for_failed(RUN, HOST, "a2")
    assert len(opened) == 1 and opened[0]["kind"] == "recovery"
    assert opened[0]["subject"]["options"] == ["retry", "stop"], "a failed turn: retry or stop"
    assert led.decide_wait(opened[0]["wait_id"], {"recovery": "retry"}, "a2",
                           recovery=("retry", t1["turn_id"]))
    t2, batch = _claim(led, "a2")
    assert t2["turn_no"] == 2 and t2["retry_of"] == t1["turn_id"]
    assert [(m["message_id"], m["body"], m["delivery_count"]) for m in batch] == [
        (first["message_id"], "one", 2)], "the same message again, never a new copy"


def test_a_running_turn_found_at_start_becomes_uncertain_with_a_recovery_wait(led):
    p, _ = _attach(led)
    led.post(RUN, HOST, ROLE, "one")
    t1, _ = _claim(led)
    assert led.mark_effect(t1["turn_id"], "intent", epoch=t1["epoch"])
    [(cut, wait)] = led.take_over(RUN, HOST, "a2", lambda name: NO_BOX)
    assert cut["turn_id"] == t1["turn_id"] and cut["state"] == "uncertain"
    assert wait["subject"]["effect_state"] == "intent"
    assert "may have acted" in wait["subject"]["question"]
    assert led.interrupted_turns(RUN, HOST) == []
    assert led.participant(p["participant_id"])["state"] == "uncertain"


def test_cancel_closes_every_open_wait(led):
    _attach(led)
    led.open_wait(RUN, HOST, "owner", {}, "a1")
    led.open_wait(RUN, HOST, "stalled", {}, "a1")
    assert len(led.cancel_open_waits(RUN, HOST, "a1", "run cancelled")) == 2
    assert led.open_waits(RUN, HOST) == []
    assert {w["state"] for w in led.snapshot(RUN)["waits"]} == {"cancelled"}
