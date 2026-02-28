"""Tests for StaticCheckerAgent — pre_commands + single LLM synthesis call."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.agent.static_checker_agent import StaticCheckerAgent
from temper_ai.llm.prompts.validation import PromptRenderError
from temper_ai.llm.service import LLMRunResult, LLMService
from temper_ai.shared.utils.exceptions import LLMError
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PreCommand,
    PromptConfig,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _make_checker_config(
    name: str = "test_checker",
    pre_commands: list[PreCommand] | None = None,
) -> AgentConfig:
    """Create a minimal static_checker AgentConfig for testing."""
    if pre_commands is None:
        pre_commands = [PreCommand(name="check", command="echo hello")]
    return AgentConfig(
        agent=AgentConfigInner(
            name=name,
            description="Test static checker agent",
            type="static_checker",
            prompt=PromptConfig(inline="Analyze results"),
            inference=InferenceConfig(provider="ollama", model="test-model"),
            pre_commands=pre_commands,
            error_handling=ErrorHandlingConfig(),
        )
    )


def _make_llm_result(
    output: str = "analysis complete",
    reasoning: str | None = None,
    tokens: int = 100,
    cost: float = 0.001,
    error: str | None = None,
) -> MagicMock:
    """Create a mock LLMRunResult with the fields _build_checker_response accesses."""
    result = MagicMock(spec=LLMRunResult)
    result.output = output
    result.reasoning = reasoning
    result.tokens = tokens
    result.cost = cost
    result.error = error
    return result


# ── TestStaticCheckerAgentInit ────────────────────────────────────────────


class TestStaticCheckerAgentInit:
    """Tests for StaticCheckerAgent.__init__ and validate_config."""

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_init_success(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        assert agent.name == "test_checker"

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_llm_service_created(self, mock_create_llm: MagicMock) -> None:
        """LLMService is created during __init__."""
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        assert isinstance(agent.llm_service, LLMService)

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_validate_config_returns_true(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        assert agent.validate_config() is True

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_validate_config_missing_pre_commands_raises(
        self, mock_create_llm: MagicMock
    ) -> None:
        """validate_config raises ValueError when pre_commands is None."""
        mock_create_llm.return_value = MagicMock()
        config = _make_checker_config()
        config.agent.pre_commands = None
        with pytest.raises(ValueError, match="requires at least one pre_command"):
            StaticCheckerAgent(config)

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_validate_config_empty_pre_commands_raises(
        self, mock_create_llm: MagicMock
    ) -> None:
        """validate_config raises ValueError when pre_commands is an empty list."""
        mock_create_llm.return_value = MagicMock()
        config = _make_checker_config(pre_commands=[])
        with pytest.raises(ValueError, match="requires at least one pre_command"):
            StaticCheckerAgent(config)

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_validate_config_error_includes_agent_name(
        self, mock_create_llm: MagicMock
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        config = _make_checker_config(name="my_checker")
        config.agent.pre_commands = None
        with pytest.raises(ValueError, match="my_checker"):
            StaticCheckerAgent(config)


# ── TestBuildCheckerResponse ──────────────────────────────────────────────


class TestBuildCheckerResponse:
    """Tests for _build_checker_response — output concatenation logic."""

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_both_raw_and_output_concatenated(self, mock_create_llm: MagicMock) -> None:
        """When both raw_results and LLM output exist, joined with '---' separator."""
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        result = _make_llm_result(output="verdict: pass")
        input_data = {"command_results": "# Pre-Command Results\n## check — PASS"}

        response = agent._build_checker_response(result, input_data, time.time())

        assert "# Pre-Command Results" in response.output
        assert "verdict: pass" in response.output
        assert "---" in response.output

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_only_raw_when_llm_output_empty(self, mock_create_llm: MagicMock) -> None:
        """When LLM output is empty string, only raw_results is returned."""
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        result = _make_llm_result(output="")
        input_data = {"command_results": "raw output here"}

        response = agent._build_checker_response(result, input_data, time.time())

        assert response.output == "raw output here"

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_only_llm_output_when_no_command_results(
        self, mock_create_llm: MagicMock
    ) -> None:
        """When command_results absent, only LLM output is returned."""
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        result = _make_llm_result(output="analysis result")

        response = agent._build_checker_response(result, {}, time.time())

        assert response.output == "analysis result"

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_empty_both_yields_empty_output(self, mock_create_llm: MagicMock) -> None:
        """When both command_results and LLM output are empty, output is empty."""
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        result = _make_llm_result(output="")

        response = agent._build_checker_response(result, {}, time.time())

        assert response.output == ""

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_tokens_and_cost_passed_through(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        result = _make_llm_result(output="ok", tokens=500, cost=0.05)

        response = agent._build_checker_response(result, {}, time.time())

        assert response.tokens == 500
        assert response.estimated_cost_usd == 0.05

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_error_field_passed_through(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        result = _make_llm_result(output="", error="LLM rate limited")

        response = agent._build_checker_response(result, {}, time.time())

        assert response.error == "LLM rate limited"

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_tool_calls_always_empty_list(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        result = _make_llm_result(output="ok")

        response = agent._build_checker_response(result, {}, time.time())

        assert response.tool_calls == []


# ── TestStaticCheckerAgentRun ─────────────────────────────────────────────


class TestStaticCheckerAgentRun:
    """Tests for StaticCheckerAgent._run (core sync execution logic)."""

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_success_with_command_results(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.return_value = "# Pre-Command Results\n## check — PASS"

        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        llm_result = _make_llm_result(output="all clear")
        agent.llm_service.run = MagicMock(return_value=llm_result)

        response = agent._run({}, None, time.time())

        assert response.error is None
        assert "all clear" in response.output
        assert "Pre-Command Results" in response.output

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_none_command_results_not_injected(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        """When execute_pre_commands returns None, command_results not added."""
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.return_value = None

        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        llm_result = _make_llm_result(output="analysis")
        agent.llm_service.run = MagicMock(return_value=llm_result)

        input_data: dict = {}
        response = agent._run(input_data, None, time.time())

        assert "command_results" not in input_data
        assert response.output == "analysis"

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_llm_service_called_with_tools_none(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        """StaticCheckerAgent never uses tools — LLMService.run called with tools=None."""
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.return_value = None

        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        llm_result = _make_llm_result(output="done")
        mock_run = MagicMock(return_value=llm_result)
        agent.llm_service.run = mock_run

        agent._run({}, None, time.time())

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["tools"] is None

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_execute_routes_llm_error(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        """execute() routes LLMError through _on_error, returns response with error."""
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.side_effect = LLMError("llm call failed")

        agent = StaticCheckerAgent(_make_checker_config())
        response = agent.execute({})

        assert response.error is not None

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_execute_routes_prompt_render_error(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.side_effect = PromptRenderError("template broken")

        agent = StaticCheckerAgent(_make_checker_config())
        response = agent.execute({})

        assert response.error is not None

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_execute_routes_runtime_error(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.side_effect = RuntimeError("subprocess crashed")

        agent = StaticCheckerAgent(_make_checker_config())
        response = agent.execute({})

        assert response.error is not None

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_execute_routes_value_error(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.side_effect = ValueError("invalid config")

        agent = StaticCheckerAgent(_make_checker_config())
        response = agent.execute({})

        assert response.error is not None

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_execute_routes_timeout_error(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.side_effect = TimeoutError("command timed out")

        agent = StaticCheckerAgent(_make_checker_config())
        response = agent.execute({})

        assert response.error is not None

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_unexpected_error_handled_by_base(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        """Unexpected error types fall through to BaseAgent._build_error_response."""
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.side_effect = KeyError("unexpected key error")

        agent = StaticCheckerAgent(_make_checker_config())
        response = agent.execute({})

        assert response.error is not None


# ── TestStaticCheckerAgentArun ────────────────────────────────────────────


class TestStaticCheckerAgentArun:
    """Tests for StaticCheckerAgent._arun (async path via asyncio.to_thread)."""

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_arun_success(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.return_value = "# Pre-Command Results"

        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        llm_result = _make_llm_result(output="async result")
        agent.llm_service.arun = AsyncMock(return_value=llm_result)

        response = asyncio.run(agent._arun({}, None, time.time()))

        assert response.error is None
        assert "async result" in response.output

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_arun_injects_command_results_into_input_data(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        """_arun mutates input_data with command_results when non-None."""
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.return_value = "cmd output"

        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        llm_result = _make_llm_result(output="done")
        agent.llm_service.arun = AsyncMock(return_value=llm_result)

        input_data: dict = {}
        asyncio.run(agent._arun(input_data, None, time.time()))

        assert input_data.get("command_results") == "cmd output"

    @patch("temper_ai.agent.static_checker_agent.execute_pre_commands")
    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_arun_none_results_not_injected(
        self,
        mock_create_llm: MagicMock,
        mock_exec_pre: MagicMock,
    ) -> None:
        """When execute_pre_commands returns None, command_results not added."""
        mock_create_llm.return_value = MagicMock()
        mock_exec_pre.return_value = None

        agent = StaticCheckerAgent(_make_checker_config())
        agent._stream_callback = None
        agent._observer = None

        llm_result = _make_llm_result(output="done")
        agent.llm_service.arun = AsyncMock(return_value=llm_result)

        input_data: dict = {}
        asyncio.run(agent._arun(input_data, None, time.time()))

        assert "command_results" not in input_data

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_aexecute_full_flow(self, mock_create_llm: MagicMock) -> None:
        """aexecute() goes through full async template method and succeeds."""
        mock_create_llm.return_value = MagicMock()

        agent = StaticCheckerAgent(_make_checker_config())

        llm_result = _make_llm_result(output="async done")
        agent.llm_service.arun = AsyncMock(return_value=llm_result)

        with patch(
            "temper_ai.agent.static_checker_agent.execute_pre_commands",
            return_value="pre-cmd output",
        ):
            response = asyncio.run(agent.aexecute({}))

        assert response.error is None
        assert "async done" in response.output


# ── TestStaticCheckerOnError ──────────────────────────────────────────────


class TestStaticCheckerOnError:
    """Tests for _on_error — handled vs. unhandled exception types."""

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_llm_error_returns_response(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        response = agent._on_error(LLMError("llm down"), time.time())
        assert response is not None
        assert response.error is not None

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_prompt_render_error_returns_response(
        self, mock_create_llm: MagicMock
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        response = agent._on_error(PromptRenderError("bad template"), time.time())
        assert response is not None
        assert response.error is not None

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_runtime_error_returns_response(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        response = agent._on_error(RuntimeError("runtime fail"), time.time())
        assert response is not None
        assert response.error is not None

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_value_error_returns_response(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        response = agent._on_error(ValueError("invalid"), time.time())
        assert response is not None
        assert response.error is not None

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_timeout_error_returns_response(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        response = agent._on_error(TimeoutError("timed out"), time.time())
        assert response is not None
        assert response.error is not None

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_unhandled_key_error_returns_none(self, mock_create_llm: MagicMock) -> None:
        """KeyError is not in _on_error's handled set — returns None."""
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        response = agent._on_error(KeyError("oops"), time.time())
        assert response is None

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_unhandled_attribute_error_returns_none(
        self, mock_create_llm: MagicMock
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        response = agent._on_error(AttributeError("attr missing"), time.time())
        assert response is None


# ── TestGetCapabilities ───────────────────────────────────────────────────


class TestGetCapabilities:
    """Tests for get_capabilities() metadata and structure."""

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_type_is_static_checker(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        assert agent.get_capabilities()["type"] == "static_checker"

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_tools_is_empty_list(self, mock_create_llm: MagicMock) -> None:
        """StaticCheckerAgent never uses tools."""
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        assert agent.get_capabilities()["tools"] == []

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_pre_commands_names_listed(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        config = _make_checker_config(
            pre_commands=[
                PreCommand(name="lint", command="pylint src/"),
                PreCommand(name="typecheck", command="mypy src/"),
            ]
        )
        agent = StaticCheckerAgent(config)
        caps = agent.get_capabilities()
        assert "lint" in caps["pre_commands"]
        assert "typecheck" in caps["pre_commands"]

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_name_matches_config(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config(name="my_checker"))
        assert agent.get_capabilities()["name"] == "my_checker"

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_supports_streaming_true(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        assert agent.get_capabilities()["supports_streaming"] is True

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_supports_multimodal_false(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        assert agent.get_capabilities()["supports_multimodal"] is False

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_llm_provider_and_model_from_config(
        self, mock_create_llm: MagicMock
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        caps = agent.get_capabilities()
        assert caps["llm_provider"] == "ollama"
        assert caps["llm_model"] == "test-model"

    @patch("temper_ai.agent.base_agent.create_llm_from_config")
    def test_single_pre_command_in_list(self, mock_create_llm: MagicMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = StaticCheckerAgent(_make_checker_config())
        caps = agent.get_capabilities()
        assert caps["pre_commands"] == ["check"]
