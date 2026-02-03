"""
Tests for observability backend abstraction.
"""
import pytest
from datetime import datetime, timezone

from src.observability.backend import ObservabilityBackend
from src.observability.backends import (
    SQLObservabilityBackend,
    PrometheusObservabilityBackend,
    S3ObservabilityBackend,
)
from src.observability.tracker import ExecutionTracker
from src.observability.database import init_database


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    # Reset global database before each test
    from src.observability.database import _db_manager, _db_lock
    import src.observability.database as db_module
    with _db_lock:
        db_module._db_manager = None

    db_manager = init_database("sqlite:///:memory:")
    yield db_manager

    # Clean up after test
    with _db_lock:
        db_module._db_manager = None


class TestBackendAbstraction:
    """Tests for backend abstraction layer."""

    def test_sql_backend_creation(self, db):
        """Test SQL backend can be created."""
        backend = SQLObservabilityBackend()
        assert isinstance(backend, ObservabilityBackend)

    def test_prometheus_backend_creation(self):
        """Test Prometheus backend can be created."""
        backend = PrometheusObservabilityBackend(push_gateway_url="http://localhost:9091")
        assert isinstance(backend, ObservabilityBackend)
        assert backend.push_gateway_url == "http://localhost:9091"

    def test_s3_backend_creation(self):
        """Test S3 backend can be created."""
        backend = S3ObservabilityBackend(
            bucket_name="test-bucket",
            prefix="observability",
            region="us-west-2"
        )
        assert isinstance(backend, ObservabilityBackend)
        assert backend.bucket_name == "test-bucket"
        assert backend.prefix == "observability"
        assert backend.region == "us-west-2"

    def test_tracker_with_sql_backend(self, db):
        """Test tracker works with SQL backend."""
        backend = SQLObservabilityBackend()
        tracker = ExecutionTracker(backend=backend)

        config = {"workflow": {"name": "test"}}
        with tracker.track_workflow("test_workflow", config) as workflow_id:
            assert workflow_id is not None

    def test_tracker_with_prometheus_backend(self):
        """Test tracker works with Prometheus backend (stub)."""
        backend = PrometheusObservabilityBackend()
        tracker = ExecutionTracker(backend=backend)

        config = {"workflow": {"name": "test"}}
        # Should not raise, just log
        with tracker.track_workflow("test_workflow", config) as workflow_id:
            assert workflow_id is not None

    def test_tracker_with_s3_backend(self):
        """Test tracker works with S3 backend (stub)."""
        backend = S3ObservabilityBackend(bucket_name="test-bucket")
        tracker = ExecutionTracker(backend=backend)

        config = {"workflow": {"name": "test"}}
        # Should not raise, just log
        with tracker.track_workflow("test_workflow", config) as workflow_id:
            assert workflow_id is not None

    def test_tracker_defaults_to_sql_backend(self, db):
        """Test tracker defaults to SQL backend if no backend provided."""
        tracker = ExecutionTracker()  # No backend specified
        assert isinstance(tracker.backend, SQLObservabilityBackend)

    def test_backend_stats(self, db):
        """Test backend stats interface."""
        # SQL backend
        sql_backend = SQLObservabilityBackend()
        stats = sql_backend.get_stats()
        assert stats["backend_type"] == "sql"
        assert "total_workflows" in stats

        # Prometheus backend
        prom_backend = PrometheusObservabilityBackend()
        stats = prom_backend.get_stats()
        assert stats["backend_type"] == "prometheus"
        assert stats["status"] == "stub"

        # S3 backend
        s3_backend = S3ObservabilityBackend(bucket_name="test")
        stats = s3_backend.get_stats()
        assert stats["backend_type"] == "s3"
        assert stats["status"] == "stub"

    def test_sql_backend_cleanup(self, db):
        """Test SQL backend cleanup functionality."""
        backend = SQLObservabilityBackend()

        # Dry run - should return counts without deleting
        counts = backend.cleanup_old_records(retention_days=30, dry_run=True)
        assert isinstance(counts, dict)
        assert "workflows" in counts

    def test_sql_backend_session_context(self, db):
        """Test SQL backend session context management."""
        backend = SQLObservabilityBackend()

        with backend.get_session_context() as session:
            # Should be able to use session
            assert session is not None

    def test_prometheus_backend_no_op_context(self):
        """Test Prometheus backend has no-op context."""
        backend = PrometheusObservabilityBackend()

        with backend.get_session_context() as session:
            # Should be None for stateless backend
            assert session is None

    def test_s3_backend_no_op_context(self):
        """Test S3 backend has no-op context."""
        backend = S3ObservabilityBackend(bucket_name="test")

        with backend.get_session_context() as session:
            # Should be None for stateless backend
            assert session is None


class TestBackendWorkflowExecution:
    """Test workflow execution with different backends."""

    def test_sql_backend_workflow_end_to_end(self, db):
        """Test complete workflow execution with SQL backend."""
        backend = SQLObservabilityBackend()
        tracker = ExecutionTracker(backend=backend)

        config = {"workflow": {"name": "test", "version": "1.0"}}

        with tracker.track_workflow("test_workflow", config) as workflow_id:
            with tracker.track_stage("test_stage", config, workflow_id) as stage_id:
                with tracker.track_agent("test_agent", config, stage_id) as agent_id:
                    # Track LLM call
                    llm_id = tracker.track_llm_call(
                        agent_id=agent_id,
                        provider="ollama",
                        model="test-model",
                        prompt="test prompt",
                        response="test response",
                        prompt_tokens=10,
                        completion_tokens=5,
                        latency_ms=100,
                        estimated_cost_usd=0.001
                    )
                    assert llm_id is not None

                    # Track tool call
                    tool_id = tracker.track_tool_call(
                        agent_id=agent_id,
                        tool_name="calculator",
                        input_params={"a": 1, "b": 2},
                        output_data={"result": 3},
                        duration_seconds=0.01
                    )
                    assert tool_id is not None

    def test_prometheus_backend_workflow_execution(self):
        """Test workflow execution with Prometheus backend (stub)."""
        backend = PrometheusObservabilityBackend(push_gateway_url="http://localhost:9091")
        tracker = ExecutionTracker(backend=backend)

        config = {"workflow": {"name": "test"}}

        # Should not raise, just log
        with tracker.track_workflow("test_workflow", config) as workflow_id:
            with tracker.track_stage("test_stage", config, workflow_id) as stage_id:
                with tracker.track_agent("test_agent", config, stage_id) as agent_id:
                    tracker.track_llm_call(
                        agent_id=agent_id,
                        provider="ollama",
                        model="test-model",
                        prompt="test",
                        response="response",
                        prompt_tokens=10,
                        completion_tokens=5,
                        latency_ms=100,
                        estimated_cost_usd=0.001
                    )
                    tracker.track_tool_call(
                        agent_id=agent_id,
                        tool_name="calculator",
                        input_params={},
                        output_data={},
                        duration_seconds=0.01
                    )

    def test_safety_violation_tracking(self, db):
        """Test safety violation tracking with backend."""
        backend = SQLObservabilityBackend()
        tracker = ExecutionTracker(backend=backend)

        config = {"workflow": {"name": "test"}}

        with tracker.track_workflow("test_workflow", config) as workflow_id:
            with tracker.track_stage("test_stage", config, workflow_id) as stage_id:
                with tracker.track_agent("test_agent", config, stage_id) as agent_id:
                    # Track safety violation
                    tracker.track_safety_violation(
                        violation_severity="HIGH",
                        violation_message="Test violation",
                        policy_name="TestPolicy",
                        service_name="test_service",
                        context={"test": "data"}
                    )

        # Verify violation was tracked (SQL backend specific)
        from src.observability.database import get_session
        from src.observability.models import AgentExecution

        with get_session() as session:
            from sqlmodel import select
            statement = select(AgentExecution).where(AgentExecution.id == agent_id)
            agent = session.exec(statement).first()
            assert agent is not None
            assert agent.extra_metadata is not None
            assert "safety_violations" in agent.extra_metadata
            assert len(agent.extra_metadata["safety_violations"]) == 1
            assert agent.extra_metadata["safety_violations"][0]["severity"] == "HIGH"


class TestCascadeDelete:
    """Test cascade deletion removes all child records when parent is deleted."""

    def test_delete_workflow_cascades_to_all_children(self, db):
        """Deleting a workflow removes all stages, agents, llm_calls, tool_executions."""
        from src.observability.database import get_session
        from src.observability.models import (
            WorkflowExecution, StageExecution, AgentExecution,
            LLMCall, ToolExecution
        )
        from sqlmodel import select, func, delete

        now = datetime.now(timezone.utc)

        # Insert records directly via session to avoid standalone session issues
        with get_session() as session:
            wf = WorkflowExecution(
                id="wf-cascade-1", workflow_name="cascade_test",
                workflow_config_snapshot={"version": "1.0"},
                start_time=now, status="running",
                total_llm_calls=0, total_tool_calls=0,
                total_tokens=0, total_cost_usd=0.0,
            )
            session.add(wf)
            session.commit()

            st = StageExecution(
                id="st-cascade-1", workflow_execution_id="wf-cascade-1",
                stage_name="test_stage", stage_config_snapshot={"stage": {"version": "1.0"}},
                start_time=now, status="running",
            )
            session.add(st)
            session.commit()

            ag = AgentExecution(
                id="ag-cascade-1", stage_execution_id="st-cascade-1",
                agent_name="test_agent", agent_config_snapshot={"agent": {"version": "1.0"}},
                start_time=now, status="running",
            )
            session.add(ag)
            session.commit()

            llm = LLMCall(
                id="llm-cascade-1", agent_execution_id="ag-cascade-1",
                provider="test", model="test-model",
                prompt="hello", response="world",
                prompt_tokens=5, completion_tokens=5, total_tokens=10,
                latency_ms=100, estimated_cost_usd=0.001,
                start_time=now, status="success",
            )
            session.add(llm)
            session.commit()

            tool = ToolExecution(
                id="tool-cascade-1", agent_execution_id="ag-cascade-1",
                tool_name="calculator",
                input_params={"expression": "2+2"},
                output_data={"result": 4},
                start_time=now, duration_seconds=0.01, status="success",
            )
            session.add(tool)
            session.commit()

        # Verify all records exist
        with get_session() as session:
            assert session.exec(select(func.count(WorkflowExecution.id)).where(
                WorkflowExecution.id == "wf-cascade-1")).first() == 1
            assert session.exec(select(func.count(StageExecution.id)).where(
                StageExecution.workflow_execution_id == "wf-cascade-1")).first() == 1
            assert session.exec(select(func.count(AgentExecution.id)).where(
                AgentExecution.stage_execution_id == "st-cascade-1")).first() == 1
            assert session.exec(select(func.count(LLMCall.id)).where(
                LLMCall.agent_execution_id == "ag-cascade-1")).first() == 1
            assert session.exec(select(func.count(ToolExecution.id)).where(
                ToolExecution.agent_execution_id == "ag-cascade-1")).first() == 1

        # Delete workflow via raw SQL DELETE (same as cleanup_old_records)
        with get_session() as session:
            session.exec(
                delete(WorkflowExecution).where(WorkflowExecution.id == "wf-cascade-1")
            )
            session.commit()

        # Verify ALL child records are gone (no orphans)
        with get_session() as session:
            assert session.exec(select(func.count(WorkflowExecution.id)).where(
                WorkflowExecution.id == "wf-cascade-1")).first() == 0
            assert session.exec(select(func.count(StageExecution.id)).where(
                StageExecution.id == "st-cascade-1")).first() == 0
            assert session.exec(select(func.count(AgentExecution.id)).where(
                AgentExecution.id == "ag-cascade-1")).first() == 0
            assert session.exec(select(func.count(LLMCall.id)).where(
                LLMCall.id == "llm-cascade-1")).first() == 0
            assert session.exec(select(func.count(ToolExecution.id)).where(
                ToolExecution.id == "tool-cascade-1")).first() == 0

    def test_delete_stage_does_not_cascade_up(self, db):
        """Deleting a stage should NOT delete its parent workflow."""
        backend = SQLObservabilityBackend(buffer=False)
        now = datetime.now(timezone.utc)

        with backend.get_session_context() as session:
            backend.track_workflow_start(
                workflow_id="wf-up-1",
                workflow_name="cascade_up_test",
                workflow_config={"version": "1.0"},
                start_time=now,
            )

        backend.track_stage_start(
            stage_id="st-up-1",
            workflow_id="wf-up-1",
            stage_name="test_stage",
            stage_config={"stage": {"version": "1.0"}},
            start_time=now,
        )

        from src.observability.database import get_session
        from src.observability.models import WorkflowExecution, StageExecution
        from sqlmodel import select, func, delete

        # Delete stage
        with get_session() as session:
            session.exec(delete(StageExecution).where(StageExecution.id == "st-up-1"))
            session.commit()

        # Workflow should still exist
        with get_session() as session:
            assert session.exec(select(func.count(WorkflowExecution.id)).where(
                WorkflowExecution.id == "wf-up-1")).first() == 1
            # But stage should be gone
            assert session.exec(select(func.count(StageExecution.id)).where(
                StageExecution.id == "st-up-1")).first() == 0

    def test_cleanup_old_records_no_orphans(self, db):
        """cleanup_old_records deletes workflows and all nested records."""
        from datetime import timedelta
        backend = SQLObservabilityBackend(buffer=False)
        old_time = datetime.now(timezone.utc) - timedelta(days=100)

        # Create old workflow with children
        with backend.get_session_context() as session:
            backend.track_workflow_start(
                workflow_id="wf-old-1",
                workflow_name="old_workflow",
                workflow_config={"version": "1.0"},
                start_time=old_time,
            )

        backend.track_stage_start(
            stage_id="st-old-1",
            workflow_id="wf-old-1",
            stage_name="old_stage",
            stage_config={"stage": {"version": "1.0"}},
            start_time=old_time,
        )

        backend.track_agent_start(
            agent_id="ag-old-1",
            stage_id="st-old-1",
            agent_name="old_agent",
            agent_config={"agent": {"version": "1.0"}},
            start_time=old_time,
        )

        # Run cleanup with 30-day retention
        counts = backend.cleanup_old_records(retention_days=30)
        assert counts["workflows"] == 1

        # Verify no orphans remain
        from src.observability.database import get_session
        from src.observability.models import StageExecution, AgentExecution
        from sqlmodel import select, func

        with get_session() as session:
            assert session.exec(select(func.count(StageExecution.id)).where(
                StageExecution.id == "st-old-1")).first() == 0
            assert session.exec(select(func.count(AgentExecution.id)).where(
                AgentExecution.id == "ag-old-1")).first() == 0
