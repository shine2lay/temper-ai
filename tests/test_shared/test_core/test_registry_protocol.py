"""Tests for DomainToolRegistryProtocol conformance.

This test module validates that ToolRegistry satisfies the
DomainToolRegistryProtocol interface.
"""

from temper_ai.shared.core.protocols import DomainToolRegistryProtocol
from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.registry import ToolRegistry


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


class TestDomainToolRegistryProtocolConformance:
    """Test ToolRegistry conformance to DomainToolRegistryProtocol (C-04 fix)."""

    def test_tool_registry_satisfies_tool_registry_protocol(self):
        """ToolRegistry should satisfy DomainToolRegistryProtocol (C-04)."""
        registry = ToolRegistry()
        # Verify it's recognized as DomainToolRegistryProtocol instance
        assert isinstance(registry, DomainToolRegistryProtocol)

    def test_tool_registry_protocol_get_signature(self):
        """ToolRegistry.get() signature matches DomainToolRegistryProtocol (C-04)."""
        registry = ToolRegistry()
        tool = MockTool(name="test_tool", version="1.0.0")
        registry.register(tool)

        # Test get with name only (version defaults to None)
        retrieved = registry.get("test_tool")
        assert retrieved is not None
        assert retrieved.name == "test_tool"

        # Test get with explicit version
        retrieved_v1 = registry.get("test_tool", version="1.0.0")
        assert retrieved_v1 is not None
        assert retrieved_v1.get_metadata().version == "1.0.0"

        # Test get nonexistent
        assert registry.get("nonexistent") is None
        assert registry.get("nonexistent", version="1.0.0") is None

    def test_tool_registry_protocol_any_implementation(self):
        """Any class with get(name, version=None) satisfies DomainToolRegistryProtocol."""

        class MinimalToolRegistry:
            """Minimal implementation of DomainToolRegistryProtocol."""

            def __init__(self):
                self._tools = {}

            def get(self, name: str, version=None):
                """Minimal get implementation."""
                return self._tools.get(name)

        minimal_registry = MinimalToolRegistry()
        # Should satisfy the protocol
        assert isinstance(minimal_registry, DomainToolRegistryProtocol)

        # Should work with protocol-typed functions
        def use_registry(reg: DomainToolRegistryProtocol):
            return reg.get("test")

        assert use_registry(minimal_registry) is None
