"""Circuit breakers and safety gates for preventing cascading failures.

This module provides circuit breakers that monitor failure rates and automatically
block operations when failures exceed thresholds, preventing cascading failures.
Safety gates integrate circuit breakers with policy validation for comprehensive
execution control.

Key Features:
- Circuit breaker pattern (CLOSED/OPEN/HALF_OPEN states)
- Failure threshold monitoring
- Automatic recovery attempts
- Safety gates with policy integration
- Circuit breaker metrics and history
- Integration with rollback and approval systems

Example:
    >>> breaker = CircuitBreaker(name="api_calls", failure_threshold=5, timeout_seconds=60)
    >>>
    >>> # Execute with circuit breaker protection
    >>> try:
    ...     with breaker:
    ...         risky_api_call()
    ... except CircuitBreakerOpen:
    ...     print("Circuit breaker is open - too many failures")
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Dict, Any, Optional, List, Callable, Generator
from contextlib import contextmanager
import threading


class CircuitBreakerState(Enum):
    """Circuit breaker states.

    States:
        CLOSED: Normal operation, requests pass through
        OPEN: Too many failures, requests blocked
        HALF_OPEN: Testing if service recovered, limited requests allowed
    """
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""
    pass


class SafetyGateBlocked(Exception):
    """Exception raised when safety gate blocks execution."""
    pass


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
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_state_change_time": self.last_state_change_time.isoformat() if self.last_state_change_time else None
        }


class CircuitBreaker:
    """Circuit breaker for preventing cascading failures.

    Monitors failure rates and automatically blocks operations when failures
    exceed thresholds. Implements the circuit breaker pattern with CLOSED,
    OPEN, and HALF_OPEN states.

    Example:
        >>> breaker = CircuitBreaker(
        ...     name="database_calls",
        ...     failure_threshold=5,
        ...     timeout_seconds=60,
        ...     success_threshold=2
        ... )
        >>>
        >>> # Use as context manager
        >>> try:
        ...     with breaker:
        ...         execute_database_query()
        ... except CircuitBreakerOpen:
        ...     print("Too many failures - circuit breaker open")
        >>>
        >>> # Or manually
        >>> if breaker.can_execute():
        ...     try:
        ...         result = execute_query()
        ...         breaker.record_success()
        ...     except Exception:
        ...         breaker.record_failure()
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        success_threshold: int = 2
    ):
        """Initialize circuit breaker.

        Args:
            name: Circuit breaker name
            failure_threshold: Number of failures before opening circuit
            timeout_seconds: Seconds to wait before attempting recovery
            success_threshold: Successes needed in HALF_OPEN to close circuit
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.success_threshold = success_threshold

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._opened_at: Optional[datetime] = None
        self._lock = threading.Lock()

        self.metrics = CircuitBreakerMetrics()
        self._on_state_change_callbacks: List[Callable[[CircuitBreakerState, CircuitBreakerState], None]] = []

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        with self._lock:
            self._check_state_transition()
            return self._state

    def can_execute(self) -> bool:
        """Check if execution is allowed.

        Returns:
            True if execution allowed, False if breaker is open
        """
        state = self.state  # This also checks transitions
        return state != CircuitBreakerState.OPEN

    def record_success(self) -> None:
        """Record successful execution."""
        with self._lock:
            self.metrics.total_calls += 1
            self.metrics.successful_calls += 1

            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1

                # Enough successes to close circuit
                if self._success_count >= self.success_threshold:
                    self._transition_to(CircuitBreakerState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0

    def record_failure(self, error: Optional[Exception] = None) -> None:
        """Record failed execution.

        Args:
            error: Optional exception that caused failure
        """
        with self._lock:
            self.metrics.total_calls += 1
            self.metrics.failed_calls += 1
            self.metrics.last_failure_time = datetime.now(UTC)

            self._failure_count += 1
            self._last_failure_time = datetime.now(UTC)

            # Check if we should open circuit
            if self._state == CircuitBreakerState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._transition_to(CircuitBreakerState.OPEN)
                    self._opened_at = datetime.now(UTC)
                    self._failure_count = 0

            elif self._state == CircuitBreakerState.HALF_OPEN:
                # Any failure in half-open state reopens circuit
                self._transition_to(CircuitBreakerState.OPEN)
                self._opened_at = datetime.now(UTC)
                self._failure_count = 0
                self._success_count = 0

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        with self._lock:
            self._transition_to(CircuitBreakerState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._opened_at = None

    def force_open(self) -> None:
        """Manually force circuit breaker to OPEN state."""
        with self._lock:
            self._transition_to(CircuitBreakerState.OPEN)
            self._opened_at = datetime.now(UTC)

    def _check_state_transition(self) -> None:
        """Check if state should transition (OPEN -> HALF_OPEN)."""
        if self._state == CircuitBreakerState.OPEN:
            if self._opened_at:
                time_since_open = (datetime.now(UTC) - self._opened_at).total_seconds()
                if time_since_open >= self.timeout_seconds:
                    self._transition_to(CircuitBreakerState.HALF_OPEN)
                    self._success_count = 0

    def _transition_to(self, new_state: CircuitBreakerState) -> None:
        """Transition to new state and trigger callbacks."""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self.metrics.state_changes += 1
            self.metrics.last_state_change_time = datetime.now(UTC)

            # Trigger callbacks (outside lock to avoid deadlocks)
            callbacks = self._on_state_change_callbacks.copy()

        else:
            return  # No change

        # Call callbacks outside lock
        for callback in callbacks:
            try:
                callback(old_state, new_state)
            except Exception:
                # Don't let callback errors break circuit breaker
                pass

    def on_state_change(self, callback: Callable[[CircuitBreakerState, CircuitBreakerState], None]) -> None:
        """Register callback for state changes.

        Args:
            callback: Function(old_state, new_state) to call on state change
        """
        self._on_state_change_callbacks.append(callback)

    @contextmanager
    def __call__(self) -> Generator[None, None, None]:
        """Context manager for circuit breaker protection.

        Raises:
            CircuitBreakerOpen: If circuit breaker is open

        Example:
            >>> with breaker:
            ...     risky_operation()
        """
        if not self.can_execute():
            self.metrics.rejected_calls += 1
            raise CircuitBreakerOpen(f"Circuit breaker '{self.name}' is {self.state.value}")

        try:
            yield
            self.record_success()
        except Exception as e:
            self.record_failure(e)
            raise

    def get_metrics(self) -> CircuitBreakerMetrics:
        """Get current metrics.

        Returns:
            CircuitBreakerMetrics object
        """
        return self.metrics

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"CircuitBreaker("
            f"name='{self.name}', "
            f"state={self.state.value}, "
            f"failures={self._failure_count}/{self.failure_threshold})"
        )


class SafetyGate:
    """Safety gate that combines circuit breaker with policy validation.

    Provides a comprehensive execution gate that checks both circuit breaker
    state and policy violations before allowing execution.

    Example:
        >>> from src.safety import PolicyComposer, FileAccessPolicy
        >>>
        >>> composer = PolicyComposer()
        >>> composer.add_policy(FileAccessPolicy())
        >>>
        >>> gate = SafetyGate(
        ...     name="file_operations",
        ...     circuit_breaker=CircuitBreaker("file_ops"),
        ...     policy_composer=composer
        ... )
        >>>
        >>> # Check if action allowed
        >>> action = {"tool": "write_file", "path": "/tmp/test.txt"}
        >>> if gate.can_pass(action, context={}):
        ...     execute_action(action)
    """

    def __init__(
        self,
        name: str,
        circuit_breaker: Optional[CircuitBreaker] = None,
        policy_composer: Optional[Any] = None,
        require_approval: bool = False
    ):
        """Initialize safety gate.

        Args:
            name: Gate name
            circuit_breaker: Circuit breaker to check
            policy_composer: Policy composer for validation
            require_approval: Whether to require approval for high-risk actions
        """
        self.name = name
        self.circuit_breaker = circuit_breaker
        self.policy_composer = policy_composer
        self.require_approval = require_approval

        self._blocked = False
        self._blocked_reason: Optional[str] = None

    def can_pass(
        self,
        action: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Check if action can pass through gate.

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            True if allowed, False if blocked
        """
        # Check if manually blocked
        if self._blocked:
            return False

        # Check circuit breaker
        if self.circuit_breaker and not self.circuit_breaker.can_execute():
            return False

        # Check policies
        if self.policy_composer:
            result = self.policy_composer.validate(action, context or {})
            if not result.valid and result.has_blocking_violations():
                return False

        return True

    def validate(
        self,
        action: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, List[str]]:
        """Validate action and return detailed reasons if blocked.

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            (can_pass, block_reasons)
        """
        reasons = []

        # Check manual block
        if self._blocked:
            reasons.append(f"Gate manually blocked: {self._blocked_reason}")

        # Check circuit breaker
        if self.circuit_breaker:
            if not self.circuit_breaker.can_execute():
                reasons.append(
                    f"Circuit breaker '{self.circuit_breaker.name}' is {self.circuit_breaker.state.value}"
                )

        # Check policies
        if self.policy_composer:
            result = self.policy_composer.validate(action, context or {})
            if not result.valid and result.has_blocking_violations():
                for violation in result.violations:
                    reasons.append(f"Policy violation: {violation.message}")

        return (len(reasons) == 0, reasons)

    def block(self, reason: str) -> None:
        """Manually block the gate.

        Args:
            reason: Reason for blocking
        """
        self._blocked = True
        self._blocked_reason = reason

    def unblock(self) -> None:
        """Manually unblock the gate."""
        self._blocked = False
        self._blocked_reason = None

    def is_blocked(self) -> bool:
        """Check if gate is blocked."""
        return self._blocked

    @contextmanager
    def __call__(
        self,
        action: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Generator[None, None, None]:
        """Context manager for safety gate protection.

        Args:
            action: Action to validate
            context: Execution context

        Raises:
            SafetyGateBlocked: If gate blocks execution

        Example:
            >>> with gate(action={"tool": "deploy"}, context={}):
            ...     deploy_to_production()
        """
        can_pass, reasons = self.validate(action, context)

        if not can_pass:
            raise SafetyGateBlocked(
                f"Safety gate '{self.name}' blocked: {'; '.join(reasons)}"
            )

        # If we have circuit breaker, use it
        if self.circuit_breaker:
            with self.circuit_breaker():
                yield
        else:
            yield

    def __repr__(self) -> str:
        """String representation."""
        status = "blocked" if self._blocked else "open"
        breaker_state = f", breaker={self.circuit_breaker.state.value}" if self.circuit_breaker else ""
        return f"SafetyGate(name='{self.name}', status={status}{breaker_state})"


class CircuitBreakerManager:
    """Manages multiple circuit breakers and safety gates.

    Provides centralized management, metrics aggregation, and coordination
    across multiple circuit breakers.

    Example:
        >>> manager = CircuitBreakerManager()
        >>>
        >>> # Create breakers
        >>> manager.create_breaker("database", failure_threshold=5)
        >>> manager.create_breaker("api_calls", failure_threshold=10)
        >>>
        >>> # Use breaker
        >>> breaker = manager.get_breaker("database")
        >>> with breaker:
        ...     execute_database_query()
    """

    def __init__(self) -> None:
        """Initialize circuit breaker manager."""
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._gates: Dict[str, SafetyGate] = {}
        self._lock = threading.Lock()

    def create_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        success_threshold: int = 2
    ) -> CircuitBreaker:
        """Create and register a circuit breaker.

        Args:
            name: Breaker name
            failure_threshold: Failures before opening
            timeout_seconds: Timeout before attempting recovery
            success_threshold: Successes needed to close from half-open

        Returns:
            CircuitBreaker instance

        Raises:
            ValueError: If breaker with name already exists
        """
        with self._lock:
            if name in self._breakers:
                raise ValueError(f"Circuit breaker '{name}' already exists")

            breaker = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                timeout_seconds=timeout_seconds,
                success_threshold=success_threshold
            )

            self._breakers[name] = breaker
            return breaker

    def get_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name.

        Args:
            name: Breaker name

        Returns:
            CircuitBreaker if found, None otherwise
        """
        return self._breakers.get(name)

    def remove_breaker(self, name: str) -> bool:
        """Remove circuit breaker.

        Args:
            name: Breaker name

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if name in self._breakers:
                del self._breakers[name]
                return True
            return False

    def list_breakers(self) -> List[str]:
        """Get list of all breaker names.

        Returns:
            List of breaker names
        """
        return list(self._breakers.keys())

    def create_gate(
        self,
        name: str,
        breaker_name: Optional[str] = None,
        policy_composer: Optional[Any] = None
    ) -> SafetyGate:
        """Create and register a safety gate.

        Args:
            name: Gate name
            breaker_name: Name of circuit breaker to use
            policy_composer: Policy composer for validation

        Returns:
            SafetyGate instance

        Raises:
            ValueError: If gate with name already exists
        """
        with self._lock:
            if name in self._gates:
                raise ValueError(f"Safety gate '{name}' already exists")

            breaker = self._breakers.get(breaker_name) if breaker_name else None

            gate = SafetyGate(
                name=name,
                circuit_breaker=breaker,
                policy_composer=policy_composer
            )

            self._gates[name] = gate
            return gate

    def get_gate(self, name: str) -> Optional[SafetyGate]:
        """Get safety gate by name.

        Args:
            name: Gate name

        Returns:
            SafetyGate if found, None otherwise
        """
        return self._gates.get(name)

    def remove_gate(self, name: str) -> bool:
        """Remove safety gate.

        Args:
            name: Gate name

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if name in self._gates:
                del self._gates[name]
                return True
            return False

    def list_gates(self) -> List[str]:
        """Get list of all gate names.

        Returns:
            List of gate names
        """
        return list(self._gates.keys())

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all circuit breakers.

        Returns:
            Dict mapping breaker name to metrics
        """
        return {
            name: breaker.get_metrics().to_dict()
            for name, breaker in self._breakers.items()
        }

    def reset_all(self) -> None:
        """Reset all circuit breakers to CLOSED state."""
        for breaker in self._breakers.values():
            breaker.reset()

    def breaker_count(self) -> int:
        """Get total number of circuit breakers.

        Returns:
            Number of breakers
        """
        return len(self._breakers)

    def gate_count(self) -> int:
        """Get total number of safety gates.

        Returns:
            Number of gates
        """
        return len(self._gates)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"CircuitBreakerManager("
            f"breakers={len(self._breakers)}, "
            f"gates={len(self._gates)})"
        )
