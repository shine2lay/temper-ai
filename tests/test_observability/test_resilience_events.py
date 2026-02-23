"""Tests for src/observability/resilience_events.py.

Covers dataclass creation, emit helpers with mock trackers, and structured logging.
"""

from __future__ import annotations

import logging
from unittest.mock import Mock

from temper_ai.observability.resilience_events import (
    EVENT_TYPE_CIRCUIT_BREAKER,
    EVENT_TYPE_FALLBACK,
    EVENT_TYPE_RETRY,
    RETRY_OUTCOME_EXHAUSTED,
    RETRY_OUTCOME_FAILED,
    RETRY_OUTCOME_SUCCESS,
    CircuitBreakerEventData,
    FallbackEventData,
    RetryEventData,
    emit_circuit_breaker_event,
    emit_fallback_event,
    emit_retry_event,
)


class TestRetryEventData:
    """Test RetryEventData dataclass."""

    def test_create_basic(self):
        event = RetryEventData(
            attempt_number=1,
            max_retries=3,
            agent_name="agent-1",
            stage_name="analysis",
            outcome=RETRY_OUTCOME_SUCCESS,
        )
        assert event.attempt_number == 1
        assert event.max_retries == 3
        assert event.agent_name == "agent-1"
        assert event.stage_name == "analysis"
        assert event.outcome == RETRY_OUTCOME_SUCCESS
        assert event.error_type is None
        assert event.is_transient is None
        assert event.backoff_delay_seconds is None

    def test_create_with_all_fields(self):
        event = RetryEventData(
            attempt_number=2,
            max_retries=5,
            agent_name="agent-2",
            stage_name="review",
            outcome=RETRY_OUTCOME_FAILED,
            error_type="llm_timeout",
            is_transient=True,
            backoff_delay_seconds=4.0,
        )
        assert event.error_type == "llm_timeout"
        assert event.is_transient is True
        assert event.backoff_delay_seconds == 4.0

    def test_outcome_exhausted(self):
        event = RetryEventData(
            attempt_number=3,
            max_retries=3,
            agent_name="agent-1",
            stage_name="stage-a",
            outcome=RETRY_OUTCOME_EXHAUSTED,
        )
        assert event.outcome == RETRY_OUTCOME_EXHAUSTED


class TestFallbackEventData:
    """Test FallbackEventData dataclass."""

    def test_create_basic(self):
        event = FallbackEventData(
            from_mode="parallel",
            to_mode="sequential",
            reason="disagreement_threshold_exceeded",
            stage_name="analysis",
        )
        assert event.from_mode == "parallel"
        assert event.to_mode == "sequential"
        assert event.reason == "disagreement_threshold_exceeded"
        assert event.stage_name == "analysis"
        assert event.disagreement_rate is None
        assert event.threshold is None
        assert event.agents is None
        assert event.error_message is None

    def test_create_with_all_fields(self):
        event = FallbackEventData(
            from_mode="parallel",
            to_mode="sequential",
            reason="disagreement_threshold_exceeded",
            stage_name="review",
            disagreement_rate=0.6,
            threshold=0.5,
            agents=["agent-1", "agent-2"],
            error_message=None,
        )
        assert event.disagreement_rate == 0.6
        assert event.threshold == 0.5
        assert event.agents == ["agent-1", "agent-2"]

    def test_create_with_error(self):
        event = FallbackEventData(
            from_mode="parallel",
            to_mode="sequential",
            reason="parallel_execution_failed",
            stage_name="stage-x",
            error_message="KeyError: missing key",
        )
        assert event.error_message == "KeyError: missing key"


class TestCircuitBreakerEventData:
    """Test CircuitBreakerEventData dataclass."""

    def test_create_basic(self):
        event = CircuitBreakerEventData(
            breaker_name="llm-breaker",
            old_state="closed",
            new_state="open",
        )
        assert event.breaker_name == "llm-breaker"
        assert event.old_state == "closed"
        assert event.new_state == "open"
        assert event.failure_count == 0
        assert event.success_count == 0

    def test_create_with_counts(self):
        event = CircuitBreakerEventData(
            breaker_name="safety-breaker",
            old_state="half_open",
            new_state="closed",
            failure_count=0,
            success_count=2,
        )
        assert event.failure_count == 0
        assert event.success_count == 2


class TestEmitRetryEvent:
    """Test emit_retry_event helper."""

    def test_emit_with_tracker(self):
        tracker = Mock()
        tracker.track_collaboration_event = Mock()

        event_data = RetryEventData(
            attempt_number=1,
            max_retries=3,
            agent_name="agent-1",
            stage_name="analysis",
            outcome=RETRY_OUTCOME_SUCCESS,
        )

        emit_retry_event(tracker, "stage-123", event_data)

        tracker.track_collaboration_event.assert_called_once()
        collab_data = tracker.track_collaboration_event.call_args[0][0]
        assert collab_data.event_type == EVENT_TYPE_RETRY
        assert collab_data.stage_id == "stage-123"
        assert collab_data.event_data["agent_name"] == "agent-1"
        assert collab_data.event_data["outcome"] == RETRY_OUTCOME_SUCCESS

    def test_emit_without_tracker(self, caplog):
        """Should not raise when tracker is None."""
        event_data = RetryEventData(
            attempt_number=1,
            max_retries=3,
            agent_name="agent-1",
            stage_name="analysis",
            outcome=RETRY_OUTCOME_FAILED,
        )

        with caplog.at_level(logging.INFO):
            emit_retry_event(None, "stage-123", event_data)

        assert "Retry event" in caplog.text

    def test_emit_tracker_without_method(self, caplog):
        """Should not raise when tracker lacks track_collaboration_event."""
        tracker = object()  # no track_collaboration_event

        event_data = RetryEventData(
            attempt_number=1,
            max_retries=3,
            agent_name="agent-1",
            stage_name="analysis",
            outcome=RETRY_OUTCOME_SUCCESS,
        )

        with caplog.at_level(logging.INFO):
            emit_retry_event(tracker, "stage-123", event_data)

        assert "Retry event" in caplog.text

    def test_emit_logs_structured_data(self, caplog):
        tracker = Mock()
        tracker.track_collaboration_event = Mock()

        event_data = RetryEventData(
            attempt_number=2,
            max_retries=5,
            agent_name="researcher",
            stage_name="review",
            outcome=RETRY_OUTCOME_EXHAUSTED,
            error_type="llm_timeout",
            is_transient=True,
            backoff_delay_seconds=8.0,
        )

        with caplog.at_level(logging.INFO):
            emit_retry_event(tracker, "stage-456", event_data)

        assert "researcher" in caplog.text
        assert "review" in caplog.text
        assert "2/5" in caplog.text
        assert RETRY_OUTCOME_EXHAUSTED in caplog.text

    def test_emit_tracker_exception_handled(self):
        """Tracker failures should be silently caught."""
        tracker = Mock()
        tracker.track_collaboration_event.side_effect = RuntimeError("boom")

        event_data = RetryEventData(
            attempt_number=1,
            max_retries=3,
            agent_name="agent-1",
            stage_name="analysis",
            outcome=RETRY_OUTCOME_FAILED,
        )

        # Must not raise — exception should be swallowed
        emit_retry_event(tracker, "stage-123", event_data)
        # Verify the tracker method was actually called (and raised)
        tracker.track_collaboration_event.assert_called_once()


class TestEmitFallbackEvent:
    """Test emit_fallback_event helper."""

    def test_emit_with_tracker(self):
        tracker = Mock()
        tracker.track_collaboration_event = Mock()

        event_data = FallbackEventData(
            from_mode="parallel",
            to_mode="sequential",
            reason="disagreement_threshold_exceeded",
            stage_name="analysis",
            disagreement_rate=0.7,
            threshold=0.5,
            agents=["agent-1", "agent-2"],
        )

        emit_fallback_event(tracker, "stage-123", event_data)

        tracker.track_collaboration_event.assert_called_once()
        collab_data = tracker.track_collaboration_event.call_args[0][0]
        assert collab_data.event_type == EVENT_TYPE_FALLBACK
        assert collab_data.stage_id == "stage-123"
        assert collab_data.event_data["from_mode"] == "parallel"
        assert collab_data.event_data["to_mode"] == "sequential"

    def test_emit_without_tracker(self, caplog):
        event_data = FallbackEventData(
            from_mode="parallel",
            to_mode="sequential",
            reason="error",
            stage_name="stage-a",
        )

        with caplog.at_level(logging.INFO):
            emit_fallback_event(None, "stage-123", event_data)

        assert "Fallback event" in caplog.text

    def test_emit_logs_structured_data(self, caplog):
        tracker = Mock()
        tracker.track_collaboration_event = Mock()

        event_data = FallbackEventData(
            from_mode="parallel",
            to_mode="sequential",
            reason="parallel_execution_failed",
            stage_name="review",
            error_message="KeyError: x",
        )

        with caplog.at_level(logging.INFO):
            emit_fallback_event(tracker, "stage-789", event_data)

        assert "parallel" in caplog.text
        assert "sequential" in caplog.text
        assert "parallel_execution_failed" in caplog.text


class TestEmitCircuitBreakerEvent:
    """Test emit_circuit_breaker_event helper."""

    def test_emit_with_callback(self):
        callback = Mock()

        event_data = CircuitBreakerEventData(
            breaker_name="llm-breaker",
            old_state="closed",
            new_state="open",
            failure_count=5,
        )

        emit_circuit_breaker_event(callback, event_data)

        callback.assert_called_once_with(event_data)

    def test_emit_without_callback(self, caplog):
        event_data = CircuitBreakerEventData(
            breaker_name="test-breaker",
            old_state="open",
            new_state="half_open",
        )

        with caplog.at_level(logging.INFO):
            emit_circuit_breaker_event(None, event_data)

        assert "Circuit breaker event" in caplog.text
        assert "test-breaker" in caplog.text

    def test_emit_callback_exception_handled(self):
        callback = Mock(side_effect=RuntimeError("callback error"))

        event_data = CircuitBreakerEventData(
            breaker_name="llm-breaker",
            old_state="closed",
            new_state="open",
        )

        # Must not raise — exception should be swallowed
        emit_circuit_breaker_event(callback, event_data)
        # Verify the callback was actually called (and raised)
        callback.assert_called_once()

    def test_emit_logs_state_transition(self, caplog):
        callback = Mock()

        event_data = CircuitBreakerEventData(
            breaker_name="safety-breaker",
            old_state="half_open",
            new_state="closed",
            failure_count=0,
            success_count=2,
        )

        with caplog.at_level(logging.INFO):
            emit_circuit_breaker_event(callback, event_data)

        assert "safety-breaker" in caplog.text
        assert "half_open" in caplog.text
        assert "closed" in caplog.text


class TestEventTypeConstants:
    """Test event type constant values."""

    def test_retry_event_type(self):
        assert EVENT_TYPE_RETRY == "resilience_retry"

    def test_fallback_event_type(self):
        assert EVENT_TYPE_FALLBACK == "resilience_fallback"

    def test_circuit_breaker_event_type(self):
        assert EVENT_TYPE_CIRCUIT_BREAKER == "resilience_circuit_breaker"

    def test_retry_outcome_constants(self):
        assert RETRY_OUTCOME_SUCCESS == "success"
        assert RETRY_OUTCOME_FAILED == "failed"
        assert RETRY_OUTCOME_EXHAUSTED == "exhausted"
