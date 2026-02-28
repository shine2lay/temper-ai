"""Tests for temper_ai/shared/core/_circuit_breaker_helpers.py.

Covers pure helper functions extracted from CircuitBreaker.
"""

import json
import time
from unittest.mock import MagicMock

import pytest

from temper_ai.shared.core._circuit_breaker_helpers import (
    _get_state_key,
    _should_attempt_reset,
    _should_count_failure,
    fire_callbacks,
    load_state,
    save_state,
    time_until_retry,
)
from temper_ai.shared.core.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitState,
)

# ---------------------------------------------------------------------------
# _should_count_failure
# ---------------------------------------------------------------------------


class TestShouldCountFailure:
    def test_generic_exception_returns_false(self):
        """Generic exceptions that are not network/LLM errors return False."""
        exc = ValueError("some app error")
        assert _should_count_failure(exc) is False

    def test_generic_runtime_error_returns_false(self):
        exc = RuntimeError("runtime")
        assert _should_count_failure(exc) is False

    def test_httpx_connect_error_counts(self):
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")
        exc = httpx.ConnectError("connection refused")
        assert _should_count_failure(exc) is True

    def test_httpx_timeout_counts(self):
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")
        exc = httpx.ReadTimeout("timeout")
        assert _should_count_failure(exc) is True

    def test_httpx_500_status_counts(self):
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")
        response = MagicMock()
        response.status_code = 503
        exc = httpx.HTTPStatusError(
            "server error", request=MagicMock(), response=response
        )
        assert _should_count_failure(exc) is True

    def test_httpx_429_counts(self):
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")
        response = MagicMock()
        response.status_code = 429
        exc = httpx.HTTPStatusError(
            "rate limited", request=MagicMock(), response=response
        )
        assert _should_count_failure(exc) is True

    def test_httpx_400_does_not_count(self):
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")
        response = MagicMock()
        response.status_code = 400
        exc = httpx.HTTPStatusError(
            "bad request", request=MagicMock(), response=response
        )
        assert _should_count_failure(exc) is False

    def test_httpx_404_does_not_count(self):
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")
        response = MagicMock()
        response.status_code = 404
        exc = httpx.HTTPStatusError("not found", request=MagicMock(), response=response)
        assert _should_count_failure(exc) is False

    def test_llm_auth_error_does_not_count(self):
        """LLMAuthenticationError should NOT count as a circuit-breaker failure."""
        try:
            from temper_ai.shared.utils.exceptions import LLMAuthenticationError
        except ImportError:
            pytest.skip("LLMAuthenticationError not available")
        exc = LLMAuthenticationError("bad key")
        assert _should_count_failure(exc) is False

    def test_llm_timeout_error_counts(self):
        try:
            from temper_ai.shared.utils.exceptions import LLMTimeoutError
        except ImportError:
            pytest.skip("LLMTimeoutError not available")
        exc = LLMTimeoutError("timed out")
        assert _should_count_failure(exc) is True

    def test_llm_rate_limit_error_counts(self):
        try:
            from temper_ai.shared.utils.exceptions import LLMRateLimitError
        except ImportError:
            pytest.skip("LLMRateLimitError not available")
        exc = LLMRateLimitError("rate limited")
        assert _should_count_failure(exc) is True


# ---------------------------------------------------------------------------
# _should_attempt_reset
# ---------------------------------------------------------------------------


class TestShouldAttemptReset:
    def test_none_last_failure_returns_true(self):
        """No recorded failure means reset should be attempted."""
        assert _should_attempt_reset(None, 60) is True

    def test_recent_failure_returns_false(self):
        """Recent failure (within timeout) should not attempt reset."""
        last = time.time() - 10  # 10 seconds ago
        assert _should_attempt_reset(last, 60) is False

    def test_old_failure_returns_true(self):
        """Old failure (past timeout) should attempt reset."""
        last = time.time() - 120  # 120 seconds ago
        assert _should_attempt_reset(last, 60) is True

    def test_exactly_at_timeout_returns_true(self):
        """Elapsed exactly equal to timeout returns True."""
        timeout = 60
        last = time.time() - timeout
        # should be >= so True
        result = _should_attempt_reset(last, timeout)
        assert result is True

    def test_zero_timeout_always_resets(self):
        """Timeout=0 means always attempt reset."""
        last = time.time()  # just now
        assert _should_attempt_reset(last, 0) is True


# ---------------------------------------------------------------------------
# time_until_retry
# ---------------------------------------------------------------------------


class TestTimeUntilRetry:
    def test_none_last_failure_returns_zero(self):
        assert time_until_retry(None, 60) == 0

    def test_recent_failure_returns_remaining_seconds(self):
        timeout = 60
        last = time.time() - 20  # 20 seconds ago, 40 seconds remain
        remaining = time_until_retry(last, timeout)
        # Should be approximately 40
        assert 35 < remaining <= 40

    def test_expired_failure_returns_zero(self):
        """After timeout elapsed, remaining is 0."""
        last = time.time() - 120
        result = time_until_retry(last, 60)
        assert result == 0

    def test_result_is_non_negative(self):
        """Never returns a negative value."""
        last = time.time() - 10000
        assert time_until_retry(last, 60) >= 0


# ---------------------------------------------------------------------------
# _get_state_key
# ---------------------------------------------------------------------------


class TestGetStateKey:
    def test_returns_expected_format(self):
        key = _get_state_key("my-breaker")
        assert key == "circuit_breaker:my-breaker:state"

    def test_name_included_in_key(self):
        key = _get_state_key("production-llm")
        assert "production-llm" in key

    def test_different_names_produce_different_keys(self):
        k1 = _get_state_key("breaker-a")
        k2 = _get_state_key("breaker-b")
        assert k1 != k2

    def test_returns_string(self):
        assert isinstance(_get_state_key("test"), str)


# ---------------------------------------------------------------------------
# save_state
# ---------------------------------------------------------------------------


class TestSaveState:
    def test_no_storage_does_nothing(self):
        """save_state with no storage is a no-op."""
        save_state(None, "test", CircuitState.CLOSED, 0, 0, None, MagicMock())

    def test_saves_to_storage(self):
        storage = MagicMock()
        config = CircuitBreakerConfig(
            failure_threshold=5, success_threshold=2, timeout=60
        )
        save_state(storage, "test", CircuitState.CLOSED, 0, 0, None, config)
        storage.set.assert_called_once()

    def test_saved_value_is_json(self):
        """The value stored is valid JSON."""
        storage = MagicMock()
        config = CircuitBreakerConfig()
        save_state(storage, "test", CircuitState.OPEN, 3, 0, 1234567.0, config)

        call_args = storage.set.call_args
        key, value = call_args[0]
        parsed = json.loads(value)
        assert parsed["state"] == "open"
        assert parsed["failure_count"] == 3
        assert parsed["last_failure_time"] == 1234567.0

    def test_key_is_correct(self):
        storage = MagicMock()
        config = CircuitBreakerConfig()
        save_state(storage, "my-breaker", CircuitState.CLOSED, 0, 0, None, config)
        key = storage.set.call_args[0][0]
        assert "my-breaker" in key


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------


class TestLoadState:
    def test_no_storage_returns_defaults(self):
        result = load_state(None, "test")
        assert result["state"] == CircuitState.CLOSED
        assert result["failure_count"] == 0
        assert result["success_count"] == 0

    def test_missing_key_returns_defaults(self):
        storage = MagicMock()
        storage.get.return_value = None
        result = load_state(storage, "test")
        assert result["state"] == CircuitState.CLOSED

    def test_loads_saved_state(self):
        state_data = json.dumps(
            {
                "state": "open",
                "failure_count": 4,
                "success_count": 0,
                "last_failure_time": 1234.5,
                "config": {
                    "failure_threshold": 5,
                    "success_threshold": 2,
                    "timeout": 60,
                },
            }
        )
        storage = MagicMock()
        storage.get.return_value = state_data
        result = load_state(storage, "test")
        assert result["state"] == CircuitState.OPEN
        assert result["failure_count"] == 4
        assert result["last_failure_time"] == 1234.5

    def test_loads_config_from_storage(self):
        state_data = json.dumps(
            {
                "state": "closed",
                "failure_count": 0,
                "success_count": 0,
                "last_failure_time": None,
                "config": {
                    "failure_threshold": 10,
                    "success_threshold": 3,
                    "timeout": 120,
                },
            }
        )
        storage = MagicMock()
        storage.get.return_value = state_data
        result = load_state(storage, "test")
        assert isinstance(result["config"], CircuitBreakerConfig)
        assert result["config"].failure_threshold == 10

    def test_corrupt_json_returns_defaults(self):
        storage = MagicMock()
        storage.get.return_value = "not-valid-json"
        result = load_state(storage, "test")
        assert result["state"] == CircuitState.CLOSED

    def test_missing_config_key_returns_none_config(self):
        state_data = json.dumps(
            {
                "state": "closed",
                "failure_count": 0,
                "success_count": 0,
                "last_failure_time": None,
            }
        )
        storage = MagicMock()
        storage.get.return_value = state_data
        result = load_state(storage, "test")
        assert result["config"] is None


# ---------------------------------------------------------------------------
# fire_callbacks
# ---------------------------------------------------------------------------


class TestFireCallbacks:
    def test_none_transition_info_does_nothing(self):
        """fire_callbacks(None) is a no-op."""
        fire_callbacks(None)  # Should not raise

    def test_fires_state_change_callbacks(self):
        cb = MagicMock()
        transition = (CircuitState.CLOSED, CircuitState.OPEN, [cb])
        fire_callbacks(transition)
        cb.assert_called_once_with(CircuitState.CLOSED, CircuitState.OPEN)

    def test_error_in_callback_does_not_propagate(self):
        def bad_cb(old, new):
            raise RuntimeError("callback error")

        transition = (CircuitState.CLOSED, CircuitState.OPEN, [bad_cb])
        fire_callbacks(transition)  # Should not raise

    def test_all_callbacks_called(self):
        cb1 = MagicMock()
        cb2 = MagicMock()
        transition = (CircuitState.CLOSED, CircuitState.OPEN, [cb1, cb2])
        fire_callbacks(transition)
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_later_callbacks_called_even_after_error(self):
        cb_good = MagicMock()

        def bad_cb(old, new):
            raise RuntimeError("error")

        transition = (CircuitState.CLOSED, CircuitState.OPEN, [bad_cb, cb_good])
        fire_callbacks(transition)
        cb_good.assert_called_once()

    def test_fire_with_no_state_change_callbacks(self):
        """Empty callbacks list should work without errors."""
        transition = (CircuitState.CLOSED, CircuitState.OPEN, [])
        fire_callbacks(transition)  # Should not raise

    def test_fire_with_breaker_none(self):
        """Passing breaker=None does not crash."""
        cb = MagicMock()
        transition = (CircuitState.CLOSED, CircuitState.OPEN, [cb])
        fire_callbacks(transition, breaker=None)
        cb.assert_called_once()
