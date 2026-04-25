"""Tests for CompositeNotifier — fan EventRecorder events to N sinks."""

from __future__ import annotations

from unittest.mock import MagicMock

from temper_ai.observability.composite_notifier import CompositeNotifier


def test_notify_event_fans_out_to_all_notifiers():
    a = MagicMock()
    b = MagicMock()
    c = CompositeNotifier(a, b)
    c.notify_event("e", "type", {"k": "v"})
    a.notify_event.assert_called_once_with("e", "type", {"k": "v"})
    b.notify_event.assert_called_once_with("e", "type", {"k": "v"})


def test_notify_stream_chunk_fans_out():
    a = MagicMock()
    b = MagicMock()
    c = CompositeNotifier(a, b)
    c.notify_stream_chunk("e", "agent", "hello", "content", False)
    a.notify_stream_chunk.assert_called_once()
    b.notify_stream_chunk.assert_called_once()


def test_notify_stream_chunk_skips_notifiers_without_method():
    """A notifier that doesn't implement notify_stream_chunk is silently
    skipped — JsonlNotifier doesn't need to handle chunks for example."""

    class NoChunks:
        def notify_event(self, *_args, **_kwargs):
            pass

        def cleanup(self, *_args, **_kwargs):
            pass

    a = MagicMock()
    b = NoChunks()  # no notify_stream_chunk attribute
    c = CompositeNotifier(a, b)
    c.notify_stream_chunk("e", "x", "y")  # must not raise
    a.notify_stream_chunk.assert_called_once()


def test_cleanup_fans_out():
    a = MagicMock()
    b = MagicMock()
    c = CompositeNotifier(a, b)
    c.cleanup("e")
    a.cleanup.assert_called_once_with("e")
    b.cleanup.assert_called_once_with("e")


def test_failing_sink_does_not_block_others():
    a = MagicMock()
    a.notify_event.side_effect = RuntimeError("a is broken")
    b = MagicMock()
    c = CompositeNotifier(a, b)

    c.notify_event("e", "type", {})  # must not raise
    b.notify_event.assert_called_once()


def test_none_notifiers_filtered_out():
    """Caller can pass None for optional sinks without conditional construction."""
    a = MagicMock()
    c = CompositeNotifier(a, None, None)
    c.notify_event("e", "x", {})
    a.notify_event.assert_called_once()


def test_no_notifiers_is_no_op():
    c = CompositeNotifier()
    c.notify_event("e", "x", {})
    c.notify_stream_chunk("e", "a", "x")
    c.cleanup("e")
    # Just verify no exception
