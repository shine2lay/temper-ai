"""Integration tests: LLMService emits per-iteration and cache events.

Verifies that LLMService.run() and LLMService.arun() emit
LLMIterationEventData events for each loop iteration, and that
LLMCache fires cache events through its callback.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.llm.service import LLMService, LLMRunResult, _RunState
from src.observability.llm_loop_events import (
    CacheEventData,
    LLMIterationEventData,
    emit_llm_iteration_event,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@dataclass
class FakeLLMResponse:
    """Minimal LLM response for testing."""
    content: str = "Final answer."
    total_tokens: int = 100
    prompt_tokens: int = 50
    completion_tokens: int = 50
    latency_ms: float = 42.0
    model: Optional[str] = "test-model"


@dataclass
class FakeInferenceConfig:
    """Minimal inference config for testing."""
    provider: str = "test"
    model: str = "test-model"
    temperature: float = 0.7
    max_tokens: int = 1024
    max_retries: int = 0


def make_llm_service(
    responses: Optional[List[FakeLLMResponse]] = None,
) -> tuple:
    """Create LLMService with a mock LLM that returns predefined responses.

    Returns:
        (service, mock_llm, inference_config)
    """
    if responses is None:
        responses = [FakeLLMResponse()]

    mock_llm = MagicMock()
    call_count = 0

    def fake_call(prompt: str, **kwargs: Any) -> FakeLLMResponse:
        nonlocal call_count
        resp = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return resp

    mock_llm.call = fake_call
    mock_llm.model = "test-model"
    mock_llm.supports_native_tools = False

    config = FakeInferenceConfig()
    service = LLMService(llm=mock_llm, inference_config=config)
    return service, mock_llm, config


# ---------------------------------------------------------------------------
# Tests: iteration event emission during run()
# ---------------------------------------------------------------------------

class TestLLMServiceIterationEvents:
    """Test that LLMService emits iteration events."""

    @patch("src.llm.service.emit_llm_iteration_event")
    @patch("src.llm.service.estimate_cost", return_value=0.001)
    @patch("src.llm.service.call_with_retry_sync")
    @patch("src.llm.service.track_call")
    def test_single_iteration_emits_event(
        self, mock_track_call: MagicMock,
        mock_retry: MagicMock,
        mock_cost: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        """Single LLM call (no tool calls) should emit one iteration event."""
        service, mock_llm, config = make_llm_service()
        response = FakeLLMResponse(content="Hello!")
        mock_retry.return_value = (response, None)

        observer = MagicMock()
        result = service.run("test prompt", observer=observer, agent_name="agent-a")

        assert mock_emit.call_count == 1
        call_args = mock_emit.call_args
        assert call_args[0][0] is observer
        event_data = call_args[0][1]
        assert isinstance(event_data, LLMIterationEventData)
        assert event_data.iteration_number == 1
        assert event_data.agent_name == "agent-a"
        assert event_data.tool_calls_this_iteration == 0

    @patch("src.llm.service.build_text_schemas", return_value=(None, 0))
    @patch("src.llm.service.build_native_tool_defs", return_value=(None, None))
    @patch("src.llm.service.inject_results", return_value="injected prompt")
    @patch("src.llm.service.execute_tools", return_value=[{"name": "bash", "result": "ok"}])
    @patch("src.llm.service.parse_tool_calls")
    @patch("src.llm.service.track_call")
    @patch("src.llm.service.call_with_retry_sync")
    @patch("src.llm.service.estimate_cost", return_value=0.001)
    @patch("src.llm.service.emit_llm_iteration_event")
    def test_multi_iteration_emits_per_iteration(
        self,
        mock_emit: MagicMock,
        mock_cost: MagicMock,
        mock_retry: MagicMock,
        mock_track_call: MagicMock,
        mock_parse: MagicMock,
        mock_exec_tools: MagicMock,
        mock_inject: MagicMock,
        mock_native_defs: MagicMock,
        mock_text_schemas: MagicMock,
    ) -> None:
        """Two iterations should emit two events with incrementing numbers."""
        service, mock_llm, config = make_llm_service()

        # First call returns tool calls, second returns final answer
        resp1 = FakeLLMResponse(content="<tool>bash</tool>", total_tokens=80)
        resp2 = FakeLLMResponse(content="Done!", total_tokens=120)
        mock_retry.side_effect = [(resp1, None), (resp2, None)]

        # First parse returns tool call, second returns empty
        mock_parse.side_effect = [
            [{"name": "bash", "arguments": {}}],
            [],
        ]

        mock_tool = MagicMock()
        mock_tool.name = "bash"
        result = service.run("test", tools=[mock_tool], agent_name="multi-agent")

        assert mock_emit.call_count == 2
        # First iteration
        first_event = mock_emit.call_args_list[0][0][1]
        assert first_event.iteration_number == 1
        assert first_event.tool_calls_this_iteration == 1

        # Second iteration
        second_event = mock_emit.call_args_list[1][0][1]
        assert second_event.iteration_number == 2
        assert second_event.tool_calls_this_iteration == 0

    @patch("src.llm.service.emit_llm_iteration_event")
    @patch("src.llm.service.estimate_cost", return_value=0.0)
    @patch("src.llm.service.call_with_retry_sync")
    @patch("src.llm.service.track_call")
    def test_none_observer_still_emits(
        self, mock_track_call: MagicMock,
        mock_retry: MagicMock,
        mock_cost: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        """Even with no observer, the emit function should be called."""
        service, _, _ = make_llm_service()
        mock_retry.return_value = (FakeLLMResponse(), None)

        service.run("prompt", observer=None)

        assert mock_emit.call_count == 1
        assert mock_emit.call_args[0][0] is None

    @patch("src.llm.service.emit_llm_iteration_event")
    @patch("src.llm.service.estimate_cost", return_value=0.005)
    @patch("src.llm.service.call_with_retry_sync")
    @patch("src.llm.service.track_call")
    def test_iteration_tokens_tracked(
        self, mock_track_call: MagicMock,
        mock_retry: MagicMock,
        mock_cost: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        """Iteration event should contain per-iteration token count."""
        service, _, _ = make_llm_service()
        response = FakeLLMResponse(total_tokens=250)
        mock_retry.return_value = (response, None)

        service.run("test")

        event_data = mock_emit.call_args[0][1]
        assert event_data.total_tokens_this_iteration == 250


class TestLLMServiceIterationEventsAsync:
    """Test async iteration event emission."""

    @patch("src.llm.service.emit_llm_iteration_event")
    @patch("src.llm.service.estimate_cost", return_value=0.0)
    @patch("src.llm.service.call_with_retry_async")
    @patch("src.llm.service.track_call")
    def test_arun_emits_iteration_event(
        self, mock_track_call: MagicMock,
        mock_retry: MagicMock,
        mock_cost: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        """arun() should emit iteration events like run()."""
        service, _, _ = make_llm_service()
        response = FakeLLMResponse(content="async answer")

        async def fake_retry(*args: Any, **kwargs: Any) -> tuple:
            return (response, None)

        mock_retry.side_effect = fake_retry

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                service.arun("async prompt", agent_name="async-agent")
            )
        finally:
            loop.close()

        assert mock_emit.call_count == 1
        event_data = mock_emit.call_args[0][1]
        assert event_data.iteration_number == 1
        assert event_data.agent_name == "async-agent"


class TestRunStateIterationNumber:
    """Test _RunState.iteration_number field."""

    def test_default_is_zero(self) -> None:
        state = _RunState()
        assert state.iteration_number == 0

    def test_increments(self) -> None:
        state = _RunState()
        state.iteration_number += 1
        assert state.iteration_number == 1
        state.iteration_number += 1
        assert state.iteration_number == 2


# ---------------------------------------------------------------------------
# Tests: LLMCache event callback
# ---------------------------------------------------------------------------

class TestLLMCacheEvents:
    """Test cache event emission via on_event callback."""

    def test_cache_hit_fires_event(self) -> None:
        from src.llm.cache.llm_cache import LLMCache

        received: list = []
        cache = LLMCache(backend="memory", on_event=received.append)

        # Populate then retrieve
        cache._backend.set("testkey", "value")
        cache.stats.writes += 1
        # Now get should fire "hit"
        result = cache.get("testkey")

        assert result == "value"
        hit_events = [e for e in received if e.event_type == "hit"]
        assert len(hit_events) >= 1
        assert hit_events[0].key_prefix.startswith("testkey"[:16])

    def test_cache_miss_fires_event(self) -> None:
        from src.llm.cache.llm_cache import LLMCache

        received: list = []
        cache = LLMCache(backend="memory", on_event=received.append)

        result = cache.get("nonexistent")

        assert result is None
        miss_events = [e for e in received if e.event_type == "miss"]
        assert len(miss_events) >= 1

    def test_cache_write_fires_event(self) -> None:
        from src.llm.cache.llm_cache import LLMCache

        received: list = []
        cache = LLMCache(backend="memory", on_event=received.append)

        cache.set("writekey", "some-value")

        write_events = [e for e in received if e.event_type == "write"]
        assert len(write_events) == 1

    def test_cache_eviction_fires_event(self) -> None:
        from src.llm.cache.llm_cache import LLMCache

        received: list = []
        cache = LLMCache(backend="memory", max_size=2, on_event=received.append)

        # Fill cache to capacity
        cache.set("key1", "v1")
        cache.set("key2", "v2")
        # This should trigger eviction of key1
        cache.set("key3", "v3")

        eviction_events = [e for e in received if e.event_type == "eviction"]
        assert len(eviction_events) >= 1

    def test_no_event_callback_no_error(self) -> None:
        from src.llm.cache.llm_cache import LLMCache

        cache = LLMCache(backend="memory")
        cache.set("k", "v")
        result = cache.get("k")
        assert result == "v"

    def test_event_callback_error_handled(self) -> None:
        from src.llm.cache.llm_cache import LLMCache

        def bad_callback(event: Any) -> None:
            raise RuntimeError("boom")

        cache = LLMCache(backend="memory", on_event=bad_callback)
        # Should not raise despite callback error
        cache.set("k", "v")
        result = cache.get("k")
        assert result == "v"

    def test_event_includes_cache_size(self) -> None:
        from src.llm.cache.llm_cache import LLMCache

        received: list = []
        cache = LLMCache(backend="memory", on_event=received.append)

        cache.set("k1", "v1")
        write_events = [e for e in received if e.event_type == "write"]
        assert len(write_events) == 1
        assert write_events[0].cache_size is not None
        assert write_events[0].cache_size >= 1
