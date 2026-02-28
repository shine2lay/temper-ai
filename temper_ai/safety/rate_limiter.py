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

import threading
import time
import unicodedata
from collections import defaultdict
from typing import Any

from temper_ai.shared.constants.durations import (
    RATE_LIMIT_WINDOW_DAY,
    RATE_LIMIT_WINDOW_HOUR,
    RATE_LIMIT_WINDOW_MINUTE,
    RATE_LIMIT_WINDOW_SECOND,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
)

SECONDS_PER_2_HOURS = 7200

# Default rate limit values
DEFAULT_MAX_CALLS_PER_MINUTE = 100  # scanner: skip-magic
DEFAULT_MAX_CALLS_PER_HOUR = 5000  # scanner: skip-magic
DEFAULT_MAX_CALLS_PER_SECOND = 20  # scanner: skip-magic
DEFAULT_MAX_DB_QUERIES_PER_SECOND = 50  # scanner: skip-magic
DEFAULT_MAX_DB_QUERIES_PER_MINUTE = 2000  # scanner: skip-magic
DEFAULT_MAX_FILE_OPS_PER_MINUTE = 30  # scanner: skip-magic
DEFAULT_MAX_TOOL_CALLS_PER_MINUTE = 60  # scanner: skip-magic
DEFAULT_MAX_API_CALLS_PER_MINUTE = 1000  # scanner: skip-magic
from temper_ai.safety.base import BaseSafetyPolicy
from temper_ai.safety.constants import RATE_LIMIT_PRIORITY
from temper_ai.safety.interfaces import (
    SafetyViolation,
    ValidationResult,
    ViolationSeverity,
)

# Burst allowance multiplier (1.5 = 50% burst above base rate)
BURST_ALLOWANCE_DEFAULT = 1.5  # scanner: skip-magic

# Overage threshold for critical severity
OVERAGE_CRITICAL_THRESHOLD = 2
# History retention multiplier
HISTORY_RETENTION_MULTIPLIER = 2


class WindowRateLimitPolicy(BaseSafetyPolicy):
    """Window-based rate limiting policy.

    Uses fixed/sliding time windows to enforce operation rate limits.
    For token-bucket-based rate limiting, see ``TokenBucketRateLimitPolicy``
    in ``temper_ai.safety.policies.rate_limit_policy``.

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
        >>> policy = WindowRateLimitPolicy(config)
        >>> result = policy.validate(
        ...     action={"operation": "llm_call"},
        ...     context={"agent_id": "agent-123"}
        ... )
    """

    # Default limits for common operations
    DEFAULT_LIMITS = {
        "llm_call": {
            "max_per_minute": DEFAULT_MAX_CALLS_PER_MINUTE,
            "max_per_hour": DEFAULT_MAX_CALLS_PER_HOUR,
        },
        "tool_call": {"max_per_minute": DEFAULT_MAX_TOOL_CALLS_PER_MINUTE},
        "file_operation": {"max_per_minute": DEFAULT_MAX_FILE_OPS_PER_MINUTE},
        "api_call": {
            "max_per_second": DEFAULT_MAX_CALLS_PER_SECOND,
            "max_per_minute": DEFAULT_MAX_API_CALLS_PER_MINUTE,
        },
        "database_query": {
            "max_per_second": DEFAULT_MAX_DB_QUERIES_PER_SECOND,
            "max_per_minute": DEFAULT_MAX_DB_QUERIES_PER_MINUTE,
        },
    }

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize rate limiter policy.

        Args:
            config: Policy configuration (optional)
        """
        super().__init__(config or {})

        # Configuration
        self.limits = self.config.get("limits", self.DEFAULT_LIMITS)
        self.strategy = self.config.get("strategy", "sliding_window")
        self.burst_allowance = self.config.get(
            "burst_allowance", BURST_ALLOWANCE_DEFAULT
        )
        self.per_entity = self.config.get("per_entity", True)

        # State tracking: {(operation, entity): [(timestamp, ...)]}
        self._operation_history: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._history_lock = threading.Lock()

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
        return RATE_LIMIT_PRIORITY

    def _get_entity_key(self, context: dict[str, Any]) -> str:
        """Extract and normalize entity identifier from context.

        Normalization prevents bypass attacks via:
        - Case variation ("Admin" vs "admin")
        - Whitespace insertion (" agent-1 " vs "agent-1")
        - Unicode composition variants (NFD vs NFC)

        Args:
            context: Execution context

        Returns:
            Normalized entity key (agent_id, user_id, etc.) or "global"
        """
        if not self.per_entity:
            return "global"

        raw = (
            context.get("agent_id")
            or context.get("user_id")
            or context.get("workflow_id")
            or "global"
        )

        # Normalize: NFKC unicode -> lowercase -> strip whitespace
        normalized = unicodedata.normalize("NFKC", str(raw))
        normalized = normalized.lower().strip()
        return normalized if normalized else "global"

    def _clean_old_records(
        self, history: list[float], max_age_seconds: float
    ) -> list[float]:
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
        history: list[float],
        max_count: int,
        window_seconds: float,
        operation: str,
    ) -> SafetyViolation | None:
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
            if overage_ratio > OVERAGE_CRITICAL_THRESHOLD:
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
                    "overage_ratio": round(overage_ratio, 2),
                },
            )

        return None

    def _format_window(self, seconds: float) -> str:
        """Format time window for human readability.

        Args:
            seconds: Time window in seconds

        Returns:
            Formatted string (e.g., "1 minute", "30 seconds")
        """
        if seconds >= SECONDS_PER_HOUR:
            return f"{int(seconds / SECONDS_PER_HOUR)} hour{'s' if seconds >= SECONDS_PER_2_HOURS else ''}"
        elif seconds >= SECONDS_PER_MINUTE:
            return f"{int(seconds / SECONDS_PER_MINUTE)} minute{'s' if seconds >= OVERAGE_CRITICAL_THRESHOLD * SECONDS_PER_MINUTE else ''}"
        else:
            return f"{int(seconds)} second{'s' if seconds >= OVERAGE_CRITICAL_THRESHOLD else ''}"

    def _check_time_window_limits(
        self, history: list[float], operation_limits: dict[str, int], operation: str
    ) -> list[SafetyViolation]:
        """Check all time window limits for an operation.

        Args:
            history: Operation history timestamps
            operation_limits: Limits for this operation
            operation: Operation name

        Returns:
            List of violations
        """
        violations: list[SafetyViolation] = []

        # Define limit checks
        limit_checks = [
            ("max_per_second", RATE_LIMIT_WINDOW_SECOND),
            ("max_per_minute", RATE_LIMIT_WINDOW_MINUTE),
            ("max_per_hour", RATE_LIMIT_WINDOW_HOUR),
        ]

        for limit_key, window_duration in limit_checks:
            if limit_key not in operation_limits:
                continue

            violation = self._check_limit(
                history, operation_limits[limit_key], window_duration, operation
            )
            if violation:
                violations.append(violation)

        return violations

    def _get_max_window_duration(self, operation_limits: dict[str, int]) -> float:
        """Get maximum window duration from operation limits.

        Args:
            operation_limits: Limits configuration

        Returns:
            Maximum window duration in seconds
        """
        window_durations = {
            "max_per_second": RATE_LIMIT_WINDOW_SECOND,
            "max_per_minute": RATE_LIMIT_WINDOW_MINUTE,
            "max_per_hour": RATE_LIMIT_WINDOW_HOUR,
            "max_per_day": RATE_LIMIT_WINDOW_DAY,
        }

        return max(
            (
                window_durations.get(k, RATE_LIMIT_WINDOW_HOUR)
                for k in operation_limits
                if k.startswith("max_per_")
            ),
            default=RATE_LIMIT_WINDOW_HOUR,
        )

    def _validate_impl(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        """Check if operation exceeds rate limits.

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            ValidationResult with violations if rate limit exceeded
        """
        # Extract operation type
        operation = action.get("operation", "unknown")

        # Get limits for this operation
        operation_limits = self.limits.get(operation)
        if not operation_limits:
            return ValidationResult(valid=True, policy_name=self.name)

        # Get entity key for tracking
        entity_key = self._get_entity_key(context)
        history_key = (operation, entity_key)

        # Atomic check-and-mutate under lock to prevent race conditions
        with self._history_lock:
            history = self._operation_history[history_key]
            now = time.time()

            # Check all time window limits
            violations = self._check_time_window_limits(
                history, operation_limits, operation
            )

            # If no violations, record this operation
            if not violations:
                history.append(now)
                max_window = self._get_max_window_duration(operation_limits)
                self._operation_history[history_key] = self._clean_old_records(
                    history, max_window * HISTORY_RETENTION_MULTIPLIER
                )

        # Determine validity
        valid = not any(v.severity >= ViolationSeverity.HIGH for v in violations)

        return ValidationResult(
            valid=valid, violations=violations, policy_name=self.name
        )

    def _delete_matching_keys(self, index: int, value: str) -> None:
        """Delete history entries where the key tuple matches at the given index.

        Must be called with ``_history_lock`` held.

        Args:
            index: Tuple index to match (0 = operation, 1 = entity)
            value: Value to match at that index
        """
        keys_to_delete = [k for k in self._operation_history if k[index] == value]
        for key in keys_to_delete:
            del self._operation_history[key]

    def reset_limits(
        self, operation: str | None = None, entity: str | None = None
    ) -> None:
        """Reset rate limit tracking (useful for testing).

        Args:
            operation: Specific operation to reset (None = all)
            entity: Specific entity to reset (None = all)
        """
        with self._history_lock:
            if operation is None and entity is None:
                self._operation_history.clear()
            elif operation and entity:
                self._operation_history.pop((operation, entity), None)
            elif operation:
                self._delete_matching_keys(0, operation)
            elif entity:
                self._delete_matching_keys(1, entity)
