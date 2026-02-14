"""Tests for StaticCheckerAgent — dedicated agent type for pre_commands + LLM synthesis."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.agent_factory import AgentFactory
from src.agents.base_agent import AgentResponse
from src.agents.static_checker_agent import StaticCheckerAgent
from src.cli.stream_events import PROGRESS, TOOL_RESULT, TOOL_START
from src.schemas.agent_config import AgentConfig


# ============================================================================
# Fixtures
# ============================================================================


def _make_config(
    pre_commands=None,
    inline_prompt="Synthesize: {{ command_results }}",
    tools=None,
    agent_type="static_checker",
):
    """Build a minimal AgentConfig for StaticCheckerAgent."""
    agent_dict = {
        "name": "test_static_checker",
        "description": "test static checker",
        "type": agent_type,
        "prompt": {"inline": inline_prompt},
        "inference": {
            "provider": "ollama",
            "model": "test-model",
        },
        "error_handling": {
            "retry_strategy": "ExponentialBackoff",
            "max_retries": 1,
            "fallback": "GracefulDegradation",
            "escalate_to_human_after": 3,
        },
    }
    if pre_commands is not None:
        agent_dict["pre_commands"] = pre_commands
    if tools is not None:
        agent_dict["tools"] = tools
    return AgentConfig(agent=agent_dict)


_SAMPLE_PRE_COMMANDS = [
    {"name": "check_syntax", "command": "echo ok", "timeout_seconds": 10},
    {"name": "check_imports", "command": "echo imports ok", "timeout_seconds": 10},
]


# ============================================================================
# Factory integration
# ============================================================================


class TestFactoryCreation:
    """AgentFactory creates StaticCheckerAgent for type: static_checker."""

    def test_factory_creates_static_checker(self) -> None:
        config = _make_config(pre_commands=_SAMPLE_PRE_COMMANDS)
        agent = AgentFactory.create(config)
        assert isinstance(agent, StaticCheckerAgent)

    def test_factory_lists_static_checker(self) -> None:
        types = AgentFactory.list_types()
        assert "static_checker" in types
        assert types["static_checker"] is StaticCheckerAgent


# ============================================================================
# Validation
# ============================================================================


class TestValidation:
    """StaticCheckerAgent rejects configs without pre_commands."""

    def test_rejects_no_pre_commands(self) -> None:
        config = _make_config(pre_commands=None)
        with pytest.raises(ValueError, match="requires at least one pre_command"):
            StaticCheckerAgent(config)

    def test_rejects_empty_pre_commands(self) -> None:
        config = _make_config(pre_commands=[])
        with pytest.raises(ValueError, match="requires at least one pre_command"):
            StaticCheckerAgent(config)

    def test_accepts_valid_pre_commands(self) -> None:
        agent = StaticCheckerAgent(_make_config(pre_commands=_SAMPLE_PRE_COMMANDS))
        assert agent.name == "test_static_checker"

    def test_no_tool_registry(self) -> None:
        agent = StaticCheckerAgent(_make_config(pre_commands=_SAMPLE_PRE_COMMANDS))
        assert not hasattr(agent, "tool_registry")


# ============================================================================
# Capabilities
# ============================================================================


class TestCapabilities:

    def test_capabilities_type(self) -> None:
        agent = StaticCheckerAgent(_make_config(pre_commands=_SAMPLE_PRE_COMMANDS))
        caps = agent.get_capabilities()
        assert caps["type"] == "static_checker"
        assert caps["tools"] == []
        assert "check_syntax" in caps["pre_commands"]
        assert "check_imports" in caps["pre_commands"]
        assert caps["supports_streaming"] is True


# ============================================================================
# Execution (sync)
# ============================================================================


class TestExecute:
    """Test execute() with mocked subprocess and LLM."""

    @patch("src.agents._pre_command_helpers.subprocess.run")
    @patch("src.agents.static_checker_agent.create_llm_from_config")
    def test_execute_happy_path(self, mock_llm_factory, mock_subproc) -> None:
        # Mock subprocess: all commands pass
        mock_subproc.return_value = MagicMock(returncode=0, stdout="OK", stderr="")

        # Mock LLM
        mock_llm = MagicMock()
        mock_llm.complete.return_value = MagicMock(
            content="<answer>OVERALL: PASS</answer>",
            total_tokens=100,
            prompt_tokens=80,
            completion_tokens=20,
            model="test-model",
        )
        mock_llm_factory.return_value = mock_llm

        agent = StaticCheckerAgent(_make_config(pre_commands=_SAMPLE_PRE_COMMANDS))
        response = agent.execute({"workspace_path": "/tmp/test"})

        assert isinstance(response, AgentResponse)
        assert response.error is None
        assert "PASS" in response.output
        assert response.tokens == 100
        # LLM called exactly once (no tool loop)
        mock_llm.complete.assert_called_once()

    @patch("src.agents._pre_command_helpers.subprocess.run")
    @patch("src.agents.static_checker_agent.create_llm_from_config")
    def test_execute_command_failure_still_calls_llm(self, mock_llm_factory, mock_subproc) -> None:
        """Even if a pre_command fails, LLM is still called to synthesise the verdict."""
        mock_subproc.return_value = MagicMock(returncode=1, stdout="", stderr="ImportError")

        mock_llm = MagicMock()
        mock_llm.complete.return_value = MagicMock(
            content="<answer>OVERALL: FAIL\nERRORS:\n- ImportError</answer>",
            total_tokens=50,
            prompt_tokens=40,
            completion_tokens=10,
            model="test-model",
        )
        mock_llm_factory.return_value = mock_llm

        agent = StaticCheckerAgent(_make_config(pre_commands=_SAMPLE_PRE_COMMANDS))
        response = agent.execute({})

        assert response.error is None
        mock_llm.complete.assert_called_once()

    @patch("src.agents._pre_command_helpers.subprocess.run")
    @patch("src.agents.static_checker_agent.create_llm_from_config")
    def test_execute_llm_error(self, mock_llm_factory, mock_subproc) -> None:
        """LLM failure produces an error response (not an exception)."""
        from src.agents.llm import LLMError

        mock_subproc.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = LLMError("connection refused")
        mock_llm_factory.return_value = mock_llm

        agent = StaticCheckerAgent(_make_config(pre_commands=_SAMPLE_PRE_COMMANDS))
        response = agent.execute({})

        assert response.error is not None
        assert "connection refused" in response.error

    @pytest.mark.asyncio
    @patch("src.agents._pre_command_helpers.subprocess.run")
    @patch("src.agents.static_checker_agent.create_llm_from_config")
    async def test_aexecute_happy_path(self, mock_llm_factory, mock_subproc) -> None:
        """Async execution path works correctly."""
        mock_subproc.return_value = MagicMock(returncode=0, stdout="OK", stderr="")

        mock_response = MagicMock()
        mock_response.content = "<answer>OVERALL: PASS</answer>"
        mock_response.total_tokens = 100
        mock_response.prompt_tokens = 80
        mock_response.completion_tokens = 20
        mock_response.model = "test-model"

        mock_llm = MagicMock()
        mock_llm.acomplete = AsyncMock(return_value=mock_response)
        mock_llm_factory.return_value = mock_llm

        agent = StaticCheckerAgent(_make_config(pre_commands=_SAMPLE_PRE_COMMANDS))
        response = await agent.aexecute({"workspace_path": "/tmp/test"})

        assert isinstance(response, AgentResponse)
        assert response.error is None
        assert "PASS" in response.output
        mock_llm.acomplete.assert_called_once()


# ============================================================================
# StreamEvent emission
# ============================================================================


class TestStreamEvents:
    """Verify TOOL_START, PROGRESS, TOOL_RESULT events via _stream_callback."""

    @patch("src.agents._pre_command_helpers.subprocess.run")
    @patch("src.agents.static_checker_agent.create_llm_from_config")
    def test_stream_events_emitted(self, mock_llm_factory, mock_subproc) -> None:
        mock_subproc.return_value = MagicMock(returncode=0, stdout="check passed", stderr="")

        mock_response = MagicMock()
        mock_response.content = "<answer>PASS</answer>"
        mock_response.total_tokens = 10
        mock_response.prompt_tokens = 8
        mock_response.completion_tokens = 2
        mock_response.model = "test-model"

        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_response
        mock_llm.stream.return_value = mock_response
        mock_llm_factory.return_value = mock_llm

        # Use a single pre_command for simplicity
        config = _make_config(pre_commands=[
            {"name": "syntax_check", "command": "echo check passed", "timeout_seconds": 10},
        ])
        agent = StaticCheckerAgent(config)

        # Collect stream events
        events = []
        agent.execute({"stream_callback": lambda evt: events.append(evt)})

        # Should have: TOOL_START, PROGRESS (stdout), TOOL_RESULT
        event_types = [e.event_type for e in events]
        assert TOOL_START in event_types
        assert PROGRESS in event_types
        assert TOOL_RESULT in event_types

        # Verify TOOL_START metadata
        start_evt = next(e for e in events if e.event_type == TOOL_START)
        assert start_evt.metadata["tool_name"] == "pre_command:syntax_check"

        # Verify TOOL_RESULT metadata
        result_evt = next(e for e in events if e.event_type == TOOL_RESULT)
        assert result_evt.metadata["tool_name"] == "pre_command:syntax_check"
        assert result_evt.metadata["success"] is True

    @patch("src.agents._pre_command_helpers.subprocess.run")
    @patch("src.agents.static_checker_agent.create_llm_from_config")
    def test_stream_events_on_failure(self, mock_llm_factory, mock_subproc) -> None:
        mock_subproc.return_value = MagicMock(returncode=1, stdout="", stderr="SyntaxError")

        mock_response = MagicMock()
        mock_response.content = "<answer>FAIL</answer>"
        mock_response.total_tokens = 10
        mock_response.prompt_tokens = 8
        mock_response.completion_tokens = 2
        mock_response.model = "test-model"

        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_response
        mock_llm.stream.return_value = mock_response
        mock_llm_factory.return_value = mock_llm

        config = _make_config(pre_commands=[
            {"name": "bad_check", "command": "false", "timeout_seconds": 10},
        ])
        agent = StaticCheckerAgent(config)

        events = []
        agent.execute({"stream_callback": lambda evt: events.append(evt)})

        result_evt = next(e for e in events if e.event_type == TOOL_RESULT)
        assert result_evt.metadata["success"] is False
        assert result_evt.metadata["error"] is not None


# ============================================================================
# Observer tracking
# ============================================================================


class TestObserverTracking:

    @patch("src.agents._pre_command_helpers.subprocess.run")
    @patch("src.agents.static_checker_agent.create_llm_from_config")
    def test_observer_track_tool_call(self, mock_llm_factory, mock_subproc) -> None:
        mock_subproc.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

        mock_response = MagicMock()
        mock_response.content = "<answer>PASS</answer>"
        mock_response.total_tokens = 10
        mock_response.prompt_tokens = 8
        mock_response.completion_tokens = 2
        mock_response.model = "test-model"

        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_response
        mock_llm_factory.return_value = mock_llm

        config = _make_config(pre_commands=[
            {"name": "mycheck", "command": "echo ok", "timeout_seconds": 10},
        ])
        agent = StaticCheckerAgent(config)

        # Provide a mock tracker with agent_id so AgentObserver.active is True
        mock_tracker = MagicMock()
        mock_context = MagicMock()
        mock_context.agent_id = "test-agent-id"
        agent.execute({"tracker": mock_tracker})

        # setup_execution creates the observer; patch it after setup and re-run
        # Instead, verify the observer was created at all — since no execution_context
        # with agent_id is provided, observer.active == False and track_tool_call is a no-op.
        # The pre_command_helpers call the observer directly (not via AgentObserver).
        observer = getattr(agent, "_observer", None)
        assert observer is not None

    @patch("src.agents._pre_command_helpers.subprocess.run")
    @patch("src.agents.static_checker_agent.create_llm_from_config")
    def test_observer_track_tool_call_with_mock(self, mock_llm_factory, mock_subproc) -> None:
        """Verify track_tool_call is invoked when observer is a mock."""
        mock_subproc.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

        mock_response = MagicMock()
        mock_response.content = "<answer>PASS</answer>"
        mock_response.total_tokens = 10
        mock_response.prompt_tokens = 8
        mock_response.completion_tokens = 2
        mock_response.model = "test-model"

        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_response
        mock_llm_factory.return_value = mock_llm

        config = _make_config(pre_commands=[
            {"name": "mycheck", "command": "echo ok", "timeout_seconds": 10},
        ])
        agent = StaticCheckerAgent(config)

        # Execute to trigger setup_execution, then patch observer for second run
        agent.execute({})
        # Replace observer with a mock and run pre_commands directly
        mock_observer = MagicMock()
        agent._observer = mock_observer

        from src.agents._pre_command_helpers import execute_pre_commands
        execute_pre_commands(agent, {})

        mock_observer.track_tool_call.assert_called_once()
        call_kwargs = mock_observer.track_tool_call.call_args[1]
        assert call_kwargs["tool_name"] == "pre_command:mycheck"
        assert call_kwargs["status"] == "success"
