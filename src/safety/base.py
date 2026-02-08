"""Base safety policy implementation with composition support.

This module provides the BaseSafetyPolicy class which implements the SafetyPolicy
interface with support for policy composition, priority-based execution, and
short-circuit evaluation on critical violations.
"""
from typing import Any, Dict, List

from src.constants.limits import MAX_TEXT_LENGTH, THRESHOLD_LARGE_COUNT, THRESHOLD_VERY_LARGE_COUNT
from src.safety.interfaces import SafetyPolicy, SafetyViolation, ValidationResult, ViolationSeverity


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
        """Initialize base safety policy with validation.

        Args:
            config: Policy configuration dictionary

        Raises:
            ValueError: If config contains invalid values
        """
        # SECURITY (code-high-12): Validate config is a dictionary
        if not isinstance(config, dict):
            raise ValueError(
                f"config must be a dictionary, got {type(config).__name__}"
            )

        # SECURITY: Validate config size to prevent DoS
        if len(config) > THRESHOLD_LARGE_COUNT:
            raise ValueError(
                f"config exceeds maximum size of {THRESHOLD_LARGE_COUNT} keys, got {len(config)}"
            )

        # SECURITY: Validate all keys and values (prevent injection and DoS)
        self._validate_config_dict(config, depth=0)

        # Store validated config
        self.config = config
        self._child_policies: List[SafetyPolicy] = []

    # Maximum nesting depth for config dicts (prevents DoS via deeply nested structures)
    _MAX_CONFIG_DEPTH = 4

    @classmethod
    def _validate_config_dict(cls, d: dict, depth: int) -> None:
        """Recursively validate a config dictionary.

        Validates keys are strings, values are safe types, collections are
        bounded, and nesting depth is limited to prevent DoS.

        Args:
            d: Dictionary to validate.
            depth: Current nesting depth (0 = top level).

        Raises:
            ValueError: If any validation check fails.
        """
        if depth > cls._MAX_CONFIG_DEPTH:
            raise ValueError(
                f"config nesting depth exceeds maximum of {cls._MAX_CONFIG_DEPTH}"
            )

        for key, value in d.items():
            # Validate key
            if not isinstance(key, str):
                raise ValueError(
                    f"config keys must be strings, got {type(key).__name__}: {key}"
                )
            if len(key) > THRESHOLD_LARGE_COUNT:
                raise ValueError(
                    f"config key exceeds {THRESHOLD_LARGE_COUNT} characters: {key[:20]}..."
                )

            # SECURITY: Recursively validate nested dicts (depth-bounded)
            if isinstance(value, dict):
                if len(value) > THRESHOLD_LARGE_COUNT:
                    raise ValueError(
                        f"config nested dict exceeds maximum size of {THRESHOLD_LARGE_COUNT} keys "
                        f"for key '{key}'"
                    )
                cls._validate_config_dict(value, depth + 1)

            # SECURITY: Validate collection sizes
            elif isinstance(value, (list, tuple, set)):
                if len(value) > THRESHOLD_VERY_LARGE_COUNT:
                    raise ValueError(
                        f"config list/tuple/set must have <= {THRESHOLD_VERY_LARGE_COUNT} items, "
                        f"got {len(value)} for key '{key}'"
                    )

            # SECURITY: Validate string lengths
            elif isinstance(value, str):
                if len(value) > MAX_TEXT_LENGTH:
                    raise ValueError(
                        f"config string must be <= {MAX_TEXT_LENGTH:,} chars, "
                        f"got {len(value)} for key '{key}'"
                    )

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

    def _init_validation_metadata(self) -> Dict[str, Any]:
        """Create initial metadata dict for validation. Shared by sync/async."""
        return {
            "policy_name": self.name,
            "policy_version": self.version,
            "child_policies": [p.name for p in self._child_policies]
        }

    def _merge_child_result(
        self,
        child: SafetyPolicy,
        child_result: ValidationResult,
        violations: List[SafetyViolation],
        metadata: Dict[str, Any],
    ) -> bool:
        """Merge a child policy result into the accumulated state.

        Returns True if short-circuiting should occur (CRITICAL violation).
        Shared by sync and async validation paths.
        """
        violations.extend(child_result.violations)

        for key, value in child_result.metadata.items():
            metadata[f"child_{child.name}_{key}"] = value

        if child_result.has_critical_violations():
            metadata["short_circuit"] = True
            metadata["short_circuit_policy"] = child.name
            return True
        return False

    def _merge_own_result(
        self,
        own_result: ValidationResult,
        violations: List[SafetyViolation],
        metadata: Dict[str, Any],
    ) -> None:
        """Merge own validation result into accumulated state. Shared by sync/async."""
        violations.extend(own_result.violations)
        for key, value in own_result.metadata.items():
            if key not in metadata:
                metadata[key] = value

    def _finalize_validation(
        self,
        violations: List[SafetyViolation],
        metadata: Dict[str, Any],
    ) -> ValidationResult:
        """Determine validity, report violations, and return result. Shared by sync/async."""
        valid = not any(v.severity >= ViolationSeverity.HIGH for v in violations)

        for violation in violations:
            self.report_violation(violation)

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata=metadata,
            policy_name=self.name
        )

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
        metadata = self._init_validation_metadata()

        for child in self._child_policies:
            child_result = child.validate(action, context)
            if self._merge_child_result(child, child_result, violations, metadata):
                break

        if not metadata.get("short_circuit", False):
            own_result = self._validate_impl(action, context)
            self._merge_own_result(own_result, violations, metadata)

        return self._finalize_validation(violations, metadata)

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
        metadata = self._init_validation_metadata()

        for child in self._child_policies:
            child_result = await child.validate_async(action, context)
            if self._merge_child_result(child, child_result, violations, metadata):
                break

        if not metadata.get("short_circuit", False):
            own_result = await self._validate_async_impl(action, context)
            self._merge_own_result(own_result, violations, metadata)

        return self._finalize_validation(violations, metadata)

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
