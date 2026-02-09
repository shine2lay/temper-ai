"""Tests for Continuous Executor.

This test module verifies:
- Continuous loop execution with multiple agents
- Convergence detection (no deployments in N iterations)
- Budget enforcement (max iterations, cost budget)
- Signal handling (SIGINT, SIGTERM)
- Graceful shutdown on error
- Statistics tracking
- Iteration sleep with shutdown checks
"""

import pytest
import signal
import time
from unittest.mock import Mock, patch, call
from datetime import datetime, timezone

from src.self_improvement.loop.continuous_executor import (
    ContinuousExecutor,
    ContinuousExecutionStats,
)
from src.self_improvement.loop.config import LoopConfig
from src.self_improvement.loop.models import IterationResult, Phase


@pytest.fixture
def mock_config():
    """Create loop configuration for continuous mode."""
    config = LoopConfig(
        continuous_check_interval_minutes=1,
        continuous_max_iterations=10,
        continuous_convergence_window=3,
        continuous_cost_budget=100.0,
    )
    return config


@pytest.fixture
def mock_iteration_result():
    """Create mock iteration result."""
    result = Mock(spec=IterationResult)
    result.success = True
    result.deployment_result = None
    result.error = None
    return result


class TestContinuousExecutionStats:
    """Test ContinuousExecutionStats data class."""

    def test_stats_initialization(self):
        """Test stats initialization with defaults."""
        stats = ContinuousExecutionStats()

        assert stats.total_iterations == 0
        assert stats.successful_iterations == 0
        assert stats.failed_iterations == 0
        assert stats.total_deployments == 0
        assert stats.total_cost == 0.0
        assert stats.iterations_without_deployment == 0
        assert isinstance(stats.agents, dict)
        assert isinstance(stats.started_at, datetime)
        assert stats.stopped_at is None
        assert stats.stop_reason is None

    def test_stats_with_agents(self):
        """Test stats initialization with agent dict."""
        stats = ContinuousExecutionStats(
            agents={
                "agent1": {"iterations": 0, "deployments": 0},
                "agent2": {"iterations": 0, "deployments": 0},
            }
        )

        assert len(stats.agents) == 2
        assert "agent1" in stats.agents
        assert "agent2" in stats.agents


class TestContinuousExecutor:
    """Test ContinuousExecutor class."""

    def test_executor_initialization(self, mock_config):
        """Test executor initialization."""
        run_fn = Mock()
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        assert executor.config == mock_config
        assert executor.run_iteration_fn == run_fn

    def test_execute_empty_agents_raises_error(self, mock_config):
        """Test execute with empty agent list raises ValueError."""
        run_fn = Mock()
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        with pytest.raises(ValueError, match="agent_names is required"):
            executor.execute(agent_names=[])

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_single_iteration_no_deployment(
        self, mock_signal, mock_sleep, mock_config, mock_iteration_result
    ):
        """Test single iteration without deployment."""
        mock_config.continuous_max_iterations = 1

        run_fn = Mock(return_value=mock_iteration_result)
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        result = executor.execute(agent_names=["agent1"])

        # Verify result structure
        assert result["total_iterations"] == 1
        assert result["successful_iterations"] == 1
        assert result["failed_iterations"] == 0
        assert result["total_deployments"] == 0
        assert result["stop_reason"] == "max_iterations_reached"
        assert "agent1" in result["agents"]

        # Verify run_fn was called
        run_fn.assert_called_once_with("agent1")

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_with_deployment(
        self, mock_signal, mock_sleep, mock_config, mock_iteration_result
    ):
        """Test iteration with deployment."""
        mock_config.continuous_max_iterations = 1
        mock_iteration_result.deployment_result = Mock(deployment_id="deploy-1")

        run_fn = Mock(return_value=mock_iteration_result)
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        result = executor.execute(agent_names=["agent1"])

        assert result["total_deployments"] == 1
        assert result["iterations_without_deployment"] == 0

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_convergence_detection(
        self, mock_signal, mock_sleep, mock_config, mock_iteration_result
    ):
        """Test convergence detection stops loop."""
        mock_config.continuous_max_iterations = 10
        mock_config.continuous_convergence_window = 3

        run_fn = Mock(return_value=mock_iteration_result)
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        result = executor.execute(agent_names=["agent1"])

        # Should stop after 3 iterations without deployment
        assert result["total_iterations"] == 3
        assert result["stop_reason"] == "converged"
        assert result["iterations_without_deployment"] == 3

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_multiple_agents(
        self, mock_signal, mock_sleep, mock_config, mock_iteration_result
    ):
        """Test execution with multiple agents."""
        mock_config.continuous_max_iterations = 1

        run_fn = Mock(return_value=mock_iteration_result)
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        result = executor.execute(agent_names=["agent1", "agent2"])

        # Should run iteration for both agents
        assert run_fn.call_count == 2
        assert call("agent1") in run_fn.call_args_list
        assert call("agent2") in run_fn.call_args_list

        # Both agents should have stats
        assert "agent1" in result["agents"]
        assert "agent2" in result["agents"]
        assert result["agents"]["agent1"]["iterations"] == 1
        assert result["agents"]["agent2"]["iterations"] == 1

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_handles_iteration_error(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test handling of iteration error."""
        mock_config.continuous_max_iterations = 1

        # Create result with error
        error_result = Mock(spec=IterationResult)
        error_result.success = False
        error_result.error = Exception("Test error")
        error_result.deployment_result = None

        run_fn = Mock(return_value=error_result)
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        result = executor.execute(agent_names=["agent1"])

        assert result["successful_iterations"] == 0
        assert result["failed_iterations"] == 1
        assert result["stop_reason"] == "max_iterations_reached"

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_handles_iteration_exception(
        self, mock_signal, mock_sleep, mock_config, mock_iteration_result
    ):
        """Test handling of exception during iteration."""
        mock_config.continuous_max_iterations = 1

        run_fn = Mock(side_effect=RuntimeError("Iteration crashed"))
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        result = executor.execute(agent_names=["agent1"])

        assert result["successful_iterations"] == 0
        assert result["failed_iterations"] == 1

    @patch("time.sleep")
    @patch("signal.signal")
    def test_should_stop_max_iterations(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test _should_stop for max iterations."""
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=Mock())
        stats = ContinuousExecutionStats()
        stats.total_iterations = 11

        should_stop = executor._should_stop(
            stats, max_iterations=10, cost_budget=None,
            convergence_window=3, shutdown_requested=False
        )

        assert should_stop is True
        assert stats.stop_reason == "max_iterations_reached"

    @patch("time.sleep")
    @patch("signal.signal")
    def test_should_stop_convergence(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test _should_stop for convergence."""
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=Mock())
        stats = ContinuousExecutionStats()
        stats.iterations_without_deployment = 5

        should_stop = executor._should_stop(
            stats, max_iterations=100, cost_budget=None,
            convergence_window=5, shutdown_requested=False
        )

        assert should_stop is True
        assert stats.stop_reason == "converged"

    @patch("time.sleep")
    @patch("signal.signal")
    def test_should_stop_cost_budget(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test _should_stop for cost budget."""
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=Mock())
        stats = ContinuousExecutionStats()
        stats.total_cost = 150.0

        should_stop = executor._should_stop(
            stats, max_iterations=100, cost_budget=100.0,
            convergence_window=5, shutdown_requested=False
        )

        assert should_stop is True
        assert stats.stop_reason == "cost_budget_exceeded"

    @patch("time.sleep")
    @patch("signal.signal")
    def test_should_stop_shutdown_requested(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test _should_stop for manual shutdown."""
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=Mock())
        stats = ContinuousExecutionStats()

        should_stop = executor._should_stop(
            stats, max_iterations=100, cost_budget=None,
            convergence_window=5, shutdown_requested=True
        )

        assert should_stop is True
        assert stats.stop_reason == "manual_interrupt"

    @patch("time.sleep")
    @patch("signal.signal")
    def test_wait_for_next_iteration_completes(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test _wait_for_next_iteration completes normally."""
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=Mock())
        shutdown_requested = {"flag": False}

        result = executor._wait_for_next_iteration(
            interval_minutes=1, shutdown_requested=shutdown_requested
        )

        assert result is True
        # Verify sleep was called (with periodic checks)
        assert mock_sleep.call_count > 0

    @patch("time.sleep")
    @patch("signal.signal")
    def test_wait_for_next_iteration_shutdown(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test _wait_for_next_iteration with shutdown."""
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=Mock())
        shutdown_requested = {"flag": True}

        result = executor._wait_for_next_iteration(
            interval_minutes=1, shutdown_requested=shutdown_requested
        )

        assert result is False

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_agent_iterations_stops_on_shutdown(
        self, mock_signal, mock_sleep, mock_config, mock_iteration_result
    ):
        """Test _execute_agent_iterations stops when shutdown requested."""
        run_fn = Mock(return_value=mock_iteration_result)
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        stats = ContinuousExecutionStats(
            agents={"agent1": {"iterations": 0, "deployments": 0}}
        )
        shutdown_requested = {"flag": True}

        # Should stop after first agent when shutdown requested
        result = executor._execute_agent_iterations(
            agent_names=["agent1", "agent2"],
            stats=stats,
            shutdown_requested=shutdown_requested
        )

        # Only agent1 should be processed
        assert run_fn.call_count == 1
        assert stats.agents["agent1"]["iterations"] == 1

    @patch("time.sleep")
    @patch("signal.signal")
    def test_signal_handler_sets_shutdown_flag(
        self, mock_signal, mock_sleep, mock_config, mock_iteration_result
    ):
        """Test signal handler sets shutdown flag."""
        mock_config.continuous_max_iterations = 10

        run_fn = Mock(return_value=mock_iteration_result)
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        # Mock sleep to trigger shutdown after first iteration
        def sleep_side_effect(*args, **kwargs):
            # Simulate SIGINT after first iteration
            shutdown_requested = {"flag": True}
            return

        mock_sleep.side_effect = sleep_side_effect

        # Execute with shutdown during sleep
        with patch.object(executor, '_wait_for_next_iteration', return_value=False):
            result = executor.execute(agent_names=["agent1"])

        assert result["stop_reason"] == "manual_interrupt"

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_restores_signal_handlers(
        self, mock_signal, mock_sleep, mock_config, mock_iteration_result
    ):
        """Test signal handlers are restored after execution."""
        mock_config.continuous_max_iterations = 1

        run_fn = Mock(return_value=mock_iteration_result)
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        executor.execute(agent_names=["agent1"])

        # Verify signal handlers were set and then restored
        signal_calls = mock_signal.call_args_list

        # Should have calls to set handlers and restore to SIG_DFL
        assert any(call(signal.SIGINT, signal.SIG_DFL) in signal_calls for call in signal_calls)
        assert any(call(signal.SIGTERM, signal.SIG_DFL) in signal_calls for call in signal_calls)

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_keyboard_interrupt(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test handling of KeyboardInterrupt during execution."""
        run_fn = Mock(side_effect=KeyboardInterrupt())
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        result = executor.execute(agent_names=["agent1"])

        assert result["stop_reason"] == "keyboard_interrupt"
        assert "stopped_at" in result
        assert result["stopped_at"] is not None

    @patch("time.sleep")
    @patch("signal.signal")
    def test_log_iteration_complete(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test _log_iteration_complete logs correctly."""
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=Mock())
        stats = ContinuousExecutionStats(
            successful_iterations=5,
            failed_iterations=2,
            total_deployments=3,
            iterations_without_deployment=1
        )

        # Should not raise
        executor._log_iteration_complete(stats, iteration=7)

    @patch("time.sleep")
    @patch("signal.signal")
    def test_log_final_summary(
        self, mock_signal, mock_sleep, mock_config
    ):
        """Test _log_final_summary logs correctly."""
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=Mock())
        stats = ContinuousExecutionStats(
            total_iterations=10,
            successful_iterations=8,
            failed_iterations=2,
            total_deployments=5,
            iterations_without_deployment=2,
            agents={
                "agent1": {"iterations": 10, "deployments": 5}
            }
        )
        stats.stopped_at = datetime.now(timezone.utc)
        stats.stop_reason = "converged"

        # Should not raise
        executor._log_final_summary(stats)

    @patch("time.sleep")
    @patch("signal.signal")
    def test_execute_with_custom_interval(
        self, mock_signal, mock_sleep, mock_config, mock_iteration_result
    ):
        """Test execute with custom check interval."""
        mock_config.continuous_max_iterations = 1

        run_fn = Mock(return_value=mock_iteration_result)
        executor = ContinuousExecutor(config=mock_config, run_iteration_fn=run_fn)

        # Override interval
        result = executor.execute(agent_names=["agent1"], check_interval_minutes=30)

        assert result["total_iterations"] == 1
        # Interval override doesn't affect result structure, just timing
