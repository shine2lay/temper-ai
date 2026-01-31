"""Base safety policy implementation with composition support.

This module provides the BaseSafetyPolicy class which implements the SafetyPolicy
interface with support for policy composition, priority-based execution, and
short-circuit evaluation on critical violations.
"""
from typing import List, Dict, Any
from src.safety.interfaces import (
    SafetyPolicy,
    ValidationResult,
    SafetyViolation,
    ViolationSeverity
)


class BaseSafetyPolicy(SafetyPolicy):
    """Base implementation of SafetyPolicy with composition support.

    This class provides:
    - Policy composition via add_child_policy()
    - Priority-based execution order
    - Short-circuit evaluation on CRITICAL violations
    - Aggregation of violations from child policies

    Subclasses should override _validate_impl() to provide specific validation logic.

    Attributes:
        config: Configuration dictionary for the policy
        _child_policies: List of child policies (sorted by priority)

    Example:
        >>> class MyPolicy(BaseSafetyPolicy):
        ...     def __init__(self, config: Dict):
        ...         super().__init__(config)
        ...
        ...     @property
        ...     def name(self) -> str:
        ...         return "my_policy"
        ...
        ...     @property
        ...     def version(self) -> str:
        ...         return "1.0.0"
        ...
        ...     def _validate_impl(self, action, context) -> ValidationResult:
        ...         # Custom validation logic
        ...         return ValidationResult(valid=True, policy_name=self.name)
        ...
        >>> policy = MyPolicy({"threshold": 10})
        >>> child = AnotherPolicy({})
        >>> policy.add_child_policy(child)
        >>> result = policy.validate(action={}, context={})
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize base safety policy.

        Args:
            config: Policy configuration dictionary
        """
        self.config = config
        self._child_policies: List[SafetyPolicy] = []

    def add_child_policy(self, policy: SafetyPolicy) -> None:
        """Add a child policy for composition.

        Child policies are executed in priority order (highest first).
        If a child policy produces a CRITICAL violation, execution short-circuits.

        Args:
            policy: SafetyPolicy instance to add as child

        Example:
            >>> parent = MyPolicy({})
            >>> child1 = HighPriorityPolicy({})
            >>> child2 = LowPriorityPolicy({})
            >>> parent.add_child_policy(child1)
            >>> parent.add_child_policy(child2)
            >>> # child1 executes before child2
        """
        self._child_policies.append(policy)
        # Re-sort by priority (highest first)
        self._child_policies.sort(key=lambda p: p.priority, reverse=True)

    def get_child_policies(self) -> List[SafetyPolicy]:
        """Get list of child policies in execution order.

        Returns:
            List of child policies sorted by priority (highest first)
        """
        return self._child_policies.copy()

    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action with child policy composition.

        Execution flow:
        1. Validate with child policies in priority order
        2. Short-circuit if any child produces CRITICAL violation
        3. Run own validation logic via _validate_impl()
        4. Aggregate all violations
        5. Determine validity based on HIGH+ severity violations

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            ValidationResult with aggregated violations

        Example:
            >>> result = policy.validate(
            ...     action={"tool": "file_read", "path": "/etc/passwd"},
            ...     context={"agent": "researcher"}
            ... )
            >>> if not result.valid:
            ...     for violation in result.violations:
            ...         print(f"{violation.severity.name}: {violation.message}")
        """
        violations: List[SafetyViolation] = []
        metadata: Dict[str, Any] = {
            "policy_name": self.name,
            "policy_version": self.version,
            "child_policies": [p.name for p in self._child_policies]
        }

        # Validate with child policies first (higher priority)
        for child in self._child_policies:
            child_result = child.validate(action, context)
            violations.extend(child_result.violations)

            # Merge child metadata (prefix keys to avoid conflicts)
            for key, value in child_result.metadata.items():
                metadata[f"child_{child.name}_{key}"] = value

            # Short-circuit on CRITICAL violations
            if child_result.has_critical_violations():
                metadata["short_circuit"] = True
                metadata["short_circuit_policy"] = child.name
                break

        # Run own validation logic (unless short-circuited)
        if not metadata.get("short_circuit", False):
            own_result = self._validate_impl(action, context)
            violations.extend(own_result.violations)

            # Merge own metadata
            for key, value in own_result.metadata.items():
                if key not in metadata:  # Don't override existing keys
                    metadata[key] = value

        # Determine validity: no HIGH or CRITICAL violations
        valid = not any(v.severity >= ViolationSeverity.HIGH for v in violations)

        # Report violations
        for violation in violations:
            self.report_violation(violation)

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata=metadata,
            policy_name=self.name
        )

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Implementation-specific validation logic.

        Override this method in subclasses to provide custom validation.
        Default implementation returns valid with no violations.

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            ValidationResult

        Example:
            >>> class FilePolicy(BaseSafetyPolicy):
            ...     def _validate_impl(self, action, context):
            ...         if action.get("path", "").startswith("/etc/"):
            ...             return ValidationResult(
            ...                 valid=False,
            ...                 violations=[
            ...                     SafetyViolation(
            ...                         policy_name=self.name,
            ...                         severity=ViolationSeverity.CRITICAL,
            ...                         message="Access to /etc/ forbidden",
            ...                         action=str(action),
            ...                         context=context
            ...                     )
            ...                 ],
            ...                 policy_name=self.name
            ...             )
            ...         return ValidationResult(valid=True, policy_name=self.name)
        """
        return ValidationResult(
            valid=True,
            violations=[],
            metadata={},
            policy_name=self.name
        )

    async def validate_async(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Async validation with child policy composition.

        Calls validate_async() on child policies, then own validation.
        Supports async/await patterns for policies that need async operations.

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            ValidationResult
        """
        violations: List[SafetyViolation] = []
        metadata: Dict[str, Any] = {
            "policy_name": self.name,
            "policy_version": self.version,
            "child_policies": [p.name for p in self._child_policies]
        }

        # Validate with child policies
        for child in self._child_policies:
            child_result = await child.validate_async(action, context)
            violations.extend(child_result.violations)

            for key, value in child_result.metadata.items():
                metadata[f"child_{child.name}_{key}"] = value

            # Short-circuit on CRITICAL
            if child_result.has_critical_violations():
                metadata["short_circuit"] = True
                metadata["short_circuit_policy"] = child.name
                break

        # Run own validation
        if not metadata.get("short_circuit", False):
            own_result = await self._validate_async_impl(action, context)
            violations.extend(own_result.violations)

            for key, value in own_result.metadata.items():
                if key not in metadata:
                    metadata[key] = value

        valid = not any(v.severity >= ViolationSeverity.HIGH for v in violations)

        # Report violations
        for violation in violations:
            self.report_violation(violation)

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata=metadata,
            policy_name=self.name
        )

    async def _validate_async_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Async implementation-specific validation logic.

        Override this method for policies that need async operations.
        Default implementation calls sync _validate_impl().

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            ValidationResult
        """
        return self._validate_impl(action, context)
