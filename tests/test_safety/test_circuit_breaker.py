"""Tests for circuit breaker system (shared.core.circuit_breaker)."""

from unittest.mock import patch

import pytest

from temper_ai.shared.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerMetrics,
)
from temper_ai.shared.core.circuit_breaker import (
    CircuitBreakerError as CircuitBreakerOpen,
)
from temper_ai.shared.core.circuit_breaker import (
    CircuitState as CircuitBreakerState,
)


class TestCircuitBreakerMetrics:
    """Test circuit breaker metrics."""

    def test_initialization(self):
        """Test metrics initialization."""
        metrics = CircuitBreakerMetrics()

        assert metrics.total_calls == 0
        assert metrics.successful_calls == 0
        assert metrics.failed_calls == 0
        assert metrics.rejected_calls == 0
        assert metrics.state_changes == 0

    def test_success_rate(self):
        """Test success rate calculation."""
        metrics = CircuitBreakerMetrics(
            total_calls=10, successful_calls=7, failed_calls=3
        )

        assert abs(metrics.success_rate() - 0.7) < 0.001
        assert abs(metrics.failure_rate() - 0.3) < 0.001

    def test_success_rate_no_calls(self):
        """Test success rate with no calls."""
        metrics = CircuitBreakerMetrics()

        assert metrics.success_rate() == 1.0
        assert metrics.failure_rate() == 0.0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        metrics = CircuitBreakerMetrics(
            total_calls=10, successful_calls=7, failed_calls=3, state_changes=2
        )

        data = metrics.to_dict()

        assert data["total_calls"] == 10
        assert data["successful_calls"] == 7
        assert data["failed_calls"] == 3
        assert data["success_rate"] == 0.7


class TestCircuitBreaker:
    """Test circuit breaker."""

    def test_initialization(self):
        """Test circuit breaker initialization."""
        breaker = CircuitBreaker(
            name="test_breaker", failure_threshold=5, timeout_seconds=60
        )

        assert breaker.name == "test_breaker"
        assert breaker.failure_threshold == 5
        assert breaker.timeout_seconds == 60
        assert breaker.state == CircuitBreakerState.CLOSED

    def test_initial_state_closed(self):
        """Test initial state is CLOSED."""
        breaker = CircuitBreaker("test")

        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.can_execute() is True

    def test_record_success(self):
        """Test recording successful execution."""
        breaker = CircuitBreaker("test")

        breaker.record_success()

        assert breaker.metrics.successful_calls == 1
        assert breaker.metrics.total_calls == 1

    def test_record_failure(self):
        """Test recording failed execution."""
        breaker = CircuitBreaker("test")

        breaker.record_failure()

        assert breaker.metrics.failed_calls == 1
        assert breaker.metrics.total_calls == 1

    def test_open_after_threshold_failures(self):
        """Test circuit opens after threshold failures."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        # Record failures up to threshold
        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN

    def test_cannot_execute_when_open(self):
        """Test execution blocked when circuit is open."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.can_execute() is False

    def test_transition_to_half_open_after_timeout(self):
        """Test transition from OPEN to HALF_OPEN after timeout."""
        breaker = CircuitBreaker(
            name="test", failure_threshold=1, timeout_seconds=1  # 1 second timeout
        )

        # Open circuit
        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN

        # Mock time.time to advance past timeout (no flaky sleep)
        original_time = breaker._last_failure_time
        with patch("temper_ai.shared.core.circuit_breaker.time") as mock_time:
            mock_time.time.return_value = original_time + 1.1
            # Check state (should transition to HALF_OPEN)
            assert breaker.state == CircuitBreakerState.HALF_OPEN
            assert breaker.can_execute() is True

    def test_half_open_to_closed_on_success(self):
        """Test transition from HALF_OPEN to CLOSED on success."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            timeout_seconds=1,
            success_threshold=2,  # Need 2 successes
        )

        # Open circuit
        breaker.record_failure()

        # Mock time.time to advance past timeout (no flaky sleep)
        original_time = breaker._last_failure_time
        with patch("temper_ai.shared.core.circuit_breaker.time") as mock_time:
            mock_time.time.return_value = original_time + 1.1
            # Now in HALF_OPEN
            assert breaker.state == CircuitBreakerState.HALF_OPEN

        # First success
        breaker.record_success()
        assert breaker.state == CircuitBreakerState.HALF_OPEN

        # Second success - should close
        breaker.record_success()
        assert breaker.state == CircuitBreakerState.CLOSED

    def test_half_open_to_open_on_failure(self):
        """Test transition from HALF_OPEN back to OPEN on failure."""
        breaker = CircuitBreaker(name="test", failure_threshold=1, timeout_seconds=1)

        # Open circuit
        breaker.record_failure()

        # Mock time.time to advance past timeout (no flaky sleep)
        original_time = breaker._last_failure_time
        with patch("temper_ai.shared.core.circuit_breaker.time") as mock_time:
            mock_time.time.return_value = original_time + 1.1
            # Now in HALF_OPEN
            assert breaker.state == CircuitBreakerState.HALF_OPEN

        # Any failure in HALF_OPEN reopens circuit
        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN

    def test_reset(self):
        """Test manual reset to CLOSED."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        # Open circuit
        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN

        # Reset
        breaker.reset()
        assert breaker.state == CircuitBreakerState.CLOSED

    def test_force_open(self):
        """Test forcing circuit to OPEN."""
        breaker = CircuitBreaker("test")

        assert breaker.state == CircuitBreakerState.CLOSED

        breaker.force_open()
        assert breaker.state == CircuitBreakerState.OPEN

    def test_context_manager_success(self):
        """Test circuit breaker as context manager with success."""
        breaker = CircuitBreaker("test")

        with breaker():
            # Simulated successful operation
            pass

        assert breaker.metrics.successful_calls == 1

    def test_context_manager_failure(self):
        """Test circuit breaker as context manager with failure."""
        breaker = CircuitBreaker("test")

        with pytest.raises(ValueError):
            with breaker():
                raise ValueError("Simulated failure")

        assert breaker.metrics.failed_calls == 1

    def test_context_manager_raises_when_open(self):
        """Test context manager raises exception when open."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        # Open circuit
        breaker.record_failure()

        # Should raise CircuitBreakerOpen
        with pytest.raises(CircuitBreakerOpen, match="Circuit breaker 'test' is open"):
            with breaker():
                pass

        assert breaker.metrics.rejected_calls == 1

    def test_state_change_callback(self):
        """Test state change callback."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        callback_called = []

        def on_state_change(old_state, new_state):
            callback_called.append((old_state, new_state))

        breaker.on_state_change(on_state_change)

        # Open circuit
        breaker.record_failure()

        assert len(callback_called) == 1
        assert callback_called[0] == (
            CircuitBreakerState.CLOSED,
            CircuitBreakerState.OPEN,
        )

    def test_callback_exception_doesnt_break_breaker(self):
        """Test that callback exceptions don't break circuit breaker."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        def failing_callback(old_state, new_state):
            raise RuntimeError("Callback failed")

        breaker.on_state_change(failing_callback)

        # Should not raise exception
        breaker.record_failure()

        assert breaker.state == CircuitBreakerState.OPEN

    def test_get_metrics(self):
        """Test getting metrics."""
        breaker = CircuitBreaker("test")

        breaker.record_success()
        breaker.record_success()
        breaker.record_failure()

        metrics = breaker.get_metrics()

        assert metrics.total_calls == 3
        assert metrics.successful_calls == 2
        assert metrics.failed_calls == 1

    def test_repr(self):
        """Test string representation."""
        breaker = CircuitBreaker(name="test_breaker", failure_threshold=5)

        repr_str = repr(breaker)

        assert "CircuitBreaker" in repr_str
        assert "test_breaker" in repr_str
        assert "closed" in repr_str


class TestIntegration:
    """Integration tests for circuit breaker system."""

    def test_circuit_breaker_prevents_cascading_failures(self):
        """Test circuit breaker stops cascading failures."""
        breaker = CircuitBreaker(
            name="external_api", failure_threshold=3, timeout_seconds=2
        )

        failed_count = 0
        success_count = 0

        # Simulate 10 calls to failing service
        for i in range(10):
            try:
                with breaker():
                    # Simulated failing API call
                    if i < 5:  # First 5 fail
                        raise Exception("API error")
                    success_count += 1
            except CircuitBreakerOpen:
                # Circuit opened - prevented call
                pass
            except Exception:
                failed_count += 1

        # Circuit should have opened after 3 failures
        assert breaker.state == CircuitBreakerState.OPEN
        assert failed_count == 3  # Only 3 failures recorded
        assert breaker.metrics.rejected_calls > 0  # Some calls rejected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
