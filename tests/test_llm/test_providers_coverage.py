"""Coverage tests for LLM provider implementations.

Covers: VllmLLM, OllamaLLM, OpenAILLM, AnthropicLLM — all methods including
build_request, parse_response, streaming, SSE parsing, tool call handling.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.llm.providers.base import LLMProvider, LLMResponse

# ===========================================================================
# VllmLLM tests
# ===========================================================================


class TestVllmLLM:
    """Tests for temper_ai.llm.providers.vllm_provider.VllmLLM."""

    def _make_provider(self, **kwargs: Any) -> Any:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        defaults = {
            "model": "test-model",
            "base_url": "http://localhost:8000",
        }
        defaults.update(kwargs)
        return VllmLLM(**defaults)

    def test_get_endpoint(self) -> None:
        p = self._make_provider()
        assert p._get_endpoint() == "/v1/chat/completions"

    def test_get_headers_with_api_key(self) -> None:
        p = self._make_provider(api_key="test-key")
        headers = p._get_headers()
        assert headers["Authorization"] == "Bearer test-key"
        assert headers["Content-Type"] == "application/json"

    def test_get_headers_without_api_key(self) -> None:
        p = self._make_provider()
        headers = p._get_headers()
        assert "Authorization" not in headers

    def test_build_request_basic(self) -> None:
        p = self._make_provider()
        req = p._build_request("Hello")
        assert req["model"] == "test-model"
        assert req["messages"] == [{"role": "user", "content": "Hello"}]
        assert req["stream"] is False

    def test_build_request_with_messages(self) -> None:
        p = self._make_provider()
        msgs = [{"role": "system", "content": "Be helpful"}]
        req = p._build_request("Hello", messages=msgs)
        assert req["messages"] == msgs

    def test_build_request_with_tools(self) -> None:
        p = self._make_provider()
        tools = [{"type": "function", "function": {"name": "test"}}]
        req = p._build_request("Hello", tools=tools)
        assert req["tools"] == tools

    def test_build_request_streaming(self) -> None:
        p = self._make_provider()
        req = p._build_request("Hello", stream=True)
        assert req["stream"] is True
        assert req["stream_options"] == {"include_usage": True}

    def test_build_request_repeat_penalty(self) -> None:
        p = self._make_provider()
        req = p._build_request("Hello", repeat_penalty=1.2)
        assert req["repetition_penalty"] == 1.2

    def test_parse_response(self) -> None:
        p = self._make_provider()
        response_data = {
            "choices": [
                {
                    "message": {"content": "Hi there"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            "model": "test-model",
        }
        result = p._parse_response(response_data, 100)
        assert result.content == "Hi there"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 5
        assert result.provider == LLMProvider.VLLM

    def test_parse_response_with_tool_calls(self) -> None:
        p = self._make_provider()
        response_data = {
            "choices": [
                {
                    "message": {
                        "content": "I'll search",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "search",
                                    "arguments": '{"query": "test"}',
                                }
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {},
            "model": "test-model",
        }
        result = p._parse_response(response_data, 100)
        assert "<tool_call>" in result.content
        assert "search" in result.content

    def test_format_tool_calls_xml_empty(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        assert VllmLLM._format_tool_calls_xml([]) == ""

    def test_format_tool_calls_xml(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        tool_calls = [{"function": {"name": "test", "arguments": {"key": "value"}}}]
        result = VllmLLM._format_tool_calls_xml(tool_calls)
        assert "<tool_call>" in result
        assert "test" in result

    def test_format_tool_calls_xml_string_args(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        tool_calls = [{"function": {"name": "test", "arguments": '{"key": "value"}'}}]
        result = VllmLLM._format_tool_calls_xml(tool_calls)
        assert "<tool_call>" in result

    def test_format_tool_calls_xml_invalid_json_args(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        tool_calls = [{"function": {"name": "test", "arguments": "not-json{"}}]
        result = VllmLLM._format_tool_calls_xml(tool_calls)
        assert "<tool_call>" in result

    def test_parse_sse_line_empty(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        assert VllmLLM._parse_sse_line("") is None
        assert VllmLLM._parse_sse_line("   ") is None

    def test_parse_sse_line_done(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        result = VllmLLM._parse_sse_line("data: [DONE]")
        assert result == "[DONE]"

    def test_parse_sse_line_valid_json(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        result = VllmLLM._parse_sse_line('data: {"test": 1}')
        assert result == {"test": 1}

    def test_parse_sse_line_invalid_json(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        assert VllmLLM._parse_sse_line("data: {invalid}") is None

    def test_parse_sse_line_not_data(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        assert VllmLLM._parse_sse_line("event: update") is None

    def test_extract_chunk_fields_empty_choices(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        content, ctype, done = VllmLLM._extract_chunk_fields({"choices": []})
        assert content == ""
        assert done is False

    def test_extract_chunk_fields_content(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        data = {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]}
        content, ctype, done = VllmLLM._extract_chunk_fields(data)
        assert content == "hello"
        assert ctype == "content"
        assert done is False

    def test_extract_chunk_fields_reasoning(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        data = {
            "choices": [
                {
                    "delta": {"reasoning_content": "thinking...", "content": ""},
                    "finish_reason": None,
                }
            ]
        }
        content, ctype, done = VllmLLM._extract_chunk_fields(data)
        assert content == "thinking..."
        assert ctype == "thinking"

    def test_extract_chunk_fields_done(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        data = {"choices": [{"delta": {"content": "end"}, "finish_reason": "stop"}]}
        content, ctype, done = VllmLLM._extract_chunk_fields(data)
        assert done is True

    def test_accumulate_delta_tool_calls(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        buf: dict[int, dict[str, str]] = {}
        data = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"name": "search", "arguments": '{"q"'},
                            }
                        ]
                    }
                }
            ]
        }
        VllmLLM._accumulate_delta_tool_calls(data, buf)
        assert buf[0]["name"] == "search"
        assert buf[0]["arguments"] == '{"q"'

        # Second chunk appends
        data2 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ': "test"}'},
                            }
                        ]
                    }
                }
            ]
        }
        VllmLLM._accumulate_delta_tool_calls(data2, buf)
        assert '{"q": "test"}' in buf[0]["arguments"]

    def test_accumulate_delta_tool_calls_empty(self) -> None:
        from temper_ai.llm.providers.vllm_provider import VllmLLM

        buf: dict[int, dict[str, str]] = {}
        VllmLLM._accumulate_delta_tool_calls({"choices": []}, buf)
        assert len(buf) == 0

    def test_process_sse_chunk(self) -> None:
        p = self._make_provider()
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_call_buf: dict[int, dict[str, str]] = {}
        on_chunk = MagicMock()

        data = {
            "choices": [{"delta": {"content": "hi"}, "finish_reason": None}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }
        pt, ct, fr = p._process_sse_chunk(
            data, content_parts, thinking_parts, tool_call_buf, on_chunk
        )
        assert pt == 5
        assert ct == 3
        assert fr is None
        assert "hi" in content_parts

    def test_finalize_and_build(self) -> None:
        p = self._make_provider()
        result = p._finalize_and_build(["hello", " world"], {}, 10, 5, "stop")
        assert result.content == "hello world"
        assert result.prompt_tokens == 10

    def test_finalize_and_build_with_tool_calls(self) -> None:
        p = self._make_provider()
        tool_buf = {0: {"name": "search", "arguments": '{"q": "test"}'}}
        result = p._finalize_and_build(["content"], tool_buf, None, None, None)
        assert "<tool_call>" in result.content

    def test_consume_stream(self) -> None:
        p = self._make_provider()
        mock_response = MagicMock()
        lines = [
            'data: {"choices": [{"delta": {"content": "hi"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {"content": " there"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
            "data: [DONE]",
        ]
        mock_response.iter_lines.return_value = iter(lines)
        on_chunk = MagicMock()
        result = p._consume_stream(mock_response, on_chunk)
        assert "hi" in result.content

    @pytest.mark.asyncio
    async def test_aconsume_stream(self) -> None:
        p = self._make_provider()
        mock_response = AsyncMock()
        lines = [
            'data: {"choices": [{"delta": {"content": "hello"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
            "data: [DONE]",
        ]

        async def aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        on_chunk = MagicMock()
        result = await p._aconsume_stream(mock_response, on_chunk)
        assert "hello" in result.content

    def test_stream_no_callback_falls_back(self) -> None:
        p = self._make_provider()
        with patch.object(
            p,
            "complete",
            return_value=LLMResponse(content="fb", model="m", provider="p"),
        ):
            result = p.stream("test", on_chunk=None)
            assert result.content == "fb"


# ===========================================================================
# OllamaLLM tests
# ===========================================================================


class TestOllamaLLM:
    """Tests for temper_ai.llm.providers.ollama.OllamaLLM."""

    def _make_provider(self, **kwargs: Any) -> Any:
        from temper_ai.llm.providers.ollama import OllamaLLM

        defaults = {
            "model": "llama3",
            "base_url": "http://localhost:11434",
        }
        defaults.update(kwargs)
        return OllamaLLM(**defaults)

    def test_get_endpoint_generate(self) -> None:
        p = self._make_provider()
        assert p._get_endpoint() == "/api/generate"

    def test_get_endpoint_chat(self) -> None:
        p = self._make_provider()
        p._use_chat_api = True
        assert p._get_endpoint() == "/api/chat"

    def test_get_headers(self) -> None:
        p = self._make_provider()
        headers = p._get_headers()
        assert headers["Content-Type"] == "application/json"

    def test_build_request_generate(self) -> None:
        p = self._make_provider()
        req = p._build_request("Hello")
        assert req["prompt"] == "Hello"
        assert "messages" not in req
        assert p._use_chat_api is False

    def test_build_request_with_tools(self) -> None:
        p = self._make_provider()
        tools = [{"type": "function", "function": {"name": "test"}}]
        req = p._build_request("Hello", tools=tools)
        assert "messages" in req
        assert p._use_chat_api is True
        assert "tools" in req

    def test_build_request_with_messages(self) -> None:
        p = self._make_provider()
        msgs = [{"role": "user", "content": "Hi"}]
        req = p._build_request("Hello", messages=msgs)
        assert req["messages"] == msgs
        assert p._use_chat_api is True

    def test_build_request_with_tools_and_messages(self) -> None:
        p = self._make_provider()
        tools = [{"type": "function"}]
        msgs = [{"role": "user", "content": "Custom"}]
        req = p._build_request("Hello", tools=tools, messages=msgs)
        assert req["messages"] == msgs

    def test_parse_response_generate(self) -> None:
        p = self._make_provider()
        p._use_chat_api = False
        response_data = {
            "response": "Hello World",
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        result = p._parse_response(response_data, 100)
        assert result.content == "Hello World"
        assert result.provider == LLMProvider.OLLAMA
        assert result.finish_reason == "stop"

    def test_parse_response_chat(self) -> None:
        p = self._make_provider()
        p._use_chat_api = True
        response_data = {
            "message": {"content": "Chat response"},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        result = p._parse_response(response_data, 100)
        assert result.content == "Chat response"

    def test_parse_response_chat_with_tool_calls(self) -> None:
        p = self._make_provider()
        p._use_chat_api = True
        response_data = {
            "message": {
                "content": "Using tool",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search",
                            "arguments": {"query": "test"},
                        }
                    }
                ],
            },
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        result = p._parse_response(response_data, 100)
        assert "<tool_call>" in result.content
        assert "search" in result.content

    def test_parse_response_not_done(self) -> None:
        p = self._make_provider()
        p._use_chat_api = False
        response_data = {"response": "partial", "done": False}
        result = p._parse_response(response_data, 50)
        assert result.finish_reason is None

    def test_extract_chunk_fields_chat_thinking(self) -> None:
        p = self._make_provider()
        p._use_chat_api = True
        data = {"message": {"thinking": "reasoning", "content": ""}, "done": False}
        content, ctype, done = p._extract_chunk_fields(data)
        assert content == "reasoning"
        assert ctype == "thinking"

    def test_extract_chunk_fields_chat_content(self) -> None:
        p = self._make_provider()
        p._use_chat_api = True
        data = {"message": {"content": "hello"}, "done": False}
        content, ctype, done = p._extract_chunk_fields(data)
        assert content == "hello"
        assert ctype == "content"

    def test_extract_chunk_fields_generate_thinking(self) -> None:
        p = self._make_provider()
        p._use_chat_api = False
        data = {"thinking": "I think", "response": "", "done": False}
        content, ctype, done = p._extract_chunk_fields(data)
        assert content == "I think"
        assert ctype == "thinking"

    def test_extract_chunk_fields_generate_content(self) -> None:
        p = self._make_provider()
        p._use_chat_api = False
        data = {"response": "hello", "done": True}
        content, ctype, done = p._extract_chunk_fields(data)
        assert content == "hello"
        assert done is True

    def test_consume_stream(self) -> None:
        p = self._make_provider()
        p._use_chat_api = False
        mock_response = MagicMock()
        lines = [
            '{"response": "hi", "done": false}',
            '{"response": " there", "done": true, "prompt_eval_count": 10, "eval_count": 5}',
        ]
        mock_response.iter_lines.return_value = iter(lines)
        on_chunk = MagicMock()
        result = p._consume_stream(mock_response, on_chunk)
        assert "hi" in result.content

    def test_consume_stream_empty_line(self) -> None:
        p = self._make_provider()
        p._use_chat_api = False
        mock_response = MagicMock()
        lines = [
            "",
            "   ",
            '{"response": "ok", "done": true, "prompt_eval_count": 5, "eval_count": 2}',
        ]
        mock_response.iter_lines.return_value = iter(lines)
        on_chunk = MagicMock()
        result = p._consume_stream(mock_response, on_chunk)
        assert "ok" in result.content

    def test_consume_stream_invalid_json(self) -> None:
        p = self._make_provider()
        p._use_chat_api = False
        mock_response = MagicMock()
        lines = [
            "not-json{",
            '{"response": "ok", "done": true}',
        ]
        mock_response.iter_lines.return_value = iter(lines)
        on_chunk = MagicMock()
        result = p._consume_stream(mock_response, on_chunk)
        assert "ok" in result.content

    @pytest.mark.asyncio
    async def test_aconsume_stream(self) -> None:
        p = self._make_provider()
        p._use_chat_api = False
        mock_response = AsyncMock()

        lines = [
            '{"response": "async", "done": false}',
            '{"response": " ok", "done": true, "prompt_eval_count": 8, "eval_count": 3}',
        ]

        async def aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        on_chunk = MagicMock()
        result = await p._aconsume_stream(mock_response, on_chunk)
        assert "async" in result.content

    @pytest.mark.asyncio
    async def test_aconsume_stream_skips_empty_and_invalid(self) -> None:
        p = self._make_provider()
        p._use_chat_api = False
        mock_response = AsyncMock()

        lines = ["", "  ", "not-json{", '{"response": "x", "done": true}']

        async def aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        on_chunk = MagicMock()
        result = await p._aconsume_stream(mock_response, on_chunk)
        assert result.content == "x"

    def test_stream_no_callback(self) -> None:
        p = self._make_provider()
        with patch.object(
            p,
            "complete",
            return_value=LLMResponse(content="fb", model="m", provider="p"),
        ):
            result = p.stream("test", on_chunk=None)
            assert result.content == "fb"


# ===========================================================================
# OpenAILLM tests
# ===========================================================================


class TestOpenAILLM:
    """Tests for temper_ai.llm.providers.openai_provider.OpenAILLM."""

    def _make_provider(self, **kwargs: Any) -> Any:
        from temper_ai.llm.providers.openai_provider import OpenAILLM

        defaults = {
            "model": "gpt-4",
            "base_url": "https://api.openai.com",
            "api_key": "sk-test",
        }
        defaults.update(kwargs)
        return OpenAILLM(**defaults)

    def test_get_endpoint(self) -> None:
        p = self._make_provider()
        assert p._get_endpoint() == "/v1/chat/completions"

    def test_get_headers(self) -> None:
        p = self._make_provider()
        headers = p._get_headers()
        assert headers["Authorization"] == "Bearer sk-test"

    def test_build_request_basic(self) -> None:
        p = self._make_provider()
        req = p._build_request("Hello")
        assert req["model"] == "gpt-4"
        assert req["messages"] == [{"role": "user", "content": "Hello"}]

    def test_build_request_with_messages(self) -> None:
        p = self._make_provider()
        msgs = [{"role": "system", "content": "You are helpful"}]
        req = p._build_request("Hello", messages=msgs)
        assert req["messages"] == msgs

    def test_parse_response(self) -> None:
        p = self._make_provider()
        resp = {
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            "model": "gpt-4",
        }
        result = p._parse_response(resp, 100)
        assert result.content == "Hi"
        assert result.provider == LLMProvider.OPENAI

    def test_extract_openai_chunk_with_content(self) -> None:
        from temper_ai.llm.providers.openai_provider import OpenAILLM

        data = {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]}
        content, fin, usage = OpenAILLM._extract_openai_chunk(data)
        assert content == "hello"
        assert fin is None
        assert usage is None

    def test_extract_openai_chunk_with_finish(self) -> None:
        from temper_ai.llm.providers.openai_provider import OpenAILLM

        data = {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        content, fin, usage = OpenAILLM._extract_openai_chunk(data)
        assert fin == "stop"
        assert usage is not None

    def test_extract_openai_chunk_empty_choices(self) -> None:
        from temper_ai.llm.providers.openai_provider import OpenAILLM

        content, fin, usage = OpenAILLM._extract_openai_chunk({"choices": []})
        assert content == ""

    def test_consume_stream(self) -> None:
        p = self._make_provider()
        mock_response = MagicMock()
        lines = [
            'data: {"choices": [{"delta": {"content": "hi"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
            "data: [DONE]",
        ]
        mock_response.iter_lines.return_value = iter(lines)
        on_chunk = MagicMock()
        result = p._consume_stream(mock_response, on_chunk)
        assert "hi" in result.content
        assert result.provider == LLMProvider.OPENAI

    def test_consume_stream_skips_non_data_lines(self) -> None:
        p = self._make_provider()
        mock_response = MagicMock()
        lines = [
            "",
            "event: ping",
            'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ]
        mock_response.iter_lines.return_value = iter(lines)
        on_chunk = MagicMock()
        result = p._consume_stream(mock_response, on_chunk)
        assert "ok" in result.content

    def test_consume_stream_invalid_json(self) -> None:
        p = self._make_provider()
        mock_response = MagicMock()
        lines = [
            "data: {invalid}",
            'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ]
        mock_response.iter_lines.return_value = iter(lines)
        on_chunk = MagicMock()
        result = p._consume_stream(mock_response, on_chunk)
        assert "ok" in result.content

    @pytest.mark.asyncio
    async def test_aconsume_stream(self) -> None:
        p = self._make_provider()
        mock_response = AsyncMock()

        lines = [
            'data: {"choices": [{"delta": {"content": "async"}, "finish_reason": null}]}',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
            "data: [DONE]",
        ]

        async def aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        on_chunk = MagicMock()
        result = await p._aconsume_stream(mock_response, on_chunk)
        assert "async" in result.content

    @pytest.mark.asyncio
    async def test_aconsume_stream_skips_invalid(self) -> None:
        p = self._make_provider()
        mock_response = AsyncMock()

        lines = [
            "",
            "data: {invalid-json",
            'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ]

        async def aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = aiter_lines
        on_chunk = MagicMock()
        result = await p._aconsume_stream(mock_response, on_chunk)
        assert "ok" in result.content

    def test_stream_no_callback(self) -> None:
        p = self._make_provider()
        with patch.object(
            p,
            "complete",
            return_value=LLMResponse(content="fb", model="m", provider="p"),
        ):
            result = p.stream("test", on_chunk=None)
            assert result.content == "fb"


# ===========================================================================
# AnthropicLLM tests
# ===========================================================================


class TestAnthropicLLM:
    """Tests for temper_ai.llm.providers.anthropic_provider.AnthropicLLM."""

    def _make_provider(self, **kwargs: Any) -> Any:
        from temper_ai.llm.providers.anthropic_provider import AnthropicLLM

        defaults = {
            "model": "claude-3-opus",
            "base_url": "https://api.anthropic.com",
            "api_key": "sk-ant-test",
        }
        defaults.update(kwargs)
        return AnthropicLLM(**defaults)

    def test_get_endpoint(self) -> None:
        p = self._make_provider()
        assert p._get_endpoint() == "/v1/messages"

    def test_get_headers_with_api_key(self) -> None:
        p = self._make_provider()
        headers = p._get_headers()
        assert headers["x-api-key"] == "sk-ant-test"
        assert headers["anthropic-version"] == "2023-06-01"

    def test_get_headers_without_api_key(self) -> None:
        p = self._make_provider(api_key=None)
        headers = p._get_headers()
        assert "x-api-key" not in headers

    def test_build_request_basic(self) -> None:
        p = self._make_provider()
        req = p._build_request("Hello")
        assert req["model"] == "claude-3-opus"
        assert req["messages"] == [{"role": "user", "content": "Hello"}]

    def test_build_request_with_system_message(self) -> None:
        p = self._make_provider()
        msgs = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hello"},
        ]
        req = p._build_request("Hello", messages=msgs)
        assert req["system"] == "Be helpful"
        # System messages should be excluded from messages list
        assert all(m["role"] != "system" for m in req["messages"])

    def test_parse_response(self) -> None:
        p = self._make_provider()
        resp = {
            "content": [{"text": "Hello there"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "model": "claude-3-opus",
            "stop_reason": "end_turn",
        }
        result = p._parse_response(resp, 100)
        assert result.content == "Hello there"
        assert result.provider == LLMProvider.ANTHROPIC
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 5
        assert result.total_tokens == 15

    def test_consume_stream_not_implemented(self) -> None:
        p = self._make_provider()
        with pytest.raises(NotImplementedError):
            p._consume_stream(MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_aconsume_stream_not_implemented(self) -> None:
        p = self._make_provider()
        with pytest.raises(NotImplementedError):
            await p._aconsume_stream(MagicMock(), MagicMock())
