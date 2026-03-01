"""Tests for LLM iteration event emission.

Covers:
- LLMIterationEventData dataclass creation
- emit_llm_iteration_event with mock observers
- Structured log output verification
- Edge cases (None observer, failing callbacks)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from temper_ai.llm.llm_loop_events import (
    LLMIterationEventData,
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
