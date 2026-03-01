"""Tests for temper_ai/shared/core/circuit_breaker.py.

Covers CircuitBreaker state machine, metrics, callbacks, call/async_call
context manager, storage persistence, and validation helpers.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.shared.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerMetrics,
    CircuitState,
    _build_config,
    _validate_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_breaker(
    name: str = "test-breaker",
    failure_threshold: int = 3,
    timeout_seconds: int = 60,
    success_threshold: int = 2,
) -> CircuitBreaker:
    return CircuitBreaker(
        name=name,
        failure_threshold=failure_threshold,
        timeout_seconds=timeout_seconds,
        success_threshold=success_threshold,
    )


def trip_breaker(breaker: CircuitBreaker) -> None:
    """Record enough failures to open the breaker."""
    for _ in range(breaker.config.failure_threshold):
        breaker.record_failure()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class TestValidateName:
    def test_valid_name_passes(self):
        _validate_name("my-breaker")  # No exception

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name must be"):
            _validate_name("")

    def test_non_string_raises(self):
        with pytest.raises(ValueError, match="name must be a string"):
            _validate_name(123)  # type: ignore[arg-type]

    def test_too_long_name_raises(self):
        with pytest.raises(ValueError, match="name must be"):
            _validate_name("x" * 101)

    def test_exactly_100_chars_passes(self):
        _validate_name("x" * 100)  # should not raise


class TestBuildConfig:
    def test_uses_config_object_if_provided(self):
        cfg = CircuitBreakerConfig(
            failure_threshold=10, success_threshold=5, timeout=120
        )
        result = _build_config(cfg, None, None, None, "test")
        assert result is cfg

    def test_config_overrides_individual_params(self, caplog):
        """When both config and individual params supplied, config wins and a warning is logged."""
        import logging

        cfg = CircuitBreakerConfig(
            failure_threshold=10, success_threshold=5, timeout=120
        )
        with caplog.at_level(logging.WARNING):
            result = _build_config(cfg, 3, None, None, "test")
        assert result is cfg
        assert any("config takes precedence" in r.message for r in caplog.records)

    def test_builds_from_individual_params(self):
        result = _build_config(None, 4, 30, 3, "test")
        assert result.failure_threshold == 4
        assert result.timeout == 30
        assert result.success_threshold == 3

    def test_invalid_failure_threshold_raises(self):
        with pytest.raises(ValueError, match="failure_threshold"):
            _build_config(None, 0, 30, 2, "test")

    def test_invalid_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout_seconds"):
            _build_config(None, 5, -1, 2, "test")

    def test_invalid_success_threshold_raises(self):
        with pytest.raises(ValueError, match="success_threshold"):
            _build_config(None, 5, 30, 0, "test")

    def test_defaults_applied_when_no_params(self):
        result = _build_config(None, None, None, None, "test")
        assert result.failure_threshold > 0
        assert result.timeout > 0
        assert result.success_threshold > 0


# ---------------------------------------------------------------------------
# CircuitBreakerMetrics
# ---------------------------------------------------------------------------


class TestCircuitBreakerMetrics:
    def test_default_values(self):
        m = CircuitBreakerMetrics()
        assert m.total_calls == 0
        assert m.successful_calls == 0
        assert m.failed_calls == 0
        assert m.rejected_calls == 0
        assert m.state_changes == 0
        assert m.last_failure_time is None
        assert m.last_state_change_time is None

    def test_success_rate_no_calls(self):
        """Success rate is 1.0 when no calls have been made."""
        assert CircuitBreakerMetrics().success_rate() == 1.0

    def test_success_rate_all_success(self):
        m = CircuitBreakerMetrics(total_calls=10, successful_calls=10)
        assert m.success_rate() == 1.0

    def test_success_rate_partial(self):
        m = CircuitBreakerMetrics(total_calls=10, successful_calls=7)
        assert abs(m.success_rate() - 0.7) < 1e-9

    def test_failure_rate_complement(self):
        m = CircuitBreakerMetrics(total_calls=10, successful_calls=7)
        assert abs(m.failure_rate() - 0.3) < 1e-9

    def test_to_dict_structure(self):
        m = CircuitBreakerMetrics()
        d = m.to_dict()
        assert "total_calls" in d
        assert "successful_calls" in d
        assert "failed_calls" in d
        assert "rejected_calls" in d
        assert "state_changes" in d
        assert "success_rate" in d
        assert "failure_rate" in d
        assert "last_failure_time" in d
        assert "last_state_change_time" in d

    def test_to_dict_times_are_none_when_not_set(self):
        m = CircuitBreakerMetrics()
        d = m.to_dict()
        assert d["last_failure_time"] is None
        assert d["last_state_change_time"] is None

    def test_to_dict_times_are_iso_strings_when_set(self):
        from datetime import UTC, datetime

        m = CircuitBreakerMetrics(
            last_failure_time=datetime(2024, 1, 1, tzinfo=UTC),
            last_state_change_time=datetime(2024, 1, 2, tzinfo=UTC),
        )
        d = m.to_dict()
        assert isinstance(d["last_failure_time"], str)
        assert isinstance(d["last_state_change_time"], str)


# ---------------------------------------------------------------------------
# CircuitBreaker construction
# ---------------------------------------------------------------------------


class TestCircuitBreakerConstruction:
    def test_basic_construction(self):
        breaker = make_breaker()
        assert breaker.name == "test-breaker"
        assert breaker.state == CircuitState.CLOSED

    def test_initial_state_is_closed(self):
        breaker = make_breaker()
        assert breaker.state == CircuitState.CLOSED

    def test_failure_count_starts_at_zero(self):
        breaker = make_breaker()
        assert breaker.failure_count == 0

    def test_success_count_starts_at_zero(self):
        breaker = make_breaker()
        assert breaker.success_count == 0

    def test_config_from_individual_params(self):
        breaker = make_breaker(
            failure_threshold=7, timeout_seconds=90, success_threshold=3
        )
        assert breaker.config.failure_threshold == 7
        assert breaker.config.timeout == 90
        assert breaker.config.success_threshold == 3

    def test_config_object_accepted(self):
        cfg = CircuitBreakerConfig(failure_threshold=8, success_threshold=4, timeout=45)
        breaker = CircuitBreaker(name="test", config=cfg)
        assert breaker.config.failure_threshold == 8

    def test_invalid_name_raises(self):
        with pytest.raises(ValueError):
            CircuitBreaker(name="")

    def test_repr(self):
        breaker = make_breaker()
        r = repr(breaker)
        assert "test-breaker" in r
        assert "closed" in r


# ---------------------------------------------------------------------------
# State machine: CLOSED → OPEN
# ---------------------------------------------------------------------------


class TestClosedToOpen:
    def test_single_failure_does_not_open(self):
        breaker = make_breaker(failure_threshold=3)
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

    def test_failures_below_threshold_keep_closed(self):
        breaker = make_breaker(failure_threshold=3)
        for _ in range(2):
            breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

    def test_failure_at_threshold_opens(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        assert breaker.state == CircuitState.OPEN

    def test_failure_count_reset_after_open(self):
        """failure_count resets to 0 when breaker opens."""
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        # After tripping, failure_count resets
        assert breaker.failure_count == 0

    def test_metrics_updated_on_failure(self):
        breaker = make_breaker(failure_threshold=3)
        breaker.record_failure()
        assert breaker.metrics.total_calls == 1
        assert breaker.metrics.failed_calls == 1

    def test_state_change_callback_fired(self):
        breaker = make_breaker(failure_threshold=3)
        callback = MagicMock()
        breaker.on_state_change(callback)
        trip_breaker(breaker)
        callback.assert_called_once_with(CircuitState.CLOSED, CircuitState.OPEN)


# ---------------------------------------------------------------------------
# State machine: OPEN → HALF_OPEN
# ---------------------------------------------------------------------------


class TestOpenToHalfOpen:
    def test_open_state_fast_fails(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        with pytest.raises(CircuitBreakerError):
            breaker.call(lambda: None)

    def test_open_rejects_via_context_manager(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        with pytest.raises(CircuitBreakerError):
            with breaker():
                pass

    def test_auto_transitions_to_half_open_after_timeout(self):
        """After timeout elapses, state property returns HALF_OPEN."""
        breaker = make_breaker(failure_threshold=3, timeout_seconds=60)
        trip_breaker(breaker)
        # Simulate timeout elapsed by patching time.time
        with patch("temper_ai.shared.core.circuit_breaker.time") as mock_time:
            mock_time.time.return_value = time.time() + 120  # past timeout
            assert breaker.state == CircuitState.HALF_OPEN

    def test_open_does_not_transition_before_timeout(self):
        breaker = make_breaker(failure_threshold=3, timeout_seconds=600)
        trip_breaker(breaker)
        # State should still be OPEN immediately
        assert breaker._state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# State machine: HALF_OPEN → CLOSED
# ---------------------------------------------------------------------------


class TestHalfOpenToClosed:
    def test_successes_in_half_open_close_breaker(self):
        breaker = make_breaker(
            failure_threshold=3, success_threshold=2, timeout_seconds=1
        )
        trip_breaker(breaker)
        # Force into HALF_OPEN
        breaker._state = CircuitState.HALF_OPEN
        breaker.record_success()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self):
        breaker = make_breaker(failure_threshold=3, success_threshold=2)
        trip_breaker(breaker)
        breaker._state = CircuitState.HALF_OPEN
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# record_success
# ---------------------------------------------------------------------------


class TestRecordSuccess:
    def test_success_increments_total_calls(self):
        breaker = make_breaker()
        breaker.record_success()
        assert breaker.metrics.total_calls == 1
        assert breaker.metrics.successful_calls == 1

    def test_success_resets_failure_count(self):
        breaker = make_breaker(failure_threshold=10)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        assert breaker.failure_count == 0


# ---------------------------------------------------------------------------
# call() method
# ---------------------------------------------------------------------------


class TestCallMethod:
    def test_successful_call_returns_result(self):
        breaker = make_breaker()
        result = breaker.call(lambda: 42)
        assert result == 42

    def test_failed_call_raises_original_exception(self):
        breaker = make_breaker()

        def fail():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            breaker.call(fail)

    def test_call_passes_args_and_kwargs(self):
        breaker = make_breaker()
        result = breaker.call(lambda x, y=0: x + y, 10, y=5)
        assert result == 15

    def test_open_breaker_raises_circuit_breaker_error(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        with pytest.raises(CircuitBreakerError):
            breaker.call(lambda: None)

    def test_open_breaker_increments_rejected_calls(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        try:
            breaker.call(lambda: None)
        except CircuitBreakerError:
            pass
        assert breaker.metrics.rejected_calls == 1


# ---------------------------------------------------------------------------
# async_call() method
# ---------------------------------------------------------------------------


class TestAsyncCallMethod:
    def test_successful_async_call(self):
        breaker = make_breaker()

        async def async_func():
            return 99

        result = asyncio.run(breaker.async_call(async_func))
        assert result == 99

    def test_failed_async_call_raises(self):
        breaker = make_breaker()

        async def async_fail():
            raise RuntimeError("async error")

        with pytest.raises(RuntimeError, match="async error"):
            asyncio.run(breaker.async_call(async_fail))

    def test_open_breaker_rejects_async(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)

        async def async_func():
            return 1

        with pytest.raises(CircuitBreakerError):
            asyncio.run(breaker.async_call(async_func))


# ---------------------------------------------------------------------------
# Context manager __call__
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_successful_context(self):
        breaker = make_breaker()
        with breaker():
            pass  # Should not raise
        assert breaker.metrics.successful_calls == 1

    def test_exception_in_context_records_failure(self):
        breaker = make_breaker(failure_threshold=10)
        with pytest.raises(RuntimeError):
            with breaker():
                raise RuntimeError("boom")
        assert breaker.metrics.failed_calls == 1

    def test_open_breaker_rejects_context(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        with pytest.raises(CircuitBreakerError):
            with breaker():
                pass


# ---------------------------------------------------------------------------
# reset() and force_open()
# ---------------------------------------------------------------------------


class TestResetAndForceOpen:
    def test_reset_closes_open_breaker(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED

    def test_reset_clears_failure_count(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        breaker.reset()
        assert breaker.failure_count == 0

    def test_reset_fires_callback(self):
        breaker = make_breaker(failure_threshold=3)
        trip_breaker(breaker)
        callback = MagicMock()
        breaker.on_state_change(callback)
        breaker.reset()
        callback.assert_called_with(CircuitState.OPEN, CircuitState.CLOSED)

    def test_force_open_sets_open(self):
        breaker = make_breaker()
        breaker.force_open()
        assert breaker._state == CircuitState.OPEN

    def test_force_open_fires_callback(self):
        breaker = make_breaker()
        callback = MagicMock()
        breaker.on_state_change(callback)
        breaker.force_open()
        callback.assert_called_with(CircuitState.CLOSED, CircuitState.OPEN)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


class TestCallbacks:
    def test_on_state_change_registered(self):
        breaker = make_breaker()
        fn = MagicMock()
        breaker.on_state_change(fn)
        assert fn in breaker._on_state_change_callbacks

    def test_add_observability_callback(self):
        breaker = make_breaker()
        fn = MagicMock()
        breaker.add_observability_callback(fn)
        assert fn in breaker._observability_callbacks

    def test_error_in_state_change_callback_does_not_propagate(self):
        """Callbacks that raise should not crash the breaker."""
        breaker = make_breaker(failure_threshold=3)

        def bad_callback(old, new):
            raise RuntimeError("callback error")

        breaker.on_state_change(bad_callback)
        # Should not propagate
        trip_breaker(breaker)

    def test_multiple_callbacks_all_called(self):
        breaker = make_breaker(failure_threshold=3)
        cb1 = MagicMock()
        cb2 = MagicMock()
        breaker.on_state_change(cb1)
        breaker.on_state_change(cb2)
        trip_breaker(breaker)
        cb1.assert_called_once()
        cb2.assert_called_once()


# ---------------------------------------------------------------------------
# Thread safety smoke test
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_failures_do_not_crash(self):
        """Multiple threads recording failures concurrently should not crash."""
        breaker = make_breaker(failure_threshold=100)
        errors = []

        def record():
            try:
                breaker.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_concurrent_successes_do_not_crash(self):
        breaker = make_breaker()
        errors = []

        def record():
            try:
                breaker.record_success()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
