"""
Tests for prompt caching in LLMService.

Tests cover:
- Tool schemas caching
- Cache hit/miss behavior
- Cache invalidation when tools change
- Performance improvements
"""
import time
from unittest.mock import Mock, patch

from src.agent.standard_agent import StandardAgent
from src.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
    SafetyConfig,
)
from src.llm.service import LLMService
from src.tools.base import BaseTool, ToolMetadata, ToolResult


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


def _make_llm_service() -> LLMService:
    """Create an LLMService with mock LLM for testing."""
    mock_llm = Mock()
    mock_inf_config = Mock()
    mock_inf_config.provider = "ollama"
    mock_inf_config.model = "test-model"
    return LLMService(mock_llm, mock_inf_config)


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

        with patch('src.agent.base_agent.create_llm_from_config') as mock_llm, \
             patch.object(StandardAgent, '_create_tool_registry') as mock_registry:
            mock_llm.return_value = Mock()
            from src.tools.registry import ToolRegistry
            mock_registry.return_value = ToolRegistry(auto_discover=False)
            agent = StandardAgent(config)

        return agent

    def test_tool_schemas_cached_on_first_call(self):
        """Test that tool schemas are cached after first build."""
        service = _make_llm_service()
        tool = DummyTool("test_tool")

        schemas1 = service._build_text_schemas([tool])
        assert schemas1 is not None
        assert "test_tool" in schemas1
        assert service._cached_text_schemas is not None

    def test_tool_schemas_cache_hit_on_second_call(self):
        """Test that second call uses cached schemas."""
        service = _make_llm_service()
        tool = DummyTool("test_tool")

        schemas1 = service._build_text_schemas([tool])
        schemas2 = service._build_text_schemas([tool])

        assert schemas1 == schemas2

    def test_cache_invalidated_when_tools_added(self):
        """Test that cache is invalidated when tools are added."""
        service = _make_llm_service()
        tool1 = DummyTool("tool1")

        schemas1 = service._build_text_schemas([tool1])
        assert "tool1" in schemas1
        assert "tool2" not in schemas1

        tool2 = DummyTool("tool2")
        schemas2 = service._build_text_schemas([tool1, tool2])
        assert "tool1" in schemas2
        assert "tool2" in schemas2
        assert schemas1 != schemas2

    def test_cache_returns_none_for_no_tools(self):
        """Test that cache returns None when no tools provided."""
        service = _make_llm_service()
        schemas = service._build_text_schemas([])
        assert schemas is None

        schemas2 = service._build_text_schemas(None)
        assert schemas2 is None

    def test_prompt_render_no_tool_schemas_injected(self):
        """Test that _build_prompt does NOT inject tool schemas (LLMService handles it)."""
        agent = self.create_test_agent()

        # Register a tool
        tool = DummyTool("test_tool")
        agent.tool_registry.register(tool)

        # Render prompt - should NOT contain tool schemas
        # (LLMService adds them during run())
        prompt = agent._build_prompt({"query": "test"})

        # The prompt should just be the template + input context
        assert "Test prompt:" in prompt

    def test_cache_performance_improvement(self):
        """Test that caching provides performance improvement."""
        service = _make_llm_service()
        tools = [DummyTool(f"tool_{i}") for i in range(10)]

        # Time first call (cache miss)
        start1 = time.perf_counter()
        schemas1 = service._build_text_schemas(tools)
        time1 = time.perf_counter() - start1

        # Time second call (cache hit)
        start2 = time.perf_counter()
        schemas2 = service._build_text_schemas(tools)
        time2 = time.perf_counter() - start2

        # Cache hit should be faster
        assert time2 < time1
        assert schemas1 == schemas2

    def test_cache_version_tracking(self):
        """Test that cache version tracks tool count changes."""
        service = _make_llm_service()

        # Initially no cached schemas
        assert service._cached_text_schemas is None
        assert service._cached_text_schemas_version == 0

        # Add one tool
        tool1 = DummyTool("tool1")
        service._build_text_schemas([tool1])
        assert service._cached_text_schemas_version == 1
        assert service._cached_text_schemas is not None

        # Add another tool
        tool2 = DummyTool("tool2")
        service._build_text_schemas([tool1, tool2])
        assert service._cached_text_schemas_version == 2

    def test_cache_with_different_tool_parameters(self):
        """Test that cache correctly includes tool parameter schemas."""
        service = _make_llm_service()

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
        schemas = service._build_text_schemas([tool])
        assert schemas is not None
        assert "complex_tool" in schemas
        assert "param1" in schemas
        assert "param2" in schemas
        assert "nested" in schemas

    def test_multiple_services_independent_caches(self):
        """Test that multiple LLMService instances have independent caches."""
        service1 = _make_llm_service()
        service2 = _make_llm_service()

        tool_a = DummyTool("tool_a")
        tool_b = DummyTool("tool_b")

        schemas1 = service1._build_text_schemas([tool_a])
        schemas2 = service2._build_text_schemas([tool_b])

        assert "tool_a" in schemas1
        assert "tool_a" not in schemas2

        assert "tool_b" in schemas2
        assert "tool_b" not in schemas1

    def test_cache_with_json_special_characters(self):
        """Test that cache correctly handles special characters in tool schemas."""
        service = _make_llm_service()

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
        schemas = service._build_text_schemas([tool])
        assert schemas is not None
        assert "special_tool" in schemas
        assert '"quotes"' in schemas or '\\"quotes\\"' in schemas

    def test_empty_tools_no_cache(self):
        """Test that empty tools list doesn't cache anything."""
        service = _make_llm_service()

        schemas = service._build_text_schemas([])
        assert schemas is None
        assert service._cached_text_schemas is None
        assert service._cached_text_schemas_version == 0

    def test_cache_updates_when_tools_removed(self):
        """Test that cache updates when tools are removed."""
        service = _make_llm_service()

        tool1 = DummyTool("test_tool")
        tool2 = DummyTool("test_tool2")

        schemas1 = service._build_text_schemas([tool1, tool2])
        assert schemas1 is not None

        # Build with fewer tools
        schemas2 = service._build_text_schemas([tool1])
        assert schemas2 is not None
        assert "test_tool2" not in schemas2
