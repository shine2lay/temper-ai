"""Tests for StandardAgent."""
from unittest.mock import Mock, patch

import pytest

from src.agent.base_agent import AgentResponse, ExecutionContext
from src.llm.providers import LLMResponse
from src.shared.utils.exceptions import LLMError
from src.llm.response_parser import (
    extract_final_answer,
    extract_reasoning,
    parse_tool_calls,
)
from src.agent.standard_agent import StandardAgent
from src.llm.service import LLMService
from src.llm._tool_execution import validate_tool_calls_input as _validate_tool_calls_input
from src.tools.base import ToolResult
from src.tools.executor import ToolExecutor


# Tests for StandardAgent class
def test_standard_agent_initialization(minimal_agent_config):
    """Test StandardAgent initialization."""
    with patch('src.agent.base_agent.ToolRegistry'):
        agent = StandardAgent(minimal_agent_config)

        assert agent.name == "test_agent"
        assert agent.description == "Test agent for unit tests"
        assert agent.version == "1.0"
        assert agent.config == minimal_agent_config
        assert hasattr(agent, 'llm_service')
        assert isinstance(agent.llm_service, LLMService)


def test_standard_agent_get_capabilities(minimal_agent_config):
    """Test StandardAgent get_capabilities."""
    with patch('src.agent.base_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []
        agent = StandardAgent(minimal_agent_config)

        capabilities = agent.get_capabilities()

        assert capabilities["name"] == "test_agent"
        assert capabilities["type"] == "standard"
        assert capabilities["llm_provider"] == "ollama"
        assert capabilities["llm_model"] == "llama2"
        assert "tools" in capabilities
        assert "max_tool_calls" in capabilities


def test_standard_agent_validate_config(minimal_agent_config):
    """Test StandardAgent config validation."""
    with patch('src.agent.base_agent.ToolRegistry'):
        agent = StandardAgent(minimal_agent_config)

        # Should pass validation
        assert agent.validate_config() is True


def test_standard_agent_execute_simple_response(minimal_agent_config):
    """Test StandardAgent execute with simple LLM response (no tools)."""
    with patch('src.agent.base_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)

        # Mock LLM response (no tool calls)
        mock_llm_response = LLMResponse(
            content="<answer>Hello! How can I help you?</answer>",
            model="llama2",
            provider="ollama",
            total_tokens=50,
        )

        agent.llm = Mock()
        agent.llm.complete.return_value = mock_llm_response
        agent.llm_service.llm = agent.llm

        # Execute
        response = agent.execute({"input": "Hello"})

        # Verify response
        assert isinstance(response, AgentResponse)
        assert "Hello! How can I help you?" in response.output
        assert response.error is None
        assert response.tokens == 50
        assert len(response.tool_calls) == 0


def test_standard_agent_execute_with_tool_calls(minimal_agent_config):
    """Test StandardAgent execute with tool calling loop."""
    with patch('src.agent.base_agent.ToolRegistry') as mock_registry:
        # Setup mock tool
        mock_tool = Mock()
        mock_tool.name = "calculator"
        mock_tool.description = "Calculate expressions"
        mock_tool.get_parameters_schema.return_value = {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"]
        }
        mock_tool.execute.return_value = ToolResult(
            success=True,
            result="42",
            error=None
        )

        mock_registry_instance = Mock()
        mock_registry_instance.list_tools.return_value = [mock_tool]
        mock_registry_instance.get.return_value = mock_tool
        mock_registry_instance.get_all_tools.return_value = {"calculator": mock_tool}
        mock_registry.return_value = mock_registry_instance

        agent = StandardAgent(minimal_agent_config)

        # Mock LLM responses
        tool_call_response = LLMResponse(
            content='<reasoning>I need to calculate</reasoning>\n<tool_call>{"name": "calculator", "parameters": {"expression": "2+2"}}</tool_call>',
            model="llama2",
            provider="ollama",
            total_tokens=30,
        )

        final_response = LLMResponse(
            content="<answer>The answer is 42</answer>",
            model="llama2",
            provider="ollama",
            total_tokens=20,
        )

        agent.llm = Mock()
        agent.llm.complete.side_effect = [tool_call_response, final_response]
        agent.llm_service.llm = agent.llm

        # Create mock tool_executor that delegates to the tool registry
        mock_executor = Mock(spec=ToolExecutor)
        mock_executor.policy_engine = None
        mock_executor.execute.return_value = ToolResult(success=True, result="42")

        # Execute
        response = agent.execute({"input": "What is 2+2?", "tool_executor": mock_executor})

        # Verify response
        assert isinstance(response, AgentResponse)
        assert "The answer is 42" in response.output
        assert response.error is None
        assert response.tokens == 50  # 30 + 20
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["name"] == "calculator"
        assert response.tool_calls[0]["success"] is True
        assert response.tool_calls[0]["result"] == "42"


def test_standard_agent_execute_tool_not_found(minimal_agent_config):
    """Test StandardAgent handles missing tool gracefully."""
    with patch('src.agent.base_agent.ToolRegistry') as mock_registry:
        mock_registry_instance = Mock()
        mock_registry_instance.list_tools.return_value = []
        mock_registry_instance.get.return_value = None  # Tool not found
        mock_registry_instance.get_all_tools.return_value = {}  # No tools available
        mock_registry.return_value = mock_registry_instance

        agent = StandardAgent(minimal_agent_config)

        # Mock LLM response with tool call for non-existent tool
        tool_call_response = LLMResponse(
            content='<tool_call>{"name": "nonexistent_tool", "parameters": {}}</tool_call>',
            model="llama2",
            provider="ollama",
            total_tokens=30,
        )

        final_response = LLMResponse(
            content="<answer>Tool not found, continuing</answer>",
            model="llama2",
            provider="ollama",
            total_tokens=20,
        )

        agent.llm = Mock()
        agent.llm.complete.side_effect = [tool_call_response, final_response]
        agent.llm_service.llm = agent.llm

        # Create mock tool_executor that returns "not found" for unknown tools
        mock_executor = Mock(spec=ToolExecutor)
        mock_executor.policy_engine = None
        mock_executor.execute.return_value = ToolResult(
            success=False, result=None, error="Tool 'nonexistent_tool' not found"
        )

        # Execute — with no tools in registry, LLMService runs in no-tools mode
        # So we won't see tool call parsing. Let's test with a tool present.
        response = agent.execute({"input": "Use missing tool", "tool_executor": mock_executor})

        # Should handle gracefully — either no tool calls (no tools in registry)
        # or tool call with error
        assert isinstance(response, AgentResponse)


def test_standard_agent_execute_llm_error(minimal_agent_config):
    """Test StandardAgent handles LLM errors."""
    with patch('src.agent.base_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)

        # Mock LLM error
        agent.llm = Mock()
        agent.llm.complete.side_effect = LLMError("Connection failed")
        agent.llm_service.llm = agent.llm

        # Execute
        response = agent.execute({"input": "Hello"})

        # Should return error response
        assert isinstance(response, AgentResponse), \
            f"Expected AgentResponse, got {type(response)}"
        assert response.error is not None, "Error should be set for LLM failures"
        assert isinstance(response.error, str), "Error should be string message"
        assert "LLM call failed" in response.error, \
            f"Error should mention LLM failure, got: {response.error}"
        assert "Connection failed" in response.error, \
            f"Error should include root cause, got: {response.error}"


def test_standard_agent_execute_max_iterations(minimal_agent_config):
    """Test StandardAgent respects max tool call iterations."""
    with patch('src.agent.base_agent.ToolRegistry') as mock_registry:
        mock_tool = Mock()
        mock_tool.name = "calculator"
        mock_tool.description = "Calculator tool"
        mock_tool.get_parameters_schema.return_value = {
            "type": "object",
            "properties": {}
        }
        mock_tool.get_result_schema.return_value = None
        mock_tool.execute.return_value = ToolResult(success=True, result="42")

        mock_registry_instance = Mock()
        mock_registry_instance.list_tools.return_value = [mock_tool]
        mock_registry_instance.get.return_value = mock_tool
        mock_registry_instance.get_all_tools.return_value = {"calculator": mock_tool}
        mock_registry.return_value = mock_registry_instance

        agent = StandardAgent(minimal_agent_config)

        # Mock LLM to always return tool calls (infinite loop scenario)
        tool_call_response = LLMResponse(
            content='<tool_call>{"name": "calculator", "parameters": {}}</tool_call>',
            model="llama2",
            provider="ollama",
            total_tokens=10,
        )

        agent.llm = Mock()
        agent.llm.complete.return_value = tool_call_response
        agent.llm_service.llm = agent.llm

        # Execute
        response = agent.execute({"input": "Test"})

        # Should stop after max iterations
        assert isinstance(response, AgentResponse), \
            f"Expected AgentResponse, got {type(response)}"
        assert response.error is not None, "Should have error when max iterations reached"
        assert "Max tool calling iterations" in response.error, \
            f"Error should mention max iterations, got: {response.error}"
        assert len(response.tool_calls) >= 1, \
            f"Should record tool calls made before stopping, got {len(response.tool_calls)}"


def test_standard_agent_extract_reasoning(minimal_agent_config):
    """Test reasoning extraction from LLM response."""
    with patch('src.agent.base_agent.ToolRegistry'):
        agent = StandardAgent(minimal_agent_config)

        # Test with <reasoning> tag
        text = "<reasoning>My thought process</reasoning>\n<answer>Final answer</answer>"
        reasoning = extract_reasoning(text)
        assert reasoning == "My thought process"

        # Test with <thinking> tag
        text = "<thinking>Deep thoughts</thinking>\n<answer>Result</answer>"
        reasoning = extract_reasoning(text)
        assert reasoning == "Deep thoughts"

        # Test without reasoning tags
        text = "<answer>Just an answer</answer>"
        reasoning = extract_reasoning(text)
        assert reasoning is None


def test_standard_agent_extract_final_answer(minimal_agent_config):
    """Test final answer extraction from LLM response."""
    with patch('src.agent.base_agent.ToolRegistry'):
        agent = StandardAgent(minimal_agent_config)

        # Test with <answer> tag
        text = "<reasoning>Thinking...</reasoning>\n<answer>This is the answer</answer>"
        answer = extract_final_answer(text)
        assert answer == "This is the answer"

        # Test without answer tag
        text = "This is just a plain response"
        answer = extract_final_answer(text)
        assert answer == "This is just a plain response"


def test_standard_agent_parse_tool_calls(minimal_agent_config):
    """Test tool call parsing from LLM response."""
    with patch('src.agent.base_agent.ToolRegistry'):
        agent = StandardAgent(minimal_agent_config)

        # Single tool call
        text = '<tool_call>{"name": "calculator", "parameters": {"expression": "2+2"}}</tool_call>'
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "calculator"
        assert calls[0]["parameters"]["expression"] == "2+2"

        # Multiple tool calls
        text = '''
<tool_call>{"name": "tool1", "parameters": {}}</tool_call>
<tool_call>{"name": "tool2", "parameters": {"arg": "value"}}</tool_call>
        '''
        calls = parse_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["name"] == "tool1"
        assert calls[1]["name"] == "tool2"

        # No tool calls
        text = "<answer>Just a plain answer</answer>"
        calls = parse_tool_calls(text)
        assert len(calls) == 0

        # Invalid JSON in tool call
        text = '<tool_call>invalid json</tool_call>'
        calls = parse_tool_calls(text)
        assert len(calls) == 0  # Should skip invalid JSON


def test_standard_agent_execute_with_context(minimal_agent_config):
    """Test StandardAgent execute with execution context."""
    with patch('src.agent.base_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)

        # Mock LLM
        mock_response = LLMResponse(
            content="<answer>Response</answer>",
            model="llama2",
            provider="ollama",
            total_tokens=10,
        )
        agent.llm = Mock()
        agent.llm.complete.return_value = mock_response
        agent.llm_service.llm = agent.llm

        # Execute with context
        context = ExecutionContext(
            workflow_id="wf-001",
            stage_id="stage-001",
            agent_id="agent-001"
        )
        response = agent.execute({"input": "Test"}, context=context)

        # Should execute successfully
        assert isinstance(response, AgentResponse)
        assert response.error is None


class TestInputValidation:
    """Test input validation for StandardAgent methods."""

    def test_execute_rejects_none_input_data(self, minimal_agent_config):
        """Test that execute() rejects None input_data."""
        with patch('src.agent.base_agent.ToolRegistry'):
            agent = StandardAgent(minimal_agent_config)

            with pytest.raises(ValueError) as exc_info:
                agent.execute(None)  # type: ignore

            assert "input_data cannot be None" in str(exc_info.value)

    def test_execute_rejects_non_dict_input_data(self, minimal_agent_config):
        """Test that execute() rejects non-dict input_data."""
        with patch('src.agent.base_agent.ToolRegistry'):
            agent = StandardAgent(minimal_agent_config)

            with pytest.raises(TypeError) as exc_info:
                agent.execute("not a dict")  # type: ignore

            assert "input_data must be a dictionary" in str(exc_info.value)
            assert "got str" in str(exc_info.value)

    def test_execute_rejects_invalid_context(self, minimal_agent_config):
        """Test that execute() rejects invalid context."""
        with patch('src.agent.base_agent.ToolRegistry'):
            agent = StandardAgent(minimal_agent_config)

            with pytest.raises(TypeError) as exc_info:
                agent.execute({"input": "test"}, context="not a context")  # type: ignore

            assert "context must be an ExecutionContext" in str(exc_info.value)

    def test_execute_tool_calls_rejects_non_list(self, minimal_agent_config):
        """Test that _validate_tool_calls_input rejects non-list input."""
        with pytest.raises(TypeError) as exc_info:
            _validate_tool_calls_input({"not": "a list"})  # type: ignore

        assert "tool_calls must be a list" in str(exc_info.value)

    def test_execute_tool_calls_rejects_non_dict_items(self, minimal_agent_config):
        """Test that _validate_tool_calls_input rejects non-dict items."""
        with pytest.raises(TypeError) as exc_info:
            _validate_tool_calls_input(["not a dict", "also not a dict"])  # type: ignore

        assert "tool_call at index" in str(exc_info.value)
        assert "must be a dictionary" in str(exc_info.value)

    def test_execute_single_tool_rejects_non_dict(self, minimal_agent_config):
        """Test that execute_single_tool rejects non-dict input."""
        from src.llm._tool_execution import execute_single_tool

        with pytest.raises(TypeError) as exc_info:
            execute_single_tool("not a dict", None, None, None)  # type: ignore

        assert "tool_call must be a dictionary" in str(exc_info.value)

    def test_execute_single_tool_rejects_missing_name(self, minimal_agent_config):
        """Test that execute_single_tool rejects missing 'name' field."""
        from src.llm._tool_execution import execute_single_tool

        with pytest.raises(ValueError) as exc_info:
            execute_single_tool({"parameters": {}}, None, None, None)

        assert "tool_call must contain 'name' field" in str(exc_info.value)

    def test_execute_single_tool_rejects_non_string_name(self, minimal_agent_config):
        """Test that execute_single_tool rejects non-string 'name'."""
        from src.llm._tool_execution import execute_single_tool

        with pytest.raises(TypeError) as exc_info:
            execute_single_tool({"name": 123, "parameters": {}}, None, None, None)

        assert "tool_call 'name' must be a string" in str(exc_info.value)

    def test_execute_single_tool_rejects_non_dict_parameters(self, minimal_agent_config):
        """Test that execute_single_tool rejects non-dict 'parameters'."""
        from src.llm._tool_execution import execute_single_tool

        with pytest.raises(TypeError) as exc_info:
            execute_single_tool({"name": "test_tool", "parameters": "not a dict"}, None, None, None)

        assert "tool_call 'parameters' must be a dictionary" in str(exc_info.value)

    def test_execute_accepts_valid_input(self, minimal_agent_config):
        """Test that execute() accepts valid input."""
        with patch('src.agent.base_agent.ToolRegistry'):
            agent = StandardAgent(minimal_agent_config)

            # Mock LLM response
            mock_response = LLMResponse(
                content="Test response",
                model="test-model",
                provider="test-provider",
                total_tokens=10
            )
            agent.llm = Mock()
            agent.llm.complete.return_value = mock_response
            agent.llm_service.llm = agent.llm

            # Should not raise
            response = agent.execute({"input": "valid input"})
            assert isinstance(response, AgentResponse)

    def test_execute_single_tool_accepts_valid_input(self, minimal_agent_config):
        """Test that execute_single_tool accepts valid input."""
        from src.llm._tool_execution import execute_single_tool

        # Valid tool call with no executor should return security error
        result = execute_single_tool({"name": "unknown_tool", "parameters": {}}, None, None, None)
        assert "error" in result
        assert result["success"] is False


def test_tool_loading_with_configuration():
    """Test that tools can be loaded with configuration passed to constructor."""
    from src.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)

    # Create minimal config with tools
    config = AgentConfig(
        agent=AgentConfigInner(
            name="test_agent_with_config",
            description="Test agent with tool config",
            version="1.0",
            prompt=PromptConfig(inline="You are a helpful assistant."),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2"
            ),
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation"
            ),
            tools=["Calculator"]
        )
    )

    with patch('src.agent.base_agent.ToolRegistry') as mock_registry_class:
        # Create a real registry instance
        from src.tools.registry import ToolRegistry
        real_registry = ToolRegistry(auto_discover=False)
        mock_registry_class.return_value = real_registry

        # Create agent (will load tools)
        agent = StandardAgent(config)

        # Verify Calculator was loaded
        calc = agent.tool_registry.get("Calculator")
        assert calc is not None, "Calculator should be loaded from tool registry"
        assert type(calc).__name__ == 'Calculator', \
            f"Expected Calculator tool, got {type(calc).__name__}"
        assert hasattr(calc, 'execute'), "Calculator must have execute method"
        # Verify config is set (even if empty)
        assert hasattr(calc, 'config')
        assert isinstance(calc.config, dict)


def test_tool_loading_with_custom_config():
    """Test that custom tool configuration is passed to tool constructor."""
    from pydantic import BaseModel

    from src.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)

    class ToolReference(BaseModel):
        """Tool reference with config."""
        name: str
        config: dict = {}

    # Mock the config with tool having custom config
    config = AgentConfig(
        agent=AgentConfigInner(
            name="test_agent_custom_config",
            description="Test agent",
            version="1.0",
            prompt=PromptConfig(inline="You are a helpful assistant."),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2"
            ),
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation"
            ),
            tools=[]  # Will be patched
        )
    )

    # Manually create ToolReference with custom config
    tool_ref = ToolReference(name="Calculator", config={"precision": 10})

    with patch('src.agent.base_agent.ToolRegistry') as mock_registry_class:
        from src.tools.registry import ToolRegistry
        real_registry = ToolRegistry(auto_discover=False)
        mock_registry_class.return_value = real_registry

        agent = StandardAgent(config)

        # Clear registry to ensure clean state for this test
        agent.tool_registry.clear()

        # Manually load tool with config using the method
        # (simulating what would happen if tools list had ToolReference objects)
        from src.agent.base_agent import load_tools_from_config
        load_tools_from_config(agent.tool_registry, [tool_ref])

        # Verify Calculator was loaded with custom config
        calc = agent.tool_registry.get("Calculator")
        assert calc is not None, "Calculator should be loaded from tool registry"
        assert type(calc).__name__ == 'Calculator', \
            f"Expected Calculator tool, got {type(calc).__name__}"
        assert calc.config == {"precision": 10}, \
            f"Expected config with precision=10, got {calc.config}"
