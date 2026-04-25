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
