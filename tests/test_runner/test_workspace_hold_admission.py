"""FWS-HOLD-1: cleanup ownership survives refused admission at every retained caller.

Real routes, checkpoints, queue and both database tiers; counted workflow threads
never run. Reuse the parked-claim fixture and its committed-state readers.
"""
from __future__ import annotations

import inspect
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import select

from temper_ai.api import routes
from temper_ai.checkpoint.service import CheckpointService
from temper_ai.database import get_session
from temper_ai.runner import (
    cleanup_dispatch,
    hold_sweeper,
    holds,
    pi_lane,
    queue,
    resume_claim,
)
from temper_ai.runner.lanes import LANE_KEY, PI_LANE
from temper_ai.runner.models import WorkflowRun
from temper_ai.spawner.box_seal import WorkspacePathRefused
from temper_ai.stage.executor import NodeResult, Status
from tests.test_runner.test_parked_claim_atomic import (
    _attempt,
    _hold_state,
    _row,
    _state,
    at,
)
from tests.test_runner.test_parked_claim_atomic import (
    _shared_database as _shared_database,
)
from tests.test_runner.test_parked_claim_atomic import (
    resume_rig as resume_rig,
)


@pytest.fixture
def client(resume_rig, monkeypatch):
    monkeypatch.setattr(routes, "require_caller_may", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "record_action", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as http:
        yield http


def _seed(run, workspace="/workspaces/ws", *, pi=True):
    _attempt(run, status="failed", note={})
    _row(run, "failed", handle="old-box", lane=PI_LANE if pi else None)
    with get_session() as session:
        row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == run)).one()
        row.workspace_path = workspace or ""
        session.add(row)
    checkpoint = CheckpointService(run)
    checkpoint.save_node_completed("plan", NodeResult(status=Status.COMPLETED, output="ready"))
    holds.record(run, workflow_name="wf", workspace_path=workspace, inputs={"topic": "t"},
                 held=[{"path": "cleanup"}], deadline=at("11:00:00"))
    return checkpoint.get_latest_sequence()


def _call(client, action, run, workspace, sequence):
    if action == "resume":
        return client.post(f"/api/runs/{run}/resume", json={"workspace_path": workspace})
    if action == "fork":
        return client.post("/api/runs/fork", json={"workflow": "wf", "source_execution_id": run,
                                                "sequence": sequence, "workspace_path": workspace})
    if action == "cleanup":
        return client.post(f"/api/runs/{run}/cleanup")
    if action == "lane":
        pi_lane.resume_in_the_lane(run)
    else:
        assert action == "sweep"
        hold_sweeper._sweep()
    return None


def _queued():
    with get_session() as session:
        return [row.model_dump() for row in session.exec(
            select(WorkflowRun).where(WorkflowRun.status == "queued")).all()]


ACTIONS = ("resume", "fork", "lane", "cleanup", "sweep")


def _assert_case(client, rig, action, safe, *, suffix="", pi=True):
    run = f"hold-admission-{action}-{safe}-{suffix}"
    workspace = "/workspaces/ws" if safe else "/outside"
    sequence = _seed(run, workspace, pi=pi)
    before, hold_before = _state(run), _hold_state(run)
    queued_before = _queued()
    if action == "lane" and not safe:
        with pytest.raises(WorkspacePathRefused, match="outside"):
            _call(client, action, run, workspace, sequence)
        reply = None
    else:
        reply = _call(client, action, run, workspace, sequence)
    if reply is not None:
        assert reply.status_code == (200 if safe else 400), f"FWS-{action.upper()}-STATUS"
        if not safe:
            assert "'/outside'" in reply.json()["detail"]
    if safe:
        new = [row for row in _queued() if row not in queued_before]
        assert len(new) == 1 and new[0]["status"] == "queued"
        successor = new[0]["execution_id"]
        assert (successor != run) == (action == "fork")
        expected_start = "cleanup" if action in ("cleanup", "sweep") else "fork" if action == "fork" else "resume"
        assert new[0]["spawner_metadata"]["start"] == expected_start
        if pi:
            assert new[0]["spawner_metadata"][LANE_KEY] == PI_LANE
        hold = _hold_state(run)
        assert hold["status"] == ("released" if action in ("cleanup", "sweep") else "taken_over")
        assert hold["ended_by"] == ("give_up" if action == "cleanup" else "deadline" if action == "sweep" else successor)
        assert hold["deadline"] == hold_before["deadline"] and hold["ended_at"] is not None
        if action in ("resume", "lane") and pi:
            assert resume_claim._read(run) is not None
    else:
        assert _state(run) == before, f"FWS-{action.upper()}-REFUSED-ROW"
        assert _queued() == queued_before
        # Stable reviewer oracles carried into production regression coverage.
        oracle = {"resume": "FWS365-RESUME-REFUSED-HOLD", "cleanup": "FWS365-CLEANUP-REFUSED-HOLD"}
        assert _hold_state(run) == hold_before, oracle.get(action, f"FWS-{action.upper()}-REFUSED-HOLD")
        assert resume_claim._read(run) is None
        assert run not in [eid for eid, _seen in rig.took]
        assert run in [hold["execution_id"] for hold in holds.due()]
        if action == "sweep":
            hold_sweeper._sweep()
            assert _hold_state(run) == hold_before and _state(run) == before
            assert run in [hold["execution_id"] for hold in holds.due()]
    assert rig.starts == rig.released == []


def test_all_successors_queue_then_own_their_cleanup_without_starting_work(client, resume_rig):
    """Opening combined happy path: every retained dispatch, real row and hold, no boxes."""
    for action in ACTIONS:
        _assert_case(client, resume_rig, action, True)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("safe", [True, False], ids=["valid", "outside"])
def test_each_retained_caller_keeps_its_hold_until_admitted(client, resume_rig, action, safe):
    _assert_case(client, resume_rig, action, safe)


@pytest.mark.parametrize("action", ["resume", "fork", "cleanup", "sweep"])
@pytest.mark.parametrize("safe", [True, False], ids=["valid", "outside"])
def test_plain_workflows_have_the_same_hold_admission_rule(client, resume_rig, monkeypatch, action, safe):
    resume_rig.nodes.clear()
    monkeypatch.delenv("TEMPER_LANE", raising=False)
    _assert_case(client, resume_rig, action, safe, pi=False)


@pytest.mark.parametrize("failure", ["busy", "after-row-write"])
def test_cleanup_admission_rolls_back_hold_and_partial_queue_work(client, resume_rig, monkeypatch, failure):
    run = f"cleanup-error-{failure}"
    _seed(run)
    if failure == "busy":
        with get_session() as session:
            row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == run)).one()
            row.status = "running"
            session.add(row)
    before, held = _state(run), _hold_state(run)
    if failure == "after-row-write":
        original = queue.queue_run_in

        def fail_after_write(session, *args, **kwargs):
            original(session, *args, **kwargs)
            session.flush()
            raise WorkspacePathRefused("injected admission refusal")

        monkeypatch.setattr(queue, "queue_run_in", fail_after_write)
    response = client.post(f"/api/runs/{run}/cleanup")
    assert response.status_code == (409 if failure == "busy" else 400)
    assert _state(run) == before and _hold_state(run) == held
    assert _queued() == []


def test_two_cleanup_dispatchers_share_one_conditional_winner(resume_rig, monkeypatch):
    run = "cleanup-concurrent"
    _seed(run)
    barrier = threading.Barrier(2)
    original = holds.end_in

    def together(session, *args, **kwargs):
        barrier.wait(timeout=10)
        return original(session, *args, **kwargs)

    monkeypatch.setattr(holds, "end_in", together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(cleanup_dispatch.queue_held_cleanups, run, by=by)
                 for by in ("give_up", "deadline")]
        outcomes = [call.result(timeout=15) for call in calls]
    assert sum(ended is not None for ended in outcomes) == 1
    assert len(_queued()) == 1
    assert _hold_state(run)["status"] == "released"
    assert _hold_state(run)["ended_by"] in ("give_up", "deadline")


def test_a_stale_sweeper_cannot_replace_another_actors_hold_transition(client, resume_rig, monkeypatch):
    run = "cleanup-other-winner"
    _seed(run, "/outside")
    stale = holds.due()
    holds.take_over(run, by="newer-run")
    before = _hold_state(run)
    monkeypatch.setattr(holds, "due", lambda: stale)
    hold_sweeper._sweep()
    assert _hold_state(run) == before and _queued() == []
    assert client.post(f"/api/runs/{run}/cleanup").status_code == 409
    assert _hold_state(run) == before


def test_conditional_hold_end_keeps_other_and_already_ended_holds(resume_rig):
    run = "cleanup-end-cas"
    _seed(run)
    before = _hold_state(run)
    assert holds.end("missing-run", "released", by="deadline") is None, "FWS-HOLD-ID-PREDICATE"
    assert _hold_state(run) == before
    assert holds.end(run, "taken_over", by="newer-run") is not None
    ended = _hold_state(run)
    assert holds.end(run, "released", by="deadline") is None, "FWS-HOLD-WAITING-PREDICATE"
    assert _hold_state(run) == ended


def test_lane_hold_error_after_admission_does_not_release_the_successors_claim(resume_rig):
    run = "lane-admitted-hold-error"
    _seed(run)
    resume_rig.hold_error = RuntimeError("hold failed after admission")
    with pytest.raises(RuntimeError, match="hold failed after admission"):
        pi_lane.resume_in_the_lane(run)
    assert _state(run)["row"]["status"] == "queued"
    assert resume_claim._read(run) is not None
    assert _hold_state(run)["status"] == "waiting"
    with pytest.raises(pi_lane.CarriedOnAlready):
        pi_lane.resume_in_the_lane(run)


@pytest.mark.parametrize("workspace", [None, ""])
def test_cleanup_without_an_explicit_workspace_keeps_automatic_allocation(client, resume_rig, workspace):
    run = f"cleanup-automatic-{workspace!r}"
    _seed(run, workspace)
    assert client.post(f"/api/runs/{run}/cleanup").status_code == 200
    assert _state(run)["row"]["workspace_path"] == ""
    assert _hold_state(run)["status"] == "released"


@pytest.mark.parametrize("case", ["inprocess-plain", "no-paths"])
def test_cleanup_non_dispatch_cases_keep_existing_behavior(client, resume_rig, monkeypatch, case):
    run = f"cleanup-no-dispatch-{case}"
    _seed(run, "/outside", pi=False)
    before = _state(run)
    if case == "inprocess-plain":
        monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
        monkeypatch.delenv("TEMPER_LANE", raising=False)
    else:
        holds.record(run, workflow_name="wf", workspace_path="/outside", inputs={},
                     held=[{}], deadline=at("11:00:00"))
    assert client.post(f"/api/runs/{run}/cleanup").status_code == 200
    assert _state(run) == before and _queued() == []
    assert _hold_state(run)["status"] == "released"


def _mutate(monkeypatch, module, name, old, new):
    source = inspect.getsource(getattr(module, name))
    assert source.count(old) == 1
    namespace = dict(vars(module))
    exec(compile(source.replace(old, new), "<FWS hold ordering removed>", "exec"), namespace)
    monkeypatch.setattr(module, name, namespace[name])


@pytest.mark.parametrize("action", ACTIONS)
def test_early_hold_commits_have_a_bite(client, resume_rig, monkeypatch, action):
    if action == "resume":
        _mutate(monkeypatch, routes, "_resume_run", "        response = _start_resume(",
                "        holds.take_over(execution_id, by=execution_id)\n        response = _start_resume(")
    elif action == "fork":
        _mutate(monkeypatch, routes, "_fork_run", "        _queue_run(new_execution_id,",
                "        holds.take_over(body.source_execution_id, by=new_execution_id)\n        _queue_run(new_execution_id,")
    elif action == "lane":
        _mutate(monkeypatch, pi_lane, "resume_in_the_lane", "        queue_run(execution_id,",
                "        holds.take_over(execution_id, by=execution_id)\n        queue_run(execution_id,")
    else:
        _mutate(monkeypatch, cleanup_dispatch, "queue_held_cleanups",
                'holds.end_in(session, execution_id, "released", by)',
                'holds.end(execution_id, "released", by)')
    with pytest.raises(AssertionError, match="REFUSED-HOLD"):
        _assert_case(client, resume_rig, action, False)


@pytest.mark.parametrize("predicate,oracle", [
    ('col(CleanupHold.execution_id) == execution_id', "FWS-HOLD-ID-PREDICATE"),
    ('col(CleanupHold.status) == "waiting"', "FWS-HOLD-WAITING-PREDICATE"),
])
def test_each_hold_transition_predicate_has_a_bite(resume_rig, monkeypatch, predicate, oracle):
    _mutate(monkeypatch, holds, "end_in", predicate, "True")
    with pytest.raises(AssertionError, match=oracle):
        test_conditional_hold_end_keeps_other_and_already_ended_holds(resume_rig)
