"""Tests for circuit breaker and safety gate system."""

from unittest.mock import Mock, patch

import pytest

from temper_ai.safety.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerManager,
    CircuitBreakerMetrics,
    CircuitBreakerOpen,
    CircuitBreakerState,
    SafetyGate,
    SafetyGateBlocked,
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


class TestSafetyGate:
    """Test safety gate."""

    def test_initialization(self):
        """Test safety gate initialization."""
        gate = SafetyGate(name="test_gate")

        assert gate.name == "test_gate"
        assert gate.circuit_breaker is None
        assert gate.policy_composer is None

    def test_can_pass_no_restrictions(self):
        """Test can_pass with no restrictions."""
        gate = SafetyGate(name="test")

        result = gate.can_pass(action={"tool": "test"}, context={})

        assert result is True

    def test_can_pass_with_circuit_breaker(self):
        """Test can_pass with circuit breaker."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)
        gate = SafetyGate(name="test_gate", circuit_breaker=breaker)

        # Initially can pass
        assert gate.can_pass(action={}, context={}) is True

        # Open circuit
        breaker.record_failure()

        # Now blocked
        assert gate.can_pass(action={}, context={}) is False

    def test_can_pass_with_policy_composer(self):
        """Test can_pass with policy composer."""
        from temper_ai.safety.interfaces import ValidationResult

        # Mock policy composer
        mock_composer = Mock()

        # Mock validation result with blocking violation
        mock_result = Mock(spec=ValidationResult)
        mock_result.valid = False
        mock_result.has_blocking_violations.return_value = True
        mock_composer.validate.return_value = mock_result

        gate = SafetyGate(name="test_gate", policy_composer=mock_composer)

        result = gate.can_pass(action={"tool": "test"}, context={})

        assert result is False
        mock_composer.validate.assert_called_once()

    def test_manual_block(self):
        """Test manually blocking gate."""
        gate = SafetyGate(name="test")

        assert gate.can_pass(action={}, context={}) is True

        gate.block("Manual block for testing")

        assert gate.can_pass(action={}, context={}) is False
        assert gate.is_blocked() is True

    def test_manual_unblock(self):
        """Test manually unblocking gate."""
        gate = SafetyGate(name="test")

        gate.block("Test")
        assert gate.is_blocked() is True

        gate.unblock()
        assert gate.is_blocked() is False
        assert gate.can_pass(action={}, context={}) is True

    def test_validate_returns_reasons(self):
        """Test validate returns detailed reasons."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)
        gate = SafetyGate(name="test_gate", circuit_breaker=breaker)

        # Open circuit
        breaker.record_failure()

        can_pass, reasons = gate.validate(action={}, context={})

        assert can_pass is False
        assert len(reasons) > 0
        assert "Circuit breaker" in reasons[0]

    def test_context_manager_success(self):
        """Test safety gate as context manager with success."""
        gate = SafetyGate(name="test")

        with gate(action={"tool": "test"}, context={}):
            # Simulated operation
            pass

        # Verify gate allowed operation to proceed
        assert not gate.is_blocked()

    def test_context_manager_raises_when_blocked(self):
        """Test context manager raises exception when blocked."""
        gate = SafetyGate(name="test")
        gate.block("Testing")

        with pytest.raises(SafetyGateBlocked, match="Safety gate 'test' blocked"):
            with gate(action={}, context={}):
                pass

    def test_context_manager_with_circuit_breaker(self):
        """Test context manager integrates with circuit breaker."""
        breaker = CircuitBreaker("test")
        gate = SafetyGate(name="test_gate", circuit_breaker=breaker)

        # Success
        with gate(action={}, context={}):
            pass

        assert breaker.metrics.successful_calls == 1

    def test_repr(self):
        """Test string representation."""
        gate = SafetyGate(name="test_gate")

        repr_str = repr(gate)

        assert "SafetyGate" in repr_str
        assert "test_gate" in repr_str


class TestCircuitBreakerManager:
    """Test circuit breaker manager."""

    def test_initialization(self):
        """Test manager initialization."""
        manager = CircuitBreakerManager()

        assert manager.breaker_count() == 0
        assert manager.gate_count() == 0

    def test_create_breaker(self):
        """Test creating circuit breaker."""
        manager = CircuitBreakerManager()

        breaker = manager.create_breaker(name="test", failure_threshold=5)

        assert breaker is not None
        assert breaker.name == "test"
        assert manager.breaker_count() == 1

    def test_create_duplicate_breaker_raises_error(self):
        """Test creating duplicate breaker raises error."""
        manager = CircuitBreakerManager()

        manager.create_breaker("test")

        with pytest.raises(ValueError, match="already exists"):
            manager.create_breaker("test")

    def test_get_breaker(self):
        """Test getting breaker by name."""
        manager = CircuitBreakerManager()
        created = manager.create_breaker("test")

        retrieved = manager.get_breaker("test")

        assert retrieved is created

    def test_get_nonexistent_breaker(self):
        """Test getting nonexistent breaker."""
        manager = CircuitBreakerManager()

        breaker = manager.get_breaker("nonexistent")

        assert breaker is None

    def test_remove_breaker(self):
        """Test removing breaker."""
        manager = CircuitBreakerManager()
        manager.create_breaker("test")

        removed = manager.remove_breaker("test")

        assert removed is True
        assert manager.breaker_count() == 0

    def test_remove_nonexistent_breaker(self):
        """Test removing nonexistent breaker."""
        manager = CircuitBreakerManager()

        removed = manager.remove_breaker("nonexistent")

        assert removed is False

    def test_list_breakers(self):
        """Test listing all breakers."""
        manager = CircuitBreakerManager()

        manager.create_breaker("breaker1")
        manager.create_breaker("breaker2")
        manager.create_breaker("breaker3")

        breakers = manager.list_breakers()

        assert len(breakers) == 3
        assert "breaker1" in breakers
        assert "breaker2" in breakers
        assert "breaker3" in breakers

    def test_create_gate(self):
        """Test creating safety gate."""
        manager = CircuitBreakerManager()

        gate = manager.create_gate(name="test_gate")

        assert gate is not None
        assert gate.name == "test_gate"
        assert manager.gate_count() == 1

    def test_create_gate_with_breaker(self):
        """Test creating gate with circuit breaker."""
        manager = CircuitBreakerManager()

        manager.create_breaker("test_breaker")
        gate = manager.create_gate(name="test_gate", breaker_name="test_breaker")

        assert gate.circuit_breaker is not None
        assert gate.circuit_breaker.name == "test_breaker"

    def test_create_duplicate_gate_raises_error(self):
        """Test creating duplicate gate raises error."""
        manager = CircuitBreakerManager()

        manager.create_gate("test")

        with pytest.raises(ValueError, match="already exists"):
            manager.create_gate("test")

    def test_get_gate(self):
        """Test getting gate by name."""
        manager = CircuitBreakerManager()
        created = manager.create_gate("test")

        retrieved = manager.get_gate("test")

        assert retrieved is created

    def test_get_nonexistent_gate(self):
        """Test getting nonexistent gate."""
        manager = CircuitBreakerManager()

        gate = manager.get_gate("nonexistent")

        assert gate is None

    def test_remove_gate(self):
        """Test removing gate."""
        manager = CircuitBreakerManager()
        manager.create_gate("test")

        removed = manager.remove_gate("test")

        assert removed is True
        assert manager.gate_count() == 0

    def test_list_gates(self):
        """Test listing all gates."""
        manager = CircuitBreakerManager()

        manager.create_gate("gate1")
        manager.create_gate("gate2")

        gates = manager.list_gates()

        assert len(gates) == 2
        assert "gate1" in gates
        assert "gate2" in gates

    def test_get_all_metrics(self):
        """Test getting metrics for all breakers."""
        manager = CircuitBreakerManager()

        breaker1 = manager.create_breaker("breaker1")
        breaker2 = manager.create_breaker("breaker2")

        breaker1.record_success()
        breaker2.record_failure()

        metrics = manager.get_all_metrics()

        assert "breaker1" in metrics
        assert "breaker2" in metrics
        assert metrics["breaker1"]["successful_calls"] == 1
        assert metrics["breaker2"]["failed_calls"] == 1

    def test_reset_all(self):
        """Test resetting all breakers."""
        manager = CircuitBreakerManager()

        breaker1 = manager.create_breaker("breaker1", failure_threshold=1)
        breaker2 = manager.create_breaker("breaker2", failure_threshold=1)

        # Open both circuits
        breaker1.record_failure()
        breaker2.record_failure()

        assert breaker1.state == CircuitBreakerState.OPEN
        assert breaker2.state == CircuitBreakerState.OPEN

        # Reset all
        manager.reset_all()

        assert breaker1.state == CircuitBreakerState.CLOSED
        assert breaker2.state == CircuitBreakerState.CLOSED

    def test_repr(self):
        """Test string representation."""
        manager = CircuitBreakerManager()
        manager.create_breaker("test1")
        manager.create_gate("gate1")

        repr_str = repr(manager)

        assert "CircuitBreakerManager" in repr_str
        assert "breakers=1" in repr_str
        assert "gates=1" in repr_str


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

    def test_safety_gate_with_multiple_checks(self):
        """Test safety gate coordinates multiple safety checks."""
        from temper_ai.safety.interfaces import ValidationResult

        # Create circuit breaker
        breaker = CircuitBreaker("test", failure_threshold=2)

        # Mock policy composer
        mock_composer = Mock()
        mock_result = Mock(spec=ValidationResult)
        mock_result.valid = True
        mock_result.has_blocking_violations.return_value = False
        mock_composer.validate.return_value = mock_result

        # Create gate
        gate = SafetyGate(
            name="multi_check_gate",
            circuit_breaker=breaker,
            policy_composer=mock_composer,
        )

        # Should pass - both checks OK
        assert gate.can_pass(action={}, context={}) is True

        # Open circuit
        breaker.record_failure()
        breaker.record_failure()

        # Should fail - circuit open
        assert gate.can_pass(action={}, context={}) is False

    def test_manager_coordinates_multiple_breakers(self):
        """Test manager coordinates multiple circuit breakers."""
        manager = CircuitBreakerManager()

        # Create breakers for different services
        db_breaker = manager.create_breaker("database", failure_threshold=3)
        api_breaker = manager.create_breaker("api", failure_threshold=5)
        cache_breaker = manager.create_breaker("cache", failure_threshold=2)

        # Simulate failures on different services
        db_breaker.record_failure()
        db_breaker.record_failure()
        db_breaker.record_failure()

        api_breaker.record_success()

        cache_breaker.record_failure()
        cache_breaker.record_failure()

        # Check states
        assert db_breaker.state == CircuitBreakerState.OPEN
        assert api_breaker.state == CircuitBreakerState.CLOSED
        assert cache_breaker.state == CircuitBreakerState.OPEN

        # Get aggregated metrics
        metrics = manager.get_all_metrics()
        assert metrics["database"]["failed_calls"] == 3
        assert metrics["api"]["successful_calls"] == 1
        assert metrics["cache"]["failed_calls"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
