"""Tests for Error Recovery Strategy.

This test module verifies:
- Recovery action determination (retry, skip, fail)
- Transient vs permanent error classification
- Retry logic with exponential backoff
- Max retries enforcement
- Backoff delay calculation
- Rollback decision logic
"""

import pytest
import time
from unittest.mock import Mock, patch

from src.self_improvement.loop.error_recovery import ErrorRecoveryStrategy
from src.self_improvement.loop.config import LoopConfig
from src.self_improvement.loop.models import Phase, RecoveryAction


@pytest.fixture
def mock_config():
    """Create loop configuration for error recovery."""
    config = LoopConfig(
        max_retries_per_phase=3,
        initial_retry_delay_seconds=1.0,
        retry_backoff_multiplier=2.0,
        fail_on_permanent_error=False,
    )
    return config


@pytest.fixture
def mock_config_fail_on_error():
    """Create config that fails on permanent errors."""
    config = LoopConfig(
        max_retries_per_phase=3,
        fail_on_permanent_error=True,
    )
    return config


class PerformanceDataError(Exception):
    """Transient error for testing."""
    pass


class ValueError(Exception):
    """Permanent error for testing."""
    pass


class TestErrorRecoveryStrategy:
    """Test ErrorRecoveryStrategy class."""

    def test_strategy_initialization(self, mock_config):
        """Test strategy initialization."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        assert strategy.config == mock_config
        assert ErrorRecoveryStrategy.TRANSIENT_ERRORS
        assert ErrorRecoveryStrategy.PERMANENT_ERRORS

    def test_transient_errors_set(self):
        """Test TRANSIENT_ERRORS contains expected error types."""
        expected_transient = {
            "PerformanceDataError",
            "ProblemDetectionDataError",
            "ImprovementDataError",
            "DatabaseQueryError",
            "TimeoutError",
            "ConnectionError",
        }

        assert ErrorRecoveryStrategy.TRANSIENT_ERRORS == expected_transient

    def test_permanent_errors_set(self):
        """Test PERMANENT_ERRORS contains expected error types."""
        expected_permanent = {
            "ValueError",
            "ConfigurationError",
        }

        assert ErrorRecoveryStrategy.PERMANENT_ERRORS == expected_permanent

    def test_handle_phase_error_retry_transient(self, mock_config):
        """Test handling transient error triggers retry."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        # Create transient error
        error = PerformanceDataError("Not enough data")

        action = strategy.handle_phase_error(
            agent_name="test_agent",
            phase=Phase.ANALYZE,
            error=error,
            attempt=1
        )

        assert action == RecoveryAction.RETRY

    def test_handle_phase_error_skip_after_max_retries(self, mock_config):
        """Test skip after max retries exceeded."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        error = PerformanceDataError("Not enough data")

        # Attempt 4 (max_retries=3)
        action = strategy.handle_phase_error(
            agent_name="test_agent",
            phase=Phase.ANALYZE,
            error=error,
            attempt=4
        )

        assert action == RecoveryAction.SKIP

    def test_handle_phase_error_fail_after_max_retries(self, mock_config_fail_on_error):
        """Test fail after max retries when fail_on_permanent_error=True."""
        strategy = ErrorRecoveryStrategy(config=mock_config_fail_on_error)

        error = PerformanceDataError("Not enough data")

        # Attempt 4 (max_retries=3)
        action = strategy.handle_phase_error(
            agent_name="test_agent",
            phase=Phase.ANALYZE,
            error=error,
            attempt=4
        )

        assert action == RecoveryAction.FAIL

    def test_handle_phase_error_permanent_skip(self, mock_config):
        """Test permanent error triggers skip when fail_on_permanent_error=False."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        # Create permanent error
        error = ValueError("Invalid configuration")

        action = strategy.handle_phase_error(
            agent_name="test_agent",
            phase=Phase.DETECT,
            error=error,
            attempt=1
        )

        assert action == RecoveryAction.SKIP

    def test_handle_phase_error_permanent_fail(self, mock_config_fail_on_error):
        """Test permanent error triggers fail when fail_on_permanent_error=True."""
        strategy = ErrorRecoveryStrategy(config=mock_config_fail_on_error)

        error = ValueError("Invalid configuration")

        action = strategy.handle_phase_error(
            agent_name="test_agent",
            phase=Phase.DETECT,
            error=error,
            attempt=1
        )

        assert action == RecoveryAction.FAIL

    def test_should_retry_transient_within_limit(self, mock_config):
        """Test should_retry returns True for transient error within retry limit."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        error = PerformanceDataError("Not enough data")

        # With max_retries=3, can retry on attempts 1 and 2
        assert strategy.should_retry(error, attempt=1) is True
        assert strategy.should_retry(error, attempt=2) is True

    def test_should_retry_exceeds_max_retries(self, mock_config):
        """Test should_retry returns False when max retries exceeded."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        error = PerformanceDataError("Not enough data")

        # With max_retries=3, attempt 3 reaches the limit
        assert strategy.should_retry(error, attempt=3) is False
        # Attempt 4 also exceeds
        assert strategy.should_retry(error, attempt=4) is False

    def test_should_retry_permanent_error(self, mock_config):
        """Test should_retry returns False for permanent error."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        error = ValueError("Invalid input")

        assert strategy.should_retry(error, attempt=1) is False

    def test_should_retry_unknown_error_type(self, mock_config):
        """Test should_retry returns False for unknown error type."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        error = RuntimeError("Unknown error")

        # Unknown errors are not transient
        assert strategy.should_retry(error, attempt=1) is False

    def test_get_retry_delay_exponential_backoff(self, mock_config):
        """Test exponential backoff calculation."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        # initial_retry_delay_seconds=1.0, retry_backoff_multiplier=2.0
        assert strategy.get_retry_delay(attempt=1) == 1.0  # 1.0 * 2^0
        assert strategy.get_retry_delay(attempt=2) == 2.0  # 1.0 * 2^1
        assert strategy.get_retry_delay(attempt=3) == 4.0  # 1.0 * 2^2
        assert strategy.get_retry_delay(attempt=4) == 8.0  # 1.0 * 2^3

    def test_get_retry_delay_capped_at_5_minutes(self, mock_config):
        """Test retry delay is capped at 5 minutes (300 seconds)."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        # With backoff multiplier of 2.0, attempt 10 would be 1 * 2^9 = 512 seconds
        # But should be capped at 300 seconds
        delay = strategy.get_retry_delay(attempt=10)
        assert delay == 300.0

    @patch("time.sleep")
    def test_wait_for_retry(self, mock_sleep, mock_config):
        """Test wait_for_retry calls time.sleep with correct delay."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        strategy.wait_for_retry(attempt=1)
        mock_sleep.assert_called_once_with(1.0)

        mock_sleep.reset_mock()
        strategy.wait_for_retry(attempt=2)
        mock_sleep.assert_called_once_with(2.0)

    @patch("time.sleep")
    def test_wait_for_retry_with_large_attempt(self, mock_sleep, mock_config):
        """Test wait_for_retry with large attempt number."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        strategy.wait_for_retry(attempt=10)
        # Should be capped at 300 seconds
        mock_sleep.assert_called_once_with(300.0)

    def test_should_rollback_always_false(self, mock_config):
        """Test should_rollback always returns False (not supported)."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        error = ValueError("Test error")
        assert strategy.should_rollback(error) is False

        error = PerformanceDataError("Transient error")
        assert strategy.should_rollback(error) is False

    def test_is_permanent_error(self, mock_config):
        """Test _is_permanent_error classification."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        # Permanent errors
        assert strategy._is_permanent_error(ValueError("Invalid")) is True

        # Non-permanent errors
        assert strategy._is_permanent_error(PerformanceDataError("Data error")) is False
        assert strategy._is_permanent_error(RuntimeError("Unknown")) is False

    def test_is_transient_error(self, mock_config):
        """Test _is_transient_error classification."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        # Transient errors
        assert strategy._is_transient_error(PerformanceDataError("Data error")) is True

        # Non-transient errors
        assert strategy._is_transient_error(ValueError("Invalid")) is False
        assert strategy._is_transient_error(RuntimeError("Unknown")) is False

    def test_multiple_phases_same_error(self, mock_config):
        """Test handling same error across multiple phases."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        error = PerformanceDataError("Not enough data")

        # First phase
        action1 = strategy.handle_phase_error("agent1", Phase.DETECT, error, attempt=1)
        assert action1 == RecoveryAction.RETRY

        # Second phase (different phase, same error)
        action2 = strategy.handle_phase_error("agent1", Phase.ANALYZE, error, attempt=1)
        assert action2 == RecoveryAction.RETRY

    def test_different_agents_same_error(self, mock_config):
        """Test handling same error for different agents."""
        strategy = ErrorRecoveryStrategy(config=mock_config)

        error = PerformanceDataError("Not enough data")

        # Agent 1
        action1 = strategy.handle_phase_error("agent1", Phase.ANALYZE, error, attempt=1)
        assert action1 == RecoveryAction.RETRY

        # Agent 2 (different agent, same error)
        action2 = strategy.handle_phase_error("agent2", Phase.ANALYZE, error, attempt=1)
        assert action2 == RecoveryAction.RETRY

    def test_custom_retry_config(self):
        """Test with custom retry configuration."""
        config = LoopConfig(
            max_retries_per_phase=5,
            initial_retry_delay_seconds=2.0,
            retry_backoff_multiplier=3.0,
        )
        strategy = ErrorRecoveryStrategy(config=config)

        # With max_retries=5, can retry on attempts 1-4
        error = PerformanceDataError("Test")
        assert strategy.should_retry(error, attempt=4) is True
        assert strategy.should_retry(error, attempt=5) is False
        assert strategy.should_retry(error, attempt=6) is False

        # Backoff should use multiplier 3.0
        assert strategy.get_retry_delay(attempt=1) == 2.0  # 2.0 * 3^0
        assert strategy.get_retry_delay(attempt=2) == 6.0  # 2.0 * 3^1
        assert strategy.get_retry_delay(attempt=3) == 18.0  # 2.0 * 3^2

    def test_zero_retries_config(self):
        """Test with zero retries configured."""
        config = LoopConfig(max_retries_per_phase=0)
        strategy = ErrorRecoveryStrategy(config=config)

        error = PerformanceDataError("Test")

        # Should not retry with max_retries=0
        assert strategy.should_retry(error, attempt=1) is False

        # Should skip immediately
        action = strategy.handle_phase_error("agent1", Phase.DETECT, error, attempt=1)
        assert action == RecoveryAction.SKIP
