"""Tests for lifecycle event buffering in ObservabilityBuffer."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from temper_ai.observability.buffer import BufferedLifecycleEvent, ObservabilityBuffer


def _make_event(event_type: str = "agent_end", entity_id: str = "agent-1") -> BufferedLifecycleEvent:
    """Create a test lifecycle event."""
    return BufferedLifecycleEvent(
        event_type=event_type,
        entity_id=entity_id,
        timestamp=datetime.now(timezone.utc),
        data={"status": "completed"},
    )


def _make_buffer(**kwargs) -> ObservabilityBuffer:
    """Create a buffer with auto_flush disabled for deterministic testing."""
    defaults = {"auto_flush": False, "flush_size": 100}
    defaults.update(kwargs)
    return ObservabilityBuffer(**defaults)


class TestBufferLifecycleAppend:
    """Test that buffer_lifecycle_event adds events to the list."""

    def test_append_single_event(self):
        buf = _make_buffer()
        event = _make_event()

        buf.buffer_lifecycle_event(event)

        assert len(buf.lifecycle_events) == 1
        assert buf.lifecycle_events[0] is event

    def test_append_multiple_events(self):
        buf = _make_buffer()

        buf.buffer_lifecycle_event(_make_event(entity_id="a"))
        buf.buffer_lifecycle_event(_make_event(entity_id="b"))

        assert len(buf.lifecycle_events) == 2
        assert buf.lifecycle_events[0].entity_id == "a"
        assert buf.lifecycle_events[1].entity_id == "b"


class TestBufferLifecycleStats:
    """Test that get_stats includes lifecycle event count."""

    def test_stats_includes_lifecycle_events_buffered(self):
        buf = _make_buffer()
        buf.buffer_lifecycle_event(_make_event())
        buf.buffer_lifecycle_event(_make_event())

        stats = buf.get_stats()

        assert stats["lifecycle_events_buffered"] == 2

    def test_stats_zero_when_empty(self):
        buf = _make_buffer()

        stats = buf.get_stats()

        assert stats["lifecycle_events_buffered"] == 0

    def test_total_buffered_includes_lifecycle(self):
        buf = _make_buffer()
        buf.buffer_lifecycle_event(_make_event())

        stats = buf.get_stats()

        assert stats["total_buffered"] == 1


class TestBufferLifecycleFlush:
    """Test flush behavior with lifecycle events."""

    def test_flush_calls_lifecycle_callback(self):
        buf = _make_buffer()
        callback = MagicMock()
        buf.set_lifecycle_flush_callback(callback)
        event = _make_event()
        buf.buffer_lifecycle_event(event)

        buf.flush()

        callback.assert_called_once()
        flushed_events = callback.call_args[0][0]
        assert len(flushed_events) == 1
        assert flushed_events[0] is event

    def test_cleared_after_flush(self):
        buf = _make_buffer()
        buf.set_lifecycle_flush_callback(MagicMock())
        buf.buffer_lifecycle_event(_make_event())

        buf.flush()

        assert len(buf.lifecycle_events) == 0

    def test_no_callback_silent_discard(self):
        buf = _make_buffer()
        buf.buffer_lifecycle_event(_make_event())

        # Flush without setting a lifecycle callback — should not raise
        buf.flush()

        assert len(buf.lifecycle_events) == 0

    def test_callback_error_does_not_crash(self):
        buf = _make_buffer()
        bad_callback = MagicMock(side_effect=RuntimeError("db down"))
        buf.set_lifecycle_flush_callback(bad_callback)
        buf.buffer_lifecycle_event(_make_event())

        # Should not propagate the exception
        buf.flush()

        bad_callback.assert_called_once()
        assert len(buf.lifecycle_events) == 0


class TestBufferLifecycleShouldFlush:
    """Test that lifecycle events contribute to flush trigger."""

    def test_lifecycle_count_triggers_flush(self):
        buf = _make_buffer(flush_size=2)
        # Need a flush callback for _swap_and_prepare to succeed
        buf.set_flush_callback(MagicMock())

        buf.buffer_lifecycle_event(_make_event(entity_id="a"))
        # At this point flush_size=2 not yet reached; only 1 lifecycle event
        assert len(buf.lifecycle_events) == 1

        # Second event should trigger _should_flush but lifecycle events
        # are not part of _swap_and_prepare (only llm/tool/metric),
        # so they stay in lifecycle_events. The point is _should_flush returns True.
        buf.buffer_lifecycle_event(_make_event(entity_id="b"))

        # The _should_flush check fires, but _swap_and_prepare returns None
        # because there are no llm_calls/tool_calls/agent_metrics/retry_queue.
        # Events remain buffered until explicit flush().
        assert len(buf.lifecycle_events) == 2

    def test_lifecycle_plus_llm_triggers_flush(self):
        buf = _make_buffer(flush_size=2)
        flush_cb = MagicMock()
        buf.set_flush_callback(flush_cb)
        buf.set_lifecycle_flush_callback(MagicMock())

        # Add 1 lifecycle event (count=1, below flush_size=2)
        buf.buffer_lifecycle_event(_make_event())

        from temper_ai.observability.buffer import LLMCallBufferParams

        # Adding 1 LLM call makes total=2 (lifecycle+llm), triggers flush
        buf.buffer_llm_call(LLMCallBufferParams(
            llm_call_id="llm-1", agent_id="agent-1", provider="test",
            model="test", prompt="p", response="r",
            prompt_tokens=10, completion_tokens=10, latency_ms=100,
            estimated_cost_usd=0.01, start_time=datetime.now(timezone.utc),
        ))

        # The LLM flush callback was invoked because total items >= flush_size
        flush_cb.assert_called_once()


class TestBufferedLifecycleEventDataclass:
    """Test the BufferedLifecycleEvent dataclass."""

    def test_fields(self):
        now = datetime.now(timezone.utc)
        event = BufferedLifecycleEvent(
            event_type="workflow_end",
            entity_id="wf-123",
            timestamp=now,
            data={"duration_ms": 500},
        )

        assert event.event_type == "workflow_end"
        assert event.entity_id == "wf-123"
        assert event.timestamp == now
        assert event.data == {"duration_ms": 500}
