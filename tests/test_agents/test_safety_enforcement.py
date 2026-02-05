"""Tests for SafetyConfig enforcement in StandardAgent.

Tests verify that SafetyConfig fields (mode, require_approval_for_tools,
max_execution_time_seconds) are actually enforced during tool execution.
"""
import time
import pytest
from unittest.mock import patch, MagicMock
from src.agents.standard_agent import StandardAgent
from src.agents.llm_providers import LLMResponse
from src.tools.base import ToolResult
from src.compiler.schemas import (
    AgentConfig,
    AgentConfigInner,
    PromptConfig,
    InferenceConfig,
    ErrorHandlingConfig,
    SafetyConfig,
)


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
    with patch('src.agents.standard_agent.ToolRegistry'):
        agent = StandardAgent(_make_config(safety))
    # Register a mock tool
    mock_tool = MagicMock()
    mock_tool.execute.return_value = ToolResult(
        success=True, result="tool output"
    )
    agent.tool_registry.get = lambda name: mock_tool if name == "bash" else None

    # Provide a mock tool_executor so execution doesn't block on missing safety stack
    mock_executor = MagicMock()
    mock_executor.execute.return_value = ToolResult(success=True, result="tool output")
    agent.tool_executor = mock_executor

    # Provide a mock observer (normally set in execute(), needed for direct calls)
    agent._observer = MagicMock()
    return agent


class TestRequireApprovalMode:
    """Test that require_approval mode blocks all tool execution."""

    def test_require_approval_blocks_tool(self):
        """Tools are blocked when mode is 'require_approval'."""
        agent = _make_agent(SafetyConfig(mode="require_approval"))
        result = agent._execute_single_tool(
            {"name": "bash", "parameters": {"command": "ls"}}
        )
        assert result["success"] is False
        assert "blocked" in result["error"]
        assert "require_approval" in result["error"]

    def test_require_approval_blocks_any_tool(self):
        """All tools are blocked, not just specific ones."""
        agent = _make_agent(SafetyConfig(mode="require_approval"))
        for tool_name in ["bash", "calculator", "web_scraper"]:
            # Register mock for each
            mock_tool = MagicMock()
            mock_tool.execute.return_value = ToolResult(success=True, result="ok")
            original_get = agent.tool_registry.get
            agent.tool_registry.get = lambda name, t=mock_tool: t

            result = agent._execute_single_tool(
                {"name": tool_name, "parameters": {}}
            )
            assert result["success"] is False
            assert "require_approval" in result["error"]

    def test_require_approval_does_not_execute(self):
        """Tool.execute() is never called in require_approval mode."""
        agent = _make_agent(SafetyConfig(mode="require_approval"))
        mock_tool = MagicMock()
        agent.tool_registry.get = lambda name: mock_tool

        agent._execute_single_tool({"name": "bash", "parameters": {"command": "rm -rf /"}})
        mock_tool.execute.assert_not_called()


class TestDryRunMode:
    """Test that dry_run mode returns simulated result without executing."""

    def test_dry_run_returns_simulated_result(self):
        """Dry run returns success with simulated output."""
        agent = _make_agent(SafetyConfig(mode="dry_run"))
        result = agent._execute_single_tool(
            {"name": "bash", "parameters": {"command": "ls"}}
        )
        assert result["success"] is True
        assert "[DRY RUN]" in result["result"]
        assert "bash" in result["result"]
        assert result["error"] is None

    def test_dry_run_does_not_execute(self):
        """Tool.execute() is never called in dry_run mode."""
        agent = _make_agent(SafetyConfig(mode="dry_run"))
        mock_tool = MagicMock()
        agent.tool_registry.get = lambda name: mock_tool

        agent._execute_single_tool({"name": "bash", "parameters": {"command": "rm -rf /"}})
        mock_tool.execute.assert_not_called()

    def test_dry_run_includes_parameters(self):
        """Dry run output includes the parameters that would have been used."""
        agent = _make_agent(SafetyConfig(mode="dry_run"))
        params = {"command": "echo hello", "timeout": 30}
        result = agent._execute_single_tool(
            {"name": "bash", "parameters": params}
        )
        assert "echo hello" in result["result"]


class TestRequireApprovalForTools:
    """Test that require_approval_for_tools blocks specific tools."""

    def test_listed_tool_blocked(self):
        """Tools in require_approval_for_tools list are blocked."""
        agent = _make_agent(SafetyConfig(
            mode="execute",
            require_approval_for_tools=["bash"]
        ))
        result = agent._execute_single_tool(
            {"name": "bash", "parameters": {"command": "ls"}}
        )
        assert result["success"] is False
        assert "requires approval" in result["error"]

    def test_unlisted_tool_executes(self):
        """Tools NOT in the list execute normally."""
        agent = _make_agent(SafetyConfig(
            mode="execute",
            require_approval_for_tools=["web_scraper"]
        ))
        result = agent._execute_single_tool(
            {"name": "bash", "parameters": {"command": "ls"}}
        )
        assert result["success"] is True
        assert result["result"] == "tool output"

    def test_approval_list_checked_in_execute_mode(self):
        """Tool-specific approval is checked even in normal execute mode."""
        agent = _make_agent(SafetyConfig(
            mode="execute",
            require_approval_for_tools=["bash", "calculator"]
        ))
        mock_tool = MagicMock()
        agent.tool_registry.get = lambda name: mock_tool

        result = agent._execute_single_tool(
            {"name": "bash", "parameters": {}}
        )
        assert result["success"] is False
        mock_tool.execute.assert_not_called()

    def test_approval_list_does_not_execute_tool(self):
        """Blocked tools are not executed."""
        agent = _make_agent(SafetyConfig(
            mode="execute",
            require_approval_for_tools=["bash"]
        ))
        mock_tool = MagicMock()
        agent.tool_registry.get = lambda name: mock_tool

        agent._execute_single_tool({"name": "bash", "parameters": {}})
        mock_tool.execute.assert_not_called()


class TestExecuteMode:
    """Test that normal execute mode works correctly."""

    def test_execute_mode_runs_tool(self):
        """Tools execute normally in execute mode."""
        agent = _make_agent(SafetyConfig(mode="execute"))
        result = agent._execute_single_tool(
            {"name": "bash", "parameters": {"command": "ls"}}
        )
        assert result["success"] is True
        assert result["result"] == "tool output"

    def test_default_mode_is_execute(self):
        """Default safety config allows normal execution."""
        agent = _make_agent()  # default SafetyConfig
        result = agent._execute_single_tool(
            {"name": "bash", "parameters": {"command": "ls"}}
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

        # Mock time.time to simulate time progression
        # First call is start_time, then each subsequent call adds time
        call_count = [0]
        base_time = 1000.0

        original_time = time.time

        def mock_time():
            call_count[0] += 1
            # After first iteration (~4 calls), time exceeds limit
            return base_time + (call_count[0] * 0.5)

        with patch('src.agents.standard_agent.time') as mock_time_module:
            mock_time_module.time = mock_time

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

        response = agent.execute({"query": "test"})

        assert response.error is None
        assert "Hello!" in response.output


class TestSafetyModeCannotBeBypassed:
    """Test that safety mode cannot be bypassed by any code path."""

    def test_tool_calls_list_respects_safety(self):
        """_execute_tool_calls respects safety mode for each tool."""
        agent = _make_agent(SafetyConfig(mode="require_approval"))
        results = agent._execute_tool_calls([
            {"name": "bash", "parameters": {"command": "ls"}},
            {"name": "bash", "parameters": {"command": "pwd"}},
        ])
        assert all(r["success"] is False for r in results)
        assert all("require_approval" in r["error"] for r in results)

    def test_dry_run_in_tool_calls_list(self):
        """_execute_tool_calls returns dry run results for all tools."""
        agent = _make_agent(SafetyConfig(mode="dry_run"))
        results = agent._execute_tool_calls([
            {"name": "bash", "parameters": {"command": "ls"}},
            {"name": "bash", "parameters": {"command": "pwd"}},
        ])
        assert all(r["success"] is True for r in results)
        assert all("[DRY RUN]" in r["result"] for r in results)

    def test_execute_iteration_respects_safety(self):
        """Full execute iteration respects safety mode."""
        agent = _make_agent(SafetyConfig(mode="require_approval"))

        # LLM returns tool calls
        mock_response = LLMResponse(
            content='<tool_call>{"name": "bash", "parameters": {"command": "rm -rf /"}}</tool_call>',
            model="llama2",
            provider="ollama",
            total_tokens=10,
        )
        agent.llm.complete = MagicMock(return_value=mock_response)

        result = agent._execute_iteration(
            "test prompt", 0, 0.0, [], time.time()
        )

        # Should not be complete (tool calls were made but blocked)
        assert result["complete"] is False
        # Tool call should show blocked
        blocked_calls = [
            tc for tc in result["tool_calls_made"]
            if not tc["success"]
        ]
        assert len(blocked_calls) > 0
