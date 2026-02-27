"""Tests for code-high-cascade-delete-27.

Verifies that ON DELETE CASCADE is configured on all foreign keys referencing
parent execution records, so that cleanup_old_records leaves no orphaned rows
in DecisionOutcome, RollbackSnapshotDB, or RollbackEvent tables.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from temper_ai.storage.database.manager import (
    get_session,
    init_database,
    reset_database,
)
from temper_ai.storage.database.models import (
    AgentExecution,
    DecisionOutcome,
    LLMCall,
    RollbackEvent,
    RollbackSnapshotDB,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh in-memory database for each test."""
    import temper_ai.storage.database.manager as db_module
    from temper_ai.storage.database.manager import _db_lock

    with _db_lock:
        db_module._db_manager = None

    init_database("sqlite:///:memory:")
    yield
    reset_database()


def _make_workflow(wf_id: str, old: bool = False) -> WorkflowExecution:
    """Create a WorkflowExecution, optionally backdated."""
    now = datetime.now(UTC)
    start = now - timedelta(days=90) if old else now
    return WorkflowExecution(
        id=wf_id,
        workflow_name="test",
        workflow_config_snapshot={},
        start_time=start,
        end_time=start + timedelta(minutes=5),
        duration_seconds=300.0,
        status="completed",
        total_cost_usd=0.01,
        total_tokens=100,
        total_llm_calls=1,
        total_tool_calls=0,
    )


class TestDecisionOutcomeCascade:
    """Verify DecisionOutcome rows are cascade-deleted with their parent."""

    def test_decision_outcome_deleted_with_workflow(self):
        """Deleting a workflow should cascade-delete its DecisionOutcome rows."""
        wf_id = f"wf-{uuid4().hex[:8]}"
        with get_session() as session:
            wf = _make_workflow(wf_id)
            session.add(wf)
            session.flush()

            outcome = DecisionOutcome(
                id=f"do-{uuid4().hex[:8]}",
                workflow_execution_id=wf_id,
                decision_type="test",
                decision_data={"key": "value"},
                outcome="success",
            )
            session.add(outcome)
            session.commit()

        # Verify it exists
        with get_session() as session:
            count = session.query(DecisionOutcome).count()
            assert count == 1

        # Delete workflow via raw SQL (same as cleanup_old_records)
        from sqlalchemy import delete

        with get_session() as session:
            session.exec(delete(WorkflowExecution).where(WorkflowExecution.id == wf_id))
            session.commit()

        # DecisionOutcome should be gone
        with get_session() as session:
            count = session.query(DecisionOutcome).count()
            assert count == 0, "DecisionOutcome should be cascade-deleted with workflow"

    def test_decision_outcome_deleted_with_agent(self):
        """Deleting an agent should cascade-delete its DecisionOutcome rows."""
        wf_id = f"wf-{uuid4().hex[:8]}"
        stage_id = f"stage-{uuid4().hex[:8]}"
        agent_id = f"agent-{uuid4().hex[:8]}"

        with get_session() as session:
            wf = _make_workflow(wf_id)
            session.add(wf)
            session.flush()

            stage = StageExecution(
                id=stage_id,
                workflow_execution_id=wf_id,
                stage_name="test-stage",
                stage_config_snapshot={},
                start_time=datetime.now(UTC),
                status="completed",
            )
            session.add(stage)
            session.flush()

            agent = AgentExecution(
                id=agent_id,
                stage_execution_id=stage_id,
                agent_name="test-agent",
                agent_config_snapshot={},
                start_time=datetime.now(UTC),
                status="completed",
            )
            session.add(agent)
            session.flush()

            outcome = DecisionOutcome(
                id=f"do-{uuid4().hex[:8]}",
                agent_execution_id=agent_id,
                decision_type="test",
                decision_data={},
                outcome="success",
            )
            session.add(outcome)
            session.commit()

        # Delete workflow (cascades: workflow → stage → agent → decision_outcome)
        from sqlalchemy import delete

        with get_session() as session:
            session.exec(delete(WorkflowExecution).where(WorkflowExecution.id == wf_id))
            session.commit()

        with get_session() as session:
            assert session.query(DecisionOutcome).count() == 0
            assert session.query(AgentExecution).count() == 0
            assert session.query(StageExecution).count() == 0


class TestRollbackSnapshotCascade:
    """Verify RollbackSnapshotDB rows are cascade-deleted with their parent."""

    def test_rollback_snapshot_deleted_with_workflow(self):
        """Deleting a workflow should cascade-delete its RollbackSnapshotDB rows."""
        wf_id = f"wf-{uuid4().hex[:8]}"
        with get_session() as session:
            wf = _make_workflow(wf_id)
            session.add(wf)
            session.flush()

            snapshot = RollbackSnapshotDB(
                id=f"snap-{uuid4().hex[:8]}",
                workflow_execution_id=wf_id,
                action={"type": "deploy"},
                context={"env": "test"},
                file_snapshots={},
                state_snapshots={},
            )
            session.add(snapshot)
            session.commit()

        with get_session() as session:
            assert session.query(RollbackSnapshotDB).count() == 1

        from sqlalchemy import delete

        with get_session() as session:
            session.exec(delete(WorkflowExecution).where(WorkflowExecution.id == wf_id))
            session.commit()

        with get_session() as session:
            assert (
                session.query(RollbackSnapshotDB).count() == 0
            ), "RollbackSnapshotDB should be cascade-deleted with workflow"


class TestRollbackEventCascade:
    """Verify RollbackEvent rows are cascade-deleted with their snapshot."""

    def test_rollback_event_deleted_with_snapshot(self):
        """Deleting a workflow should cascade: workflow → snapshot → event."""
        wf_id = f"wf-{uuid4().hex[:8]}"
        snap_id = f"snap-{uuid4().hex[:8]}"

        with get_session() as session:
            wf = _make_workflow(wf_id)
            session.add(wf)
            session.flush()

            snapshot = RollbackSnapshotDB(
                id=snap_id,
                workflow_execution_id=wf_id,
                action={"type": "deploy"},
                context={},
                file_snapshots={},
                state_snapshots={},
            )
            session.add(snapshot)
            session.flush()

            event = RollbackEvent(
                id=f"evt-{uuid4().hex[:8]}",
                snapshot_id=snap_id,
                status="completed",
                trigger="auto",
                reverted_items=["file1.py"],
                failed_items=[],
                errors=[],
            )
            session.add(event)
            session.commit()

        with get_session() as session:
            assert session.query(RollbackEvent).count() == 1

        from sqlalchemy import delete

        with get_session() as session:
            session.exec(delete(WorkflowExecution).where(WorkflowExecution.id == wf_id))
            session.commit()

        with get_session() as session:
            assert session.query(RollbackSnapshotDB).count() == 0
            assert (
                session.query(RollbackEvent).count() == 0
            ), "RollbackEvent should be cascade-deleted via snapshot → workflow chain"


class TestFullHierarchyCascade:
    """Verify complete cascade from workflow down through all descendants."""

    def test_full_hierarchy_cascade_on_delete(self):
        """Delete a workflow and verify ALL descendant records are removed."""
        wf_id = f"wf-{uuid4().hex[:8]}"
        stage_id = f"stage-{uuid4().hex[:8]}"
        agent_id = f"agent-{uuid4().hex[:8]}"
        llm_id = f"llm-{uuid4().hex[:8]}"
        tool_id = f"tool-{uuid4().hex[:8]}"
        do_id = f"do-{uuid4().hex[:8]}"
        snap_id = f"snap-{uuid4().hex[:8]}"
        evt_id = f"evt-{uuid4().hex[:8]}"
        now = datetime.now(UTC)

        with get_session() as session:
            session.add(_make_workflow(wf_id))
            session.flush()

            session.add(
                StageExecution(
                    id=stage_id,
                    workflow_execution_id=wf_id,
                    stage_name="s1",
                    stage_config_snapshot={},
                    start_time=now,
                    status="completed",
                )
            )
            session.flush()

            session.add(
                AgentExecution(
                    id=agent_id,
                    stage_execution_id=stage_id,
                    agent_name="a1",
                    agent_config_snapshot={},
                    start_time=now,
                    status="completed",
                )
            )
            session.flush()

            session.add(
                LLMCall(
                    id=llm_id,
                    agent_execution_id=agent_id,
                    model="test-model",
                    provider="test",
                    start_time=now,
                    status="success",
                )
            )
            session.add(
                ToolExecution(
                    id=tool_id,
                    agent_execution_id=agent_id,
                    tool_name="test-tool",
                    start_time=now,
                    status="success",
                )
            )
            session.add(
                DecisionOutcome(
                    id=do_id,
                    workflow_execution_id=wf_id,
                    decision_type="test",
                    decision_data={},
                    outcome="success",
                )
            )
            session.add(
                RollbackSnapshotDB(
                    id=snap_id,
                    workflow_execution_id=wf_id,
                    action={},
                    context={},
                    file_snapshots={},
                    state_snapshots={},
                )
            )
            session.flush()
            session.add(
                RollbackEvent(
                    id=evt_id,
                    snapshot_id=snap_id,
                    status="completed",
                    trigger="auto",
                    reverted_items=[],
                    failed_items=[],
                    errors=[],
                )
            )
            session.commit()

        # Verify all records exist
        with get_session() as session:
            assert session.query(WorkflowExecution).count() == 1
            assert session.query(StageExecution).count() == 1
            assert session.query(AgentExecution).count() == 1
            assert session.query(LLMCall).count() == 1
            assert session.query(ToolExecution).count() == 1
            assert session.query(DecisionOutcome).count() == 1
            assert session.query(RollbackSnapshotDB).count() == 1
            assert session.query(RollbackEvent).count() == 1

        # Delete workflow
        from sqlalchemy import delete

        with get_session() as session:
            session.exec(delete(WorkflowExecution).where(WorkflowExecution.id == wf_id))
            session.commit()

        # Verify ALL records are gone
        with get_session() as session:
            assert session.query(WorkflowExecution).count() == 0
            assert session.query(StageExecution).count() == 0
            assert session.query(AgentExecution).count() == 0
            assert session.query(LLMCall).count() == 0
            assert session.query(ToolExecution).count() == 0
            assert session.query(DecisionOutcome).count() == 0
            assert session.query(RollbackSnapshotDB).count() == 0
            assert session.query(RollbackEvent).count() == 0
