"""
Unified circuit breaker pattern for resilience and safety.

Merges features from src/llm/circuit_breaker.py (LLM resilience) and
src/safety/circuit_breaker.py (safety gates) into a single implementation.

Features from LLM module:
- call() / async_call() with state reservation pattern
- StateStorage protocol for state persistence
- Thundering herd prevention via semaphore in HALF_OPEN
- Error classification (_should_count_failure)
- CircuitBreakerConfig dataclass

Features from safety module:
- Context manager __call__() for 'with breaker:' usage
- CircuitBreakerMetrics with success/failure rates
- State change callbacks
- Parameter validation with bounds checking

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Too many failures, fast-fail without calling provider
- HALF_OPEN: Testing if service recovered, allow limited requests
"""
import json
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Protocol,
    TypeVar,
)

T = TypeVar('T')
logger = logging.getLogger(__name__)

# Import FrameworkException for proper exception hierarchy
from src.utils.exceptions import FrameworkException

# Cache exception class imports at module level to avoid per-call overhead (P-17)
try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore[assignment]

try:
    from src.utils.exceptions import (
        LLMAuthenticationError as _LLMAuthenticationError,
        LLMError as _LLMError,
        LLMRateLimitError as _LLMRateLimitError,
        LLMTimeoutError as _LLMTimeoutError,
    )
except ImportError:
    _LLMError = None  # type: ignore[assignment,misc]
    _LLMTimeoutError = None  # type: ignore[assignment,misc]
    _LLMRateLimitError = None  # type: ignore[assignment,misc]
    _LLMAuthenticationError = None  # type: ignore[assignment,misc]


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
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# Backward-compatible alias used by safety module
CircuitBreakerState = CircuitState


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: int = 60  # seconds before trying half-open


class CircuitBreakerError(FrameworkException):
    """Raised when circuit breaker is open (LLM module interface)."""
    pass


# Backward-compatible alias used by safety module
CircuitBreakerOpen = CircuitBreakerError


@dataclass
class CircuitBreakerMetrics:
    """Metrics for circuit breaker monitoring.

    Attributes:
        total_calls: Total number of calls attempted
        successful_calls: Number of successful calls
        failed_calls: Number of failed calls
        rejected_calls: Number of calls rejected (breaker open)
        state_changes: Number of state transitions
        last_failure_time: Timestamp of last failure
        last_state_change_time: Timestamp of last state change
    """
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_changes: int = 0
    last_failure_time: Optional[datetime] = None
    last_state_change_time: Optional[datetime] = None

    def success_rate(self) -> float:
        """Calculate success rate (0.0 to 1.0)."""
        if self.total_calls == 0:
            return 1.0
        return self.successful_calls / self.total_calls

    def failure_rate(self) -> float:
        """Calculate failure rate (0.0 to 1.0)."""
        return 1.0 - self.success_rate()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "rejected_calls": self.rejected_calls,
            "state_changes": self.state_changes,
            "success_rate": self.success_rate(),
            "failure_rate": self.failure_rate(),
            "last_failure_time": (
                self.last_failure_time.isoformat()
                if self.last_failure_time else None
            ),
            "last_state_change_time": (
                self.last_state_change_time.isoformat()
                if self.last_state_change_time else None
            ),
        }


class CircuitBreaker:
    """Unified circuit breaker for resilience and safety.

    Supports two usage patterns:

    1. LLM-style call/async_call (with state reservation, thundering herd
       prevention, error filtering, state persistence):

        >>> breaker = CircuitBreaker("ollama", config=CircuitBreakerConfig())
        >>> result = breaker.call(api_request, prompt="Hello")

    2. Safety-style context manager (with metrics, callbacks):

        >>> breaker = CircuitBreaker("database_calls", failure_threshold=5)
        >>> with breaker():
        ...     execute_query()

    Args:
        name: Circuit breaker name (1-100 characters)
        failure_threshold: Failures before opening (1-1000)
        timeout_seconds: Seconds before attempting recovery (1-86400)
        success_threshold: Successes needed to close from half-open (1-100)
        config: CircuitBreakerConfig (overrides individual params if provided)
        storage: Optional StateStorage backend for state persistence
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        storage: Optional[StateStorage] = None,
        failure_threshold: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        success_threshold: Optional[int] = None,
    ):
        # Validate name
        if not isinstance(name, str):
            raise ValueError(
                f"name must be a string, got {type(name).__name__}"
            )
        if not name or len(name) > 100:
            raise ValueError(
                f"name must be 1-100 characters, got {len(name)}"
            )
        self.name = name

        # Warn on config+params conflict (API-19)
        individual_params = [failure_threshold, timeout_seconds, success_threshold]
        if config is not None and any(p is not None for p in individual_params):
            logger.warning(
                "CircuitBreaker(%s): both config and individual parameters supplied; "
                "config takes precedence",
                name,
            )

        # Config from explicit config object OR individual params
        if config is not None:
            self.config = config
        else:
            # Apply defaults for any parameters not explicitly provided
            ft = failure_threshold if failure_threshold is not None else 5
            ts = timeout_seconds if timeout_seconds is not None else 60
            st = success_threshold if success_threshold is not None else 2

            # Validate individual params
            if not isinstance(ft, int) or ft < 1 or ft > 1000:
                raise ValueError(
                    f"failure_threshold must be int 1-1000, got {ft}"
                )
            if not isinstance(ts, int) or ts < 1 or ts > 86400:
                raise ValueError(
                    f"timeout_seconds must be int 1-86400, got {ts}"
                )
            if not isinstance(st, int) or st < 1 or st > 100:
                raise ValueError(
                    f"success_threshold must be int 1-100, got {st}"
                )
            self.config = CircuitBreakerConfig(
                failure_threshold=ft,
                success_threshold=st,
                timeout=ts,
            )

        # Backward-compatible attribute aliases
        self.failure_threshold = self.config.failure_threshold
        self.success_threshold = self.config.success_threshold
        self.timeout_seconds = self.config.timeout

        # Storage for state persistence
        self.storage = storage
        self.lock = threading.Lock()

        # Semaphore to prevent thundering herd in HALF_OPEN state
        self._half_open_semaphore = threading.Semaphore(1)

        # Metrics (safety module feature)
        self.metrics = CircuitBreakerMetrics()
        self._on_state_change_callbacks: List[
            Callable[[CircuitState, CircuitState], None]
        ] = []

        # Load persisted state or initialize fresh
        if self.storage:
            self._load_state()
        else:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time: Optional[float] = None
            self._opened_at: Optional[datetime] = None

    # -- Properties (safety module interface) --

    @property
    def state(self) -> CircuitState:
        """Get current circuit breaker state, checking for auto-transitions."""
        with self.lock:
            pending = self._check_state_transition()
            current = self._state
        self._fire_callbacks(pending)
        return current

    @state.setter
    def state(self, value: CircuitState) -> None:
        """Set state directly (used by persistence loader)."""
        self._state = value

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @failure_count.setter
    def failure_count(self, value: int) -> None:
        self._failure_count = value

    @property
    def success_count(self) -> int:
        return self._success_count

    @success_count.setter
    def success_count(self, value: int) -> None:
        self._success_count = value

    @property
    def last_failure_time(self) -> Optional[float]:
        return self._last_failure_time

    @last_failure_time.setter
    def last_failure_time(self, value: Optional[float]) -> None:
        self._last_failure_time = value

    # -- Safety module interface: can_execute, record_success, record_failure --

    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        """Record successful execution (safety module interface)."""
        pending = None
        with self.lock:
            self.metrics.total_calls += 1
            self.metrics.successful_calls += 1
            self._failure_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    pending = self._transition_to(CircuitState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0

            if self.storage:
                self._save_state()
        self._fire_callbacks(pending)

    def record_failure(self, error: Optional[Exception] = None) -> None:
        """Record failed execution (safety module interface)."""
        pending = None
        with self.lock:
            self.metrics.total_calls += 1
            self.metrics.failed_calls += 1
            self.metrics.last_failure_time = datetime.now(UTC)

            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    pending = self._transition_to(CircuitState.OPEN)
                    self._opened_at = datetime.now(UTC)
                    self._failure_count = 0
            elif self._state == CircuitState.HALF_OPEN:
                pending = self._transition_to(CircuitState.OPEN)
                self._opened_at = datetime.now(UTC)
                self._failure_count = 0
                self._success_count = 0

            if self.storage:
                self._save_state()
        self._fire_callbacks(pending)

    # -- LLM module interface: call, async_call --

    def is_open(self) -> bool:
        """Check if circuit breaker is currently OPEN."""
        with self.lock:
            if self._state == CircuitState.OPEN:
                if self._last_failure_time is not None:
                    elapsed = time.time() - self._last_failure_time
                    if elapsed >= self.config.timeout:
                        return False
                return True
            return False

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function through circuit breaker with state reservation.

        Uses atomic state reservation to prevent race conditions.

        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from func

        Raises:
            CircuitBreakerError: If circuit is open
        """
        reserved_state = self._reserve_execution()

        if reserved_state is None:
            with self.lock:
                self.metrics.rejected_calls += 1
            raise CircuitBreakerError(
                f"Circuit breaker OPEN for {self.name}. "
                f"Retry after {self._time_until_retry():.0f}s"
            )

        try:
            result = func(*args, **kwargs)
            self._on_call_success(reserved_state)
            return result
        except Exception as e:
            self._on_call_failure(e, reserved_state)
            raise

    async def async_call(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Execute async function through circuit breaker.

        Same state management as call(), but awaits the async function.
        """
        reserved_state = self._reserve_execution()

        if reserved_state is None:
            with self.lock:
                self.metrics.rejected_calls += 1
            raise CircuitBreakerError(
                f"Circuit breaker OPEN for {self.name}. "
                f"Retry after {self._time_until_retry():.0f}s"
            )

        try:
            result = await func(*args, **kwargs)
            self._on_call_success(reserved_state)
            return result
        except Exception as e:
            self._on_call_failure(e, reserved_state)
            raise

    # -- Context manager interface (safety module) --

    @contextmanager
    def __call__(self) -> Generator[None, None, None]:
        """Context manager for circuit breaker protection.

        Raises:
            CircuitBreakerError: If circuit breaker is open
        """
        if not self.can_execute():
            with self.lock:
                self.metrics.rejected_calls += 1
            raise CircuitBreakerError(
                f"Circuit breaker '{self.name}' is {self.state.value}"
            )

        try:
            yield
            self.record_success()
        except Exception as e:
            self.record_failure(e)
            raise

    # -- Callbacks (safety module) --

    def on_state_change(
        self,
        callback: Callable[[CircuitState, CircuitState], None],
    ) -> None:
        """Register callback for state changes.

        Args:
            callback: Function(old_state, new_state) called on transition
        """
        self._on_state_change_callbacks.append(callback)

    def get_metrics(self) -> CircuitBreakerMetrics:
        """Get current metrics."""
        return self.metrics

    # -- Control methods --

    def reset(self) -> None:
        """Reset circuit breaker to CLOSED state."""
        with self.lock:
            pending = self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._opened_at = None
            if self.storage:
                self._save_state()
        self._fire_callbacks(pending)

    def force_open(self) -> None:
        """Manually force circuit breaker to OPEN state."""
        with self.lock:
            pending = self._transition_to(CircuitState.OPEN)
            self._opened_at = datetime.now(UTC)
            self._last_failure_time = time.time()
        self._fire_callbacks(pending)

    # -- Internal: state transitions --

    def _check_state_transition(self):
        """Check if OPEN -> HALF_OPEN transition should occur.

        Must be called while holding self.lock.
        Returns callback info tuple or None.
        """
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                result = self._transition_to(CircuitState.HALF_OPEN)
                self._success_count = 0
                if self.storage:
                    self._save_state()
                return result
        return None

    def _transition_to(self, new_state: CircuitState):
        """Transition to new state. Must be called while holding self.lock.

        Returns (old_state, new_state, callbacks) for deferred execution,
        or None if no transition occurred.
        """
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self.metrics.state_changes += 1
            self.metrics.last_state_change_time = datetime.now(UTC)
            return (
                old_state,
                new_state,
                self._on_state_change_callbacks.copy(),
            )
        return None

    @staticmethod
    def _fire_callbacks(transition_info) -> None:
        """Execute state change callbacks outside the lock."""
        if transition_info is None:
            return
        old_state, new_state, callbacks = transition_info
        for callback in callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                logger.warning(
                    "Circuit breaker state change callback failed: %s", e
                )

    # -- Internal: LLM call pattern --

    def _reserve_execution(self) -> Optional[CircuitState]:
        """Atomically check if execution is allowed and reserve permission.

        For HALF_OPEN, enforces single concurrent test execution via semaphore.

        Returns:
            CircuitState at time of reservation if allowed, None if blocked
        """
        with self.lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    if self.storage:
                        self._save_state()
                else:
                    return None

            current_state = self._state

        if current_state == CircuitState.HALF_OPEN:
            if not self._half_open_semaphore.acquire(blocking=False):
                with self.lock:
                    self.metrics.rejected_calls += 1
                raise CircuitBreakerError(
                    f"Circuit breaker for {self.name} is testing recovery. "
                    f"Retry in 1-2 seconds."
                )

        return current_state

    def _on_call_success(
        self, reserved_state: Optional[CircuitState] = None
    ) -> None:
        """Handle successful call() execution."""
        try:
            with self.lock:
                self.metrics.total_calls += 1
                self.metrics.successful_calls += 1
                self._failure_count = 0

                if self._state == CircuitState.HALF_OPEN:
                    self._success_count += 1
                    if self._success_count >= self.config.success_threshold:
                        self._state = CircuitState.CLOSED
                        self._success_count = 0
                elif (
                    reserved_state == CircuitState.HALF_OPEN
                    and self._state == CircuitState.OPEN
                ):
                    pass  # Re-opened by another thread, ignore our success

                if self.storage:
                    self._save_state()
        finally:
            if reserved_state == CircuitState.HALF_OPEN:
                self._half_open_semaphore.release()

    def _on_call_failure(
        self,
        error: Exception,
        reserved_state: Optional[CircuitState] = None,
    ) -> None:
        """Handle failed call() execution."""
        if not self._should_count_failure(error):
            if reserved_state == CircuitState.HALF_OPEN:
                self._half_open_semaphore.release()
            return

        try:
            with self.lock:
                self.metrics.total_calls += 1
                self.metrics.failed_calls += 1
                self.metrics.last_failure_time = datetime.now(UTC)

                self._failure_count += 1
                self._last_failure_time = time.time()

                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.OPEN
                elif (
                    reserved_state == CircuitState.HALF_OPEN
                    and self._state != CircuitState.HALF_OPEN
                ):
                    self._state = CircuitState.OPEN
                elif self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN

                if self.storage:
                    self._save_state()
        finally:
            if reserved_state == CircuitState.HALF_OPEN:
                self._half_open_semaphore.release()

    def _should_count_failure(self, error: Exception) -> bool:
        """Determine if error should count toward circuit breaker.

        Network/server errors count (transient). Client errors don't.
        Uses module-level cached imports for performance (P-17).
        """
        if _httpx is None:
            return True  # If httpx not available, count all errors

        if isinstance(error, (_httpx.ConnectError, _httpx.TimeoutException)):
            return True
        if _LLMTimeoutError and isinstance(error, _LLMTimeoutError):
            return True
        if _LLMRateLimitError and isinstance(error, _LLMRateLimitError):
            return True
        if _LLMAuthenticationError and isinstance(error, _LLMAuthenticationError):
            return False
        if _LLMError and isinstance(error, _LLMError):
            return True
        if isinstance(error, _httpx.HTTPStatusError):
            status = error.response.status_code
            return status >= 500 or status == 429

        return False

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try half-open."""
        if self._last_failure_time is None:
            return True
        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.config.timeout

    def _time_until_retry(self) -> float:
        """Seconds until circuit will try half-open."""
        if self._last_failure_time is None:
            return 0
        elapsed = time.time() - self._last_failure_time
        return max(0, self.config.timeout - elapsed)

    # -- State persistence --

    def _get_state_key(self) -> str:
        """Get storage key for this circuit breaker."""
        return f"circuit_breaker:{self.name}:state"

    def _save_state(self) -> None:
        """Save circuit breaker state to storage."""
        if not self.storage:
            return

        state_dict = {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "config": asdict(self.config),
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
                self._state = CircuitState(state_dict["state"])
                self._failure_count = state_dict["failure_count"]
                self._success_count = state_dict["success_count"]
                self._last_failure_time = state_dict.get("last_failure_time")
                self._opened_at = None
                if "config" in state_dict:
                    saved_config = state_dict["config"]
                    self.config = CircuitBreakerConfig(**saved_config)
            except (json.JSONDecodeError, KeyError, ValueError):
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                self._last_failure_time = None
                self._opened_at = None
        else:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._opened_at = None

    # Backward-compatible aliases for LLM module tests
    def _on_success(
        self, reserved_state: Optional[CircuitState] = None
    ) -> None:
        """Alias for _on_call_success (backward compat)."""
        self._on_call_success(reserved_state)

    def _on_failure(
        self,
        error: Exception,
        reserved_state: Optional[CircuitState] = None,
    ) -> None:
        """Alias for _on_call_failure (backward compat)."""
        self._on_call_failure(error, reserved_state)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"CircuitBreaker("
            f"name='{self.name}', "
            f"state={self.state.value}, "
            f"failures={self._failure_count}/{self.config.failure_threshold})"
        )
