"""Restart and Resume: the same run and the same Pi session come back; a cut-off or failed
turn is never re-run without the owner's decision."""

from __future__ import annotations

import sqlalchemy as sa

from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox


def _crash(pi) -> str:
    out = sup.crash_child(pi.url, pi.tmp, "pi_talk", pi.ws, pi.box_json)
    return out["execution_id"]


def test_a_worker_killed_mid_turn_comes_back_as_the_same_run_and_session(pi):
    eid = _crash(pi)
    before = sup.ledger().snapshot(eid)
    assert [t["state"] for t in before["turns"]] == ["running"]
    assert [t["effect_state"] for t in before["turns"]] == ["intent"]
    session_id = before["participants"][0]["session_id"]

    picked = sup.restart_service()
    assert eid in picked["marked"] and eid in picked["picked"]
    rec = sup.open_wait(eid, "recovery")
    assert len(sup.attempts(eid)) == 2, "picked up as a new attempt of the same run"
    agents = sup.turn_agents(eid)
    assert len(agents) == 1
    end = sup.agent_end(eid, agents[0]["id"])
    assert end["type"] == "agent.failed", "the cut-off turn is closed red, not left running"
    assert FakeBox.STARTS == [], "nothing was re-run before the owner decided"
    turn = sup.ledger().snapshot(eid)["turns"][0]
    assert turn["state"] == "uncertain"
    assert "may have acted" in rec["subject"]["question"]

    assert sup.approve(pi.client, eid, rec["gate_name"], "retry").status_code == 200
    owner = sup.open_wait(eid, "owner")
    snap = sup.ledger().snapshot(eid)
    assert len(snap["participants"]) == 1
    assert [s["session_id"] for s in FakeBox.STARTS] == [session_id]
    agents = sup.turn_agents(eid)
    assert [a["data"]["pi_turn"]["session_id"] for a in agents] == [session_id] * 2
    assert [t["state"] for t in snap["turns"]] == ["superseded", "completed"]
    # The role was bound by the first start (in the killed worker); the retry reopened that
    # session without binding again.
    assert FakeBox.STARTS[0]["commands"].count("prompt") == 2
    sup.approve(pi.client, eid, owner["gate_name"], "done")
    assert sup.wait_ended(eid, 2)[-1]["status"] == "completed"


def test_an_owner_answer_given_while_the_run_is_down_is_used_on_pick_up(pi, monkeypatch):
    """The Pi step's owner wait lets the worker go (C7), so a worker that dies while the run
    waits loses nothing: the run is not marked interrupted, an answer given while nothing
    can act on it is kept, and start-up carries the run on from the parked step -- the
    settled turn is not run again, the answer starts the next turn in the same session, and
    nothing is asked twice."""
    from temper_ai.api import routes
    from temper_ai.runner import parked

    out = sup.crash_child(pi.url, pi.tmp, "pi_talk", pi.ws, pi.box_json, die_at="owner_wait")
    eid = out["execution_id"]
    w = sup.open_wait(eid, "owner")
    assert w["wait_id"] == out["killing"]["wait_id"]
    assert w["ask_event_id"] == out["killing"]["ask_event_id"]
    session_id = sup.ledger().snapshot(eid)["participants"][0]["session_id"]
    starts_before = len(FakeBox.STARTS)

    marked = sup.reconcile_only()
    assert eid not in [m["execution_id"] for m in marked], "parked: no worker was lost"
    with monkeypatch.context() as down:  # the answer lands, then the server stops
        down.setattr(routes, "_carry_on_parked", lambda execution_id, by: False)
        r = pi.client.post(f"/api/runs/{eid}/approve/{w['gate_name']}",
                           json={"response": "What was the word?",
                                 "event_id": w["ask_event_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["needs_resume"] is True, "kept for start-up, not lost"
    assert len(FakeBox.STARTS) == starts_before, "nothing ran while no worker did"

    assert parked.carry_on_at_startup() == [eid]
    # The kept answer is used: a new turn, then a new wait (the first closes as decided).
    owner2 = sup.open_wait(eid, "owner", other_than=w["wait_id"])
    snap = sup.ledger().snapshot(eid)
    assert "What was the word?" in [m["body"] for m in snap["messages"]]
    assert [s["session_id"] for s in FakeBox.STARTS[starts_before:]] == [session_id]
    first = next(x for x in snap["waits"] if x["wait_id"] == w["wait_id"])
    assert first["state"] == "decided"
    sup.approve(pi.client, eid, owner2["gate_name"], "done")
    assert sup.wait_ended(eid, 3)[-1]["status"] == "completed"
    ev = next(e for e in sup.events(eid) if e["id"] == w["ask_event_id"])
    assert ev["data"].get("gate_used_at"), "used once the step completed"
    assert parked.carry_on_at_startup() == [], "carried on once"


def test_changed_settings_refuse_to_reopen_the_session(pi):
    eid = _crash(pi)
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import participants

    with get_database().engine.begin() as conn:
        row = conn.execute(sa.select(participants.c.participant_id, participants.c.pin)).first()
        pin = {**row.pin, "model": "another-model"}
        conn.execute(participants.update().where(
            participants.c.participant_id == row.participant_id).values(pin=pin))
    sup.restart_service()
    assert sup.wait_ended(eid, 2)[-1]["status"] == "failed"
    assert FakeBox.STARTS == []
    assert len(sup.turn_agents(eid)) == 1
    said = [e["type"] for e in sup.events(eid) if "settings changed" in str(e["data"])]
    assert said, "the refusal says why"
    assert sup.node_status(eid, "talk")[-1] == "failed"


def test_resume_after_a_failed_turn_asks_the_owner_first(pi):
    FakeBox.behaviour = "provider_error"
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    assert sup.wait_ended(eid)[-1]["status"] == "failed"
    assert len(FakeBox.STARTS) == 1
    FakeBox.behaviour = "answer"
    r = pi.client.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    rec = sup.open_wait(eid, "recovery")
    assert len(FakeBox.STARTS) == 1, "the Resume itself re-ran nothing"
    assert "failed" in rec["subject"]["question"]
    sup.approve(pi.client, eid, rec["gate_name"], "retry")
    owner = sup.open_wait(eid, "owner")
    snap = sup.ledger().snapshot(eid)
    assert [t["state"] for t in snap["turns"]] == ["superseded", "completed"]
    assert len({s["session_id"] for s in FakeBox.STARTS}) == 1
    sup.approve(pi.client, eid, owner["gate_name"], "done")
    assert sup.wait_ended(eid, 2)[-1]["status"] == "completed"


def test_a_failed_turn_is_answered_retry_or_stop_never_accept(pi):
    """R2 N1, a change from L2: a turn that failed visibly is never kept as if it had
    finished. Its recovery wait offers retry or stop. An 'accept' names neither: nothing is
    decided (no stop by default either) and the owner is asked again at a new wait for the
    same turn (M3 F1); a 'stop' there stops the step, red."""
    FakeBox.behaviour = "provider_error"
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    assert sup.wait_ended(eid)[-1]["status"] == "failed"
    assert pi.client.post(f"/api/runs/{eid}/resume", json={}).status_code == 200
    rec = sup.open_wait(eid, "recovery")
    assert rec["subject"]["options"] == ["retry", "stop"]
    assert "accept" not in rec["subject"]["question"]
    sup.approve(pi.client, eid, rec["gate_name"], "accept")
    again = sup.open_wait(eid, "recovery", other_than=rec["wait_id"])
    assert again["subject"]["turn_id"] == rec["subject"]["turn_id"]
    assert again["subject"]["options"] == ["retry", "stop"]
    snap = sup.ledger().snapshot(eid)
    assert [t["state"] for t in snap["turns"]] == ["failed"]
    decided = {w["wait_id"]: (w["decision"] or {}).get("recovery") for w in snap["waits"]}
    assert decided[rec["wait_id"]] == "invalid"

    sup.approve(pi.client, eid, again["gate_name"], "stop")
    sup.wait_for(lambda: sup.attempts(eid)[-1]["status"] == "failed",
                 what=f"the stop to end {eid}'s step")
    assert len(FakeBox.STARTS) == 1, "nothing ran again"
    snap = sup.ledger().snapshot(eid)
    assert [t["state"] for t in snap["turns"]] == ["failed"]
    assert snap["participants"][0]["state"] == "failed"
    decided = {w["wait_id"]: (w["decision"] or {}).get("recovery") for w in snap["waits"]}
    assert decided[again["wait_id"]] == "stop"
