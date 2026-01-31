"""
Centralized error handling utilities.

Provides common error handling patterns including retry strategies,
exponential backoff, and standardized error result creation.
"""
import time
import logging
from typing import Callable, TypeVar, Optional, Any, Dict, Type, Tuple
from functools import wraps
from enum import Enum

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryStrategy(Enum):
    """Retry strategy types."""
    NONE = "none"
    FIXED_DELAY = "fixed"
    EXPONENTIAL_BACKOFF = "exponential"
    LINEAR_BACKOFF = "linear"


class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds (caps exponential growth)
        strategy: Retry strategy to use
        backoff_multiplier: Multiplier for delay (default 2.0 for exponential)
        retryable_exceptions: Tuple of exception types to retry
    """

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF,
        backoff_multiplier: float = 2.0,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.strategy = strategy
        self.backoff_multiplier = backoff_multiplier
        self.retryable_exceptions = retryable_exceptions or (Exception,)

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number.

        Args:
            attempt: Attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        if self.strategy == RetryStrategy.NONE:
            return 0.0
        elif self.strategy == RetryStrategy.FIXED_DELAY:
            delay = self.initial_delay
        elif self.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = self.initial_delay * (attempt + 1)
        elif self.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = self.initial_delay * (self.backoff_multiplier ** attempt)
        else:
            delay = self.initial_delay  # type: ignore[unreachable]

        # Cap at max_delay
        return min(delay, self.max_delay)


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for automatic retry with backoff.

    Args:
        max_retries: Maximum retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay cap
        strategy: Retry strategy to use
        retryable_exceptions: Exception types to retry (default: all exceptions)
        on_retry: Callback function called on each retry (exception, attempt_number)

    Returns:
        Decorator function

    Example:
        >>> @retry_with_backoff(max_retries=3, initial_delay=1.0)
        ... def unstable_api_call():
        ...     response = requests.get("https://api.example.com")
        ...     return response.json()

        >>> @retry_with_backoff(
        ...     max_retries=5,
        ...     strategy=RetryStrategy.LINEAR_BACKOFF,
        ...     retryable_exceptions=(ConnectionError, TimeoutError)
        ... )
        ... def network_operation():
        ...     pass
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        strategy=strategy,
        retryable_exceptions=retryable_exceptions
    )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None

            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e

                    # Don't retry on last attempt
                    if attempt == config.max_retries:
                        break

                    # Calculate delay
                    delay = config.calculate_delay(attempt)

                    # Log retry attempt
                    logger.warning(
                        f"Attempt {attempt + 1}/{config.max_retries + 1} failed for {func.__name__}: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )

                    # Call retry callback if provided
                    if on_retry:
                        on_retry(e, attempt + 1)

                    # Wait before retry
                    if delay > 0:
                        time.sleep(delay)

            # All retries exhausted
            logger.error(
                f"All {config.max_retries + 1} attempts failed for {func.__name__}: {last_exception}"
            )
            assert last_exception is not None, "last_exception should not be None after retries"
            raise last_exception

        return wrapper
    return decorator


def safe_execute(
    func: Callable[..., T],
    *args: Any,
    default: Optional[T] = None,
    log_errors: bool = True,
    **kwargs: Any
) -> Tuple[Optional[T], Optional[Exception]]:
    """Safely execute a function and return result or error.

    Args:
        func: Function to execute
        *args: Positional arguments for func
        default: Default value to return on error
        log_errors: Whether to log errors
        **kwargs: Keyword arguments for func

    Returns:
        Tuple of (result, error). One will be None.

    Example:
        >>> result, error = safe_execute(risky_operation, param=123)
        >>> if error:
        ...     print(f"Operation failed: {error}")
        ... else:
        ...     print(f"Success: {result}")
    """
    try:
        result = func(*args, **kwargs)
        return result, None
    except Exception as e:
        if log_errors:
            logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
        return default, e


def create_error_result(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    include_traceback: bool = False
) -> Dict[str, Any]:
    """Create standardized error result dictionary.

    Args:
        error: Exception that occurred
        context: Additional context information
        include_traceback: Whether to include traceback (for debugging)

    Returns:
        Standardized error result dict

    Example:
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     return create_error_result(e, context={"user_id": 123})
    """
    import traceback

    result = {
        "success": False,
        "error": str(error),
        "error_type": type(error).__name__,
        "metadata": context or {}
    }

    if include_traceback:
        result["traceback"] = traceback.format_exc()

    return result


class ErrorHandler:
    """Reusable error handler with configurable behavior.

    Example:
        >>> handler = ErrorHandler(
        ...     max_retries=3,
        ...     log_errors=True,
        ...     raise_on_failure=False
        ... )
        >>>
        >>> result = handler.execute(
        ...     risky_function,
        ...     arg1="value",
        ...     fallback_value="default"
        ... )
    """

    def __init__(
        self,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        log_errors: bool = True,
        raise_on_failure: bool = True
    ):
        """Initialize error handler.

        Args:
            max_retries: Maximum retry attempts
            retry_delay: Base delay for retries
            log_errors: Whether to log errors
            raise_on_failure: Whether to raise on final failure
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.log_errors = log_errors
        self.raise_on_failure = raise_on_failure

    def execute(
        self,
        func: Callable[..., T],
        *args: Any,
        fallback_value: Optional[T] = None,
        **kwargs: Any
    ) -> Optional[T]:
        """Execute function with error handling and retries.

        Args:
            func: Function to execute
            *args: Positional arguments
            fallback_value: Value to return if all attempts fail
            **kwargs: Keyword arguments

        Returns:
            Function result or fallback value

        Raises:
            Exception if raise_on_failure=True and all attempts fail
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e

                if self.log_errors:
                    logger.warning(
                        f"Attempt {attempt + 1}/{self.max_retries + 1} failed: {e}"
                    )

                # Don't sleep on last attempt
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * (2 ** attempt))

        # All attempts failed
        if self.raise_on_failure:
            assert last_exception is not None, "last_exception should not be None after retries"
            raise last_exception

        return fallback_value
