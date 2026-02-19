"""Integration tests for retry and fallback observability events.

Verifies that retry_agent_with_backoff emits structured retry events,
and that the adaptive executor emits fallback events through the
resilience_events module.
"""
from __future__ import annotations

import threading
from unittest.mock import Mock, patch, MagicMock

import pytest

from temper_ai.observability.resilience_events import (
    EVENT_TYPE_FALLBACK,
    EVENT_TYPE_RETRY,
    RETRY_OUTCOME_EXHAUSTED,
    RETRY_OUTCOME_FAILED,
    RETRY_OUTCOME_SUCCESS,
)
from temper_ai.stage.executors._sequential_helpers import (
    AgentExecutionContext,
    retry_agent_with_backoff,
)
from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.shared.utils.exceptions import ErrorCode


def _make_ctx(tracker=None):
    """Build a minimal AgentExecutionContext for testing."""
    executor = Mock()
    executor.shutdown_event = threading.Event()
    # shutdown_event.wait returns False (not shutting down) immediately
    executor.shutdown_event.wait = Mock(return_value=False)

    return AgentExecutionContext(
        executor=executor,
        stage_id="stage-001",
        stage_name="test-stage",
        workflow_id="wf-001",
        state={},
        tracker=tracker,
        config_loader=Mock(),
    )


def _make_success_result(agent_name="agent-1"):
    """Build a successful agent result."""
    return {
        StateKeys.AGENT_NAME: agent_name,
        StateKeys.STATUS: "success",
        StateKeys.OUTPUT_DATA: {"response": "ok"},
        StateKeys.METRICS: {StateKeys.RETRIES: 0},
    }


def _make_failure_result(agent_name="agent-1", error_type=None):
    """Build a failed agent result."""
    et = error_type or ErrorCode.LLM_TIMEOUT.value
    return {
        StateKeys.AGENT_NAME: agent_name,
        StateKeys.STATUS: "failed",
        StateKeys.OUTPUT_DATA: {
            StateKeys.ERROR: "timeout",
            StateKeys.ERROR_TYPE: et,
        },
        StateKeys.METRICS: {StateKeys.RETRIES: 0},
    }


class TestRetryEmitsEvents:
    """Test that retry_agent_with_backoff emits retry events."""

    @patch("temper_ai.stage.executors._sequential_retry._execute_retry_attempt")
    def test_success_on_first_retry_emits_event(self, mock_attempt):
        """When retry succeeds, a success event should be emitted."""
        tracker = Mock()
        tracker.track_collaboration_event = Mock()
        ctx = _make_ctx(tracker=tracker)

        success_result = _make_success_result()
        mock_attempt.return_value = (success_result, True)

        result = retry_agent_with_backoff(ctx, "agent_ref", {}, 3, "agent-1")

        assert result[StateKeys.STATUS] == "success"
        tracker.track_collaboration_event.assert_called_once()
        collab_data = tracker.track_collaboration_event.call_args[0][0]
        assert collab_data.event_type == EVENT_TYPE_RETRY
        assert collab_data.event_data["outcome"] == RETRY_OUTCOME_SUCCESS
        assert collab_data.event_data["attempt_number"] == 1

    @patch("temper_ai.stage.executors._sequential_retry._execute_retry_attempt")
    def test_permanent_error_emits_failed_event(self, mock_attempt):
        """When a permanent error stops retries, a failed event should be emitted."""
        tracker = Mock()
        tracker.track_collaboration_event = Mock()
        ctx = _make_ctx(tracker=tracker)

        # Permanent error - should_stop=True
        fail_result = _make_failure_result(error_type="config_validation_error")
        mock_attempt.return_value = (fail_result, True)

        result = retry_agent_with_backoff(ctx, "agent_ref", {}, 3, "agent-1")

        assert result[StateKeys.STATUS] == "failed"
        tracker.track_collaboration_event.assert_called_once()
        collab_data = tracker.track_collaboration_event.call_args[0][0]
        assert collab_data.event_data["outcome"] == RETRY_OUTCOME_FAILED

    @patch("temper_ai.stage.executors._sequential_retry._execute_retry_attempt")
    def test_exhausted_retries_emits_exhausted_event(self, mock_attempt):
        """When all retries are exhausted, an exhausted event should be emitted."""
        tracker = Mock()
        tracker.track_collaboration_event = Mock()
        ctx = _make_ctx(tracker=tracker)

        # All attempts fail with transient errors (should_stop=False)
        fail_result = _make_failure_result(error_type=ErrorCode.LLM_TIMEOUT.value)
        mock_attempt.return_value = (fail_result, False)

        result = retry_agent_with_backoff(ctx, "agent_ref", {}, 2, "agent-1")

        assert result[StateKeys.STATUS] == "failed"
        tracker.track_collaboration_event.assert_called_once()
        collab_data = tracker.track_collaboration_event.call_args[0][0]
        assert collab_data.event_data["outcome"] == RETRY_OUTCOME_EXHAUSTED
        assert collab_data.event_data["attempt_number"] == 2
        assert collab_data.event_data["max_retries"] == 2

    @patch("temper_ai.stage.executors._sequential_retry._execute_retry_attempt")
    def test_no_tracker_does_not_raise(self, mock_attempt):
        """Retry should work fine without a tracker."""
        ctx = _make_ctx(tracker=None)

        success_result = _make_success_result()
        mock_attempt.return_value = (success_result, True)

        result = retry_agent_with_backoff(ctx, "agent_ref", {}, 3, "agent-1")
        assert result[StateKeys.STATUS] == "success"

    @patch("temper_ai.stage.executors._sequential_retry._execute_retry_attempt")
    def test_retry_event_includes_stage_info(self, mock_attempt):
        """Retry events should include stage_name and stage_id."""
        tracker = Mock()
        tracker.track_collaboration_event = Mock()
        ctx = _make_ctx(tracker=tracker)

        success_result = _make_success_result()
        mock_attempt.return_value = (success_result, True)

        retry_agent_with_backoff(ctx, "agent_ref", {}, 3, "my-agent")

        collab_data = tracker.track_collaboration_event.call_args[0][0]
        assert collab_data.stage_id == "stage-001"
        assert collab_data.event_data["stage_name"] == "test-stage"
        assert collab_data.event_data["agent_name"] == "my-agent"


class TestAdaptiveFallbackEvents:
    """Test that adaptive executor emits fallback events."""

    def test_fallback_on_disagreement(self):
        """When disagreement exceeds threshold, a fallback event should be emitted."""
        from temper_ai.stage.executors.adaptive import (
            ParallelSwitchCheckParams,
            _execute_parallel_with_switch_check,
        )

        tracker = Mock()
        tracker.track_collaboration_event = Mock()

        parallel_executor = Mock()
        parallel_executor.execute_stage.return_value = {
            "stage_outputs": {
                "analysis": {
                    "synthesis": {"votes": {"yes": 1, "no": 1}},
                    "agent_outputs": {"agent-1": {}, "agent-2": {}},
                }
            }
        }

        params = ParallelSwitchCheckParams(
            parallel_executor=parallel_executor,
            stage_name="analysis",
            stage_config={},
            state={},
            config_loader=Mock(),
            tool_registry=None,
            disagreement_threshold=0.3,
            tracker=tracker,
        )

        _, should_switch, disagreement_rate, _ = _execute_parallel_with_switch_check(params)

        assert should_switch is True
        assert disagreement_rate == 0.5
        tracker.track_collaboration_event.assert_called_once()
        collab_data = tracker.track_collaboration_event.call_args[0][0]
        assert collab_data.event_type == EVENT_TYPE_FALLBACK
        assert collab_data.event_data["from_mode"] == "parallel"
        assert collab_data.event_data["to_mode"] == "sequential"

    def test_no_fallback_when_below_threshold(self):
        """No fallback event when disagreement is below threshold."""
        from temper_ai.stage.executors.adaptive import (
            ParallelSwitchCheckParams,
            _execute_parallel_with_switch_check,
        )

        tracker = Mock()
        tracker.track_collaboration_event = Mock()

        parallel_executor = Mock()
        parallel_executor.execute_stage.return_value = {
            "stage_outputs": {
                "analysis": {
                    "synthesis": {"votes": {"yes": 3}},
                    "agent_outputs": {"agent-1": {}, "agent-2": {}, "agent-3": {}},
                }
            }
        }

        params = ParallelSwitchCheckParams(
            parallel_executor=parallel_executor,
            stage_name="analysis",
            stage_config={},
            state={},
            config_loader=Mock(),
            tool_registry=None,
            disagreement_threshold=0.5,
            tracker=tracker,
        )

        _, should_switch, _, _ = _execute_parallel_with_switch_check(params)

        assert should_switch is False
        tracker.track_collaboration_event.assert_not_called()

    def test_fallback_on_error(self):
        """When parallel execution fails, a fallback event should be emitted."""
        from temper_ai.stage.executors.adaptive import (
            AdaptiveStageExecutor,
            ParallelErrorHandlerParams,
        )

        tracker = Mock()
        tracker.track_collaboration_event = Mock()

        executor = AdaptiveStageExecutor()
        executor.sequential_executor = Mock()
        executor.sequential_executor.execute_stage.return_value = {
            "stage_outputs": {"stage-x": {"result": "ok"}}
        }

        params = ParallelErrorHandlerParams(
            e=KeyError("missing"),
            stage_name="stage-x",
            stage_config={},
            state={"stage_outputs": {}},
            config_loader=Mock(),
            tool_registry=None,
            disagreement_threshold=0.5,
            tracker=tracker,
        )

        result = executor._handle_parallel_error(params)

        assert "stage-x" in result["stage_outputs"]
        tracker.track_collaboration_event.assert_called_once()
        collab_data = tracker.track_collaboration_event.call_args[0][0]
        assert collab_data.event_type == EVENT_TYPE_FALLBACK
        assert collab_data.event_data["reason"] == "parallel_execution_failed"


class TestCircuitBreakerObservability:
    """Test circuit breaker observability callbacks."""

    def test_callback_fired_on_state_transition(self):
        """Observability callback should fire when state transitions."""
        from temper_ai.shared.core.circuit_breaker import CircuitBreaker

        callback = Mock()
        breaker = CircuitBreaker(
            name="test-breaker",
            failure_threshold=2,
            observability_callback=callback,
        )

        # Trigger enough failures to open
        breaker.record_failure(RuntimeError("err1"))
        breaker.record_failure(RuntimeError("err2"))

        assert callback.call_count >= 1
        event_data = callback.call_args[0][0]
        assert event_data.breaker_name == "test-breaker"
        assert event_data.new_state == "open"

    def test_add_observability_callback(self):
        """add_observability_callback should register additional callbacks."""
        from temper_ai.shared.core.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker(name="test-breaker", failure_threshold=2)
        callback = Mock()
        breaker.add_observability_callback(callback)

        assert callback in breaker._observability_callbacks

    def test_no_callback_no_error(self):
        """No observability callbacks should not cause errors."""
        from temper_ai.shared.core.circuit_breaker import CircuitBreaker

        breaker = CircuitBreaker(name="test-breaker", failure_threshold=2)

        # Should not raise
        breaker.record_failure(RuntimeError("err1"))
        breaker.record_failure(RuntimeError("err2"))

        assert breaker._observability_callbacks == []
