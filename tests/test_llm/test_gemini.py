"""Tests for the Gemini provider — message conversion, response parsing, streaming."""

import pytest
from unittest.mock import MagicMock, patch

from temper_ai.llm.models import LLMResponse, LLMStreamChunk


# ---------------------------------------------------------------------------
# Import guard — skip if google-genai is not installed
# ---------------------------------------------------------------------------

genai_available = True
try:
    from google import genai as _genai  # noqa: F401
except ImportError:
    genai_available = False

pytestmark = pytest.mark.skipif(
    not genai_available,
    reason="google-genai SDK not installed",
)


# ---------------------------------------------------------------------------
# Helpers for mocking Gemini SDK objects
# ---------------------------------------------------------------------------

def _make_text_part(text: str):
    part = MagicMock()
    part.text = text
    part.function_call = None
    return part


def _make_function_call_part(name: str, args: dict):
    fc = MagicMock()
    fc.name = name
    fc.args = args
    part = MagicMock()
    part.text = None
    part.function_call = fc
    return part


def _make_candidate(parts):
    content = MagicMock()
    content.parts = parts
    candidate = MagicMock()
    candidate.content = content
    return candidate


def _make_usage_metadata(prompt_tokens: int = 10, candidate_tokens: int = 5):
    um = MagicMock()
    um.prompt_token_count = prompt_tokens
    um.candidates_token_count = candidate_tokens
    return um


def _make_sdk_response(parts=None, prompt_tokens: int = 10, candidate_tokens: int = 5):
    resp = MagicMock()
    resp.candidates = [_make_candidate(parts or [_make_text_part("Hello")])]
    resp.usage_metadata = _make_usage_metadata(prompt_tokens, candidate_tokens)
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    """GeminiLLM with the SDK client replaced by a MagicMock."""
    from temper_ai.llm.providers.gemini import GeminiLLM

    with patch("temper_ai.llm.providers.gemini._ensure_genai") as mock_ensure:
        mock_genai = MagicMock()
        mock_ensure.return_value = mock_genai
        p = GeminiLLM(model="gemini-2.5-flash", api_key="test-key")
    p._client = MagicMock()
    return p


# ---------------------------------------------------------------------------
# _convert_messages
# ---------------------------------------------------------------------------

class TestConvertMessages:
    def test_system_message_extracted(self):
        from temper_ai.llm.providers.gemini import _convert_messages

        messages = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello"},
        ]
        system, contents = _convert_messages(messages)
        assert system == "Be helpful."
        assert len(contents) == 1

    def test_no_system_message(self):
        from temper_ai.llm.providers.gemini import _convert_messages

        messages = [{"role": "user", "content": "Hi"}]
        system, contents = _convert_messages(messages)
        assert system == ""
        assert len(contents) == 1

    def test_user_message_role(self):
        from temper_ai.llm.providers.gemini import _convert_messages

        messages = [{"role": "user", "content": "Hello"}]
        _, contents = _convert_messages(messages)
        assert contents[0].role == "user"

    def test_assistant_message_role_becomes_model(self):
        from temper_ai.llm.providers.gemini import _convert_messages

        messages = [{"role": "assistant", "content": "Sure."}]
        _, contents = _convert_messages(messages)
        assert contents[0].role == "model"

    def test_tool_result_becomes_user_function_response(self):
        from temper_ai.llm.providers.gemini import _convert_messages

        messages = [{
            "role": "tool",
            "name": "bash",
            "content": "file.txt",
        }]
        _, contents = _convert_messages(messages)
        assert contents[0].role == "user"

    def test_unknown_role_skipped(self):
        from temper_ai.llm.providers.gemini import _convert_messages

        messages = [{"role": "unknown_role", "content": "something"}]
        _, contents = _convert_messages(messages)
        assert len(contents) == 0

    def test_empty_messages(self):
        from temper_ai.llm.providers.gemini import _convert_messages

        system, contents = _convert_messages([])
        assert system == ""
        assert contents == []


# ---------------------------------------------------------------------------
# _convert_tool_call_part
# ---------------------------------------------------------------------------

class TestConvertToolCallPart:
    def test_string_arguments_parsed_to_dict(self):
        from temper_ai.llm.providers.gemini import _convert_tool_call_part

        with patch("temper_ai.llm.providers.gemini._ensure_genai"):
            from google.genai import types

        tc = {"function": {"name": "bash", "arguments": '{"cmd": "ls"}'}}
        part = _convert_tool_call_part(tc, types)
        # Should not raise; part is a types.Part
        assert part is not None

    def test_dict_arguments_passed_through(self):
        from temper_ai.llm.providers.gemini import _convert_tool_call_part

        from google.genai import types

        tc = {"function": {"name": "bash", "arguments": {"cmd": "ls"}}}
        part = _convert_tool_call_part(tc, types)
        assert part is not None

    def test_invalid_json_arguments_fallback(self):
        from temper_ai.llm.providers.gemini import _convert_tool_call_part

        from google.genai import types

        tc = {"function": {"name": "bash", "arguments": "not-json"}}
        part = _convert_tool_call_part(tc, types)
        assert part is not None  # fallback to {"raw": ...}


# ---------------------------------------------------------------------------
# _convert_tools
# ---------------------------------------------------------------------------

class TestConvertTools:
    def test_openai_tools_converted_to_tool_object(self):
        from temper_ai.llm.providers.gemini import _convert_tools
        from google.genai import types

        tools = [{
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Run shell commands",
                "parameters": {"type": "object", "properties": {}},
            },
        }]
        result = _convert_tools(tools)
        assert isinstance(result, types.Tool)
        assert len(result.function_declarations) == 1
        assert result.function_declarations[0].name == "bash"

    def test_multiple_tools(self):
        from temper_ai.llm.providers.gemini import _convert_tools
        from google.genai import types

        tools = [
            {"type": "function", "function": {"name": "bash", "description": "a", "parameters": {}}},
            {"type": "function", "function": {"name": "read", "description": "b", "parameters": {}}},
        ]
        result = _convert_tools(tools)
        assert len(result.function_declarations) == 2


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_text_response(self):
        from temper_ai.llm.providers.gemini import _parse_response

        resp = _make_sdk_response(
            parts=[_make_text_part("Hello world")],
            prompt_tokens=10,
            candidate_tokens=5,
        )
        result = _parse_response(resp, "gemini-2.5-flash")
        assert result.content == "Hello world"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 5
        assert result.total_tokens == 15
        assert result.finish_reason == "stop"
        assert result.tool_calls is None
        assert result.provider == "gemini"
        assert result.model == "gemini-2.5-flash"

    def test_function_call_response(self):
        from temper_ai.llm.providers.gemini import _parse_response

        resp = _make_sdk_response(
            parts=[_make_function_call_part("bash", {"command": "ls"})],
        )
        result = _parse_response(resp, "gemini-2.5-flash")
        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc["function"]["name"] == "bash"
        assert tc["function"]["arguments"] == {"command": "ls"}
        assert tc["id"] == "call_bash"

    def test_mixed_text_and_function_call(self):
        from temper_ai.llm.providers.gemini import _parse_response

        resp = _make_sdk_response(
            parts=[
                _make_text_part("Running command."),
                _make_function_call_part("bash", {"cmd": "pwd"}),
            ],
        )
        result = _parse_response(resp, "gemini-2.5-flash")
        assert result.content == "Running command."
        assert len(result.tool_calls) == 1
        assert result.finish_reason == "tool_calls"

    def test_empty_candidates(self):
        from temper_ai.llm.providers.gemini import _parse_response

        resp = MagicMock()
        resp.candidates = []
        resp.usage_metadata = _make_usage_metadata(0, 0)
        result = _parse_response(resp, "gemini-2.5-flash")
        assert result.content == ""
        assert result.tool_calls is None

    def test_no_usage_metadata(self):
        from temper_ai.llm.providers.gemini import _parse_response

        resp = _make_sdk_response()
        resp.usage_metadata = None
        result = _parse_response(resp, "gemini-2.5-flash")
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0

    def test_multiple_text_parts_concatenated(self):
        from temper_ai.llm.providers.gemini import _parse_response

        resp = _make_sdk_response(
            parts=[_make_text_part("Part A. "), _make_text_part("Part B.")]
        )
        result = _parse_response(resp, "gemini-2.5-flash")
        assert result.content == "Part A. Part B."

    def test_none_function_call_args_handled(self):
        from temper_ai.llm.providers.gemini import _parse_response

        fc_part = _make_function_call_part("tool", None)
        fc_part.function_call.args = None
        resp = _make_sdk_response(parts=[fc_part])
        result = _parse_response(resp, "gemini-2.5-flash")
        assert result.tool_calls[0]["function"]["arguments"] == {}


# ---------------------------------------------------------------------------
# GeminiLLM.complete() — integration via mocked SDK client
# ---------------------------------------------------------------------------

class TestGeminiComplete:
    def test_complete_basic(self, provider):
        sdk_resp = _make_sdk_response(
            parts=[_make_text_part("Hi there!")],
            prompt_tokens=10,
            candidate_tokens=5,
        )
        provider._client.models.generate_content.return_value = sdk_resp

        with patch("temper_ai.llm.providers.gemini._convert_messages") as mock_convert:
            from google.genai import types
            mock_convert.return_value = ("", [MagicMock()])
            result = provider.complete([{"role": "user", "content": "Hello"}])

        assert result.content == "Hi there!"
        assert result.provider == "gemini"
        provider._client.models.generate_content.assert_called_once()

    def test_complete_passes_model(self, provider):
        sdk_resp = _make_sdk_response()
        provider._client.models.generate_content.return_value = sdk_resp

        with patch("temper_ai.llm.providers.gemini._convert_messages") as mock_convert:
            mock_convert.return_value = ("", [MagicMock()])
            provider.complete([{"role": "user", "content": "Hi"}])

        call_kwargs = provider._client.models.generate_content.call_args
        assert call_kwargs.kwargs["model"] == provider.model

    def test_complete_sdk_exception_propagates(self, provider):
        provider._client.models.generate_content.side_effect = RuntimeError("quota exceeded")

        with patch("temper_ai.llm.providers.gemini._convert_messages") as mock_convert:
            mock_convert.return_value = ("", [MagicMock()])
            with pytest.raises(RuntimeError, match="quota exceeded"):
                provider.complete([{"role": "user", "content": "Hi"}])


# ---------------------------------------------------------------------------
# GeminiLLM.stream() — integration via mocked SDK client
# ---------------------------------------------------------------------------

class TestGeminiStream:
    def _make_stream_chunk(self, text: str):
        chunk = MagicMock()
        chunk.text = text
        return chunk

    def test_stream_basic(self, provider):
        chunks_from_sdk = [
            self._make_stream_chunk("Hello "),
            self._make_stream_chunk("world"),
        ]
        provider._client.models.generate_content_stream.return_value = iter(chunks_from_sdk)

        with patch("temper_ai.llm.providers.gemini._convert_messages") as mock_convert:
            mock_convert.return_value = ("", [MagicMock()])
            received_chunks = []
            result = provider.stream(
                [{"role": "user", "content": "Hi"}],
                on_chunk=lambda c: received_chunks.append(c),
            )

        assert result.content == "Hello world"
        # text chunks + done chunk
        assert len(received_chunks) == 3
        assert received_chunks[-1].done is True

    def test_stream_no_callback(self, provider):
        chunks_from_sdk = [self._make_stream_chunk("Silent")]
        provider._client.models.generate_content_stream.return_value = iter(chunks_from_sdk)

        with patch("temper_ai.llm.providers.gemini._convert_messages") as mock_convert:
            mock_convert.return_value = ("", [MagicMock()])
            result = provider.stream([{"role": "user", "content": "Hi"}], on_chunk=None)

        assert result.content == "Silent"

    def test_stream_empty_chunks_skipped(self, provider):
        chunks_from_sdk = [
            self._make_stream_chunk(""),
            self._make_stream_chunk("Real content"),
            self._make_stream_chunk(""),
        ]
        provider._client.models.generate_content_stream.return_value = iter(chunks_from_sdk)

        with patch("temper_ai.llm.providers.gemini._convert_messages") as mock_convert:
            mock_convert.return_value = ("", [MagicMock()])
            received_chunks = []
            result = provider.stream(
                [{"role": "user", "content": "Hi"}],
                on_chunk=lambda c: received_chunks.append(c),
            )

        assert result.content == "Real content"
        # Only 1 non-empty content chunk + done chunk
        content_chunks = [c for c in received_chunks if not c.done]
        assert len(content_chunks) == 1


# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------

class TestGeminiProviderMetadata:
    def test_provider_name(self, provider):
        assert provider.provider_name == "gemini"

    def test_stub_methods_return_empty(self, provider):
        assert provider._get_headers() == {}
        assert provider._get_endpoint() == ""
        assert provider._build_request([]) == {}

    def test_stub_parse_response_returns_llmresponse(self, provider):
        result = provider._parse_response({})
        assert isinstance(result, LLMResponse)

    def test_context_manager(self):
        from temper_ai.llm.providers.gemini import GeminiLLM

        with patch("temper_ai.llm.providers.gemini._ensure_genai") as mock_ensure:
            mock_genai = MagicMock()
            mock_ensure.return_value = mock_genai
            with GeminiLLM(model="gemini-2.5-flash", api_key="k") as p:
                assert isinstance(p, GeminiLLM)


# ---------------------------------------------------------------------------
# Import guard — missing google-genai SDK
# ---------------------------------------------------------------------------

class TestGeminiImportGuard:
    def test_import_error_raised_when_sdk_missing(self):
        import sys

        with patch.dict(sys.modules, {"google": None, "google.genai": None}):
            from temper_ai.llm.providers.gemini import _ensure_genai
            with pytest.raises(ImportError, match="google-genai is required"):
                _ensure_genai()
