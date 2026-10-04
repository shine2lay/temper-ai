"""Pi runs in in-process mode: an approval lets go of the worker thread, the answer carries
the run on through Resume's own path (temper_ai/runner/parked.py)."""

from __future__ import annotations

from datetime import timedelta

from temper_ai.shared.clock import utcnow
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw


def _gate_checkpoints(client, eid: str) -> list[dict]:
    r = client.get(f"/api/runs/{eid}/checkpoints")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body.get("checkpoints", body) if isinstance(body, dict) else body
    return [c for c in rows if c.get("event_type") == "gate_parked"]


def test_a_pi_gate_lets_go_of_the_worker_and_the_answer_carries_it_on(pw_run):
    c = pw_run.client
    eid = sup.start(c, "pw_after_pi", pw_run.ws)
    pw.finish_pi(c, eid)
    first = pw.wait_parked(pw_run.state, eid)

    # Saved where it waits, with the wait's own id; no thread holds the run.
    gate = pw.open_gate(c, eid, "check")
    assert pw.parked(first)["event_id"] == gate["event_id"]
    assert pw.parked(first)["path"] == "check" and pw.parked(first)["round"] == 1
    assert [cp["id"] for cp in _gate_checkpoints(c, eid)] == [gate["event_id"]]
    assert eid not in pw_run.state.running and pw.run_threads(eid) == []

    # The run shows "waiting on you".
    seen = pw.detail(c, eid)
    assert seen["status"] == "waiting" and seen.get("waiting_on_you") is True
    assert pw.listed(c, eid)["status"] == "waiting"

    r = pw.approve(c, eid, "check", event_id=gate["event_id"], request_id="tab-1")
    assert r.status_code == 200, r.text
    assert r.json()["carries_on"] is True and r.json()["needs_resume"] is False
    attempts = pw.wait_ended(eid, 2)
    assert [a["status"] for a in attempts] == ["parked", "completed"]

    # Nothing finished ran again: one brief, one Pi turn, the gated step once, then ship.
    assert pw.RAN == {"brief": 1, "check": 1, "ship": 1}
    assert len(FakeBox.STARTS) == 1
    # The new attempt used the same wait: answered once, used once, never asked again.
    waits = pw.waits(eid, "check")
    assert len(waits) == 1 and waits[0]["status"] == "approved"
    assert waits[0]["data"].get("gate_used_at")
    assert pw.detail(c, eid)["status"] == "completed"


def test_a_first_node_wait_resumes_and_is_waited_on_again_not_asked_twice(pw_run):
    """C6: nothing has run and nothing is checkpointed, yet Resume starts the run again from
    its first node, which waits on the same approval it had opened."""
    c = pw_run.client
    eid = sup.start(c, "pw_first", pw_run.ws)
    first = pw.wait_parked(pw_run.state, eid)
    asked = pw.open_gate(c, eid, "ask")
    assert pw.parked(first)["event_id"] == asked["event_id"]
    assert pw.RAN == {} and FakeBox.STARTS == []

    r = c.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    second = pw.wait_parked(pw_run.state, eid, n_attempts=2)
    assert pw.parked(second)["event_id"] == asked["event_id"]
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "waiting"]
    assert len(pw.waits(eid, "ask")) == 1, "the same wait, not a second one"
    assert [cp["id"] for cp in _gate_checkpoints(c, eid)] == [asked["event_id"]]

    r = pw.approve(c, eid, "ask", event_id=asked["event_id"])
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    pw.finish_pi(c, eid)
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "completed"]
    assert pw.RAN == {"ask": 1, "audit": 1} and len(FakeBox.STARTS) == 1


def test_a_first_node_pi_step_is_handed_back_by_resume(pw_run):
    """C6: Resume hands a first-node Pi step back to the step, as it hands any node back.
    (L2's own rule still refuses a Pi step as a first node, so it fails again the same way.)"""
    c = pw_run.client
    eid = sup.start(c, "pi_first", pw_run.ws)
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    r = c.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    attempts = pw.wait_ended(eid, 2)
    assert [a["status"] for a in attempts] == ["failed", "failed"]
    assert sup.node_status(eid, "talk").count("failed") == 2, "the Pi step ran in each attempt"
    assert FakeBox.STARTS == []


def test_resume_with_no_checkpoint_starts_a_pi_run_again_and_not_any_other(pw_run):
    c = pw_run.client
    pi_run = sup.start(c, "pw_fails_first", pw_run.ws)
    plain = sup.start(c, "plain_fails_first", pw_run.ws)
    pw.wait_ended(pi_run, 1)
    pw.wait_ended(plain, 1)

    r = c.post(f"/api/runs/{plain}/resume", json={})
    assert r.status_code == 400
    assert r.json()["detail"] == "No checkpoints found \u2014 nothing to resume from"

    r = c.post(f"/api/runs/{pi_run}/resume", json={})
    assert r.status_code == 200, r.text
    pw.wait_ended(pi_run, 2)
    assert pw.RAN["first"] == 2, "the first step ran again"


def test_a_gate_in_a_workflow_without_a_pi_step_holds_its_worker_as_before(pw_run):
    c = pw_run.client
    eid = sup.start(c, "plain_gate", pw_run.ws)
    gate = pw.open_gate(c, eid, "check")
    attempt = pw.attempts(eid)[-1]
    assert attempt["status"] == "running" and pw.parked(attempt) is None
    assert eid in pw_run.state.running and pw.run_threads(eid)
    assert _gate_checkpoints(c, eid) == []
    r = pw.approve(c, eid, "check", event_id=gate["event_id"])
    assert r.status_code == 200 and "carries_on" not in r.json(), r.text
    assert [a["status"] for a in pw.wait_ended(eid, 1)] == ["completed"]


def test_each_wait_lets_go_with_its_own_checkpoint_and_old_answers_get_409s(pw_run):
    c = pw_run.client
    eid = sup.start(c, "pw_two_gates", pw_run.ws)
    pw.wait_parked(pw_run.state, eid)
    first = pw.open_gate(c, eid, "first")

    r = pw.approve(c, eid, "first", event_id=first["event_id"], request_id="tab-1")
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    # The same click again (a retry) gets the first result; it carries nothing on twice.
    again = pw.approve(c, eid, "first", event_id=first["event_id"], request_id="tab-1")
    assert again.status_code == 200 and again.json()["repeated"] is True, again.text
    pw.wait_parked(pw_run.state, eid, n_attempts=2)
    second = pw.open_gate(c, eid, "second")
    # Another tab answering the first wait late gets a 409 naming who answered.
    late = pw.approve(c, eid, "first", event_id=first["event_id"], request_id="tab-2")
    assert late.status_code == 409 and late.json()["detail"]["reason"] == "already_answered"
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "waiting"]
    assert [cp["id"] for cp in _gate_checkpoints(c, eid)] == [first["event_id"],
                                                               second["event_id"]]

    r = pw.approve(c, eid, "second", event_id=second["event_id"])
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    pw.finish_pi(c, eid)
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "completed"]
    assert pw.RAN == {"brief": 1, "first": 1, "second": 1}


def test_each_round_of_a_loop_waits_with_its_own_checkpoint_and_running_out_fails(pw_run):
    c = pw_run.client
    eid = sup.start(c, "pw_loop", pw_run.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(pw_run.state, eid)
    round1 = pw.open_gate(c, eid, "review")
    assert round1["round"] == 1
    assert pw.approve(c, eid, "review", event_id=round1["event_id"]).status_code == 200
    pw.wait_parked(pw_run.state, eid, n_attempts=2)
    round2 = pw.open_gate(c, eid, "review")
    assert round2["round"] == 2 and round2["event_id"] != round1["event_id"]
    stale = pw.approve(c, eid, "review", event_id=round1["event_id"], request_id="old-tab")
    assert stale.status_code == 409
    assert [cp["id"] for cp in _gate_checkpoints(c, eid)] == [round1["event_id"],
                                                               round2["event_id"]]
    assert pw.approve(c, eid, "review", event_id=round2["event_id"]).status_code == 200
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "failed"]
    assert "ran out of rounds: 2 of 2" in str(sup.events(eid, event_type="stage.started"))
    assert pw.RAN == {"brief": 1, "review": 2} and len(FakeBox.STARTS) == 1


def test_a_gate_next_to_a_running_step_lets_go_once_that_step_is_done(pw_run):
    c = pw_run.client
    eid = sup.start(c, "pw_side_by_side", pw_run.ws)
    pw.wait_parked(pw_run.state, eid)
    assert pw.RAN == {"brief": 1, "right": 1}
    gate = pw.open_gate(c, eid, "left")
    assert pw.approve(c, eid, "left", event_id=gate["event_id"]).status_code == 200
    pw.finish_pi(c, eid)
    assert pw.wait_ended(eid, 2)[-1]["status"] == "completed"
    assert pw.RAN == {"brief": 1, "right": 1, "left": 1}


def test_cancel_or_reject_while_parked_stops_it(pw_run):
    c = pw_run.client
    eid = sup.start(c, "pw_before_pi", pw_run.ws)
    pw.wait_parked(pw_run.state, eid)
    gate = pw.open_gate(c, eid, "check")

    r = c.post(f"/api/runs/{eid}/cancel", json={"reason": "not this one"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    assert [a["status"] for a in pw.attempts(eid)] == ["cancelled"]
    wait = pw.waits(eid, "check")[0]
    assert wait["status"] == "rejected"
    assert "not this one" in str(wait["data"].get("gate_response"))
    late = pw.approve(c, eid, "check", event_id=gate["event_id"])
    assert late.status_code in (404, 409)
    from temper_ai.runner import parked

    assert parked.carry_on_at_startup() == []
    assert [a["status"] for a in pw.attempts(eid)] == ["cancelled"]
    assert pw.detail(c, eid)["status"] == "cancelled"
    assert pw.RAN == {"brief": 1} and FakeBox.STARTS == []


def _age(eid: str, by: timedelta) -> None:
    """Move everything a run recorded back in time (the clock, for this run)."""
    from sqlmodel import select

    from temper_ai.checkpoint.models import Checkpoint
    from temper_ai.database import get_session
    from temper_ai.observability.models import Event

    with get_session() as session:
        for model in (Event, Checkpoint):
            for row in session.exec(select(model).where(model.execution_id == eid)).all():
                row.timestamp = row.timestamp - by
                session.add(row)


def test_a_wait_of_days_across_restarts_is_never_dropped_or_carried_on_by_itself(pw_run):
    from temper_ai.observability.reconcile import reconcile_and_report
    from temper_ai.runner import parked

    c = pw_run.client
    eid = sup.start(c, "pw_after_pi", pw_run.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(pw_run.state, eid)
    _age(eid, timedelta(days=3))

    for _restart in range(2):
        marked = reconcile_and_report(started_before=utcnow())
        assert eid not in [m["execution_id"] for m in marked], "not marked interrupted"
        picks = sup.restart_service(now=utcnow(), marked=marked)
        assert eid not in str(picks)
        assert parked.carry_on_at_startup() == [], "no answer: it stays put"
    attempt = pw.attempts(eid)[-1]
    assert attempt["status"] == "waiting" and pw.parked(attempt)
    assert len(pw.attempts(eid)) == 1 and pw.detail(c, eid)["status"] == "waiting"

    gate = pw.open_gate(c, eid, "check")
    r = pw.approve(c, eid, "check", event_id=gate["event_id"])
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["parked", "completed"]
    assert pw.RAN == {"brief": 1, "check": 1, "ship": 1} and len(FakeBox.STARTS) == 1


def test_an_answer_given_while_the_worker_was_down_is_applied_at_start_up(pw_run, monkeypatch):
    """The answer went in, but the server stopped before it carried the run on: start-up
    carries it on, however long ago that was."""
    from temper_ai.api import routes
    from temper_ai.runner import parked

    c = pw_run.client
    eid = sup.start(c, "pw_after_pi", pw_run.ws)
    pw.finish_pi(c, eid)
    pw.wait_parked(pw_run.state, eid)
    gate = pw.open_gate(c, eid, "check")
    with monkeypatch.context() as down:
        down.setattr(routes, "_carry_on_parked", lambda execution_id, by: False)
        r = pw.approve(c, eid, "check", event_id=gate["event_id"])
    assert r.status_code == 200, r.text
    assert r.json()["carries_on"] is False and r.json()["needs_resume"] is True
    _age(eid, timedelta(days=2))
    assert len(pw.attempts(eid)) == 1

    marked = reconcile_and_report_now()
    assert eid not in [m["execution_id"] for m in marked]
    assert parked.carry_on_at_startup() == [eid]
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["parked", "completed"]
    assert pw.RAN == {"brief": 1, "check": 1, "ship": 1} and len(FakeBox.STARTS) == 1
    # Only once: a second start-up finds nothing to carry on.
    assert parked.carry_on_at_startup() == []


def reconcile_and_report_now() -> list[dict]:
    from temper_ai.observability.reconcile import reconcile_and_report

    return reconcile_and_report(started_before=utcnow())


def test_a_second_resume_never_starts_a_second_copy(pw_run):
    from temper_ai.runner import parked

    c = pw_run.client
    eid = sup.start(c, "pw_before_pi", pw_run.ws)
    attempt = pw.wait_parked(pw_run.state, eid)
    # Someone else (the answer, start-up) has just claimed it and is starting it.
    assert parked.claim(attempt) is True
    assert parked.claim(attempt) is False
    r = c.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 409, r.text
    assert parked.carry_on_at_startup() == []
    parked.release(attempt)
    assert parked.parked_attempt(eid) is not None, "put back: it still waits on you"
    assert pw.RAN == {"brief": 1}
