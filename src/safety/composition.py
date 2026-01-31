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
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from src.safety.interfaces import (
    SafetyPolicy,
    ValidationResult,
    SafetyViolation,
    ViolationSeverity
)


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
    violations: List[SafetyViolation] = field(default_factory=list)
    policy_results: Dict[str, ValidationResult] = field(default_factory=dict)
    policies_evaluated: int = 0
    policies_skipped: int = 0
    execution_order: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_critical_violations(self) -> bool:
        """Check if any policy reported CRITICAL violations."""
        return any(v.severity == ViolationSeverity.CRITICAL for v in self.violations)

    def has_blocking_violations(self) -> bool:
        """Check if any violations should block execution (HIGH or CRITICAL)."""
        return any(v.severity >= ViolationSeverity.HIGH for v in self.violations)

    def get_violations_by_severity(self, severity: ViolationSeverity) -> List[SafetyViolation]:
        """Get all violations of a specific severity."""
        return [v for v in self.violations if v.severity == severity]

    def get_violations_by_policy(self, policy_name: str) -> List[SafetyViolation]:
        """Get all violations from a specific policy."""
        return [v for v in self.violations if v.policy_name == policy_name]

    def to_dict(self) -> Dict[str, Any]:
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
        policies: Optional[List[SafetyPolicy]] = None,
        fail_fast: bool = False,
        enable_reporting: bool = True
    ):
        """Initialize policy composer.

        Args:
            policies: Initial list of policies to add
            fail_fast: If True, stop on first violation (default: False)
            enable_reporting: If True, report violations via policy.report_violation()
        """
        self._policies: List[SafetyPolicy] = []
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

    def get_policy(self, policy_name: str) -> Optional[SafetyPolicy]:
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

    def list_policies(self) -> List[str]:
        """Get list of all policy names in execution order.

        Returns:
            List of policy names (sorted by priority, highest first)
        """
        return [p.name for p in self._policies]

    def _sort_policies(self) -> None:
        """Sort policies by priority (highest first)."""
        self._policies.sort(key=lambda p: p.priority, reverse=True)

    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
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
        all_violations: List[SafetyViolation] = []
        policy_results: Dict[str, ValidationResult] = {}
        execution_order: List[str] = []
        policies_evaluated = 0
        policies_skipped = 0

        for policy in self._policies:
            execution_order.append(policy.name)

            # In fail-fast mode, skip remaining policies if we already have violations
            if self.fail_fast and all_violations:
                policies_skipped += 1
                continue

            # Execute policy validation
            try:
                result = policy.validate(action, context)
                policies_evaluated += 1
                policy_results[policy.name] = result

                # Collect violations
                if not result.valid:
                    all_violations.extend(result.violations)

                    # Report violations if enabled
                    if self.enable_reporting:
                        for violation in result.violations:
                            policy.report_violation(violation)

            except Exception as e:
                # Policy evaluation failed - treat as CRITICAL violation
                violation = SafetyViolation(
                    policy_name=policy.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Policy evaluation failed: {str(e)}",
                    action=str(action),
                    context=context,
                    remediation_hint="Check policy implementation for errors",
                    metadata={"exception": str(e), "exception_type": type(e).__name__}
                )
                all_violations.append(violation)

                # Create failed result
                failed_result = ValidationResult(
                    valid=False,
                    violations=[violation],
                    policy_name=policy.name,
                    metadata={"error": str(e)}
                )
                policy_results[policy.name] = failed_result
                policies_evaluated += 1

                # Report exception-based violation
                if self.enable_reporting:
                    policy.report_violation(violation)

        # Determine overall validity
        overall_valid = len(all_violations) == 0

        return CompositeValidationResult(
            valid=overall_valid,
            violations=all_violations,
            policy_results=policy_results,
            policies_evaluated=policies_evaluated,
            policies_skipped=policies_skipped,
            execution_order=execution_order,
            metadata={
                "fail_fast": self.fail_fast,
                "total_policies": len(self._policies)
            }
        )

    async def validate_async(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
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
        all_violations: List[SafetyViolation] = []
        policy_results: Dict[str, ValidationResult] = {}
        execution_order: List[str] = []
        policies_evaluated = 0
        policies_skipped = 0

        for policy in self._policies:
            execution_order.append(policy.name)

            # In fail-fast mode, skip remaining policies if we already have violations
            if self.fail_fast and all_violations:
                policies_skipped += 1
                continue

            # Execute policy validation (async)
            try:
                result = await policy.validate_async(action, context)
                policies_evaluated += 1
                policy_results[policy.name] = result

                # Collect violations
                if not result.valid:
                    all_violations.extend(result.violations)

                    # Report violations if enabled
                    if self.enable_reporting:
                        for violation in result.violations:
                            policy.report_violation(violation)

            except Exception as e:
                # Policy evaluation failed - treat as CRITICAL violation
                violation = SafetyViolation(
                    policy_name=policy.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Policy evaluation failed: {str(e)}",
                    action=str(action),
                    context=context,
                    remediation_hint="Check policy implementation for errors",
                    metadata={"exception": str(e), "exception_type": type(e).__name__}
                )
                all_violations.append(violation)

                # Create failed result
                failed_result = ValidationResult(
                    valid=False,
                    violations=[violation],
                    policy_name=policy.name,
                    metadata={"error": str(e)}
                )
                policy_results[policy.name] = failed_result
                policies_evaluated += 1

                # Report exception-based violation
                if self.enable_reporting:
                    policy.report_violation(violation)

        # Determine overall validity
        overall_valid = len(all_violations) == 0

        return CompositeValidationResult(
            valid=overall_valid,
            violations=all_violations,
            policy_results=policy_results,
            policies_evaluated=policies_evaluated,
            policies_skipped=policies_skipped,
            execution_order=execution_order,
            metadata={
                "fail_fast": self.fail_fast,
                "total_policies": len(self._policies)
            }
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
