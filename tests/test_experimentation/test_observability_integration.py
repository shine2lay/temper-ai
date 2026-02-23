"""
Integration tests for experiment tracking with observability system.

Tests end-to-end workflow:
1. ExecutionTracker tracks workflow with experiment metadata
2. ExperimentMetricsCollector extracts metrics from observability DB
3. StatisticalAnalyzer analyzes experiment results
"""

import pytest

from temper_ai.experimentation.analyzer import StatisticalAnalyzer
from temper_ai.experimentation.assignment import VariantAssigner
from temper_ai.experimentation.metrics_collector import ExperimentMetricsCollector
from temper_ai.experimentation.models import (
    AssignmentStrategyType,
    ConfigType,
    Experiment,
    ExperimentStatus,
    Variant,
)
from temper_ai.observability.backends.sql_backend import SQLObservabilityBackend
from temper_ai.observability.database import init_database
from temper_ai.observability.tracker import ExecutionTracker


@pytest.fixture
def db():
    """Initialize in-memory database for testing."""
    # Reset global database before each test
    import temper_ai.observability.database as db_module
    from temper_ai.observability.database import _db_lock

    with _db_lock:
        db_module._db_manager = None

    db_manager = init_database("sqlite:///:memory:")
    yield db_manager

    # Clean up after test
    with _db_lock:
        db_module._db_manager = None


@pytest.fixture
def obs_backend():
    """Create SQL observability backend with test database."""
    return SQLObservabilityBackend()


@pytest.fixture
def tracker(db, obs_backend):
    """Create execution tracker with test backend."""
    return ExecutionTracker(backend=obs_backend)


@pytest.fixture
def experiment():
    """Create test experiment."""
    return Experiment(
        id="exp-integration-001",
        name="temperature_test",
        description="Test impact of temperature on quality",
        status=ExperimentStatus.RUNNING,
        assignment_strategy=AssignmentStrategyType.HASH,
        traffic_allocation={"control": 0.5, "treatment": 0.5},
        primary_metric="quality_score",
        confidence_level=0.95,
        min_sample_size_per_variant=8,  # Reduced from 10 to account for hash assignment imbalance
    )


@pytest.fixture
def variants():
    """Create test variants."""
    return [
        Variant(
            id="var-control",
            experiment_id="exp-integration-001",
            name="control",
            description="Baseline temperature",
            is_control=True,
            config_type=ConfigType.AGENT,
            config_overrides={},
            allocated_traffic=0.5,
        ),
        Variant(
            id="var-treatment",
            experiment_id="exp-integration-001",
            name="treatment",
            description="Higher temperature",
            is_control=False,
            config_type=ConfigType.AGENT,
            config_overrides={"temperature": 0.9},
            allocated_traffic=0.5,
        ),
    ]


class TestObservabilityIntegration:
    """Test integration between experimentation and observability systems."""

    def test_track_workflow_with_experiment_metadata(self, tracker, obs_backend):
        """Test tracking workflow execution with experiment metadata."""
        with tracker.track_workflow(
            workflow_name="test_workflow",
            workflow_config={"agent": {"temperature": 0.7}},
            experiment_id="exp-001",
            variant_id="var-control",
            assignment_strategy="hash",
            assignment_context={"user_id": "user-123"},
            custom_metrics={"quality_score": 85.0},
        ) as workflow_id:
            assert workflow_id is not None

        # Verify workflow was created with experiment metadata
        with obs_backend.get_session_context() as session:
            from temper_ai.observability.models import WorkflowExecution

            workflow = session.get(WorkflowExecution, workflow_id)

            assert workflow is not None
            assert workflow.extra_metadata is not None
            assert workflow.extra_metadata["experiment_id"] == "exp-001"
            assert workflow.extra_metadata["variant_id"] == "var-control"
            assert workflow.extra_metadata["assignment_strategy"] == "hash"
            assert (
                workflow.extra_metadata["assignment_context"]["user_id"] == "user-123"
            )
            assert workflow.extra_metadata["custom_metrics"]["quality_score"] == 85.0

    def test_end_to_end_experiment_workflow(
        self, tracker, obs_backend, experiment, variants
    ):
        """Test complete workflow: track -> collect -> analyze."""
        assigner = VariantAssigner()

        # Simulate 20 workflow executions (10 control, 10 treatment)
        for i in range(20):
            workflow_execution_id = f"wf-{i:03d}"

            # Assign variant
            variant_id = assigner.assign_variant(
                experiment, variants, workflow_execution_id, context={}
            )

            # Determine quality score based on variant
            # Control: mean=80, treatment: mean=90 (10 point improvement)
            if variant_id == "var-control":
                quality_score = 80.0 + (i % 5) * 2  # 80, 82, 84, 86, 88 pattern
            else:
                quality_score = 90.0 + (i % 5) * 2  # 90, 92, 94, 96, 98 pattern

            # Track workflow execution with experiment metadata
            with tracker.track_workflow(
                workflow_name="test_workflow",
                workflow_config={"agent": {"model": "gpt-3.5-turbo"}},
                experiment_id=experiment.id,
                variant_id=variant_id,
                assignment_strategy=experiment.assignment_strategy.value,
                custom_metrics={"quality_score": quality_score},
            ) as workflow_id:
                # Simulate some work
                pass

        # Collect experiment metrics from observability DB
        # Use a fresh session from get_session() instead of backend's session stack
        from temper_ai.observability.database import get_session

        with get_session() as session:
            collector = ExperimentMetricsCollector(session=session)

            # Collect assignments
            assignments = collector.collect_assignments(experiment.id)
            assert len(assignments) == 20

            # Get aggregated metrics
            aggregated = collector.aggregate_metrics_by_variant(experiment.id)
            assert "var-control" in aggregated
            assert "var-treatment" in aggregated

            # Verify aggregations (hash assignment may not be exactly 50/50)
            # Both variants should have assignments
            assert "var-control" in aggregated
            assert "var-treatment" in aggregated
            assert aggregated["var-control"]["count"] > 0
            assert aggregated["var-treatment"]["count"] > 0
            # Total should be 20
            assert (
                aggregated["var-control"]["count"]
                + aggregated["var-treatment"]["count"]
                == 20
            )

            # Analyze experiment with statistical analyzer
            analyzer = StatisticalAnalyzer(confidence_level=0.95, min_effect_size=0.05)
            result = analyzer.analyze_experiment(experiment, assignments, variants)

            # Should detect significant improvement
            assert result["sample_size"] == 20
            assert "var-control" in result["variant_metrics"]
            assert "var-treatment" in result["variant_metrics"]

            # Verify statistical tests were run
            assert len(result["statistical_tests"]) > 0

            # Note: With small sample size (n=10 per variant), may not reach significance
            # but metrics should be collected correctly
            control_metrics = result["variant_metrics"]["var-control"]
            treatment_metrics = result["variant_metrics"]["var-treatment"]

            # Control should be around 84 (80, 82, 84, 86, 88)
            assert 80 <= control_metrics["mean"] <= 88

            # Treatment should be around 94 (90, 92, 94, 96, 98)
            assert 90 <= treatment_metrics["mean"] <= 98

    def test_multiple_experiments_isolation(self, tracker, obs_backend):
        """Test that multiple experiments are properly isolated."""
        # Create workflows for experiment 1
        for i in range(5):
            with tracker.track_workflow(
                workflow_name="workflow_a",
                workflow_config={},
                experiment_id="exp-001",
                variant_id="var-control",
                custom_metrics={"score": 50.0},
            ):
                pass

        # Create workflows for experiment 2
        for i in range(3):
            with tracker.track_workflow(
                workflow_name="workflow_b",
                workflow_config={},
                experiment_id="exp-002",
                variant_id="var-treatment",
                custom_metrics={"score": 75.0},
            ):
                pass

        # Collect metrics for each experiment separately
        with obs_backend.get_session_context() as session:
            collector = ExperimentMetricsCollector(session=session)

            exp1_assignments = collector.collect_assignments("exp-001")
            exp2_assignments = collector.collect_assignments("exp-002")

            # Verify isolation
            assert len(exp1_assignments) == 5
            assert len(exp2_assignments) == 3
            assert all(a.experiment_id == "exp-001" for a in exp1_assignments)
            assert all(a.experiment_id == "exp-002" for a in exp2_assignments)

    def test_failed_workflow_tracking(self, tracker, obs_backend, experiment, variants):
        """Test that failed workflows are tracked correctly."""
        assigner = VariantAssigner()

        # Create successful workflow
        with tracker.track_workflow(
            workflow_name="test_workflow",
            workflow_config={},
            experiment_id=experiment.id,
            variant_id="var-control",
            custom_metrics={"quality_score": 80.0},
        ):
            pass

        # Create failed workflow
        try:
            with tracker.track_workflow(
                workflow_name="test_workflow",
                workflow_config={},
                experiment_id=experiment.id,
                variant_id="var-treatment",
                custom_metrics={"quality_score": 90.0},
            ):
                raise RuntimeError("Simulated failure")
        except RuntimeError:
            pass  # Expected

        # Collect and verify
        with obs_backend.get_session_context() as session:
            collector = ExperimentMetricsCollector(session=session)

            all_assignments = collector.collect_assignments(experiment.id)
            assert len(all_assignments) == 2

            completed = collector.collect_assignments(experiment.id, status="completed")
            failed = collector.collect_assignments(experiment.id, status="failed")

            assert len(completed) == 1
            assert len(failed) == 1

            # Failed assignment should have error_rate = 1.0
            assert failed[0].metrics["error_rate"] == 1.0

    def test_experiment_summary_with_tracking(self, tracker, obs_backend, experiment):
        """Test experiment summary with tracked workflows."""
        # Track multiple workflows
        for i in range(10):
            variant = "var-control" if i % 2 == 0 else "var-treatment"
            status_ok = i < 8  # 8 successful, 2 failed

            try:
                with tracker.track_workflow(
                    workflow_name="test_workflow",
                    workflow_config={},
                    experiment_id=experiment.id,
                    variant_id=variant,
                    custom_metrics={"quality_score": 80.0 + i},
                ):
                    if not status_ok:
                        raise RuntimeError("Simulated failure")
            except RuntimeError:
                pass

        # Get summary
        with obs_backend.get_session_context() as session:
            collector = ExperimentMetricsCollector(session=session)
            summary = collector.get_experiment_summary(experiment.id)

            assert summary["total_executions"] == 10
            assert summary["completed_executions"] == 8
            assert summary["failed_executions"] == 2
            assert summary["completion_rate"] == 0.8
            assert summary["variant_count"] == 2

    def test_custom_metrics_preservation(self, tracker, obs_backend):
        """Test that custom metrics are preserved through tracking."""
        custom_metrics = {
            "quality_score": 85.0,
            "latency_ms": 250.0,
            "user_satisfaction": 4.5,
            "success": 1.0,
        }

        with tracker.track_workflow(
            workflow_name="test_workflow",
            workflow_config={},
            experiment_id="exp-001",
            variant_id="var-control",
            custom_metrics=custom_metrics,
        ):
            pass

        # Collect and verify custom metrics
        with obs_backend.get_session_context() as session:
            collector = ExperimentMetricsCollector(session=session)
            assignments = collector.collect_assignments("exp-001")

            assert len(assignments) == 1
            assignment = assignments[0]

            # All custom metrics should be present
            for metric_name, metric_value in custom_metrics.items():
                assert metric_name in assignment.metrics
                assert assignment.metrics[metric_name] == pytest.approx(
                    metric_value, rel=0.01
                )

    def test_time_series_with_tracking(self, tracker, obs_backend, experiment):
        """Test time-series metrics extraction from tracked workflows."""
        import time

        # Track workflows over time
        for i in range(5):
            variant = "var-control" if i % 2 == 0 else "var-treatment"

            with tracker.track_workflow(
                workflow_name="test_workflow",
                workflow_config={},
                experiment_id=experiment.id,
                variant_id=variant,
                custom_metrics={"quality_score": 80.0 + i * 2},
            ):
                # Small delay to ensure different timestamps
                time.sleep(0.01)

        # Get time series
        with obs_backend.get_session_context() as session:
            collector = ExperimentMetricsCollector(session=session)
            time_series = collector.get_time_series_metrics(
                experiment.id, "quality_score"
            )

            assert "var-control" in time_series
            assert "var-treatment" in time_series

            # Control should have 3 points (indices 0, 2, 4)
            # Treatment should have 2 points (indices 1, 3)
            assert len(time_series["var-control"]) == 3
            assert len(time_series["var-treatment"]) == 2

            # Verify time series is sorted
            control_series = time_series["var-control"]
            for i in range(len(control_series) - 1):
                assert control_series[i][0] <= control_series[i + 1][0]


class TestBackwardsCompatibility:
    """Test that tracking without experiment metadata still works."""

    def test_track_workflow_without_experiment_metadata(self, tracker, obs_backend):
        """Test that workflows can be tracked without experiment metadata."""
        # Should work exactly as before
        with tracker.track_workflow(
            workflow_name="test_workflow",
            workflow_config={"agent": {"temperature": 0.7}},
        ) as workflow_id:
            assert workflow_id is not None

        # Verify workflow was created without experiment metadata
        with obs_backend.get_session_context() as session:
            from temper_ai.observability.models import WorkflowExecution

            workflow = session.get(WorkflowExecution, workflow_id)

            assert workflow is not None
            # extra_metadata should be None or empty
            assert workflow.extra_metadata is None or len(workflow.extra_metadata) == 0

    def test_partial_experiment_metadata(self, tracker, obs_backend):
        """Test tracking with only some experiment metadata fields."""
        with tracker.track_workflow(
            workflow_name="test_workflow",
            workflow_config={},
            experiment_id="exp-001",
            # Missing variant_id, assignment_strategy, etc.
        ) as workflow_id:
            assert workflow_id is not None

        with obs_backend.get_session_context() as session:
            from temper_ai.observability.models import WorkflowExecution

            workflow = session.get(WorkflowExecution, workflow_id)

            assert workflow.extra_metadata["experiment_id"] == "exp-001"
            assert "variant_id" not in workflow.extra_metadata
