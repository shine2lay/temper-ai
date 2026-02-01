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
from dataclasses import dataclass, asdict
from typing import Callable, Any, TypeVar, Optional, Type, Protocol
import time
import threading
import json

T = TypeVar('T')


class StateStorage(Protocol):
    """Protocol for state persistence storage backends."""

    def get(self, key: str) -> Optional[str]:
        """Retrieve state by key."""
        ...

    def set(self, key: str, value: str) -> None:
        """Store state by key."""
        ...

    def delete(self, key: str) -> None:
        """Delete state by key."""
        ...


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

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        storage: Optional[StateStorage] = None
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Provider name (for error messages)
            config: Circuit breaker configuration
            storage: Optional storage backend for state persistence
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.storage = storage
        self.lock = threading.Lock()

        # Semaphore to prevent thundering herd in HALF_OPEN state
        # Only allow 1 test execution at a time in HALF_OPEN
        self._half_open_semaphore = threading.Semaphore(1)

        # Try to load persisted state if storage provided
        if self.storage:
            self._load_state()
        else:
            # Initialize in-memory state
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time: Optional[float] = None

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute function through circuit breaker.

        SECURITY FIX: Uses state reservation pattern to prevent race conditions
        where state could change between check and execution.

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
        # Atomically check and reserve execution permission
        # This prevents race conditions where state changes between check and execution
        reserved_state = self._reserve_execution()

        if reserved_state is None:
            # Circuit is OPEN and timeout not elapsed
            raise CircuitBreakerError(
                f"Circuit breaker OPEN for {self.name}. "
                f"Retry after {self._time_until_retry():.0f}s"
            )

        # Execute function WITHOUT lock
        # At this point we have atomically reserved permission to execute
        try:
            result = func(*args, **kwargs)
            # Pass reserved state to handle state changes during execution
            self._on_success(reserved_state)
            return result
        except Exception as e:
            # Pass reserved state to handle state changes during execution
            self._on_failure(e, reserved_state)
            raise

    def _reserve_execution(self) -> Optional[CircuitState]:
        """
        Atomically check if execution is allowed and reserve permission.

        Thread-safety: This method is atomic - state cannot change between
        check and return. The returned state acts as a "ticket" for execution.

        For HALF_OPEN state, enforces single concurrent test execution using
        semaphore to prevent thundering herd attacks.

        Returns:
            CircuitState at time of reservation if allowed, None if blocked

        Example:
            >>> breaker = CircuitBreaker("provider")
            >>> state = breaker._reserve_execution()
            >>> if state:
            ...     # Execute protected function
            ...     result = func()
        """
        with self.lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    # Transition to half-open to test recovery
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                    if self.storage:
                        self._save_state()
                    # State is now HALF_OPEN, continue to semaphore check
                else:
                    # Circuit still open, deny execution
                    return None

            current_state = self.state

        # For HALF_OPEN state, enforce single concurrent test execution
        # This prevents thundering herd: only 1 thread tests at a time
        if current_state == CircuitState.HALF_OPEN:
            # Non-blocking acquire - fast-fail if another thread is testing
            if not self._half_open_semaphore.acquire(blocking=False):
                # Another thread is already testing recovery
                # Fast-fail to prevent overwhelming provider
                raise CircuitBreakerError(
                    f"Circuit breaker for {self.name} is testing recovery. "
                    f"Retry in 1-2 seconds."
                )

        # Circuit is CLOSED or HALF_OPEN (with semaphore acquired)
        return current_state

    def _on_success(self, reserved_state: Optional[CircuitState] = None) -> None:
        """
        Handle successful call.

        Args:
            reserved_state: State that was reserved for this execution.
                          Used to detect state changes during execution.

        Example:
            >>> breaker._on_success(CircuitState.HALF_OPEN)
        """
        try:
            with self.lock:
                # Reset failure count on success
                self.failure_count = 0

                # If half-open, count successes toward closing
                if self.state == CircuitState.HALF_OPEN:
                    self.success_count += 1
                    if self.success_count >= self.config.success_threshold:
                        # Provider recovered, close circuit
                        self.state = CircuitState.CLOSED
                        self.success_count = 0
                elif reserved_state == CircuitState.HALF_OPEN and self.state == CircuitState.OPEN:
                    # Circuit was re-opened by another thread during our execution
                    # Our success is ignored (conservative approach for safety)
                    pass

                # Persist state if storage available
                if self.storage:
                    self._save_state()
        finally:
            # Release semaphore if we were in HALF_OPEN state
            if reserved_state == CircuitState.HALF_OPEN:
                self._half_open_semaphore.release()

    def _on_failure(self, error: Exception, reserved_state: Optional[CircuitState] = None) -> None:
        """
        Handle failed call.

        Args:
            error: Exception that caused the failure
            reserved_state: State that was reserved for this execution

        Example:
            >>> breaker._on_failure(TimeoutError(), CircuitState.HALF_OPEN)
        """
        # Only count certain errors (network/server errors)
        if not self._should_count_failure(error):
            # Still need to release semaphore if we were in HALF_OPEN
            if reserved_state == CircuitState.HALF_OPEN:
                self._half_open_semaphore.release()
            return

        try:
            with self.lock:
                self.failure_count += 1
                self.last_failure_time = time.time()

                # If half-open and fails, immediately re-open
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.OPEN
                # If we reserved HALF_OPEN but current state changed, still re-open
                elif reserved_state == CircuitState.HALF_OPEN and self.state != CircuitState.HALF_OPEN:
                    # Circuit was modified by another thread, but we failed during test
                    self.state = CircuitState.OPEN
                # If closed and hit threshold, open circuit
                elif self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN

                # Persist state if storage available
                if self.storage:
                    self._save_state()
        finally:
            # Release semaphore if we were in HALF_OPEN state
            if reserved_state == CircuitState.HALF_OPEN:
                self._half_open_semaphore.release()

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
            if self.storage:
                self._save_state()

    def _get_state_key(self) -> str:
        """Get storage key for this circuit breaker."""
        return f"circuit_breaker:{self.name}:state"

    def _save_state(self) -> None:
        """Save circuit breaker state to storage."""
        if not self.storage:
            return

        state_dict = {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time,
            "config": asdict(self.config)
        }

        key = self._get_state_key()
        self.storage.set(key, json.dumps(state_dict))

    def _load_state(self) -> None:
        """Load circuit breaker state from storage."""
        if not self.storage:
            return

        key = self._get_state_key()
        data = self.storage.get(key)

        if data:
            try:
                state_dict = json.loads(data)
                self.state = CircuitState(state_dict["state"])
                self.failure_count = state_dict["failure_count"]
                self.success_count = state_dict["success_count"]
                self.last_failure_time = state_dict.get("last_failure_time")

                # Update config if saved config exists
                if "config" in state_dict:
                    saved_config = state_dict["config"]
                    self.config = CircuitBreakerConfig(**saved_config)
            except (json.JSONDecodeError, KeyError, ValueError):
                # If state is corrupted, start fresh
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                self.last_failure_time = None
        else:
            # No persisted state, start fresh
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
