"""Tests for src/utils/error_handling.py.

Tests retry strategies, error handlers, and safe execution utilities.
"""
import time
from unittest.mock import Mock

import pytest

from src.utils.error_handling import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_MAX_RETRIES,
    ErrorHandler,
    MIN_BACKOFF_SECONDS,
    RetryParams,
    RetryStrategy,
    create_error_result,
    retry_with_backoff,
    safe_execute,
)


class TestRetryStrategy:
    """Test retry strategy enum."""

    def test_retry_strategy_values(self):
        """Test that all retry strategies have correct values."""
        assert RetryStrategy.NONE.value == "none"
        assert RetryStrategy.FIXED_DELAY.value == "fixed"
        assert RetryStrategy.EXPONENTIAL_BACKOFF.value == "exponential"
        assert RetryStrategy.LINEAR_BACKOFF.value == "linear"


class TestRetryParams:
    """Test retry parameter configuration."""

    def test_default_params(self):
        """Test default retry parameters."""
        params = RetryParams()
        assert params.max_retries == DEFAULT_MAX_RETRIES
        assert params.initial_delay == MIN_BACKOFF_SECONDS
        assert params.strategy == RetryStrategy.EXPONENTIAL_BACKOFF
        assert params.backoff_multiplier == DEFAULT_BACKOFF_MULTIPLIER
        assert params.retryable_exceptions == (Exception,)

    def test_custom_params(self):
        """Test custom retry parameters."""
        params = RetryParams(
            max_retries=5,
            initial_delay=2.0,
            max_delay=60.0,
            strategy=RetryStrategy.LINEAR_BACKOFF,
            backoff_multiplier=1.5,
            retryable_exceptions=(ValueError, TypeError)
        )
        assert params.max_retries == 5
        assert params.initial_delay == 2.0
        assert params.max_delay == 60.0
        assert params.strategy == RetryStrategy.LINEAR_BACKOFF
        assert params.backoff_multiplier == 1.5
        assert params.retryable_exceptions == (ValueError, TypeError)

    def test_calculate_delay_none(self):
        """Test delay calculation with NONE strategy."""
        params = RetryParams(strategy=RetryStrategy.NONE)
        assert params.calculate_delay(0) == 0.0
        assert params.calculate_delay(5) == 0.0

    def test_calculate_delay_fixed(self):
        """Test delay calculation with FIXED_DELAY strategy."""
        params = RetryParams(initial_delay=1.0, strategy=RetryStrategy.FIXED_DELAY)
        assert params.calculate_delay(0) == 1.0
        assert params.calculate_delay(3) == 1.0
        assert params.calculate_delay(10) == 1.0

    def test_calculate_delay_linear(self):
        """Test delay calculation with LINEAR_BACKOFF strategy."""
        params = RetryParams(initial_delay=1.0, strategy=RetryStrategy.LINEAR_BACKOFF)
        assert params.calculate_delay(0) == 1.0
        assert params.calculate_delay(1) == 2.0
        assert params.calculate_delay(2) == 3.0
        assert params.calculate_delay(5) == 6.0

    def test_calculate_delay_exponential(self):
        """Test delay calculation with EXPONENTIAL_BACKOFF strategy."""
        params = RetryParams(initial_delay=1.0, strategy=RetryStrategy.EXPONENTIAL_BACKOFF, backoff_multiplier=2.0)
        assert params.calculate_delay(0) == 1.0
        assert params.calculate_delay(1) == 2.0
        assert params.calculate_delay(2) == 4.0
        assert params.calculate_delay(3) == 8.0

    def test_calculate_delay_capped(self):
        """Test that delay is capped at max_delay."""
        params = RetryParams(initial_delay=1.0, max_delay=5.0, strategy=RetryStrategy.EXPONENTIAL_BACKOFF)
        assert params.calculate_delay(0) == 1.0
        assert params.calculate_delay(1) == 2.0
        assert params.calculate_delay(2) == 4.0
        assert params.calculate_delay(3) == 5.0  # Capped at max_delay
        assert params.calculate_delay(10) == 5.0  # Still capped


class TestRetryWithBackoff:
    """Test retry_with_backoff decorator."""

    def test_success_first_try(self):
        """Test successful function on first attempt."""
        mock_func = Mock(return_value="success")

        @retry_with_backoff(max_retries=3)
        def test_func():
            return mock_func()

        result = test_func()
        assert result == "success"
        assert mock_func.call_count == 1

    def test_success_after_retries(self):
        """Test successful function after retries."""
        mock_func = Mock(side_effect=[ValueError("fail1"), ValueError("fail2"), "success"])

        @retry_with_backoff(max_retries=3, initial_delay=0.01)
        def test_func():
            return mock_func()

        result = test_func()
        assert result == "success"
        assert mock_func.call_count == 3

    def test_all_retries_exhausted(self):
        """Test when all retries are exhausted."""
        mock_func = Mock(side_effect=ValueError("always fails"))

        @retry_with_backoff(max_retries=2, initial_delay=0.01)
        def test_func():
            return mock_func()

        with pytest.raises(ValueError, match="always fails"):
            test_func()

        assert mock_func.call_count == 3  # Initial + 2 retries

    def test_specific_exceptions_only(self):
        """Test retrying only specific exception types."""
        mock_func = Mock(side_effect=RuntimeError("not retryable"))

        @retry_with_backoff(max_retries=3, initial_delay=0.01, retryable_exceptions=(ValueError,))
        def test_func():
            return mock_func()

        with pytest.raises(RuntimeError, match="not retryable"):
            test_func()

        assert mock_func.call_count == 1  # No retries for RuntimeError

    def test_on_retry_callback(self):
        """Test on_retry callback is invoked."""
        callback_mock = Mock()
        mock_func = Mock(side_effect=[ValueError("fail1"), "success"])

        @retry_with_backoff(max_retries=2, initial_delay=0.01, on_retry=callback_mock)
        def test_func():
            return mock_func()

        result = test_func()
        assert result == "success"
        assert callback_mock.call_count == 1
        # Verify callback received exception and attempt number
        callback_mock.assert_called_once()
        args = callback_mock.call_args[0]
        assert isinstance(args[0], ValueError)
        assert args[1] == 1

    def test_exponential_backoff_timing(self):
        """Test that exponential backoff delays increase."""
        mock_func = Mock(side_effect=[ValueError(), ValueError(), "success"])

        @retry_with_backoff(max_retries=3, initial_delay=0.01, strategy=RetryStrategy.EXPONENTIAL_BACKOFF)
        def test_func():
            return mock_func()

        start = time.time()
        result = test_func()
        elapsed = time.time() - start

        assert result == "success"
        # 0.01 + 0.02 + actual execution ≈ 0.03 seconds minimum
        assert elapsed >= 0.03


class TestSafeExecute:
    """Test safe_execute function."""

    def test_success(self):
        """Test successful execution."""
        result, error = safe_execute(lambda: "success")
        assert result == "success"
        assert error is None

    def test_error_caught(self):
        """Test error is caught and returned."""
        result, error = safe_execute(lambda: [][0])  # IndexError instead of ZeroDivisionError
        assert result is None
        assert isinstance(error, IndexError)

    def test_default_value_on_error(self):
        """Test default value is returned on error."""
        result, error = safe_execute(lambda: [][0], default="default")  # IndexError
        assert result == "default"
        assert isinstance(error, IndexError)

    def test_with_args_kwargs(self):
        """Test execution with positional and keyword arguments."""
        def test_func(a, b, c=0):
            return a + b + c

        result, error = safe_execute(test_func, 1, 2, c=3)
        assert result == 6
        assert error is None

    def test_log_errors_false(self):
        """Test that errors are not logged when log_errors=False."""
        result, error = safe_execute(lambda: [][0], log_errors=False)  # IndexError
        assert result is None
        assert isinstance(error, IndexError)


class TestCreateErrorResult:
    """Test create_error_result function."""

    def test_basic_error_result(self):
        """Test basic error result creation."""
        error = ValueError("test error")
        result = create_error_result(error)

        assert result["success"] is False
        assert result["error"] == "test error"
        assert result["error_type"] == "ValueError"
        assert "metadata" in result
        assert result["metadata"] == {}

    def test_with_context(self):
        """Test error result with context."""
        error = ValueError("test error")
        context = {"user_id": 123, "action": "test"}
        result = create_error_result(error, context=context)

        assert result["metadata"] == context

    def test_with_traceback(self):
        """Test error result with traceback."""
        error = ValueError("test error")
        result = create_error_result(error, include_traceback=True)

        assert "traceback" in result
        assert isinstance(result["traceback"], str)

    def test_without_traceback(self):
        """Test error result without traceback."""
        error = ValueError("test error")
        result = create_error_result(error, include_traceback=False)

        assert "traceback" not in result


class TestErrorHandler:
    """Test ErrorHandler class."""

    def test_default_initialization(self):
        """Test ErrorHandler default initialization."""
        handler = ErrorHandler()
        assert handler.max_retries == DEFAULT_MAX_RETRIES
        assert handler.retry_delay == MIN_BACKOFF_SECONDS
        assert handler.log_errors is True
        assert handler.raise_on_failure is True

    def test_custom_initialization(self):
        """Test ErrorHandler custom initialization."""
        handler = ErrorHandler(
            max_retries=5,
            retry_delay=2.0,
            log_errors=False,
            raise_on_failure=False
        )
        assert handler.max_retries == 5
        assert handler.retry_delay == 2.0
        assert handler.log_errors is False
        assert handler.raise_on_failure is False

    def test_execute_success(self):
        """Test successful execution."""
        handler = ErrorHandler()
        result = handler.execute(lambda: "success")
        assert result == "success"

    def test_execute_with_retries(self):
        """Test execution with retries."""
        handler = ErrorHandler(max_retries=2, retry_delay=0.01)
        mock_func = Mock(side_effect=[ValueError("fail1"), "success"])

        result = handler.execute(mock_func)
        assert result == "success"
        assert mock_func.call_count == 2

    def test_execute_all_retries_exhausted_raise(self):
        """Test when all retries exhausted and raise_on_failure=True."""
        handler = ErrorHandler(max_retries=1, retry_delay=0.01, raise_on_failure=True)
        mock_func = Mock(side_effect=ValueError("always fails"))

        with pytest.raises(ValueError, match="always fails"):
            handler.execute(mock_func)

    def test_execute_all_retries_exhausted_no_raise(self):
        """Test when all retries exhausted and raise_on_failure=False."""
        handler = ErrorHandler(max_retries=1, retry_delay=0.01, raise_on_failure=False)
        mock_func = Mock(side_effect=ValueError("always fails"))

        result = handler.execute(mock_func)
        assert result is None

    def test_execute_fallback_value(self):
        """Test execution with fallback value."""
        handler = ErrorHandler(max_retries=1, retry_delay=0.01, raise_on_failure=False)
        mock_func = Mock(side_effect=ValueError("always fails"))

        result = handler.execute(mock_func, fallback_value="fallback")
        assert result == "fallback"

    def test_execute_with_args_kwargs(self):
        """Test execution with arguments."""
        handler = ErrorHandler()

        def test_func(a, b, c=0):
            return a + b + c

        result = handler.execute(test_func, 1, 2, c=3)
        assert result == 6
