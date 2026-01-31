"""Rate Limiting Safety Policy.

Enforces rate limits on operations to prevent:
- Resource exhaustion from runaway processes
- API quota violations
- Denial of service (intentional or accidental)
- Cost overruns from excessive operations

Supports multiple rate limiting strategies:
- Fixed window: Max operations per time window
- Sliding window: Rolling time window for smoother limits
- Token bucket: Burst allowance with refill rate
"""
import time
from typing import Dict, Any, List, Optional
from collections import defaultdict
from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import ValidationResult, SafetyViolation, ViolationSeverity


class RateLimiterPolicy(BaseSafetyPolicy):
    """Enforces rate limits on operations.

    Configuration options:
        limits: Dict mapping operation types to limits
            - max_per_second: Maximum operations per second
            - max_per_minute: Maximum operations per minute
            - max_per_hour: Maximum operations per hour
        strategy: Rate limiting strategy ("fixed_window", "sliding_window", "token_bucket")
        burst_allowance: Allow temporary bursts (for token_bucket)
        per_entity: Whether to track limits per entity (agent, user, etc.)

    Example:
        >>> config = {
        ...     "limits": {
        ...         "llm_call": {"max_per_minute": 60, "max_per_hour": 1000},
        ...         "file_write": {"max_per_minute": 20},
        ...         "api_call": {"max_per_second": 10}
        ...     },
        ...     "strategy": "sliding_window"
        ... }
        >>> policy = RateLimiterPolicy(config)
        >>> result = policy.validate(
        ...     action={"operation": "llm_call"},
        ...     context={"agent_id": "agent-123"}
        ... )
    """

    # Default limits for common operations
    DEFAULT_LIMITS = {
        "llm_call": {"max_per_minute": 100, "max_per_hour": 5000},
        "tool_call": {"max_per_minute": 60},
        "file_operation": {"max_per_minute": 30},
        "api_call": {"max_per_second": 20, "max_per_minute": 1000},
        "database_query": {"max_per_second": 50, "max_per_minute": 2000}
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize rate limiter policy.

        Args:
            config: Policy configuration (optional)
        """
        super().__init__(config or {})

        # Configuration
        self.limits = self.config.get("limits", self.DEFAULT_LIMITS)
        self.strategy = self.config.get("strategy", "sliding_window")
        self.burst_allowance = self.config.get("burst_allowance", 1.5)
        self.per_entity = self.config.get("per_entity", True)

        # State tracking: {(operation, entity): [(timestamp, ...)]}
        self._operation_history: Dict[tuple[str, str], List[float]] = defaultdict(list)

    @property
    def name(self) -> str:
        """Return policy name."""
        return "rate_limiter"

    @property
    def version(self) -> str:
        """Return policy version."""
        return "1.0.0"

    @property
    def priority(self) -> int:
        """Return policy priority.

        Rate limiting has high priority to prevent resource exhaustion.
        """
        return 85

    def _get_entity_key(self, context: Dict[str, Any]) -> str:
        """Extract entity identifier from context.

        Args:
            context: Execution context

        Returns:
            Entity key (agent_id, user_id, etc.) or "global"
        """
        if not self.per_entity:
            return "global"

        return (
            context.get("agent_id") or
            context.get("user_id") or
            context.get("workflow_id") or
            "global"
        )

    def _clean_old_records(
        self,
        history: List[float],
        max_age_seconds: float
    ) -> List[float]:
        """Remove records older than max_age.

        Args:
            history: List of timestamps
            max_age_seconds: Maximum age to keep

        Returns:
            Cleaned list of timestamps
        """
        now = time.time()
        cutoff = now - max_age_seconds
        return [ts for ts in history if ts > cutoff]

    def _check_limit(
        self,
        history: List[float],
        max_count: int,
        window_seconds: float,
        operation: str
    ) -> Optional[SafetyViolation]:
        """Check if operation count exceeds limit in time window.

        Args:
            history: List of operation timestamps
            max_count: Maximum allowed operations
            window_seconds: Time window in seconds
            operation: Operation name

        Returns:
            SafetyViolation if limit exceeded, None otherwise
        """
        # Clean old records
        recent_history = self._clean_old_records(history, window_seconds)

        # Check if limit exceeded
        if len(recent_history) >= max_count:
            # Calculate wait time
            oldest_in_window = min(recent_history) if recent_history else time.time()
            wait_seconds = window_seconds - (time.time() - oldest_in_window)

            # Determine severity based on how much over limit
            overage_ratio = len(recent_history) / max_count
            if overage_ratio > 2.0:
                severity = ViolationSeverity.CRITICAL
            elif overage_ratio >= 1.0:
                severity = ViolationSeverity.HIGH
            else:
                severity = ViolationSeverity.MEDIUM

            window_label = self._format_window(window_seconds)
            return SafetyViolation(
                policy_name=self.name,
                severity=severity,
                message=f"Rate limit exceeded for '{operation}': {len(recent_history)} operations in {window_label} (limit: {max_count})",
                action=operation,
                context={"wait_seconds": round(wait_seconds, 1)},
                remediation_hint=f"Wait {round(wait_seconds, 1)}s before retrying",
                metadata={
                    "current_count": len(recent_history),
                    "max_count": max_count,
                    "window_seconds": window_seconds,
                    "overage_ratio": round(overage_ratio, 2)
                }
            )

        return None

    def _format_window(self, seconds: float) -> str:
        """Format time window for human readability.

        Args:
            seconds: Time window in seconds

        Returns:
            Formatted string (e.g., "1 minute", "30 seconds")
        """
        if seconds >= 3600:
            return f"{int(seconds / 3600)} hour{'s' if seconds >= 7200 else ''}"
        elif seconds >= 60:
            return f"{int(seconds / 60)} minute{'s' if seconds >= 120 else ''}"
        else:
            return f"{int(seconds)} second{'s' if seconds >= 2 else ''}"

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Check if operation exceeds rate limits.

        Args:
            action: Action to validate, should contain:
                - operation: Type of operation (llm_call, file_write, etc.)
            context: Execution context (for per-entity tracking)

        Returns:
            ValidationResult with violations if rate limit exceeded
        """
        violations: List[SafetyViolation] = []

        # Extract operation type
        operation = action.get("operation", "unknown")

        # Get limits for this operation
        operation_limits = self.limits.get(operation)
        if not operation_limits:
            # No limits defined for this operation, allow it
            return ValidationResult(valid=True, policy_name=self.name)

        # Get entity key for tracking
        entity_key = self._get_entity_key(context)
        history_key = (operation, entity_key)

        # Get operation history
        history = self._operation_history[history_key]
        now = time.time()

        # Check each limit type
        if "max_per_second" in operation_limits:
            violation = self._check_limit(
                history,
                operation_limits["max_per_second"],
                1.0,
                operation
            )
            if violation:
                violations.append(violation)

        if "max_per_minute" in operation_limits:
            violation = self._check_limit(
                history,
                operation_limits["max_per_minute"],
                60.0,
                operation
            )
            if violation:
                violations.append(violation)

        if "max_per_hour" in operation_limits:
            violation = self._check_limit(
                history,
                operation_limits["max_per_hour"],
                3600.0,
                operation
            )
            if violation:
                violations.append(violation)

        # If no violations, record this operation
        if not violations:
            history.append(now)
            # Keep only recent history to prevent memory growth
            max_history_age = max(3600.0, max(
                v for k, v in operation_limits.items()
                if k.startswith("max_per_")
            ) if any(k.startswith("max_per_") for k in operation_limits) else 3600.0)
            self._operation_history[history_key] = self._clean_old_records(history, max_history_age * 2)

        # Determine validity (invalid if any HIGH or CRITICAL violations)
        valid = not any(
            v.severity >= ViolationSeverity.HIGH
            for v in violations
        )

        return ValidationResult(
            valid=valid,
            violations=violations,
            policy_name=self.name
        )

    def reset_limits(self, operation: Optional[str] = None, entity: Optional[str] = None) -> None:
        """Reset rate limit tracking (useful for testing).

        Args:
            operation: Specific operation to reset (None = all)
            entity: Specific entity to reset (None = all)
        """
        if operation is None and entity is None:
            # Reset all
            self._operation_history.clear()
        elif operation and entity:
            # Reset specific operation for specific entity
            key = (operation, entity)
            if key in self._operation_history:
                del self._operation_history[key]
        elif operation:
            # Reset specific operation for all entities
            keys_to_delete = [k for k in self._operation_history.keys() if k[0] == operation]
            for key in keys_to_delete:
                del self._operation_history[key]
        elif entity:
            # Reset all operations for specific entity
            keys_to_delete = [k for k in self._operation_history.keys() if k[1] == entity]
            for key in keys_to_delete:
                del self._operation_history[key]
