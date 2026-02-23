"""Tests for src/observability/collaboration_tracker.py.

Tests collaboration event tracking for multi-agent interactions.
"""

from unittest.mock import Mock

from temper_ai.observability.collaboration_tracker import CollaborationEventTracker
from temper_ai.shared.core.context import ExecutionContext


class TestCollaborationEventTracker:
    """Test CollaborationEventTracker class."""

    def test_initialization(self):
        """Test tracker initialization stores backend reference."""
        backend = Mock()
        sanitize_fn = Mock(side_effect=lambda x: x)
        get_context = Mock(return_value=ExecutionContext())

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)
        assert tracker.backend is backend

    def test_track_collaboration_event_basic(self):
        """Test tracking basic collaboration event."""
        backend = Mock()
        backend.track_collaboration_event = Mock(return_value="event-123")
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="stage-1")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        event_id = tracker.track_collaboration_event(
            event_type="voting",
            agents_involved=["agent1", "agent2"],
            outcome="consensus",
        )

        assert event_id == "event-123"
        backend.track_collaboration_event.assert_called_once()

    def test_track_collaboration_event_with_all_params(self):
        """Test tracking event with all parameters."""
        backend = Mock()
        backend.track_collaboration_event = Mock(return_value="event-456")
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="stage-1")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        event_id = tracker.track_collaboration_event(
            event_type="debate",
            stage_id="custom-stage",
            agents_involved=["agent1", "agent2", "agent3"],
            event_data={"proposal": "option_a"},
            round_number=2,
            resolution_strategy="majority_vote",
            outcome="approved",
            confidence_score=0.85,
            extra_metadata={"duration": 5.2},
        )

        assert event_id == "event-456"
        backend.track_collaboration_event.assert_called_once()
        call_kwargs = backend.track_collaboration_event.call_args[1]
        assert call_kwargs["event_type"] == "debate"
        assert call_kwargs["data"].round_number == 2
        assert call_kwargs["data"].confidence_score == 0.85

    def test_track_collaboration_event_with_current_params(self):
        """Test tracking event with current parameter names."""
        backend = Mock()
        backend.track_collaboration_event = Mock(return_value="event-789")
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="stage-1")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        # Use current parameter names
        event_id = tracker.track_collaboration_event(
            event_type="voting",
            agents_involved=["agent1", "agent2"],
            outcome="approved",
            confidence_score=0.9,
            extra_metadata={"key": "value"},
        )

        assert event_id == "event-789"
        call_kwargs = backend.track_collaboration_event.call_args[1]
        assert call_kwargs["agents_involved"] == ["agent1", "agent2"]
        assert call_kwargs["data"].outcome == "approved"
        assert call_kwargs["data"].confidence_score == 0.9

    def test_track_collaboration_event_missing_stage_id(self):
        """Test that missing stage_id returns empty string."""
        backend = Mock()
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1")  # No stage_id
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        event_id = tracker.track_collaboration_event(
            event_type="voting", agents_involved=["agent1", "agent2"]
        )

        assert event_id == ""
        backend.track_collaboration_event.assert_not_called()

    def test_track_collaboration_event_missing_event_type(self):
        """Test that missing event_type returns empty string."""
        backend = Mock()
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="stage-1")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        event_id = tracker.track_collaboration_event(
            event_type="", agents_involved=["agent1"]  # Empty event type
        )

        assert event_id == ""
        backend.track_collaboration_event.assert_not_called()

    def test_event_data_passed_to_backend(self):
        """Test that event_data is passed through to backend."""
        backend = Mock()
        backend.track_collaboration_event = Mock(return_value="event-123")
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="stage-1")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        event_data = {"proposal": "option_a", "votes": 3}
        tracker.track_collaboration_event(event_type="voting", event_data=event_data)

        # Event data should be passed to backend wrapped in CollaborationEventData
        call_kwargs = backend.track_collaboration_event.call_args[1]
        assert call_kwargs["data"].event_data == event_data

    def test_backend_write_failure(self):
        """Test handling of backend write failure."""
        backend = Mock()
        backend.track_collaboration_event = Mock(side_effect=Exception("Write failed"))
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="stage-1")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        # Should handle exception gracefully and return empty string
        event_id = tracker.track_collaboration_event(
            event_type="voting", agents_involved=["agent1"]
        )

        assert event_id == ""

    def test_stage_id_from_context(self):
        """Test that stage_id is taken from context when not provided."""
        backend = Mock()
        backend.track_collaboration_event = Mock(return_value="event-123")
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="context-stage")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        tracker.track_collaboration_event(event_type="voting")

        call_kwargs = backend.track_collaboration_event.call_args[1]
        assert call_kwargs["stage_id"] == "context-stage"

    def test_stage_id_override(self):
        """Test that explicit stage_id overrides context."""
        backend = Mock()
        backend.track_collaboration_event = Mock(return_value="event-123")
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="context-stage")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        tracker.track_collaboration_event(
            event_type="voting", stage_id="explicit-stage"
        )

        call_kwargs = backend.track_collaboration_event.call_args[1]
        assert call_kwargs["stage_id"] == "explicit-stage"

    def test_multiple_events(self):
        """Test tracking multiple events."""
        backend = Mock()
        backend.track_collaboration_event = Mock(side_effect=["ev-1", "ev-2", "ev-3"])
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="stage-1")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        id1 = tracker.track_collaboration_event(event_type="vote_start")
        id2 = tracker.track_collaboration_event(event_type="vote_cast")
        id3 = tracker.track_collaboration_event(event_type="vote_complete")

        assert id1 == "ev-1"
        assert id2 == "ev-2"
        assert id3 == "ev-3"
        assert backend.track_collaboration_event.call_count == 3

    def test_event_data_types(self):
        """Test various event data types."""
        backend = Mock()
        backend.track_collaboration_event = Mock(return_value="event-123")
        sanitize_fn = Mock(side_effect=lambda x: x)
        context = ExecutionContext(workflow_id="wf-1", stage_id="stage-1")
        get_context = Mock(return_value=context)

        tracker = CollaborationEventTracker(backend, sanitize_fn, get_context)

        # Test with complex event_data
        tracker.track_collaboration_event(
            event_type="debate",
            event_data={
                "proposals": ["A", "B", "C"],
                "votes": {"A": 2, "B": 1, "C": 0},
                "metadata": {"duration": 3.5, "rounds": 2},
            },
        )

        backend.track_collaboration_event.assert_called_once()
        call_kwargs = backend.track_collaboration_event.call_args[1]
        # event_data is wrapped in CollaborationEventData passed as 'data' kwarg
        assert call_kwargs["data"].event_data["proposals"] == ["A", "B", "C"]
        assert call_kwargs["data"].event_data["votes"] == {"A": 2, "B": 1, "C": 0}
        assert call_kwargs["data"].event_data["metadata"]["rounds"] == 2
