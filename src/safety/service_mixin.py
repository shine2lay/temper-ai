"""Safety service mixin for framework services.

Provides convenience methods for safety policy registration,
validation, and violation handling. Moved from src.core.service
to maintain proper layer separation (core should not import safety).
"""
import threading
from typing import Any, Dict, List, Optional

from src.safety import SafetyPolicy, ValidationResult
from src.utils.logging import get_logger

# Module logger
logger = get_logger(__name__)

# Lazy-loaded sanitizer for violation context
_sanitizer = None
_sanitizer_lock = threading.Lock()

def _get_sanitizer():
    """Get or create DataSanitizer instance (lazy loading, thread-safe)."""
    global _sanitizer
    if _sanitizer is None:
        with _sanitizer_lock:
            if _sanitizer is None:
                from src.observability.sanitization import DataSanitizer
                _sanitizer = DataSanitizer()
    return _sanitizer


def reset_sanitizer() -> None:
    """Reset global sanitizer to None (for testing)."""
    global _sanitizer
    _sanitizer = None


def _sanitize_violation_context(context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Sanitize violation context to prevent sensitive data exposure in logs.

    SECURITY: Prevents secrets, PII, and credentials from being logged when
    violations are detected. Uses the same sanitization as observability layer.

    Args:
        context: Violation context dictionary (may contain sensitive data)

    Returns:
        Sanitized context safe for logging, or None if input was None, or {} if empty dict
    """
    if context is None:
        return None
    if not context:  # Empty dict
        return {}

    sanitizer = _get_sanitizer()

    # Recursively sanitize dictionary values
    def sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive keys from dictionary."""
        if not isinstance(data, dict):
            return data

        result = {}
        for key, value in data.items():
            if isinstance(value, dict):
                result[key] = sanitize_dict(value)
            elif isinstance(value, list):
                # Sanitize list elements recursively
                sanitized_list = []
                for v in value:
                    if isinstance(v, dict):
                        sanitized_list.append(sanitize_dict(v))
                    elif isinstance(v, str):
                        sanitized = sanitizer.sanitize_text(v, context="config")
                        sanitized_list.append(sanitized.sanitized_text)
                    else:
                        sanitized_list.append(v)
                result[key] = sanitized_list
            elif isinstance(value, str):
                sanitized = sanitizer.sanitize_text(value, context="config")
                result[key] = sanitized.sanitized_text
            else:
                result[key] = value
        return result

    return sanitize_dict(context)


class SafetyServiceMixin:
    """Mixin for services that integrate with the safety system.

    Provides convenience methods for safety policy registration,
    validation, and violation handling.

    Example:
        >>> from src.core.service import Service
        >>> class MyService(Service, SafetyServiceMixin):
        ...     def __init__(self):
        ...         self._policies = []
        ...
        ...     @property
        ...     def name(self) -> str:
        ...         return "my_service"
        ...
        ...     def do_action(self, action, context):
        ...         result = self.validate_action(action, context)
        ...         if not result.valid:
        ...             self.handle_violations(result.violations)
        ...             return
        ...         # Perform action
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize safety service mixin."""
        super().__init__(*args, **kwargs)
        self._policies: List[SafetyPolicy] = []

    def register_policy(self, policy: SafetyPolicy) -> None:
        """Register a safety policy with this service.

        Args:
            policy: SafetyPolicy instance to register
        """
        self._policies.append(policy)
        # Sort by priority (highest first)
        self._policies.sort(key=lambda p: p.priority, reverse=True)

    def get_policies(self) -> List[SafetyPolicy]:
        """Get list of registered policies.

        Returns:
            List of SafetyPolicy instances sorted by priority
        """
        return self._policies.copy()

    def validate_action(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against all registered policies.

        Policies are executed in priority order. Stops on first
        CRITICAL violation.

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            ValidationResult with aggregated violations
        """
        from src.safety import SafetyViolation, ValidationResult

        violations: List[SafetyViolation] = []
        metadata: Dict[str, Any] = {"policies_checked": []}

        for policy in self._policies:
            result = policy.validate(action, context)
            violations.extend(result.violations)
            metadata["policies_checked"].append(policy.name)

            # Merge policy metadata
            for key, value in result.metadata.items():
                metadata[f"policy_{policy.name}_{key}"] = value

            # Short-circuit on CRITICAL
            if result.has_critical_violations():
                metadata["short_circuit"] = True
                metadata["short_circuit_policy"] = policy.name
                break

        from src.safety import ViolationSeverity
        valid = not any(v.severity >= ViolationSeverity.HIGH for v in violations)

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata=metadata,
            policy_name="service_aggregate"
        )

    async def validate_action_async(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Async validation against all registered policies.

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            ValidationResult
        """
        from src.safety import SafetyViolation, ValidationResult, ViolationSeverity

        violations: List[SafetyViolation] = []
        metadata: Dict[str, Any] = {"policies_checked": []}

        for policy in self._policies:
            result = await policy.validate_async(action, context)
            violations.extend(result.violations)
            metadata["policies_checked"].append(policy.name)

            for key, value in result.metadata.items():
                metadata[f"policy_{policy.name}_{key}"] = value

            if result.has_critical_violations():
                metadata["short_circuit"] = True
                metadata["short_circuit_policy"] = policy.name
                break

        valid = not any(v.severity >= ViolationSeverity.HIGH for v in violations)

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata=metadata,
            policy_name="service_aggregate"
        )

    def handle_violations(
        self,
        violations: List[Any],
        raise_exception: bool = True,
        tracker: Optional[Any] = None
    ) -> None:
        """Handle safety violations with observability integration.

        Logs violations, sends to ExecutionTracker for metrics/analysis,
        and optionally raises exception.

        Args:
            violations: List of SafetyViolation instances
            raise_exception: Whether to raise exception on HIGH+ violations
            tracker: Optional ExecutionTracker for observability integration

        Raises:
            RuntimeError: If raise_exception=True and HIGH+ violations exist
        """
        from src.safety import ViolationSeverity

        if not violations:
            return

        # Log and track all violations
        for violation in violations:
            # Log with appropriate level based on severity
            log_level = {
                ViolationSeverity.INFO: logger.info,
                ViolationSeverity.LOW: logger.warning,
                ViolationSeverity.MEDIUM: logger.warning,
                ViolationSeverity.HIGH: logger.error,
                ViolationSeverity.CRITICAL: logger.critical,
            }.get(violation.severity, logger.warning)

            # SECURITY: Sanitize context and metadata before logging to prevent
            # exposure of detected secrets, PII, or credentials in application logs
            sanitized_context = _sanitize_violation_context(violation.context)
            sanitized_metadata = _sanitize_violation_context(violation.metadata) if violation.metadata else None

            log_level(
                f"Safety violation: {violation.message}",
                extra={
                    'severity': violation.severity.name,
                    'policy': violation.policy_name,
                    'context': sanitized_context,
                    'metadata': sanitized_metadata
                }
            )

            # Track violation in observability system
            if tracker and hasattr(tracker, 'track_safety_violation'):
                try:
                    tracker.track_safety_violation(
                        violation_severity=violation.severity.name,
                        violation_message=violation.message,
                        policy_name=violation.policy_name,
                        service_name=getattr(self, 'name', 'unknown'),
                        context=sanitized_context
                    )
                except Exception as e:
                    # Don't fail violation handling if tracking fails
                    logger.warning(
                        f"Failed to track safety violation in observability: {e}",
                        exc_info=True
                    )

        # Raise on blocking violations
        if raise_exception:
            blocking = [v for v in violations if v.severity >= ViolationSeverity.HIGH]
            if blocking:
                critical = [v for v in blocking if v.severity == ViolationSeverity.CRITICAL]
                if critical:
                    raise RuntimeError(
                        f"CRITICAL safety violation(s): {', '.join(v.message for v in critical)}"
                    )
                else:
                    raise RuntimeError(
                        f"HIGH safety violation(s): {', '.join(v.message for v in blocking)}"
                    )
