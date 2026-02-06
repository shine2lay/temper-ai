"""Safety policy interfaces and core data structures.

This module defines the foundational interfaces for all safety policies,
including validation results, violation reporting, and severity levels.

Interfaces are designed for both synchronous and asynchronous execution contexts.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable


class ViolationSeverity(Enum):
    """Severity levels for safety violations.

    Determines how violations are handled:
    - CRITICAL: Blocks execution immediately
    - HIGH: Requires approval or escalation
    - MEDIUM: Warning + logging
    - LOW: Logging only
    - INFO: Informational
    """
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    INFO = 1

    def __lt__(self, other: object) -> bool:
        """Enable severity comparisons."""
        if isinstance(other, ViolationSeverity):
            return self.value < other.value
        return NotImplemented

    def __le__(self, other: object) -> bool:
        """Enable severity comparisons."""
        if isinstance(other, ViolationSeverity):
            return self.value <= other.value
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        """Enable severity comparisons."""
        if isinstance(other, ViolationSeverity):
            return self.value > other.value
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        """Enable severity comparisons."""
        if isinstance(other, ViolationSeverity):
            return self.value >= other.value
        return NotImplemented


@dataclass
class SafetyViolation:
    """Represents a safety policy violation.

    Attributes:
        policy_name: Name of the policy that detected the violation
        severity: Severity level of the violation
        message: Human-readable description of the violation
        action: The action that triggered the violation
        context: Additional context about the execution environment
        timestamp: When the violation occurred (ISO format)
        remediation_hint: Optional suggestion for how to fix the issue
        metadata: Additional violation-specific data

    Example:
        >>> violation = SafetyViolation(
        ...     policy_name="FileAccessPolicy",
        ...     severity=ViolationSeverity.CRITICAL,
        ...     message="Attempted to access forbidden directory",
        ...     action="read_file(/etc/passwd)",
        ...     context={"agent": "researcher", "stage": "research"},
        ...     timestamp="2026-01-26T10:30:00Z",
        ...     remediation_hint="Remove /etc/passwd from file access list"
        ... )
    """
    policy_name: str
    severity: ViolationSeverity
    message: str
    action: str
    context: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    remediation_hint: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert violation to dictionary for logging/serialization."""
        return {
            "policy_name": self.policy_name,
            "severity": self.severity.name,
            "severity_value": self.severity.value,
            "message": self.message,
            "action": self.action,
            "context": self.context,
            "timestamp": self.timestamp,
            "remediation_hint": self.remediation_hint,
            "metadata": self.metadata
        }


@dataclass
class ValidationResult:
    """Result of validating an action against a safety policy.

    Attributes:
        valid: Whether the action is valid (passes all policies)
        violations: List of violations detected (may be empty if valid)
        metadata: Additional information about the validation
        policy_name: Name of the policy that produced this result

    Example:
        >>> result = ValidationResult(
        ...     valid=False,
        ...     violations=[
        ...         SafetyViolation(
        ...             policy_name="RateLimit",
        ...             severity=ViolationSeverity.HIGH,
        ...             message="Rate limit exceeded",
        ...             action="api_call",
        ...             context={}
        ...         )
        ...     ],
        ...     metadata={"rate": "10/min", "current": 15},
        ...     policy_name="RateLimit"
        ... )
    """
    valid: bool
    violations: List[SafetyViolation] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    policy_name: str = "unknown"

    def has_critical_violations(self) -> bool:
        """Check if result contains any CRITICAL severity violations."""
        return any(v.severity == ViolationSeverity.CRITICAL for v in self.violations)

    def has_blocking_violations(self) -> bool:
        """Check if result contains violations that should block execution."""
        return any(v.severity >= ViolationSeverity.HIGH for v in self.violations)

    def get_violations_by_severity(self, severity: ViolationSeverity) -> List[SafetyViolation]:
        """Get all violations of a specific severity level."""
        return [v for v in self.violations if v.severity == severity]


class SafetyPolicy(ABC):
    """Abstract base class for all safety policies.

    Safety policies validate actions before execution and report violations.
    Policies can be composed together and executed in priority order.

    Required properties:
        - name: Unique identifier for the policy
        - version: Version string for the policy
        - priority: Execution priority (higher values execute first)

    Required methods:
        - validate(): Synchronous validation
        - validate_async(): Asynchronous validation (optional override)
        - report_violation(): Report violation to observability system

    Example:
        >>> class FileAccessPolicy(SafetyPolicy):
        ...     @property
        ...     def name(self) -> str:
        ...         return "file_access_policy"
        ...
        ...     @property
        ...     def version(self) -> str:
        ...         return "1.0.0"
        ...
        ...     def validate(self, action: Dict, context: Dict) -> ValidationResult:
        ...         # Validation logic here
        ...         return ValidationResult(valid=True)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique policy name for identification and logging.

        Returns:
            Policy name (e.g., "file_access_policy")
        """
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Policy version for tracking changes and compatibility.

        Returns:
            Version string (e.g., "1.0.0", "2.1.3")
        """
        pass

    @property
    def priority(self) -> int:
        """Execution priority for policy ordering.

        Higher priority policies execute first. Use this to ensure
        critical security policies run before optimization policies.

        Returns:
            Priority value (default: 100, range: 0-1000)
        """
        return 100

    @property
    def description(self) -> str:
        """Human-readable description of what the policy enforces.

        Returns:
            Policy description
        """
        return f"Safety policy: {self.name}"

    @abstractmethod
    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against safety policy (synchronous).

        Args:
            action: Action to validate. Structure depends on action type:
                - tool_call: {"tool": "name", "args": {...}}
                - file_operation: {"operation": "read|write", "path": "..."}
                - api_call: {"endpoint": "...", "method": "..."}
            context: Execution context with information about:
                - agent: Agent name/ID
                - stage: Current workflow stage
                - workflow_id: Workflow execution ID
                - permissions: Agent permissions

        Returns:
            ValidationResult with valid flag and any violations detected

        Example:
            >>> result = policy.validate(
            ...     action={"tool": "file_read", "args": {"path": "/tmp/file.txt"}},
            ...     context={"agent": "researcher", "stage": "research"}
            ... )
            >>> if not result.valid:
            ...     print(f"Violations: {result.violations}")
        """
        pass

    async def validate_async(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against safety policy (asynchronous).

        Default implementation calls synchronous validate() method.
        Override for policies that require async operations (e.g., database lookups).

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            ValidationResult
        """
        return self.validate(action, context)

    def report_violation(self, violation: SafetyViolation) -> None:
        """Report violation to observability/logging system.

        Default implementation does nothing. Override to integrate with
        M1 observability, send alerts, or log to external systems.

        Args:
            violation: SafetyViolation to report

        Example:
            >>> violation = SafetyViolation(...)
            >>> policy.report_violation(violation)
        """
        pass


class Validator(ABC):
    """Base interface for specialized validators.

    Validators are reusable components that check specific conditions.
    They can be used by multiple policies to avoid code duplication.

    Example validators:
        - PathValidator: Check if file paths are allowed
        - RateValidator: Check if rate limits are exceeded
        - PatternValidator: Check if content matches forbidden patterns
    """

    @abstractmethod
    def validate(
        self,
        value: Any,
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate a specific value against validator rules.

        Args:
            value: Value to validate
            context: Additional context for validation

        Returns:
            ValidationResult
        """
        pass


# -- LLM Security Protocols --
# These define the boundary between src/security/ and src/safety/.
# Classes in src/security/llm_security.py satisfy these protocols,
# allowing the safety layer to depend on the interface rather than
# the concrete security implementation.


@runtime_checkable
class PromptInjectionDetectorProtocol(Protocol):
    """Protocol for prompt injection / jailbreak detection."""

    def detect(self, prompt: str) -> Tuple[bool, list]:
        """Detect prompt injection attacks.

        Args:
            prompt: User or agent prompt to scan.

        Returns:
            (is_injection, violations) tuple.
        """
        ...


@runtime_checkable
class OutputSanitizerProtocol(Protocol):
    """Protocol for sanitizing LLM output."""

    def sanitize(self, output: str) -> Tuple[str, list]:
        """Sanitize LLM output by removing secrets and dangerous content.

        Args:
            output: Raw LLM output.

        Returns:
            (sanitized_output, violations) tuple.
        """
        ...


@runtime_checkable
class LLMRateLimiterProtocol(Protocol):
    """Protocol for LLM-layer rate limiting."""

    def check_rate_limit(self, entity_id: str) -> Tuple[bool, Optional[str]]:
        """Check whether the entity is within rate limits.

        Args:
            entity_id: Caller identifier (agent id, user id, etc.).

        Returns:
            (allowed, reason) -- reason is None when allowed.
        """
        ...
