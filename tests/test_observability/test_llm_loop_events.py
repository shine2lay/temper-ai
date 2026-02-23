"""Tests for LLM iteration and cache event emission.

Covers:
- LLMIterationEventData and CacheEventData dataclass creation
- emit_llm_iteration_event with mock observers
- emit_cache_event with mock callbacks
- Structured log output verification
- Edge cases (None observer, failing callbacks)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from temper_ai.llm.llm_loop_events import (
    _CACHE_KEY_PREFIX_LENGTH,
    CacheEventData,
    LLMIterationEventData,
    emit_cache_event,
    emit_llm_iteration_event,
)


class TestLLMIterationEventData:
    """Test LLMIterationEventData dataclass."""

    def test_default_values(self) -> None:
        event = LLMIterationEventData(iteration_number=1)
        assert event.iteration_number == 1
        assert event.agent_name == "unknown"
        assert event.conversation_turns_count == 0
        assert event.tool_calls_this_iteration == 0
        assert event.total_tokens_this_iteration == 0
        assert event.total_cost_this_iteration == 0.0
        assert event.cache_hit is None

    def test_custom_values(self) -> None:
        event = LLMIterationEventData(
            iteration_number=3,
            agent_name="researcher",
            conversation_turns_count=5,
            tool_calls_this_iteration=2,
            total_tokens_this_iteration=1500,
            total_cost_this_iteration=0.003,
            cache_hit=True,
        )
        assert event.iteration_number == 3
        assert event.agent_name == "researcher"
        assert event.conversation_turns_count == 5
        assert event.tool_calls_this_iteration == 2
        assert event.total_tokens_this_iteration == 1500
        assert event.total_cost_this_iteration == 0.003
        assert event.cache_hit is True


class TestCacheEventData:
    """Test CacheEventData dataclass."""

    def test_default_values(self) -> None:
        event = CacheEventData(event_type="hit")
        assert event.event_type == "hit"
        assert event.key_prefix == ""
        assert event.model is None
        assert event.cache_size is None

    def test_custom_values(self) -> None:
        event = CacheEventData(
            event_type="miss",
            key_prefix="abc123def456",
            model="gpt-4",
            cache_size=42,
        )
        assert event.event_type == "miss"
        assert event.key_prefix == "abc123def456"
        assert event.model == "gpt-4"
        assert event.cache_size == 42

    def test_all_event_types(self) -> None:
        for event_type in ("hit", "miss", "write", "eviction"):
            event = CacheEventData(event_type=event_type)
            assert event.event_type == event_type


class TestEmitLLMIterationEvent:
    """Test emit_llm_iteration_event helper."""

    def test_emits_to_observer(self) -> None:
        observer = MagicMock()
        event_data = LLMIterationEventData(
            iteration_number=1,
            agent_name="test-agent",
        )
        emit_llm_iteration_event(observer, event_data)
        observer.track_llm_iteration.assert_called_once_with(event_data)

    def test_none_observer_no_error(self) -> None:
        event_data = LLMIterationEventData(iteration_number=1)
        emit_llm_iteration_event(None, event_data)
        assert event_data.iteration_number == 1  # no exception raised

    def test_observer_without_track_method(self) -> None:
        observer = MagicMock(spec=[])  # No methods
        event_data = LLMIterationEventData(iteration_number=1)
        emit_llm_iteration_event(observer, event_data)
        assert event_data.iteration_number == 1  # no exception raised

    def test_observer_raises_runtime_error(self) -> None:
        observer = MagicMock()
        observer.track_llm_iteration.side_effect = RuntimeError("fail")
        event_data = LLMIterationEventData(iteration_number=2)
        emit_llm_iteration_event(observer, event_data)
        assert event_data.iteration_number == 2  # exception swallowed

    def test_observer_raises_type_error(self) -> None:
        observer = MagicMock()
        observer.track_llm_iteration.side_effect = TypeError("bad arg")
        event_data = LLMIterationEventData(iteration_number=1)
        emit_llm_iteration_event(observer, event_data)
        assert event_data.iteration_number == 1  # exception swallowed

    def test_structured_log_output(self, caplog: pytest.LogCaptureFixture) -> None:
        event_data = LLMIterationEventData(
            iteration_number=2,
            agent_name="analyzer",
            tool_calls_this_iteration=3,
            total_tokens_this_iteration=500,
            total_cost_this_iteration=0.001,
        )
        with caplog.at_level(logging.INFO, logger="temper_ai.llm.llm_loop_events"):
            emit_llm_iteration_event(None, event_data)

        assert "LLM iteration 2" in caplog.text
        assert "analyzer" in caplog.text
        assert "tools=3" in caplog.text
        assert "tokens=500" in caplog.text


class TestEmitCacheEvent:
    """Test emit_cache_event helper."""

    def test_emits_to_callback(self) -> None:
        callback = MagicMock()
        event_data = CacheEventData(event_type="hit", key_prefix="abc123")
        emit_cache_event(callback, event_data)
        callback.assert_called_once_with(event_data)

    def test_none_callback_no_error(self) -> None:
        event_data = CacheEventData(event_type="miss")
        emit_cache_event(None, event_data)
        assert event_data.event_type == "miss"  # no exception raised

    def test_callback_raises_type_error(self) -> None:
        callback = MagicMock(side_effect=TypeError("bad"))
        event_data = CacheEventData(event_type="write")
        emit_cache_event(callback, event_data)
        assert event_data.event_type == "write"  # exception swallowed

    def test_callback_raises_runtime_error(self) -> None:
        callback = MagicMock(side_effect=RuntimeError("fail"))
        event_data = CacheEventData(event_type="eviction")
        emit_cache_event(callback, event_data)
        assert event_data.event_type == "eviction"  # exception swallowed

    def test_callback_raises_value_error(self) -> None:
        callback = MagicMock(side_effect=ValueError("oops"))
        event_data = CacheEventData(event_type="hit")
        emit_cache_event(callback, event_data)
        assert event_data.event_type == "hit"  # exception swallowed

    def test_structured_log_output(self, caplog: pytest.LogCaptureFixture) -> None:
        event_data = CacheEventData(
            event_type="hit",
            key_prefix="abc123",
            model="gpt-4",
            cache_size=10,
        )
        with caplog.at_level(logging.DEBUG, logger="temper_ai.llm.llm_loop_events"):
            emit_cache_event(None, event_data)

        assert "Cache event=hit" in caplog.text
        assert "abc123" in caplog.text

    def test_cache_key_prefix_length_constant(self) -> None:
        assert _CACHE_KEY_PREFIX_LENGTH == 16


class TestCacheEventIntegration:
    """Integration tests for cache event data flow."""

    def test_event_data_passed_through(self) -> None:
        received = []

        def capture(event: CacheEventData) -> None:
            received.append(event)

        event = CacheEventData(
            event_type="write",
            key_prefix="sha256abc",
            model="llama3",
            cache_size=5,
        )
        emit_cache_event(capture, event)

        assert len(received) == 1
        assert received[0].event_type == "write"
        assert received[0].key_prefix == "sha256abc"
        assert received[0].model == "llama3"
        assert received[0].cache_size == 5

    def test_multiple_events(self) -> None:
        received = []

        def capture(event: CacheEventData) -> None:
            received.append(event)

        for event_type in ("miss", "write", "hit"):
            emit_cache_event(capture, CacheEventData(event_type=event_type))

        assert len(received) == 3
        assert [e.event_type for e in received] == ["miss", "write", "hit"]
