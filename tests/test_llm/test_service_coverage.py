"""Coverage tests for temper_ai/llm/service.py.

Covers: LLMService init, _MessagesLLMWrapper, run/arun loop,
_prepare_run_state, _check_iteration_guards, _handle_llm_failure,
_track_and_parse, _build_final_result, _execute_and_inject,
_raise_max_iterations, pre-call hooks, resolve helpers.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.llm.service import (
    LLMRunResult,
    LLMService,
    _MessagesLLMWrapper,
    _RunState,
    resolve_max_iterations,
    resolve_max_prompt_length,
    resolve_max_tool_result_size,
)
from temper_ai.shared.utils.exceptions import LLMError, MaxIterationsError

# ---------------------------------------------------------------------------
# _MessagesLLMWrapper
# ---------------------------------------------------------------------------


class TestMessagesLLMWrapper:
    def test_complete_injects_messages(self) -> None:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "response"
        msgs = [{"role": "user", "content": "hi"}]
        wrapper = _MessagesLLMWrapper(mock_llm, msgs)
        wrapper.complete("prompt")
        mock_llm.complete.assert_called_once()
        call_kwargs = mock_llm.complete.call_args[1]
        assert call_kwargs["messages"] == msgs

    @pytest.mark.asyncio
    async def test_acomplete_injects_messages(self) -> None:
        mock_llm = AsyncMock()
        msgs = [{"role": "user", "content": "hi"}]
        wrapper = _MessagesLLMWrapper(mock_llm, msgs)
        await wrapper.acomplete("prompt")
        call_kwargs = mock_llm.acomplete.call_args[1]
        assert call_kwargs["messages"] == msgs

    def test_stream_injects_messages(self) -> None:
        mock_llm = MagicMock()
        msgs = [{"role": "user", "content": "hi"}]
        wrapper = _MessagesLLMWrapper(mock_llm, msgs)
        wrapper.stream("prompt")
        call_kwargs = mock_llm.stream.call_args[1]
        assert call_kwargs["messages"] == msgs

    @pytest.mark.asyncio
    async def test_astream_injects_messages(self) -> None:
        mock_llm = AsyncMock()
        msgs = [{"role": "user", "content": "hi"}]
        wrapper = _MessagesLLMWrapper(mock_llm, msgs)
        await wrapper.astream("prompt")
        call_kwargs = mock_llm.astream.call_args[1]
        assert call_kwargs["messages"] == msgs

    def test_getattr_delegates(self) -> None:
        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        wrapper = _MessagesLLMWrapper(mock_llm, [])
        assert wrapper.model == "test-model"

    def test_doesnt_overwrite_existing_messages(self) -> None:
        mock_llm = MagicMock()
        wrapper_msgs = [{"role": "user", "content": "wrapper"}]
        wrapper = _MessagesLLMWrapper(mock_llm, wrapper_msgs)
        # If messages already passed as kwarg, setdefault won't overwrite
        existing_msgs = [{"role": "user", "content": "existing"}]
        wrapper.complete("prompt", messages=existing_msgs)
        call_kwargs = mock_llm.complete.call_args[1]
        assert call_kwargs["messages"] == existing_msgs


# ---------------------------------------------------------------------------
# Resolve helpers
# ---------------------------------------------------------------------------


class TestResolveHelpers:
    def test_resolve_max_iterations_explicit(self) -> None:
        assert resolve_max_iterations(5, None) == 5

    def test_resolve_max_iterations_from_safety(self) -> None:
        safety = MagicMock()
        safety.max_tool_calls_per_execution = 20
        assert resolve_max_iterations(None, safety) == 20

    def test_resolve_max_iterations_default(self) -> None:
        assert resolve_max_iterations(None, None) == 10

    def test_resolve_max_tool_result_size_from_safety(self) -> None:
        safety = MagicMock()
        safety.max_tool_result_size = 5000
        assert resolve_max_tool_result_size(safety) == 5000

    def test_resolve_max_tool_result_size_default(self) -> None:
        assert resolve_max_tool_result_size(None) == 10000

    def test_resolve_max_prompt_length_from_safety(self) -> None:
        safety = MagicMock()
        safety.max_prompt_length = 16000
        assert resolve_max_prompt_length(safety) == 16000

    def test_resolve_max_prompt_length_default(self) -> None:
        assert resolve_max_prompt_length(None) == 32000


# ---------------------------------------------------------------------------
# LLMService init and pre-call hooks
# ---------------------------------------------------------------------------


class TestLLMServiceInit:
    def test_basic_init(self) -> None:
        llm = MagicMock()
        config = MagicMock()
        svc = LLMService(llm, config)
        assert svc.llm is llm
        assert svc.inference_config is config
        assert svc.pre_call_hooks == []

    def test_init_with_hooks(self) -> None:
        hook = MagicMock(return_value=None)
        svc = LLMService(MagicMock(), MagicMock(), pre_call_hooks=[hook])
        assert len(svc.pre_call_hooks) == 1


class TestPreCallHooks:
    def test_hook_returns_none_allows(self) -> None:
        hook = MagicMock(return_value=None)
        svc = LLMService(MagicMock(), MagicMock(), pre_call_hooks=[hook])
        result = svc._run_pre_call_hooks("prompt")
        assert result is None

    def test_hook_returns_value_blocks(self) -> None:
        hook = MagicMock(return_value="blocked reason")
        svc = LLMService(MagicMock(), MagicMock(), pre_call_hooks=[hook])
        result = svc._run_pre_call_hooks("prompt")
        assert result == "blocked reason"

    def test_hook_raises_blocks(self) -> None:
        hook = MagicMock(side_effect=ValueError("hook error"))
        svc = LLMService(MagicMock(), MagicMock(), pre_call_hooks=[hook])
        result = svc._run_pre_call_hooks("prompt")
        assert "hook error" in result


# ---------------------------------------------------------------------------
# LLMService.run — full loop paths
# ---------------------------------------------------------------------------


class TestLLMServiceRun:
    def _make_service(self, **overrides: Any) -> LLMService:
        llm = overrides.get("llm", MagicMock())
        config = overrides.get("config", MagicMock())
        config.max_retries = overrides.get("max_retries", 0)
        config.retry_delay_seconds = overrides.get("retry_delay_seconds", 0.01)
        config.use_text_tool_schemas = overrides.get("use_text_tool_schemas", False)
        hooks = overrides.get("hooks", None)
        return LLMService(llm, config, pre_call_hooks=hooks)

    def test_simple_run_no_tools(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.content = "Hello World"
        mock_response.total_tokens = 100
        mock_response.model = "test"
        mock_response.provider = "test"

        with (
            patch.object(
                svc,
                "_call_with_retry_sync",
                return_value=(mock_response, None),
            ),
            patch.object(svc, "_estimate_cost", return_value=0.01),
            patch.object(svc, "_track_call"),
        ):
            result = svc.run("test prompt")
            assert result.output is not None
            assert result.iterations == 1

    def test_run_llm_failure(self) -> None:
        svc = self._make_service()
        with patch.object(
            svc,
            "_call_with_retry_sync",
            return_value=(None, LLMError("fail")),
        ):
            result = svc.run("test prompt")
            assert result.error is not None
            assert "failed" in result.error.lower()

    def test_run_timeout_guard(self) -> None:
        svc = self._make_service()
        result = svc.run(
            "test prompt",
            max_execution_time=0.0001,
            start_time=time.time() - 100,
        )
        assert result.error is not None
        assert "time limit" in result.error.lower()

    def test_run_pre_call_hook_blocks(self) -> None:
        hook = MagicMock(return_value="blocked")
        svc = self._make_service(hooks=[hook])
        result = svc.run("test prompt")
        assert result.error is not None
        assert "blocked" in result.error.lower()

    def test_run_with_tool_calls(self) -> None:
        svc = self._make_service()
        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.description = "Search tool"
        mock_tool.get_parameters_schema.return_value = {"type": "object"}
        mock_tool.get_result_schema.return_value = None

        # First response has tool calls, second has final answer
        resp1 = MagicMock()
        resp1.content = (
            '<tool_call>\n{"name": "search", "parameters": {"q": "test"}}\n</tool_call>'
        )
        resp1.total_tokens = 50
        resp2 = MagicMock()
        resp2.content = "The answer is 42"
        resp2.total_tokens = 30

        call_count = 0

        def side_effect(*a: Any, **kw: Any) -> tuple:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return resp1, None
            return resp2, None

        mock_executor = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.result = "search results"
        mock_result.error = None
        mock_executor.execute.return_value = mock_result

        with (
            patch.object(svc, "_call_with_retry_sync", side_effect=side_effect),
            patch.object(svc, "_estimate_cost", return_value=0.001),
            patch.object(svc, "_track_call"),
        ):
            result = svc.run(
                "test prompt",
                tools=[mock_tool],
                tool_executor=mock_executor,
            )
            assert result.iterations >= 1

    def test_run_max_iterations_exceeded(self) -> None:
        svc = self._make_service()
        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.description = "Search"
        mock_tool.get_parameters_schema.return_value = {"type": "object"}
        mock_tool.get_result_schema.return_value = None

        # Always return tool calls
        resp = MagicMock()
        resp.content = '<tool_call>\n{"name": "search", "parameters": {}}\n</tool_call>'
        resp.total_tokens = 10

        mock_executor = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.result = "result"
        mock_result.error = None
        mock_executor.execute.return_value = mock_result

        with (
            patch.object(svc, "_call_with_retry_sync", return_value=(resp, None)),
            patch.object(svc, "_estimate_cost", return_value=0.001),
            patch.object(svc, "_track_call"),
            pytest.raises(MaxIterationsError),
        ):
            svc.run(
                "test",
                tools=[mock_tool],
                tool_executor=mock_executor,
                max_iterations=2,
            )

    def test_run_with_messages(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.content = "reply"
        mock_response.total_tokens = 10

        with (
            patch.object(
                svc,
                "_call_with_retry_sync",
                return_value=(mock_response, None),
            ),
            patch.object(svc, "_estimate_cost", return_value=0.001),
            patch.object(svc, "_track_call"),
        ):
            result = svc.run(
                "test",
                messages=[{"role": "user", "content": "hello"}],
            )
            assert result.output is not None


# ---------------------------------------------------------------------------
# LLMService.arun
# ---------------------------------------------------------------------------


class TestLLMServiceArun:
    @pytest.mark.asyncio
    async def test_simple_arun(self) -> None:
        llm = MagicMock()
        config = MagicMock()
        config.max_retries = 0
        config.retry_delay_seconds = 0.01
        config.use_text_tool_schemas = False
        svc = LLMService(llm, config)

        mock_response = MagicMock()
        mock_response.content = "async reply"
        mock_response.total_tokens = 10

        with (
            patch.object(
                svc,
                "_call_with_retry_async",
                new_callable=AsyncMock,
                return_value=(mock_response, None),
            ),
            patch.object(svc, "_estimate_cost", return_value=0.001),
            patch.object(svc, "_track_call"),
        ):
            result = await svc.arun("test prompt")
            assert result.output is not None
            assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_arun_failure(self) -> None:
        config = MagicMock()
        config.max_retries = 0
        config.retry_delay_seconds = 0.01
        config.use_text_tool_schemas = False
        svc = LLMService(MagicMock(), config)

        with patch.object(
            svc,
            "_call_with_retry_async",
            new_callable=AsyncMock,
            return_value=(None, LLMError("fail")),
        ):
            result = await svc.arun("test prompt")
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_arun_timeout(self) -> None:
        config = MagicMock()
        config.max_retries = 0
        config.retry_delay_seconds = 0.01
        config.use_text_tool_schemas = False
        svc = LLMService(MagicMock(), config)
        result = await svc.arun(
            "test",
            max_execution_time=0.0001,
            start_time=time.time() - 100,
        )
        assert "time limit" in result.error.lower()

    @pytest.mark.asyncio
    async def test_arun_max_iterations(self) -> None:
        config = MagicMock()
        config.max_retries = 0
        config.retry_delay_seconds = 0.01
        config.use_text_tool_schemas = False
        svc = LLMService(MagicMock(), config)

        mock_tool = MagicMock()
        mock_tool.name = "tool1"
        mock_tool.description = "Tool"
        mock_tool.get_parameters_schema.return_value = {"type": "object"}
        mock_tool.get_result_schema.return_value = None

        resp = MagicMock()
        resp.content = '<tool_call>\n{"name": "tool1", "parameters": {}}\n</tool_call>'
        resp.total_tokens = 5

        mock_executor = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.result = "r"
        mock_result.error = None
        mock_executor.execute.return_value = mock_result

        with (
            patch.object(
                svc,
                "_call_with_retry_async",
                new_callable=AsyncMock,
                return_value=(resp, None),
            ),
            patch.object(svc, "_estimate_cost", return_value=0.001),
            patch.object(svc, "_track_call"),
            pytest.raises(MaxIterationsError),
        ):
            await svc.arun(
                "test",
                tools=[mock_tool],
                tool_executor=mock_executor,
                max_iterations=1,
            )


# ---------------------------------------------------------------------------
# LLMService delegation methods
# ---------------------------------------------------------------------------


class TestLLMServiceDelegation:
    def test_estimate_cost(self) -> None:
        config = MagicMock()
        config.use_text_tool_schemas = False
        llm = MagicMock()
        llm.model = "test-model"
        svc = LLMService(llm, config)
        resp = MagicMock()
        resp.model = "test-model"
        resp.prompt_tokens = 100
        resp.completion_tokens = 50
        with patch("temper_ai.llm.service.estimate_cost", return_value=0.05):
            cost = svc._estimate_cost(resp)
            assert cost == 0.05

    def test_track_call(self) -> None:
        config = MagicMock()
        svc = LLMService(MagicMock(), config)
        observer = MagicMock()
        with patch("temper_ai.llm.service.track_call") as mock_track:
            svc._track_call(observer, "prompt", MagicMock(), 0.01)
            mock_track.assert_called_once()

    def test_track_failed_call(self) -> None:
        config = MagicMock()
        svc = LLMService(MagicMock(), config)
        observer = MagicMock()
        with patch("temper_ai.llm.service.track_failed_call") as mock_track:
            svc._track_failed_call(observer, "prompt", Exception("e"), 1, 3)
            mock_track.assert_called_once()

    def test_build_text_schemas(self) -> None:
        config = MagicMock()
        config.use_text_tool_schemas = True
        svc = LLMService(MagicMock(), config)
        mock_tool = MagicMock()
        mock_tool.name = "t"
        mock_tool.description = "d"
        mock_tool.get_parameters_schema.return_value = {"type": "object"}
        result = svc._build_text_schemas([mock_tool])
        assert result is not None
        assert "Available Tools" in result

    def test_build_native_tool_defs(self) -> None:
        config = MagicMock()
        svc = LLMService(MagicMock(), config)
        mock_tool = MagicMock()
        mock_tool.name = "t"
        mock_tool.description = "d"
        mock_tool.get_parameters_schema.return_value = {"type": "object"}
        mock_tool.get_result_schema.return_value = None
        result = svc._build_native_tool_defs([mock_tool])
        assert result is not None
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _RunState
# ---------------------------------------------------------------------------


class TestRunState:
    def test_defaults(self) -> None:
        s = _RunState()
        assert s.iteration_number == 0
        assert s.total_tokens == 0
        assert s.total_cost == 0.0
        assert s.tools is None
        assert s.messages is None

    def test_custom(self) -> None:
        s = _RunState(agent_name="test-agent", resolved_max_iterations=5)
        assert s.agent_name == "test-agent"
        assert s.resolved_max_iterations == 5


# ---------------------------------------------------------------------------
# LLMRunResult
# ---------------------------------------------------------------------------


class TestLLMRunResult:
    def test_defaults(self) -> None:
        r = LLMRunResult(output="hello")
        assert r.output == "hello"
        assert r.reasoning is None
        assert r.tool_calls == []
        assert r.tokens == 0
        assert r.cost == 0.0
        assert r.error is None

    def test_with_error(self) -> None:
        r = LLMRunResult(output="", error="something went wrong")
        assert r.error == "something went wrong"
