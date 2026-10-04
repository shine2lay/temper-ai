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
