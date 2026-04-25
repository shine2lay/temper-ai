"""Tests for the WorkflowRun SQLModel — server-side spawner tracking."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from temper_ai.runner import WorkflowRun


@pytest.fixture
def session():
    """In-memory SQLite session, isolated per test."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class TestWorkflowRunModel:
    def test_minimal_insert_and_read(self, session):
        run = WorkflowRun(
            execution_id="abc-123",
            workflow_name="garmin",
            workspace_path="/workspaces/garmin/main",
        )
        session.add(run)
        session.commit()

        loaded = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == "abc-123")
        ).one()
        assert loaded.workflow_name == "garmin"
        assert loaded.status == "queued"
        assert loaded.cancel_requested is False
        assert loaded.attempts == 0
        assert loaded.max_attempts == 1
        assert loaded.inputs == {}

    def test_status_transitions_persist(self, session):
        run = WorkflowRun(
            execution_id="abc-123",
            workflow_name="garmin",
            workspace_path="/workspaces/garmin/main",
        )
        session.add(run)
        session.commit()

        # Spawn
        run.status = "running"
        run.spawner_kind = "subprocess"
        run.spawner_handle = "12345"
        run.started_at = datetime.now(UTC)
        session.commit()

        loaded = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == "abc-123")
        ).one()
        assert loaded.status == "running"
        assert loaded.spawner_kind == "subprocess"
        assert loaded.spawner_handle == "12345"

    def test_inputs_jsonb_roundtrip(self, session):
        run = WorkflowRun(
            execution_id="abc-123",
            workflow_name="garmin",
            workspace_path="/workspaces/garmin/main",
            inputs={"target": "build app", "max_sprints": 5},
        )
        session.add(run)
        session.commit()

        loaded = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == "abc-123")
        ).one()
        assert loaded.inputs["target"] == "build app"
        assert loaded.inputs["max_sprints"] == 5

    def test_cancel_request_default_false(self, session):
        run = WorkflowRun(
            execution_id="abc-123",
            workflow_name="garmin",
            workspace_path="/workspaces/garmin/main",
        )
        session.add(run)
        session.commit()
        loaded = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == "abc-123")
        ).one()
        assert loaded.cancel_requested is False

    def test_query_running_runs(self, session):
        for i in range(5):
            run = WorkflowRun(
                execution_id=f"run-{i}",
                workflow_name="garmin",
                workspace_path=f"/workspaces/{i}/main",
                status="running" if i % 2 == 0 else "completed",
            )
            session.add(run)
        session.commit()

        running = session.exec(
            select(WorkflowRun).where(WorkflowRun.status == "running")
        ).all()
        assert len(running) == 3  # i=0, 2, 4

    def test_terminal_payloads(self, session):
        run = WorkflowRun(
            execution_id="abc-123",
            workflow_name="garmin",
            workspace_path="/workspaces/garmin/main",
            status="failed",
            error={"type": "TimeoutError", "message": "deadline exceeded"},
        )
        session.add(run)
        session.commit()

        loaded = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == "abc-123")
        ).one()
        assert loaded.error["type"] == "TimeoutError"
        assert loaded.result is None
