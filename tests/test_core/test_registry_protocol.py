"""Tests for Registry Protocol conformance.

This test module validates that ToolRegistry and PolicyRegistry
satisfy the Registry Protocol interface.
"""
import pytest
from unittest.mock import Mock

from src.core.protocols import Registry
from src.tools.registry import ToolRegistry
from src.tools.base import BaseTool, ToolMetadata, ToolResult
from src.safety.policy_registry import PolicyRegistry
from src.safety.interfaces import SafetyPolicy, ValidationResult


class MockTool(BaseTool):
    """Mock tool for testing."""

    def __init__(self, name: str = "mock_tool", version: str = "1.0.0"):
        self._name = name
        self._version = version

    @property
    def name(self) -> str:
        return self._name

    def execute(self, **kwargs):
        return ToolResult(success=True, data={"result": "mock"})

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self._name,
            description="Mock tool for testing",
            version=self._version,
            category="test",
        )

    def get_parameters_schema(self):
        return {"type": "object", "properties": {}}


class MockPolicy:
    """Mock policy for testing."""

    def __init__(self, name: str = "mock_policy", priority: int = 100):
        self.name = name
        self.priority = priority

    def validate(self, action_type: str, action_data: dict) -> ValidationResult:
        return ValidationResult(allowed=True)

    async def validate_async(self, action_type: str, action_data: dict) -> ValidationResult:
        return ValidationResult(allowed=True)


class TestRegistryProtocol:
    """Test that registries satisfy the Registry Protocol."""

    def test_tool_registry_is_registry_instance(self):
        """ToolRegistry should be recognized as a Registry instance."""
        registry = ToolRegistry()
        assert isinstance(registry, Registry)

    def test_policy_registry_is_registry_instance(self):
        """PolicyRegistry should be recognized as a Registry instance."""
        registry = PolicyRegistry()
        assert isinstance(registry, Registry)

    def test_tool_registry_get(self):
        """ToolRegistry.get() should return registered tools."""
        registry = ToolRegistry()
        tool = MockTool(name="test_tool", version="1.0.0")
        registry.register(tool)

        # Test get method (Registry Protocol)
        retrieved = registry.get("test_tool")
        assert retrieved is not None
        assert retrieved.name == "test_tool"

        # Test get nonexistent
        assert registry.get("nonexistent") is None

    def test_policy_registry_get(self):
        """PolicyRegistry.get() should return registered policies."""
        registry = PolicyRegistry()
        policy = MockPolicy(name="test_policy")
        registry.register_policy(policy)

        # Test get method (Registry Protocol)
        retrieved = registry.get("test_policy")
        assert retrieved is not None
        assert retrieved.name == "test_policy"

        # Test get nonexistent
        assert registry.get("nonexistent") is None

    def test_tool_registry_list_all(self):
        """ToolRegistry.list_all() should return all tool names."""
        registry = ToolRegistry()
        tool1 = MockTool(name="tool1", version="1.0.0")
        tool2 = MockTool(name="tool2", version="1.0.0")
        registry.register(tool1)
        registry.register(tool2)

        # Test list_all method (Registry Protocol)
        names = registry.list_all()
        assert isinstance(names, list)
        assert "tool1" in names
        assert "tool2" in names
        assert len(names) == 2

    def test_policy_registry_list_all(self):
        """PolicyRegistry.list_all() should return all policy names."""
        registry = PolicyRegistry()
        policy1 = MockPolicy(name="policy1")
        policy2 = MockPolicy(name="policy2")
        registry.register_policy(policy1)
        registry.register_policy(policy2)

        # Test list_all method (Registry Protocol)
        names = registry.list_all()
        assert isinstance(names, list)
        assert "policy1" in names
        assert "policy2" in names
        assert len(names) == 2

    def test_tool_registry_count(self):
        """ToolRegistry.count() should return number of registered tools."""
        registry = ToolRegistry()

        # Empty registry
        assert registry.count() == 0

        # Add tools
        tool1 = MockTool(name="tool1", version="1.0.0")
        tool2 = MockTool(name="tool2", version="1.0.0")
        registry.register(tool1)
        registry.register(tool2)

        assert registry.count() == 2

        # Add another version of tool1
        tool1_v2 = MockTool(name="tool1", version="2.0.0")
        registry.register(tool1_v2)

        # Count should include all versions
        assert registry.count() == 3

    def test_policy_registry_count(self):
        """PolicyRegistry.count() should return number of registered policies."""
        registry = PolicyRegistry()

        # Empty registry
        assert registry.count() == 0

        # Add policies
        policy1 = MockPolicy(name="policy1")
        policy2 = MockPolicy(name="policy2")
        registry.register_policy(policy1)
        registry.register_policy(policy2)

        assert registry.count() == 2

    def test_tool_registry_get_with_version(self):
        """ToolRegistry.get() should support version parameter."""
        registry = ToolRegistry()
        tool_v1 = MockTool(name="tool", version="1.0.0")
        tool_v2 = MockTool(name="tool", version="2.0.0")
        registry.register(tool_v1)
        registry.register(tool_v2)

        # Get latest version (no version specified)
        latest = registry.get("tool")
        assert latest is not None
        assert latest.get_metadata().version == "2.0.0"

        # Get specific version
        v1 = registry.get("tool", version="1.0.0")
        assert v1 is not None
        assert v1.get_metadata().version == "1.0.0"

    def test_empty_registries_satisfy_protocol(self):
        """Empty registries should still satisfy the Protocol."""
        tool_registry = ToolRegistry()
        policy_registry = PolicyRegistry()

        # Both should be recognized as Registry instances
        assert isinstance(tool_registry, Registry)
        assert isinstance(policy_registry, Registry)

        # All methods should work on empty registries
        assert tool_registry.get("anything") is None
        assert tool_registry.list_all() == []
        assert tool_registry.count() == 0

        assert policy_registry.get("anything") is None
        assert policy_registry.list_all() == []
        assert policy_registry.count() == 0


class TestRegistryProtocolEdgeCases:
    """Test edge cases for Registry Protocol conformance."""

    def test_duplicate_registration_tool(self):
        """Test duplicate tool registration behavior."""
        registry = ToolRegistry()
        tool1 = MockTool(name="tool", version="1.0.0")
        tool2 = MockTool(name="tool", version="1.0.0")  # Same name and version

        registry.register(tool1)

        # Should raise error without allow_override
        with pytest.raises(Exception):
            registry.register(tool2, allow_override=False)

        # Should succeed with allow_override
        registry.register(tool2, allow_override=True)
        assert registry.count() == 1  # Still only 1 version

    def test_duplicate_registration_policy(self):
        """Test duplicate policy registration behavior."""
        registry = PolicyRegistry()
        policy1 = MockPolicy(name="policy")
        policy2 = MockPolicy(name="policy")  # Same name

        registry.register_policy(policy1)

        # Should raise error
        with pytest.raises(ValueError, match="already registered"):
            registry.register_policy(policy2)

    def test_get_nonexistent_returns_none(self):
        """Test that get() returns None for nonexistent items."""
        tool_registry = ToolRegistry()
        policy_registry = PolicyRegistry()

        assert tool_registry.get("nonexistent") is None
        assert policy_registry.get("nonexistent") is None

    def test_list_all_order(self):
        """Test list_all() ordering behavior."""
        # ToolRegistry - list_all() returns unordered list
        tool_registry = ToolRegistry()
        for name in ["zebra", "apple", "banana"]:
            tool_registry.register(MockTool(name=name))

        tool_names = tool_registry.list_all()
        assert len(tool_names) == 3
        assert set(tool_names) == {"zebra", "apple", "banana"}

        # PolicyRegistry - list_all() returns sorted list
        policy_registry = PolicyRegistry()
        for name in ["zebra", "apple", "banana"]:
            policy_registry.register_policy(MockPolicy(name=name))

        policy_names = policy_registry.list_all()
        assert policy_names == ["apple", "banana", "zebra"]  # Sorted

    def test_count_consistency(self):
        """Test that count() is consistent with list_all() length."""
        # For unique items (policies), count should match list_all length
        policy_registry = PolicyRegistry()
        for i in range(5):
            policy_registry.register_policy(MockPolicy(name=f"policy{i}"))

        assert policy_registry.count() == len(policy_registry.list_all())

        # For tools with versions, count may be > list_all length
        tool_registry = ToolRegistry()
        tool_registry.register(MockTool(name="tool1", version="1.0.0"))
        tool_registry.register(MockTool(name="tool1", version="2.0.0"))
        tool_registry.register(MockTool(name="tool2", version="1.0.0"))

        assert tool_registry.count() == 3  # 3 versions total
        assert len(tool_registry.list_all()) == 2  # 2 unique tool names


class TestRegistryProtocolTypeChecking:
    """Test type checking with Registry Protocol."""

    def test_function_accepting_registry_protocol(self):
        """Test that a function accepting Registry[T] works with both registries."""

        def process_registry(registry: Registry) -> int:
            """Function that accepts any Registry."""
            return registry.count()

        tool_registry = ToolRegistry()
        tool_registry.register(MockTool(name="tool1"))

        policy_registry = PolicyRegistry()
        policy_registry.register_policy(MockPolicy(name="policy1"))

        # Both should work with the generic function
        assert process_registry(tool_registry) == 1
        assert process_registry(policy_registry) == 1

    def test_mock_registry_satisfies_protocol(self):
        """Test that a mock object with Registry methods satisfies the Protocol."""

        class MockRegistry:
            """Minimal mock registry."""

            def get(self, name: str):
                return None if name != "exists" else "item"

            def list_all(self):
                return ["item1", "item2"]

            def count(self):
                return 2

        mock_registry = MockRegistry()
        assert isinstance(mock_registry, Registry)

        # Should have all required methods
        assert mock_registry.get("exists") == "item"
        assert mock_registry.get("missing") is None
        assert mock_registry.list_all() == ["item1", "item2"]
        assert mock_registry.count() == 2
