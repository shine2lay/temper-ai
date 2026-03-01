"""Extended tests for _circuit_breaker_helpers.py covering uncovered lines.

Targets:
- Lines 22-23: _httpx is None branch in _should_count_failure
- Lines 38-42: ImportError branch for LLM exception imports
- Line 58: _httpx is None returns True
- Line 71: _LLMError isinstance check
- Line 243: _log_state_transition
- Lines 277-291: _fire_observability_callbacks with obs_callbacks
- Lines 312-317: on_call_success HALF_OPEN -> CLOSED transition
- Line 320: on_call_success with storage
- Line 331: semaphore release in finally (HALF_OPEN reserved)
- Lines 334-335: _log_state_transition + _fire_observability_callbacks after success
- Lines 348-359: _should_open_on_failure all branches
- Lines 376: on_call_failure HALF_OPEN semaphore release when not counting
- Lines 379-415: on_call_failure full flow
- Lines 434-437: reserve_execution with storage save
- Lines 452-455: reserve_execution HALF_OPEN semaphore blocked
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.shared.core._circuit_breaker_helpers import (
    _fire_observability_callbacks,
    _log_state_transition,
    _should_count_failure,
    _should_open_on_failure,
    fire_callbacks,
    on_call_failure,
    on_call_success,
    reserve_execution,
)
from temper_ai.shared.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
)

# ---------------------------------------------------------------------------
# Helpers to build a minimal breaker mock
# ---------------------------------------------------------------------------


def _make_breaker(state=CircuitState.CLOSED, failures=0, successes=0):
    """Build a real CircuitBreaker so we can test helpers against it."""
    config = CircuitBreakerConfig(failure_threshold=3, success_threshold=2, timeout=60)
    breaker = CircuitBreaker(name="test", config=config)
    breaker._state = state
    breaker._failure_count = failures
    breaker._success_count = successes
    return breaker


# ---------------------------------------------------------------------------
# _should_count_failure with _httpx patched to None
# ---------------------------------------------------------------------------


class TestShouldCountFailureWithoutHttpx:
    """Tests when httpx is unavailable (lines 22-23, 58)."""

    def test_returns_true_when_httpx_is_none(self):
        """When _httpx is None, any error returns True (line 58)."""
        with patch("temper_ai.shared.core._circuit_breaker_helpers._httpx", None):
            assert _should_count_failure(ValueError("any error")) is True

    def test_generic_error_returns_true_when_httpx_none(self):
        with patch("temper_ai.shared.core._circuit_breaker_helpers._httpx", None):
            assert _should_count_failure(RuntimeError("runtime")) is True


class TestShouldCountFailureLLMErrors:
    """Tests with LLM error types (lines 38-42, 71)."""

    def test_llm_error_counts_when_not_auth(self):
        """Generic LLMError (not auth) should count (line 71)."""
        try:
            from temper_ai.shared.utils.exceptions import LLMError
        except ImportError:
            pytest.skip("LLMError not available")
        exc = LLMError("provider error")
        assert _should_count_failure(exc) is True

    def test_llm_error_subclass_does_not_count_for_auth(self):
        """LLMAuthenticationError should NOT count (existing coverage, verify)."""
        try:
            from temper_ai.shared.utils.exceptions import LLMAuthenticationError
        except ImportError:
            pytest.skip("LLMAuthenticationError not available")
        exc = LLMAuthenticationError("unauthorized")
        assert _should_count_failure(exc) is False

    def test_should_count_when_llm_error_is_none(self):
        """When _LLMError is patched to None, generic error falls through to False."""
        with (
            patch("temper_ai.shared.core._circuit_breaker_helpers._LLMError", None),
            patch(
                "temper_ai.shared.core._circuit_breaker_helpers._LLMTimeoutError", None
            ),
            patch(
                "temper_ai.shared.core._circuit_breaker_helpers._LLMRateLimitError",
                None,
            ),
            patch(
                "temper_ai.shared.core._circuit_breaker_helpers._LLMAuthenticationError",
                None,
            ),
        ):
            # Generic exception with no httpx match falls through to False
            assert _should_count_failure(ValueError("nope")) is False


# ---------------------------------------------------------------------------
# _log_state_transition (line 243)
# ---------------------------------------------------------------------------


class TestLogStateTransition:
    """Tests for _log_state_transition."""

    def test_logs_transition(self, caplog):
        """_log_state_transition emits an info log."""
        import logging

        breaker = _make_breaker()
        breaker.name = "test-breaker"
        breaker.failure_count = 3
        breaker.success_count = 0

        with caplog.at_level(logging.INFO):
            _log_state_transition(breaker, CircuitState.CLOSED, CircuitState.OPEN)

        assert any("test-breaker" in r.message for r in caplog.records)

    def test_logs_both_states(self, caplog):
        """Both old and new states appear in the log."""
        import logging

        breaker = _make_breaker()
        breaker.name = "cb"
        breaker.failure_count = 1
        breaker.success_count = 0

        with caplog.at_level(logging.INFO):
            _log_state_transition(breaker, CircuitState.OPEN, CircuitState.HALF_OPEN)

        full_log = " ".join(r.message for r in caplog.records)
        assert "open" in full_log
        assert "half_open" in full_log


# ---------------------------------------------------------------------------
# _fire_observability_callbacks (lines 277-291)
# ---------------------------------------------------------------------------


class TestFireObservabilityCallbacks:
    """Tests for _fire_observability_callbacks."""

    def test_does_nothing_when_breaker_none(self):
        """breaker=None is a no-op (line 272)."""
        _fire_observability_callbacks(None, CircuitState.CLOSED, CircuitState.OPEN)

    def test_does_nothing_when_no_obs_callbacks(self):
        """Empty/missing _observability_callbacks is a no-op."""
        breaker = _make_breaker()
        breaker._observability_callbacks = []
        _fire_observability_callbacks(breaker, CircuitState.CLOSED, CircuitState.OPEN)

    def test_fires_observability_callbacks(self):
        """With callbacks and resilience_events available, fires them."""
        mock_cb = MagicMock()
        breaker = _make_breaker()
        breaker._observability_callbacks = [mock_cb]
        breaker.name = "obs-test"
        breaker.failure_count = 2
        breaker.success_count = 0

        mock_emit = MagicMock()
        mock_event_data_cls = MagicMock()
        mock_event_data_instance = MagicMock()
        mock_event_data_cls.return_value = mock_event_data_instance

        with patch.dict(
            "sys.modules",
            {
                "temper_ai.observability.resilience_events": MagicMock(
                    CircuitBreakerEventData=mock_event_data_cls,
                    emit_circuit_breaker_event=mock_emit,
                )
            },
        ):
            _fire_observability_callbacks(
                breaker, CircuitState.CLOSED, CircuitState.OPEN
            )

        mock_emit.assert_called_once_with(
            callback=mock_cb, event_data=mock_event_data_instance
        )


# ---------------------------------------------------------------------------
# on_call_success (lines 312-335)
# ---------------------------------------------------------------------------


class TestOnCallSuccess:
    """Tests for on_call_success helper."""

    def test_closed_state_increments_metrics(self):
        """Success in CLOSED state increments totals and resets failure count."""
        breaker = _make_breaker(state=CircuitState.CLOSED, failures=2)
        on_call_success(breaker)
        assert breaker.metrics.successful_calls == 1
        assert breaker.metrics.total_calls == 1
        assert breaker.failure_count == 0

    def test_half_open_success_increments_success_count(self):
        """Success in HALF_OPEN increments success_count (line 312)."""
        config = CircuitBreakerConfig(
            failure_threshold=3, success_threshold=2, timeout=60
        )
        breaker = CircuitBreaker(name="test2", config=config)
        breaker._state = CircuitState.HALF_OPEN
        breaker._success_count = 0
        on_call_success(breaker)
        # success_count incremented but not yet at threshold
        assert breaker.success_count == 1
        assert breaker._state == CircuitState.HALF_OPEN

    def test_half_open_reaches_threshold_transitions_to_closed(self):
        """When success_count reaches threshold in HALF_OPEN, transitions to CLOSED (lines 314-317)."""
        config = CircuitBreakerConfig(
            failure_threshold=3, success_threshold=2, timeout=60
        )
        breaker = CircuitBreaker(name="test3", config=config)
        breaker._state = CircuitState.HALF_OPEN
        breaker._success_count = 1  # one success already, one more = threshold 2

        on_call_success(breaker)

        assert breaker._state == CircuitState.CLOSED
        assert breaker.success_count == 0  # reset after close

    def test_half_open_reserved_state_releases_semaphore(self):
        """Semaphore is released when reserved_state is HALF_OPEN (line 330-331)."""
        breaker = _make_breaker(state=CircuitState.CLOSED)
        # Acquire semaphore to put it at 0
        acquired = breaker._half_open_semaphore.acquire(blocking=False)
        assert acquired

        on_call_success(breaker, reserved_state=CircuitState.HALF_OPEN)

        # After success, semaphore should be releasable again
        assert breaker._half_open_semaphore.acquire(blocking=False)
        breaker._half_open_semaphore.release()

    def test_success_fires_log_and_obs_callbacks_on_transition(self):
        """_log_state_transition and observability are called on HALF_OPEN->CLOSED."""
        config = CircuitBreakerConfig(
            failure_threshold=3, success_threshold=1, timeout=60
        )
        breaker = CircuitBreaker(name="test4", config=config)
        breaker._state = CircuitState.HALF_OPEN
        breaker._success_count = 0

        with (
            patch(
                "temper_ai.shared.core._circuit_breaker_helpers._log_state_transition"
            ) as mock_log,
            patch(
                "temper_ai.shared.core._circuit_breaker_helpers._fire_observability_callbacks"
            ) as mock_obs,
        ):
            on_call_success(breaker)

        mock_log.assert_called_once()
        mock_obs.assert_called_once()


# ---------------------------------------------------------------------------
# _should_open_on_failure (lines 348-359)
# ---------------------------------------------------------------------------


class TestShouldOpenOnFailure:
    """Tests for _should_open_on_failure."""

    def test_half_open_state_returns_true(self):
        """If breaker is HALF_OPEN, always return True (line 350-351)."""
        breaker = _make_breaker(state=CircuitState.HALF_OPEN)
        assert _should_open_on_failure(breaker, None) is True

    def test_reserved_half_open_but_state_changed_returns_true(self):
        """reserved_state=HALF_OPEN but breaker moved on (lines 352-356)."""
        breaker = _make_breaker(state=CircuitState.CLOSED)
        # reserved_state was HALF_OPEN but breaker is now CLOSED
        assert _should_open_on_failure(breaker, CircuitState.HALF_OPEN) is True

    def test_failure_threshold_reached_returns_true(self):
        """Failure count at threshold returns True (lines 357-358)."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(name="thresh", config=config)
        breaker._state = CircuitState.CLOSED
        breaker._failure_count = 3  # at threshold
        assert _should_open_on_failure(breaker, None) is True

    def test_below_threshold_closed_returns_false(self):
        """Below threshold in CLOSED state returns False (line 359)."""
        config = CircuitBreakerConfig(failure_threshold=5)
        breaker = CircuitBreaker(name="below", config=config)
        breaker._state = CircuitState.CLOSED
        breaker._failure_count = 2
        assert _should_open_on_failure(breaker, None) is False

    def test_reserved_closed_state_below_threshold_returns_false(self):
        """reserved_state=CLOSED, current=CLOSED, below threshold -> False."""
        config = CircuitBreakerConfig(failure_threshold=5)
        breaker = CircuitBreaker(name="ok", config=config)
        breaker._state = CircuitState.CLOSED
        breaker._failure_count = 1
        assert _should_open_on_failure(breaker, CircuitState.CLOSED) is False


# ---------------------------------------------------------------------------
# on_call_failure (lines 374-415)
# ---------------------------------------------------------------------------


class TestOnCallFailure:
    """Tests for on_call_failure helper."""

    def test_non_counting_error_returns_early(self):
        """Errors that don't count (e.g., ValueError) skip failure logic (lines 374-377)."""
        breaker = _make_breaker()
        initial_failed = breaker.metrics.failed_calls
        on_call_failure(breaker, ValueError("client error"))
        assert breaker.metrics.failed_calls == initial_failed

    def test_non_counting_error_with_half_open_releases_semaphore(self):
        """Non-counting error releases semaphore if reserved as HALF_OPEN (line 376)."""
        breaker = _make_breaker()
        acquired = breaker._half_open_semaphore.acquire(blocking=False)
        assert acquired

        on_call_failure(
            breaker, ValueError("client error"), reserved_state=CircuitState.HALF_OPEN
        )

        # Semaphore should be available again
        assert breaker._half_open_semaphore.acquire(blocking=False)
        breaker._half_open_semaphore.release()

    def test_counting_error_increments_failure_count(self):
        """Network error increments failure count and metrics."""
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not available")

        breaker = _make_breaker()
        exc = httpx.ConnectError("conn refused")
        on_call_failure(breaker, exc)

        assert breaker.metrics.failed_calls == 1
        assert breaker.failure_count >= 1

    def test_failure_trips_breaker_when_at_threshold(self):
        """When failure count reaches threshold, state transitions to OPEN."""
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not available")

        config = CircuitBreakerConfig(
            failure_threshold=3, success_threshold=2, timeout=60
        )
        breaker = CircuitBreaker(name="trip", config=config)
        breaker._failure_count = 2  # one more will trip

        exc = httpx.ConnectError("refused")
        on_call_failure(breaker, exc)

        assert breaker._state == CircuitState.OPEN

    def test_half_open_failure_releases_semaphore(self):
        """HALF_OPEN reserved state releases semaphore on failure (line 410-411)."""
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not available")

        breaker = _make_breaker(state=CircuitState.HALF_OPEN)
        acquired = breaker._half_open_semaphore.acquire(blocking=False)
        assert acquired

        on_call_failure(
            breaker,
            httpx.ConnectError("refused"),
            reserved_state=CircuitState.HALF_OPEN,
        )

        # semaphore released in finally
        assert breaker._half_open_semaphore.acquire(blocking=False)
        breaker._half_open_semaphore.release()

    def test_failure_fires_log_and_obs_callbacks_on_state_change(self):
        """State transition callbacks fire when breaker trips to OPEN."""
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not available")

        config = CircuitBreakerConfig(
            failure_threshold=1, success_threshold=2, timeout=60
        )
        breaker = CircuitBreaker(name="cb-fire", config=config)
        breaker._failure_count = 0

        with (
            patch(
                "temper_ai.shared.core._circuit_breaker_helpers._log_state_transition"
            ) as mock_log,
            patch(
                "temper_ai.shared.core._circuit_breaker_helpers._fire_observability_callbacks"
            ) as mock_obs,
        ):
            on_call_failure(breaker, httpx.ConnectError("refused"))

        mock_log.assert_called_once()
        mock_obs.assert_called_once()

    def test_failure_does_not_fire_callbacks_without_state_change(self):
        """Callbacks not fired if state did not change."""
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not available")

        config = CircuitBreakerConfig(
            failure_threshold=10, success_threshold=2, timeout=60
        )
        breaker = CircuitBreaker(name="no-trip", config=config)
        breaker._failure_count = 0

        with (
            patch(
                "temper_ai.shared.core._circuit_breaker_helpers._log_state_transition"
            ) as mock_log,
        ):
            on_call_failure(breaker, httpx.ConnectError("refused"))

        mock_log.assert_not_called()


# ---------------------------------------------------------------------------
# reserve_execution (lines 434-437, 452-455)
# ---------------------------------------------------------------------------


class TestReserveExecution:
    """Tests for reserve_execution."""

    def test_closed_state_returns_closed(self):
        """CLOSED state allows execution and returns CircuitState.CLOSED."""
        breaker = _make_breaker(state=CircuitState.CLOSED)
        result = reserve_execution(breaker)
        assert result == CircuitState.CLOSED

    def test_open_state_past_timeout_transitions_to_half_open(self):
        """OPEN state past timeout transitions to HALF_OPEN and returns it."""
        import time

        breaker = _make_breaker(state=CircuitState.OPEN)
        breaker._last_failure_time = time.time() - 300  # far past timeout

        result = reserve_execution(breaker)
        assert result == CircuitState.HALF_OPEN
        assert breaker._state == CircuitState.HALF_OPEN

    def test_open_state_before_timeout_returns_none(self):
        """OPEN state within timeout returns None (blocked)."""
        import time

        breaker = _make_breaker(state=CircuitState.OPEN)
        breaker._last_failure_time = time.time()  # just now

        result = reserve_execution(breaker)
        assert result is None

    def test_half_open_semaphore_blocked_raises_error(self):
        """If HALF_OPEN semaphore is already acquired, raises CircuitBreakerError (lines 452-455)."""
        breaker = _make_breaker(state=CircuitState.HALF_OPEN)
        # Consume the semaphore slot
        acquired = breaker._half_open_semaphore.acquire(blocking=False)
        assert acquired

        try:
            with pytest.raises(CircuitBreakerError):
                reserve_execution(breaker)
        finally:
            breaker._half_open_semaphore.release()

    def test_half_open_semaphore_blocked_increments_rejected_calls(self):
        """Rejected HALF_OPEN execution increments rejected_calls metric."""
        breaker = _make_breaker(state=CircuitState.HALF_OPEN)
        acquired = breaker._half_open_semaphore.acquire(blocking=False)
        assert acquired

        try:
            with pytest.raises(CircuitBreakerError):
                reserve_execution(breaker)
            assert breaker.metrics.rejected_calls == 1
        finally:
            breaker._half_open_semaphore.release()

    def test_half_open_allows_execution_when_semaphore_free(self):
        """HALF_OPEN state allows single execution when semaphore is free."""
        breaker = _make_breaker(state=CircuitState.HALF_OPEN)
        result = reserve_execution(breaker)
        assert result == CircuitState.HALF_OPEN
        # Release for cleanup
        breaker._half_open_semaphore.release()


# ---------------------------------------------------------------------------
# fire_callbacks with breaker (lines 277-291 via fire_callbacks)
# ---------------------------------------------------------------------------


class TestFireCallbacksWithBreaker:
    """Test fire_callbacks passing a breaker instance."""

    def test_fire_with_breaker_triggers_observability(self):
        """fire_callbacks with breaker calls _fire_observability_callbacks."""
        cb = MagicMock()
        breaker = _make_breaker()
        breaker._observability_callbacks = []

        transition = (CircuitState.CLOSED, CircuitState.OPEN, [cb])

        with patch(
            "temper_ai.shared.core._circuit_breaker_helpers._fire_observability_callbacks"
        ) as mock_obs:
            fire_callbacks(transition, breaker=breaker)

        mock_obs.assert_called_once_with(
            breaker, CircuitState.CLOSED, CircuitState.OPEN
        )

    def test_fire_callbacks_calls_all_state_callbacks_with_breaker(self):
        """All state change callbacks get called even with breaker provided."""
        cb1 = MagicMock()
        cb2 = MagicMock()
        breaker = _make_breaker()
        transition = (CircuitState.CLOSED, CircuitState.OPEN, [cb1, cb2])

        with patch(
            "temper_ai.shared.core._circuit_breaker_helpers._fire_observability_callbacks"
        ):
            fire_callbacks(transition, breaker=breaker)

        cb1.assert_called_once_with(CircuitState.CLOSED, CircuitState.OPEN)
        cb2.assert_called_once_with(CircuitState.CLOSED, CircuitState.OPEN)
