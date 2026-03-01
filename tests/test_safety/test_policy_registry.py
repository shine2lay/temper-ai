"""Tests for PolicyRegistry.

Tests cover:
- Policy registration (action-specific and global)
- Policy lookup by action type
- Priority ordering
- Duplicate detection
- Utility methods (list_policies, policy_count, clear)
"""

from typing import Any

import pytest

from temper_ai.safety.interfaces import SafetyPolicy, ValidationResult
from temper_ai.safety.policy_registry import PolicyRegistry

# ============================================================================
# Mock Policies for Testing
# ============================================================================


class MockPolicy(SafetyPolicy):
    """Mock policy for testing."""

    def __init__(self, name: str, priority: int = 100):
        self._name = name
        self._priority = priority

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def priority(self) -> int:
        return self._priority

    def validate(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        return ValidationResult(valid=True, policy_name=self.name)


# ============================================================================
# Test Policy Registration
# ============================================================================


class TestPolicyRegistration:
    """Test policy registration functionality."""

    def test_register_action_specific_policy(self):
        """Test registering policy for specific action types."""
        registry = PolicyRegistry()
        policy = MockPolicy("file_policy")

        registry.register_policy(policy, action_types=["file_read", "file_write"])

        assert registry.policy_count() == 1
        assert "file_policy" in registry.list_policies()

    def test_register_global_policy(self):
        """Test registering global policy (applies to all actions)."""
        registry = PolicyRegistry()
        policy = MockPolicy("global_policy")

        registry.register_policy(policy)  # No action_types = global

        assert "global_policy" in registry.list_policies()

        # Global policy should apply to any action type
        policies = registry.get_policies_for_action("any_action")
        assert len(policies) == 1
        assert policies[0].name == "global_policy"

    def test_register_duplicate_policy_raises_error(self):
        """Test that registering duplicate policy name raises error."""
        registry = PolicyRegistry()
        policy1 = MockPolicy("same_name")
        policy2 = MockPolicy("same_name")

        registry.register_policy(policy1, action_types=["action1"])

        with pytest.raises(ValueError, match="already registered"):
            registry.register_policy(policy2, action_types=["action2"])

    def test_register_multiple_policies_for_same_action(self):
        """Test registering multiple policies for same action type."""
        registry = PolicyRegistry()
        policy1 = MockPolicy("policy1", priority=100)
        policy2 = MockPolicy("policy2", priority=200)

        registry.register_policy(policy1, action_types=["file_write"])
        registry.register_policy(policy2, action_types=["file_write"])

        policies = registry.get_policies_for_action("file_write")
        assert len(policies) == 2
        # Higher priority should be first
        assert policies[0].name == "policy2"
        assert policies[1].name == "policy1"


# ============================================================================
# Test Policy Lookup
# ============================================================================


class TestPolicyLookup:
    """Test policy lookup functionality."""

    def test_get_policies_for_action(self):
        """Test getting policies for specific action type."""
        registry = PolicyRegistry()
        policy1 = MockPolicy("policy1")
        policy2 = MockPolicy("policy2")

        registry.register_policy(policy1, action_types=["file_read"])
        registry.register_policy(policy2, action_types=["file_write"])

        # file_read should only have policy1
        policies = registry.get_policies_for_action("file_read")
        assert len(policies) == 1
        assert policies[0].name == "policy1"

        # file_write should only have policy2
        policies = registry.get_policies_for_action("file_write")
        assert len(policies) == 1
        assert policies[0].name == "policy2"

    def test_get_policies_includes_global(self):
        """Test that action-specific lookup includes global policies."""
        registry = PolicyRegistry()
        global_policy = MockPolicy("global", priority=200)
        action_policy = MockPolicy("action", priority=100)

        registry.register_policy(global_policy)  # Global
        registry.register_policy(action_policy, action_types=["file_write"])

        policies = registry.get_policies_for_action("file_write")
        assert len(policies) == 2
        assert policies[0].name == "global"  # Higher priority first
        assert policies[1].name == "action"

    def test_get_policies_for_unregistered_action(self):
        """Test getting policies for action with no specific policies."""
        registry = PolicyRegistry()
        global_policy = MockPolicy("global")

        registry.register_policy(global_policy)

        # Unregistered action should still get global policies
        policies = registry.get_policies_for_action("unregistered_action")
        assert len(policies) == 1
        assert policies[0].name == "global"

    def test_get_policies_for_action_empty(self):
        """Test getting policies when no policies registered."""
        registry = PolicyRegistry()

        policies = registry.get_policies_for_action("any_action")
        assert len(policies) == 0


# ============================================================================
# Test Priority Ordering
# ============================================================================


class TestPriorityOrdering:
    """Test policy priority ordering."""

    def test_policies_sorted_by_priority(self):
        """Test policies are returned in priority order (highest first)."""
        registry = PolicyRegistry()

        # Add policies in random priority order
        low = MockPolicy("low", priority=50)
        high = MockPolicy("high", priority=200)
        medium = MockPolicy("medium", priority=100)

        registry.register_policy(low, action_types=["action1"])
        registry.register_policy(high, action_types=["action1"])
        registry.register_policy(medium, action_types=["action1"])

        policies = registry.get_policies_for_action("action1")

        # Should be sorted: high, medium, low
        assert policies[0].name == "high"
        assert policies[1].name == "medium"
        assert policies[2].name == "low"

    def test_global_and_action_policies_sorted_together(self):
        """Test global and action-specific policies sorted by priority."""
        registry = PolicyRegistry()

        global_high = MockPolicy("global_high", priority=200)
        action_medium = MockPolicy("action_medium", priority=150)
        global_low = MockPolicy("global_low", priority=50)

        registry.register_policy(global_high)
        registry.register_policy(global_low)
        registry.register_policy(action_medium, action_types=["action1"])

        policies = registry.get_policies_for_action("action1")

        # Should be sorted: global_high (200), action_medium (150), global_low (50)
        assert len(policies) == 3
        assert policies[0].name == "global_high"
        assert policies[1].name == "action_medium"
        assert policies[2].name == "global_low"


# ============================================================================
# Test Utility Methods
# ============================================================================


class TestUtilityMethods:
    """Test utility and helper methods."""

    def test_list_policies_returns_all_names(self):
        """Test getting all registered policy names via list_policies."""
        registry = PolicyRegistry()

        policy1 = MockPolicy("policy1")
        policy2 = MockPolicy("policy2")
        policy3 = MockPolicy("policy3")

        registry.register_policy(policy1, action_types=["action1"])
        registry.register_policy(policy2, action_types=["action2"])
        registry.register_policy(policy3)  # Global

        names = registry.list_policies()

        assert len(names) == 3
        assert "policy1" in names
        assert "policy2" in names
        assert "policy3" in names

    def test_policy_count(self):
        """Test counting registered policies."""
        registry = PolicyRegistry()

        assert registry.policy_count() == 0

        registry.register_policy(MockPolicy("policy1"), action_types=["action1"])
        assert registry.policy_count() == 1

        registry.register_policy(MockPolicy("policy2"))  # Global
        assert registry.policy_count() == 2

        registry.register_policy(MockPolicy("policy3"), action_types=["action2"])
        assert registry.policy_count() == 3

    def test_clear(self):
        """Test clearing all policies."""
        registry = PolicyRegistry()

        registry.register_policy(MockPolicy("policy1"), action_types=["action1"])
        registry.register_policy(MockPolicy("policy2"))
        registry.register_policy(MockPolicy("policy3"), action_types=["action2"])

        assert registry.policy_count() == 3

        registry.clear()

        assert registry.policy_count() == 0
        assert len(registry.get_policies_for_action("action1")) == 0

    def test_repr(self):
        """Test string representation."""
        registry = PolicyRegistry()

        registry.register_policy(MockPolicy("policy1"), action_types=["action1"])
        registry.register_policy(MockPolicy("policy2"))

        repr_str = repr(registry)

        assert "PolicyRegistry" in repr_str
        assert "policies=2" in repr_str
        assert "global=1" in repr_str


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_register_policy_with_empty_action_types(self):
        """Test registering policy with empty action types list."""
        registry = PolicyRegistry()
        policy = MockPolicy("test_policy")

        # Empty list should be treated as no action types (not global)
        registry.register_policy(policy, action_types=[])

        # Policy should be registered
        assert registry.policy_count() == 1

    def test_policy_registered_for_same_action_multiple_times(self):
        """Test that same policy can't be registered multiple times."""
        registry = PolicyRegistry()
        policy = MockPolicy("test_policy")

        registry.register_policy(policy, action_types=["action1"])

        # Should raise error on duplicate registration
        with pytest.raises(ValueError, match="already registered"):
            registry.register_policy(policy, action_types=["action2"])

    def test_global_policy_applies_to_all_actions(self):
        """Test global policy applies to any action type."""
        registry = PolicyRegistry()
        global_policy = MockPolicy("global")

        registry.register_policy(global_policy)

        # Should apply to any action type
        assert len(registry.get_policies_for_action("action1")) == 1
        assert len(registry.get_policies_for_action("action2")) == 1
        assert len(registry.get_policies_for_action("any_random_action")) == 1


# ============================================================================
# Test Integration Scenarios
# ============================================================================


class TestIntegration:
    """Test realistic integration scenarios."""

    def test_p0_p1_p2_priority_enforcement(self):
        """Test P0/P1/P2 priority levels are properly ordered."""
        registry = PolicyRegistry()

        # P0 = 200, P1 = 100, P2 = 50
        p0_security = MockPolicy("p0_security", priority=200)
        p1_validation = MockPolicy("p1_validation", priority=100)
        p2_optimization = MockPolicy("p2_optimization", priority=50)

        registry.register_policy(p2_optimization, action_types=["action1"])
        registry.register_policy(p0_security, action_types=["action1"])
        registry.register_policy(p1_validation, action_types=["action1"])

        policies = registry.get_policies_for_action("action1")

        # Should execute in order: P0, P1, P2
        assert policies[0].name == "p0_security"
        assert policies[1].name == "p1_validation"
        assert policies[2].name == "p2_optimization"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
