"""Circuit breakers and safety gates for preventing cascading failures.

This module re-exports the unified CircuitBreaker from src.core.circuit_breaker
and provides SafetyGate and CircuitBreakerManager which build on top of it.

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
from typing import Dict, Any, Optional, List, Generator
from contextlib import contextmanager
import threading

# Re-export core circuit breaker classes
from src.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerMetrics,
    CircuitState,
    StateStorage,
)

# Backward-compatible aliases
CircuitBreakerState = CircuitState
CircuitBreakerOpen = CircuitBreakerError


class SafetyGateBlocked(Exception):
    """Exception raised when safety gate blocks execution."""
    pass


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
        if self._blocked:
            return False

        if self.circuit_breaker and not self.circuit_breaker.can_execute():
            return False

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

        if self._blocked:
            reasons.append(f"Gate manually blocked: {self._blocked_reason}")

        if self.circuit_breaker:
            if not self.circuit_breaker.can_execute():
                reasons.append(
                    f"Circuit breaker '{self.circuit_breaker.name}' is "
                    f"{self.circuit_breaker.state.value}"
                )

        if self.policy_composer:
            result = self.policy_composer.validate(action, context or {})
            if not result.valid and result.has_blocking_violations():
                for violation in result.violations:
                    reasons.append(f"Policy violation: {violation.message}")

        return (len(reasons) == 0, reasons)

    def block(self, reason: str) -> None:
        """Manually block the gate."""
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

        Raises:
            SafetyGateBlocked: If gate blocks execution
        """
        can_pass, reasons = self.validate(action, context)

        if not can_pass:
            raise SafetyGateBlocked(
                f"Safety gate '{self.name}' blocked: {'; '.join(reasons)}"
            )

        if self.circuit_breaker:
            with self.circuit_breaker():
                yield
        else:
            yield

    def __repr__(self) -> str:
        status = "blocked" if self._blocked else "open"
        breaker_state = (
            f", breaker={self.circuit_breaker.state.value}"
            if self.circuit_breaker else ""
        )
        return f"SafetyGate(name='{self.name}', status={status}{breaker_state})"


class CircuitBreakerManager:
    """Manages multiple circuit breakers and safety gates.

    Example:
        >>> manager = CircuitBreakerManager()
        >>> manager.create_breaker("database", failure_threshold=5)
        >>> breaker = manager.get_breaker("database")
        >>> with breaker:
        ...     execute_database_query()
    """

    def __init__(self) -> None:
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
            name: Breaker name (1-100 characters)
            failure_threshold: Failures before opening (1-1000)
            timeout_seconds: Timeout before recovery attempt (1-86400)
            success_threshold: Successes to close from half-open (1-100)

        Returns:
            CircuitBreaker instance

        Raises:
            ValueError: If breaker with name already exists or parameters invalid
        """
        if not isinstance(name, str):
            raise ValueError(f"name must be a string, got {type(name).__name__}")
        if not name or len(name) > 100:
            raise ValueError(f"name must be 1-100 characters, got {len(name)}")

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
        """Get circuit breaker by name."""
        return self._breakers.get(name)

    def remove_breaker(self, name: str) -> bool:
        """Remove circuit breaker."""
        with self._lock:
            if name in self._breakers:
                del self._breakers[name]
                return True
            return False

    def list_breakers(self) -> List[str]:
        """Get list of all breaker names."""
        return list(self._breakers.keys())

    def create_gate(
        self,
        name: str,
        breaker_name: Optional[str] = None,
        policy_composer: Optional[Any] = None
    ) -> SafetyGate:
        """Create and register a safety gate."""
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
        """Get safety gate by name."""
        return self._gates.get(name)

    def remove_gate(self, name: str) -> bool:
        """Remove safety gate."""
        with self._lock:
            if name in self._gates:
                del self._gates[name]
                return True
            return False

    def list_gates(self) -> List[str]:
        """Get list of all gate names."""
        return list(self._gates.keys())

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all circuit breakers."""
        return {
            name: breaker.get_metrics().to_dict()
            for name, breaker in self._breakers.items()
        }

    def reset_all(self) -> None:
        """Reset all circuit breakers to CLOSED state."""
        for breaker in self._breakers.values():
            breaker.reset()

    def breaker_count(self) -> int:
        return len(self._breakers)

    def gate_count(self) -> int:
        return len(self._gates)

    def __repr__(self) -> str:
        return (
            f"CircuitBreakerManager("
            f"breakers={len(self._breakers)}, "
            f"gates={len(self._gates)})"
        )
