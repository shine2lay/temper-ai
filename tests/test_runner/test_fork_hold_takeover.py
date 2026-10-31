"""FWS375-FORK-TAKEOVER: a fork takes over its source's held clean-ups in the commit that
queues it, or it is refused.

A fork is a new execution id, so the busy refusal that protects a same-id successor never
protects it. If the fork queued in one commit and took the source's hold over in another,
a failed takeover write, or Give up or a due sweep ending the hold in between, would queue
the source's clean-ups while the fork resumes into the same workspace.

Reuses FWS-HOLD-1's route harness (test_workspace_hold_admission) and the parked-claim
readers: real router, holds, sweeper and queue on a fresh test database; no box, workflow
thread, provider or model starts.
"""
from __future__ import annotations

import pytest
from sqlalchemy import delete

from temper_ai.api import routes
from temper_ai.database import get_session
from temper_ai.runner import cleanup_dispatch, hold_sweeper, holds, queue
from temper_ai.runner.models import CleanupHold
from tests.test_runner.test_parked_claim_atomic import _hold_state, _state
from tests.test_runner.test_parked_claim_atomic import (
    _shared_database as _shared_database,
)
from tests.test_runner.test_parked_claim_atomic import resume_rig as resume_rig
from tests.test_runner.test_workspace_hold_admission import _mutate, _queued, _seed
from tests.test_runner.test_workspace_hold_admission import client as client

INJECTED = "FWS375 injected fork takeover write error"
WORKSPACE = "/workspaces/ws"


def _fork(client, run: str, sequence: int):
    return client.post("/api/runs/fork", json={"workflow": "wf", "source_execution_id": run,
                                               "sequence": sequence, "workspace_path": WORKSPACE})


def _plain_workflow(rig, monkeypatch) -> None:
    rig.nodes.clear()
    monkeypatch.delenv("TEMPER_LANE", raising=False)


def _queued_view() -> list[tuple[str, str | None]]:
    return sorted((row["execution_id"], (row["spawner_metadata"] or {}).get("start"))
                  for row in _queued())


def _queue_attempts(monkeypatch, source: str) -> list[str]:
    """Every queue write the fork asks for (any execution id other than its source)."""
    real = queue.queue_run_in
    attempts: list[str] = []

    def spy(session, execution_id, *args, **kwargs):
        if execution_id != source:
            attempts.append(execution_id)
        return real(session, execution_id, *args, **kwargs)

    monkeypatch.setattr(queue, "queue_run_in", spy)
    return attempts


def _in_the_window(monkeypatch, interloper) -> list[str]:
    """Run ``interloper`` once, after the fork began and before it queues and takes over."""
    real = routes._record_fork_metadata
    ran: list[str] = []

    def record_then_interlope(new_execution_id, *args, **kwargs):
        real(new_execution_id, *args, **kwargs)
        if not ran:
            ran.append(interloper())

    monkeypatch.setattr(routes, "_record_fork_metadata", record_then_interlope)
    return ran


def _give_up(run: str):
    return lambda: routes._release_cleanups(run)["status"]


def _sweep():
    hold_sweeper._sweep()
    return "swept"


def _source_cleanup_only(run: str) -> list[tuple[str, str | None]]:
    return [(run, "cleanup")]


@pytest.mark.parametrize("workflow", ["pi", "plain"])
def test_a_fork_twin_takes_over_the_waiting_hold_it_queues_with(
        client, resume_rig, monkeypatch, workflow):
    """Valid twin: the hold is waiting throughout; the fork queues and owns the clean-ups."""
    if workflow == "plain":
        _plain_workflow(resume_rig, monkeypatch)
    run = f"fws375-fork-twin-{workflow}"
    sequence = _seed(run, pi=workflow == "pi")
    hold_before, row_before = _hold_state(run), _state(run)
    reply = _fork(client, run, sequence)
    assert reply.status_code == 200, "FWS375-FORK-TWIN-STATUS"
    fork = reply.json()["execution_id"]
    assert _queued_view() == [(fork, "fork")], "FWS375-FORK-TWIN-QUEUED"
    hold = _hold_state(run)
    assert (hold["status"], hold["ended_by"]) == ("taken_over", fork), "FWS375-FORK-TWIN-HOLD"
    assert hold["deadline"] == hold_before["deadline"] and hold["ended_at"] is not None
    # The source's clean-ups are the fork's now: neither Give up nor the deadline runs them.
    assert client.post(f"/api/runs/{run}/cleanup").status_code == 409, "FWS375-FORK-TWIN-GIVEUP"
    hold_sweeper._sweep()
    assert _hold_state(run) == hold, "FWS375-FORK-TWIN-SWEEP"
    assert _queued_view() == [(fork, "fork")] and _state(run) == row_before
    assert resume_rig.starts == resume_rig.released == []


@pytest.mark.parametrize("workflow", ["pi", "plain"])
def test_a_failed_takeover_write_queues_no_fork_and_keeps_the_sources_hold(
        client, resume_rig, monkeypatch, workflow):
    if workflow == "plain":
        _plain_workflow(resume_rig, monkeypatch)
    run = f"fws375-fork-write-{workflow}"
    sequence = _seed(run, pi=workflow == "pi")
    hold_before, row_before, queued_before = _hold_state(run), _state(run), _queued_view()
    real_end_in = holds.end_in
    writes: list[tuple[str, str, str]] = []

    def failing_takeover(session, execution_id, status, by):
        writes.append((execution_id, status, by))
        if status == "taken_over":
            raise RuntimeError(INJECTED)
        return real_end_in(session, execution_id, status, by)

    monkeypatch.setattr(holds, "end_in", failing_takeover)
    try:
        status = _fork(client, run, sequence).status_code
    except RuntimeError as exc:
        assert INJECTED in str(exc)
        status = None
    assert [(eid, wanted) for eid, wanted, _by in writes] == [(run, "taken_over")], \
        "FWS375-FORK-WRITE-FAULT-REACHED"
    assert _queued_view() == queued_before, "FWS375-FORK-WRITE-NO-FORK"
    assert _hold_state(run) == hold_before, "FWS375-FORK-WRITE-HOLD-KEPT"
    assert status is None, "FWS375-FORK-WRITE-NOT-ADMITTED"
    assert _state(run) == row_before
    # The source still owns its clean-ups: Give up runs them, and nothing else is queued.
    monkeypatch.setattr(holds, "end_in", real_end_in)
    assert client.post(f"/api/runs/{run}/cleanup").status_code == 200
    assert _queued_view() == _source_cleanup_only(run), "FWS375-FORK-WRITE-SOURCE-OWNS"
    assert resume_rig.starts == resume_rig.released == []


@pytest.mark.parametrize("workflow", ["pi", "plain"])
@pytest.mark.parametrize("interloper", ["give_up", "sweep"])
def test_a_hold_ended_inside_the_forks_window_refuses_the_fork(
        client, resume_rig, monkeypatch, interloper, workflow):
    if workflow == "plain":
        _plain_workflow(resume_rig, monkeypatch)
    run = f"fws375-fork-window-{interloper}-{workflow}"
    sequence = _seed(run, pi=workflow == "pi")
    hold_before = _hold_state(run)
    attempts = _queue_attempts(monkeypatch, run)
    ran = _in_the_window(monkeypatch, _give_up(run) if interloper == "give_up" else _sweep)
    reply = _fork(client, run, sequence)
    assert ran == (["queued"] if interloper == "give_up" else ["swept"]), "FWS375-FORK-WINDOW-REACHED"
    assert reply.status_code == 409, "FWS375-FORK-WINDOW-STATUS"
    assert _queued_view() == _source_cleanup_only(run), "FWS375-FORK-WINDOW-QUEUED"
    hold = _hold_state(run)
    expected_by = "give_up" if interloper == "give_up" else "deadline"
    assert (hold["status"], hold["ended_by"]) == ("released", expected_by), "FWS375-FORK-WINDOW-HOLD"
    assert hold["deadline"] == hold_before["deadline"]
    assert attempts == [], "FWS375-FORK-HOLD-FIRST"
    assert resume_rig.starts == resume_rig.released == []


@pytest.mark.parametrize("before_fork", ["no-hold", "released"])
def test_a_fork_whose_source_held_nothing_when_it_began_is_unchanged(
        client, resume_rig, before_fork):
    """Ordinary twin: with no waiting hold when the fork begins there is nothing to take
    over, and the fork queues as before (a hold given up earlier stays the source's)."""
    run = f"fws375-fork-unheld-{before_fork}"
    sequence = _seed(run)
    if before_fork == "no-hold":
        with get_session() as session:
            session.exec(delete(CleanupHold).where(CleanupHold.execution_id == run))
        expected_before: list[tuple[str, str | None]] = []
    else:
        assert client.post(f"/api/runs/{run}/cleanup").status_code == 200
        expected_before = _source_cleanup_only(run)
    assert _queued_view() == expected_before
    held = _hold_state(run) if before_fork == "released" else None
    reply = _fork(client, run, sequence)
    assert reply.status_code == 200, "FWS375-FORK-UNHELD-STATUS"
    fork = reply.json()["execution_id"]
    assert _queued_view() == sorted([*expected_before, (fork, "fork")]), "FWS375-FORK-UNHELD-QUEUED"
    if held is not None:
        assert _hold_state(run) == held, "FWS375-FORK-UNHELD-HOLD"
    assert resume_rig.starts == resume_rig.released == []


# The same-transaction guard's bite is FWS-HOLD-1's fork case in test_workspace_hold_admission
# (a separately committed takeover survives a refused fork).


@pytest.mark.parametrize("interloper", ["give_up", "sweep"])
def test_the_ended_wait_refusal_has_a_bite(client, resume_rig, monkeypatch, interloper):
    _mutate(monkeypatch, cleanup_dispatch, "queue_fork_taking_over",
            "if taken is None and source_was_holding:", "if False:")
    with pytest.raises(AssertionError, match="FWS375-FORK-WINDOW-STATUS"):
        test_a_hold_ended_inside_the_forks_window_refuses_the_fork(
            client, resume_rig, monkeypatch, interloper, "pi")


def test_the_hold_first_order_has_a_bite(client, resume_rig, monkeypatch):
    queue_first = ('queue.queue_run_in(session, fork_execution_id, workflow_name, workspace_path,'
                   ' inputs, start="fork", lane=lane)\n        ')
    _mutate(monkeypatch, cleanup_dispatch, "queue_fork_taking_over",
            "if taken is None and source_was_holding:",
            queue_first + "if taken is None and source_was_holding:")
    with pytest.raises(AssertionError, match="FWS375-FORK-HOLD-FIRST"):
        test_a_hold_ended_inside_the_forks_window_refuses_the_fork(
            client, resume_rig, monkeypatch, "give_up", "pi")


def test_the_holding_reading_at_fork_start_has_a_bite(client, resume_rig, monkeypatch):
    """Without the reading at fork start the fork cannot tell an ended wait from none."""
    monkeypatch.setattr(holds, "waiting", lambda execution_id: None)
    with pytest.raises(AssertionError, match="FWS375-FORK-WINDOW-STATUS"):
        test_a_hold_ended_inside_the_forks_window_refuses_the_fork(
            client, resume_rig, monkeypatch, "sweep", "plain")
