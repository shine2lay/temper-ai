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
                                              "pi_team_acts", "pi_team_outcomes",
                                              "pi_team_requests", "pi_team_trials",
                                              "pi_team_versions", "pi_turns", "pi_waits"]


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


def test_a_take_over_skips_a_newer_attempts_turn_and_still_fences_an_older_ones(led):
    """SW-84: attempt a2 takes over while a3, which started after it, is mid-turn. a3's turn
    is its live work: same epoch, still running, its box never stopped, no recovery wait,
    and its own fenced writes still land. In another of the run's teams a1, older than a2,
    was cut off mid-turn: that turn is fenced and put to the owner as before."""
    side = "side"
    newer_p, _ = _attach(led, attempt="a3")
    led.post(RUN, HOST, ROLE, "for the newer attempt")
    live, _ = _claim(led, "a3")
    assert led.record_box(live["turn_id"], live["epoch"], "pi-box-a3")
    older_p, _ = led.attach_participant(RUN, side, ROLE, session_root="/state/run-1/side",
                                        pin={"model": "m"}, attempt_id="a1")
    led.post(RUN, side, ROLE, "for the older attempt")
    cut_off, _ = led.claim_turn(RUN, side, attempt_id="a1")
    assert led.record_box(cut_off["turn_id"], cut_off["epoch"], "pi-box-a1")
    stopped: list[str] = []

    def stop_box(name):
        stopped.append(name)
        return NO_BOX

    def newer_than_a2():
        return {"a3"}

    assert led.take_over(RUN, HOST, "a2", stop_box, newer_attempts=newer_than_a2) == []
    [still] = led.interrupted_turns(RUN, HOST)
    assert (still["turn_id"], still["state"], still["epoch"]) == (
        live["turn_id"], "running", live["epoch"]), "the newer attempt's turn is untouched"
    assert stopped == [], "the newer attempt's box is never stopped"
    assert led.open_waits(RUN, HOST) == [], "no recovery wait for a live turn"
    assert led.participant(newer_p["participant_id"])["state"] != "uncertain"
    assert led.mark_effect(live["turn_id"], "intent", epoch=live["epoch"]), (
        "the newer attempt's fence still holds its own writes")

    [(cut, wait)] = led.take_over(RUN, side, "a2", stop_box, newer_attempts=newer_than_a2)
    assert (cut["turn_id"], cut["state"], cut["epoch"]) == (
        cut_off["turn_id"], "uncertain", cut_off["epoch"] + 1)
    assert stopped == ["pi-box-a1"]
    assert wait["kind"] == "recovery"
    assert led.participant(older_p["participant_id"])["state"] == "uncertain"
    assert not led.mark_effect(cut_off["turn_id"], "intent", epoch=cut_off["epoch"]), (
        "the older attempt's late write fails its fence")


def test_cancel_closes_every_open_wait(led):
    _attach(led)
    led.open_wait(RUN, HOST, "owner", {}, "a1")
    led.open_wait(RUN, HOST, "stalled", {}, "a1")
    assert len(led.cancel_open_waits(RUN, HOST, "a1", "run cancelled")) == 2
    assert led.open_waits(RUN, HOST) == []
    assert {w["state"] for w in led.snapshot(RUN)["waits"]} == {"cancelled"}
