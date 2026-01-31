"""
Circuit breaker pattern for LLM provider resilience.

Prevents cascading failures when providers are down or rate-limited by:
- Opening circuit after repeated failures (fast-fail)
- Testing recovery through half-open state
- Auto-recovering when provider is healthy

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, fast-fail without calling provider
- HALF_OPEN: Testing if provider recovered, allow limited requests
"""
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Any, TypeVar, Optional, Type
import time
import threading

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing, fast-fail
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5   # Failures before opening
    success_threshold: int = 2   # Successes to close from half-open
    timeout: int = 60            # Seconds before trying half-open


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """
    Circuit breaker for LLM provider resilience.

    Features:
    - Fast-fail when provider is down (reduces latency)
    - Auto-recovery through half-open state
    - Thread-safe for concurrent requests
    - Per-provider isolation

    Examples:
        >>> breaker = CircuitBreaker("ollama")
        >>> try:
        ...     result = breaker.call(api_request, prompt="Hello")
        ... except CircuitBreakerError:
        ...     print("Circuit is open, provider is down")
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize circuit breaker.

        Args:
            name: Provider name (for error messages)
            config: Circuit breaker configuration
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.lock = threading.Lock()

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute function through circuit breaker.

        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from func

        Raises:
            CircuitBreakerError: If circuit is open
            Any exception raised by func

        Example:
            >>> breaker = CircuitBreaker("provider")
            >>> result = breaker.call(lambda: "success")
            >>> print(result)
            'success'
        """
        # Check if circuit is open
        with self.lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    # Transition to half-open to test recovery
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                else:
                    # Circuit still open, fast-fail
                    raise CircuitBreakerError(
                        f"Circuit breaker OPEN for {self.name}. "
                        f"Retry after {self._time_until_retry():.0f}s"
                    )

        # Execute function
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            raise

    def _on_success(self) -> None:
        """Handle successful call."""
        with self.lock:
            # Reset failure count
            self.failure_count = 0

            # If half-open, count successes toward closing
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    # Provider recovered, close circuit
                    self.state = CircuitState.CLOSED
                    self.success_count = 0

    def _on_failure(self, error: Exception) -> None:
        """Handle failed call."""
        # Only count certain errors
        if not self._should_count_failure(error):
            return

        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            # If half-open and fails, immediately re-open
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
            # If closed and hit threshold, open circuit
            elif self.failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN

    def _should_count_failure(self, error: Exception) -> bool:
        """
        Determine if error should count toward circuit breaker.

        Network/server errors count (transient):
        - Connection errors (provider down)
        - Timeouts (provider slow)
        - HTTP 5xx (server errors)
        - HTTP 429 (rate limiting)

        Client errors don't count (user error, won't improve):
        - HTTP 401 (auth error)
        - HTTP 400 (bad request)
        - HTTP 404 (not found)

        Args:
            error: Exception raised by API call

        Returns:
            True if error should count, False otherwise
        """
        import httpx

        # Import LLM exceptions
        LLMError: Optional[Type[Exception]]
        LLMTimeoutError: Optional[Type[Exception]]
        LLMRateLimitError: Optional[Type[Exception]]
        LLMAuthenticationError: Optional[Type[Exception]]

        try:
            from src.utils.exceptions import (
                LLMError,
                LLMTimeoutError,
                LLMRateLimitError,
                LLMAuthenticationError,
            )
        except ImportError:
            # Fallback if exceptions not available
            LLMError = None
            LLMTimeoutError = None
            LLMRateLimitError = None
            LLMAuthenticationError = None

        # Network/connection errors count
        if isinstance(error, (httpx.ConnectError, httpx.TimeoutException)):
            return True

        # Timeout errors count
        if LLMTimeoutError and isinstance(error, LLMTimeoutError):
            return True

        # Rate limit errors count (429)
        if LLMRateLimitError and isinstance(error, LLMRateLimitError):
            return True

        # Server errors count (LLMError typically indicates 5xx)
        # Note: We check this before LLMAuthenticationError since it's a subclass
        if LLMAuthenticationError and isinstance(error, LLMAuthenticationError):
            return False  # Client errors don't count

        if LLMError and isinstance(error, LLMError):
            # LLMError is raised for server errors (5xx)
            return True

        # HTTP status errors
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            # 5xx server errors and 429 count
            return status >= 500 or status == 429

        # Unknown errors don't count (conservative approach)
        return False

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try half-open."""
        if self.last_failure_time is None:
            return True
        elapsed = time.time() - self.last_failure_time
        return elapsed >= self.config.timeout

    def _time_until_retry(self) -> float:
        """Seconds until circuit will try half-open."""
        if self.last_failure_time is None:
            return 0
        elapsed = time.time() - self.last_failure_time
        return max(0, self.config.timeout - elapsed)

    def reset(self) -> None:
        """Reset circuit breaker to closed state (for testing)."""
        with self.lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
