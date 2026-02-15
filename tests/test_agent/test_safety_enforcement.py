"""Tests for SafetyConfig enforcement in StandardAgent.

Tests verify that SafetyConfig fields (mode, require_approval_for_tools,
max_execution_time_seconds) are actually enforced during tool execution.
"""
import time
from unittest.mock import MagicMock, patch

from src.llm.providers import LLMResponse
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
from src.llm._tool_execution import check_safety_mode as _check_safety_mode
from src.tools.base import ToolResult


def _make_config(safety: SafetyConfig = None) -> AgentConfig:
    """Create agent config with custom safety settings."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="test_agent",
            description="Test agent",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="You are a helper. {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
                temperature=0.7,
                max_tokens=2048,
            ),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
            safety=safety or SafetyConfig(),
        )
    )


def _make_agent(safety: SafetyConfig = None) -> StandardAgent:
    """Create a StandardAgent with mocked dependencies and custom safety."""
    with patch('src.agent.base_agent.ToolRegistry'):
        agent = StandardAgent(_make_config(safety))

    # Build a mock tool with all methods LLMService needs for schema building
    mock_tool = MagicMock()
    mock_tool.name = "bash"
    mock_tool.description = "Execute commands"
    mock_tool.get_parameters_schema.return_value = {"type": "object", "properties": {}}
    mock_tool.get_result_schema.return_value = None
    mock_tool.execute.return_value = ToolResult(
        success=True, result="tool output"
    )
    agent.tool_registry.get = lambda name: mock_tool if name == "bash" else None
    agent.tool_registry.get_all_tools = MagicMock(return_value={"bash": mock_tool})

    # Provide a mock tool_executor so execution doesn't block on missing safety stack
    mock_executor = MagicMock()
    mock_executor.execute.return_value = ToolResult(success=True, result="tool output")
    agent.tool_executor = mock_executor

    # Provide a mock observer (normally set in execute(), needed for direct calls)
    mock_observer = MagicMock()
    mock_observer.active = False  # Prevent streaming path from activating
    agent._observer = mock_observer
    # Streaming not used in tests — set to None to avoid triggering stream()
    agent._stream_callback = None
    return agent


def _make_llm_service_and_execute_single(
    safety: SafetyConfig,
    tool_call: dict,
) -> dict:
    """Execute a single tool call with given safety config via module-level function."""
    from src.llm._tool_execution import execute_single_tool

    mock_executor = MagicMock()
    mock_executor.execute.return_value = ToolResult(success=True, result="tool output")

    return execute_single_tool(
        tool_call, mock_executor, None, safety,
    )


class TestRequireApprovalMode:
    """Test that require_approval mode blocks all tool execution."""

    def test_require_approval_blocks_tool(self):
        """Tools are blocked when mode is 'require_approval'."""
        result = _make_llm_service_and_execute_single(
            SafetyConfig(mode="require_approval"),
            {"name": "bash", "parameters": {"command": "ls"}},
        )
        assert result["success"] is False
        assert "blocked" in result["error"]
        assert "require_approval" in result["error"]

    def test_require_approval_blocks_any_tool(self):
        """All tools are blocked, not just specific ones."""
        safety = SafetyConfig(mode="require_approval")
        for tool_name in ["bash", "calculator", "web_scraper"]:
            result = _make_llm_service_and_execute_single(
                safety,
                {"name": tool_name, "parameters": {}},
            )
            assert result["success"] is False
            assert "require_approval" in result["error"]

    def test_require_approval_does_not_execute(self):
        """Tool.execute() is never called in require_approval mode."""
        from src.llm._tool_execution import execute_single_tool

        mock_executor = MagicMock()
        execute_single_tool(
            {"name": "bash", "parameters": {"command": "rm -rf /"}},
            mock_executor, None, SafetyConfig(mode="require_approval"),
        )
        mock_executor.execute.assert_not_called()


class TestDryRunMode:
    """Test that dry_run mode returns simulated result without executing."""

    def test_dry_run_returns_simulated_result(self):
        """Dry run returns success with simulated output."""
        result = _make_llm_service_and_execute_single(
            SafetyConfig(mode="dry_run"),
            {"name": "bash", "parameters": {"command": "ls"}},
        )
        assert result["success"] is True
        assert "[DRY RUN]" in result["result"]
        assert "bash" in result["result"]
        assert result["error"] is None

    def test_dry_run_does_not_execute(self):
        """Tool.execute() is never called in dry_run mode."""
        from src.llm._tool_execution import execute_single_tool

        mock_executor = MagicMock()
        execute_single_tool(
            {"name": "bash", "parameters": {"command": "rm -rf /"}},
            mock_executor, None, SafetyConfig(mode="dry_run"),
        )
        mock_executor.execute.assert_not_called()

    def test_dry_run_includes_parameters(self):
        """Dry run output includes the parameters that would have been used."""
        result = _make_llm_service_and_execute_single(
            SafetyConfig(mode="dry_run"),
            {"name": "bash", "parameters": {"command": "echo hello", "timeout": 30}},
        )
        assert "echo hello" in result["result"]


class TestRequireApprovalForTools:
    """Test that require_approval_for_tools blocks specific tools."""

    def test_listed_tool_blocked(self):
        """Tools in require_approval_for_tools list are blocked."""
        result = _make_llm_service_and_execute_single(
            SafetyConfig(mode="execute", require_approval_for_tools=["bash"]),
            {"name": "bash", "parameters": {"command": "ls"}},
        )
        assert result["success"] is False
        assert "requires approval" in result["error"]

    def test_unlisted_tool_executes(self):
        """Tools NOT in the list execute normally."""
        result = _make_llm_service_and_execute_single(
            SafetyConfig(mode="execute", require_approval_for_tools=["web_scraper"]),
            {"name": "bash", "parameters": {"command": "ls"}},
        )
        assert result["success"] is True
        assert result["result"] == "tool output"

    def test_approval_list_checked_in_execute_mode(self):
        """Tool-specific approval is checked even in normal execute mode."""
        from src.llm._tool_execution import execute_single_tool

        mock_executor = MagicMock()
        result = execute_single_tool(
            {"name": "bash", "parameters": {}},
            mock_executor, None,
            SafetyConfig(mode="execute", require_approval_for_tools=["bash", "calculator"]),
        )
        assert result["success"] is False
        mock_executor.execute.assert_not_called()

    def test_approval_list_does_not_execute_tool(self):
        """Blocked tools are not executed."""
        from src.llm._tool_execution import execute_single_tool

        mock_executor = MagicMock()
        execute_single_tool(
            {"name": "bash", "parameters": {}},
            mock_executor, None,
            SafetyConfig(mode="execute", require_approval_for_tools=["bash"]),
        )
        mock_executor.execute.assert_not_called()


class TestExecuteMode:
    """Test that normal execute mode works correctly."""

    def test_execute_mode_runs_tool(self):
        """Tools execute normally in execute mode."""
        result = _make_llm_service_and_execute_single(
            SafetyConfig(mode="execute"),
            {"name": "bash", "parameters": {"command": "ls"}},
        )
        assert result["success"] is True
        assert result["result"] == "tool output"

    def test_default_mode_is_execute(self):
        """Default safety config allows normal execution."""
        result = _make_llm_service_and_execute_single(
            SafetyConfig(),
            {"name": "bash", "parameters": {"command": "ls"}},
        )
        assert result["success"] is True


class TestMaxExecutionTimeEnforcement:
    """Test that max_execution_time_seconds is enforced in execute() loop."""

    def test_execution_time_limit_triggers(self):
        """Execute loop stops when wall-clock time exceeds limit."""
        agent = _make_agent(SafetyConfig(
            max_execution_time_seconds=1,
            max_tool_calls_per_execution=100
        ))

        # Mock LLM to always return tool calls (never completes)
        mock_response = LLMResponse(
            content='<tool_call>{"name": "bash", "parameters": {"command": "ls"}}</tool_call>',
            model="llama2",
            provider="ollama",
            total_tokens=10,
        )
        agent.llm.complete = MagicMock(return_value=mock_response)
        # Also update llm_service.llm to use same mock
        agent.llm_service.llm = agent.llm

        # Mock time.time to simulate time progression
        # First call is start_time, then each subsequent call adds time
        call_count = [0]
        base_time = 1000.0

        def mock_time():
            call_count[0] += 1
            # After first iteration (~4 calls), time exceeds limit
            return base_time + (call_count[0] * 0.5)

        with patch('src.agent.base_agent.time') as mock_base_time, \
             patch('src.llm.service.time') as mock_service_time:
            mock_base_time.time = mock_time
            mock_service_time.time = mock_time

            response = agent.execute({"query": "test"})

        assert response.error is not None
        assert "time limit exceeded" in response.error.lower() or "execution time" in response.error.lower()

    def test_execution_within_time_limit_completes(self):
        """Execute completes normally when within time limit."""
        agent = _make_agent(SafetyConfig(max_execution_time_seconds=300))

        # Mock LLM to return a direct answer (no tool calls)
        mock_response = LLMResponse(
            content="<answer>Hello!</answer>",
            model="llama2",
            provider="ollama",
            total_tokens=10,
        )
        agent.llm.complete = MagicMock(return_value=mock_response)
        agent.llm_service.llm = agent.llm

        response = agent.execute({"query": "test"})

        assert response.error is None
        assert "Hello!" in response.output


class TestSafetyModeCannotBeBypassed:
    """Test that safety mode cannot be bypassed by any code path."""

    def test_tool_calls_list_respects_safety(self):
        """LLMService._execute_tools respects safety mode for each tool."""
        mock_llm = MagicMock()
        mock_inf_config = MagicMock()
        service = LLMService(mock_llm, mock_inf_config)

        results = service._execute_tools(
            [
                {"name": "bash", "parameters": {"command": "ls"}},
                {"name": "bash", "parameters": {"command": "pwd"}},
            ],
            MagicMock(), None,
            SafetyConfig(mode="require_approval"),
        )
        assert all(r["success"] is False for r in results)
        assert all("require_approval" in r["error"] for r in results)

    def test_dry_run_in_tool_calls_list(self):
        """LLMService._execute_tools returns dry run results for all tools."""
        mock_llm = MagicMock()
        mock_inf_config = MagicMock()
        service = LLMService(mock_llm, mock_inf_config)

        results = service._execute_tools(
            [
                {"name": "bash", "parameters": {"command": "ls"}},
                {"name": "bash", "parameters": {"command": "pwd"}},
            ],
            MagicMock(), None,
            SafetyConfig(mode="dry_run"),
        )
        assert all(r["success"] is True for r in results)
        assert all("[DRY RUN]" in r["result"] for r in results)

    def test_execute_respects_safety(self):
        """Full execute() respects safety mode."""
        agent = _make_agent(SafetyConfig(mode="require_approval"))

        # LLM returns tool calls
        mock_response = LLMResponse(
            content='<tool_call>{"name": "bash", "parameters": {"command": "rm -rf /"}}</tool_call>',
            model="llama2",
            provider="ollama",
            total_tokens=10,
        )
        agent.llm.complete = MagicMock(return_value=mock_response)
        agent.llm_service.llm = agent.llm

        # Provide a tool in the registry so tools list is non-empty
        mock_tool = MagicMock()
        mock_tool.name = "bash"
        mock_tool.description = "Execute commands"
        mock_tool.get_parameters_schema.return_value = {"type": "object", "properties": {}}
        mock_tool.get_result_schema.return_value = None
        agent.tool_registry.get_all_tools = MagicMock(return_value={"bash": mock_tool})

        response = agent.execute({"query": "test"})

        # Max iterations reached, with blocked tool calls
        blocked_calls = [tc for tc in response.tool_calls if not tc["success"]]
        assert len(blocked_calls) > 0
