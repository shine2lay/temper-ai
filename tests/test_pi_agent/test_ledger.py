"""The Pi step's ledger on a private SQLite file: participants, delivery, turns, waits."""

from __future__ import annotations

import threading

import pytest
import sqlalchemy as sa

from temper_ai.pi_agent.ledger import TABLES, Ledger, gate_name_for

RUN, HOST, ROLE = "run-1", "talk", "scout"


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


def test_tables_are_pi_prefixed():
    assert sorted(t.name for t in TABLES) == ["pi_messages", "pi_participants", "pi_turns",
                                              "pi_waits"]


def test_a_participant_is_attached_once_with_one_session(led):
    p, created = _attach(led)
    again, created2 = _attach(led, attempt="a2")
    assert created and not created2
    assert again["participant_id"] == p["participant_id"]
    assert again["session_id"] == p["session_id"]
    assert p["session_dir"] == f"/state/run-1/talk/{p['participant_id']}/sessions"


def test_delivery_is_idempotent_and_never_drops(led):
    p, _ = _attach(led)
    m1 = led.post(RUN, HOST, ROLE, "owner", "hello", dedupe_key="k1")
    m2 = led.post(RUN, HOST, ROLE, "owner", "hello", dedupe_key="k1")
    assert m2["duplicate"] and m2["message_id"] == m1["message_id"]
    lost = led.post(RUN, HOST, "nobody", "owner", "to no one")
    assert lost["state"] == "undeliverable"
    assert [m["body"] for m in led.pending_for(p["participant_id"])] == ["hello"]


def test_a_turn_takes_every_pending_message_and_none_starts_while_a_wait_is_open(led):
    p, _ = _attach(led)
    pid = p["participant_id"]
    led.post(RUN, HOST, ROLE, "owner", "one")
    led.post(RUN, HOST, ROLE, "owner", "two")
    turn, batch = led.start_turn(pid, "a1")
    assert [m["body"] for m in batch] == ["one", "two"] and turn["turn_no"] == 1
    assert led.start_turn(pid, "a1") is None, "the participant is busy"
    res = led.finish_turn(turn["turn_id"], output="ok", model_call_ids=["c1"], worker={},
                          ask_owner={"question": "next?", "options": ["done"]}, attempt_id="a1")
    wait = res["wait"]
    assert wait["gate_name"] == gate_name_for(HOST, wait["wait_id"])
    led.post(RUN, HOST, ROLE, "owner", "three")
    assert led.start_turn(pid, "a1") is None, "no turn while the owner is asked"


def test_a_decision_applies_exactly_once(led):
    p, _ = _attach(led)
    wait = led.open_wait(RUN, HOST, "owner", {"participant_id": p["participant_id"]}, "a1")
    results: list[bool] = []
    barrier = threading.Barrier(8)

    def decide(i):
        barrier.wait()
        results.append(led.decide_wait(wait["wait_id"], {"owner": "message"}, f"a{i}",
                                       deliveries=[(ROLE, "owner", "the reply")]))
    threads = [threading.Thread(target=decide, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 7 + [True]
    assert [m["body"] for m in led.pending_for(p["participant_id"])] == ["the reply"]
    assert led.open_waits(RUN, HOST) == []


def test_turn_numbers_never_repeat_after_a_failed_turn(led):
    p, _ = _attach(led)
    pid = p["participant_id"]
    led.post(RUN, HOST, ROLE, "owner", "one")
    t1, _ = led.start_turn(pid, "a1")
    led.fail_turn(t1["turn_id"], "boom", [])
    opened = led.open_recovery_for_failed(RUN, HOST, "a2")
    assert len(opened) == 1 and opened[0]["kind"] == "recovery"
    assert led.decide_wait(opened[0]["wait_id"], {"recovery": "retry"}, "a2",
                           deliveries=[(ROLE, "owner", "one")],
                           turn_state=(t1["turn_id"], "superseded"),
                           participant_states=[(pid, "idle")])
    t2, batch = led.start_turn(pid, "a2")
    assert t2["turn_no"] == 2 and [m["body"] for m in batch] == ["one"]


def test_a_running_turn_found_at_start_becomes_uncertain_with_a_recovery_wait(led):
    p, _ = _attach(led)
    led.post(RUN, HOST, ROLE, "owner", "one")
    t1, _ = led.start_turn(p["participant_id"], "a1")
    led.mark_effect(t1["turn_id"], "intent")
    [cut] = led.interrupted_turns(RUN, HOST)
    wait = led.mark_uncertain(cut, "a2", why="the service stopped during the turn")
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
