"""
Tests for RollbackMonitor (automated regression detection and rollback).

Test coverage:
- No deployment history (skip monitoring)
- Already rolled back deployment (skip monitoring)
- Insufficient current data (skip monitoring)
- Not enough executions (skip monitoring)
- Quality regression detected (triggers rollback)
- Cost regression detected (triggers rollback)
- Speed regression detected (triggers rollback)
- No regression (no rollback)
- Multiple regressions (reports first)
- Monitor multiple agents
- Rollback failure handling
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch

from src.self_improvement.data_models import (
    AgentConfig,
    ConfigDeployment,
    AgentPerformanceProfile,
    utcnow,
)
from src.self_improvement.deployment.rollback_monitor import (
    RollbackMonitor,
    RegressionThresholds,
)


@pytest.fixture
def mock_performance_analyzer():
    """Create mock PerformanceAnalyzer."""
    return Mock()


@pytest.fixture
def mock_config_deployer():
    """Create mock ConfigDeployer."""
    deployer = Mock()
    deployer.get_last_deployment = Mock(return_value=None)
    deployer.rollback = Mock()
    return deployer


@pytest.fixture
def rollback_monitor(mock_performance_analyzer, mock_config_deployer):
    """Create RollbackMonitor instance."""
    return RollbackMonitor(
        performance_analyzer=mock_performance_analyzer,
        config_deployer=mock_config_deployer,
    )


@pytest.fixture
def custom_thresholds():
    """Create custom regression thresholds."""
    return RegressionThresholds(
        quality_drop_pct=5.0,
        cost_increase_pct=15.0,
        speed_increase_pct=25.0,
        min_executions=10,
    )


@pytest.fixture
def deployment():
    """Create test deployment."""
    return ConfigDeployment(
        id="deploy-001",
        agent_name="test_agent",
        previous_config=AgentConfig(agent_name="test_agent"),
        new_config=AgentConfig(agent_name="test_agent"),
        deployed_at=utcnow() - timedelta(hours=12),
    )


@pytest.fixture
def baseline_profile():
    """Create baseline performance profile."""
    return AgentPerformanceProfile(
        agent_name="test_agent",
        window_start=utcnow() - timedelta(hours=36),
        window_end=utcnow() - timedelta(hours=12),
        total_executions=100,
        metrics={
            "quality_score": {"mean": 0.90, "std": 0.05},
            "cost_usd": {"mean": 0.50, "std": 0.10},
            "duration_seconds": {"mean": 10.0, "std": 2.0},
        },
    )


@pytest.fixture
def current_profile_good():
    """Create current profile with good performance (no regression)."""
    return AgentPerformanceProfile(
        agent_name="test_agent",
        window_start=utcnow() - timedelta(hours=24),
        window_end=utcnow(),
        total_executions=50,
        metrics={
            "quality_score": {"mean": 0.92, "std": 0.04},  # Improved
            "cost_usd": {"mean": 0.48, "std": 0.08},  # Improved
            "duration_seconds": {"mean": 9.5, "std": 1.8},  # Improved
        },
    )


@pytest.fixture
def current_profile_quality_regression():
    """Create current profile with quality regression."""
    return AgentPerformanceProfile(
        agent_name="test_agent",
        window_start=utcnow() - timedelta(hours=24),
        window_end=utcnow(),
        total_executions=50,
        metrics={
            "quality_score": {"mean": 0.78, "std": 0.06},  # 13.3% drop
            "cost_usd": {"mean": 0.50, "std": 0.10},
            "duration_seconds": {"mean": 10.0, "std": 2.0},
        },
    )


@pytest.fixture
def current_profile_cost_regression():
    """Create current profile with cost regression."""
    return AgentPerformanceProfile(
        agent_name="test_agent",
        window_start=utcnow() - timedelta(hours=24),
        window_end=utcnow(),
        total_executions=50,
        metrics={
            "quality_score": {"mean": 0.90, "std": 0.05},
            "cost_usd": {"mean": 0.70, "std": 0.12},  # 40% increase
            "duration_seconds": {"mean": 10.0, "std": 2.0},
        },
    )


@pytest.fixture
def current_profile_speed_regression():
    """Create current profile with speed regression."""
    return AgentPerformanceProfile(
        agent_name="test_agent",
        window_start=utcnow() - timedelta(hours=24),
        window_end=utcnow(),
        total_executions=50,
        metrics={
            "quality_score": {"mean": 0.90, "std": 0.05},
            "cost_usd": {"mean": 0.50, "std": 0.10},
            "duration_seconds": {"mean": 14.0, "std": 2.5},  # 40% slower
        },
    )


class TestRegressionThresholds:
    """Test regression threshold configuration."""

    def test_default_thresholds(self):
        """Test default threshold values."""
        thresholds = RegressionThresholds()
        assert thresholds.quality_drop_pct == 10.0
        assert thresholds.cost_increase_pct == 20.0
        assert thresholds.speed_increase_pct == 30.0
        assert thresholds.min_executions == 20

    def test_custom_thresholds(self):
        """Test custom threshold values."""
        thresholds = RegressionThresholds(
            quality_drop_pct=5.0,
            cost_increase_pct=15.0,
            speed_increase_pct=25.0,
            min_executions=10,
        )
        assert thresholds.quality_drop_pct == 5.0
        assert thresholds.cost_increase_pct == 15.0
        assert thresholds.speed_increase_pct == 25.0
        assert thresholds.min_executions == 10


class TestCheckForRegression:
    """Test regression checking logic."""

    def test_no_deployment_history(
        self, rollback_monitor, mock_config_deployer
    ):
        """Test skips monitoring when no deployment history."""
        mock_config_deployer.get_last_deployment.return_value = None

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is False
        assert result["rolled_back"] is False
        assert result["reason"] is None

    def test_already_rolled_back(
        self, rollback_monitor, mock_config_deployer, deployment
    ):
        """Test skips monitoring when deployment already rolled back."""
        deployment.rollback_at = utcnow()
        mock_config_deployer.get_last_deployment.return_value = deployment

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is False
        assert result["rolled_back"] is False

    def test_no_baseline_data(
        self,
        rollback_monitor,
        mock_config_deployer,
        mock_performance_analyzer,
        deployment,
    ):
        """Test skips monitoring when no baseline data available."""
        mock_config_deployer.get_last_deployment.return_value = deployment
        mock_performance_analyzer.analyze_agent_performance.return_value = None

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is False
        assert result["rolled_back"] is False

    def test_insufficient_current_data(
        self,
        rollback_monitor,
        mock_config_deployer,
        mock_performance_analyzer,
        deployment,
        baseline_profile,
    ):
        """Test skips monitoring when insufficient current data."""
        mock_config_deployer.get_last_deployment.return_value = deployment

        # Return baseline, then None for current
        mock_performance_analyzer.analyze_agent_performance.side_effect = [
            baseline_profile,
            None,
        ]

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is False
        assert result["rolled_back"] is False

    def test_not_enough_executions(
        self,
        rollback_monitor,
        mock_config_deployer,
        mock_performance_analyzer,
        deployment,
        baseline_profile,
    ):
        """Test skips monitoring when not enough executions."""
        mock_config_deployer.get_last_deployment.return_value = deployment

        # Create current profile with insufficient executions
        current_profile = AgentPerformanceProfile(
            agent_name="test_agent",
            window_start=utcnow() - timedelta(hours=24),
            window_end=utcnow(),
            total_executions=10,  # Less than min_executions (20)
            metrics={
                "quality_score": {"mean": 0.75, "std": 0.05}
            },
        )

        mock_performance_analyzer.analyze_agent_performance.side_effect = [
            baseline_profile,
            current_profile,
        ]

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is False
        assert result["rolled_back"] is False

    def test_quality_regression_triggers_rollback(
        self,
        rollback_monitor,
        mock_config_deployer,
        mock_performance_analyzer,
        deployment,
        baseline_profile,
        current_profile_quality_regression,
    ):
        """Test quality regression triggers automatic rollback."""
        mock_config_deployer.get_last_deployment.return_value = deployment
        mock_performance_analyzer.analyze_agent_performance.side_effect = [
            baseline_profile,
            current_profile_quality_regression,
        ]

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is True
        assert result["rolled_back"] is True
        assert "Quality dropped" in result["reason"]

        # Verify rollback was called
        mock_config_deployer.rollback.assert_called_once()
        call_args = mock_config_deployer.rollback.call_args
        assert call_args[1]["agent_name"] == "test_agent"
        assert "Automatic rollback" in call_args[1]["rollback_reason"]

    def test_cost_regression_triggers_rollback(
        self,
        rollback_monitor,
        mock_config_deployer,
        mock_performance_analyzer,
        deployment,
        baseline_profile,
        current_profile_cost_regression,
    ):
        """Test cost regression triggers automatic rollback."""
        mock_config_deployer.get_last_deployment.return_value = deployment
        mock_performance_analyzer.analyze_agent_performance.side_effect = [
            baseline_profile,
            current_profile_cost_regression,
        ]

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is True
        assert result["rolled_back"] is True
        assert "Cost increased" in result["reason"]

    def test_speed_regression_triggers_rollback(
        self,
        rollback_monitor,
        mock_config_deployer,
        mock_performance_analyzer,
        deployment,
        baseline_profile,
        current_profile_speed_regression,
    ):
        """Test speed regression triggers automatic rollback."""
        mock_config_deployer.get_last_deployment.return_value = deployment
        mock_performance_analyzer.analyze_agent_performance.side_effect = [
            baseline_profile,
            current_profile_speed_regression,
        ]

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is True
        assert result["rolled_back"] is True
        assert "Speed degraded" in result["reason"]

    def test_no_regression_no_rollback(
        self,
        rollback_monitor,
        mock_config_deployer,
        mock_performance_analyzer,
        deployment,
        baseline_profile,
        current_profile_good,
    ):
        """Test no rollback when performance is good."""
        mock_config_deployer.get_last_deployment.return_value = deployment
        mock_performance_analyzer.analyze_agent_performance.side_effect = [
            baseline_profile,
            current_profile_good,
        ]

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is False
        assert result["rolled_back"] is False
        assert result["reason"] is None

        # Verify rollback was NOT called
        mock_config_deployer.rollback.assert_not_called()

    def test_rollback_failure_handled(
        self,
        rollback_monitor,
        mock_config_deployer,
        mock_performance_analyzer,
        deployment,
        baseline_profile,
        current_profile_quality_regression,
    ):
        """Test handles rollback failures gracefully."""
        mock_config_deployer.get_last_deployment.return_value = deployment
        mock_performance_analyzer.analyze_agent_performance.side_effect = [
            baseline_profile,
            current_profile_quality_regression,
        ]

        # Make rollback raise exception
        mock_config_deployer.rollback.side_effect = Exception("Rollback failed")

        result = rollback_monitor.check_for_regression("test_agent")

        assert result["regression_detected"] is True
        assert result["rolled_back"] is False
        assert "rollback_error" in result
        assert "Rollback failed" in result["rollback_error"]


class TestMonitorMultipleAgents:
    """Test monitoring multiple agents."""

    def test_monitor_all_agents_success(
        self,
        rollback_monitor,
        mock_config_deployer,
        mock_performance_analyzer,
        deployment,
        baseline_profile,
        current_profile_good,
    ):
        """Test successfully monitors multiple agents."""
        # Setup for both agents
        mock_config_deployer.get_last_deployment.return_value = deployment
        mock_performance_analyzer.analyze_agent_performance.side_effect = [
            baseline_profile,
            current_profile_good,
            baseline_profile,
            current_profile_good,
        ]

        results = rollback_monitor.monitor_all_agents(
            ["agent1", "agent2"]
        )

        assert len(results) == 2
        assert results["agent1"]["regression_detected"] is False
        assert results["agent2"]["regression_detected"] is False

    def test_monitor_all_agents_handles_errors(
        self,
        rollback_monitor,
        mock_config_deployer,
    ):
        """Test handles errors gracefully when monitoring multiple agents."""
        # Make get_last_deployment raise error
        mock_config_deployer.get_last_deployment.side_effect = Exception(
            "DB error"
        )

        results = rollback_monitor.monitor_all_agents(
            ["agent1", "agent2"]
        )

        assert len(results) == 2
        assert "error" in results["agent1"]
        assert "DB error" in results["agent1"]["error"]
        assert results["agent1"]["regression_detected"] is False


class TestCustomThresholds:
    """Test custom threshold configuration."""

    def test_custom_thresholds_applied(
        self,
        mock_performance_analyzer,
        mock_config_deployer,
        custom_thresholds,
        deployment,
        baseline_profile,
    ):
        """Test custom thresholds are applied correctly."""
        monitor = RollbackMonitor(
            performance_analyzer=mock_performance_analyzer,
            config_deployer=mock_config_deployer,
            thresholds=custom_thresholds,
        )

        # Create profile with 6% quality drop (triggers 5% threshold)
        current_profile = AgentPerformanceProfile(
            agent_name="test_agent",
            window_start=utcnow() - timedelta(hours=24),
            window_end=utcnow(),
            total_executions=50,
            metrics={
                "quality_score": {"mean": 0.846, "std": 0.05}  # 6% drop
            },
        )

        mock_config_deployer.get_last_deployment.return_value = deployment
        mock_performance_analyzer.analyze_agent_performance.side_effect = [
            baseline_profile,
            current_profile,
        ]

        result = monitor.check_for_regression("test_agent")

        # Should trigger with 5% threshold
        assert result["regression_detected"] is True
        assert result["rolled_back"] is True
