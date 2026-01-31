# Task: m4-08 - Action Policy Engine

**Priority:** CRITICAL (P0 - Security)
**Effort:** 14 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement the central action policy engine that validates agent actions against all safety policies before execution. Supports pre-execution validation, post-execution verification, policy caching, and integration with agent executor lifecycle hooks. This is the enforcement layer that brings all M4 policies together.

---

## Files to Create

- `src/safety/action_policy_engine.py` - Core policy engine implementation
- `src/safety/policy_registry.py` - Policy registration and lookup service
- `config/safety/action_policies.yaml` - Policy-to-action-type mappings
- `tests/safety/test_action_policy_engine.py` - Engine unit tests
- `tests/safety/integration/test_policy_enforcement.py` - Integration tests

---

## Files to Modify

- `src/core/agent_executor.py` - Add policy engine hooks (pre_execute, post_execute)
- `src/core/service_factory.py` - Register policy engine as singleton service

---

## Acceptance Criteria

### Core Functionality
- [ ] Policy engine validates all agent actions before execution
- [ ] Supports policy composition (multiple policies per action type)
- [ ] Policy caching for performance (configurable TTL)
- [ ] Pre-execution and post-execution validation hooks
- [ ] Violation aggregation and reporting to observability system

### Policy Registration
- [ ] `PolicyRegistry` supports dynamic policy registration
- [ ] Policies registered by action type (git_commit, deploy, tool_call, etc.)
- [ ] Multiple policies can be registered for same action type
- [ ] Policy priority ordering (higher priority executes first)

### Integration
- [ ] Agent executor lifecycle integration (hooks at pre/post execution)
- [ ] M1 observability integration (all violations logged)
- [ ] YAML configuration for policy-to-action-type mappings
- [ ] Support for custom policy plugins

### Performance
- [ ] Policy caching reduces redundant validations
- [ ] Async policy execution where possible
- [ ] Short-circuit on CRITICAL violations

### Testing
- [ ] Unit tests for policy execution and caching (>90% coverage)
- [ ] Integration tests with real agent actions (>85% coverage)
- [ ] Performance tests (1000+ validations/second)

---

## Implementation Details

### ActionPolicyEngine

```python
import asyncio
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from src.safety.interfaces import SafetyPolicy, ValidationResult, SafetyViolation
from src.safety.policy_registry import PolicyRegistry
from src.observability.database import get_session
from src.observability.models import SafetyViolationLog

@dataclass
class PolicyExecutionContext:
    """Context for policy execution."""
    agent_id: str
    workflow_id: str
    stage_id: str
    action_type: str
    action_data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class EnforcementResult:
    """Result of policy enforcement."""
    allowed: bool
    violations: List[SafetyViolation]
    policies_executed: List[str]
    execution_time_ms: float
    metadata: Dict[str, Any]

class ActionPolicyEngine:
    """Central policy enforcement engine."""

    def __init__(
        self,
        policy_registry: PolicyRegistry,
        config: Dict[str, Any]
    ):
        self.registry = policy_registry
        self.config = config

        # Policy cache (action_hash -> ValidationResult)
        self.cache: Dict[str, ValidationResult] = {}
        self.cache_ttl = config.get('cache_ttl', 60)  # 60 seconds default

        # Observability
        self.violations_logged = 0
        self.validations_performed = 0

    async def validate_action(
        self,
        action: Dict[str, Any],
        context: PolicyExecutionContext
    ) -> EnforcementResult:
        """
        Validate action against all applicable policies.

        Args:
            action: Action to validate (type, parameters, etc.)
            context: Execution context (agent, workflow, stage)

        Returns:
            EnforcementResult with allowed flag and any violations
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
                metadata={'reason': 'no_policies'}
            )

        # Execute policies in priority order
        all_violations = []
        policies_executed = []

        for policy in policies:
            try:
                # Check cache first
                cache_key = self._get_cache_key(policy, action, context)
                cached_result = self._get_cached_result(cache_key)

                if cached_result is not None:
                    result = cached_result
                else:
                    # Execute policy validation
                    result = await policy.validate_async(
                        action=action,
                        context=vars(context)
                    )

                    # Cache result
                    self._cache_result(cache_key, result)

                policies_executed.append(policy.name)
                all_violations.extend(result.violations)

                # Short-circuit on CRITICAL violations
                if any(v.severity == ViolationSeverity.CRITICAL for v in result.violations):
                    break

            except Exception as e:
                # Policy execution error - log and continue
                logging.error(f"Policy {policy.name} execution failed: {e}")
                # Treat as violation for safety
                violation = SafetyViolation(
                    policy_name=policy.name,
                    severity=ViolationSeverity.HIGH,
                    message=f"Policy execution error: {e}",
                    action=context.action_type,
                    context=vars(context),
                    timestamp=time.time()
                )
                all_violations.append(violation)

        # Determine if action is allowed
        high_severity_violations = [
            v for v in all_violations
            if v.severity.value >= ViolationSeverity.HIGH.value
        ]

        allowed = len(high_severity_violations) == 0

        # Log violations to observability
        if all_violations:
            await self._log_violations(all_violations, context)

        execution_time = (time.time() - start_time) * 1000  # ms

        self.validations_performed += 1

        return EnforcementResult(
            allowed=allowed,
            violations=all_violations,
            policies_executed=policies_executed,
            execution_time_ms=execution_time,
            metadata={
                'total_violations': len(all_violations),
                'critical_violations': len([v for v in all_violations if v.severity == ViolationSeverity.CRITICAL]),
                'high_violations': len([v for v in all_violations if v.severity == ViolationSeverity.HIGH])
            }
        )

    def _get_cache_key(
        self,
        policy: SafetyPolicy,
        action: Dict[str, Any],
        context: PolicyExecutionContext
    ) -> str:
        """Generate cache key for policy result."""
        import hashlib
        import json

        # Create deterministic hash of policy + action + context
        data = {
            'policy': policy.name,
            'policy_version': policy.version,
            'action': action,
            'agent_id': context.agent_id,
            'action_type': context.action_type
        }

        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> Optional[ValidationResult]:
        """Get cached validation result if available and not expired."""
        if cache_key in self.cache:
            cached, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached
            else:
                # Expired - remove from cache
                del self.cache[cache_key]
        return None

    def _cache_result(self, cache_key: str, result: ValidationResult):
        """Cache validation result with timestamp."""
        self.cache[cache_key] = (result, time.time())

        # Limit cache size (LRU eviction)
        if len(self.cache) > 1000:
            # Remove oldest 100 entries
            oldest = sorted(self.cache.items(), key=lambda x: x[1][1])[:100]
            for key, _ in oldest:
                del self.cache[key]

    async def _log_violations(
        self,
        violations: List[SafetyViolation],
        context: PolicyExecutionContext
    ):
        """Log violations to observability database."""
        # Integration with M1 observability
        with get_session() as session:
            for violation in violations:
                log_entry = SafetyViolationLog(
                    agent_id=context.agent_id,
                    workflow_id=context.workflow_id,
                    stage_id=context.stage_id,
                    policy_name=violation.policy_name,
                    severity=violation.severity.name,
                    action_type=context.action_type,
                    message=violation.message,
                    context_data=violation.context,
                    timestamp=violation.timestamp
                )
                session.add(log_entry)
            session.commit()

        self.violations_logged += len(violations)

    def clear_cache(self):
        """Clear policy cache (for testing or config changes)."""
        self.cache.clear()

    def get_metrics(self) -> Dict[str, Any]:
        """Get engine metrics for observability."""
        return {
            'validations_performed': self.validations_performed,
            'violations_logged': self.violations_logged,
            'cache_size': len(self.cache),
            'cache_hit_rate': self._calculate_cache_hit_rate()
        }

    def _calculate_cache_hit_rate(self) -> float:
        """Calculate cache hit rate (approximation)."""
        # Simplified - real implementation would track hits/misses
        if self.validations_performed == 0:
            return 0.0
        return len(self.cache) / self.validations_performed
```

### PolicyRegistry

```python
from typing import Dict, List
from src.safety.interfaces import SafetyPolicy

class PolicyRegistry:
    """Registry for safety policies."""

    def __init__(self):
        # action_type -> List[SafetyPolicy]
        self._policies: Dict[str, List[SafetyPolicy]] = {}

        # Global policies (apply to all actions)
        self._global_policies: List[SafetyPolicy] = []

    def register_policy(
        self,
        policy: SafetyPolicy,
        action_types: List[str] = None
    ):
        """
        Register policy for specific action types.

        Args:
            policy: Policy to register
            action_types: List of action types (None = global policy)
        """
        if action_types is None:
            # Global policy
            self._global_policies.append(policy)
            self._global_policies.sort(key=lambda p: p.priority, reverse=True)
        else:
            # Action-specific policy
            for action_type in action_types:
                if action_type not in self._policies:
                    self._policies[action_type] = []

                self._policies[action_type].append(policy)
                self._policies[action_type].sort(key=lambda p: p.priority, reverse=True)

    def get_policies_for_action(self, action_type: str) -> List[SafetyPolicy]:
        """Get all policies applicable to an action type (global + specific)."""
        policies = list(self._global_policies)  # Copy global policies

        if action_type in self._policies:
            policies.extend(self._policies[action_type])

        # Re-sort by priority
        policies.sort(key=lambda p: p.priority, reverse=True)

        return policies

    def unregister_policy(self, policy_name: str):
        """Remove policy by name."""
        # Remove from global
        self._global_policies = [
            p for p in self._global_policies
            if p.name != policy_name
        ]

        # Remove from action-specific
        for action_type in self._policies:
            self._policies[action_type] = [
                p for p in self._policies[action_type]
                if p.name != policy_name
            ]
```

---

## Configuration Example

```yaml
# config/safety/action_policies.yaml

# Policy engine configuration
policy_engine:
  cache_ttl: 60          # Cache validation results for 60 seconds
  max_cache_size: 1000   # Max cached results
  enable_async: true     # Use async validation where possible

# Policy-to-action-type mappings
policy_mappings:
  # File operations
  file_write:
    - file_access_policy
    - forbidden_ops_policy
    - resource_limit_policy

  file_read:
    - file_access_policy

  # Git operations
  git_commit:
    - rate_limit_policy
    - forbidden_ops_policy
    - file_access_policy

  # Deployments
  deploy:
    - rate_limit_policy
    - approval_workflow_policy

  # Tool calls
  tool_call:
    - rate_limit_policy
    - resource_limit_policy

  # LLM calls
  llm_call:
    - rate_limit_policy

# Global policies (apply to all actions)
global_policies:
  - circuit_breaker_policy
```

---

## Integration with Agent Executor

```python
# src/core/agent_executor.py modifications

class AgentExecutor:
    def __init__(self, ...):
        # ...
        self.policy_engine = ServiceFactory.get_service('action_policy_engine')

    async def execute_action(self, action: Dict[str, Any]) -> Any:
        """Execute action with policy enforcement."""

        # PRE-EXECUTION: Validate with policy engine
        context = PolicyExecutionContext(
            agent_id=self.agent_id,
            workflow_id=self.workflow_id,
            stage_id=self.stage_id,
            action_type=action['type'],
            action_data=action
        )

        result = await self.policy_engine.validate_action(action, context)

        if not result.allowed:
            # Action blocked by safety policy
            raise SafetyViolation(
                f"Action blocked: {result.violations[0].message}"
            )

        # Execute the action
        try:
            output = await self._execute_action_impl(action)

            # POST-EXECUTION: Log success
            # (Future: post-execution validation)

            return output

        except Exception as e:
            # Execution failed - may trigger rollback
            await self.policy_engine.handle_execution_failure(action, e)
            raise
```

---

## Test Strategy

### Unit Tests
- Test policy registration and lookup
- Test policy priority ordering
- Test cache hit/miss scenarios
- Test short-circuit on CRITICAL violations
- Test error handling (policy execution failure)

### Integration Tests
- Test with real agent executor
- Test with multiple policies for same action
- Test observability integration (violations logged)
- Test performance under load (1000+ validations/s)

### End-to-End Tests
- Test full workflow: agent action → policy validation → execution/block
- Test with all Phase 2 policies (file access, rate limit, etc.)
- Test rollback on post-execution violations

---

## Success Metrics

- [ ] Test coverage >90% (unit), >85% (integration)
- [ ] Policy validation overhead <10ms per action
- [ ] Handles 1000+ validations/second
- [ ] Cache hit rate >70% in typical usage
- [ ] Zero policy bypass vulnerabilities

---

## Dependencies

**Blocked by:** m4-04, m4-05, m4-06, m4-07 (needs policies to enforce)
**Blocks:** m4-09, m4-10, m4-11, m4-14

---

## Design References

- Chain of Responsibility pattern for policy execution
- Registry pattern for policy management
- Cache-aside pattern for result caching

---

## Notes

This is the **most critical component** of M4 - it brings all safety policies together into a unified enforcement layer.

**Performance is paramount** - this is in the critical path for EVERY agent action.

**Failure mode:** If policy engine fails, should fail CLOSED (block action) not OPEN (allow action).

**Extensibility:** Users should be able to register custom policies easily.
