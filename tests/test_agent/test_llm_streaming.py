"""Tests for LLM streaming support.

Covers:
- OllamaLLM.stream() with mock NDJSON response
- OllamaLLM._build_request num_predict fix
- BaseLLM.stream() default fallback to complete()
- Agent streaming integration
- StreamDisplay thread safety (generic StreamEvent + backward compat)
- Dashboard DataStore stream batch handling
"""
import json
import threading
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from temper_ai.llm.providers.base import BaseLLM, LLMResponse, LLMStreamChunk, StreamCallback
from temper_ai.llm.providers.ollama import OllamaLLM
from temper_ai.interfaces.cli.stream_events import (
    LLM_DONE,
    LLM_TOKEN,
    PROGRESS,
    STATUS,
    TOOL_RESULT,
    TOOL_START,
    StreamEvent,
    from_llm_chunk,
)


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
        """_make_stream_callback should return combined callback when user_cb is set."""
        from temper_ai.agent.base_agent import BaseAgent

        agent = MagicMock(spec=BaseAgent)
        agent._stream_callback = MagicMock()
        agent._observer = MagicMock()
        agent._observer.active = True

        cb = BaseAgent._make_stream_callback(agent)
        assert cb is not None

        # Call the combined callback
        chunk = LLMStreamChunk(content="hello", chunk_type="content", done=False)
        cb(chunk)

        agent._stream_callback.assert_called_once_with(chunk)
        agent._observer.emit_stream_chunk.assert_called_once()

    def test_make_stream_callback_no_cb_no_observer(self):
        """_make_stream_callback should return None when neither is available."""
        from temper_ai.agent.base_agent import BaseAgent

        agent = MagicMock(spec=BaseAgent)
        agent._stream_callback = None
        agent._observer = MagicMock()
        agent._observer.active = False

        cb = BaseAgent._make_stream_callback(agent)
        assert cb is None

    def test_make_stream_callback_observer_only(self):
        """_make_stream_callback should work with only observer."""
        from temper_ai.agent.base_agent import BaseAgent

        agent = MagicMock(spec=BaseAgent)
        agent._stream_callback = None
        agent._observer = MagicMock()
        agent._observer.active = True

        cb = BaseAgent._make_stream_callback(agent)
        assert cb is not None

        chunk = LLMStreamChunk(content="hi", chunk_type="content", done=False)
        cb(chunk)
        agent._observer.emit_stream_chunk.assert_called_once()

    def test_setup_execution_stores_stream_callback(self):
        """_setup should extract stream_callback from input_data."""
        from temper_ai.agent.base_agent import BaseAgent

        agent = MagicMock(spec=BaseAgent)
        agent.name = "test"
        agent.tool_registry = None
        my_callback = lambda c: None  # noqa: E731

        context = MagicMock()
        context.agent_id = "agent-123"

        BaseAgent._setup(agent, {"stream_callback": my_callback}, context)
        assert agent._stream_callback == my_callback

    def test_setup_execution_no_stream_callback(self):
        """_setup should set None when no stream_callback provided."""
        from temper_ai.agent.base_agent import BaseAgent

        agent = MagicMock(spec=BaseAgent)
        agent.name = "test"
        agent.tool_registry = None

        context = MagicMock()
        context.agent_id = "agent-123"

        BaseAgent._setup(agent, {}, context)
        assert agent._stream_callback is None


# -----------------------------------------------------------------------
# StreamDisplay
# -----------------------------------------------------------------------

class TestStreamDisplay:
    """Test CLI StreamDisplay thread safety and rendering."""

    def test_stream_display_buffer_accumulation(self):
        """on_chunk should accumulate content in per-agent buffers."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        # Mock Live to prevent actual terminal output
        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            mock_live = MagicMock()
            MockLive.return_value = mock_live

            chunk1 = LLMStreamChunk(content="Hello", chunk_type="content", done=False, model="test")
            chunk2 = LLMStreamChunk(content=" world", chunk_type="content", done=False, model="test")

            display.on_chunk(chunk1)
            display.on_chunk(chunk2)

            # Buffers are per-source; on_chunk routes by model name
            assert display._sources["test"].content_buffer == "Hello world"
            assert display._sources["test"].thinking_buffer == ""

    def test_stream_display_thinking_separation(self):
        """Thinking tokens should go to thinking buffer."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            think_chunk = LLMStreamChunk(content="reasoning...", chunk_type="thinking", done=False, model="test")
            content_chunk = LLMStreamChunk(content="answer", chunk_type="content", done=False, model="test")

            display.on_chunk(think_chunk)
            display.on_chunk(content_chunk)

            assert display._sources["test"].thinking_buffer == "reasoning..."
            assert display._sources["test"].content_buffer == "answer"

    def test_stream_display_done_stops(self):
        """Done chunk should stop the Live display."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
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
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)
        errors = []

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
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
            # All chunks from all threads routed to "test" source stream
            assert len(display._sources["test"].content_buffer) > 0

    def test_stream_display_multi_agent(self):
        """make_callback should route chunks to separate per-agent panels."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            cb_a = display.make_callback("agent_a")
            cb_b = display.make_callback("agent_b")

            cb_a(LLMStreamChunk(content="Hello from A", chunk_type="content", done=False, model="m1"))
            cb_b(LLMStreamChunk(content="Hello from B", chunk_type="content", done=False, model="m2"))

            assert "agent_a" in display._sources
            assert "agent_b" in display._sources
            assert display._sources["agent_a"].content_buffer == "Hello from A"
            assert display._sources["agent_b"].content_buffer == "Hello from B"

    def test_stream_display_multi_agent_done(self):
        """Live stops only when ALL agents are done."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            mock_live = MagicMock()
            MockLive.return_value = mock_live

            cb_a = display.make_callback("agent_a")
            cb_b = display.make_callback("agent_b")

            cb_a(LLMStreamChunk(content="A", chunk_type="content", done=False, model="m"))
            cb_b(LLMStreamChunk(content="B", chunk_type="content", done=False, model="m"))

            # Agent A finishes — Live should NOT stop yet
            cb_a(LLMStreamChunk(content="", chunk_type="content", done=True, model="m"))
            assert display._started is True
            assert display._sources["agent_a"].done is True
            assert display._sources["agent_b"].done is False

            # Agent B finishes — now Live should stop
            cb_b(LLMStreamChunk(content="", chunk_type="content", done=True, model="m"))
            assert display._started is False
            mock_live.stop.assert_called_once()


# -----------------------------------------------------------------------
# AgentObserver.emit_stream_chunk
# -----------------------------------------------------------------------

class TestAgentObserverStreaming:
    """Test AgentObserver streaming event emission."""

    def test_emit_stream_chunk_calls_tracker(self):
        """emit_stream_chunk should emit event via tracker's event bus."""
        from temper_ai.agent.utils.agent_observer import AgentObserver

        tracker = MagicMock()
        tracker._event_bus = MagicMock()
        context = MagicMock()
        context.agent_id = "agent-123"
        context.workflow_id = "wf-1"
        context.stage_id = "stage-1"

        observer = AgentObserver(tracker, context)

        with patch('temper_ai.observability._tracker_helpers.emit_llm_stream_chunk') as mock_emit:
            observer.emit_stream_chunk(
                content="hello",
                chunk_type="content",
                done=False,
                model="test",
            )
            mock_emit.assert_called_once()

    def test_emit_stream_chunk_no_tracker(self):
        """emit_stream_chunk should be a no-op when tracker is None."""
        from temper_ai.agent.utils.agent_observer import AgentObserver

        observer = AgentObserver(None, None)
        # Should not raise
        observer.emit_stream_chunk(content="hello")
        assert observer._tracker is None

    def test_emit_stream_chunk_no_event_bus(self):
        """emit_stream_chunk should be a no-op when event_bus is missing."""
        from temper_ai.agent.utils.agent_observer import AgentObserver

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
        from temper_ai.observability._tracker_helpers import emit_llm_stream_chunk, StreamChunkData

        event_bus = MagicMock()
        data = StreamChunkData(
            agent_id="agent-1",
            content="hello",
            chunk_type="content",
            done=False,
        )
        emit_llm_stream_chunk(event_bus=event_bus, data=data)
        event_bus.emit.assert_called_once()
        event = event_bus.emit.call_args[0][0]
        assert event.event_type == "llm_stream_chunk"
        assert event.data["content"] == "hello"
        assert event.data["agent_id"] == "agent-1"

    def test_emit_none_event_bus(self):
        """Should be a no-op when event_bus is None."""
        from temper_ai.observability._tracker_helpers import emit_llm_stream_chunk, StreamChunkData

        data = StreamChunkData(agent_id="agent-1", content="hello")
        # Should not raise and return None
        result = emit_llm_stream_chunk(event_bus=None, data=data)
        assert result is None

    def test_emit_exception_silenced(self):
        """Should silently catch exceptions."""
        from temper_ai.observability._tracker_helpers import emit_llm_stream_chunk, StreamChunkData

        event_bus = MagicMock()
        event_bus.emit.side_effect = RuntimeError("boom")

        data = StreamChunkData(agent_id="agent-1", content="hello")
        # Should not raise — returns None on error
        result = emit_llm_stream_chunk(event_bus=event_bus, data=data)
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


# -----------------------------------------------------------------------
# StreamEvent dataclass + adapter
# -----------------------------------------------------------------------

class TestStreamEvent:
    """Test StreamEvent dataclass and from_llm_chunk adapter."""

    def test_default_fields(self):
        """StreamEvent defaults: content='', done=False, metadata={}."""
        event = StreamEvent(source="agent1", event_type=LLM_TOKEN)
        assert event.source == "agent1"
        assert event.event_type == LLM_TOKEN
        assert event.content == ""
        assert event.done is False
        assert event.metadata == {}

    def test_metadata_isolation(self):
        """Each StreamEvent should get its own metadata dict."""
        e1 = StreamEvent(source="a", event_type=STATUS, content="x")
        e2 = StreamEvent(source="b", event_type=STATUS, content="y")
        e1.metadata["key"] = "val"
        assert "key" not in e2.metadata

    def test_from_llm_chunk_content(self):
        """Adapter converts content LLMStreamChunk to LLM_TOKEN event."""
        chunk = LLMStreamChunk(content="hello", chunk_type="content", done=False, model="qwen3")
        event = from_llm_chunk("researcher", chunk)
        assert event.source == "researcher"
        assert event.event_type == LLM_TOKEN
        assert event.content == "hello"
        assert event.done is False
        assert event.metadata["model"] == "qwen3"
        assert event.metadata["chunk_type"] == "content"

    def test_from_llm_chunk_thinking(self):
        """Adapter preserves thinking chunk_type."""
        chunk = LLMStreamChunk(content="reasoning...", chunk_type="thinking", done=False, model="m")
        event = from_llm_chunk("agent", chunk)
        assert event.event_type == LLM_TOKEN
        assert event.metadata["chunk_type"] == "thinking"

    def test_from_llm_chunk_done(self):
        """Adapter converts done chunk to LLM_DONE event."""
        chunk = LLMStreamChunk(
            content="", done=True, model="qwen3",
            prompt_tokens=100, completion_tokens=50, finish_reason="stop",
        )
        event = from_llm_chunk("agent", chunk)
        assert event.event_type == LLM_DONE
        assert event.done is True
        assert event.metadata["prompt_tokens"] == 100
        assert event.metadata["completion_tokens"] == 50
        assert event.metadata["finish_reason"] == "stop"


# -----------------------------------------------------------------------
# StreamDisplay — StreamEvent handling
# -----------------------------------------------------------------------

class TestStreamDisplayEvents:
    """Test StreamDisplay with generic StreamEvent objects."""

    def test_stream_event_tool_start(self):
        """TOOL_START event should set tool_line on the source stream."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            cb = display.make_callback("agent1")

            # First send a content token so the stream is created
            cb(StreamEvent(
                source="agent1", event_type=LLM_TOKEN, content="Hi",
                metadata={"chunk_type": "content", "model": "test"},
            ))
            # Now send tool_start
            cb(StreamEvent(
                source="agent1", event_type=TOOL_START,
                metadata={"tool_name": "web_search"},
            ))

            assert "\u26a1 web_search running..." == display._sources["agent1"].tool_line

    def test_stream_event_tool_result_success(self):
        """TOOL_RESULT with success should update tool_line with checkmark."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            cb = display.make_callback("agent1")
            cb(StreamEvent(
                source="agent1", event_type=LLM_TOKEN, content="x",
                metadata={"chunk_type": "content", "model": "m"},
            ))
            cb(StreamEvent(
                source="agent1", event_type=TOOL_RESULT,
                metadata={"tool_name": "web_search", "success": True, "duration_s": 1.23},
            ))

            assert "\u2713 web_search (1.2s)" == display._sources["agent1"].tool_line

    def test_stream_event_tool_result_failure(self):
        """TOOL_RESULT with failure should show X mark and error."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            cb = display.make_callback("agent1")
            cb(StreamEvent(
                source="agent1", event_type=LLM_TOKEN, content="x",
                metadata={"chunk_type": "content", "model": "m"},
            ))
            cb(StreamEvent(
                source="agent1", event_type=TOOL_RESULT,
                metadata={"tool_name": "calc", "success": False, "error": "timeout"},
            ))

            assert "\u2717 calc: timeout" == display._sources["agent1"].tool_line

    def test_stream_event_status_overwrites(self):
        """STATUS events should overwrite (not append) the status_line."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            cb = display.make_callback("agent1")
            cb(StreamEvent(
                source="agent1", event_type=LLM_TOKEN, content="x",
                metadata={"chunk_type": "content", "model": "m"},
            ))
            cb(StreamEvent(source="agent1", event_type=STATUS, content="Processing..."))
            cb(StreamEvent(source="agent1", event_type=STATUS, content="Finalizing..."))

            assert display._sources["agent1"].status_line == "Finalizing..."

    def test_stream_event_progress_appends(self):
        """PROGRESS events should append to content_buffer."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            cb = display.make_callback("agent1")
            cb(StreamEvent(
                source="agent1", event_type=PROGRESS, content="Step 1 done. ",
                metadata={"model": "m"},
            ))
            cb(StreamEvent(
                source="agent1", event_type=PROGRESS, content="Step 2 done.",
            ))

            assert display._sources["agent1"].content_buffer == "Step 1 done. Step 2 done."

    def test_stream_event_mixed(self):
        """LLM tokens + tool events should coexist in same source stream."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            cb = display.make_callback("agent1")

            # Thinking
            cb(StreamEvent(
                source="agent1", event_type=LLM_TOKEN, content="Let me think...",
                metadata={"chunk_type": "thinking", "model": "qwen3"},
            ))
            # Content
            cb(StreamEvent(
                source="agent1", event_type=LLM_TOKEN, content="Answer: ",
                metadata={"chunk_type": "content", "model": "qwen3"},
            ))
            # Tool start
            cb(StreamEvent(
                source="agent1", event_type=TOOL_START,
                metadata={"tool_name": "calculator"},
            ))
            # Tool result
            cb(StreamEvent(
                source="agent1", event_type=TOOL_RESULT,
                metadata={"tool_name": "calculator", "success": True, "duration_s": 0.5},
            ))
            # Status
            cb(StreamEvent(source="agent1", event_type=STATUS, content="Done"))

            stream = display._sources["agent1"]
            assert stream.thinking_buffer == "Let me think..."
            assert stream.content_buffer == "Answer: "
            assert stream.tool_line == "\u2713 calculator (0.5s)"
            assert stream.status_line == "Done"

    def test_backward_compat_llm_chunk_via_make_callback(self):
        """make_callback should auto-adapt LLMStreamChunk to StreamEvent."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            MockLive.return_value = MagicMock()

            cb = display.make_callback("agent1")

            # Send legacy LLMStreamChunk
            chunk = LLMStreamChunk(content="Hello", chunk_type="content", done=False, model="test")
            cb(chunk)

            assert "agent1" in display._sources
            assert display._sources["agent1"].content_buffer == "Hello"

    def test_backward_compat_llm_chunk_done_via_make_callback(self):
        """make_callback should handle done LLMStreamChunk correctly."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            mock_live = MagicMock()
            MockLive.return_value = mock_live

            cb = display.make_callback("agent1")

            cb(LLMStreamChunk(content="Hi", chunk_type="content", done=False, model="m"))
            cb(LLMStreamChunk(content="", chunk_type="content", done=True, model="m"))

            assert display._sources["agent1"].done is True
            assert display._started is False

    def test_stream_event_done_stops_display(self):
        """done=True StreamEvent should stop display when all sources are done."""
        from temper_ai.interfaces.cli.stream_display import StreamDisplay

        console = MagicMock()
        display = StreamDisplay(console)

        with patch('temper_ai.interfaces.cli.stream_display.Live') as MockLive:
            mock_live = MagicMock()
            MockLive.return_value = mock_live

            cb = display.make_callback("agent1")
            cb(StreamEvent(
                source="agent1", event_type=LLM_TOKEN, content="x",
                metadata={"chunk_type": "content", "model": "m"},
            ))
            cb(StreamEvent(
                source="agent1", event_type=LLM_DONE, done=True,
                metadata={"model": "m"},
            ))

            assert display._sources["agent1"].done is True
            assert display._started is False
            mock_live.stop.assert_called_once()
