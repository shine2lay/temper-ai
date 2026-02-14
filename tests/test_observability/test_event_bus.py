"""Tests for ObservabilityEventBus and tracker integration."""
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.observability.constants import ObservabilityFields
from src.observability.event_bus import ObservabilityEvent, ObservabilityEventBus


# ============================================================
# ObservabilityEvent dataclass tests
# ============================================================

class TestObservabilityEvent:
    """Tests for the ObservabilityEvent dataclass."""

    def test_create_event_with_required_fields(self):
        ts = datetime.now(timezone.utc)
        event = ObservabilityEvent(
            event_type="workflow_start",
            timestamp=ts,
            data={"workflow_id": "wf-123"},
        )
        assert event.event_type == "workflow_start"
        assert event.timestamp == ts
        assert event.data == {"workflow_id": "wf-123"}
        assert event.workflow_id is None
        assert event.stage_id is None
        assert event.agent_id is None

    def test_create_event_with_all_fields(self):
        ts = datetime.now(timezone.utc)
        event = ObservabilityEvent(
            event_type="llm_call",
            timestamp=ts,
            data={"model": "gpt-4"},
            workflow_id="wf-1",
            stage_id="st-1",
            agent_id="ag-1",
        )
        assert event.workflow_id == "wf-1"
        assert event.stage_id == "st-1"
        assert event.agent_id == "ag-1"


# ============================================================
# ObservabilityEventBus unit tests
# ============================================================

class TestObservabilityEventBus:
    """Unit tests for the event bus subscribe/unsubscribe/emit."""

    def _make_event(self, event_type: str = "test_event") -> ObservabilityEvent:
        return ObservabilityEvent(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            data={"key": "value"},
        )

    def test_subscribe_returns_id(self):
        bus = ObservabilityEventBus()
        cb = Mock()
        sub_id = bus.subscribe(cb)
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0

    def test_emit_calls_subscriber(self):
        bus = ObservabilityEventBus()
        cb = Mock()
        bus.subscribe(cb)
        event = self._make_event()
        bus.emit(event)
        cb.assert_called_once_with(event)

    def test_emit_to_multiple_subscribers(self):
        bus = ObservabilityEventBus()
        cb1 = Mock()
        cb2 = Mock()
        bus.subscribe(cb1)
        bus.subscribe(cb2)
        event = self._make_event()
        bus.emit(event)
        cb1.assert_called_once_with(event)
        cb2.assert_called_once_with(event)

    def test_unsubscribe_stops_delivery(self):
        bus = ObservabilityEventBus()
        cb = Mock()
        sub_id = bus.subscribe(cb)
        bus.unsubscribe(sub_id)
        bus.emit(self._make_event())
        cb.assert_not_called()

    def test_unsubscribe_nonexistent_id_is_noop(self):
        bus = ObservabilityEventBus()
        result = bus.unsubscribe("nonexistent-id")  # should not raise
        assert result is None

    def test_event_type_filtering_receives_matching(self):
        bus = ObservabilityEventBus()
        cb = Mock()
        bus.subscribe(cb, event_types={"workflow_start", "workflow_end"})
        bus.emit(self._make_event("workflow_start"))
        assert cb.call_count == 1

    def test_event_type_filtering_skips_non_matching(self):
        bus = ObservabilityEventBus()
        cb = Mock()
        bus.subscribe(cb, event_types={"workflow_start"})
        bus.emit(self._make_event("agent_start"))
        cb.assert_not_called()

    def test_none_filter_receives_all_events(self):
        bus = ObservabilityEventBus()
        cb = Mock()
        bus.subscribe(cb, event_types=None)
        bus.emit(self._make_event("workflow_start"))
        bus.emit(self._make_event("agent_end"))
        bus.emit(self._make_event("llm_call"))
        assert cb.call_count == 3

    def test_subscriber_exception_does_not_break_others(self):
        bus = ObservabilityEventBus()
        bad_cb = Mock(side_effect=ValueError("boom"))
        good_cb = Mock()
        bus.subscribe(bad_cb)
        bus.subscribe(good_cb)
        event = self._make_event()
        bus.emit(event)
        bad_cb.assert_called_once_with(event)
        good_cb.assert_called_once_with(event)

    def test_subscriber_exception_is_logged(self):
        bus = ObservabilityEventBus()
        bad_cb = Mock(side_effect=RuntimeError("fail"))
        bus.subscribe(bad_cb)
        with patch("src.observability.event_bus.logger") as mock_logger:
            bus.emit(self._make_event())
            mock_logger.warning.assert_called_once()

    def test_emit_with_no_subscribers(self):
        bus = ObservabilityEventBus()
        result = bus.emit(self._make_event())  # should not raise
        assert result is None

    def test_thread_safety_concurrent_emit(self):
        """Verify concurrent emits from multiple threads work correctly."""
        bus = ObservabilityEventBus()
        received = []
        lock = threading.Lock()

        def callback(event: ObservabilityEvent):
            with lock:
                received.append(event.event_type)

        bus.subscribe(callback)

        threads = []
        num_threads = 10
        events_per_thread = 50
        for i in range(num_threads):
            def emit_events(thread_id=i):
                for j in range(events_per_thread):
                    bus.emit(self._make_event(f"event_{thread_id}_{j}"))
            t = threading.Thread(target=emit_events)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(received) == num_threads * events_per_thread

    def test_thread_safety_concurrent_subscribe_unsubscribe(self):
        """Verify concurrent subscribe/unsubscribe doesn't corrupt state."""
        bus = ObservabilityEventBus()
        sub_ids = []
        lock = threading.Lock()

        def subscribe_task():
            cb = Mock()
            sid = bus.subscribe(cb)
            with lock:
                sub_ids.append(sid)

        def unsubscribe_task():
            with lock:
                if sub_ids:
                    sid = sub_ids.pop(0)
            bus.unsubscribe(sid)

        threads = []
        for _ in range(20):
            threads.append(threading.Thread(target=subscribe_task))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(sub_ids) == 20

        unsub_threads = []
        for _ in range(10):
            unsub_threads.append(threading.Thread(target=unsubscribe_task))
        for t in unsub_threads:
            t.start()
        for t in unsub_threads:
            t.join()

        # 20 subscribed - 10 unsubscribed = 10 remaining
        assert len(sub_ids) == 10


# ============================================================
# Integration tests: ExecutionTracker + EventBus
# ============================================================

class TestTrackerEventBusIntegration:
    """Test that ExecutionTracker emits events through the bus."""

    @pytest.fixture
    def event_bus(self):
        return ObservabilityEventBus()

    @pytest.fixture
    def received_events(self):
        return []

    @pytest.fixture
    def tracker(self, event_bus, received_events):
        """Create an ExecutionTracker with NoOpBackend and event bus."""
        from src.observability.backends.noop_backend import NoOpBackend
        from src.observability.tracker import ExecutionTracker

        def collector(event: ObservabilityEvent):
            received_events.append(event)

        event_bus.subscribe(collector)

        tracker = ExecutionTracker(
            backend=NoOpBackend(),
            event_bus=event_bus,
        )
        return tracker

    def test_workflow_emits_start_and_end(self, tracker, received_events):
        with tracker.track_workflow("test_wf", {"key": "val"}):
            pass

        types = [e.event_type for e in received_events]
        assert "workflow_start" in types
        assert "workflow_end" in types

        start_event = next(e for e in received_events if e.event_type == "workflow_start")
        assert start_event.data["workflow_name"] == "test_wf"

        end_event = next(e for e in received_events if e.event_type == "workflow_end")
        assert end_event.data[ObservabilityFields.STATUS] == "completed"

    def test_workflow_failure_emits_end_with_failed_status(self, tracker, received_events):
        with pytest.raises(ValueError, match="boom"):
            with tracker.track_workflow("test_wf", {}):
                raise ValueError("boom")

        end_events = [e for e in received_events if e.event_type == "workflow_end"]
        assert len(end_events) == 1
        assert end_events[0].data[ObservabilityFields.STATUS] == "failed"
        assert end_events[0].data[ObservabilityFields.ERROR_MESSAGE] == "boom"

    def test_stage_emits_start_and_end(self, tracker, received_events):
        with tracker.track_workflow("wf", {}) as wf_id:
            with tracker.track_stage("stage1", {}, wf_id):
                pass

        types = [e.event_type for e in received_events]
        assert "stage_start" in types
        assert "stage_end" in types

        start_event = next(e for e in received_events if e.event_type == "stage_start")
        assert start_event.data["stage_name"] == "stage1"

    def test_agent_emits_start_and_end(self, tracker, received_events):
        with tracker.track_workflow("wf", {}) as wf_id:
            with tracker.track_stage("s1", {}, wf_id) as stage_id:
                with tracker.track_agent("agent1", {}, stage_id):
                    pass

        types = [e.event_type for e in received_events]
        assert "agent_start" in types
        assert "agent_end" in types

        start_event = next(e for e in received_events if e.event_type == "agent_start")
        assert start_event.data[ObservabilityFields.AGENT_NAME] == "agent1"

        end_event = next(e for e in received_events if e.event_type == "agent_end")
        assert end_event.data[ObservabilityFields.STATUS] == "completed"

    def test_set_agent_output_emits_event(self, tracker, received_events):
        tracker.set_agent_output(
            agent_id="ag-1",
            output_data={"result": "ok"},
            confidence_score=0.95,
            total_tokens=100,
        )
        types = [e.event_type for e in received_events]
        assert "agent_output" in types

        event = next(e for e in received_events if e.event_type == "agent_output")
        assert event.data[ObservabilityFields.AGENT_ID] == "ag-1"
        assert event.data["confidence_score"] == 0.95

    def test_set_stage_output_emits_event(self, tracker, received_events):
        tracker.set_stage_output(stage_id="st-1", output_data={"out": "data"})
        types = [e.event_type for e in received_events]
        assert "stage_output" in types

    def test_track_safety_violation_emits_event(self, tracker, received_events):
        tracker.track_safety_violation(
            violation_severity="HIGH",
            violation_message="unsafe action",
            policy_name="test_policy",
        )
        types = [e.event_type for e in received_events]
        assert "safety_violation" in types

        event = next(e for e in received_events if e.event_type == "safety_violation")
        assert event.data["violation_severity"] == "HIGH"
        assert event.data["policy_name"] == "test_policy"

    def test_track_collaboration_event_emits_event(self, tracker, received_events):
        # Need workflow + stage context for collaboration tracker
        with tracker.track_workflow("wf", {}) as wf_id:
            with tracker.track_stage("s1", {}, wf_id) as stage_id:
                tracker.track_collaboration_event(
                    event_type="vote",
                    stage_id=stage_id,
                    agents_involved=["agent1", "agent2"],
                    outcome="consensus",
                )

        collab_events = [e for e in received_events if e.event_type == "collaboration_event"]
        assert len(collab_events) == 1
        assert collab_events[0].data["outcome"] == "consensus"

    def test_no_event_bus_means_no_emission(self):
        """Tracker without event_bus should work normally without errors."""
        from src.observability.backends.noop_backend import NoOpBackend
        from src.observability.tracker import ExecutionTracker

        tracker = ExecutionTracker(backend=NoOpBackend())
        # Should not raise
        with tracker.track_workflow("wf", {}) as wf_id:
            assert wf_id is not None

    def test_event_carries_context_ids(self, tracker, received_events):
        """Verify events carry workflow_id, stage_id, agent_id from context."""
        with tracker.track_workflow("wf", {}) as wf_id:
            with tracker.track_stage("s1", {}, wf_id) as stage_id:
                with tracker.track_agent("a1", {}, stage_id) as agent_id:
                    # agent_end event should have all context ids
                    pass

        agent_end = next(e for e in received_events if e.event_type == "agent_end")
        assert agent_end.workflow_id == wf_id
        assert agent_end.stage_id == stage_id
        # agent_id in context gets cleared in finally, but the event is emitted before that
        assert agent_end.agent_id == agent_id

    def test_llm_call_emits_event(self, tracker, received_events):
        """Verify track_llm_call emits an llm_call event."""
        tracker.track_llm_call(
            agent_id="ag-1",
            provider="ollama",
            model="test-model",
            prompt="hello",
            response="world",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.001,
        )
        types = [e.event_type for e in received_events]
        assert "llm_call" in types

        event = next(e for e in received_events if e.event_type == "llm_call")
        assert event.data["provider"] == "ollama"
        assert event.data["model"] == "test-model"
        assert event.data["prompt_tokens"] == 10
        assert event.agent_id == "ag-1"

    def test_tool_call_emits_event(self, tracker, received_events):
        """Verify track_tool_call emits a tool_call event."""
        tracker.track_tool_call(
            agent_id="ag-1",
            tool_name="web_search",
            input_params={"query": "test"},
            output_data={"results": []},
            duration_seconds=1.5,
        )
        types = [e.event_type for e in received_events]
        assert "tool_call" in types

        event = next(e for e in received_events if e.event_type == "tool_call")
        assert event.data["tool_name"] == "web_search"
        assert event.data[ObservabilityFields.DURATION_SECONDS] == 1.5
        assert event.agent_id == "ag-1"
