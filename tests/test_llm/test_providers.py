"""Tests for LLM providers — request building, response parsing, retry, streaming."""

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from temper_ai.llm.models import LLMStreamChunk
from temper_ai.llm.providers.factory import create_provider
from temper_ai.llm.providers.openai import OpenAILLM
from temper_ai.llm.providers.vllm import VllmLLM


# -- OpenAI: request building --


class TestOpenAIBuildRequest:
    def test_basic_request(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")
        req = p._build_request([{"role": "user", "content": "Hi"}])
        assert req["model"] == "gpt-4"
        assert req["messages"] == [{"role": "user", "content": "Hi"}]
        assert req["temperature"] == 0.7
        assert "stream" not in req
        assert "tools" not in req

    def test_with_tools(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")
        tools = [{"type": "function", "function": {"name": "bash"}}]
        req = p._build_request([{"role": "user", "content": "Hi"}], tools=tools)
        assert req["tools"] == tools

    def test_with_stream_flag(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")
        req = p._build_request([{"role": "user", "content": "Hi"}], stream=True)
        assert req["stream"] is True

    def test_extra_kwargs_from_constructor(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test", top_p=0.9)
        req = p._build_request([{"role": "user", "content": "Hi"}])
        assert req["top_p"] == 0.9

    def test_explicit_kwargs_dont_override_extra(self):
        """Extra kwargs from constructor use setdefault, so explicit wins."""
        p = OpenAILLM(model="gpt-4", base_url="http://test", temperature=0.5)
        req = p._build_request([{"role": "user", "content": "Hi"}])
        # temperature is set directly in the request, extra_kwargs use setdefault
        assert req["temperature"] == 0.5


# -- OpenAI: response parsing --


class TestOpenAIParseResponse:
    def test_text_response(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")
        raw = {
            "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "gpt-4",
        }
        resp = p._parse_response(raw, latency_ms=100)
        assert resp.content == "Hello"
        assert resp.prompt_tokens == 10
        assert resp.completion_tokens == 5
        assert resp.total_tokens == 15
        assert resp.latency_ms == 100
        assert resp.finish_reason == "stop"
        assert resp.tool_calls is None
        assert resp.model == "gpt-4"
        assert resp.provider == "openai"

    def test_tool_call_response(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")
        raw = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": '{"command": "ls"}',
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            "model": "gpt-4",
        }
        resp = p._parse_response(raw, latency_ms=200)
        assert resp.content is None
        assert resp.finish_reason == "tool_calls"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["id"] == "call_abc"
        assert resp.tool_calls[0]["name"] == "bash"
        assert resp.tool_calls[0]["arguments"] == '{"command": "ls"}'

    def test_no_usage_field(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")
        raw = {
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
            "model": "gpt-4",
        }
        resp = p._parse_response(raw, latency_ms=50)
        assert resp.content == "Hi"
        assert resp.prompt_tokens is None


# -- OpenAI: complete with mocked HTTP --


class TestOpenAIComplete:
    def _make_provider(self, **kwargs):
        p = OpenAILLM(model="gpt-4", base_url="http://test", api_key="test-key", **kwargs)
        return p

    def _mock_success_response(self, content="Hello", tokens=15):
        mock = MagicMock()
        mock.json.return_value = {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": tokens - 10, "total_tokens": tokens},
            "model": "gpt-4",
        }
        mock.raise_for_status = MagicMock()
        return mock

    def test_successful_complete(self):
        p = self._make_provider()
        mock_client = MagicMock()
        mock_client.post.return_value = self._mock_success_response()
        p._http_client = mock_client

        result = p.complete([{"role": "user", "content": "Hi"}])
        assert result.content == "Hello"
        assert result.total_tokens == 15
        mock_client.post.assert_called_once()

    def _make_http_error(self, status_code, message="error"):
        """Create an HTTPStatusError with a properly wired response mock."""
        resp_mock = MagicMock()
        resp_mock.status_code = status_code
        error = httpx.HTTPStatusError(
            message, request=MagicMock(), response=resp_mock,
        )
        # Wire the mock: post() returns resp_mock, raise_for_status() raises
        resp_mock.raise_for_status.side_effect = error
        return resp_mock

    def test_retry_on_429(self):
        p = self._make_provider(max_retries=3)

        error_resp = self._make_http_error(429, "Rate limited")

        mock_client = MagicMock()
        mock_client.post.side_effect = [error_resp, self._mock_success_response()]
        p._http_client = mock_client

        with patch("temper_ai.llm.providers.base.time.sleep"):
            result = p.complete([{"role": "user", "content": "Hi"}])

        assert result.content == "Hello"
        assert mock_client.post.call_count == 2

    def test_retry_on_500(self):
        p = self._make_provider(max_retries=3)

        error_resp = self._make_http_error(500, "Server error")

        mock_client = MagicMock()
        mock_client.post.side_effect = [error_resp, self._mock_success_response()]
        p._http_client = mock_client

        with patch("temper_ai.llm.providers.base.time.sleep"):
            result = p.complete([{"role": "user", "content": "Hi"}])

        assert result.content == "Hello"

    def test_no_retry_on_400(self):
        p = self._make_provider(max_retries=3)

        error_resp = self._make_http_error(400, "Bad request")

        mock_client = MagicMock()
        mock_client.post.return_value = error_resp
        p._http_client = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            p.complete([{"role": "user", "content": "Hi"}])

        assert mock_client.post.call_count == 1  # no retry

    def test_retry_on_timeout(self):
        p = self._make_provider(max_retries=2)

        mock_client = MagicMock()
        mock_client.post.side_effect = [
            httpx.ConnectTimeout("timeout"),
            self._mock_success_response(),
        ]
        p._http_client = mock_client

        with patch("temper_ai.llm.providers.base.time.sleep"):
            result = p.complete([{"role": "user", "content": "Hi"}])

        assert result.content == "Hello"

    def test_all_retries_exhausted(self):
        p = self._make_provider(max_retries=2)

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectTimeout("timeout")
        p._http_client = mock_client

        with patch("temper_ai.llm.providers.base.time.sleep"):
            with pytest.raises(httpx.ConnectTimeout):
                p.complete([{"role": "user", "content": "Hi"}])

        assert mock_client.post.call_count == 2

    def test_backoff_delay_increases(self):
        """Verify exponential backoff: delay grows with each attempt."""
        p = self._make_provider(max_retries=4)

        error_resp = self._make_http_error(500, "Server error")
        mock_client = MagicMock()
        mock_client.post.side_effect = [
            error_resp, error_resp, error_resp,
            self._mock_success_response(),
        ]
        p._http_client = mock_client

        sleep_calls = []
        with patch("temper_ai.llm.providers.base.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            with patch("temper_ai.llm.providers.base.random.random", return_value=0.5):
                p.complete([{"role": "user", "content": "Hi"}])

        # 3 retries before success on 4th attempt
        assert len(sleep_calls) == 3
        # Delays: 2^0 + 0.5 = 1.5, 2^1 + 0.5 = 2.5, 2^2 + 0.5 = 4.5
        assert sleep_calls[0] == 1.5
        assert sleep_calls[1] == 2.5
        assert sleep_calls[2] == 4.5


# -- OpenAI: streaming --


class TestOpenAIStreaming:
    def test_consume_stream_text(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")

        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"Hel"},"index":0}],"model":"gpt-4"}',
            'data: {"choices":[{"delta":{"content":"lo"},"index":0}],"model":"gpt-4"}',
            'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"model":"gpt-4","usage":{"prompt_tokens":10,"completion_tokens":2}}',
            "data: [DONE]",
        ]

        chunks = []
        result = p._consume_stream(mock_response, on_chunk=lambda c: chunks.append(c))

        assert result.content == "Hello"
        assert result.finish_reason == "stop"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 2
        assert result.tool_calls is None

        # Chunks: "Hel", "lo", done
        assert len(chunks) == 3
        assert chunks[0].content == "Hel"
        assert chunks[0].done is False
        assert chunks[2].done is True

    def test_consume_stream_tool_calls(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")

        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"bash","arguments":""}}]},"index":0}],"model":"gpt-4"}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"command\\""}}]},"index":0}],"model":"gpt-4"}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":": \\"ls\\"}"}}]},"index":0}],"model":"gpt-4"}',
            'data: {"choices":[{"delta":{},"index":0,"finish_reason":"tool_calls"}],"model":"gpt-4","usage":{"prompt_tokens":15,"completion_tokens":10}}',
            "data: [DONE]",
        ]

        result = p._consume_stream(mock_response, on_chunk=None)

        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["id"] == "call_1"
        assert result.tool_calls[0]["name"] == "bash"
        assert json.loads(result.tool_calls[0]["arguments"]) == {"command": "ls"}

    def test_consume_stream_no_callback(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")

        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"Hi"},"index":0}],"model":"gpt-4"}',
            'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"model":"gpt-4"}',
            "data: [DONE]",
        ]

        result = p._consume_stream(mock_response, on_chunk=None)
        assert result.content == "Hi"

    def test_malformed_sse_lines_skipped(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")

        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [
            "",  # empty line
            "not a data line",
            "data: {invalid json",
            'data: {"choices":[{"delta":{"content":"OK"},"index":0}],"model":"gpt-4"}',
            'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"model":"gpt-4"}',
            "data: [DONE]",
        ]

        result = p._consume_stream(mock_response, on_chunk=None)
        assert result.content == "OK"


# -- vLLM --


class TestVllmProvider:
    def test_adds_chat_template_kwargs(self):
        p = VllmLLM(model="qwen3-next", base_url="http://localhost:8000")
        req = p._build_request([{"role": "user", "content": "Hi"}])
        assert req["chat_template_kwargs"] == {"enable_thinking": True}

    def test_adds_stream_options(self):
        p = VllmLLM(model="qwen3-next", base_url="http://localhost:8000")
        req = p._build_request([{"role": "user", "content": "Hi"}], stream=True)
        assert req["stream_options"] == {"include_usage": True}

    def test_no_stream_options_without_stream(self):
        p = VllmLLM(model="qwen3-next", base_url="http://localhost:8000")
        req = p._build_request([{"role": "user", "content": "Hi"}])
        assert "stream_options" not in req

    def test_preserves_existing_chat_template_kwargs(self):
        p = VllmLLM(
            model="qwen3-next", base_url="http://localhost:8000",
            chat_template_kwargs={"custom": True},
        )
        req = p._build_request([{"role": "user", "content": "Hi"}])
        # Constructor value should be preserved via extra_kwargs -> setdefault
        assert req["chat_template_kwargs"] == {"custom": True}

    def test_per_call_override_thinking(self):
        """Per-call kwargs override the constructor default."""
        p = VllmLLM(model="qwen3-next", base_url="http://localhost:8000")

        # Default: thinking enabled
        req1 = p._build_request([{"role": "user", "content": "Hi"}])
        assert req1["chat_template_kwargs"] == {"enable_thinking": True}

        # Per-call: disable thinking
        req2 = p._build_request(
            [{"role": "user", "content": "Hi"}],
            chat_template_kwargs={"enable_thinking": False},
        )
        assert req2["chat_template_kwargs"] == {"enable_thinking": False}

    def test_provider_name(self):
        p = VllmLLM(model="qwen3-next", base_url="http://localhost:8000")
        assert p.provider_name == "vllm"


# -- Factory --


class TestProviderFactory:
    def test_create_openai(self):
        p = create_provider("openai", model="gpt-4", api_key="test")
        assert isinstance(p, OpenAILLM)
        assert p.model == "gpt-4"
        p.close()

    def test_create_vllm(self):
        p = create_provider("vllm", model="qwen3-next")
        assert isinstance(p, VllmLLM)
        assert p.base_url == "http://localhost:8000"
        p.close()

    def test_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("unknown", model="x")

    def test_api_key_from_env(self):
        with patch.dict(os.environ, {"MY_API_KEY": "secret-123"}):
            p = create_provider("openai", model="gpt-4", api_key_env="MY_API_KEY")
            assert p.api_key == "secret-123"
            p.close()

    def test_explicit_api_key_over_env(self):
        with patch.dict(os.environ, {"MY_API_KEY": "from-env"}):
            p = create_provider(
                "openai", model="gpt-4",
                api_key="explicit", api_key_env="MY_API_KEY",
            )
            assert p.api_key == "explicit"
            p.close()

    def test_custom_base_url(self):
        p = create_provider("openai", model="gpt-4", base_url="http://custom:8080")
        assert p.base_url == "http://custom:8080"
        p.close()

    def test_default_base_url_openai(self):
        p = create_provider("openai", model="gpt-4")
        assert p.base_url == "https://api.openai.com"
        p.close()


# -- Context manager --


class TestProviderContextManager:
    def test_close(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")
        p._http_client = MagicMock()
        p.close()
        assert p._http_client is None

    def test_context_manager(self):
        with OpenAILLM(model="gpt-4", base_url="http://test") as p:
            assert isinstance(p, OpenAILLM)
        # _client should be None after exit (was never created)
        assert p._http_client is None

    def test_headers(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test", api_key="sk-test")
        headers = p._get_headers()
        assert headers["Authorization"] == "Bearer sk-test"
        assert headers["Content-Type"] == "application/json"

    def test_headers_no_api_key(self):
        p = OpenAILLM(model="gpt-4", base_url="http://test")
        headers = p._get_headers()
        assert "Authorization" not in headers
