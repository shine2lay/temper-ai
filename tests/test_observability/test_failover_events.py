"""Tests for WI-3: Failover event emission.

Tests FailoverEventData, emit_failover_event helper, and None tracker safety.
"""
import pytest
from unittest.mock import MagicMock, patch

from temper_ai.observability.failover_events import (
    EVENT_TYPE_FAILOVER,
    FailoverEventData,
    emit_failover_event,
)


class TestFailoverEventData:
    """Test FailoverEventData dataclass."""

    def test_creation(self) -> None:
        """Create FailoverEventData with required fields."""
        data = FailoverEventData(
            from_provider="openai",
            to_provider="anthropic",
            failover_sequence=["openai:gpt-4:TimeoutError", "anthropic:claude:success"],
            total_attempts=2,
        )
        assert data.from_provider == "openai"
        assert data.to_provider == "anthropic"
        assert len(data.failover_sequence) == 2
        assert data.total_attempts == 2
        assert data.successful_provider is None

    def test_creation_with_optionals(self) -> None:
        """Create with optional fields."""
        data = FailoverEventData(
            from_provider="openai",
            to_provider="anthropic",
            failover_sequence=["openai:gpt-4:TimeoutError"],
            total_attempts=2,
            successful_provider="anthropic",
            stage_name="analysis",
        )
        assert data.successful_provider == "anthropic"
        assert data.stage_name == "analysis"


class TestEmitFailoverEvent:
    """Test emit_failover_event helper."""

    def test_emit_with_tracker(self) -> None:
        """emit_failover_event routes through tracker."""
        tracker = MagicMock()
        tracker.track_collaboration_event = MagicMock(return_value="evt-1")

        data = FailoverEventData(
            from_provider="openai",
            to_provider="anthropic",
            failover_sequence=["openai:gpt-4:TimeoutError", "anthropic:claude:success"],
            total_attempts=2,
        )
        emit_failover_event(tracker, "stage-123", data)

        tracker.track_collaboration_event.assert_called_once()
        call_args = tracker.track_collaboration_event.call_args
        event_data = call_args[0][0]
        assert event_data.event_type == EVENT_TYPE_FAILOVER

    def test_emit_with_none_tracker(self) -> None:
        """emit_failover_event handles None tracker gracefully."""
        data = FailoverEventData(
            from_provider="openai",
            to_provider="anthropic",
            failover_sequence=[],
            total_attempts=1,
        )
        # Should not raise — returns None implicitly
        result = emit_failover_event(None, "stage-123", data)
        assert result is None

    def test_emit_with_tracker_missing_method(self) -> None:
        """emit_failover_event handles tracker without track_collaboration_event."""
        tracker = MagicMock(spec=[])  # No methods
        data = FailoverEventData(
            from_provider="openai",
            to_provider="anthropic",
            failover_sequence=[],
            total_attempts=1,
        )
        result = emit_failover_event(tracker, "stage-123", data)
        assert result is None

    def test_emit_with_tracker_exception(self) -> None:
        """emit_failover_event swallows tracker exceptions."""
        tracker = MagicMock()
        tracker.track_collaboration_event.side_effect = RuntimeError("db error")

        data = FailoverEventData(
            from_provider="openai",
            to_provider="anthropic",
            failover_sequence=[],
            total_attempts=1,
        )
        result = emit_failover_event(tracker, "stage-123", data)
        assert result is None
