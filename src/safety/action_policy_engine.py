"""Action Policy Engine - Central enforcement layer for safety policies.

This module provides the ActionPolicyEngine class which validates agent actions
against all applicable safety policies before execution. It supports:
- Pre-execution validation
- Policy caching for performance
- Async policy execution
- Short-circuit on CRITICAL violations
- Observability integration

Example:
    >>> from src.safety.action_policy_engine import ActionPolicyEngine
    >>> from src.safety.policy_registry import PolicyRegistry
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
import asyncio
import time
import hashlib
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, UTC

from src.safety.interfaces import SafetyPolicy, ValidationResult, SafetyViolation, ViolationSeverity
from src.safety.policy_registry import PolicyRegistry


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
    action_data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


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
    violations: List[SafetyViolation]
    policies_executed: List[str]
    execution_time_ms: float
    metadata: Dict[str, Any]
    cache_hit: bool = False

    def has_critical_violations(self) -> bool:
        """Check if any CRITICAL violations detected."""
        return any(v.severity == ViolationSeverity.CRITICAL for v in self.violations)

    def has_blocking_violations(self) -> bool:
        """Check if any blocking (HIGH or CRITICAL) violations detected."""
        return any(v.severity >= ViolationSeverity.HIGH for v in self.violations)

    def get_violations_by_severity(self, severity: ViolationSeverity) -> List[SafetyViolation]:
        """Get violations of specific severity."""
        return [v for v in self.violations if v.severity == severity]


class ActionPolicyEngine:
    """Central policy enforcement engine.

    Validates agent actions against all applicable safety policies. Provides:
    - Policy execution in priority order
    - Result caching for performance
    - Short-circuit on CRITICAL violations
    - Async policy execution
    - Observability integration

    Example:
        >>> engine = ActionPolicyEngine(registry, config={"cache_ttl": 60})
        >>>
        >>> context = PolicyExecutionContext(
        ...     agent_id="agent-123",
        ...     workflow_id="wf-456",
        ...     stage_id="research",
        ...     action_type="file_write",
        ...     action_data={"path": "/tmp/file.txt"}
        ... )
        >>>
        >>> result = await engine.validate_action(
        ...     action={"command": "cat > file.txt"},
        ...     context=context
        ... )
        >>> if not result.allowed:
        ...     raise ValueError(f"Action blocked: {result.violations}")
    """

    def __init__(
        self,
        policy_registry: PolicyRegistry,
        config: Optional[Dict[str, Any]] = None
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
        """
        self.registry = policy_registry
        self.config = config or {}

        # Configuration
        self.cache_ttl = self.config.get('cache_ttl', 60)  # 60 seconds
        self.max_cache_size = self.config.get('max_cache_size', 1000)
        self.enable_caching = self.config.get('enable_caching', True)
        self.short_circuit_critical = self.config.get('short_circuit_critical', True)
        self.log_violations = self.config.get('log_violations', True)

        # Policy result cache: cache_key -> (result, timestamp)
        self._cache: Dict[str, Tuple[ValidationResult, float]] = {}

        # Metrics
        self._validations_performed = 0
        self._violations_logged = 0
        self._cache_hits = 0
        self._cache_misses = 0

    async def validate_action(
        self,
        action: Dict[str, Any],
        context: PolicyExecutionContext
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

        # Get applicable policies for this action type
        policies = self.registry.get_policies_for_action(context.action_type)

        if not policies:
            # No policies for this action type - allow by default
            return EnforcementResult(
                allowed=True,
                violations=[],
                policies_executed=[],
                execution_time_ms=0.0,
                metadata={'reason': 'no_policies_registered'},
                cache_hit=False
            )

        # Execute policies in priority order
        all_violations: List[SafetyViolation] = []
        policies_executed: List[str] = []
        cache_hits = 0

        for policy in policies:
            try:
                # Check cache first (if enabled)
                cache_key = self._get_cache_key(policy, action, context)
                cached_result = self._get_cached_result(cache_key) if self.enable_caching else None

                if cached_result is not None:
                    result = cached_result
                    cache_hits += 1
                    self._cache_hits += 1
                else:
                    # Execute policy validation
                    result = await policy.validate_async(
                        action=action,
                        context=self._context_to_dict(context)
                    )

                    # Cache result (if enabled)
                    if self.enable_caching:
                        self._cache_result(cache_key, result)
                        self._cache_misses += 1

                policies_executed.append(policy.name)
                all_violations.extend(result.violations)

                # Short-circuit on CRITICAL violations (if configured)
                if self.short_circuit_critical:
                    if any(v.severity == ViolationSeverity.CRITICAL for v in result.violations):
                        logger.warning(
                            f"Short-circuiting on CRITICAL violation from {policy.name}"
                        )
                        break

            except Exception as e:
                # Policy execution error - log and treat as violation for safety
                logger.error(f"Policy {policy.name} execution failed: {e}", exc_info=True)

                violation = SafetyViolation(
                    policy_name=policy.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Policy execution error: {str(e)}",
                    action=str(action),
                    context=self._context_to_dict(context),
                    remediation_hint="Check policy implementation for errors",
                    metadata={'exception': str(e), 'exception_type': type(e).__name__}
                )
                all_violations.append(violation)
                policies_executed.append(policy.name)

        # Determine if action is allowed
        # Block if any HIGH or CRITICAL severity violations
        blocking_violations = [
            v for v in all_violations
            if v.severity >= ViolationSeverity.HIGH
        ]
        allowed = len(blocking_violations) == 0

        # Log violations to observability (if enabled)
        if self.log_violations and all_violations:
            await self._log_violations(all_violations, context)

        execution_time = (time.time() - start_time) * 1000  # ms
        self._validations_performed += 1

        return EnforcementResult(
            allowed=allowed,
            violations=all_violations,
            policies_executed=policies_executed,
            execution_time_ms=execution_time,
            metadata={
                'total_violations': len(all_violations),
                'critical_violations': len([v for v in all_violations if v.severity == ViolationSeverity.CRITICAL]),
                'high_violations': len([v for v in all_violations if v.severity == ViolationSeverity.HIGH]),
                'medium_violations': len([v for v in all_violations if v.severity == ViolationSeverity.MEDIUM]),
                'cache_hits': cache_hits,
                'short_circuited': self.short_circuit_critical and any(
                    v.severity == ViolationSeverity.CRITICAL for v in all_violations
                )
            },
            cache_hit=cache_hits > 0
        )

    def _get_cache_key(
        self,
        policy: SafetyPolicy,
        action: Dict[str, Any],
        context: PolicyExecutionContext
    ) -> str:
        """Generate cache key for policy result.

        Creates deterministic hash of policy + action + context.
        """
        # Create deterministic representation
        data = {
            'policy': policy.name,
            'policy_version': policy.version,
            'action': action,
            'agent_id': context.agent_id,
            'action_type': context.action_type,
            # Note: workflow_id and stage_id deliberately excluded
            # to allow caching across different workflow instances
        }

        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> Optional[ValidationResult]:
        """Get cached validation result if available and not expired."""
        if cache_key in self._cache:
            cached_result, timestamp = self._cache[cache_key]

            # Check if expired
            if time.time() - timestamp < self.cache_ttl:
                return cached_result
            else:
                # Expired - remove from cache
                del self._cache[cache_key]

        return None

    def _cache_result(self, cache_key: str, result: ValidationResult) -> None:
        """Cache validation result with timestamp."""
        self._cache[cache_key] = (result, time.time())

        # Limit cache size (simple LRU eviction)
        if len(self._cache) > self.max_cache_size:
            # Remove oldest 10% of entries
            num_to_remove = max(1, self.max_cache_size // 10)
            oldest = sorted(self._cache.items(), key=lambda x: x[1][1])[:num_to_remove]

            for key, _ in oldest:
                del self._cache[key]

            logger.debug(f"Cache eviction: removed {num_to_remove} oldest entries")

    def _context_to_dict(self, context: PolicyExecutionContext) -> Dict[str, Any]:
        """Convert PolicyExecutionContext to dict for policy validation."""
        return {
            'agent_id': context.agent_id,
            'workflow_id': context.workflow_id,
            'stage_id': context.stage_id,
            'action_type': context.action_type,
            'action_data': context.action_data,
            'metadata': context.metadata
        }

    async def _log_violations(
        self,
        violations: List[SafetyViolation],
        context: PolicyExecutionContext
    ) -> None:
        """Log violations to observability system.

        Note: This is a placeholder for M1 observability integration.
        Actual implementation would write to database.
        """
        for violation in violations:
            logger.warning(
                f"Safety violation: [{violation.severity.name}] "
                f"{violation.policy_name}: {violation.message}",
                extra={
                    'agent_id': context.agent_id,
                    'workflow_id': context.workflow_id,
                    'stage_id': context.stage_id,
                    'policy': violation.policy_name,
                    'severity': violation.severity.name,
                    'action_type': context.action_type
                }
            )

        self._violations_logged += len(violations)

    def clear_cache(self) -> None:
        """Clear policy result cache.

        Useful for testing or when policies are updated.
        """
        self._cache.clear()
        logger.info("Policy cache cleared")

    def get_metrics(self) -> Dict[str, Any]:
        """Get engine metrics for observability.

        Returns:
            Dictionary with engine performance metrics

        Example:
            >>> metrics = engine.get_metrics()
            >>> print(f"Cache hit rate: {metrics['cache_hit_rate']:.2%}")
        """
        total_cache_requests = self._cache_hits + self._cache_misses
        cache_hit_rate = (
            self._cache_hits / total_cache_requests
            if total_cache_requests > 0
            else 0.0
        )

        return {
            'validations_performed': self._validations_performed,
            'violations_logged': self._violations_logged,
            'cache_size': len(self._cache),
            'cache_hits': self._cache_hits,
            'cache_misses': self._cache_misses,
            'cache_hit_rate': cache_hit_rate,
            'policies_registered': self.registry.policy_count()
        }

    def reset_metrics(self) -> None:
        """Reset engine metrics.

        Useful for testing or periodic metrics reporting.
        """
        self._validations_performed = 0
        self._violations_logged = 0
        self._cache_hits = 0
        self._cache_misses = 0
        logger.debug("Engine metrics reset")

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"ActionPolicyEngine("
            f"policies={self.registry.policy_count()}, "
            f"cache_size={len(self._cache)}, "
            f"validations={self._validations_performed})"
        )
