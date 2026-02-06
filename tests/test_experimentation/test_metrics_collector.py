"""
Tests for experiment metrics collection and analytics.

Tests the integration between the A/B testing framework and the
observability system for metrics collection and reporting.
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.experimentation.metrics_collector import ExperimentMetricsCollector
from src.experimentation.models import ExecutionStatus, VariantAssignment
from src.observability.database import get_session, init_database
from src.observability.models import WorkflowExecution


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    # Reset global database before each test
    import src.observability.database as db_module
    from src.observability.database import _db_lock
    with _db_lock:
        db_module._db_manager = None

    db_manager = init_database("sqlite:///:memory:")
    yield db_manager

    # Clean up after test
    with _db_lock:
        db_module._db_manager = None


@pytest.fixture
def test_session(db):
    """Create test database session."""
    with get_session() as session:
        yield session


@pytest.fixture
def sample_workflows(db):
    """Create sample workflow executions with experiment metadata."""
    now = datetime.now(timezone.utc)

    workflows = [
        # Control variant workflows
        WorkflowExecution(
            id="wf-001",
            workflow_name="test_workflow",
            workflow_config_snapshot={"agent": {"temperature": 0.7}},
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1, minutes=55),
            duration_seconds=300.0,
            status="completed",
            total_cost_usd=0.05,
            total_tokens=1000,
            total_llm_calls=5,
            total_tool_calls=2,
            extra_metadata={
                "experiment_id": "exp-001",
                "variant_id": "var-control",
                "assignment_strategy": "hash",
                "custom_metrics": {"quality_score": 85.0}
            }
        ),
        WorkflowExecution(
            id="wf-002",
            workflow_name="test_workflow",
            workflow_config_snapshot={"agent": {"temperature": 0.7}},
            start_time=now - timedelta(hours=1),
            end_time=now - timedelta(minutes=55),
            duration_seconds=310.0,
            status="completed",
            total_cost_usd=0.06,
            total_tokens=1100,
            total_llm_calls=6,
            total_tool_calls=3,
            extra_metadata={
                "experiment_id": "exp-001",
                "variant_id": "var-control",
                "assignment_strategy": "hash",
                "custom_metrics": {"quality_score": 82.0}
            }
        ),
        # Treatment variant workflows
        WorkflowExecution(
            id="wf-003",
            workflow_name="test_workflow",
            workflow_config_snapshot={"agent": {"temperature": 0.9}},
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1, minutes=50),
            duration_seconds=280.0,
            status="completed",
            total_cost_usd=0.07,
            total_tokens=1200,
            total_llm_calls=7,
            total_tool_calls=4,
            extra_metadata={
                "experiment_id": "exp-001",
                "variant_id": "var-treatment",
                "assignment_strategy": "hash",
                "custom_metrics": {"quality_score": 92.0}
            }
        ),
        WorkflowExecution(
            id="wf-004",
            workflow_name="test_workflow",
            workflow_config_snapshot={"agent": {"temperature": 0.9}},
            start_time=now - timedelta(minutes=30),
            end_time=now - timedelta(minutes=25),
            duration_seconds=285.0,
            status="completed",
            total_cost_usd=0.08,
            total_tokens=1300,
            total_llm_calls=8,
            total_tool_calls=5,
            extra_metadata={
                "experiment_id": "exp-001",
                "variant_id": "var-treatment",
                "assignment_strategy": "hash",
                "custom_metrics": {"quality_score": 95.0}
            }
        ),
        # Failed workflow
        WorkflowExecution(
            id="wf-005",
            workflow_name="test_workflow",
            workflow_config_snapshot={"agent": {"temperature": 0.9}},
            start_time=now - timedelta(minutes=10),
            end_time=now - timedelta(minutes=8),
            duration_seconds=120.0,
            status="failed",
            error_message="Test error",
            total_cost_usd=0.02,
            total_tokens=300,
            total_llm_calls=2,
            total_tool_calls=1,
            extra_metadata={
                "experiment_id": "exp-001",
                "variant_id": "var-treatment",
                "assignment_strategy": "hash",
            }
        ),
    ]

    # Use global get_session to add workflows
    with get_session() as session:
        for workflow in workflows:
            session.add(workflow)
        session.commit()

    return workflows


class TestMetricsCollector:
    """Test experiment metrics collection."""

    def test_collect_assignments_basic(self, test_session, sample_workflows):
        """Test basic assignment collection from workflows."""
        collector = ExperimentMetricsCollector(session=test_session)
        assignments = collector.collect_assignments("exp-001")

        assert len(assignments) == 5
        assert all(isinstance(a, VariantAssignment) for a in assignments)

        # Check control variant assignments
        control_assignments = [a for a in assignments if a.variant_id == "var-control"]
        assert len(control_assignments) == 2

        # Check treatment variant assignments (including failed one)
        treatment_assignments = [a for a in assignments if a.variant_id == "var-treatment"]
        assert len(treatment_assignments) == 3

    def test_collect_assignments_with_status_filter(self, test_session, sample_workflows):
        """Test filtering assignments by execution status."""
        collector = ExperimentMetricsCollector(session=test_session)

        # Filter for completed only
        completed = collector.collect_assignments("exp-001", status="completed")
        assert len(completed) == 4
        assert all(a.execution_status == ExecutionStatus.COMPLETED for a in completed)

        # Filter for failed only
        failed = collector.collect_assignments("exp-001", status="failed")
        assert len(failed) == 1
        assert failed[0].execution_status == ExecutionStatus.FAILED

    def test_extract_metrics_from_workflow(self, test_session, sample_workflows):
        """Test metric extraction from workflow execution."""
        collector = ExperimentMetricsCollector(session=test_session)
        assignments = collector.collect_assignments("exp-001")

        # Check first assignment metrics
        assignment = assignments[0]
        assert assignment.metrics is not None
        assert "duration_seconds" in assignment.metrics
        assert "cost_usd" in assignment.metrics
        assert "total_tokens" in assignment.metrics
        assert "llm_calls" in assignment.metrics
        assert "tool_calls" in assignment.metrics
        assert "quality_score" in assignment.metrics
        assert "error_rate" in assignment.metrics

        # Check values
        assert assignment.metrics["duration_seconds"] == 300.0
        assert assignment.metrics["cost_usd"] == 0.05
        assert assignment.metrics["total_tokens"] == 1000.0
        assert assignment.metrics["quality_score"] == 85.0
        assert assignment.metrics["error_rate"] == 0.0

    def test_extract_metrics_with_failure(self, test_session, sample_workflows):
        """Test metric extraction from failed workflow."""
        collector = ExperimentMetricsCollector(session=test_session)
        failed_assignments = collector.collect_assignments("exp-001", status="failed")

        assert len(failed_assignments) == 1
        assignment = failed_assignments[0]

        # Check error rate is 1.0 for failed workflow
        assert assignment.metrics["error_rate"] == 1.0
        assert assignment.execution_status == ExecutionStatus.FAILED

    def test_aggregate_metrics_by_variant(self, test_session, sample_workflows):
        """Test metrics aggregation grouped by variant."""
        collector = ExperimentMetricsCollector(session=test_session)
        aggregated = collector.aggregate_metrics_by_variant("exp-001")

        assert "var-control" in aggregated
        assert "var-treatment" in aggregated

        # Check control variant aggregation
        control = aggregated["var-control"]
        assert control["count"] == 2
        assert control["successful"] == 2
        assert control["failed"] == 0
        assert control["success_rate"] == 1.0
        assert "avg_duration_seconds" in control
        assert "avg_quality_score" in control

        # Check treatment variant aggregation (2 successful, 1 failed)
        treatment = aggregated["var-treatment"]
        assert treatment["count"] == 3
        assert treatment["successful"] == 2
        assert treatment["failed"] == 1
        assert treatment["success_rate"] == pytest.approx(2/3, rel=0.01)

    def test_aggregate_metric_calculations(self, test_session, sample_workflows):
        """Test correctness of aggregate metric calculations."""
        collector = ExperimentMetricsCollector(session=test_session)
        aggregated = collector.aggregate_metrics_by_variant("exp-001")

        control = aggregated["var-control"]

        # Check average calculations
        # Control: (85.0 + 82.0) / 2 = 83.5
        assert control["avg_quality_score"] == pytest.approx(83.5, rel=0.01)

        # Check sum calculations
        # Control: 1000 + 1100 = 2100
        assert control["sum_total_tokens"] == pytest.approx(2100.0, rel=0.01)

        # Check min/max
        assert control["min_quality_score"] == 82.0
        assert control["max_quality_score"] == 85.0

    def test_get_experiment_summary(self, test_session, sample_workflows):
        """Test comprehensive experiment summary generation."""
        collector = ExperimentMetricsCollector(session=test_session)
        summary = collector.get_experiment_summary("exp-001")

        assert summary["experiment_id"] == "exp-001"
        assert summary["total_executions"] == 5
        assert summary["completed_executions"] == 4
        assert summary["failed_executions"] == 1
        assert summary["running_executions"] == 0
        assert summary["completion_rate"] == pytest.approx(0.8, rel=0.01)
        assert summary["variant_count"] == 2
        assert "variants" in summary
        assert "collected_at" in summary

    def test_query_workflows_by_variant(self, test_session, sample_workflows):
        """Test querying workflows for specific variant."""
        collector = ExperimentMetricsCollector(session=test_session)

        # Query control variant
        control_workflows = collector.query_workflows_by_variant("exp-001", "var-control")
        assert len(control_workflows) == 2
        assert all(w.extra_metadata["variant_id"] == "var-control" for w in control_workflows)

        # Query treatment variant
        treatment_workflows = collector.query_workflows_by_variant("exp-001", "var-treatment")
        assert len(treatment_workflows) == 3
        assert all(w.extra_metadata["variant_id"] == "var-treatment" for w in treatment_workflows)

    def test_query_workflows_with_limit(self, test_session, sample_workflows):
        """Test limit parameter in workflow queries."""
        collector = ExperimentMetricsCollector(session=test_session)

        workflows = collector.query_workflows_by_variant("exp-001", "var-treatment", limit=2)
        assert len(workflows) == 2

    def test_get_time_series_metrics(self, test_session, sample_workflows):
        """Test time-series metrics extraction."""
        collector = ExperimentMetricsCollector(session=test_session)

        time_series = collector.get_time_series_metrics("exp-001", "quality_score")

        assert "var-control" in time_series
        assert "var-treatment" in time_series

        # Check control series has 2 data points
        control_series = time_series["var-control"]
        assert len(control_series) == 2
        assert all(isinstance(ts, datetime) for ts, _ in control_series)
        assert all(isinstance(val, float) for _, val in control_series)

        # Check treatment series has 2 data points (failed workflow has no quality_score)
        treatment_series = time_series["var-treatment"]
        assert len(treatment_series) == 2

    def test_empty_experiment(self, test_session):
        """Test collecting from non-existent experiment."""
        collector = ExperimentMetricsCollector(session=test_session)

        assignments = collector.collect_assignments("exp-nonexistent")
        assert len(assignments) == 0

        aggregated = collector.aggregate_metrics_by_variant("exp-nonexistent")
        assert len(aggregated) == 0

        summary = collector.get_experiment_summary("exp-nonexistent")
        assert summary["total_executions"] == 0
        assert summary["completion_rate"] == 0.0

    def test_assignment_metadata_preserved(self, test_session, sample_workflows):
        """Test that assignment metadata is correctly preserved."""
        collector = ExperimentMetricsCollector(session=test_session)
        assignments = collector.collect_assignments("exp-001")

        for assignment in assignments:
            assert assignment.experiment_id == "exp-001"
            assert assignment.variant_id in ["var-control", "var-treatment"]
            assert assignment.assignment_strategy == "hash"
            assert assignment.workflow_execution_id.startswith("wf-")
            assert assignment.assigned_at is not None
            assert assignment.execution_started_at is not None

    def test_collector_without_session(self, db, sample_workflows):
        """Test collector creates its own sessions when not provided."""
        # Create collector without session (uses global database)
        collector = ExperimentMetricsCollector()

        # Should work without explicitly provided session
        assignments = collector.collect_assignments("exp-001")
        assert len(assignments) > 0


class TestMetricsCollectorEdgeCases:
    """Test edge cases and error handling."""

    def test_workflow_without_variant_id(self, test_session):
        """Test handling of workflows with experiment_id but no variant_id."""
        # Create workflow with experiment_id but missing variant_id
        workflow = WorkflowExecution(
            id="wf-bad",
            workflow_name="test",
            workflow_config_snapshot={},
            start_time=datetime.now(timezone.utc),
            status="running",
            extra_metadata={"experiment_id": "exp-001"}  # Missing variant_id
        )
        test_session.add(workflow)
        test_session.commit()

        collector = ExperimentMetricsCollector(session=test_session)
        assignments = collector.collect_assignments("exp-001")

        # Should be skipped with warning
        assert len(assignments) == 0

    def test_workflow_without_metrics(self, test_session):
        """Test handling of workflows with missing metrics."""
        workflow = WorkflowExecution(
            id="wf-no-metrics",
            workflow_name="test",
            workflow_config_snapshot={},
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            status="completed",
            extra_metadata={
                "experiment_id": "exp-001",
                "variant_id": "var-control"
            }
            # No duration, cost, tokens, etc.
        )
        test_session.add(workflow)
        test_session.commit()

        collector = ExperimentMetricsCollector(session=test_session)
        assignments = collector.collect_assignments("exp-001")

        assert len(assignments) == 1
        assignment = assignments[0]

        # Should handle None values gracefully
        assert assignment.metrics is not None
        assert "error_rate" in assignment.metrics  # Always present

    def test_aggregate_empty_variant(self, test_session):
        """Test aggregating variant with no assignments."""
        collector = ExperimentMetricsCollector(session=test_session)

        # Create aggregation with empty list
        aggregated = collector._aggregate_assignments([])

        assert aggregated["count"] == 0
        assert aggregated["successful"] == 0
        assert aggregated["failed"] == 0
        assert aggregated["success_rate"] == 0.0
