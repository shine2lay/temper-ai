"""Tests for the Ollama provider — defaults, request building, response parsing, HTTP."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from temper_ai.llm.providers.ollama import OllamaLLM
from temper_ai.llm.providers.openai import OpenAILLM

# ---------------------------------------------------------------------------
# Construction and defaults
# ---------------------------------------------------------------------------

class TestOllamaDefaults:
    def test_inherits_openai(self):
        p = OllamaLLM()
        assert isinstance(p, OpenAILLM)
        p.close()

    def test_default_model(self):
        p = OllamaLLM()
        assert p.model == "llama3.2"
        p.close()

    def test_default_base_url(self):
        p = OllamaLLM()
        assert p.base_url == "http://localhost:11434"
        p.close()

    def test_custom_model(self):
        p = OllamaLLM(model="mistral")
        assert p.model == "mistral"
        p.close()

    def test_custom_base_url(self):
        p = OllamaLLM(base_url="http://gpu-server:11434")
        assert p.base_url == "http://gpu-server:11434"
        p.close()

    def test_api_key_set_to_ollama(self):
        """Ollama doesn't need a real key; it's hardcoded to 'ollama'."""
        p = OllamaLLM()
        assert p.api_key == "ollama"
        p.close()

    def test_provider_name(self):
        p = OllamaLLM()
        assert p.provider_name == "ollama"
        p.close()

    def test_extra_kwargs_forwarded(self):
        p = OllamaLLM(temperature=0.3, max_tokens=1024)
        assert p.temperature == 0.3
        assert p.max_tokens == 1024
        p.close()


# ---------------------------------------------------------------------------
# Request building (inherits OpenAI)
# ---------------------------------------------------------------------------

class TestOllamaBuildRequest:
    def test_basic_request_structure(self):
        p = OllamaLLM(model="llama3.2")
        req = p._build_request([{"role": "user", "content": "Hi"}])
        assert req["model"] == "llama3.2"
        assert req["messages"] == [{"role": "user", "content": "Hi"}]
        assert req["temperature"] == p.temperature
        assert "stream" not in req
        assert "tools" not in req
        p.close()

    def test_stream_flag_included_when_set(self):
        p = OllamaLLM(model="llama3.2")
        req = p._build_request([{"role": "user", "content": "Hi"}], stream=True)
        assert req["stream"] is True
        p.close()

    def test_tools_included_when_provided(self):
        p = OllamaLLM(model="llama3.2")
        tools = [{"type": "function", "function": {"name": "bash"}}]
        req = p._build_request([{"role": "user", "content": "Hi"}], tools=tools)
        assert req["tools"] == tools
        p.close()

    def test_extra_kwargs_in_request(self):
        p = OllamaLLM(model="llama3.2", num_ctx=8192)
        req = p._build_request([{"role": "user", "content": "Hi"}])
        assert req["num_ctx"] == 8192
        p.close()


# ---------------------------------------------------------------------------
# Endpoint and headers
# ---------------------------------------------------------------------------

class TestOllamaEndpointAndHeaders:
    def test_endpoint(self):
        p = OllamaLLM()
        assert p._get_endpoint() == "/v1/chat/completions"
        p.close()

    def test_headers_content_type(self):
        p = OllamaLLM()
        headers = p._get_headers()
        assert headers["Content-Type"] == "application/json"
        p.close()

    def test_headers_authorization_uses_ollama_key(self):
        """Ollama sets api_key='ollama', so Authorization header is Bearer ollama."""
        p = OllamaLLM()
        headers = p._get_headers()
        assert headers["Authorization"] == "Bearer ollama"
        p.close()


# ---------------------------------------------------------------------------
# Response parsing (inherits OpenAI)
# ---------------------------------------------------------------------------

class TestOllamaParseResponse:
    def test_text_response(self):
        p = OllamaLLM(model="llama3.2")
        raw = {
            "choices": [{"message": {"content": "Hello from Ollama"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            "model": "llama3.2",
        }
        resp = p._parse_response(raw, latency_ms=50)
        assert resp.content == "Hello from Ollama"
        assert resp.prompt_tokens == 8
        assert resp.completion_tokens == 4
        assert resp.total_tokens == 12
        assert resp.latency_ms == 50
        assert resp.finish_reason == "stop"
        assert resp.tool_calls is None
        assert resp.provider == "ollama"
        p.close()

    def test_tool_call_response(self):
        p = OllamaLLM(model="llama3.2")
        raw = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "tc_1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"cmd": "ls"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            "model": "llama3.2",
        }
        resp = p._parse_response(raw, latency_ms=80)
        assert resp.finish_reason == "tool_calls"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["id"] == "tc_1"
        assert resp.tool_calls[0]["name"] == "bash"
        p.close()

    def test_no_usage_field(self):
        p = OllamaLLM(model="llama3.2")
        raw = {
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
            "model": "llama3.2",
        }
        resp = p._parse_response(raw, latency_ms=30)
        assert resp.content == "Hi"
        assert resp.prompt_tokens is None
        p.close()


# ---------------------------------------------------------------------------
# HTTP: complete with mocked httpx client
# ---------------------------------------------------------------------------

class TestOllamaComplete:
    def _mock_http_response(self, content="Hello", total_tokens=15):
        mock = MagicMock()
        mock.json.return_value = {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": total_tokens - 10, "total_tokens": total_tokens},
            "model": "llama3.2",
        }
        mock.raise_for_status = MagicMock()
        return mock

    def _make_http_error(self, status_code: int):
        resp_mock = MagicMock()
        resp_mock.status_code = status_code
        error = httpx.HTTPStatusError("error", request=MagicMock(), response=resp_mock)
        resp_mock.raise_for_status.side_effect = error
        return resp_mock

    def test_successful_complete(self):
        p = OllamaLLM(model="llama3.2")
        mock_client = MagicMock()
        mock_client.post.return_value = self._mock_http_response("Hi from Llama")
        p._http_client = mock_client

        result = p.complete([{"role": "user", "content": "Hello"}])
        assert result.content == "Hi from Llama"
        assert result.total_tokens == 15
        mock_client.post.assert_called_once()
        p.close()

    def test_retry_on_500(self):
        p = OllamaLLM(model="llama3.2", max_retries=3)
        error_resp = self._make_http_error(500)
        mock_client = MagicMock()
        mock_client.post.side_effect = [error_resp, self._mock_http_response()]
        p._http_client = mock_client

        with patch("temper_ai.llm.providers.base.time.sleep"):
            result = p.complete([{"role": "user", "content": "Hi"}])

        assert result.content == "Hello"
        assert mock_client.post.call_count == 2
        p.close()

    def test_no_retry_on_401(self):
        p = OllamaLLM(model="llama3.2", max_retries=3)
        error_resp = self._make_http_error(401)
        mock_client = MagicMock()
        mock_client.post.return_value = error_resp
        p._http_client = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            p.complete([{"role": "user", "content": "Hi"}])

        assert mock_client.post.call_count == 1
        p.close()

    def test_retry_on_timeout(self):
        p = OllamaLLM(model="llama3.2", max_retries=2)
        mock_client = MagicMock()
        mock_client.post.side_effect = [
            httpx.ConnectTimeout("timeout"),
            self._mock_http_response(),
        ]
        p._http_client = mock_client

        with patch("temper_ai.llm.providers.base.time.sleep"):
            result = p.complete([{"role": "user", "content": "Hi"}])

        assert result.content == "Hello"
        p.close()

    def test_all_retries_exhausted_raises(self):
        p = OllamaLLM(model="llama3.2", max_retries=2)
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectTimeout("timeout")
        p._http_client = mock_client

        with patch("temper_ai.llm.providers.base.time.sleep"):
            with pytest.raises(httpx.ConnectTimeout):
                p.complete([{"role": "user", "content": "Hi"}])

        assert mock_client.post.call_count == 2
        p.close()


# ---------------------------------------------------------------------------
# HTTP: streaming with mocked httpx client
# ---------------------------------------------------------------------------

class TestOllamaStream:
    def _make_sse_lines(self, content_chunks: list[str], finish_reason: str = "stop"):
        import json
        lines = []
        for chunk in content_chunks:
            data = {"choices": [{"delta": {"content": chunk}, "index": 0}], "model": "llama3.2"}
            lines.append(f"data: {json.dumps(data)}")
        # final chunk with finish_reason
        final = {"choices": [{"delta": {}, "index": 0, "finish_reason": finish_reason}], "model": "llama3.2"}
        lines.append(f"data: {json.dumps(final)}")
        lines.append("data: [DONE]")
        return lines

    def test_stream_text(self):
        p = OllamaLLM(model="llama3.2")
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = self._make_sse_lines(["Hello", " world"])

        chunks = []
        result = p._consume_stream(mock_response, on_chunk=lambda c: chunks.append(c))

        assert result.content == "Hello world"
        assert result.finish_reason == "stop"
        content_chunks = [c for c in chunks if not c.done]
        assert len(content_chunks) == 2
        assert chunks[-1].done is True
        p.close()

    def test_stream_no_callback(self):
        p = OllamaLLM(model="llama3.2")
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = self._make_sse_lines(["Silent"])

        result = p._consume_stream(mock_response, on_chunk=None)
        assert result.content == "Silent"
        p.close()

    def test_stream_malformed_lines_skipped(self):
        import json
        p = OllamaLLM(model="llama3.2")
        mock_response = MagicMock()
        good = json.dumps({"choices": [{"delta": {"content": "OK"}, "index": 0}], "model": "llama3.2"})
        done = json.dumps({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}], "model": "llama3.2"})
        mock_response.iter_lines.return_value = [
            "",
            "not-data-prefix",
            "data: {bad json",
            f"data: {good}",
            f"data: {done}",
            "data: [DONE]",
        ]

        result = p._consume_stream(mock_response, on_chunk=None)
        assert result.content == "OK"
        p.close()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestOllamaContextManager:
    def test_close_sets_http_client_to_none(self):
        p = OllamaLLM()
        p._http_client = MagicMock()
        p.close()
        assert p._http_client is None

    def test_context_manager_usage(self):
        with OllamaLLM() as p:
            assert isinstance(p, OllamaLLM)
        assert p._http_client is None
