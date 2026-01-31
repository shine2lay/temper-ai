"""
Tests for prompt caching in StandardAgent.

Tests cover:
- Tool schemas caching
- Cache hit/miss behavior
- Cache invalidation when tools change
- Performance improvements
"""
import time
from unittest.mock import Mock, patch, MagicMock
import pytest

from src.agents.standard_agent import StandardAgent
from src.compiler.schemas import AgentConfig, AgentConfigInner, InferenceConfig, PromptConfig, SafetyConfig, ErrorHandlingConfig
from src.tools.base import BaseTool, ToolResult, ToolMetadata


class DummyTool(BaseTool):
    """Dummy tool for testing."""

    def __init__(self, name: str = "dummy_tool"):
        self._name = name
        super().__init__()

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A dummy tool for testing"

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="dummy result")

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "test_param": {"type": "string", "description": "Test parameter"}
            }
        }

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            version="1.0.0"
        )


class TestPromptCaching:
    """Tests for prompt caching functionality."""

    def create_test_agent(self) -> StandardAgent:
        """Create a test agent with minimal config."""
        config = AgentConfig(
            agent=AgentConfigInner(
                name="test_agent",
                description="Test agent",
                version="1.0.0",
                inference=InferenceConfig(
                    provider="ollama",
                    model="test-model",
                    base_url="http://localhost:11434",
                    temperature=0.7,
                    max_tokens=2048
                ),
                prompt=PromptConfig(
                    inline="Test prompt: {{ query }}"
                ),
                safety=SafetyConfig(
                    max_tool_calls_per_execution=5
                ),
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation"
                ),
                tools=[]
            )
        )

        with patch.object(StandardAgent, '_create_llm_provider') as mock_llm, \
             patch.object(StandardAgent, '_create_tool_registry') as mock_registry:
            mock_llm.return_value = Mock()
            from src.tools.registry import ToolRegistry
            mock_registry.return_value = ToolRegistry(auto_discover=False)
            agent = StandardAgent(config)

        return agent

    def test_tool_schemas_cached_on_first_call(self):
        """Test that tool schemas are cached after first render."""
        agent = self.create_test_agent()

        # Register a tool
        tool = DummyTool("test_tool")
        agent.tool_registry.register(tool)

        # First call should build cache
        schemas1 = agent._get_cached_tool_schemas()
        assert schemas1 is not None
        assert "test_tool" in schemas1
        assert agent._cached_tool_schemas is not None

    def test_tool_schemas_cache_hit_on_second_call(self):
        """Test that second call uses cached schemas."""
        agent = self.create_test_agent()

        # Register a tool
        tool = DummyTool("test_tool")
        agent.tool_registry.register(tool)

        # First call builds cache
        schemas1 = agent._get_cached_tool_schemas()

        # Mock the expensive operations to detect cache hit
        with patch.object(agent.tool_registry, 'get_all_tools', wraps=agent.tool_registry.get_all_tools) as mock_get:
            # Second call should use cache
            schemas2 = agent._get_cached_tool_schemas()

            assert schemas1 == schemas2
            # get_all_tools is called once to get count, but schemas not rebuilt
            assert mock_get.call_count == 1

    def test_cache_invalidated_when_tools_added(self):
        """Test that cache is invalidated when tools are added."""
        agent = self.create_test_agent()

        # Register first tool
        tool1 = DummyTool("tool1")
        agent.tool_registry.register(tool1)

        # Build cache
        schemas1 = agent._get_cached_tool_schemas()
        assert "tool1" in schemas1
        assert "tool2" not in schemas1

        # Add another tool
        tool2 = DummyTool("tool2")
        agent.tool_registry.register(tool2)

        # Cache should be invalidated and rebuilt
        schemas2 = agent._get_cached_tool_schemas()
        assert "tool1" in schemas2
        assert "tool2" in schemas2
        assert schemas1 != schemas2

    def test_cache_returns_none_for_no_tools(self):
        """Test that cache returns None when no tools registered."""
        agent = self.create_test_agent()

        schemas = agent._get_cached_tool_schemas()
        assert schemas is None

    def test_prompt_render_uses_cached_schemas(self):
        """Test that _render_prompt uses cached tool schemas."""
        agent = self.create_test_agent()

        # Register a tool
        tool = DummyTool("test_tool")
        agent.tool_registry.register(tool)

        # Render prompt twice
        prompt1 = agent._render_prompt({"query": "test"})
        prompt2 = agent._render_prompt({"query": "test"})

        # Both should contain the tool schema
        assert "test_tool" in prompt1
        assert "test_tool" in prompt2

        # Both should be identical (using cached schema)
        assert prompt1 == prompt2

    def test_cache_performance_improvement(self):
        """Test that caching provides performance improvement."""
        agent = self.create_test_agent()

        # Register multiple tools to make schema building expensive
        for i in range(10):
            tool = DummyTool(f"tool_{i}")
            agent.tool_registry.register(tool)

        # Time first call (cache miss)
        start1 = time.perf_counter()
        schemas1 = agent._get_cached_tool_schemas()
        time1 = time.perf_counter() - start1

        # Time second call (cache hit)
        start2 = time.perf_counter()
        schemas2 = agent._get_cached_tool_schemas()
        time2 = time.perf_counter() - start2

        # Cache hit should be faster
        assert time2 < time1
        # Cache hit should be at least 2x faster
        assert time2 < time1 * 0.5

        assert schemas1 == schemas2

    def test_cache_version_tracking(self):
        """Test that cache version tracks tool registry changes."""
        agent = self.create_test_agent()

        # Initially no tools
        assert agent._tool_registry_version == 0
        assert agent._cached_tool_schemas is None

        # Add one tool
        tool1 = DummyTool("tool1")
        agent.tool_registry.register(tool1)
        agent._get_cached_tool_schemas()

        assert agent._tool_registry_version == 1
        assert agent._cached_tool_schemas is not None

        # Add another tool
        tool2 = DummyTool("tool2")
        agent.tool_registry.register(tool2)
        agent._get_cached_tool_schemas()

        assert agent._tool_registry_version == 2

    def test_cache_with_different_tool_parameters(self):
        """Test that cache correctly includes tool parameter schemas."""
        agent = self.create_test_agent()

        # Create tool with complex parameters
        class ComplexTool(BaseTool):
            _name = "complex_tool"

            @property
            def name(self) -> str:
                return self._name

            @property
            def description(self) -> str:
                return "Complex tool"

            def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, result="ok")

            def get_parameters_schema(self) -> dict:
                return {
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string"},
                        "param2": {"type": "number"},
                        "param3": {
                            "type": "object",
                            "properties": {
                                "nested": {"type": "boolean"}
                            }
                        }
                    },
                    "required": ["param1"]
                }

            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name=self.name, description=self.description, version="1.0.0")

        tool = ComplexTool()
        agent.tool_registry.register(tool)

        schemas = agent._get_cached_tool_schemas()
        assert schemas is not None
        assert "complex_tool" in schemas
        assert "param1" in schemas
        assert "param2" in schemas
        assert "nested" in schemas

    def test_multiple_agents_independent_caches(self):
        """Test that multiple agents have independent caches."""
        agent1 = self.create_test_agent()
        agent2 = self.create_test_agent()

        # Register different tools for each agent
        tool1 = DummyTool("tool_a")
        agent1.tool_registry.register(tool1)

        tool2 = DummyTool("tool_b")
        agent2.tool_registry.register(tool2)

        # Build caches
        schemas1 = agent1._get_cached_tool_schemas()
        schemas2 = agent2._get_cached_tool_schemas()

        # Caches should be different
        assert "tool_a" in schemas1
        assert "tool_a" not in schemas2

        assert "tool_b" in schemas2
        assert "tool_b" not in schemas1

    def test_cache_with_json_special_characters(self):
        """Test that cache correctly handles special characters in tool schemas."""
        agent = self.create_test_agent()

        class SpecialTool(BaseTool):
            _name = "special_tool"

            @property
            def name(self) -> str:
                return self._name

            @property
            def description(self) -> str:
                return 'Tool with "quotes" and \\backslashes\\'

            def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, result="ok")

            def get_parameters_schema(self) -> dict:
                return {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": 'Parameter with "quotes"'
                        }
                    }
                }

            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(name=self.name, description=self.description, version="1.0.0")

        tool = SpecialTool()
        agent.tool_registry.register(tool)

        # Should not raise JSON encoding errors
        schemas = agent._get_cached_tool_schemas()
        assert schemas is not None
        assert "special_tool" in schemas
        assert '"quotes"' in schemas or '\\"quotes\\"' in schemas

    def test_empty_tool_registry_no_cache(self):
        """Test that empty tool registry doesn't cache anything."""
        agent = self.create_test_agent()

        # No tools registered
        schemas = agent._get_cached_tool_schemas()

        assert schemas is None
        assert agent._cached_tool_schemas is None
        assert agent._tool_registry_version == 0

    def test_cache_cleared_on_all_tools_removed(self):
        """Test that cache updates when all tools are removed."""
        agent = self.create_test_agent()

        # Register and cache
        tool = DummyTool("test_tool")
        agent.tool_registry.register(tool)
        schemas1 = agent._get_cached_tool_schemas()
        assert schemas1 is not None

        # Remove all tools (simulate clearing registry)
        agent.tool_registry._tools.clear()

        # Cache should return None
        schemas2 = agent._get_cached_tool_schemas()
        assert schemas2 is None
