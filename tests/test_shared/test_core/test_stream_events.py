"""Tests for temper_ai/shared/core/stream_events.py.

Covers StreamEvent dataclass and event type constants.
"""

from temper_ai.shared.core.stream_events import (
    PROGRESS,
    TOOL_RESULT,
    TOOL_START,
    StreamEvent,
)


class TestEventTypeConstants:
    """Tests for module-level event type constants."""

    def test_tool_start_value(self):
        assert TOOL_START == "tool_start"

    def test_tool_result_value(self):
        assert TOOL_RESULT == "tool_result"

    def test_progress_value(self):
        assert PROGRESS == "progress"

    def test_all_constants_are_strings(self):
        """All event type constants are strings."""
        for const in (TOOL_START, TOOL_RESULT, PROGRESS):
            assert isinstance(const, str)

    def test_all_constants_are_unique(self):
        """No two event type constants share the same value."""
        constants = [TOOL_START, TOOL_RESULT, PROGRESS]
        assert len(set(constants)) == len(constants)


class TestStreamEvent:
    """Tests for StreamEvent dataclass."""

    def test_required_fields(self):
        """source and event_type are required."""
        event = StreamEvent(source="agent-1", event_type=TOOL_START)
        assert event.source == "agent-1"
        assert event.event_type == TOOL_START

    def test_content_defaults_empty(self):
        """content defaults to empty string."""
        event = StreamEvent(source="src", event_type=TOOL_START)
        assert event.content == ""

    def test_done_defaults_false(self):
        """done defaults to False."""
        event = StreamEvent(source="src", event_type=TOOL_START)
        assert event.done is False

    def test_metadata_defaults_empty_dict(self):
        """metadata defaults to an empty dict."""
        event = StreamEvent(source="src", event_type=TOOL_START)
        assert event.metadata == {}

    def test_metadata_not_shared_between_instances(self):
        """Each instance gets its own metadata dict."""
        e1 = StreamEvent(source="a", event_type=TOOL_START)
        e2 = StreamEvent(source="b", event_type=TOOL_START)
        e1.metadata["key"] = "value"
        assert "key" not in e2.metadata

    def test_full_construction(self):
        """All fields can be set explicitly."""
        event = StreamEvent(
            source="stage-1",
            event_type=TOOL_RESULT,
            content="tool output",
            done=True,
            metadata={"tool_name": "search", "success": True, "duration_s": 1.5},
        )
        assert event.source == "stage-1"
        assert event.event_type == TOOL_RESULT
        assert event.content == "tool output"
        assert event.done is True
        assert event.metadata["tool_name"] == "search"
        assert event.metadata["success"] is True
        assert event.metadata["duration_s"] == 1.5

    def test_is_dataclass(self):
        """StreamEvent is a dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(StreamEvent)

    def test_equality(self):
        """Two StreamEvents with same fields are equal."""
        e1 = StreamEvent(source="a", event_type=TOOL_START, content="hello")
        e2 = StreamEvent(source="a", event_type=TOOL_START, content="hello")
        assert e1 == e2

    def test_inequality_different_source(self):
        """StreamEvents with different source are not equal."""
        e1 = StreamEvent(source="a", event_type=TOOL_START)
        e2 = StreamEvent(source="b", event_type=TOOL_START)
        assert e1 != e2

    def test_progress_event(self):
        """PROGRESS events can hold appending progress messages."""
        event = StreamEvent(source="system", event_type=PROGRESS, content="Step 1 done")
        assert event.event_type == PROGRESS

    def test_tool_start_event(self):
        """TOOL_START events carry tool metadata."""
        event = StreamEvent(
            source="executor",
            event_type=TOOL_START,
            metadata={"tool_name": "web_search", "input_params": {"query": "test"}},
        )
        assert event.event_type == TOOL_START
        assert event.metadata["tool_name"] == "web_search"
