"""Helper functions extracted from CircuitBreaker to reduce method count.

These are internal implementation details - use CircuitBreaker's public API.
"""
import json
import logging
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# HTTP status codes
HTTP_STATUS_SERVER_ERROR_MIN = 500
HTTP_STATUS_TOO_MANY_REQUESTS = 429

# Cache exception class imports at module level (P-17)
try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore[assignment]

try:
    from temper_ai.shared.utils.exceptions import (
        LLMAuthenticationError as _LLMAuthenticationError,
    )
    from temper_ai.shared.utils.exceptions import (
        LLMError as _LLMError,
    )
    from temper_ai.shared.utils.exceptions import (
        LLMRateLimitError as _LLMRateLimitError,
    )
    from temper_ai.shared.utils.exceptions import (
        LLMTimeoutError as _LLMTimeoutError,
    )
except ImportError:
    _LLMError = None  # type: ignore[assignment,misc]
    _LLMTimeoutError = None  # type: ignore[assignment,misc]
    _LLMRateLimitError = None  # type: ignore[assignment,misc]
    _LLMAuthenticationError = None  # type: ignore[assignment,misc]


def should_count_failure(error: Exception) -> bool:
    """Determine if error should count toward circuit breaker.

    Network/server errors count (transient). Client errors don't.
    Uses module-level cached imports for performance (P-17).

    Args:
        error: The exception that occurred

    Returns:
        True if the error should count as a failure
    """
    if _httpx is None:
        return True  # type: ignore[unreachable]

    if isinstance(error, (_httpx.ConnectError, _httpx.TimeoutException)):
        return True
    if _LLMTimeoutError is not None and isinstance(error, _LLMTimeoutError):
        return True
    if _LLMRateLimitError is not None and isinstance(error, _LLMRateLimitError):
        return True
    if _LLMAuthenticationError is not None and isinstance(error, _LLMAuthenticationError):
        return False
    if _LLMError is not None and isinstance(error, _LLMError):
        return True
    if isinstance(error, _httpx.HTTPStatusError):
        status = error.response.status_code
        return status >= HTTP_STATUS_SERVER_ERROR_MIN or status == HTTP_STATUS_TOO_MANY_REQUESTS

    return False


def should_attempt_reset(last_failure_time: Optional[float], timeout: int) -> bool:
    """Check if enough time has passed to try half-open.

    Args:
        last_failure_time: Timestamp of last failure (time.time())
        timeout: Timeout in seconds before attempting reset

    Returns:
        True if enough time has passed
    """
    if last_failure_time is None:
        return True
    elapsed = time.time() - last_failure_time
    return elapsed >= timeout


def time_until_retry(last_failure_time: Optional[float], timeout: int) -> float:
    """Seconds until circuit will try half-open.

    Args:
        last_failure_time: Timestamp of last failure
        timeout: Timeout in seconds

    Returns:
        Seconds remaining
    """
    if last_failure_time is None:
        return 0
    elapsed = time.time() - last_failure_time
    return max(0, timeout - elapsed)


def get_state_key(name: str) -> str:
    """Get storage key for a circuit breaker.

    Args:
        name: Circuit breaker name

    Returns:
        Storage key string
    """
    return f"circuit_breaker:{name}:state"


def save_state(storage: Any, name: str, state: Any, failure_count: int,
               success_count: int, last_failure_time: Optional[float],
               config: Any) -> None:
    """Save circuit breaker state to storage.

    Args:
        storage: StateStorage backend
        name: Circuit breaker name
        state: Current CircuitState
        failure_count: Current failure count
        success_count: Current success count
        last_failure_time: Last failure timestamp
        config: CircuitBreakerConfig
    """
    if not storage:
        return

    state_dict = {
        "state": state.value,
        "failure_count": failure_count,
        "success_count": success_count,
        "last_failure_time": last_failure_time,
        "config": asdict(config),
    }

    key = get_state_key(name)
    storage.set(key, json.dumps(state_dict))


def load_state(storage: Any, name: str) -> dict:
    """Load circuit breaker state from storage.

    Args:
        storage: StateStorage backend
        name: Circuit breaker name

    Returns:
        Dict with state, failure_count, success_count, last_failure_time, config
        or default values if not found/corrupt
    """
    from temper_ai.shared.core.circuit_breaker import CircuitBreakerConfig, CircuitState

    defaults = {
        "state": CircuitState.CLOSED,
        "failure_count": 0,
        "success_count": 0,
        "last_failure_time": None,
        "opened_at": None,
        "config": None,
    }

    if not storage:
        return defaults

    key = get_state_key(name)
    data = storage.get(key)

    if data:
        try:
            state_dict = json.loads(data)
            result = {
                "state": CircuitState(state_dict["state"]),
                "failure_count": state_dict["failure_count"],
                "success_count": state_dict["success_count"],
                "last_failure_time": state_dict.get("last_failure_time"),
                "opened_at": None,
            }
            if "config" in state_dict:
                result["config"] = CircuitBreakerConfig(**state_dict["config"])
            else:
                result["config"] = None
            return result
        except (json.JSONDecodeError, KeyError, ValueError):
            return defaults

    return defaults


def fire_callbacks(
    transition_info: Optional[tuple],
    breaker: Optional[Any] = None,
) -> None:
    """Execute state change callbacks outside the lock.

    Args:
        transition_info: Tuple of (old_state, new_state, callbacks) or None
        breaker: Optional CircuitBreaker instance for observability callbacks
    """
    if transition_info is None:
        return
    old_state, new_state, callbacks = transition_info

    # Fire state-change callbacks
    for callback in callbacks:
        try:
            callback(old_state, new_state)
        except Exception as e:
            logger.warning(
                "Circuit breaker state change callback failed: %s", e
            )

    # Fire observability callbacks
    _fire_observability_callbacks(breaker, old_state, new_state)


def _log_state_transition(breaker: Any, old_state: Any, new_state: Any) -> None:
    """Log a structured circuit breaker state transition.

    Args:
        breaker: CircuitBreaker instance
        old_state: Previous CircuitState
        new_state: New CircuitState
    """
    logger.info(
        "Circuit breaker %s transitioned %s -> %s (failures=%d)",
        breaker.name,
        old_state.value,
        new_state.value,
        breaker.failure_count,
        extra={
            "breaker_name": breaker.name,
            "old_state": old_state.value,
            "new_state": new_state.value,
            "failure_count": breaker.failure_count,
            "success_count": breaker.success_count,
        },
    )


def _fire_observability_callbacks(
    breaker: Optional[Any],
    old_state: Any,
    new_state: Any,
) -> None:
    """Fire observability callbacks for circuit breaker state transitions.

    Args:
        breaker: CircuitBreaker instance (may be None)
        old_state: Previous CircuitState
        new_state: New CircuitState
    """
    if breaker is None:
        return
    obs_callbacks = getattr(breaker, "_observability_callbacks", None)
    if not obs_callbacks:
        return

    from temper_ai.observability.resilience_events import (
        CircuitBreakerEventData,
        emit_circuit_breaker_event,
    )

    event_data = CircuitBreakerEventData(
        breaker_name=breaker.name,
        old_state=old_state.value,
        new_state=new_state.value,
        failure_count=breaker.failure_count,
        success_count=breaker.success_count,
    )

    for cb in obs_callbacks:
        emit_circuit_breaker_event(callback=cb, event_data=event_data)


def on_call_success(breaker: Any, reserved_state: Optional[Any] = None) -> None:
    """Handle successful call() execution.

    Args:
        breaker: CircuitBreaker instance
        reserved_state: State at time of reservation
    """
    from temper_ai.shared.core.circuit_breaker import CircuitState

    old_state = None
    new_state = None
    try:
        with breaker.lock:
            breaker.metrics.total_calls += 1
            breaker.metrics.successful_calls += 1
            breaker.failure_count = 0

            if breaker._state == CircuitState.HALF_OPEN:
                breaker.success_count += 1
                if breaker.success_count >= breaker.config.success_threshold:
                    old_state = CircuitState.HALF_OPEN
                    breaker._state = CircuitState.CLOSED
                    new_state = CircuitState.CLOSED
                    breaker.success_count = 0

            if breaker.storage:
                save_state(
                    breaker.storage, breaker.name, breaker._state,
                    breaker.failure_count, breaker.success_count,
                    breaker.last_failure_time, breaker.config,
                )
    finally:
        if reserved_state == CircuitState.HALF_OPEN:
            breaker._half_open_semaphore.release()

    if old_state is not None and new_state is not None:
        _log_state_transition(breaker, old_state, new_state)
        _fire_observability_callbacks(breaker, old_state, new_state)


def _should_open_on_failure(breaker: Any, reserved_state: Optional[Any]) -> bool:
    """Determine whether a failure should trip the breaker to OPEN.

    Args:
        breaker: CircuitBreaker instance (lock must be held by caller).
        reserved_state: State at time of reservation.

    Returns:
        True if the breaker should transition to OPEN.
    """
    from temper_ai.shared.core.circuit_breaker import CircuitState

    if breaker._state == CircuitState.HALF_OPEN:
        return True
    if reserved_state == CircuitState.HALF_OPEN and breaker._state != CircuitState.HALF_OPEN:
        return True
    if breaker.failure_count >= breaker.config.failure_threshold:
        return True
    return False


def on_call_failure(breaker: Any, error: Exception, reserved_state: Optional[Any] = None) -> None:
    """Handle failed call() execution.

    Args:
        breaker: CircuitBreaker instance
        error: The exception that occurred
        reserved_state: State at time of reservation
    """
    from temper_ai.shared.core.circuit_breaker import CircuitState

    if not should_count_failure(error):
        if reserved_state == CircuitState.HALF_OPEN:
            breaker._half_open_semaphore.release()
        return

    old_state = None
    new_state = None
    try:
        with breaker.lock:
            breaker.metrics.total_calls += 1
            breaker.metrics.failed_calls += 1
            breaker.metrics.last_failure_time = datetime.now(UTC)

            breaker.failure_count += 1
            breaker._last_failure_time = time.time()

            prev_state = breaker._state

            if _should_open_on_failure(breaker, reserved_state):
                breaker._state = CircuitState.OPEN

            if breaker._state != prev_state:
                old_state = prev_state
                new_state = breaker._state

            if breaker.storage:
                save_state(
                    breaker.storage, breaker.name, breaker._state,
                    breaker.failure_count, breaker.success_count,
                    breaker.last_failure_time, breaker.config,
                )
    finally:
        if reserved_state == CircuitState.HALF_OPEN:
            breaker._half_open_semaphore.release()

    if old_state is not None and new_state is not None:
        _log_state_transition(breaker, old_state, new_state)
        _fire_observability_callbacks(breaker, old_state, new_state)


def reserve_execution(breaker: Any) -> Optional[Any]:
    """Atomically check if execution is allowed and reserve permission.

    For HALF_OPEN, enforces single concurrent test execution via semaphore.

    Args:
        breaker: CircuitBreaker instance

    Returns:
        CircuitState at time of reservation if allowed, None if blocked
    """
    from temper_ai.shared.core.circuit_breaker import CircuitBreakerError, CircuitState

    with breaker.lock:
        if breaker._state == CircuitState.OPEN:
            if should_attempt_reset(breaker.last_failure_time, breaker.config.timeout):
                breaker._state = CircuitState.HALF_OPEN
                breaker.success_count = 0
                if breaker.storage:
                    save_state(
                        breaker.storage, breaker.name, breaker._state,
                        breaker.failure_count, breaker.success_count,
                        breaker.last_failure_time, breaker.config,
                    )
            else:
                return None

        current_state = breaker._state

    if current_state == CircuitState.HALF_OPEN:
        if not breaker._half_open_semaphore.acquire(blocking=False):
            with breaker.lock:
                breaker.metrics.rejected_calls += 1
            raise CircuitBreakerError(
                f"Circuit breaker for {breaker.name} is testing recovery. "
                f"Retry in 1-2 seconds."
            )

    return current_state
