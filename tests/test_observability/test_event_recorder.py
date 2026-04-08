"""Tests for EventRecorder."""

from unittest.mock import MagicMock

from temper_ai.observability.event_recorder import EventRecorder, NullNotifier


class TestNullNotifier:
    def test_notify_event_noop(self):
        n = NullNotifier()
        n.notify_event("exec-1", "test", {})  # should not raise

    def test_cleanup_noop(self):
        n = NullNotifier()
        n.cleanup("exec-1")  # should not raise


class TestEventRecorder:
    def test_record_returns_event_id(self):
        recorder = EventRecorder("exec-1", persist=False)
        event_id = recorder.record("test.event", data={"key": "val"})
        assert event_id is not None
        assert len(event_id) > 0

    def test_record_with_custom_id(self):
        recorder = EventRecorder("exec-1", persist=False)
        event_id = recorder.record("test.event", event_id="custom-123")
        assert event_id == "custom-123"

    def test_record_notifies(self):
        notifier = MagicMock()
        recorder = EventRecorder("exec-1", notifier=notifier, persist=False)
        recorder.record("test.event", data={"x": 1})
        notifier.notify_event.assert_called_once()
        args = notifier.notify_event.call_args
        assert args[0][0] == "exec-1"  # execution_id
        assert args[0][1] == "test.event"  # event_type

    def test_record_without_notifier(self):
        recorder = EventRecorder("exec-1", notifier=None, persist=False)
        event_id = recorder.record("test.event")
        assert event_id is not None  # should not crash

    def test_record_with_persist_false_skips_db(self):
        recorder = EventRecorder("exec-1", persist=False)
        # Should not crash even without DB
        event_id = recorder.record("test.event", data={"key": "val"})
        assert event_id is not None

    def test_update_event_notifies(self):
        notifier = MagicMock()
        recorder = EventRecorder("exec-1", notifier=notifier, persist=False)
        recorder.update_event("evt-1", status="completed", data={"result": "ok"})
        assert notifier.notify_event.called

    def test_broadcast_stream_chunk_with_capable_notifier(self):
        notifier = MagicMock()
        notifier.notify_stream_chunk = MagicMock()
        recorder = EventRecorder("exec-1", notifier=notifier, persist=False)
        recorder.broadcast_stream_chunk("agent-1", "hello", done=False)
        notifier.notify_stream_chunk.assert_called_once()

    def test_broadcast_stream_chunk_without_method(self):
        notifier = MagicMock(spec=[])  # No notify_stream_chunk
        recorder = EventRecorder("exec-1", notifier=notifier, persist=False)
        # Should not crash
        recorder.broadcast_stream_chunk("agent-1", "hello", done=False)
