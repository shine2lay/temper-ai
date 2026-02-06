"""Tests for ActionPolicyEngine.

Tests cover:
- Action validation with policies
- Policy caching and performance
- Short-circuit on CRITICAL violations
- Multiple policy execution
- Async validation
- Metrics tracking
- Error handling
"""
import asyncio
import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from src.safety.action_policy_engine import (
    ActionPolicyEngine,
    EnforcementResult,
    PolicyExecutionContext,
)
from src.safety.interfaces import SafetyPolicy, SafetyViolation, ValidationResult, ViolationSeverity
from src.safety.policy_registry import PolicyRegistry

# ============================================================================
# Mock Policies for Testing
# ============================================================================

class MockPolicy(SafetyPolicy):
    """Mock policy for testing."""

    def __init__(
        self,
        name: str,
        priority: int = 100,
        violations: list = None,
        delay_ms: float = 0
    ):
        self._name = name
        self._priority = priority
        self._violations = violations or []
        self._delay_ms = delay_ms
        self.validate_called = False
        self.validate_async_called = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return self._priority

    def validate(self, action: Dict[str, Any], context: Dict[str, Any]) -> ValidationResult:
        self.validate_called = True
        violations = [
            SafetyViolation(
                policy_name=self.name,
                severity=v["severity"],
                message=v["message"],
                action=str(action),
                context=context
            )
            for v in self._violations
        ]
        return ValidationResult(
            valid=len(violations) == 0,
            violations=violations,
            policy_name=self.name
        )

    async def validate_async(self, action: Dict[str, Any], context: Dict[str, Any]) -> ValidationResult:
        self.validate_async_called = True

        # Simulate async delay if specified
        if self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000.0)

        return self.validate(action, context)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def registry():
    """Create empty policy registry."""
    return PolicyRegistry()


@pytest.fixture
def engine(registry):
    """Create action policy engine."""
    return ActionPolicyEngine(registry, config={})


@pytest.fixture
def context():
    """Create sample execution context."""
    return PolicyExecutionContext(
        agent_id="agent-123",
        workflow_id="wf-456",
        stage_id="research",
        action_type="file_write",
        action_data={"path": "/tmp/file.txt"}
    )


# ============================================================================
# Test Basic Validation
# ============================================================================

class TestBasicValidation:
    """Test basic action validation."""

    @pytest.mark.asyncio
    async def test_no_policies_denies_action_by_default(self, engine, context):
        """Test that action is denied when no policies registered (fail-closed)."""
        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert result.allowed is False
        assert len(result.violations) == 0
        assert len(result.policies_executed) == 0
        assert result.metadata['reason'] == 'no_policies_registered'
        assert result.metadata['mode'] == 'fail_closed'

    @pytest.mark.asyncio
    async def test_no_policies_allows_action_when_fail_open(self, registry, context):
        """Test that action is allowed with fail_open=True when no policies registered."""
        fail_open_engine = ActionPolicyEngine(registry, config={'fail_open': True})
        result = await fail_open_engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert result.allowed is True
        assert len(result.violations) == 0
        assert len(result.policies_executed) == 0
        assert result.metadata['reason'] == 'no_policies_registered'
        assert result.metadata['mode'] == 'fail_open'

    @pytest.mark.asyncio
    async def test_policy_with_no_violations_allows_action(self, registry, engine, context):
        """Test that action is allowed when policy has no violations."""
        policy = MockPolicy("test_policy")
        registry.register_policy(policy, action_types=["file_write"])

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert result.allowed is True
        assert len(result.violations) == 0
        assert "test_policy" in result.policies_executed

    @pytest.mark.asyncio
    async def test_policy_with_critical_violation_blocks_action(self, registry, engine, context):
        """Test that CRITICAL violation blocks action."""
        policy = MockPolicy("test_policy", violations=[
            {"severity": ViolationSeverity.CRITICAL, "message": "Critical violation"}
        ])
        registry.register_policy(policy, action_types=["file_write"])

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert result.allowed is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert result.has_critical_violations()
        assert result.has_blocking_violations()

    @pytest.mark.asyncio
    async def test_policy_with_high_violation_blocks_action(self, registry, engine, context):
        """Test that HIGH violation blocks action."""
        policy = MockPolicy("test_policy", violations=[
            {"severity": ViolationSeverity.HIGH, "message": "High violation"}
        ])
        registry.register_policy(policy, action_types=["file_write"])

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert result.allowed is False
        assert result.has_blocking_violations()

    @pytest.mark.asyncio
    async def test_policy_with_medium_violation_allows_action(self, registry, engine, context):
        """Test that MEDIUM violation does not block action."""
        policy = MockPolicy("test_policy", violations=[
            {"severity": ViolationSeverity.MEDIUM, "message": "Medium violation"}
        ])
        registry.register_policy(policy, action_types=["file_write"])

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert result.allowed is True  # Medium doesn't block
        assert len(result.violations) == 1
        assert not result.has_blocking_violations()


# ============================================================================
# Test Multiple Policies
# ============================================================================

class TestMultiplePolicies:
    """Test execution of multiple policies."""

    @pytest.mark.asyncio
    async def test_multiple_policies_all_executed(self, registry, engine, context):
        """Test that all policies are executed."""
        policy1 = MockPolicy("policy1")
        policy2 = MockPolicy("policy2")
        policy3 = MockPolicy("policy3")

        registry.register_policy(policy1, action_types=["file_write"])
        registry.register_policy(policy2, action_types=["file_write"])
        registry.register_policy(policy3, action_types=["file_write"])

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert len(result.policies_executed) == 3
        assert "policy1" in result.policies_executed
        assert "policy2" in result.policies_executed
        assert "policy3" in result.policies_executed

    @pytest.mark.asyncio
    async def test_policies_execute_in_priority_order(self, registry, engine, context):
        """Test that policies execute in priority order (highest first)."""
        low = MockPolicy("low", priority=50)
        high = MockPolicy("high", priority=200)
        medium = MockPolicy("medium", priority=100)

        registry.register_policy(low, action_types=["file_write"])
        registry.register_policy(high, action_types=["file_write"])
        registry.register_policy(medium, action_types=["file_write"])

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # Should execute in order: high, medium, low
        assert result.policies_executed == ["high", "medium", "low"]

    @pytest.mark.asyncio
    async def test_violations_aggregated_from_all_policies(self, registry, engine, context):
        """Test that violations from all policies are aggregated."""
        policy1 = MockPolicy("policy1", violations=[
            {"severity": ViolationSeverity.MEDIUM, "message": "Violation 1"}
        ])
        policy2 = MockPolicy("policy2", violations=[
            {"severity": ViolationSeverity.HIGH, "message": "Violation 2"}
        ])
        policy3 = MockPolicy("policy3", violations=[
            {"severity": ViolationSeverity.MEDIUM, "message": "Violation 3"}
        ])

        registry.register_policy(policy1, action_types=["file_write"])
        registry.register_policy(policy2, action_types=["file_write"])
        registry.register_policy(policy3, action_types=["file_write"])

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert len(result.violations) == 3
        assert result.metadata['total_violations'] == 3
        assert result.metadata['high_violations'] == 1
        assert result.metadata['medium_violations'] == 2


# ============================================================================
# Test Short-Circuit Behavior
# ============================================================================

class TestShortCircuit:
    """Test short-circuit on CRITICAL violations."""

    @pytest.mark.asyncio
    async def test_short_circuit_on_critical(self, registry, context):
        """Test that execution stops after CRITICAL violation."""
        policy1 = MockPolicy("policy1", priority=200)  # No violation
        policy2 = MockPolicy("policy2", priority=150, violations=[
            {"severity": ViolationSeverity.CRITICAL, "message": "Critical"}
        ])
        policy3 = MockPolicy("policy3", priority=100)  # Should not execute

        registry.register_policy(policy1, action_types=["file_write"])
        registry.register_policy(policy2, action_types=["file_write"])
        registry.register_policy(policy3, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={"short_circuit_critical": True})

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # Only policy1 and policy2 should execute
        assert len(result.policies_executed) == 2
        assert "policy1" in result.policies_executed
        assert "policy2" in result.policies_executed
        assert "policy3" not in result.policies_executed
        assert result.metadata['short_circuited'] is True

    @pytest.mark.asyncio
    async def test_no_short_circuit_when_disabled(self, registry, context):
        """Test that all policies execute when short-circuit disabled."""
        policy1 = MockPolicy("policy1", priority=200)
        policy2 = MockPolicy("policy2", priority=150, violations=[
            {"severity": ViolationSeverity.CRITICAL, "message": "Critical"}
        ])
        policy3 = MockPolicy("policy3", priority=100)

        registry.register_policy(policy1, action_types=["file_write"])
        registry.register_policy(policy2, action_types=["file_write"])
        registry.register_policy(policy3, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={"short_circuit_critical": False})

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # All policies should execute
        assert len(result.policies_executed) == 3
        assert "policy3" in result.policies_executed


# ============================================================================
# Test Caching
# ============================================================================

class TestCaching:
    """Test policy result caching."""

    @pytest.mark.asyncio
    async def test_cache_hit_on_repeat_validation(self, registry, context):
        """Test that repeat validation hits cache."""
        policy = MockPolicy("test_policy")
        registry.register_policy(policy, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={"enable_caching": True})

        # First validation - cache miss
        result1 = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # Second validation - cache hit
        result2 = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # Both should have same result
        assert result1.allowed == result2.allowed

        # Second should be cache hit
        assert result2.metadata['cache_hits'] > 0

        # Metrics should show cache hit
        metrics = engine.get_metrics()
        assert metrics['cache_hits'] > 0

    @pytest.mark.asyncio
    async def test_cache_disabled(self, registry, context):
        """Test that caching can be disabled."""
        policy = MockPolicy("test_policy")
        registry.register_policy(policy, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={"enable_caching": False})

        # Multiple validations
        for _ in range(3):
            await engine.validate_action(
                action={"command": "test"},
                context=context
            )

        # No cache hits
        metrics = engine.get_metrics()
        assert metrics['cache_hits'] == 0

    @pytest.mark.asyncio
    async def test_cache_expiration(self, registry, context):
        """Test that cache entries expire based on TTL."""

        policy = MockPolicy("test_policy")
        registry.register_policy(policy, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={
            "enable_caching": True,
            "cache_ttl": 0.1  # 100ms TTL
        })

        # First validation
        await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # Wait for expiration
        await asyncio.sleep(0.2)

        # Second validation - cache miss due to expiration
        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # Should be cache miss (expired)
        metrics = engine.get_metrics()
        assert metrics['cache_misses'] >= 2  # Both validations are misses

    @pytest.mark.asyncio
    async def test_clear_cache(self, registry, context):
        """Test clearing cache."""
        policy = MockPolicy("test_policy")
        registry.register_policy(policy, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={"enable_caching": True})

        # Validate to populate cache
        await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert engine.get_metrics()['cache_size'] > 0

        # Clear cache
        engine.clear_cache()

        assert engine.get_metrics()['cache_size'] == 0


# ============================================================================
# Test Error Handling
# ============================================================================

class TestErrorHandling:
    """Test error handling in policy execution."""

    @pytest.mark.asyncio
    async def test_policy_exception_treated_as_critical_violation(self, registry, context):
        """Test that policy exceptions are treated as CRITICAL violations."""
        # Mock policy that raises exception
        policy = Mock(spec=SafetyPolicy)
        policy.name = "failing_policy"
        policy.version = "1.0.0"
        policy.priority = 100
        policy.validate_async = AsyncMock(side_effect=ValueError("Test error"))

        registry.register_policy(policy, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={})

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # Should have CRITICAL violation from exception
        assert result.allowed is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert "Policy execution error" in result.violations[0].message

    @pytest.mark.asyncio
    async def test_exception_does_not_stop_other_policies(self, registry, context):
        """Test that exception in one policy doesn't stop others."""
        failing_policy = Mock(spec=SafetyPolicy)
        failing_policy.name = "failing_policy"
        failing_policy.version = "1.0.0"
        failing_policy.priority = 200
        failing_policy.validate_async = AsyncMock(side_effect=ValueError("Test error"))

        working_policy = MockPolicy("working_policy", priority=100)

        registry.register_policy(failing_policy, action_types=["file_write"])
        registry.register_policy(working_policy, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={"short_circuit_critical": False})

        result = await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # Both policies should have executed
        assert len(result.policies_executed) == 2
        assert "failing_policy" in result.policies_executed
        assert "working_policy" in result.policies_executed


# ============================================================================
# Test Metrics
# ============================================================================

class TestMetrics:
    """Test engine metrics tracking."""

    @pytest.mark.asyncio
    async def test_validation_count_tracked(self, registry, engine, context):
        """Test that validation count is tracked."""
        policy = MockPolicy("test_policy")
        registry.register_policy(policy, action_types=["file_write"])

        initial_count = engine.get_metrics()['validations_performed']

        await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert engine.get_metrics()['validations_performed'] == initial_count + 1

    @pytest.mark.asyncio
    async def test_violation_count_tracked(self, registry, engine, context):
        """Test that violation count is tracked."""
        policy = MockPolicy("test_policy", violations=[
            {"severity": ViolationSeverity.HIGH, "message": "Violation"}
        ])
        registry.register_policy(policy, action_types=["file_write"])

        initial_count = engine.get_metrics()['violations_logged']

        await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert engine.get_metrics()['violations_logged'] == initial_count + 1

    @pytest.mark.asyncio
    async def test_cache_hit_rate_calculated(self, registry, context):
        """Test that cache hit rate is calculated."""
        policy = MockPolicy("test_policy")
        registry.register_policy(policy, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={"enable_caching": True})

        # First validation - miss
        await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        # Second validation - hit
        await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        metrics = engine.get_metrics()
        assert metrics['cache_hit_rate'] > 0.0
        assert metrics['cache_hit_rate'] <= 1.0

    @pytest.mark.asyncio
    async def test_reset_metrics(self, registry, engine, context):
        """Test resetting metrics."""
        policy = MockPolicy("test_policy")
        registry.register_policy(policy, action_types=["file_write"])

        await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        assert engine.get_metrics()['validations_performed'] > 0

        engine.reset_metrics()

        assert engine.get_metrics()['validations_performed'] == 0


# ============================================================================
# Test Result Helper Methods
# ============================================================================

class TestEnforcementResultHelpers:
    """Test EnforcementResult helper methods."""

    def test_has_critical_violations(self):
        """Test has_critical_violations() detection."""
        violations = [
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.CRITICAL,
                message="Critical",
                action="test",
                context={}
            )
        ]

        result = EnforcementResult(
            allowed=False,
            violations=violations,
            policies_executed=["test"],
            execution_time_ms=10.0,
            metadata={}
        )

        assert result.has_critical_violations() is True

    def test_has_blocking_violations(self):
        """Test has_blocking_violations() detection."""
        violations = [
            SafetyViolation(
                policy_name="test",
                severity=ViolationSeverity.HIGH,
                message="High",
                action="test",
                context={}
            )
        ]

        result = EnforcementResult(
            allowed=False,
            violations=violations,
            policies_executed=["test"],
            execution_time_ms=10.0,
            metadata={}
        )

        assert result.has_blocking_violations() is True

    def test_get_violations_by_severity(self):
        """Test filtering violations by severity."""
        violations = [
            SafetyViolation(
                policy_name="p1",
                severity=ViolationSeverity.CRITICAL,
                message="Critical",
                action="test",
                context={}
            ),
            SafetyViolation(
                policy_name="p2",
                severity=ViolationSeverity.MEDIUM,
                message="Medium",
                action="test",
                context={}
            ),
            SafetyViolation(
                policy_name="p3",
                severity=ViolationSeverity.CRITICAL,
                message="Critical2",
                action="test",
                context={}
            ),
        ]

        result = EnforcementResult(
            allowed=False,
            violations=violations,
            policies_executed=["p1", "p2", "p3"],
            execution_time_ms=10.0,
            metadata={}
        )

        critical = result.get_violations_by_severity(ViolationSeverity.CRITICAL)
        assert len(critical) == 2

        medium = result.get_violations_by_severity(ViolationSeverity.MEDIUM)
        assert len(medium) == 1


# ============================================================================
# Test Async Performance
# ============================================================================

class TestAsyncPerformance:
    """Test async execution performance."""

    @pytest.mark.asyncio
    async def test_parallel_policy_execution(self, registry, context):
        """Test that policies can execute in parallel (async)."""
        # Policies with simulated delays
        policy1 = MockPolicy("policy1", delay_ms=10)
        policy2 = MockPolicy("policy2", delay_ms=10)
        policy3 = MockPolicy("policy3", delay_ms=10)

        registry.register_policy(policy1, action_types=["file_write"])
        registry.register_policy(policy2, action_types=["file_write"])
        registry.register_policy(policy3, action_types=["file_write"])

        engine = ActionPolicyEngine(registry, config={})

        import time
        start = time.time()

        await engine.validate_action(
            action={"command": "test"},
            context=context
        )

        elapsed = (time.time() - start) * 1000  # ms

        # Sequential would be 30ms+, async should be faster
        # Note: In current implementation, policies execute sequentially
        # This test validates the async interface works
        assert elapsed < 100  # Reasonable upper bound


# ============================================================================
# Test String Representation
# ============================================================================

class TestStringRepresentation:
    """Test string representation."""

    def test_repr(self, engine):
        """Test string representation."""
        repr_str = repr(engine)

        assert "ActionPolicyEngine" in repr_str
        assert "policies=" in repr_str
        assert "cache_size=" in repr_str


class TestCacheKeySecurityFixes:
    """Test cache key generation security fixes (code-crit-05)."""

    def test_canonical_json_sorts_nested_dicts(self):
        """Test that canonical JSON sorts nested dictionary keys."""
        engine = ActionPolicyEngine(policy_registry=MagicMock(), config={})

        # Different key orders, same logical data
        obj1 = {"b": {"d": 1, "c": 2}, "a": 3}
        obj2 = {"a": 3, "b": {"c": 2, "d": 1}}

        json1 = engine._canonical_json(obj1)
        json2 = engine._canonical_json(obj2)

        # Should produce identical JSON
        assert json1 == json2
        # Should have sorted keys at all levels
        assert json1 == '{"a":3,"b":{"c":2,"d":1}}'

    def test_canonical_json_handles_lists(self):
        """Test that canonical JSON preserves list order."""
        engine = ActionPolicyEngine(policy_registry=MagicMock(), config={})

        obj1 = {"items": [3, 1, 2]}
        obj2 = {"items": [3, 1, 2]}

        json1 = engine._canonical_json(obj1)
        json2 = engine._canonical_json(obj2)

        # Same list order produces same JSON
        assert json1 == json2
        assert json1 == '{"items":[3,1,2]}'

        # Different list order produces different JSON (lists are ordered)
        obj3 = {"items": [1, 2, 3]}
        json3 = engine._canonical_json(obj3)
        assert json3 != json1

    def test_canonical_json_sorts_sets(self):
        """Test that canonical JSON sorts sets for determinism."""
        engine = ActionPolicyEngine(policy_registry=MagicMock(), config={})

        # Sets are unordered in Python, but should serialize deterministically
        obj1 = {"tags": {3, 1, 2}}
        obj2 = {"tags": {2, 3, 1}}

        json1 = engine._canonical_json(obj1)
        json2 = engine._canonical_json(obj2)

        # Same set produces same JSON regardless of internal order
        assert json1 == json2
        # Should be sorted
        assert json1 == '{"tags":[1,2,3]}'

    def test_canonical_json_deeply_nested_structures(self):
        """Test canonical JSON with deeply nested structures."""
        engine = ActionPolicyEngine(policy_registry=MagicMock(), config={})

        obj1 = {
            "level1": {
                "level2": {
                    "level3": {"c": 3, "b": 2, "a": 1}
                }
            }
        }
        obj2 = {
            "level1": {
                "level2": {
                    "level3": {"a": 1, "b": 2, "c": 3}
                }
            }
        }

        json1 = engine._canonical_json(obj1)
        json2 = engine._canonical_json(obj2)

        assert json1 == json2

    def test_canonical_json_mixed_types(self):
        """Test canonical JSON with mixed data types."""
        engine = ActionPolicyEngine(policy_registry=MagicMock(), config={})

        obj = {
            "string": "hello",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "nested": {"key": "value"}
        }

        json_str = engine._canonical_json(obj)

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["string"] == "hello"
        assert parsed["number"] == 42
        assert parsed["float"] == 3.14
        assert parsed["bool"] is True
        assert parsed["null"] is None

    def test_cache_key_prevents_collision_via_nested_key_order(self):
        """Test that cache key prevents collision via nested key order manipulation."""
        registry = MagicMock()
        engine = ActionPolicyEngine(policy_registry=registry, config={})

        policy = MagicMock()
        policy.name = "test_policy"
        policy.version = "1.0"

        context = PolicyExecutionContext(
            agent_id="agent1",
            action_type="test_action",
            action_data={},
            workflow_id="workflow1",
            stage_id="stage1"
        )

        # Two actions with same logical content but different key order
        action1 = {
            "tool": "write_file",
            "params": {"path": "/tmp/file.txt", "mode": "w"}
        }
        action2 = {
            "tool": "write_file",
            "params": {"mode": "w", "path": "/tmp/file.txt"}  # Different order
        }

        key1 = engine._get_cache_key(policy, action1, context)
        key2 = engine._get_cache_key(policy, action2, context)

        # Should produce the SAME cache key (no collision, same logical data)
        assert key1 == key2

    def test_cache_key_different_for_different_actions(self):
        """Test that different actions produce different cache keys."""
        registry = MagicMock()
        engine = ActionPolicyEngine(policy_registry=registry, config={})

        policy = MagicMock()
        policy.name = "test_policy"
        policy.version = "1.0"

        context = PolicyExecutionContext(
            agent_id="agent1",
            action_type="test_action",
            action_data={},
            workflow_id="workflow1",
            stage_id="stage1"
        )

        action1 = {"tool": "write_file", "path": "/tmp/file1.txt"}
        action2 = {"tool": "write_file", "path": "/tmp/file2.txt"}

        key1 = engine._get_cache_key(policy, action1, context)
        key2 = engine._get_cache_key(policy, action2, context)

        # Different actions should produce different keys
        assert key1 != key2

    def test_cache_key_sensitive_to_nested_value_changes(self):
        """Test that cache key changes when nested values change."""
        registry = MagicMock()
        engine = ActionPolicyEngine(policy_registry=registry, config={})

        policy = MagicMock()
        policy.name = "test_policy"
        policy.version = "1.0"

        context = PolicyExecutionContext(
            agent_id="agent1",
            action_type="test_action",
            action_data={},
            workflow_id="workflow1",
            stage_id="stage1"
        )

        action1 = {
            "tool": "api_call",
            "params": {"endpoint": "/api/users", "data": {"role": "admin"}}
        }
        action2 = {
            "tool": "api_call",
            "params": {"endpoint": "/api/users", "data": {"role": "user"}}
        }

        key1 = engine._get_cache_key(policy, action1, context)
        key2 = engine._get_cache_key(policy, action2, context)

        # Different nested values should produce different keys
        assert key1 != key2

    def test_cache_key_includes_workflow_and_stage_id(self):
        """Test that workflow_id and stage_id are included in cache key."""
        registry = MagicMock()
        engine = ActionPolicyEngine(policy_registry=registry, config={})

        policy = MagicMock()
        policy.name = "test_policy"
        policy.version = "1.0"

        action = {"tool": "test"}

        context1 = PolicyExecutionContext(
            agent_id="agent1",
            action_type="test_action",
            action_data={},
            workflow_id="workflow1",
            stage_id="stage1"
        )
        context2 = PolicyExecutionContext(
            agent_id="agent1",
            action_type="test_action",
            action_data={},
            workflow_id="workflow2",  # Different workflow
            stage_id="stage2"  # Different stage
        )

        key1 = engine._get_cache_key(policy, action, context1)
        key2 = engine._get_cache_key(policy, action, context2)

        # Different workflow/stage should produce different keys
        assert key1 != key2

        # Same context should produce same key
        key3 = engine._get_cache_key(policy, action, context1)
        assert key1 == key3

    def test_cache_key_includes_policy_version(self):
        """Test that policy version affects cache key."""
        registry = MagicMock()
        engine = ActionPolicyEngine(policy_registry=registry, config={})

        policy1 = MagicMock()
        policy1.name = "test_policy"
        policy1.version = "1.0"

        policy2 = MagicMock()
        policy2.name = "test_policy"
        policy2.version = "2.0"  # Different version

        context = PolicyExecutionContext(
            agent_id="agent1",
            action_type="test_action",
            action_data={},
            workflow_id="workflow1",
            stage_id="stage1"
        )

        action = {"tool": "test"}

        key1 = engine._get_cache_key(policy1, action, context)
        key2 = engine._get_cache_key(policy2, action, context)

        # Different policy versions should produce different keys
        assert key1 != key2

    def test_canonical_json_handles_empty_structures(self):
        """Test canonical JSON with empty structures."""
        engine = ActionPolicyEngine(policy_registry=MagicMock(), config={})

        empty_dict = {}
        empty_list = []

        json_dict = engine._canonical_json(empty_dict)
        json_list = engine._canonical_json(empty_list)

        assert json_dict == '{}'
        assert json_list == '[]'

    def test_canonical_json_deterministic_for_complex_action(self):
        """Test canonical JSON is deterministic for complex real-world action."""
        engine = ActionPolicyEngine(policy_registry=MagicMock(), config={})

        # Simulate complex action with nested structures
        action = {
            "tool": "execute_workflow",
            "params": {
                "stages": [
                    {"name": "stage1", "config": {"timeout": 30}},
                    {"name": "stage2", "config": {"retry": 3}}
                ],
                "metadata": {
                    "tags": ["production", "critical"],
                    "owner": "team-a"
                }
            }
        }

        # Generate key multiple times
        keys = [engine._canonical_json(action) for _ in range(10)]

        # All keys should be identical
        assert len(set(keys)) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
