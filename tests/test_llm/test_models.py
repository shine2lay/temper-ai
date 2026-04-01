"""Tests for LLM data models."""

from temper_ai.llm.models import CallContext, LLMResponse, LLMRunResult, LLMStreamChunk


class TestLLMResponse:
    def test_basic_response(self):
        resp = LLMResponse(content="Hello", model="gpt-4", provider="OpenAILLM")
        assert resp.content == "Hello"
        assert resp.model == "gpt-4"
        assert resp.provider == "OpenAILLM"

    def test_defaults(self):
        resp = LLMResponse(content=None, model="gpt-4", provider="OpenAILLM")
        assert resp.content is None
        assert resp.prompt_tokens is None
        assert resp.completion_tokens is None
        assert resp.total_tokens is None
        assert resp.latency_ms is None
        assert resp.finish_reason is None
        assert resp.tool_calls is None
        assert resp.raw_response is None

    def test_with_tool_calls(self):
        tool_calls = [{"id": "1", "name": "bash", "arguments": '{"cmd": "ls"}'}]
        resp = LLMResponse(
            content=None, model="gpt-4", provider="OpenAILLM",
            tool_calls=tool_calls, finish_reason="tool_calls",
        )
        assert resp.tool_calls == tool_calls
        assert resp.finish_reason == "tool_calls"


class TestLLMStreamChunk:
    def test_content_chunk(self):
        chunk = LLMStreamChunk(content="Hello", done=False)
        assert chunk.content == "Hello"
        assert chunk.done is False
        assert chunk.chunk_type == "content"

    def test_done_chunk(self):
        chunk = LLMStreamChunk(content="", done=True, finish_reason="stop")
        assert chunk.done is True
        assert chunk.finish_reason == "stop"

    def test_thinking_chunk(self):
        chunk = LLMStreamChunk(content="reasoning...", done=False, chunk_type="thinking")
        assert chunk.chunk_type == "thinking"


class TestLLMRunResult:
    def test_defaults(self):
        result = LLMRunResult(output="Done")
        assert result.output == "Done"
        assert result.tool_calls == []
        assert result.tokens == 0
        assert result.cost == 0.0
        assert result.iterations == 0
        assert result.error is None

    def test_with_error(self):
        result = LLMRunResult(
            output="", iterations=10,
            error="Reached max iterations (10)",
        )
        assert result.error is not None
        assert result.iterations == 10


class TestCallContext:
    def test_defaults(self):
        ctx = CallContext()
        assert ctx.execution_id is None
        assert ctx.agent_event_id is None
        assert ctx.agent_name is None
        assert ctx.node_path is None

    def test_with_values(self):
        ctx = CallContext(
            execution_id="exec-1",
            agent_event_id="agent-1",
            agent_name="researcher",
            node_path="analyze",
        )
        assert ctx.execution_id == "exec-1"
        assert ctx.agent_name == "researcher"
