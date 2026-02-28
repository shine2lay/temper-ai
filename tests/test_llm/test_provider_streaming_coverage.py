"""Coverage tests for provider streaming methods (stream/astream).

Covers the uncovered streaming paths in OllamaLLM, OpenAILLM, and VllmLLM
that go through the full circuit breaker + streaming call flow.
Also covers factory.py remaining uncovered branches.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.llm.providers.base import BaseLLM, LLMResponse


@pytest.fixture(autouse=True)
def reset_circuit_breakers() -> None:
    """Reset shared circuit breakers before each test."""
    BaseLLM.reset_shared_circuit_breakers()
    yield  # type: ignore[misc]
    BaseLLM.reset_shared_circuit_breakers()


# ===========================================================================
# OllamaLLM streaming
# ===========================================================================


class TestOllamaStreaming:
    def _make_provider(self, **kwargs: Any) -> Any:
        from temper_ai.llm.providers.ollama import OllamaLLM

        defaults = {"model": "llama3", "base_url": "http://localhost:11434"}
        defaults.update(kwargs)
        return OllamaLLM(**defaults)

    def test_stream_with_callback(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()
        # Mock the client chain
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200

        # The consume_stream path
        lines = [
            '{"response": "hello", "done": false}',
            '{"response": " world", "done": true, "prompt_eval_count": 10, "eval_count": 5}',
        ]
        mock_response.iter_lines.return_value = iter(lines)
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response

        with patch.object(p, "_get_client", return_value=mock_client):
            result = p.stream("test", on_chunk=on_chunk)
            assert "hello" in result.content

    def test_stream_with_cached_response(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()
        cached = LLMResponse(content="cached", model="m", provider="p")
        with patch.object(p, "_make_streaming_call_impl", return_value=("key", cached)):
            result = p.stream("test", on_chunk=on_chunk)
            assert result.content == "cached"

    @pytest.mark.asyncio
    async def test_astream_no_callback(self) -> None:
        p = self._make_provider()
        with patch.object(
            p,
            "acomplete",
            new_callable=AsyncMock,
            return_value=LLMResponse(content="fb", model="m", provider="p"),
        ):
            result = await p.astream("test", on_chunk=None)
            assert result.content == "fb"

    @pytest.mark.asyncio
    async def test_astream_with_callback(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()

        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200

        lines = [
            '{"response": "async_hello", "done": false}',
            '{"response": "", "done": true, "prompt_eval_count": 5, "eval_count": 3}',
        ]

        async def aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        mock_response.aclose = AsyncMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(return_value=mock_response)

        with patch.object(
            p,
            "_get_async_client_safe",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            result = await p.astream("test", on_chunk=on_chunk)
            assert "async_hello" in result.content

    @pytest.mark.asyncio
    async def test_astream_cached(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()
        cached = LLMResponse(content="cached", model="m", provider="p")
        with patch.object(p, "_make_streaming_call_impl", return_value=("key", cached)):
            result = await p.astream("test", on_chunk=on_chunk)
            assert result.content == "cached"


# ===========================================================================
# OpenAILLM streaming
# ===========================================================================


class TestOpenAIStreaming:
    def _make_provider(self, **kwargs: Any) -> Any:
        from temper_ai.llm.providers.openai_provider import OpenAILLM

        defaults = {
            "model": "gpt-4",
            "base_url": "https://api.openai.com",
            "api_key": "sk-test",
        }
        defaults.update(kwargs)
        return OpenAILLM(**defaults)

    def test_stream_with_callback(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200

        lines = [
            'data: {"choices": [{"delta": {"content": "hi"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
            "data: [DONE]",
        ]
        mock_response.iter_lines.return_value = iter(lines)
        mock_response.close = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response

        with patch.object(p, "_get_client", return_value=mock_client):
            result = p.stream("test", on_chunk=on_chunk)
            assert "hi" in result.content

    def test_stream_cached(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()
        cached = LLMResponse(content="cached", model="m", provider="p")
        with patch.object(p, "_make_streaming_call_impl", return_value=("key", cached)):
            result = p.stream("test", on_chunk=on_chunk)
            assert result.content == "cached"

    @pytest.mark.asyncio
    async def test_astream_no_callback(self) -> None:
        p = self._make_provider()
        with patch.object(
            p,
            "acomplete",
            new_callable=AsyncMock,
            return_value=LLMResponse(content="fb", model="m", provider="p"),
        ):
            result = await p.astream("test", on_chunk=None)
            assert result.content == "fb"

    @pytest.mark.asyncio
    async def test_astream_with_callback(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()

        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200

        lines = [
            'data: {"choices": [{"delta": {"content": "async"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
            "data: [DONE]",
        ]

        async def aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        mock_response.aclose = AsyncMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(return_value=mock_response)

        with patch.object(
            p,
            "_get_async_client_safe",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            result = await p.astream("test", on_chunk=on_chunk)
            assert "async" in result.content

    @pytest.mark.asyncio
    async def test_astream_cached(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()
        cached = LLMResponse(content="cached", model="m", provider="p")
        with patch.object(p, "_make_streaming_call_impl", return_value=("key", cached)):
            result = await p.astream("test", on_chunk=on_chunk)
            assert result.content == "cached"


# ===========================================================================
# VllmLLM streaming
# ===========================================================================


class TestVllmStreaming:
    def _make_provider(self, **kwargs: Any) -> Any:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        defaults = {"model": "llama3", "base_url": "http://localhost:8000"}
        defaults.update(kwargs)
        return VllmLLM(**defaults)

    def test_stream_with_callback(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200

        lines = [
            'data: {"choices": [{"delta": {"content": "hello"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
            "data: [DONE]",
        ]
        mock_response.iter_lines.return_value = iter(lines)
        mock_response.close = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response

        with patch.object(p, "_get_client", return_value=mock_client):
            result = p.stream("test", on_chunk=on_chunk)
            assert "hello" in result.content

    def test_stream_cached(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()
        cached = LLMResponse(content="cached", model="m", provider="p")
        with patch.object(p, "_make_streaming_call_impl", return_value=("key", cached)):
            result = p.stream("test", on_chunk=on_chunk)
            assert result.content == "cached"

    @pytest.mark.asyncio
    async def test_astream_no_callback(self) -> None:
        p = self._make_provider()
        with patch.object(
            p,
            "acomplete",
            new_callable=AsyncMock,
            return_value=LLMResponse(content="fb", model="m", provider="p"),
        ):
            result = await p.astream("test", on_chunk=None)
            assert result.content == "fb"

    @pytest.mark.asyncio
    async def test_astream_with_callback(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()

        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200

        lines = [
            'data: {"choices": [{"delta": {"content": "async"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
            "data: [DONE]",
        ]

        async def aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        mock_response.aclose = AsyncMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send = AsyncMock(return_value=mock_response)

        with patch.object(
            p,
            "_get_async_client_safe",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            result = await p.astream("test", on_chunk=on_chunk)
            assert "async" in result.content

    @pytest.mark.asyncio
    async def test_astream_cached(self) -> None:
        p = self._make_provider()
        on_chunk = MagicMock()
        cached = LLMResponse(content="cached", model="m", provider="p")
        with patch.object(p, "_make_streaming_call_impl", return_value=("key", cached)):
            result = await p.astream("test", on_chunk=on_chunk)
            assert result.content == "cached"

    def test_consume_stream_with_tool_calls(self) -> None:
        """Test _consume_stream when streaming tool calls accumulate."""
        p = self._make_provider()
        mock_response = MagicMock()
        lines = [
            'data: {"choices": [{"delta": {"content": "", "tool_calls": [{"index": 0, "function": {"name": "search", "arguments": "{\\"q"}}]}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {"content": "", "tool_calls": [{"index": 0, "function": {"arguments": ": \\"test\\"}"}}]}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
            "data: [DONE]",
        ]
        mock_response.iter_lines.return_value = iter(lines)
        on_chunk = MagicMock()
        result = p._consume_stream(mock_response, on_chunk)
        assert "<tool_call>" in result.content

    @pytest.mark.asyncio
    async def test_aconsume_stream_with_no_tokens_update(self) -> None:
        """Test _aconsume_stream where usage comes at end."""
        p = self._make_provider()
        mock_response = AsyncMock()

        lines = [
            'data: {"choices": [{"delta": {"content": "hi"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 8, "completion_tokens": 2}}',
            "data: [DONE]",
        ]

        async def aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        on_chunk = MagicMock()
        result = await p._aconsume_stream(mock_response, on_chunk)
        assert result.prompt_tokens == 8
        assert result.completion_tokens == 2


# ===========================================================================
# PromptEngine remaining coverage
# ===========================================================================


class TestPromptEngineDefaultDirSearch:
    def test_search_up_for_configs_prompts(self) -> None:
        """Test the loop that searches parent directories."""
        from temper_ai.llm.prompts.engine import PromptEngine

        # When no templates_dir is provided and cwd doesn't have configs/prompts,
        # the engine searches parent dirs. Test the edge case where it walks up.
        with patch("temper_ai.llm.prompts.engine.Path.cwd") as mock_cwd:
            # Create a mock path that always says configs/prompts doesn't exist
            mock_path = MagicMock()
            mock_path.__truediv__ = lambda self, x: MagicMock(
                exists=lambda: False,
                __truediv__=lambda self, y: MagicMock(exists=lambda: False),
            )
            mock_path.parent = mock_path  # Simulate root (parent == self)
            mock_path.__eq__ = lambda self, other: True
            mock_path.__ne__ = lambda self, other: False
            mock_cwd.return_value = mock_path
            # Should not error, just create engine without templates dir
            engine = PromptEngine(templates_dir=None)
            assert engine is not None

    def test_render_file_error(self) -> None:
        """Test render_file with a template that has render errors."""
        import os
        import tempfile

        from temper_ai.llm.prompts.engine import PromptEngine
        from temper_ai.llm.prompts.validation import PromptRenderError

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "bad.txt")
            with open(template_path, "w") as f:
                f.write("{{ undefined_var.missing_attr }}")
            engine = PromptEngine(templates_dir=tmpdir)
            with pytest.raises(PromptRenderError):
                engine.render_file("bad.txt", {})
