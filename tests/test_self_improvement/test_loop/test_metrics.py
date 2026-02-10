"""Tests for loop metrics collection."""
import pytest
from datetime import datetime, timezone, timedelta
from src.self_improvement.loop.metrics import LoopMetrics, MetricsCollector
from src.self_improvement.loop.models import Phase, IterationResult, ExperimentPhaseResult, DeploymentResult


class TestLoopMetrics:
    """Test LoopMetrics data class."""

    def test_initialization(self):
        """Test metrics initialization with defaults."""
        metrics = LoopMetrics(agent_name="test_agent")

        assert metrics.agent_name == "test_agent"
        assert metrics.total_iterations == 0
        assert metrics.successful_iterations == 0
        assert metrics.failed_iterations == 0
        assert metrics.total_experiments == 0
        assert metrics.successful_deployments == 0
        assert metrics.rollbacks == 0
        assert metrics.avg_iteration_duration == 0.0
        assert metrics.last_iteration_at is None
        assert isinstance(metrics.phase_executions, dict)
        assert isinstance(metrics.phase_successes, dict)
        assert isinstance(metrics.phase_failures, dict)
        assert isinstance(metrics.phase_durations, dict)

    def test_to_dict_empty(self):
        """Test dictionary conversion with no data."""
        metrics = LoopMetrics(agent_name="test_agent")
        result = metrics.to_dict()

        assert result["agent_name"] == "test_agent"
        assert result["total_iterations"] == 0
        assert result["successful_iterations"] == 0
        assert result["failed_iterations"] == 0
        assert result["success_rate"] == 0.0
        assert result["total_experiments"] == 0
        assert result["successful_deployments"] == 0
        assert result["rollbacks"] == 0
        assert result["avg_iteration_duration"] == 0.0
        assert result["last_iteration_at"] is None
        assert isinstance(result["phase_executions"], dict)
        assert isinstance(result["phase_successes"], dict)
        assert isinstance(result["phase_failures"], dict)
        assert isinstance(result["phase_success_rates"], dict)
        assert isinstance(result["phase_avg_durations"], dict)

    def test_to_dict_with_data(self):
        """Test dictionary conversion with actual data."""
        now = datetime.now(timezone.utc)
        metrics = LoopMetrics(
            agent_name="test_agent",
            total_iterations=10,
            successful_iterations=7,
            failed_iterations=3,
            total_experiments=5,
            successful_deployments=4,
            rollbacks=1,
            avg_iteration_duration=120.5,
            last_iteration_at=now
        )

        # Add phase data
        metrics.phase_executions[Phase.DETECT] = 10
        metrics.phase_successes[Phase.DETECT] = 9
        metrics.phase_failures[Phase.DETECT] = 1
        metrics.phase_durations[Phase.DETECT] = [10.0, 12.0, 11.0]

        result = metrics.to_dict()

        assert result["total_iterations"] == 10
        assert result["successful_iterations"] == 7
        assert result["failed_iterations"] == 3
        assert result["success_rate"] == 0.7
        assert result["total_experiments"] == 5
        assert result["successful_deployments"] == 4
        assert result["rollbacks"] == 1
        assert result["avg_iteration_duration"] == 120.5
        assert result["last_iteration_at"] == now.isoformat()
        assert result["phase_executions"]["detect"] == 10
        assert result["phase_successes"]["detect"] == 9
        assert result["phase_failures"]["detect"] == 1
        assert result["phase_success_rates"]["detect"] == 0.9
        assert result["phase_avg_durations"]["detect"] == 11.0

    def test_calculate_phase_success_rates(self):
        """Test phase success rate calculation."""
        metrics = LoopMetrics(agent_name="test_agent")

        # Phase with successes
        metrics.phase_executions[Phase.DETECT] = 10
        metrics.phase_successes[Phase.DETECT] = 8

        # Phase with no successes
        metrics.phase_executions[Phase.ANALYZE] = 5
        metrics.phase_successes[Phase.ANALYZE] = 0

        # Phase with no executions
        # Don't set Phase.STRATEGY

        rates = metrics._calculate_phase_success_rates()

        assert rates["detect"] == 0.8
        assert rates["analyze"] == 0.0
        assert rates["strategy"] == 0.0  # No executions defaults to 0/1 = 0

    def test_calculate_avg_durations(self):
        """Test phase average duration calculation."""
        metrics = LoopMetrics(agent_name="test_agent")

        # Phase with durations
        metrics.phase_durations[Phase.DETECT] = [10.0, 15.0, 20.0]

        # Phase with single duration
        metrics.phase_durations[Phase.ANALYZE] = [30.0]

        # Phase with no durations
        metrics.phase_durations[Phase.STRATEGY] = []

        avgs = metrics._calculate_avg_durations()

        assert avgs["detect"] == 15.0
        assert avgs["analyze"] == 30.0
        assert avgs["strategy"] == 0.0


class TestMetricsCollector:
    """Test MetricsCollector functionality."""

    def test_initialization(self):
        """Test collector initialization."""
        collector = MetricsCollector()

        assert isinstance(collector._metrics, dict)
        assert isinstance(collector._phase_starts, dict)
        assert len(collector._metrics) == 0
        assert len(collector._phase_starts) == 0

    def test_record_phase_start(self):
        """Test recording phase start."""
        collector = MetricsCollector()

        collector.record_phase_start("test_agent", Phase.DETECT)

        # Check phase start tracked
        assert "test_agent" in collector._phase_starts
        assert Phase.DETECT in collector._phase_starts["test_agent"]
        assert isinstance(collector._phase_starts["test_agent"][Phase.DETECT], datetime)

        # Check metrics initialized
        assert "test_agent" in collector._metrics
        metrics = collector._metrics["test_agent"]
        assert metrics.agent_name == "test_agent"
        assert metrics.phase_executions[Phase.DETECT] == 1

    def test_record_phase_start_multiple_times(self):
        """Test recording phase start increments count."""
        collector = MetricsCollector()

        collector.record_phase_start("test_agent", Phase.DETECT)
        collector.record_phase_start("test_agent", Phase.DETECT)

        metrics = collector._metrics["test_agent"]
        assert metrics.phase_executions[Phase.DETECT] == 2

    def test_record_phase_complete_with_calculated_duration(self):
        """Test recording phase completion calculates duration."""
        collector = MetricsCollector()

        # Start phase
        collector.record_phase_start("test_agent", Phase.DETECT)

        # Complete phase (duration calculated)
        collector.record_phase_complete("test_agent", Phase.DETECT)

        metrics = collector._metrics["test_agent"]
        assert metrics.phase_successes[Phase.DETECT] == 1
        assert Phase.DETECT in metrics.phase_durations
        assert len(metrics.phase_durations[Phase.DETECT]) == 1
        assert metrics.phase_durations[Phase.DETECT][0] >= 0.0

    def test_record_phase_complete_with_explicit_duration(self):
        """Test recording phase completion with explicit duration."""
        collector = MetricsCollector()

        # Initialize metrics
        collector.record_phase_start("test_agent", Phase.DETECT)

        # Complete with explicit duration
        collector.record_phase_complete("test_agent", Phase.DETECT, duration=45.5)

        metrics = collector._metrics["test_agent"]
        assert metrics.phase_successes[Phase.DETECT] == 1
        assert metrics.phase_durations[Phase.DETECT] == [45.5]

    def test_record_phase_complete_no_metrics(self):
        """Test completing phase without prior start logs warning."""
        collector = MetricsCollector()

        # Should not raise, but log warning
        collector.record_phase_complete("test_agent", Phase.DETECT)

        # Metrics should not be created
        assert "test_agent" not in collector._metrics

    def test_record_phase_error(self):
        """Test recording phase error."""
        collector = MetricsCollector()

        # Initialize
        collector.record_phase_start("test_agent", Phase.DETECT)

        # Record error
        error = ValueError("Test error")
        collector.record_phase_error("test_agent", Phase.DETECT, error)

        metrics = collector._metrics["test_agent"]
        assert metrics.phase_failures[Phase.DETECT] == 1

    def test_record_phase_error_no_metrics(self):
        """Test recording error without prior start logs warning."""
        collector = MetricsCollector()

        error = ValueError("Test error")
        collector.record_phase_error("test_agent", Phase.DETECT, error)

        # Should not crash
        assert "test_agent" not in collector._metrics

    def test_record_iteration_complete_success(self):
        """Test recording successful iteration."""
        collector = MetricsCollector()
        now = datetime.now(timezone.utc)

        result = IterationResult(
            agent_name="test_agent",
            iteration_number=1,
            phases_completed=[Phase.DETECT, Phase.ANALYZE],
            success=True,
            duration_seconds=120.0,
            timestamp=now,
            detection_result=None,
            analysis_result=None,
            strategy_result=None,
            experiment_result=ExperimentPhaseResult(experiment_id="exp1", winner_variant_id="var1"),
            deployment_result=DeploymentResult(
                deployment_id="dep-123",
                deployed_config=None,
                previous_config=None,
                deployment_timestamp=now,
                rollback_monitoring_enabled=True
            )
        )

        collector.record_iteration_complete("test_agent", result)

        metrics = collector._metrics["test_agent"]
        assert metrics.total_iterations == 1
        assert metrics.successful_iterations == 1
        assert metrics.failed_iterations == 0
        assert metrics.avg_iteration_duration == 120.0
        assert metrics.last_iteration_at == now
        assert metrics.total_experiments == 1
        assert metrics.successful_deployments == 1

    def test_record_iteration_complete_failure(self):
        """Test recording failed iteration."""
        collector = MetricsCollector()
        now = datetime.now(timezone.utc)

        result = IterationResult(
            agent_name="test_agent",
            iteration_number=1,
            phases_completed=[Phase.DETECT],
            success=False,
            duration_seconds=30.0,
            timestamp=now,
            detection_result=None,
            analysis_result=None,
            strategy_result=None,
            experiment_result=None,
            deployment_result=None
        )

        collector.record_iteration_complete("test_agent", result)

        metrics = collector._metrics["test_agent"]
        assert metrics.total_iterations == 1
        assert metrics.successful_iterations == 0
        assert metrics.failed_iterations == 1

    def test_record_iteration_complete_average_duration(self):
        """Test average duration calculation over multiple iterations."""
        collector = MetricsCollector()
        now = datetime.now(timezone.utc)

        # First iteration: 100s
        result1 = IterationResult(
            agent_name="test_agent",
            iteration_number=1,
            phases_completed=[],
            success=True,
            duration_seconds=100.0,
            timestamp=now
        )
        collector.record_iteration_complete("test_agent", result1)

        # Second iteration: 200s
        result2 = IterationResult(
            agent_name="test_agent",
            iteration_number=2,
            phases_completed=[],
            success=True,
            duration_seconds=200.0,
            timestamp=now
        )
        collector.record_iteration_complete("test_agent", result2)

        metrics = collector._metrics["test_agent"]
        assert metrics.total_iterations == 2
        assert metrics.avg_iteration_duration == 150.0  # (100 + 200) / 2

    def test_record_rollback(self):
        """Test recording rollback."""
        collector = MetricsCollector()

        # Initialize metrics
        collector.record_phase_start("test_agent", Phase.DETECT)

        collector.record_rollback("test_agent")

        metrics = collector._metrics["test_agent"]
        assert metrics.rollbacks == 1

    def test_record_rollback_no_metrics(self):
        """Test recording rollback without metrics logs warning."""
        collector = MetricsCollector()

        collector.record_rollback("test_agent")

        # Should not crash
        assert "test_agent" not in collector._metrics

    def test_get_metrics(self):
        """Test retrieving metrics for agent."""
        collector = MetricsCollector()

        # No metrics yet
        assert collector.get_metrics("test_agent") is None

        # Create metrics
        collector.record_phase_start("test_agent", Phase.DETECT)

        metrics = collector.get_metrics("test_agent")
        assert metrics is not None
        assert metrics.agent_name == "test_agent"

    def test_get_all_metrics(self):
        """Test retrieving all metrics."""
        collector = MetricsCollector()

        # Create metrics for multiple agents
        collector.record_phase_start("agent1", Phase.DETECT)
        collector.record_phase_start("agent2", Phase.ANALYZE)

        all_metrics = collector.get_all_metrics()

        assert len(all_metrics) == 2
        assert "agent1" in all_metrics
        assert "agent2" in all_metrics
        assert all_metrics["agent1"].agent_name == "agent1"
        assert all_metrics["agent2"].agent_name == "agent2"

    def test_get_all_metrics_returns_copy(self):
        """Test get_all_metrics returns a copy."""
        collector = MetricsCollector()
        collector.record_phase_start("agent1", Phase.DETECT)

        all_metrics = collector.get_all_metrics()
        all_metrics["agent2"] = LoopMetrics(agent_name="agent2")

        # Original should not be modified
        assert "agent2" not in collector._metrics

    def test_reset_metrics(self):
        """Test resetting metrics for agent."""
        collector = MetricsCollector()

        # Create metrics
        collector.record_phase_start("test_agent", Phase.DETECT)
        assert "test_agent" in collector._metrics
        assert "test_agent" in collector._phase_starts

        # Reset
        collector.reset_metrics("test_agent")

        assert "test_agent" not in collector._metrics
        assert "test_agent" not in collector._phase_starts

    def test_reset_metrics_nonexistent(self):
        """Test resetting metrics for nonexistent agent."""
        collector = MetricsCollector()

        # Should not crash
        result = collector.reset_metrics("nonexistent")
        # reset_metrics returns None for both existent and non-existent agents
        assert result is None

    def test_export_metrics(self):
        """Test exporting metrics as dictionary."""
        collector = MetricsCollector()

        # Create and populate metrics
        collector.record_phase_start("test_agent", Phase.DETECT)
        now = datetime.now(timezone.utc)
        result = IterationResult(
            agent_name="test_agent",
            iteration_number=1,
            phases_completed=[],
            success=True,
            duration_seconds=100.0,
            timestamp=now
        )
        collector.record_iteration_complete("test_agent", result)

        exported = collector.export_metrics("test_agent")

        assert exported["agent_name"] == "test_agent"
        assert exported["total_iterations"] == 1
        assert "no_data" not in exported

    def test_export_metrics_no_data(self):
        """Test exporting metrics when agent has no data."""
        collector = MetricsCollector()

        exported = collector.export_metrics("nonexistent")

        assert exported["agent_name"] == "nonexistent"
        assert exported["no_data"] is True

    def test_multiple_agents_independent(self):
        """Test that metrics for different agents are independent."""
        collector = MetricsCollector()

        # Agent 1
        collector.record_phase_start("agent1", Phase.DETECT)
        collector.record_phase_complete("agent1", Phase.DETECT)

        # Agent 2
        collector.record_phase_start("agent2", Phase.ANALYZE)
        collector.record_phase_error("agent2", Phase.ANALYZE, ValueError("error"))

        metrics1 = collector.get_metrics("agent1")
        metrics2 = collector.get_metrics("agent2")

        assert metrics1.phase_successes[Phase.DETECT] == 1
        assert Phase.DETECT not in metrics1.phase_failures

        assert metrics2.phase_failures[Phase.ANALYZE] == 1
        assert Phase.ANALYZE not in metrics2.phase_successes
