"""Tests for the external execution mode in routes.py.

External mode = server inserts WorkflowRun row + returns; doesn't spawn.
A separate watcher process picks up the row and spawns the worker.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlmodel import select

from temper_ai.api.routes import _start_run_external
from temper_ai.database import get_session, init_database, reset_database
from temper_ai.runner.models import WorkflowRun


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "external_test.db"
    monkeypatch.setenv("WORKSPACE_DIR", "/tmp")
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{db_path}")
    reset_database()
    init_database(f"sqlite:///{db_path}")
    yield db_path
    reset_database()


def _config(name: str = "test_workflow"):
    return SimpleNamespace(name=name)


def _request(workflow: str = "test_workflow", workspace: str | None = "/tmp/ws"):
    from temper_ai.api.routes import RunRequest
    return RunRequest(workflow=workflow, workspace_path=workspace, inputs={"a": 1})


def test_external_dispatch_inserts_queued_row(isolated_db):
    resp = _start_run_external("ext-A", _request(), _config())
    assert resp.execution_id == "ext-A"
    assert resp.status == "queued"

    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == "ext-A"),
        ).one()
        assert row.status == "queued"
        assert row.spawner_kind is None  # watcher will set this
        assert row.spawner_handle is None
        assert row.workflow_name == "test_workflow"
        assert row.inputs == {"a": 1}


def test_external_dispatch_does_not_spawn(isolated_db, monkeypatch):
    """External mode must not call spawner.spawn() — that's the watcher's job."""
    spawn_called = []
    monkeypatch.setattr(
        "temper_ai.spawner.get_spawner",
        lambda: SimpleNamespace(spawn=lambda eid: spawn_called.append(eid)),
    )

    _start_run_external("ext-B", _request(), _config())
    assert spawn_called == []


def test_external_handles_empty_workspace(isolated_db):
    _start_run_external("ext-C", _request(workspace=None), _config())
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == "ext-C"),
        ).one()
        assert row.workspace_path == ""


# --- Resumes and forks go through the queue too -----------------------------
# With runs in boxes the server runs nothing itself: a resume or a fork is
# queued like a new run, and its box restores the checkpoints.

@pytest.fixture
def external(isolated_db, monkeypatch):
    """External mode, with an app state that loads any workflow and runs nothing."""
    from temper_ai.api import routes

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    state = SimpleNamespace(
        running={},
        graph_loader=SimpleNamespace(load_workflow=lambda name: (
            [SimpleNamespace(name="plan"), SimpleNamespace(name="build")],
            SimpleNamespace(name=name, outputs=None, safety=None),
        )),
    )
    monkeypatch.setattr(routes, "_state", lambda: state)
    return state


def _checkpoint(execution_id: str, node: str) -> int:
    """A finished node saved for the run; returns its checkpoint's sequence."""
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.stage.executor import NodeResult, Status

    service = CheckpointService(execution_id)
    service.save_node_completed(node, NodeResult(status=Status.COMPLETED, output=f"{node} done"))
    return service.get_latest_sequence()


def _earlier_attempt(monkeypatch, **fields) -> None:
    """What the events say about the run being resumed."""
    from temper_ai.api import routes

    found = {"workflow_name": "wf", "status": "interrupted", "input_data": {}, **fields}
    monkeypatch.setattr(routes, "get_workflow_execution", lambda _eid: dict(found))


def _row(execution_id: str) -> dict:
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).one()
        return row.model_dump()


def _add_row(execution_id: str, **fields) -> None:
    fields.setdefault("workspace_path", "")
    with get_session() as session:
        session.add(WorkflowRun(execution_id=execution_id, workflow_name="wf", **fields))


def test_stop_then_resume_waits_for_its_old_box_then_starts_once(external, monkeypatch):
    """The CI incident's timeline, through the real Resume and queue watcher.

    Docker would return exit 125/Conflict if run is called before --rm finishes.
    Master does exactly that and marks this cancelled run failed on its first scan.
    """
    from temper_ai.api import routes
    from temper_ai.cli.watch_queue import _scan_and_dispatch
    from temper_ai.spawner.docker_spawner import container_name
    from tests.test_spawner.test_docker_spawner import (
        FakeDocker,
        _inspect_json,
        _spawner,
    )

    eid = "stop-resume-replay"
    name = container_name(eid)
    _add_row(eid, status="cancelled", spawner_kind="docker", spawner_handle=name,
             cancel_requested=True, error={"message": "Cancelled", "kind": "cancelled"})
    _checkpoint(eid, "plan")
    _earlier_attempt(monkeypatch, id=eid, status="cancelled")
    # Seconds in the 20:47 minute of the recorded incident. No live/model run.
    now = [47.375]
    docker = FakeDocker(
        answers={"inspect": [(0, _inspect_json(), "")], "run": [(0, "resumed-cid", "")]},
        old_boxes={name: "exited"},
    )
    spawner = _spawner(docker, "", clock=lambda: now[0])
    assert routes.get_workflow(eid)["status"] == "cancelled"

    now[0] = 49.708
    assert routes.resume_run(eid).status == "queued"
    now[0] = 50.276
    assert _scan_and_dispatch(spawner) == 0
    waiting = _row(eid)
    assert waiting["status"] == "queued", waiting["error"]
    assert (waiting["spawner_kind"], waiting["spawner_handle"]) == (None, None)
    assert waiting["error"] is None
    assert waiting["spawner_metadata"] == {"start": "resume"}
    assert docker.commands("run") == []
    now[0] = 52.276  # another scan while Docker still holds the name
    assert _scan_and_dispatch(spawner) == 0
    assert docker.commands("run") == []

    now[0] = 54.276
    docker.old_boxes.clear()
    assert _scan_and_dispatch(spawner) == 1
    assert _scan_and_dispatch(spawner) == 0  # claimed; cannot start it twice
    assert len(docker.commands("run")) == 1
    assert _row(eid)["spawner_handle"] == name
    assert _row(eid)["spawner_metadata"]["start"] == "resume"
    assert external.running == {}


def test_old_box_expiry_fails_only_the_queued_attempt(external, monkeypatch):
    from temper_ai.api import routes
    from temper_ai.cli.watch_queue import _scan_and_dispatch
    from temper_ai.spawner.docker_spawner import container_name
    from tests.test_spawner.test_docker_spawner import FakeDocker, _spawner

    name = container_name("expired")
    _add_row("expired", status="cancelled")
    _checkpoint("expired", "plan")
    _earlier_attempt(monkeypatch, status="cancelled")
    now = [0.0]
    docker = FakeDocker(old_boxes={name: "exited"})
    spawner = _spawner(docker, "", clock=lambda: now[0])
    assert routes.resume_run("expired").status == "queued"
    assert _scan_and_dispatch(spawner) == 0
    assert _row("expired")["status"] == "queued"
    now[0] = 120.0
    assert _scan_and_dispatch(spawner) == 0
    refused = _row("expired")
    assert refused["status"] == "failed"
    assert refused["error"] == {
        "kind": "spawn",
        "message": f"its last box {name} is still there (exited) after 120 s; not starting a second one",
    }
    assert docker.commands("run") == []


def test_a_resume_is_queued_for_a_box_not_run_in_the_server(external, monkeypatch):
    from temper_ai.api import routes

    _checkpoint("run-1", "plan")
    _earlier_attempt(monkeypatch, input_data={"topic": "x"}, workspace_path="/tmp/ws")

    resp = routes.resume_run("run-1")

    assert (resp.execution_id, resp.status) == ("run-1", "queued")
    assert external.running == {}  # no thread in the server
    row = _row("run-1")
    assert row["status"] == "queued"
    assert row["spawner_kind"] is None  # the watcher's to claim
    assert row["spawner_metadata"] == {"start": "resume"}
    assert row["inputs"] == {"topic": "x"}
    assert row["workspace_path"] == "/tmp/ws"


def test_resuming_a_run_that_ended_in_a_box_puts_its_row_back_in_the_queue(external, monkeypatch):
    from temper_ai.api import routes

    _add_row(
        "run-2", status="orphaned", spawner_kind="docker", spawner_handle="temper-run-run-2",
        spawner_metadata={"container": "temper-run-run-2"}, cancel_requested=True, attempts=1,
        error={"message": "reaped: gone", "kind": "orphaned"}, result={"exit_code": 1},
    )
    _checkpoint("run-2", "plan")
    _earlier_attempt(monkeypatch)

    routes.resume_run("run-2")

    row = _row("run-2")
    assert row["status"] == "queued"
    assert (row["spawner_kind"], row["spawner_handle"]) == (None, None)
    assert row["spawner_metadata"] == {"start": "resume"}
    assert row["cancel_requested"] is False
    assert (row["error"], row["result"], row["completed_at"]) == (None, None, None)
    assert row["attempts"] == 1  # the box counts its own attempt


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_run_still_waiting_for_or_in_its_box_is_not_resumed_twice(external, monkeypatch, status):
    from fastapi import HTTPException

    from temper_ai.api import routes

    _add_row("run-3", status=status)
    _checkpoint("run-3", "plan")
    _earlier_attempt(monkeypatch)

    with pytest.raises(HTTPException) as refused:
        routes.resume_run("run-3")

    assert refused.value.status_code == 409
    assert _row("run-3")["spawner_metadata"] in (None, {})


@pytest.mark.parametrize("status", ["queued", "running"])
@pytest.mark.parametrize("in_process", [False, True])
def test_active_resume_is_refused_before_hold_takeover_or_queue(
    external, monkeypatch, status, in_process,
):
    from fastapi import HTTPException

    from temper_ai.api import routes

    eid = "active"
    _add_row(eid, status=status)
    _checkpoint(eid, "plan")
    _earlier_attempt(monkeypatch, id=eid, status=status)
    if in_process:
        monkeypatch.setenv("TEMPER_EXECUTION_MODE", "in-process")
        external.running[eid] = object()
    before = _row(eid)
    takeovers = []
    monkeypatch.setattr(routes.holds, "take_over", lambda *a, **k: takeovers.append((a, k)))
    with pytest.raises(HTTPException) as refused:
        routes.resume_run(eid)
    assert refused.value.status_code == 409
    assert "stop it first" in refused.value.detail
    assert takeovers == []
    assert _row(eid) == before
    assert not in_process or eid in external.running


@pytest.mark.parametrize("status", ["cancelled", "failed", "completed"])
def test_terminal_main_lane_resume_still_queues(external, monkeypatch, status):
    from temper_ai.api import routes

    _add_row("terminal", status=status)
    _checkpoint("terminal", "plan")
    _earlier_attempt(monkeypatch, status=status)
    assert routes.resume_run("terminal").status == "queued"
    assert _row("terminal")["status"] == "queued"


def test_active_main_lane_resume_without_checkpoints_is_still_a_conflict(external, monkeypatch):
    from fastapi import HTTPException

    from temper_ai.api import routes

    _add_row("no-checkpoints", status="running")
    _earlier_attempt(monkeypatch, status="running")
    with pytest.raises(HTTPException) as refused:
        routes.resume_run("no-checkpoints")
    assert refused.value.status_code == 409
    assert "stop it first" in refused.value.detail
    assert _row("no-checkpoints")["status"] == "running"


def test_a_resume_with_nothing_saved_is_refused_before_it_is_queued(external, monkeypatch):
    from fastapi import HTTPException

    from temper_ai.api import routes

    _earlier_attempt(monkeypatch)
    with pytest.raises(HTTPException) as refused:
        routes.resume_run("run-4")
    assert refused.value.status_code == 400
    with get_session() as session:
        assert session.exec(select(WorkflowRun)).all() == []


def test_a_fork_is_queued_for_a_box_with_its_checkpoints_under_the_new_id(external):
    from temper_ai.api import routes
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.observability.models import Event

    fork_at = _checkpoint("src-1", "plan")
    _checkpoint("src-1", "build")

    resp = routes.fork_run(routes.ForkRequest(
        workflow="wf", source_execution_id="src-1", sequence=fork_at,
        inputs={"topic": "y"}, workspace_path="/tmp/ws2",
    ))

    assert resp.status == "queued"
    assert external.running == {}
    row = _row(resp.execution_id)
    assert row["spawner_metadata"] == {"start": "fork"}
    assert (row["inputs"], row["workspace_path"]) == ({"topic": "y"}, "/tmp/ws2")
    # what its box will restore: the source up to the fork point
    assert set(CheckpointService(resp.execution_id).reconstruct()) == {"plan"}
    with get_session() as session:
        (link,) = session.exec(select(Event).where(
            Event.execution_id == resp.execution_id, Event.type == "fork.metadata",
        )).all()
        assert link.data["source_execution_id"] == "src-1"
        assert link.data["restored_node_names"] == ["plan"]


def test_a_queued_run_is_found_before_its_box_starts(external):
    """No events until the box starts it: the row answers, so an MCP caller
    polling at once, or the one-run-per-page guard, sees it queued."""
    from temper_ai.api import routes

    _start_run_external("ext-Q", _request(), _config("wf"))

    found = routes.get_workflow("ext-Q")

    assert (found["status"], found["workflow_name"]) == ("queued", "wf")
    assert found["input_data"] == {"a": 1}


def test_a_run_whose_box_failed_to_start_says_why(external):
    from temper_ai.api import routes

    _add_row("ext-F", status="failed", error={"message": "no such image", "kind": "spawn"})
    found = routes.get_workflow("ext-F")
    assert (found["status"], found["error_message"]) == ("failed", "no such image")


def test_a_resume_waiting_for_its_box_shows_as_queued_not_as_the_last_attempt(external, monkeypatch):
    from temper_ai.api import routes

    _add_row("run-5", status="queued", spawner_metadata={"start": "resume"})
    _earlier_attempt(monkeypatch, id="run-5", status="interrupted")
    assert routes.get_workflow("run-5")["status"] == "queued"


def test_an_unknown_run_is_still_not_found(external):
    from fastapi import HTTPException

    from temper_ai.api import routes

    with pytest.raises(HTTPException) as missing:
        routes.get_workflow("nobody")
    assert missing.value.status_code == 404
