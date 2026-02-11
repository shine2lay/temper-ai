"""Tests for LLM streaming support.

Covers:
- OllamaLLM.stream() with mock NDJSON response
- OllamaLLM._build_request num_predict fix
- BaseLLM.stream() default fallback to complete()
- Agent streaming integration
- StreamDisplay thread safety
- Dashboard DataStore stream batch handling
"""
import json
import threading
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from src.agents.llm.base import BaseLLM, LLMResponse, LLMStreamChunk, StreamCallback
from src.agents.llm.ollama import OllamaLLM


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _make_ndjson_lines(*chunks: dict) -> list[str]:
    """Build NDJSON lines for mock streaming responses."""
    return [json.dumps(c) for c in chunks]


def _make_ollama_generate_stream() -> list[str]:
    """Simulate an /api/generate streaming response."""
    return _make_ndjson_lines(
        {"response": "Hello", "done": False},
        {"response": " world", "done": False},
        {"response": "!", "done": True, "prompt_eval_count": 10, "eval_count": 3},
    )


def _make_ollama_chat_stream() -> list[str]:
    """Simulate an /api/chat streaming response."""
    return _make_ndjson_lines(
        {"message": {"content": "Hi"}, "done": False},
        {"message": {"content": " there"}, "done": False},
        {"message": {"content": ""}, "done": True, "prompt_eval_count": 8, "eval_count": 2},
    )


def _make_ollama_thinking_stream() -> list[str]:
    """Simulate /api/generate with thinking tokens."""
    return _make_ndjson_lines(
        {"thinking": "Let me think...", "response": "", "done": False},
        {"thinking": "", "response": "Answer", "done": False},
        {"response": "", "done": True, "prompt_eval_count": 5, "eval_count": 2},
    )


class MockStreamResponse:
    """Mock httpx.Response for streaming."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self.status_code = status_code
        self._lines = lines

    def iter_lines(self):
        yield from self._lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    def read(self):
        pass

    async def aread(self):
        pass

    @property
    def text(self):
        return "error"

    def close(self):
        pass

    async def aclose(self):
        pass


# -----------------------------------------------------------------------
# OllamaLLM._build_request: num_predict fix
# -----------------------------------------------------------------------

class TestOllamaBuildRequest:
    """Verify the /api/generate path uses options.num_predict."""

    def test_generate_path_uses_options_num_predict(self):
        """Generate path should put temperature/top_p/num_predict inside options dict."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        request = llm._build_request("hello")

        # Should NOT have top-level temperature/max_tokens/top_p
        assert "temperature" not in request
        assert "max_tokens" not in request
        assert "top_p" not in request

        # Should have options dict with num_predict
        assert "options" in request
        assert "num_predict" in request["options"]
        assert "temperature" in request["options"]
        assert "top_p" in request["options"]

    def test_generate_path_num_predict_value(self):
        """num_predict should equal max_tokens."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434", max_tokens=4096)
        request = llm._build_request("hello")
        assert request["options"]["num_predict"] == 4096

    def test_generate_path_kwargs_override(self):
        """kwargs max_tokens should override default."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434", max_tokens=2048)
        request = llm._build_request("hello", max_tokens=1024)
        assert request["options"]["num_predict"] == 1024

    def test_chat_path_unchanged(self):
        """Chat path should still use options.num_predict (unchanged)."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]
        request = llm._build_request("hello", tools=tools)
        assert request["options"]["num_predict"] == 2048

    def test_generate_stream_flag(self):
        """stream kwarg should propagate to request."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        request = llm._build_request("hello", stream=True)
        assert request["stream"] is True

    def test_generate_no_stream_by_default(self):
        """Default stream should be False."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        request = llm._build_request("hello")
        assert request["stream"] is False


# -----------------------------------------------------------------------
# BaseLLM.stream() default fallback
# -----------------------------------------------------------------------

class TestBaseLLMStreamDefault:
    """Verify BaseLLM.stream() falls back to complete()."""

    def test_stream_fallback_to_complete(self):
        """stream() should call complete() when not overridden by provider."""
        mock_response = LLMResponse(
            content="test", model="test", provider="test",
            prompt_tokens=5, completion_tokens=3, total_tokens=8,
        )

        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        with patch.object(llm, 'complete', return_value=mock_response) as mock_complete:
            # Call stream with on_chunk=None triggers fallback
            result = BaseLLM.stream(llm, "hello", on_chunk=None)
            mock_complete.assert_called_once()
            assert result.content == "test"

    @pytest.mark.asyncio
    async def test_astream_fallback_to_acomplete(self):
        """astream() should call acomplete() when not overridden."""
        mock_response = LLMResponse(
            content="async test", model="test", provider="test",
        )

        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        with patch.object(llm, 'acomplete', new_callable=AsyncMock, return_value=mock_response):
            result = await BaseLLM.astream(llm, "hello", on_chunk=None)
            assert result.content == "async test"


# -----------------------------------------------------------------------
# OllamaLLM.stream() with mock NDJSON
# -----------------------------------------------------------------------

class TestOllamaStreaming:
    """Test OllamaLLM streaming with mock HTTP responses."""

    def test_stream_generate_path(self):
        """stream() should parse NDJSON and call on_chunk for each token."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        chunks_received = []

        mock_response = MockStreamResponse(_make_ollama_generate_stream())
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response

        with patch.object(llm, '_get_client', return_value=mock_client):
            with patch.object(llm, '_circuit_breaker') as mock_cb:
                mock_cb.call.side_effect = lambda fn: fn()
                result = llm.stream("hello", on_chunk=chunks_received.append)

        assert result.content == "Hello world!"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 3

        # Should have received content chunks + done chunk
        content_chunks = [c for c in chunks_received if not c.done]
        done_chunks = [c for c in chunks_received if c.done]
        assert len(content_chunks) == 3  # "Hello", " world", "!"
        assert len(done_chunks) == 1
        assert done_chunks[0].prompt_tokens == 10

    def test_stream_thinking_tokens(self):
        """stream() should detect thinking vs content tokens."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        chunks_received = []

        mock_response = MockStreamResponse(_make_ollama_thinking_stream())
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response

        with patch.object(llm, '_get_client', return_value=mock_client):
            with patch.object(llm, '_circuit_breaker') as mock_cb:
                mock_cb.call.side_effect = lambda fn: fn()
                result = llm.stream("hello", on_chunk=chunks_received.append)

        # Content should only have non-thinking text
        assert result.content == "Answer"

        # Check chunk types
        thinking_chunks = [c for c in chunks_received if c.chunk_type == "thinking" and not c.done]
        content_chunks = [c for c in chunks_received if c.chunk_type == "content" and not c.done]
        assert len(thinking_chunks) == 1
        assert thinking_chunks[0].content == "Let me think..."
        assert len(content_chunks) == 1
        assert content_chunks[0].content == "Answer"

    def test_stream_no_callback_falls_back(self):
        """stream() with on_chunk=None should call complete()."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        mock_response = LLMResponse(
            content="complete result", model="test", provider="ollama",
        )

        with patch.object(llm, 'complete', return_value=mock_response) as mock:
            result = llm.stream("hello")
            mock.assert_called_once()
            assert result.content == "complete result"

    def test_stream_chat_path(self):
        """stream() should work with /api/chat format."""
        llm = OllamaLLM(model="test", base_url="http://localhost:11434")
        chunks_received = []

        # Force chat API path
        llm._use_chat_api = True
        mock_response = MockStreamResponse(_make_ollama_chat_stream())
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_response

        with patch.object(llm, '_get_client', return_value=mock_client):
            with patch.object(llm, '_circuit_breaker') as mock_cb:
                mock_cb.call.side_effect = lambda fn: fn()
                # Use tools to trigger chat path
                result = llm.stream(
                    "hello",
                    on_chunk=chunks_received.append,
                    tools=[{"type": "function", "function": {"name": "test"}}],
                )

        assert result.content == "Hi there"
        assert result.prompt_tokens == 8
        assert result.completion_tokens == 2


# -----------------------------------------------------------------------
# Agent streaming integration
# -----------------------------------------------------------------------

class TestAgentStreamingIntegration:
    """Test that agent layer correctly wires streaming callbacks."""

    def test_make_stream_callback_with_user_cb(self):
        """make_stream_callback should return combined callback when user_cb is set."""
        from src.agents._standard_agent_helpers import make_stream_callback

        agent = MagicMock()
        agent._stream_callback = MagicMock()
        agent._observer = MagicMock()
        agent._observer.active = True

        cb = make_stream_callback(agent)
        assert cb is not None

        # Call the combined callback
        chunk = LLMStreamChunk(content="hello", chunk_type="content", done=False)
        cb(chunk)

        agent._stream_callback.assert_called_once_with(chunk)
        agent._observer.emit_stream_chunk.assert_called_once()

    def test_make_stream_callback_no_cb_no_observer(self):
        """make_stream_callback should return None when neither is available."""
        from src.agents._standard_agent_helpers import make_stream_callback

        agent = MagicMock()
        agent._stream_callback = None
        agent._observer = MagicMock()
        agent._observer.active = False

        cb = make_stream_callback(agent)
        assert cb is None

    def test_make_stream_callback_observer_only(self):
        """make_stream_callback should work with only observer."""
        from src.agents._standard_agent_helpers import make_stream_callback

        agent = MagicMock()
        agent._stream_callback = None
        agent._observer = MagicMock()
        agent._observer.active = True

        cb = make_stream_callback(agent)
        assert cb is not None

        chunk = LLMStreamChunk(content="hi", chunk_type="content", done=False)
        cb(chunk)
        agent._observer.emit_stream_chunk.assert_called_once()

    def test_setup_execution_stores_stream_callback(self):
        """setup_execution should extract stream_callback from input_data."""
        from src.agents._standard_agent_helpers import setup_execution

        agent = MagicMock()
        agent.name = "test"
        my_callback = lambda c: None  # noqa: E731

        context = MagicMock()
        context.agent_id = "agent-123"

        setup_execution(agent, {"stream_callback": my_callback}, context)
        assert agent._stream_callback == my_callback

    def test_setup_execution_no_stream_callback(self):
        """setup_execution should set None when no stream_callback provided."""
        from src.agents._standard_agent_helpers import setup_execution

        agent = MagicMock()
        agent.name = "test"

        context = MagicMock()
        context.agent_id = "agent-123"

        setup_execution(agent, {}, context)
        assert agent._stream_callback is None


# -----------------------------------------------------------------------
# StreamDisplay
# -----------------------------------------------------------------------

class TestStreamDisplay:
    """Test CLI StreamDisplay thread safety and rendering."""

    def test_stream_display_buffer_accumulation(self):
        """on_chunk should accumulate content in thread-safe buffers."""
        from src.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        # Mock Live to prevent actual terminal output
        with patch('src.cli.stream_display.Live') as MockLive:
            mock_live = MagicMock()
            MockLive.return_value = mock_live

            chunk1 = LLMStreamChunk(content="Hello", chunk_type="content", done=False, model="test")
            chunk2 = LLMStreamChunk(content=" world", chunk_type="content", done=False, model="test")

            display.on_chunk(chunk1)
            display.on_chunk(chunk2)

            assert display._content_buffer == "Hello world"
            assert display._thinking_buffer == ""

    def test_stream_display_thinking_separation(self):
        """Thinking tokens should go to thinking buffer."""
        from src.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('src.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            think_chunk = LLMStreamChunk(content="reasoning...", chunk_type="thinking", done=False, model="test")
            content_chunk = LLMStreamChunk(content="answer", chunk_type="content", done=False, model="test")

            display.on_chunk(think_chunk)
            display.on_chunk(content_chunk)

            assert display._thinking_buffer == "reasoning..."
            assert display._content_buffer == "answer"

    def test_stream_display_done_stops(self):
        """Done chunk should stop the Live display."""
        from src.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('src.cli.stream_display.Live') as MockLive:
            mock_live = MagicMock()
            MockLive.return_value = mock_live

            chunk = LLMStreamChunk(content="hi", chunk_type="content", done=False, model="test")
            done_chunk = LLMStreamChunk(content="", chunk_type="content", done=True, model="test")

            display.on_chunk(chunk)
            assert display._started is True

            display.on_chunk(done_chunk)
            assert display._started is False
            mock_live.stop.assert_called_once()

    def test_stream_display_thread_safety(self):
        """Multiple threads should be able to call on_chunk without errors."""
        from src.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)
        errors = []

        with patch('src.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            def write_chunks(thread_id: int):
                try:
                    for i in range(10):
                        chunk = LLMStreamChunk(
                            content=f"t{thread_id}-{i}",
                            chunk_type="content",
                            done=False,
                            model="test",
                        )
                        display.on_chunk(chunk)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=write_chunks, args=(i,)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            # All 40 chunks should be in the buffer
            assert len(display._content_buffer) > 0


# -----------------------------------------------------------------------
# AgentObserver.emit_stream_chunk
# -----------------------------------------------------------------------

class TestAgentObserverStreaming:
    """Test AgentObserver streaming event emission."""

    def test_emit_stream_chunk_calls_tracker(self):
        """emit_stream_chunk should emit event via tracker's event bus."""
        from src.agents.agent_observer import AgentObserver

        tracker = MagicMock()
        tracker._event_bus = MagicMock()
        context = MagicMock()
        context.agent_id = "agent-123"
        context.workflow_id = "wf-1"
        context.stage_id = "stage-1"

        observer = AgentObserver(tracker, context)

        with patch('src.observability._tracker_helpers.emit_llm_stream_chunk') as mock_emit:
            observer.emit_stream_chunk(
                content="hello",
                chunk_type="content",
                done=False,
                model="test",
            )
            mock_emit.assert_called_once()

    def test_emit_stream_chunk_no_tracker(self):
        """emit_stream_chunk should be a no-op when tracker is None."""
        from src.agents.agent_observer import AgentObserver

        observer = AgentObserver(None, None)
        # Should not raise
        observer.emit_stream_chunk(content="hello")
        assert observer._tracker is None

    def test_emit_stream_chunk_no_event_bus(self):
        """emit_stream_chunk should be a no-op when event_bus is missing."""
        from src.agents.agent_observer import AgentObserver

        tracker = MagicMock(spec=[])  # No _event_bus attribute
        context = MagicMock()
        context.agent_id = "agent-123"

        observer = AgentObserver(tracker, context)
        # Should not raise
        observer.emit_stream_chunk(content="hello")
        assert not hasattr(tracker, '_event_bus')


# -----------------------------------------------------------------------
# Observability emit_llm_stream_chunk
# -----------------------------------------------------------------------

class TestEmitLLMStreamChunk:
    """Test the tracker helper emit function."""

    def test_emit_with_event_bus(self):
        """Should emit ObservabilityEvent to the event bus."""
        from src.observability._tracker_helpers import emit_llm_stream_chunk

        event_bus = MagicMock()
        emit_llm_stream_chunk(
            event_bus=event_bus,
            agent_id="agent-1",
            content="hello",
            chunk_type="content",
            done=False,
        )
        event_bus.emit.assert_called_once()
        event = event_bus.emit.call_args[0][0]
        assert event.event_type == "llm_stream_chunk"
        assert event.data["content"] == "hello"
        assert event.data["agent_id"] == "agent-1"

    def test_emit_none_event_bus(self):
        """Should be a no-op when event_bus is None."""
        from src.observability._tracker_helpers import emit_llm_stream_chunk

        # Should not raise and return None
        result = emit_llm_stream_chunk(
            event_bus=None,
            agent_id="agent-1",
            content="hello",
        )
        assert result is None

    def test_emit_exception_silenced(self):
        """Should silently catch exceptions."""
        from src.observability._tracker_helpers import emit_llm_stream_chunk

        event_bus = MagicMock()
        event_bus.emit.side_effect = RuntimeError("boom")

        # Should not raise — returns None on error
        result = emit_llm_stream_chunk(
            event_bus=event_bus,
            agent_id="agent-1",
            content="hello",
        )
        assert result is None


# -----------------------------------------------------------------------
# LLMStreamChunk dataclass
# -----------------------------------------------------------------------

class TestLLMStreamChunk:
    """Test updated LLMStreamChunk fields."""

    def test_default_fields(self):
        """Verify default field values."""
        chunk = LLMStreamChunk(content="test")
        assert chunk.content == "test"
        assert chunk.chunk_type == "content"
        assert chunk.done is False
        assert chunk.model is None
        assert chunk.prompt_tokens is None
        assert chunk.completion_tokens is None
        assert chunk.finish_reason is None

    def test_thinking_chunk(self):
        """Verify thinking chunk."""
        chunk = LLMStreamChunk(content="thought", chunk_type="thinking")
        assert chunk.chunk_type == "thinking"

    def test_final_chunk(self):
        """Verify final chunk with token counts."""
        chunk = LLMStreamChunk(
            content="",
            done=True,
            model="qwen3",
            prompt_tokens=100,
            completion_tokens=50,
            finish_reason="stop",
        )
        assert chunk.done is True
        assert chunk.prompt_tokens == 100
        assert chunk.completion_tokens == 50
