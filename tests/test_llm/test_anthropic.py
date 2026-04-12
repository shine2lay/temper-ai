"""Tests for the Anthropic provider — message conversion, response parsing, streaming."""

import pytest
from unittest.mock import MagicMock, patch, call

from temper_ai.llm.models import LLMResponse, LLMStreamChunk


# ---------------------------------------------------------------------------
# Helpers to build mock Anthropic SDK objects without importing the real SDK
# ---------------------------------------------------------------------------

def _make_block(block_type: str, **attrs):
    """Build a mock content block mimicking an Anthropic SDK content block."""
    block = MagicMock()
    block.type = block_type
    for k, v in attrs.items():
        setattr(block, k, v)
    return block


def _make_usage(input_tokens: int = 10, output_tokens: int = 5):
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    return usage


def _make_sdk_response(
    content_blocks=None,
    input_tokens: int = 10,
    output_tokens: int = 5,
    stop_reason: str = "end_turn",
):
    resp = MagicMock()
    resp.content = content_blocks or [_make_block("text", text="Hello")]
    resp.usage = _make_usage(input_tokens, output_tokens)
    resp.stop_reason = stop_reason
    return resp


# ---------------------------------------------------------------------------
# Import guard — skip all tests if anthropic is not installed
# ---------------------------------------------------------------------------

anthropic_available = True
try:
    import anthropic as _anthropic_sdk  # noqa: F401
except ImportError:
    anthropic_available = False

pytestmark = pytest.mark.skipif(
    not anthropic_available,
    reason="anthropic SDK not installed",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    """AnthropicLLM with the SDK client replaced by a MagicMock."""
    from temper_ai.llm.providers.anthropic import AnthropicLLM

    with patch("temper_ai.llm.providers.anthropic._ensure_anthropic") as mock_ensure:
        mock_sdk = MagicMock()
        mock_ensure.return_value = mock_sdk
        p = AnthropicLLM(model="claude-sonnet-4-20250514", api_key="test-key")
    p._client = MagicMock()
    return p


# ---------------------------------------------------------------------------
# _extract_system
# ---------------------------------------------------------------------------

class TestExtractSystem:
    def test_system_message_separated(self):
        from temper_ai.llm.providers.anthropic import _extract_system

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, claude_msgs = _extract_system(messages)
        assert system == "You are helpful."
        assert len(claude_msgs) == 1
        assert claude_msgs[0]["role"] == "user"
        assert claude_msgs[0]["content"] == "Hi"

    def test_no_system_message(self):
        from temper_ai.llm.providers.anthropic import _extract_system

        messages = [{"role": "user", "content": "Hello"}]
        system, claude_msgs = _extract_system(messages)
        assert system == ""
        assert len(claude_msgs) == 1

    def test_assistant_message_without_tool_calls(self):
        from temper_ai.llm.providers.anthropic import _extract_system

        messages = [{"role": "assistant", "content": "Sure thing."}]
        _, claude_msgs = _extract_system(messages)
        assert claude_msgs[0] == {"role": "assistant", "content": "Sure thing."}

    def test_assistant_with_tool_calls_converted(self):
        from temper_ai.llm.providers.anthropic import _extract_system

        messages = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "tc_1",
                "function": {"name": "bash", "arguments": '{"command": "ls"}'},
            }],
        }]
        _, claude_msgs = _extract_system(messages)
        assert len(claude_msgs) == 1
        blocks = claude_msgs[0]["content"]
        tool_use_block = next(b for b in blocks if b["type"] == "tool_use")
        assert tool_use_block["id"] == "tc_1"
        assert tool_use_block["name"] == "bash"
        assert tool_use_block["input"] == {"command": "ls"}

    def test_assistant_tool_call_with_string_args_parsed(self):
        from temper_ai.llm.providers.anthropic import _extract_system

        messages = [{
            "role": "assistant",
            "content": "Thinking...",
            "tool_calls": [{
                "id": "tc_2",
                "function": {"name": "read_file", "arguments": '{"path": "/tmp/f.txt"}'},
            }],
        }]
        _, claude_msgs = _extract_system(messages)
        blocks = claude_msgs[0]["content"]
        text_block = next(b for b in blocks if b["type"] == "text")
        assert text_block["text"] == "Thinking..."
        tool_block = next(b for b in blocks if b["type"] == "tool_use")
        assert tool_block["input"] == {"path": "/tmp/f.txt"}

    def test_assistant_tool_call_with_invalid_json_args(self):
        from temper_ai.llm.providers.anthropic import _extract_system

        messages = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "tc_3",
                "function": {"name": "tool", "arguments": "not-json"},
            }],
        }]
        _, claude_msgs = _extract_system(messages)
        blocks = claude_msgs[0]["content"]
        tool_block = next(b for b in blocks if b["type"] == "tool_use")
        assert tool_block["input"] == {}

    def test_tool_result_message_converted(self):
        from temper_ai.llm.providers.anthropic import _extract_system

        messages = [{
            "role": "tool",
            "tool_call_id": "tc_1",
            "content": "file contents here",
        }]
        _, claude_msgs = _extract_system(messages)
        assert claude_msgs[0]["role"] == "user"
        result_block = claude_msgs[0]["content"][0]
        assert result_block["type"] == "tool_result"
        assert result_block["tool_use_id"] == "tc_1"
        assert result_block["content"] == "file contents here"

    def test_empty_messages(self):
        from temper_ai.llm.providers.anthropic import _extract_system

        system, msgs = _extract_system([])
        assert system == ""
        assert msgs == []


# ---------------------------------------------------------------------------
# _convert_tools
# ---------------------------------------------------------------------------

class TestConvertTools:
    def test_openai_format_converted(self):
        from temper_ai.llm.providers.anthropic import _convert_tools

        tools = [{
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Run a shell command",
                "parameters": {"type": "object", "properties": {}},
            },
        }]
        result = _convert_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "bash"
        assert result[0]["description"] == "Run a shell command"
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}

    def test_server_tools_passed_through(self):
        from temper_ai.llm.providers.anthropic import _convert_tools

        tools = [{"type": "web_search_20250305"}]
        result = _convert_tools(tools)
        assert result == [{"type": "web_search_20250305"}]

    def test_code_execution_server_tool_passed_through(self):
        from temper_ai.llm.providers.anthropic import _convert_tools

        tools = [{"type": "code_execution_20250522"}]
        result = _convert_tools(tools)
        assert result == [{"type": "code_execution_20250522"}]

    def test_mixed_tools(self):
        from temper_ai.llm.providers.anthropic import _convert_tools

        tools = [
            {"type": "web_search_20250305"},
            {"type": "function", "function": {"name": "bash", "description": "", "parameters": {}}},
        ]
        result = _convert_tools(tools)
        assert result[0] == {"type": "web_search_20250305"}
        assert result[1]["name"] == "bash"


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_text_response(self):
        from temper_ai.llm.providers.anthropic import _parse_response

        resp = _make_sdk_response(
            content_blocks=[_make_block("text", text="Hello there")],
            input_tokens=20,
            output_tokens=10,
            stop_reason="end_turn",
        )
        result = _parse_response(resp, "claude-3-5-sonnet")
        assert result.content == "Hello there"
        assert result.prompt_tokens == 20
        assert result.completion_tokens == 10
        assert result.total_tokens == 30
        assert result.finish_reason == "stop"
        assert result.tool_calls is None
        assert result.provider == "anthropic"
        assert result.model == "claude-3-5-sonnet"

    def test_tool_use_response(self):
        from temper_ai.llm.providers.anthropic import _parse_response

        tool_block = _make_block("tool_use", id="tu_1", name="bash", input={"command": "ls"})
        resp = _make_sdk_response(
            content_blocks=[tool_block],
            input_tokens=15,
            output_tokens=8,
            stop_reason="tool_use",
        )
        result = _parse_response(resp, "claude-3-5-sonnet")
        assert result.content == ""
        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["id"] == "tu_1"
        assert result.tool_calls[0]["name"] == "bash"
        assert result.tool_calls[0]["arguments"] == {"command": "ls"}

    def test_mixed_text_and_tool_use(self):
        from temper_ai.llm.providers.anthropic import _parse_response

        blocks = [
            _make_block("text", text="Let me run that."),
            _make_block("tool_use", id="tu_2", name="bash", input={"command": "pwd"}),
        ]
        resp = _make_sdk_response(content_blocks=blocks, stop_reason="tool_use")
        result = _parse_response(resp, "claude-3-5-sonnet")
        assert result.content == "Let me run that."
        assert len(result.tool_calls) == 1
        assert result.finish_reason == "tool_calls"

    def test_server_tool_blocks_are_skipped(self):
        from temper_ai.llm.providers.anthropic import _parse_response

        blocks = [
            _make_block("server_tool_use", text="ignored"),
            _make_block("web_search_tool_result", text="ignored"),
            _make_block("text", text="Answer after search."),
        ]
        resp = _make_sdk_response(content_blocks=blocks, stop_reason="end_turn")
        result = _parse_response(resp, "claude-3-5-sonnet")
        assert result.content == "Answer after search."
        assert result.tool_calls is None

    def test_multiple_text_blocks_concatenated(self):
        from temper_ai.llm.providers.anthropic import _parse_response

        blocks = [
            _make_block("text", text="Part 1. "),
            _make_block("text", text="Part 2."),
        ]
        resp = _make_sdk_response(content_blocks=blocks)
        result = _parse_response(resp, "claude-3-5-sonnet")
        assert result.content == "Part 1. Part 2."

    def test_empty_content_blocks(self):
        from temper_ai.llm.providers.anthropic import _parse_response

        resp = _make_sdk_response(content_blocks=[])
        result = _parse_response(resp, "claude-3-5-sonnet")
        assert result.content == ""
        assert result.tool_calls is None


# ---------------------------------------------------------------------------
# AnthropicLLM.complete() — integration via mocked SDK client
# ---------------------------------------------------------------------------

class TestAnthropicComplete:
    def test_complete_basic(self, provider):
        sdk_resp = _make_sdk_response(
            content_blocks=[_make_block("text", text="Hi there!")],
            input_tokens=10,
            output_tokens=5,
        )
        provider._client.messages.create.return_value = sdk_resp

        result = provider.complete([{"role": "user", "content": "Hello"}])

        assert result.content == "Hi there!"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 5
        provider._client.messages.create.assert_called_once()

    def test_complete_with_system_message(self, provider):
        sdk_resp = _make_sdk_response()
        provider._client.messages.create.return_value = sdk_resp

        provider.complete([
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Tell me something."},
        ])

        kwargs = provider._client.messages.create.call_args.kwargs
        assert kwargs["system"] == "Be concise."
        # System message must not appear in messages list
        assert all(m.get("role") != "system" for m in kwargs["messages"])

    def test_complete_without_system_no_system_kwarg(self, provider):
        sdk_resp = _make_sdk_response()
        provider._client.messages.create.return_value = sdk_resp

        provider.complete([{"role": "user", "content": "Hi"}])

        kwargs = provider._client.messages.create.call_args.kwargs
        assert "system" not in kwargs

    def test_complete_with_tools(self, provider):
        sdk_resp = _make_sdk_response()
        provider._client.messages.create.return_value = sdk_resp

        tools = [{"type": "function", "function": {"name": "bash", "description": "run", "parameters": {}}}]
        provider.complete([{"role": "user", "content": "Run ls"}], tools=tools)

        kwargs = provider._client.messages.create.call_args.kwargs
        assert "tools" in kwargs
        assert kwargs["tools"][0]["name"] == "bash"

    def test_complete_temperature_and_max_tokens(self, provider):
        sdk_resp = _make_sdk_response()
        provider._client.messages.create.return_value = sdk_resp

        provider.complete([{"role": "user", "content": "Hi"}])

        kwargs = provider._client.messages.create.call_args.kwargs
        assert kwargs["temperature"] == provider.temperature
        assert kwargs["max_tokens"] == provider.max_tokens

    def test_complete_model_passed(self, provider):
        sdk_resp = _make_sdk_response()
        provider._client.messages.create.return_value = sdk_resp

        provider.complete([{"role": "user", "content": "Hi"}])

        kwargs = provider._client.messages.create.call_args.kwargs
        assert kwargs["model"] == provider.model

    def test_complete_sdk_exception_propagates(self, provider):
        provider._client.messages.create.side_effect = RuntimeError("API error")

        with pytest.raises(RuntimeError, match="API error"):
            provider.complete([{"role": "user", "content": "Hi"}])


# ---------------------------------------------------------------------------
# AnthropicLLM.stream() — integration via mocked SDK client
# ---------------------------------------------------------------------------

class TestAnthropicStream:
    def test_stream_basic_text(self, provider):
        sdk_resp = _make_sdk_response(
            content_blocks=[_make_block("text", text="Streamed result")],
            input_tokens=12,
            output_tokens=6,
        )

        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
        stream_ctx.__exit__ = MagicMock(return_value=False)
        stream_ctx.text_stream = iter(["Streamed ", "result"])
        stream_ctx.get_final_message.return_value = sdk_resp
        provider._client.messages.stream.return_value = stream_ctx

        chunks = []
        result = provider.stream(
            [{"role": "user", "content": "Go"}],
            on_chunk=lambda c: chunks.append(c),
        )

        assert result.content == "Streamed result"
        assert len(chunks) == 3  # "Streamed ", "result", done
        assert chunks[-1].done is True
        assert chunks[-1].content == ""

    def test_stream_calls_on_chunk_for_each_text(self, provider):
        sdk_resp = _make_sdk_response()
        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
        stream_ctx.__exit__ = MagicMock(return_value=False)
        stream_ctx.text_stream = iter(["A", "B", "C"])
        stream_ctx.get_final_message.return_value = sdk_resp
        provider._client.messages.stream.return_value = stream_ctx

        chunks = []
        provider.stream([{"role": "user", "content": "X"}], on_chunk=lambda c: chunks.append(c))

        content_chunks = [c for c in chunks if not c.done]
        assert len(content_chunks) == 3
        assert [c.content for c in content_chunks] == ["A", "B", "C"]

    def test_stream_with_no_callback(self, provider):
        sdk_resp = _make_sdk_response(
            content_blocks=[_make_block("text", text="No callback")]
        )
        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
        stream_ctx.__exit__ = MagicMock(return_value=False)
        stream_ctx.text_stream = iter(["No callback"])
        stream_ctx.get_final_message.return_value = sdk_resp
        provider._client.messages.stream.return_value = stream_ctx

        result = provider.stream([{"role": "user", "content": "Quiet"}], on_chunk=None)
        assert result.content == "No callback"

    def test_stream_with_system_message(self, provider):
        sdk_resp = _make_sdk_response()
        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
        stream_ctx.__exit__ = MagicMock(return_value=False)
        stream_ctx.text_stream = iter(["ok"])
        stream_ctx.get_final_message.return_value = sdk_resp
        provider._client.messages.stream.return_value = stream_ctx

        provider.stream([
            {"role": "system", "content": "System prompt."},
            {"role": "user", "content": "Go"},
        ])

        kwargs = provider._client.messages.stream.call_args.kwargs
        assert kwargs["system"] == "System prompt."

    def test_stream_with_tools(self, provider):
        sdk_resp = _make_sdk_response()
        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
        stream_ctx.__exit__ = MagicMock(return_value=False)
        stream_ctx.text_stream = iter([])
        stream_ctx.get_final_message.return_value = sdk_resp
        provider._client.messages.stream.return_value = stream_ctx

        tools = [{"type": "function", "function": {"name": "bash", "description": "", "parameters": {}}}]
        provider.stream([{"role": "user", "content": "Go"}], tools=tools)

        kwargs = provider._client.messages.stream.call_args.kwargs
        assert "tools" in kwargs


# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------

class TestAnthropicProviderMetadata:
    def test_provider_name(self, provider):
        assert provider.provider_name == "anthropic"

    def test_stub_methods_return_empty(self, provider):
        """Stub methods exist to satisfy BaseLLM abstract interface."""
        assert provider._get_headers() == {}
        assert provider._get_endpoint() == ""
        assert provider._build_request([]) == {}

    def test_stub_parse_response_returns_llmresponse(self, provider):
        result = provider._parse_response({})
        assert isinstance(result, LLMResponse)

    def test_close_sets_client_to_none(self, provider):
        provider.close()
        assert provider._http_client is None

    def test_context_manager(self):
        from temper_ai.llm.providers.anthropic import AnthropicLLM

        with patch("temper_ai.llm.providers.anthropic._ensure_anthropic") as mock_ensure:
            mock_sdk = MagicMock()
            mock_ensure.return_value = mock_sdk
            with AnthropicLLM(model="claude-sonnet-4-20250514", api_key="k") as p:
                assert isinstance(p, AnthropicLLM)


# ---------------------------------------------------------------------------
# Import guard — missing anthropic SDK
# ---------------------------------------------------------------------------

class TestAnthropicImportGuard:
    def test_import_error_raised_when_sdk_missing(self):
        import sys
        from unittest.mock import patch

        with patch.dict(sys.modules, {"anthropic": None}):
            from temper_ai.llm.providers.anthropic import _ensure_anthropic
            with pytest.raises(ImportError, match="anthropic is required"):
                _ensure_anthropic()
