"""Safety policy composition layer for combining and executing multiple policies.

This module provides the PolicyComposer class which orchestrates the execution
of multiple safety policies in priority order, aggregates their results, and
provides a unified validation interface.

Key Features:
- Execute multiple policies in priority order (highest first)
- Aggregate validation results from all policies
- Support both sync and async execution
- Configurable failure modes (fail-fast vs fail-safe)
- Violation reporting and observability integration
"""

from dataclasses import dataclass, field
from typing import Any

from temper_ai.safety.interfaces import (
    SafetyPolicy,
    SafetyViolation,
    ValidationResult,
    ViolationSeverity,
)
from temper_ai.shared.core.circuit_breaker import CircuitBreakerError


@dataclass
class CompositeValidationResult:
    """Aggregated result from multiple policy validations.

    Attributes:
        valid: True only if ALL policies passed
        violations: All violations from all policies
        policy_results: Individual results from each policy
        policies_evaluated: Number of policies that were evaluated
        policies_skipped: Number of policies skipped (fail-fast mode)
        execution_order: Order in which policies executed
        metadata: Additional composition metadata
    """

    valid: bool
    violations: list[SafetyViolation] = field(default_factory=list)
    policy_results: dict[str, ValidationResult] = field(default_factory=dict)
    policies_evaluated: int = 0
    policies_skipped: int = 0
    execution_order: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_critical_violations(self) -> bool:
        """Check if any policy reported CRITICAL violations."""
        return any(v.severity == ViolationSeverity.CRITICAL for v in self.violations)

    def has_blocking_violations(self) -> bool:
        """Check if any violations should block execution (HIGH or CRITICAL)."""
        return any(v.severity >= ViolationSeverity.HIGH for v in self.violations)

    def get_violations_by_severity(
        self, severity: ViolationSeverity
    ) -> list[SafetyViolation]:
        """Get all violations of a specific severity."""
        return [v for v in self.violations if v.severity == severity]

    def get_violations_by_policy(self, policy_name: str) -> list[SafetyViolation]:
        """Get all violations from a specific policy."""
        return [v for v in self.violations if v.policy_name == policy_name]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "valid": self.valid,
            "violations": [v.to_dict() for v in self.violations],
            "policies_evaluated": self.policies_evaluated,
            "policies_skipped": self.policies_skipped,
            "execution_order": self.execution_order,
            "metadata": self.metadata,
            "has_critical_violations": self.has_critical_violations(),
            "has_blocking_violations": self.has_blocking_violations(),
        }


class PolicyComposer:
    """Composes multiple safety policies into a unified validation system.

    Executes policies in priority order (highest priority first) and aggregates
    their validation results. Supports both fail-fast (stop on first violation)
    and fail-safe (evaluate all policies) modes.

    Example:
        >>> composer = PolicyComposer()
        >>> composer.add_policy(FileAccessPolicy())
        >>> composer.add_policy(RateLimiterPolicy())
        >>> composer.add_policy(SecretDetectionPolicy())
        >>>
        >>> result = composer.validate(
        ...     action={"tool": "read_file", "path": "/tmp/data.txt"},
        ...     context={"agent": "researcher", "stage": "research"}
        ... )
        >>> if not result.valid:
        ...     for violation in result.violations:
        ...         print(f"{violation.severity.name}: {violation.message}")
    """

    def __init__(
        self,
        policies: list[SafetyPolicy] | None = None,
        fail_fast: bool = False,
        enable_reporting: bool = True,
    ):
        """Initialize policy composer.

        Args:
            policies: Initial list of policies to add
            fail_fast: If True, stop on first violation (default: False)
            enable_reporting: If True, report violations via policy.report_violation()
        """
        self._policies: list[SafetyPolicy] = []
        self.fail_fast = fail_fast
        self.enable_reporting = enable_reporting

        if policies:
            for policy in policies:
                self.add_policy(policy)

    def add_policy(self, policy: SafetyPolicy) -> None:
        """Add a policy to the composition.

        Policies are automatically sorted by priority after adding.

        Args:
            policy: Safety policy to add

        Raises:
            ValueError: If policy with same name already exists
        """
        # Check for duplicate policy names
        if any(p.name == policy.name for p in self._policies):
            raise ValueError(
                f"Policy with name '{policy.name}' already exists. "
                f"Use unique names or remove existing policy first."
            )

        self._policies.append(policy)
        self._sort_policies()

    def remove_policy(self, policy_name: str) -> bool:
        """Remove a policy by name.

        Args:
            policy_name: Name of policy to remove

        Returns:
            True if policy was removed, False if not found
        """
        original_count = len(self._policies)
        self._policies = [p for p in self._policies if p.name != policy_name]
        return len(self._policies) < original_count

    def get_policy(self, policy_name: str) -> SafetyPolicy | None:
        """Get a policy by name.

        Args:
            policy_name: Name of policy to retrieve

        Returns:
            SafetyPolicy if found, None otherwise
        """
        for policy in self._policies:
            if policy.name == policy_name:
                return policy
        return None

    def list_policies(self) -> list[str]:
        """Get list of all policy names in execution order.

        Returns:
            List of policy names (sorted by priority, highest first)
        """
        return [p.name for p in self._policies]

    def _sort_policies(self) -> None:
        """Sort policies by priority (highest first)."""
        self._policies.sort(key=lambda p: p.priority, reverse=True)

    def _handle_policy_result(
        self,
        policy: SafetyPolicy,
        result: ValidationResult,
        all_violations: list[SafetyViolation],
        policy_results: dict[str, ValidationResult],
    ) -> None:
        """Process a successful policy validation result.

        Shared by both sync and async validation paths.
        """
        policy_results[policy.name] = result

        # SA-09: Collect all violations regardless of validity.
        # Valid results can still carry informational/low-severity violations
        # that should not be silently dropped.
        if result.violations:
            all_violations.extend(result.violations)
        if not result.valid and self.enable_reporting:
            for violation in result.violations:
                policy.report_violation(violation)

    def _handle_policy_error(
        self,
        policy: SafetyPolicy,
        error: Exception,
        action: dict[str, Any],
        context: dict[str, Any],
        all_violations: list[SafetyViolation],
        policy_results: dict[str, ValidationResult],
    ) -> None:
        """Process a policy evaluation failure as a CRITICAL violation.

        Shared by both sync and async validation paths.
        """
        violation = SafetyViolation(
            policy_name=policy.name,
            severity=ViolationSeverity.CRITICAL,
            message=f"Policy evaluation failed: {str(error)}",
            action=str(action),
            context=context,
            remediation_hint="Check policy implementation for errors",
            metadata={"exception": str(error), "exception_type": type(error).__name__},
        )
        all_violations.append(violation)

        failed_result = ValidationResult(
            valid=False,
            violations=[violation],
            policy_name=policy.name,
            metadata={"error": str(error)},
        )
        policy_results[policy.name] = failed_result

        if self.enable_reporting:
            policy.report_violation(violation)

    def _build_composite_result(
        self,
        all_violations: list[SafetyViolation],
        policy_results: dict[str, ValidationResult],
        policies_evaluated: int,
        policies_skipped: int,
        execution_order: list[str],
    ) -> CompositeValidationResult:
        """Build the final CompositeValidationResult.

        Shared by both sync and async validation paths.
        """
        return CompositeValidationResult(
            valid=len(all_violations) == 0,
            violations=all_violations,
            policy_results=policy_results,
            policies_evaluated=policies_evaluated,
            policies_skipped=policies_skipped,
            execution_order=execution_order,
            metadata={
                "fail_fast": self.fail_fast,
                "total_policies": len(self._policies),
            },
        )

    def validate(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> CompositeValidationResult:
        """Validate action against all composed policies.

        Executes policies in priority order (highest first). In fail-fast mode,
        stops at first violation. Otherwise evaluates all policies.

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            CompositeValidationResult with aggregated results

        Example:
            >>> result = composer.validate(
            ...     action={"tool": "execute_code", "code": "import os"},
            ...     context={"agent": "coder", "stage": "implementation"}
            ... )
            >>> if result.has_blocking_violations():
            ...     print("Action blocked due to safety violations")
        """
        all_violations: list[SafetyViolation] = []
        policy_results: dict[str, ValidationResult] = {}
        execution_order: list[str] = []
        policies_evaluated = 0
        policies_skipped = 0

        for policy in self._policies:
            execution_order.append(policy.name)

            if self.fail_fast and all_violations:
                policies_skipped += 1
                continue

            try:
                result = policy.validate(action, context)
                policies_evaluated += 1
                self._handle_policy_result(
                    policy, result, all_violations, policy_results
                )
            except (
                AttributeError,
                TypeError,
                ValueError,
                KeyError,
                RuntimeError,
                CircuitBreakerError,
            ) as e:
                policies_evaluated += 1
                self._handle_policy_error(
                    policy, e, action, context, all_violations, policy_results
                )

        return self._build_composite_result(
            all_violations,
            policy_results,
            policies_evaluated,
            policies_skipped,
            execution_order,
        )

    async def validate_async(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> CompositeValidationResult:
        """Validate action against all policies (asynchronous).

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            CompositeValidationResult with aggregated results

        Example:
            >>> result = await composer.validate_async(
            ...     action={"tool": "api_call", "endpoint": "/data"},
            ...     context={"agent": "researcher"}
            ... )
        """
        all_violations: list[SafetyViolation] = []
        policy_results: dict[str, ValidationResult] = {}
        execution_order: list[str] = []
        policies_evaluated = 0
        policies_skipped = 0

        for policy in self._policies:
            execution_order.append(policy.name)

            if self.fail_fast and all_violations:
                policies_skipped += 1
                continue

            try:
                result = await policy.validate_async(action, context)
                policies_evaluated += 1
                self._handle_policy_result(
                    policy, result, all_violations, policy_results
                )
            except (
                AttributeError,
                TypeError,
                ValueError,
                KeyError,
                RuntimeError,
                CircuitBreakerError,
            ) as e:
                policies_evaluated += 1
                self._handle_policy_error(
                    policy, e, action, context, all_violations, policy_results
                )

        return self._build_composite_result(
            all_violations,
            policy_results,
            policies_evaluated,
            policies_skipped,
            execution_order,
        )

    def clear_policies(self) -> None:
        """Remove all policies from the composer."""
        self._policies.clear()

    def policy_count(self) -> int:
        """Get number of policies in the composer."""
        return len(self._policies)

    def __repr__(self) -> str:
        """String representation of the composer."""
        return (
            f"PolicyComposer(policies={len(self._policies)}, "
            f"fail_fast={self.fail_fast}, "
            f"reporting_enabled={self.enable_reporting})"
        )
