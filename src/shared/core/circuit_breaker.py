"""Unified circuit breaker for LLM resilience and safety gates.

States: CLOSED (normal) -> OPEN (fast-fail) -> HALF_OPEN (testing recovery).
"""
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
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

from src.shared.constants.retries import (
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_RESET_TIMEOUT,
)

# Helper functions extracted to reduce class method count
from src.shared.core._circuit_breaker_helpers import (
    fire_callbacks as _fire_callbacks_helper,
)
from src.shared.core._circuit_breaker_helpers import (
    load_state as _load_state_helper,
)
from src.shared.core._circuit_breaker_helpers import (
    on_call_failure as _on_call_failure_helper,
)
from src.shared.core._circuit_breaker_helpers import (
    on_call_success as _on_call_success_helper,
)
from src.shared.core._circuit_breaker_helpers import (
    reserve_execution as _reserve_execution_helper,
)
from src.shared.core._circuit_breaker_helpers import (
    save_state as _save_state_helper,
)
from src.shared.core._circuit_breaker_helpers import (
    time_until_retry as _time_until_retry_helper,
)
from src.shared.core.constants import (
    MAX_CIRCUIT_BREAKER_NAME_LENGTH,
    MAX_FAILURE_THRESHOLD,
    MAX_SUCCESS_THRESHOLD,
    MAX_TIMEOUT_SECONDS,
    MIN_FAILURE_THRESHOLD,
    MIN_SUCCESS_THRESHOLD,
    MIN_TIMEOUT_SECONDS,
)
from src.shared.utils.exceptions import FrameworkException


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
    failure_threshold: int = CIRCUIT_BREAKER_FAILURE_THRESHOLD
    success_threshold: int = 2
    timeout: int = CIRCUIT_BREAKER_RESET_TIMEOUT  # seconds before trying half-open


class CircuitBreakerError(FrameworkException):
    """Raised when circuit breaker is open (LLM module interface)."""
    pass


# Backward-compatible alias used by safety module
CircuitBreakerOpen = CircuitBreakerError


@dataclass
class CircuitBreakerMetrics:
    """Metrics for circuit breaker monitoring."""
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
        lft = self.last_failure_time.isoformat() if self.last_failure_time else None
        lsct = self.last_state_change_time.isoformat() if self.last_state_change_time else None
        return {"total_calls": self.total_calls, "successful_calls": self.successful_calls,
                "failed_calls": self.failed_calls, "rejected_calls": self.rejected_calls,
                "state_changes": self.state_changes, "success_rate": self.success_rate(),
                "failure_rate": self.failure_rate(), "last_failure_time": lft,
                "last_state_change_time": lsct}


def _apply_loaded_state(breaker: "CircuitBreaker", loaded: dict) -> None:
    """Apply loaded state from storage to a CircuitBreaker instance."""
    breaker._state = loaded["state"]
    breaker._failure_count = loaded["failure_count"]
    breaker._success_count = loaded["success_count"]
    breaker._last_failure_time = loaded["last_failure_time"]
    breaker._opened_at = loaded["opened_at"]
    if loaded["config"] is not None:
        breaker.config = loaded["config"]


def _validate_name(name: str) -> None:
    """Validate circuit breaker name."""
    if not isinstance(name, str):
        raise ValueError(f"name must be a string, got {type(name).__name__}")
    if not name or len(name) > MAX_CIRCUIT_BREAKER_NAME_LENGTH:
        raise ValueError(f"name must be 1-100 characters, got {len(name)}")


def _build_config(
    config: Optional["CircuitBreakerConfig"],
    failure_threshold: Optional[int],
    timeout_seconds: Optional[int],
    success_threshold: Optional[int],
    name: str,
) -> "CircuitBreakerConfig":
    """Build config from explicit config object or individual params."""
    individual_params = [failure_threshold, timeout_seconds, success_threshold]
    if config is not None and any(p is not None for p in individual_params):
        logger.warning(
            "CircuitBreaker(%s): both config and individual parameters supplied; "
            "config takes precedence",
            name,
        )

    if config is not None:
        return config

    ft = failure_threshold if failure_threshold is not None else CIRCUIT_BREAKER_FAILURE_THRESHOLD
    ts = timeout_seconds if timeout_seconds is not None else CIRCUIT_BREAKER_RESET_TIMEOUT
    st = success_threshold if success_threshold is not None else 2

    if not isinstance(ft, int) or ft < MIN_FAILURE_THRESHOLD or ft > MAX_FAILURE_THRESHOLD:
        raise ValueError(
            f"failure_threshold must be int {MIN_FAILURE_THRESHOLD}-{MAX_FAILURE_THRESHOLD}, got {ft}"
        )
    if not isinstance(ts, int) or ts < MIN_TIMEOUT_SECONDS or ts > MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be int {MIN_TIMEOUT_SECONDS}-{MAX_TIMEOUT_SECONDS}, got {ts}"
        )
    if not isinstance(st, int) or st < MIN_SUCCESS_THRESHOLD or st > MAX_SUCCESS_THRESHOLD:
        raise ValueError(
            f"success_threshold must be int {MIN_SUCCESS_THRESHOLD}-{MAX_SUCCESS_THRESHOLD}, got {st}"
        )
    return CircuitBreakerConfig(failure_threshold=ft, success_threshold=st, timeout=ts)


def _init_state_from_storage(
    storage: Optional["StateStorage"],
    name: str,
) -> dict:
    """Initialize circuit breaker state from storage or defaults."""
    if storage:
        return _load_state_helper(storage, name)
    return {
        "state": CircuitState.CLOSED,
        "failure_count": 0,
        "success_count": 0,
        "last_failure_time": None,
        "opened_at": None,
        "config": None,
    }


class CircuitBreaker:
    """Unified circuit breaker for resilience and safety.

    Usage: breaker.call(func) or 'with breaker(): ...'
    See _circuit_breaker_helpers.py for extracted internal logic.
    """

    # Class-level attribute declarations for type checker
    _state: CircuitState
    _failure_count: int
    _success_count: int
    _last_failure_time: Optional[float]
    _opened_at: Optional[datetime]

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        storage: Optional[StateStorage] = None,
        failure_threshold: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        success_threshold: Optional[int] = None,
        observability_callback: Optional[Callable] = None,
    ):
        _validate_name(name)
        self.name = name

        self.config = _build_config(config, failure_threshold, timeout_seconds, success_threshold, name)

        self.failure_threshold = self.config.failure_threshold
        self.success_threshold = self.config.success_threshold
        self.timeout_seconds = self.config.timeout

        self.storage = storage
        self.lock = threading.Lock()
        self._half_open_semaphore = threading.Semaphore(1)

        self.metrics = CircuitBreakerMetrics()
        self._on_state_change_callbacks: List[
            Callable[[CircuitState, CircuitState], None]
        ] = []
        self._observability_callbacks: List[Callable] = (
            [observability_callback] if observability_callback is not None else []
        )

        loaded = _init_state_from_storage(self.storage, self.name)
        self._state = loaded["state"]
        self._failure_count = loaded["failure_count"]
        self._success_count = loaded["success_count"]
        self._last_failure_time: Optional[float] = loaded["last_failure_time"]
        self._opened_at: Optional[datetime] = loaded["opened_at"]
        if loaded["config"] is not None:
            self.config = loaded["config"]

        self._on_success = lambda reserved_state=None: _on_call_success_helper(self, reserved_state)
        self._on_failure = lambda error, reserved_state=None: _on_call_failure_helper(self, error, reserved_state)
        self._reserve_execution = lambda: _reserve_execution_helper(self)
        self.can_execute = lambda: self.state != CircuitState.OPEN
        self.get_metrics = lambda: self.metrics
        self._save_state = lambda: _save_state_helper(
            self.storage, self.name, self._state,
            self._failure_count, self._success_count,
            self._last_failure_time, self.config,
        )
        self._load_state = lambda: _apply_loaded_state(self, _load_state_helper(self.storage, self.name))

    @property
    def state(self) -> CircuitState:
        """Get current circuit breaker state, checking for auto-transitions."""
        with self.lock:
            # Inline _check_state_transition: OPEN -> HALF_OPEN if timeout elapsed
            # Uses local time module so tests can mock src.shared.core.circuit_breaker.time
            pending = None
            if self._state == CircuitState.OPEN:
                if self._last_failure_time is None or (time.time() - self._last_failure_time) >= self.config.timeout:
                    pending = self._transition_to(CircuitState.HALF_OPEN)
                    self._success_count = 0
                    if self.storage:
                        _save_state_helper(
                            self.storage, self.name, self._state,
                            self._failure_count, self._success_count,
                            self._last_failure_time, self.config,
                        )
            current = self._state
        _fire_callbacks_helper(pending, breaker=self)
        return current

    @state.setter
    def state(self, value: CircuitState) -> None:
        """Set state directly (used by persistence loader)."""
        self._state = value

    @property
    def failure_count(self) -> int:
        """Number of consecutive failures."""
        return self._failure_count

    @failure_count.setter
    def failure_count(self, value: int) -> None:
        """Number of consecutive failures."""
        self._failure_count = value

    @property
    def success_count(self) -> int:
        """Number of consecutive successes."""
        return self._success_count

    @success_count.setter
    def success_count(self, value: int) -> None:
        """Number of consecutive successes."""
        self._success_count = value

    @property
    def last_failure_time(self) -> Optional[float]:
        """Timestamp of most recent failure."""
        return self._last_failure_time

    @last_failure_time.setter
    def last_failure_time(self, value: Optional[float]) -> None:
        """Timestamp of most recent failure."""
        self._last_failure_time = value

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
                _save_state_helper(
                    self.storage, self.name, self._state,
                    self._failure_count, self._success_count,
                    self._last_failure_time, self.config,
                )
        _fire_callbacks_helper(pending, breaker=self)

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
                _save_state_helper(
                    self.storage, self.name, self._state,
                    self._failure_count, self._success_count,
                    self._last_failure_time, self.config,
                )
        _fire_callbacks_helper(pending, breaker=self)

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function through circuit breaker. Raises CircuitBreakerError if open."""
        reserved_state = _reserve_execution_helper(self)

        if reserved_state is None:
            with self.lock:
                self.metrics.rejected_calls += 1
            raise CircuitBreakerError(
                f"Circuit breaker OPEN for {self.name}. "
                f"Retry after {_time_until_retry_helper(self._last_failure_time, self.config.timeout):.0f}s"
            )

        try:
            result = func(*args, **kwargs)
            _on_call_success_helper(self, reserved_state)
            return result
        except Exception as e:
            _on_call_failure_helper(self, e, reserved_state)
            raise

    async def async_call(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Execute async function through circuit breaker. Raises CircuitBreakerError if open."""
        reserved_state = _reserve_execution_helper(self)

        if reserved_state is None:
            with self.lock:
                self.metrics.rejected_calls += 1
            raise CircuitBreakerError(
                f"Circuit breaker OPEN for {self.name}. "
                f"Retry after {_time_until_retry_helper(self._last_failure_time, self.config.timeout):.0f}s"
            )

        try:
            result = await func(*args, **kwargs)
            _on_call_success_helper(self, reserved_state)
            return result
        except Exception as e:
            _on_call_failure_helper(self, e, reserved_state)
            raise

    @contextmanager
    def __call__(self) -> Generator[None, None, None]:
        """Context manager for circuit breaker protection."""
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

    def on_state_change(
        self,
        callback: Callable[[CircuitState, CircuitState], None],
    ) -> None:
        """Register callback for state changes."""
        self._on_state_change_callbacks.append(callback)

    def add_observability_callback(self, callback: Callable) -> None:
        """Register an observability callback for resilience tracking.

        Args:
            callback: Called with CircuitBreakerEventData on state transitions
        """
        self._observability_callbacks.append(callback)

    def reset(self) -> None:
        """Reset circuit breaker to CLOSED state."""
        with self.lock:
            pending = self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._opened_at = None
            if self.storage:
                _save_state_helper(
                    self.storage, self.name, self._state,
                    self._failure_count, self._success_count,
                    self._last_failure_time, self.config,
                )
        _fire_callbacks_helper(pending, breaker=self)

    def force_open(self) -> None:
        """Manually force circuit breaker to OPEN state."""
        with self.lock:
            pending = self._transition_to(CircuitState.OPEN)
            self._opened_at = datetime.now(UTC)
            self._last_failure_time = time.time()
        _fire_callbacks_helper(pending, breaker=self)

    def _transition_to(self, new_state: CircuitState) -> Optional[tuple]:
        """Transition to new state. Must hold self.lock. Returns callback info or None."""
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

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"CircuitBreaker("
            f"name='{self.name}', "
            f"state={self.state.value}, "
            f"failures={self._failure_count}/{self.config.failure_threshold})"
        )
