"""Coverage tests for temper_ai/llm/llm_loop_events.py.

Covers: emit_llm_iteration_event, _try_emit_to_observer,
emit_cache_event, CacheEventData, LLMIterationEventData.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from temper_ai.llm.llm_loop_events import (
    CacheEventData,
    LLMIterationEventData,
    _try_emit_to_observer,
    emit_cache_event,
    emit_llm_iteration_event,
)


class TestLLMIterationEventData:
    def test_defaults(self) -> None:
        event = LLMIterationEventData(iteration_number=1)
        assert event.iteration_number == 1
        assert event.agent_name == "unknown"
        assert event.conversation_turns_count == 0
        assert event.tool_calls_this_iteration == 0
        assert event.cache_hit is None


class TestCacheEventData:
    def test_creation(self) -> None:
        event = CacheEventData(
            event_type="hit", key_prefix="abc", model="gpt-4", cache_size=100
        )
        assert event.event_type == "hit"
        assert event.key_prefix == "abc"

    def test_defaults(self) -> None:
        event = CacheEventData(event_type="miss")
        assert event.key_prefix == ""
        assert event.model is None
        assert event.cache_size is None


class TestEmitLLMIterationEvent:
    def test_with_none_observer(self) -> None:
        event = LLMIterationEventData(iteration_number=1)
        # Should not raise
        emit_llm_iteration_event(None, event)

    def test_with_observer(self) -> None:
        observer = MagicMock()
        observer.track_llm_iteration = MagicMock()
        event = LLMIterationEventData(iteration_number=2, agent_name="test")
        emit_llm_iteration_event(observer, event)
        observer.track_llm_iteration.assert_called_once_with(event)


class TestTryEmitToObserver:
    def test_observer_with_track_fn(self) -> None:
        observer = MagicMock()
        observer.track_llm_iteration = MagicMock()
        event = LLMIterationEventData(iteration_number=1)
        _try_emit_to_observer(observer, event)
        observer.track_llm_iteration.assert_called_once()

    def test_observer_without_track_fn(self) -> None:
        observer = MagicMock(spec=[])  # No attributes
        event = LLMIterationEventData(iteration_number=1)
        # Should not raise (getattr returns None)
        _try_emit_to_observer(observer, event)

    def test_observer_raises(self) -> None:
        observer = MagicMock()
        observer.track_llm_iteration.side_effect = RuntimeError("fail")
        event = LLMIterationEventData(iteration_number=1)
        # Should not raise, logs instead
        _try_emit_to_observer(observer, event)


class TestEmitCacheEvent:
    def test_with_none_callback(self) -> None:
        event = CacheEventData(event_type="miss")
        # Should not raise
        emit_cache_event(None, event)

    def test_with_callback(self) -> None:
        callback = MagicMock()
        event = CacheEventData(event_type="hit", key_prefix="abc")
        emit_cache_event(callback, event)
        callback.assert_called_once_with(event)

    def test_callback_raises(self) -> None:
        callback = MagicMock(side_effect=TypeError("bad arg"))
        event = CacheEventData(event_type="write")
        # Should not raise
        emit_cache_event(callback, event)

    def test_callback_raises_runtime(self) -> None:
        callback = MagicMock(side_effect=RuntimeError("runtime fail"))
        event = CacheEventData(event_type="eviction")
        emit_cache_event(callback, event)

    def test_callback_raises_value(self) -> None:
        callback = MagicMock(side_effect=ValueError("value fail"))
        event = CacheEventData(event_type="eviction")
        emit_cache_event(callback, event)
