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
import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.core.circuit_breaker import CircuitBreakerError
from src.safety.interfaces import SafetyPolicy, SafetyViolation, ValidationResult, ViolationSeverity
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
        # SECURITY: Default to fail-closed when no policies match.
        # Set fail_open=True only for development/testing.
        self.fail_open = self.config.get('fail_open', False)

        # Policy result cache: cache_key -> (result, timestamp)
        self._cache: OrderedDict[str, Tuple[ValidationResult, float]] = OrderedDict()

        # SECURITY: Initialize sanitizer for defense-in-depth violation message sanitization
        # Lazy loaded to avoid import overhead if sanitization is not needed
        self._sanitizer = None

        # Metrics
        self._validations_performed = 0
        self._violations_logged = 0
        self._cache_hits = 0
        self._cache_misses = 0

        # SA-06: Track policy snapshot for cache invalidation.
        # When policies change in the registry, cached results may be stale.
        self._cached_policy_snapshot: Optional[str] = None

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

        # SA-06: Invalidate cache when the set of registered policies changes.
        self._invalidate_cache_if_policies_changed()

        # Get applicable policies for this action type
        policies = self.registry.get_policies_for_action(context.action_type)

        if not policies:
            if self.fail_open:
                # Explicit opt-in: allow when no policies registered (dev/test only)
                return EnforcementResult(
                    allowed=True,
                    violations=[],
                    policies_executed=[],
                    execution_time_ms=0.0,
                    metadata={'reason': 'no_policies_registered', 'mode': 'fail_open'},
                    cache_hit=False
                )
            # SECURITY: Fail-closed — deny action when no policies can validate it
            logger.warning(
                "No policies registered for action type '%s' — denying action (fail-closed). "
                "Register policies or set fail_open=True for development.",
                context.action_type,
            )
            return EnforcementResult(
                allowed=False,
                violations=[],
                policies_executed=[],
                execution_time_ms=0.0,
                metadata={'reason': 'no_policies_registered', 'mode': 'fail_closed'},
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

            except (AttributeError, TypeError, ValueError, KeyError, RuntimeError, CircuitBreakerError) as e:
                # Policy execution error - log and treat as violation for safety
                logger.error(f"Policy {policy.name} execution failed: {e}", exc_info=True)

                # SECURITY (SA-03): Use generic message to prevent info leakage
                # Full exception details are logged above at ERROR level with exc_info
                violation = SafetyViolation(
                    policy_name=policy.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Policy execution error in {policy.name}",
                    action=str(action),
                    context=self._context_to_dict(context),
                    remediation_hint="Check policy implementation for errors",
                    metadata={'exception_type': type(e).__name__}
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

    def validate_action_sync(
        self,
        action: Dict[str, Any],
        context: PolicyExecutionContext
    ) -> EnforcementResult:
        """Synchronous version of validate_action for non-async callers.

        Mirrors validate_action but uses policy.validate() instead of
        policy.validate_async(). Safe to call from synchronous contexts
        (e.g., StandardAgent._execute_iteration).
        """
        start_time = time.time()
        self._invalidate_cache_if_policies_changed()

        policies = self.registry.get_policies_for_action(context.action_type)

        if not policies:
            if self.fail_open:
                return EnforcementResult(
                    allowed=True, violations=[], policies_executed=[],
                    execution_time_ms=0.0,
                    metadata={'reason': 'no_policies_registered', 'mode': 'fail_open'},
                    cache_hit=False,
                )
            logger.warning(
                "No policies registered for action type '%s' — denying action (fail-closed).",
                context.action_type,
            )
            return EnforcementResult(
                allowed=False, violations=[], policies_executed=[],
                execution_time_ms=0.0,
                metadata={'reason': 'no_policies_registered', 'mode': 'fail_closed'},
                cache_hit=False,
            )

        all_violations: List[SafetyViolation] = []
        policies_executed: List[str] = []
        cache_hits = 0

        for policy in policies:
            try:
                cache_key = self._get_cache_key(policy, action, context)
                cached_result = self._get_cached_result(cache_key) if self.enable_caching else None

                if cached_result is not None:
                    result = cached_result
                    cache_hits += 1
                    self._cache_hits += 1
                else:
                    result = policy.validate(
                        action=action,
                        context=self._context_to_dict(context)
                    )
                    if self.enable_caching:
                        self._cache_result(cache_key, result)
                        self._cache_misses += 1

                policies_executed.append(policy.name)
                all_violations.extend(result.violations)

                if self.short_circuit_critical:
                    if any(v.severity == ViolationSeverity.CRITICAL for v in result.violations):
                        logger.warning(
                            f"Short-circuiting on CRITICAL violation from {policy.name}"
                        )
                        break

            except (AttributeError, TypeError, ValueError, KeyError, RuntimeError, CircuitBreakerError) as e:
                logger.error(f"Policy {policy.name} execution failed: {e}", exc_info=True)
                violation = SafetyViolation(
                    policy_name=policy.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Policy execution error in {policy.name}",
                    action=str(action),
                    context=self._context_to_dict(context),
                    remediation_hint="Check policy implementation for errors",
                    metadata={'exception_type': type(e).__name__}
                )
                all_violations.append(violation)
                policies_executed.append(policy.name)

        blocking_violations = [
            v for v in all_violations
            if v.severity >= ViolationSeverity.HIGH
        ]
        allowed = len(blocking_violations) == 0

        if self.log_violations and all_violations:
            self._log_violations_sync(all_violations, context)

        execution_time = (time.time() - start_time) * 1000
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

    def _log_violations_sync(
        self,
        violations: List[SafetyViolation],
        context: PolicyExecutionContext
    ) -> None:
        """Synchronous version of _log_violations."""
        if self._sanitizer is None:
            from src.observability.sanitization import DataSanitizer
            self._sanitizer = DataSanitizer()

        for violation in violations:
            safe_message = self._sanitizer.sanitize_text(violation.message).sanitized_text
            logger.warning(
                f"Safety violation: [{violation.severity.name}] "
                f"{violation.policy_name}: {safe_message}",
                extra={
                    'agent_id': context.agent_id,
                    'workflow_id': context.workflow_id,
                    'stage_id': context.stage_id,
                    'policy': violation.policy_name,
                    'severity': violation.severity.name,
                    'action_type': context.action_type
                }
            )

    def _canonical_json(self, obj: Any) -> str:
        """Create canonical JSON representation for deterministic hashing.

        This function ensures that identical logical data always produces
        identical JSON strings, preventing cache collision attacks.

        Security properties:
        - Recursively sorts all dict keys (not just top-level)
        - Deterministic handling of all Python types
        - Resistant to collision attacks via crafted nested structures
        - Platform-independent serialization

        Args:
            obj: Python object to serialize

        Returns:
            Canonical JSON string

        Example:
            >>> engine._canonical_json({"b": {"d": 1, "c": 2}, "a": 3})
            '{"a":3,"b":{"c":2,"d":1}}'  # All keys sorted at all levels
        """
        def canonicalize(o: Any) -> Any:
            """Recursively canonicalize an object."""
            if isinstance(o, dict):
                # Sort dict keys recursively
                return {k: canonicalize(v) for k, v in sorted(o.items())}
            elif isinstance(o, (list, tuple)):
                # Lists/tuples: canonicalize elements (preserve order)
                return [canonicalize(item) for item in o]
            elif isinstance(o, set):
                # Sets: sort for determinism (sets are unordered)
                return sorted([canonicalize(item) for item in o])
            elif isinstance(o, (str, int, float, bool, type(None))):
                # Primitives: return as-is
                return o
            else:
                # Unsupported types: convert to string representation
                # This ensures determinism for custom types
                return str(o)

        # Canonicalize the object structure
        canonical_obj = canonicalize(obj)

        # Serialize with sorted keys and no whitespace
        # Use separators for minimal, deterministic output
        return json.dumps(
            canonical_obj,
            sort_keys=True,
            separators=(',', ':'),  # No whitespace
            ensure_ascii=True  # ASCII-only for platform independence
        )

    def _get_cache_key(
        self,
        policy: SafetyPolicy,
        action: Dict[str, Any],
        context: PolicyExecutionContext
    ) -> str:
        """Generate cache key for policy result.

        Creates deterministic hash of policy + action + context.

        SECURITY: Uses canonical JSON serialization to prevent cache
        collision attacks. Standard json.dumps(sort_keys=True) only sorts
        top-level keys, allowing collision via crafted nested structures.

        Args:
            policy: Safety policy being validated
            action: Action dict (may contain nested structures)
            context: Execution context

        Returns:
            SHA-256 hex digest of canonical representation
        """
        # Create deterministic representation
        data = {
            'policy': policy.name,
            'policy_version': policy.version,
            'action': action,
            'agent_id': context.agent_id,
            'action_type': context.action_type,
            'workflow_id': context.workflow_id,
            'stage_id': context.stage_id,
        }

        # Use canonical JSON to prevent collision attacks
        json_str = self._canonical_json(data)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> Optional[ValidationResult]:
        """Get cached validation result if available and not expired."""
        if cache_key in self._cache:
            cached_result, timestamp = self._cache[cache_key]

            # Check if expired
            if time.time() - timestamp < self.cache_ttl:
                # Move to end (most recently used) for O(1) LRU
                self._cache.move_to_end(cache_key)
                return cached_result
            else:
                # Expired - remove from cache
                del self._cache[cache_key]

        return None

    def _cache_result(self, cache_key: str, result: ValidationResult) -> None:
        """Cache validation result with timestamp.

        Uses OrderedDict for O(1) LRU eviction instead of O(n log n) sorted eviction.
        """
        self._cache[cache_key] = (result, time.time())
        self._cache.move_to_end(cache_key)

        # Evict LRU entries (oldest are at the front of the OrderedDict)
        while len(self._cache) > self.max_cache_size:
            evicted_key, _ = self._cache.popitem(last=False)
            logger.debug("Cache eviction: removed LRU entry %s", evicted_key)

    def _get_policy_snapshot(self) -> str:
        """Get a fingerprint of the current set of registered policies."""
        names = sorted(self.registry.list_policies())
        return hashlib.sha256(",".join(names).encode()).hexdigest()

    def _invalidate_cache_if_policies_changed(self) -> None:
        """SA-06: Clear cache when registered policies change."""
        snapshot = self._get_policy_snapshot()
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
        # SECURITY: Lazy-load sanitizer for defense-in-depth
        # Even though policies should sanitize, we add an extra layer
        if self._sanitizer is None:
            from src.observability.sanitization import DataSanitizer
            self._sanitizer = DataSanitizer()

        for violation in violations:
            # SECURITY: Sanitize violation message for defense-in-depth
            safe_message = self._sanitizer.sanitize_text(violation.message).sanitized_text

            logger.warning(
                f"Safety violation: [{violation.severity.name}] "
                f"{violation.policy_name}: {safe_message}",
                extra={
                    'agent_id': context.agent_id,
                    'workflow_id': context.workflow_id,
                    'stage_id': context.stage_id,
                    'policy': violation.policy_name,
                    'severity': violation.severity.name,
                    'action_type': context.action_type
                    # NOTE: Intentionally omit violation.context for security
                }
            )

        self._violations_logged += len(violations)

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
