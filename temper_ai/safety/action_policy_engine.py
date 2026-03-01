"""Action Policy Engine - Central enforcement layer for safety policies.

This module provides the ActionPolicyEngine class which validates agent actions
against all applicable safety policies before execution. It supports:
- Pre-execution validation
- Policy caching for performance
- Async policy execution
- Short-circuit on CRITICAL violations
- Observability integration

Example:
    >>> from temper_ai.safety.action_policy_engine import ActionPolicyEngine
    >>> from temper_ai.safety.policy_registry import PolicyRegistry
    >>>
    >>> registry = PolicyRegistry()
    >>> engine = ActionPolicyEngine(registry, config={})
    >>>
    >>> result = await engine.validate_action(
    ...     action={"type": "file_write", "path": "/tmp/file.txt"},
    ...     context=PolicyExecutionContext(...)
    ... )
    >>> if not result.allowed:
    ...     print(f"Action blocked: {result.violations[0].message}")
"""

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from temper_ai.safety._action_policy_helpers import (
    cache_result as _cache_result_helper,
)
from temper_ai.safety._action_policy_helpers import (
    context_to_dict,
    get_cache_key,
    get_cached_result,
    get_policy_snapshot,
)
from temper_ai.safety.constants import (
    CACHE_HITS_KEY,
    FAIL_OPEN_KEY,
    MODE_KEY,
    NO_POLICIES_REGISTERED_KEY,
    REASON_KEY,
)
from temper_ai.safety.interfaces import (
    SafetyPolicy,
    SafetyViolation,
    ValidationResult,
    ViolationSeverity,
)
from temper_ai.safety.policy_registry import PolicyRegistry
from temper_ai.shared.constants.durations import MILLISECONDS_PER_SECOND, TTL_LONG
from temper_ai.shared.constants.limits import THRESHOLD_MEDIUM_COUNT
from temper_ai.shared.core.circuit_breaker import CircuitBreakerError

logger = logging.getLogger(__name__)


@dataclass
class PolicyExecutionContext:
    """Context for policy execution.

    Provides execution context information to policies during validation.

    Attributes:
        agent_id: Unique identifier for the agent
        workflow_id: Workflow execution ID
        stage_id: Current workflow stage
        action_type: Type of action (file_write, git_commit, etc.)
        action_data: Action-specific data
        metadata: Additional context metadata
    """

    agent_id: str
    workflow_id: str
    stage_id: str
    action_type: str
    action_data: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnforcementResult:
    """Result of policy enforcement.

    Attributes:
        allowed: Whether action is allowed (True) or blocked (False)
        violations: List of all violations detected
        policies_executed: Names of policies that were executed
        execution_time_ms: Total validation time in milliseconds
        metadata: Additional result metadata
        cache_hit: Whether result was retrieved from cache
    """

    allowed: bool
    violations: list[SafetyViolation]
    policies_executed: list[str]
    execution_time_ms: float
    metadata: dict[str, Any]
    cache_hit: bool = False

    def has_critical_violations(self) -> bool:
        """Check if any CRITICAL violations detected."""
        return any(v.severity == ViolationSeverity.CRITICAL for v in self.violations)

    def has_blocking_violations(self) -> bool:
        """Check if any blocking (HIGH or CRITICAL) violations detected."""
        return any(v.severity >= ViolationSeverity.HIGH for v in self.violations)


def _should_short_circuit_on_critical(
    short_circuit_critical: bool,
    violations: list[SafetyViolation],
) -> bool:
    """Check if we should short-circuit on CRITICAL violations."""
    return short_circuit_critical and any(
        v.severity == ViolationSeverity.CRITICAL for v in violations
    )


async def _run_policy_async_cached(  # noqa: params  # noqa: god
    policy: "SafetyPolicy",
    action: dict[str, Any],
    context_dict: dict[str, Any],
    cache_key: str,
    cache: Any,
    cache_ttl: float,
    max_cache_size: int,
    enable_caching: bool,
) -> "tuple[Any, int, int]":
    """Run one policy async with cache.  Returns (result, hit, miss)."""
    if enable_caching:
        cached = get_cached_result(cache, cache_key, cache_ttl)
        if cached is not None:
            return cached, 1, 0
    result = await policy.validate_async(action=action, context=context_dict)
    if enable_caching:
        _cache_result_helper(cache, cache_key, result, max_cache_size)
        return result, 0, 1
    return result, 0, 0


class ActionPolicyEngine:  # noqa: god
    """Central policy enforcement engine.

    Validates agent actions against all applicable safety policies. Provides:
    - Policy execution in priority order
    - Result caching for performance
    - Short-circuit on CRITICAL violations
    - Async policy execution
    - Observability integration
    """

    def __init__(
        self,
        policy_registry: PolicyRegistry,
        config: dict[str, Any] | None = None,
        emergency_stop: Any | None = None,
    ):
        """Initialize action policy engine.

        Args:
            policy_registry: PolicyRegistry instance with registered policies
            config: Engine configuration:
                - cache_ttl: Cache TTL in seconds (default: 60)
                - max_cache_size: Maximum cached results (default: 1000)
                - enable_caching: Enable result caching (default: True)
                - short_circuit_critical: Stop on CRITICAL violations (default: True)
                - log_violations: Log violations to observability (default: True)
            emergency_stop: Optional EmergencyStopController for progressive autonomy.
        """
        self.registry = policy_registry
        self.config = config or {}
        self._emergency_stop = emergency_stop

        # Configuration
        self.cache_ttl = self.config.get("cache_ttl", TTL_LONG)
        self.max_cache_size = self.config.get("max_cache_size", THRESHOLD_MEDIUM_COUNT)
        self.enable_caching = self.config.get("enable_caching", True)
        self.short_circuit_critical = self.config.get("short_circuit_critical", True)
        self.log_violations = self.config.get("log_violations", True)
        # SECURITY: Default to fail-closed when no policies match.
        # Set fail_open=True only for development/testing.
        self.fail_open = self.config.get("fail_open", False)

        # Policy result cache: cache_key -> (result, timestamp)
        self._cache: OrderedDict[str, tuple[ValidationResult, float]] = OrderedDict()

        # SECURITY: Initialize sanitizer for defense-in-depth violation message sanitization
        # Lazy loaded to avoid import overhead if sanitization is not needed
        self._sanitizer: Any | None = None

        # Metrics
        self._validations_performed = 0
        self._violations_logged = 0
        self._cache_hits = 0
        self._cache_misses = 0

        # SA-06: Track policy snapshot for cache invalidation.
        # When policies change in the registry, cached results may be stale.
        self._cached_policy_snapshot: str | None = None

    async def validate_action(
        self, action: dict[str, Any], context: PolicyExecutionContext
    ) -> EnforcementResult:
        """Validate action against all applicable policies.

        Executes policies in priority order (highest first). Short-circuits
        on CRITICAL violations if configured.

        Args:
            action: Action to validate (type, parameters, command, etc.)
            context: Execution context (agent, workflow, stage, metadata)

        Returns:
            EnforcementResult with allowed flag and any violations

        Example:
            >>> result = await engine.validate_action(
            ...     action={"command": "rm -rf /"},
            ...     context=context
            ... )
            >>> assert not result.allowed
            >>> assert result.has_critical_violations()
        """
        start_time = time.time()

        # Emergency stop: block all actions immediately
        if self._emergency_stop is not None and self._emergency_stop.is_active():
            return EnforcementResult(
                allowed=False,
                violations=[],
                policies_executed=[],
                execution_time_ms=0.0,
                metadata={"reason": "emergency_stop_active"},
            )

        # SA-06: Invalidate cache when the set of registered policies changes.
        self._invalidate_cache_if_policies_changed()

        # Get applicable policies for this action type
        policies = self.registry.get_policies_for_action(context.action_type)

        # Handle no policies case
        if not policies:
            no_policies_result = self._handle_no_policies(context.action_type)
            if no_policies_result:
                return no_policies_result

        # Execute all policies and collect violations
        all_violations, policies_executed, cache_hits = (
            await self._execute_policies_async(policies, action, context)
        )

        # Build and return final result
        return self._build_enforcement_result(
            all_violations, policies_executed, cache_hits, start_time, context
        )

    def _handle_no_policies(self, action_type: str) -> EnforcementResult | None:
        """Handle case when no policies are registered for action type.

        Args:
            action_type: Type of action being validated

        Returns:
            EnforcementResult if no policies found, None to continue validation
        """
        if self.fail_open:
            # Explicit opt-in: allow when no policies registered (dev/test only)
            return EnforcementResult(
                allowed=True,
                violations=[],
                policies_executed=[],
                execution_time_ms=0.0,  # noqa: long
                metadata={
                    REASON_KEY: NO_POLICIES_REGISTERED_KEY,
                    MODE_KEY: FAIL_OPEN_KEY,
                },
                cache_hit=False,
            )
        # SECURITY: Fail-closed — deny action when no policies can validate it
        logger.warning(
            "No policies registered for action type '%s' — denying action (fail-closed). "
            "Register policies or set fail_open=True for development.",
            action_type,
        )
        return EnforcementResult(
            allowed=False,
            violations=[],
            policies_executed=[],
            execution_time_ms=0.0,
            metadata={REASON_KEY: NO_POLICIES_REGISTERED_KEY, MODE_KEY: "fail_closed"},
            cache_hit=False,
        )

    async def _execute_policies_async(
        self,
        policies: list[SafetyPolicy],
        action: dict[str, Any],
        context: PolicyExecutionContext,
    ) -> tuple[list[SafetyViolation], list[str], int]:
        """Execute all policies async, collecting violations and cache hits."""
        all_violations: list[SafetyViolation] = []
        policies_executed: list[str] = []
        cache_hits = 0

        for policy in policies:
            try:
                cache_key = self._get_cache_key(policy, action, context)
                result, hit, miss = await _run_policy_async_cached(
                    policy,
                    action,
                    self._context_to_dict(context),
                    cache_key,
                    self._cache,
                    self.cache_ttl,
                    self.max_cache_size,
                    self.enable_caching,
                )
                self._cache_hits += hit
                self._cache_misses += miss
                cache_hits += hit
                policies_executed.append(policy.name)
                all_violations.extend(result.violations)
                if _should_short_circuit_on_critical(
                    self.short_circuit_critical, result.violations
                ):
                    logger.warning(
                        f"Short-circuiting on CRITICAL violation from {policy.name}"
                    )
                    break
            except (
                AttributeError,
                TypeError,
                ValueError,
                KeyError,
                RuntimeError,
                CircuitBreakerError,
            ) as e:
                all_violations.append(
                    self._create_execution_error_violation(policy, action, context, e)
                )
                policies_executed.append(policy.name)

        if self.log_violations and all_violations:
            await self._log_violations(all_violations, context)

        return all_violations, policies_executed, cache_hits

    def _create_execution_error_violation(
        self,
        policy: SafetyPolicy,
        action: dict[str, Any],
        context: PolicyExecutionContext,
        error: Exception,
    ) -> SafetyViolation:
        """Create a violation for policy execution errors.

        Args:
            policy: Policy that failed
            action: Action being validated
            context: Execution context
            error: Exception that occurred

        Returns:
            SafetyViolation representing the error
        """
        logger.error(f"Policy {policy.name} execution failed: {error}", exc_info=True)

        # SECURITY (SA-03): Use generic message to prevent info leakage
        return SafetyViolation(
            policy_name=policy.name,
            severity=ViolationSeverity.CRITICAL,
            message=f"Policy execution error in {policy.name}",
            action=str(action),
            context=self._context_to_dict(context),
            remediation_hint="Check policy implementation for errors",
            metadata={"exception_type": type(error).__name__},
        )

    def _build_enforcement_result(
        self,
        all_violations: list[SafetyViolation],
        policies_executed: list[str],
        cache_hits: int,
        start_time: float,
        context: PolicyExecutionContext,
    ) -> EnforcementResult:
        """Build final enforcement result from collected violations."""
        # Determine if action is allowed (block if any HIGH or CRITICAL)
        allowed = not any(v.severity >= ViolationSeverity.HIGH for v in all_violations)

        execution_time = (time.time() - start_time) * MILLISECONDS_PER_SECOND
        self._validations_performed += 1

        return EnforcementResult(
            allowed=allowed,
            violations=all_violations,
            policies_executed=policies_executed,
            execution_time_ms=execution_time,
            metadata={
                "total_violations": len(all_violations),
                "critical_violations": len(
                    [
                        v
                        for v in all_violations
                        if v.severity == ViolationSeverity.CRITICAL
                    ]
                ),
                "high_violations": len(
                    [v for v in all_violations if v.severity == ViolationSeverity.HIGH]
                ),
                "medium_violations": len(
                    [
                        v
                        for v in all_violations
                        if v.severity == ViolationSeverity.MEDIUM
                    ]
                ),
                CACHE_HITS_KEY: cache_hits,
                "short_circuited": self.short_circuit_critical
                and any(
                    v.severity == ViolationSeverity.CRITICAL for v in all_violations
                ),
            },
            cache_hit=cache_hits > 0,
        )

    def validate_action_sync(
        self, action: dict[str, Any], context: PolicyExecutionContext
    ) -> EnforcementResult:
        """Synchronous version of validate_action for non-async callers.

        Mirrors validate_action but uses policy.validate() instead of
        policy.validate_async(). Safe to call from synchronous contexts
        (e.g., StandardAgent._execute_iteration).
        """
        start_time = time.time()

        # Emergency stop: block all actions immediately
        if self._emergency_stop is not None and self._emergency_stop.is_active():
            return EnforcementResult(
                allowed=False,
                violations=[],
                policies_executed=[],
                execution_time_ms=0.0,
                metadata={"reason": "emergency_stop_active"},
            )

        self._invalidate_cache_if_policies_changed()

        policies = self.registry.get_policies_for_action(context.action_type)

        # Handle no policies case
        if not policies:
            no_policies_result = self._handle_no_policies(context.action_type)
            if no_policies_result:
                return no_policies_result

        # Execute all policies and collect violations
        all_violations, policies_executed, cache_hits = self._execute_policies_sync(
            policies, action, context
        )

        # Build and return final result
        return self._build_enforcement_result(
            all_violations, policies_executed, cache_hits, start_time, context
        )

    def _execute_policies_sync(  # noqa: long
        self,
        policies: list[SafetyPolicy],
        action: dict[str, Any],
        context: PolicyExecutionContext,
    ) -> tuple[list[SafetyViolation], list[str], int]:
        """Execute all policies synchronously and collect violations.

        Args:
            policies: List of policies to execute
            action: Action to validate
            context: Execution context  # noqa: long

        Returns:
            Tuple of (all_violations, policies_executed, cache_hits)
        """
        all_violations: list[SafetyViolation] = []
        policies_executed: list[str] = []
        cache_hits = 0

        for policy in policies:
            try:
                cache_key = self._get_cache_key(policy, action, context)
                cached_result = (
                    self._get_cached_result(cache_key) if self.enable_caching else None
                )

                if cached_result is not None:
                    result = cached_result
                    cache_hits += 1
                    self._cache_hits += 1
                else:
                    result = policy.validate(
                        action=action, context=self._context_to_dict(context)
                    )
                    if self.enable_caching:
                        self._cache_result(cache_key, result)
                        self._cache_misses += 1

                policies_executed.append(policy.name)
                all_violations.extend(result.violations)

                # Short-circuit on CRITICAL violations (if configured)
                if _should_short_circuit_on_critical(
                    self.short_circuit_critical, result.violations
                ):
                    logger.warning(
                        f"Short-circuiting on CRITICAL violation from {policy.name}"
                    )
                    break

            except (
                AttributeError,
                TypeError,
                ValueError,
                KeyError,
                RuntimeError,
                CircuitBreakerError,
            ) as e:
                violation = self._create_execution_error_violation(
                    policy, action, context, e
                )
                all_violations.append(violation)
                policies_executed.append(policy.name)

        # Log violations to observability (if enabled)
        if self.log_violations and all_violations:
            self._log_violations_sync(all_violations, context)

        return all_violations, policies_executed, cache_hits

    def _log_violations_sync(
        self, violations: list[SafetyViolation], context: PolicyExecutionContext
    ) -> None:
        """Synchronous version of _log_violations."""
        from temper_ai.safety._action_policy_helpers import log_violations_sync

        if self._sanitizer is None:
            from temper_ai.observability.sanitization import DataSanitizer

            self._sanitizer = DataSanitizer()
        log_violations_sync(violations, context, self._sanitizer)

    def _get_cache_key(
        self,
        policy: SafetyPolicy,
        action: dict[str, Any],
        context: PolicyExecutionContext,
    ) -> str:
        """Generate cache key for policy result."""
        return get_cache_key(
            policy,
            action,
            context.agent_id,
            context.action_type,
            context.workflow_id,
            context.stage_id,
        )

    def _get_cached_result(self, cache_key: str) -> ValidationResult | None:
        """Get cached validation result if available and not expired."""
        return get_cached_result(self._cache, cache_key, self.cache_ttl)

    def _cache_result(self, cache_key: str, result: ValidationResult) -> None:
        """Cache validation result with timestamp."""
        _cache_result_helper(self._cache, cache_key, result, self.max_cache_size)

    def _invalidate_cache_if_policies_changed(self) -> None:
        """SA-06: Clear cache when registered policies change."""
        snapshot = get_policy_snapshot(self.registry)
        if self._cached_policy_snapshot is None:
            self._cached_policy_snapshot = snapshot
        elif snapshot != self._cached_policy_snapshot:
            logger.debug("Policy registration changed; clearing validation cache")
            self._cache.clear()
            self._cached_policy_snapshot = snapshot

    def clear_cache(self) -> None:
        """Explicitly clear the validation result cache."""
        self._cache.clear()
        self._cached_policy_snapshot = None
        logger.debug("Validation cache cleared")

    def _context_to_dict(self, context: PolicyExecutionContext) -> dict[str, Any]:
        """Convert PolicyExecutionContext to dict for policy validation."""
        return context_to_dict(context)

    async def _log_violations(
        self, violations: list[SafetyViolation], context: PolicyExecutionContext
    ) -> None:
        """Log violations to observability system."""
        from temper_ai.safety._action_policy_helpers import log_violations

        if self._sanitizer is None:
            from temper_ai.observability.sanitization import DataSanitizer

            self._sanitizer = DataSanitizer()
        await log_violations(violations, context, self._sanitizer)
        self._violations_logged += len(violations)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"ActionPolicyEngine("
            f"policies={self.registry.policy_count()}, "
            f"cache_size={len(self._cache)}, "
            f"validations={self._validations_performed})"
        )
