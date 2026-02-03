"""Tests for code-high-n1-query-32.

Verifies that metrics_collector uses database-side JSON filtering instead
of fetching all workflows and filtering in Python, and that
get_experiment_summary avoids the double-query by passing pre-fetched
assignments to aggregate_metrics_by_variant.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from src.experimentation.metrics_collector import ExperimentMetricsCollector
from src.experimentation.models import VariantAssignment, ExecutionStatus
from src.observability.models import WorkflowExecution
from src.observability.database import init_database, get_session


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    from src.observability.database import _db_lock
    import src.observability.database as db_module
    with _db_lock:
        db_module._db_manager = None

    db_manager = init_database("sqlite:///:memory:")
    yield db_manager

    with _db_lock:
        db_module._db_manager = None


@pytest.fixture
def test_session(db):
    """Create test database session."""
    with get_session() as session:
        yield session


def _create_workflow(wf_id, experiment_id=None, variant_id=None, status="completed"):
    """Helper to create a WorkflowExecution with experiment metadata."""
    now = datetime.now(timezone.utc)
    metadata = {}
    if experiment_id:
        metadata["experiment_id"] = experiment_id
    if variant_id:
        metadata["variant_id"] = variant_id

    return WorkflowExecution(
        id=wf_id,
        workflow_name="test_wf",
        workflow_config_snapshot={},
        start_time=now - timedelta(hours=1),
        end_time=now,
        duration_seconds=60.0,
        status=status,
        total_cost_usd=0.01,
        total_tokens=100,
        total_llm_calls=1,
        total_tool_calls=0,
        extra_metadata=metadata if metadata else None,
    )


class TestDatabaseSideFiltering:
    """Verify json_extract is used for database-side filtering."""

    def test_only_target_experiment_workflows_returned(self, db):
        """collect_assignments should only return workflows for the target experiment."""
        with get_session() as session:
            # Create 10 workflows for target experiment
            for i in range(10):
                session.add(_create_workflow(f"wf-target-{i}", "exp-target", f"var-{i % 2}"))

            # Create 100 workflows for OTHER experiments
            for i in range(100):
                session.add(_create_workflow(f"wf-other-{i}", "exp-other", f"var-other-{i % 3}"))

            # Create 50 workflows with NO experiment metadata
            for i in range(50):
                session.add(_create_workflow(f"wf-none-{i}"))

            session.commit()

        collector = ExperimentMetricsCollector()
        assignments = collector.collect_assignments("exp-target")

        assert len(assignments) == 10
        for a in assignments:
            assert a.experiment_id == "exp-target"

    def test_query_workflows_by_variant_filtered(self, db):
        """query_workflows_by_variant should filter at database level."""
        with get_session() as session:
            for i in range(5):
                session.add(_create_workflow(f"wf-v1-{i}", "exp-1", "var-1"))
            for i in range(15):
                session.add(_create_workflow(f"wf-v2-{i}", "exp-1", "var-2"))
            for i in range(50):
                session.add(_create_workflow(f"wf-other-{i}", "exp-other", "var-x"))
            session.commit()

        # Use session-based collector to avoid DetachedInstanceError on returned ORM objects
        with get_session() as session:
            collector = ExperimentMetricsCollector(session=session)
            workflows = collector.query_workflows_by_variant("exp-1", "var-1")

            # Should return exactly 5 workflows for var-1 (not 15 for var-2 or 50 others)
            assert len(workflows) == 5
            for w in workflows:
                assert w.extra_metadata["variant_id"] == "var-1"

    def test_query_workflows_by_variant_with_limit(self, db):
        """query_workflows_by_variant respects limit parameter."""
        with get_session() as session:
            for i in range(20):
                session.add(_create_workflow(f"wf-limit-{i}", "exp-1", "var-1"))
            session.commit()

        collector = ExperimentMetricsCollector()
        workflows = collector.query_workflows_by_variant("exp-1", "var-1", limit=5)

        assert len(workflows) == 5


class TestDoubleQueryElimination:
    """Verify get_experiment_summary avoids calling collect_assignments twice."""

    def test_summary_calls_collect_once(self, db):
        """get_experiment_summary should call collect_assignments only once."""
        with get_session() as session:
            session.add(_create_workflow("wf-1", "exp-1", "var-1"))
            session.add(_create_workflow("wf-2", "exp-1", "var-2"))
            session.commit()

        collector = ExperimentMetricsCollector()

        with patch.object(collector, 'collect_assignments', wraps=collector.collect_assignments) as mock_collect:
            summary = collector.get_experiment_summary("exp-1")

            # Should be called exactly once (not twice)
            assert mock_collect.call_count == 1

        assert summary["total_executions"] == 2
        assert summary["variant_count"] == 2

    def test_aggregate_accepts_prefetched_assignments(self, db):
        """aggregate_metrics_by_variant should accept pre-fetched assignments."""
        with get_session() as session:
            session.add(_create_workflow("wf-1", "exp-1", "var-1"))
            session.add(_create_workflow("wf-2", "exp-1", "var-1"))
            session.add(_create_workflow("wf-3", "exp-1", "var-2"))
            session.commit()

        collector = ExperimentMetricsCollector()
        assignments = collector.collect_assignments("exp-1")

        # Pass pre-fetched assignments — should not query DB again
        with patch.object(collector, 'collect_assignments') as mock_collect:
            metrics = collector.aggregate_metrics_by_variant("exp-1", assignments=assignments)

            # Should NOT be called since assignments were provided
            mock_collect.assert_not_called()

        assert "var-1" in metrics
        assert "var-2" in metrics
        assert metrics["var-1"]["count"] == 2
        assert metrics["var-2"]["count"] == 1


class TestResultConsistency:
    """Verify filtered results match the previous Python-filtered behavior."""

    def test_status_filter_works(self, db):
        """Status filter should still work with json_extract filtering."""
        with get_session() as session:
            session.add(_create_workflow("wf-ok-1", "exp-1", "var-1", status="completed"))
            session.add(_create_workflow("wf-ok-2", "exp-1", "var-1", status="completed"))
            session.add(_create_workflow("wf-fail", "exp-1", "var-1", status="failed"))
            session.commit()

        collector = ExperimentMetricsCollector()

        completed = collector.collect_assignments("exp-1", status="completed")
        assert len(completed) == 2

        failed = collector.collect_assignments("exp-1", status="failed")
        assert len(failed) == 1

    def test_empty_experiment_returns_empty(self, db):
        """Non-existent experiment should return empty list."""
        with get_session() as session:
            session.add(_create_workflow("wf-1", "exp-other", "var-1"))
            session.commit()

        collector = ExperimentMetricsCollector()
        assignments = collector.collect_assignments("exp-nonexistent")
        assert assignments == []

    def test_metrics_correctly_extracted(self, db):
        """Metrics extraction should work with json_extract filtering."""
        with get_session() as session:
            session.add(_create_workflow("wf-1", "exp-1", "var-1"))
            session.commit()

        collector = ExperimentMetricsCollector()
        assignments = collector.collect_assignments("exp-1")

        assert len(assignments) == 1
        a = assignments[0]
        assert a.metrics["duration_seconds"] == 60.0
        assert a.metrics["cost_usd"] == 0.01
        assert a.metrics["total_tokens"] == 100.0
