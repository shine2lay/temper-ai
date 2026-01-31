"""Safety system exception hierarchy.

This module defines exception classes for safety violations that can be raised
and caught during workflow execution. Exceptions wrap SafetyViolation data models
with additional context and serialization capabilities.

Exception Hierarchy:
    SafetyViolationException (base)
    ├── BlastRadiusViolation
    ├── ActionPolicyViolation
    ├── RateLimitViolation
    ├── ResourceLimitViolation
    ├── ForbiddenOperationViolation
    └── AccessDeniedViolation

All exceptions support:
- Structured metadata for observability integration
- JSON serialization for logging
- Clear error messages with remediation hints
- Integration with SafetyViolation data models
"""
from typing import Dict, Any, Optional
from src.safety.interfaces import SafetyViolation, ViolationSeverity


class SafetyViolationException(Exception):
    """Base exception for all safety policy violations.

    This exception wraps a SafetyViolation data model and provides
    exception-based error handling for safety checks.

    Attributes:
        violation: The underlying SafetyViolation data
        policy_name: Name of the policy that detected the violation
        severity: Severity level of the violation
        message: Human-readable error message
        action: The action that triggered the violation
        context: Execution context
        remediation_hint: Optional suggestion for fixing the issue

    Example:
        >>> try:
        ...     raise SafetyViolationException(
        ...         policy_name="FileAccessPolicy",
        ...         severity=ViolationSeverity.CRITICAL,
        ...         message="Access to /etc/passwd denied",
        ...         action="read_file(/etc/passwd)",
        ...         context={"agent": "researcher"}
        ...     )
        ... except SafetyViolationException as e:
        ...     print(e.to_dict())
    """

    def __init__(
        self,
        policy_name: str,
        severity: ViolationSeverity,
        message: str,
        action: str,
        context: Dict[str, Any],
        remediation_hint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Initialize safety violation exception.

        Args:
            policy_name: Name of the policy that detected the violation
            severity: Severity level (CRITICAL, HIGH, MEDIUM, LOW, INFO)
            message: Human-readable error message
            action: String representation of the action that failed
            context: Execution context (agent, stage, workflow, etc.)
            remediation_hint: Optional suggestion for how to fix the issue
            metadata: Additional violation-specific data
        """
        super().__init__(message)
        self.violation = SafetyViolation(
            policy_name=policy_name,
            severity=severity,
            message=message,
            action=action,
            context=context,
            remediation_hint=remediation_hint,
            metadata=metadata or {}
        )
        self.policy_name = policy_name
        self.severity = severity
        self.message = message
        self.action = action
        self.context = context
        self.remediation_hint = remediation_hint
        self.metadata = metadata or {}

    def __str__(self) -> str:
        """Return formatted error message."""
        msg = f"[{self.severity.name}] {self.policy_name}: {self.message}"
        if self.remediation_hint:
            msg += f"\n  Remediation: {self.remediation_hint}"
        return msg

    def __repr__(self) -> str:
        """Return detailed representation."""
        return (
            f"{self.__class__.__name__}("
            f"policy={self.policy_name}, "
            f"severity={self.severity.name}, "
            f"message={self.message!r})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization.

        Returns:
            Dictionary with all violation data

        Example:
            >>> exc = SafetyViolationException(...)
            >>> log_data = exc.to_dict()
            >>> logger.error("Safety violation", extra=log_data)
        """
        return self.violation.to_dict()

    @classmethod
    def from_violation(cls, violation: SafetyViolation) -> "SafetyViolationException":
        """Create exception from SafetyViolation data model.

        Args:
            violation: SafetyViolation instance

        Returns:
            SafetyViolationException wrapping the violation

        Example:
            >>> violation = SafetyViolation(...)
            >>> exc = SafetyViolationException.from_violation(violation)
            >>> raise exc
        """
        return cls(
            policy_name=violation.policy_name,
            severity=violation.severity,
            message=violation.message,
            action=violation.action,
            context=violation.context,
            remediation_hint=violation.remediation_hint,
            metadata=violation.metadata
        )


class BlastRadiusViolation(SafetyViolationException):
    """Exception for blast radius limit violations.

    Raised when an action would affect too many files, make changes that are
    too large, or otherwise exceed blast radius safety limits.

    Example:
        >>> raise BlastRadiusViolation(
        ...     policy_name="BlastRadiusPolicy",
        ...     message="Attempted to modify 50 files (limit: 10)",
        ...     action="bulk_edit",
        ...     context={"agent": "coder", "files": 50},
        ...     remediation_hint="Split changes into smaller batches",
        ...     metadata={"files_affected": 50, "limit": 10}
        ... )
    """

    def __init__(
        self,
        policy_name: str,
        message: str,
        action: str,
        context: Dict[str, Any],
        remediation_hint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Initialize blast radius violation.

        Args:
            policy_name: Name of blast radius policy
            message: Human-readable error message
            action: Action that exceeded limits
            context: Execution context
            remediation_hint: How to fix (e.g., "Split into smaller batches")
            metadata: Additional data (e.g., files_affected, limit)
        """
        super().__init__(
            policy_name=policy_name,
            severity=ViolationSeverity.HIGH,
            message=message,
            action=action,
            context=context,
            remediation_hint=remediation_hint or "Reduce the scope of changes",
            metadata=metadata
        )


class ActionPolicyViolation(SafetyViolationException):
    """Exception for action policy violations.

    Raised when an action is forbidden by the action policy engine,
    such as accessing restricted operations, using blocked tools,
    or violating execution constraints.

    Example:
        >>> raise ActionPolicyViolation(
        ...     policy_name="ActionPolicy",
        ...     message="Tool 'execute_shell' is forbidden in production",
        ...     action="execute_shell('rm -rf /')",
        ...     context={"agent": "deployer", "environment": "production"},
        ...     remediation_hint="Use approved deployment tools instead",
        ...     metadata={"forbidden_tool": "execute_shell", "reason": "destructive"}
        ... )
    """

    def __init__(
        self,
        policy_name: str,
        message: str,
        action: str,
        context: Dict[str, Any],
        remediation_hint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Initialize action policy violation.

        Args:
            policy_name: Name of action policy
            message: Human-readable error message
            action: Forbidden action
            context: Execution context
            remediation_hint: How to fix
            metadata: Additional data (e.g., forbidden_tool, reason)
        """
        super().__init__(
            policy_name=policy_name,
            severity=ViolationSeverity.CRITICAL,
            message=message,
            action=action,
            context=context,
            remediation_hint=remediation_hint or "Review action policy constraints",
            metadata=metadata
        )


class RateLimitViolation(SafetyViolationException):
    """Exception for rate limit violations.

    Raised when an agent or workflow exceeds rate limits for API calls,
    database operations, file operations, or other throttled resources.

    Example:
        >>> raise RateLimitViolation(
        ...     policy_name="RateLimiter",
        ...     message="Exceeded API call limit: 100 calls/hour (limit: 50)",
        ...     action="api_call",
        ...     context={"agent": "researcher", "endpoint": "/search"},
        ...     remediation_hint="Wait 30 minutes or request rate limit increase",
        ...     metadata={"current_rate": 100, "limit": 50, "window": "1h"}
        ... )
    """

    def __init__(
        self,
        policy_name: str,
        message: str,
        action: str,
        context: Dict[str, Any],
        remediation_hint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Initialize rate limit violation.

        Args:
            policy_name: Name of rate limiter policy
            message: Human-readable error message
            action: Action that exceeded rate limit
            context: Execution context
            remediation_hint: How to fix
            metadata: Rate limit data (current_rate, limit, window, retry_after)
        """
        super().__init__(
            policy_name=policy_name,
            severity=ViolationSeverity.MEDIUM,
            message=message,
            action=action,
            context=context,
            remediation_hint=remediation_hint or "Reduce request rate or wait for cooldown",
            metadata=metadata
        )


class ResourceLimitViolation(SafetyViolationException):
    """Exception for resource consumption limit violations.

    Raised when an action would exceed memory, CPU, disk, or other
    resource consumption limits.

    Example:
        >>> raise ResourceLimitViolation(
        ...     policy_name="ResourceLimiter",
        ...     message="Memory usage would exceed 1GB (current: 950MB, requested: 100MB)",
        ...     action="load_large_dataset",
        ...     context={"agent": "analyst"},
        ...     remediation_hint="Process data in smaller chunks",
        ...     metadata={"resource": "memory", "current": 950, "requested": 100, "limit": 1024}
        ... )
    """

    def __init__(
        self,
        policy_name: str,
        message: str,
        action: str,
        context: Dict[str, Any],
        remediation_hint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Initialize resource limit violation.

        Args:
            policy_name: Name of resource limiter policy
            message: Human-readable error message
            action: Action that would exceed limits
            context: Execution context
            remediation_hint: How to fix
            metadata: Resource data (resource type, current, requested, limit)
        """
        super().__init__(
            policy_name=policy_name,
            severity=ViolationSeverity.HIGH,
            message=message,
            action=action,
            context=context,
            remediation_hint=remediation_hint or "Reduce resource consumption",
            metadata=metadata
        )


class ForbiddenOperationViolation(SafetyViolationException):
    """Exception for forbidden operation violations.

    Raised when an action attempts a forbidden operation such as
    accessing secrets, modifying critical files, or executing
    dangerous commands.

    Example:
        >>> raise ForbiddenOperationViolation(
        ...     policy_name="ForbiddenOps",
        ...     message="Attempted to read API keys from environment",
        ...     action="os.getenv('API_KEY')",
        ...     context={"agent": "untrusted"},
        ...     remediation_hint="Use secure secrets management instead",
        ...     metadata={"operation": "secret_access", "pattern": "API_KEY"}
        ... )
    """

    def __init__(
        self,
        policy_name: str,
        message: str,
        action: str,
        context: Dict[str, Any],
        remediation_hint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Initialize forbidden operation violation.

        Args:
            policy_name: Name of forbidden operations policy
            message: Human-readable error message
            action: Forbidden operation
            context: Execution context
            remediation_hint: How to fix
            metadata: Operation details (operation type, pattern matched)
        """
        super().__init__(
            policy_name=policy_name,
            severity=ViolationSeverity.CRITICAL,
            message=message,
            action=action,
            context=context,
            remediation_hint=remediation_hint or "Remove forbidden operation",
            metadata=metadata
        )


class AccessDeniedViolation(SafetyViolationException):
    """Exception for access control violations.

    Raised when an agent attempts to access files, directories, or
    resources that are outside their permitted scope.

    Example:
        >>> raise AccessDeniedViolation(
        ...     policy_name="FileAccessPolicy",
        ...     message="Access denied to /etc/passwd",
        ...     action="read_file(/etc/passwd)",
        ...     context={"agent": "researcher"},
        ...     remediation_hint="Restrict file access to project directory",
        ...     metadata={"path": "/etc/passwd", "allowed_paths": ["/project/*"]}
        ... )
    """

    def __init__(
        self,
        policy_name: str,
        message: str,
        action: str,
        context: Dict[str, Any],
        remediation_hint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Initialize access denied violation.

        Args:
            policy_name: Name of access control policy
            message: Human-readable error message
            action: Denied action
            context: Execution context
            remediation_hint: How to fix
            metadata: Access control data (path, allowed_paths, denied_reason)
        """
        super().__init__(
            policy_name=policy_name,
            severity=ViolationSeverity.CRITICAL,
            message=message,
            action=action,
            context=context,
            remediation_hint=remediation_hint or "Ensure access path is within allowed scope",
            metadata=metadata
        )
