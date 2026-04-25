"""Tests for the subprocess execution path through the routes layer.

Verifies:
  - _start_run_subprocess inserts a queued row, calls spawner.spawn, then
    stamps the row with the handle
  - SpawnerError → 503 + row marked failed
  - cancel_run sets cancel_requested=true on a subprocess row

Doesn't go through HTTP / TestClient because the test isn't about the
FastAPI surface — it's about the spawner integration. The HTTP wiring
is covered by the broader test_routes.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlmodel import select

from temper_ai.api.routes import _start_run_subprocess, cancel_run
from temper_ai.database import get_session, init_database, reset_database
from temper_ai.runner.models import WorkflowRun
from temper_ai.spawner.base import SpawnerError
from temper_ai.spawner.factory import reset_spawner
from temper_ai.worker_proto import ProcessHandle, SpawnerKind


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "subdispatch_test.db"
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{db_path}")
    reset_database()
    init_database(f"sqlite:///{db_path}")
    yield db_path
    reset_database()


@pytest.fixture(autouse=True)
def _reset_spawner():
    reset_spawner()
    yield
    reset_spawner()


def _config(name: str = "test_workflow"):
    return SimpleNamespace(name=name)


def _request(workflow: str = "test_workflow", workspace: str | None = "/tmp/ws"):
    from temper_ai.api.routes import RunRequest
    return RunRequest(workflow=workflow, workspace_path=workspace, inputs={"a": 1})


def _read_row(execution_id: str) -> dict:
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).one()
        return {
            "status": row.status,
            "spawner_kind": row.spawner_kind,
            "spawner_handle": row.spawner_handle,
            "cancel_requested": row.cancel_requested,
            "error": row.error,
            "workflow_name": row.workflow_name,
            "workspace_path": row.workspace_path,
            "inputs": row.inputs,
        }


# --- _start_run_subprocess --------------------------------------------------

def test_subprocess_dispatch_inserts_row_and_spawns(isolated_db, monkeypatch):
    fake_spawner = MagicMock()
    fake_spawner.spawn.return_value = ProcessHandle(
        kind=SpawnerKind.subprocess,
        handle="9999",
        metadata={"execution_id": "exec-A"},
    )
    monkeypatch.setattr(
        "temper_ai.spawner.get_spawner", lambda: fake_spawner,
    )

    resp = _start_run_subprocess("exec-A", _request(), _config())
    assert resp.execution_id == "exec-A"
    assert resp.status == "running"

    row = _read_row("exec-A")
    assert row["status"] == "queued"  # worker flips to running on its own
    assert row["spawner_kind"] == "subprocess"
    assert row["spawner_handle"] == "9999"
    assert row["workflow_name"] == "test_workflow"
    assert row["workspace_path"] == "/tmp/ws"
    assert row["inputs"] == {"a": 1}

    fake_spawner.spawn.assert_called_once_with("exec-A")


def test_subprocess_spawn_failure_marks_row_failed(isolated_db, monkeypatch):
    fake_spawner = MagicMock()
    fake_spawner.spawn.side_effect = SpawnerError("fork bombed")
    monkeypatch.setattr(
        "temper_ai.spawner.get_spawner", lambda: fake_spawner,
    )

    with pytest.raises(HTTPException) as exc_info:
        _start_run_subprocess("exec-B", _request(), _config())
    assert exc_info.value.status_code == 503
    assert "fork bombed" in exc_info.value.detail

    row = _read_row("exec-B")
    assert row["status"] == "failed"
    assert row["error"]["kind"] == "spawn"
    assert "fork bombed" in row["error"]["message"]


def test_subprocess_dispatch_handles_empty_workspace(isolated_db, monkeypatch):
    """workspace_path=None should not insert NULL — column is non-null str.
    Helper coerces None to empty string."""
    fake_spawner = MagicMock()
    fake_spawner.spawn.return_value = ProcessHandle(
        kind=SpawnerKind.subprocess,
        handle="1",
        metadata={"execution_id": "exec-C"},
    )
    monkeypatch.setattr(
        "temper_ai.spawner.get_spawner", lambda: fake_spawner,
    )

    _start_run_subprocess("exec-C", _request(workspace=None), _config())
    row = _read_row("exec-C")
    assert row["workspace_path"] == ""


# --- cancel_run for subprocess rows ----------------------------------------

def test_cancel_subprocess_run_sets_cancel_requested(isolated_db):
    """cancel_run finds the WorkflowRun row and flips cancel_requested
    rather than touching the in-memory cancel_event dict."""
    # Seed a running subprocess row directly
    with get_session() as session:
        session.add(WorkflowRun(
            execution_id="cancel-me",
            workflow_name="test",
            workspace_path="/tmp",
            status="running",
            spawner_kind="subprocess",
            spawner_handle="42",
        ))

    # Need an AppState — cancel_run reads _state().running before checking
    # the row. Provide an empty registry so it falls through to row lookup.
    from temper_ai.api.app_state import AppState
    from temper_ai.api.routes import init_app_state
    from temper_ai.config import ConfigStore
    from temper_ai.memory import InMemoryStore, MemoryService
    from temper_ai.stage.loader import GraphLoader

    init_app_state(AppState(
        config_store=ConfigStore(),
        graph_loader=GraphLoader(ConfigStore()),
        llm_providers={},
        memory_service=MemoryService(InMemoryStore()),
    ))

    result = cancel_run("cancel-me")
    assert result["status"] == "cancelling"

    row = _read_row("cancel-me")
    assert row["cancel_requested"] is True
    assert row["status"] == "running"  # reaper + worker flip to cancelled
