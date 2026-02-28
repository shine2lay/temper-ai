"""Extended tests for temper_ai/stage/executors/_sequential_retry.py.

Covers uncovered paths:
- _execute_retry_attempt (success / permanent error / transient)
- retry_agent_with_backoff (shutdown / exhausted / success / permanent stop)
- _emit_retry_outcome (success/failed outcomes)
- _emit_retry_exhausted (with/without result)
- _handle_retry_policy (transient with retries / permanent / max_retries=0)
- _handle_agent_failure (all policy branches)
- _store_failure_result (success/failed result)
- _process_agent_failure (break/continue/store)
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.shared.utils.exceptions import ErrorCode
from temper_ai.stage.executors._sequential_helpers import (
    AgentExecutionContext,
    AgentResultAccumulators,
)
from temper_ai.stage.executors._sequential_retry import (
    _emit_retry_exhausted,
    _emit_retry_outcome,
    _execute_retry_attempt,
    _handle_agent_failure,
    _handle_retry_policy,
    _process_agent_failure,
    _store_failure_result,
    is_transient_error,
    retry_agent_with_backoff,
)
from temper_ai.stage.executors.state_keys import StateKeys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(stage_name="stage1", tracker=None, shutdown_event=None):
    executor = MagicMock()
    executor.shutdown_event = shutdown_event or threading.Event()
    ctx = AgentExecutionContext(
        executor=executor,
        stage_id="sid-1",
        stage_name=stage_name,
        workflow_id="wf-1",
        state={},
        tracker=tracker,
        config_loader=MagicMock(),
    )
    return ctx


def _make_success_result(agent_name="agent_a"):
    return {
        StateKeys.AGENT_NAME: agent_name,
        StateKeys.STATUS: "success",
        StateKeys.OUTPUT_DATA: {StateKeys.OUTPUT: "out"},
        StateKeys.METRICS: {
            StateKeys.TOKENS: 10,
            StateKeys.COST_USD: 0.01,
            StateKeys.DURATION_SECONDS: 0.5,
            StateKeys.TOOL_CALLS: 0,
        },
    }


def _make_failure_result(agent_name="agent_a", error_type="llm_timeout"):
    return {
        StateKeys.AGENT_NAME: agent_name,
        StateKeys.STATUS: "failed",
        StateKeys.OUTPUT_DATA: {
            StateKeys.OUTPUT: "",
            StateKeys.ERROR: "something failed",
            StateKeys.ERROR_TYPE: error_type,
        },
        StateKeys.METRICS: {
            StateKeys.TOKENS: 0,
            StateKeys.COST_USD: 0.0,
            StateKeys.DURATION_SECONDS: 0.5,
            StateKeys.TOOL_CALLS: 0,
        },
    }


def _make_error_handling(policy="continue_with_remaining", max_retries=0):
    eh = MagicMock()
    eh.on_agent_failure = policy
    eh.max_agent_retries = max_retries
    return eh


def _make_accum():
    return AgentResultAccumulators(outputs={}, statuses={}, metrics={})


# ---------------------------------------------------------------------------
# is_transient_error
# ---------------------------------------------------------------------------


class TestIsTransientError:
    def test_llm_timeout_is_transient(self):
        assert is_transient_error(ErrorCode.LLM_TIMEOUT.value)

    def test_llm_rate_limit_is_transient(self):
        assert is_transient_error(ErrorCode.LLM_RATE_LIMIT.value)

    def test_system_timeout_is_transient(self):
        assert is_transient_error(ErrorCode.SYSTEM_TIMEOUT.value)

    def test_unknown_error_is_not_transient(self):
        assert not is_transient_error("unknown_error")

    def test_empty_string_is_not_transient(self):
        assert not is_transient_error("")

    def test_validation_error_is_not_transient(self):
        assert not is_transient_error(ErrorCode.VALIDATION_ERROR.value)


# ---------------------------------------------------------------------------
# _execute_retry_attempt
# ---------------------------------------------------------------------------


class TestExecuteRetryAttempt:
    def test_returns_true_should_stop_on_success(self):
        ctx = _make_ctx()
        success = _make_success_result()
        with patch(
            "temper_ai.stage.executors._sequential_helpers.execute_agent",
            return_value=success,
        ):
            result, should_stop = _execute_retry_attempt(
                ctx, "agent_a", {}, "agent_a", 1, 3
            )
        assert should_stop is True
        assert result[StateKeys.STATUS] == "success"
        assert result[StateKeys.METRICS][StateKeys.RETRIES] == 1

    def test_returns_true_should_stop_on_permanent_error(self):
        ctx = _make_ctx()
        failure = _make_failure_result(error_type=ErrorCode.VALIDATION_ERROR.value)
        with patch(
            "temper_ai.stage.executors._sequential_helpers.execute_agent",
            return_value=failure,
        ):
            result, should_stop = _execute_retry_attempt(
                ctx, "agent_a", {}, "agent_a", 1, 3
            )
        assert should_stop is True
        assert result[StateKeys.METRICS][StateKeys.RETRIES] == 1

    def test_returns_false_should_stop_on_transient_error(self):
        ctx = _make_ctx()
        failure = _make_failure_result(error_type=ErrorCode.LLM_TIMEOUT.value)
        with patch(
            "temper_ai.stage.executors._sequential_helpers.execute_agent",
            return_value=failure,
        ):
            result, should_stop = _execute_retry_attempt(
                ctx, "agent_a", {}, "agent_a", 1, 3
            )
        assert should_stop is False


# ---------------------------------------------------------------------------
# _emit_retry_outcome
# ---------------------------------------------------------------------------


class TestEmitRetryOutcome:
    def test_emits_success_outcome_on_success(self):
        ctx = _make_ctx()
        result = _make_success_result()
        with patch(
            "temper_ai.stage.executors._sequential_retry.emit_retry_event"
        ) as mock_emit:
            _emit_retry_outcome(ctx, result, "agent_a", 1, 3, 0.5)
        mock_emit.assert_called_once()
        event_data = mock_emit.call_args.kwargs["event_data"]
        from temper_ai.observability.resilience_events import RETRY_OUTCOME_SUCCESS

        assert event_data.outcome == RETRY_OUTCOME_SUCCESS

    def test_emits_failed_outcome_on_failure(self):
        ctx = _make_ctx()
        result = _make_failure_result(error_type=ErrorCode.VALIDATION_ERROR.value)
        with patch(
            "temper_ai.stage.executors._sequential_retry.emit_retry_event"
        ) as mock_emit:
            _emit_retry_outcome(ctx, result, "agent_a", 1, 3, 0.5)
        event_data = mock_emit.call_args.kwargs["event_data"]
        from temper_ai.observability.resilience_events import RETRY_OUTCOME_FAILED

        assert event_data.outcome == RETRY_OUTCOME_FAILED


# ---------------------------------------------------------------------------
# _emit_retry_exhausted
# ---------------------------------------------------------------------------


class TestEmitRetryExhausted:
    def test_emits_exhausted_outcome(self):
        ctx = _make_ctx()
        result = _make_failure_result()
        with patch(
            "temper_ai.stage.executors._sequential_retry.emit_retry_event"
        ) as mock_emit:
            _emit_retry_exhausted(ctx, result, "agent_a", 3)
        event_data = mock_emit.call_args.kwargs["event_data"]
        from temper_ai.observability.resilience_events import RETRY_OUTCOME_EXHAUSTED

        assert event_data.outcome == RETRY_OUTCOME_EXHAUSTED

    def test_handles_empty_result(self):
        ctx = _make_ctx()
        with patch(
            "temper_ai.stage.executors._sequential_retry.emit_retry_event"
        ) as mock_emit:
            _emit_retry_exhausted(ctx, {}, "agent_a", 3)
        mock_emit.assert_called_once()
        event_data = mock_emit.call_args.kwargs["event_data"]
        assert event_data.error_type is None


# ---------------------------------------------------------------------------
# retry_agent_with_backoff
# ---------------------------------------------------------------------------


class TestRetryAgentWithBackoff:
    def test_succeeds_on_first_retry(self):
        ctx = _make_ctx()
        success = _make_success_result()
        with patch(
            "temper_ai.stage.executors._sequential_retry._execute_retry_attempt",
            return_value=(success, True),
        ):
            with patch(
                "temper_ai.stage.executors._sequential_retry._emit_retry_outcome"
            ):
                result = retry_agent_with_backoff(ctx, "agent_a", {}, 3, "agent_a")
        assert result[StateKeys.STATUS] == "success"

    def test_raises_keyboard_interrupt_on_shutdown(self):
        shutdown = threading.Event()
        shutdown.set()  # Pre-set to simulate shutdown
        ctx = _make_ctx(shutdown_event=shutdown)

        with pytest.raises(KeyboardInterrupt):
            retry_agent_with_backoff(ctx, "agent_a", {}, 1, "agent_a")

    def test_exhausted_emits_exhausted_event(self):
        ctx = _make_ctx()
        failure = _make_failure_result(error_type=ErrorCode.LLM_TIMEOUT.value)
        # _execute_retry_attempt always returns (failure, False) — never stops
        with (
            patch(
                "temper_ai.stage.executors._sequential_retry._execute_retry_attempt",
                return_value=(failure, False),
            ),
            patch(
                "temper_ai.stage.executors._sequential_retry._emit_retry_exhausted"
            ) as mock_exhausted,
        ):
            retry_agent_with_backoff(ctx, "agent_a", {}, 1, "agent_a")
        mock_exhausted.assert_called_once()

    def test_permanent_error_stops_early(self):
        ctx = _make_ctx()
        permanent_failure = _make_failure_result(
            error_type=ErrorCode.VALIDATION_ERROR.value
        )
        with (
            patch(
                "temper_ai.stage.executors._sequential_retry._execute_retry_attempt",
                return_value=(permanent_failure, True),
            ),
            patch("temper_ai.stage.executors._sequential_retry._emit_retry_outcome"),
        ):
            result = retry_agent_with_backoff(ctx, "agent_a", {}, 3, "agent_a")
        assert result[StateKeys.STATUS] == "failed"


# ---------------------------------------------------------------------------
# _handle_retry_policy
# ---------------------------------------------------------------------------


class TestHandleRetryPolicy:
    def test_transient_error_with_retries_calls_backoff(self):
        ctx = _make_ctx()
        result = _make_failure_result(error_type=ErrorCode.LLM_TIMEOUT.value)
        error_handling = _make_error_handling(max_retries=2)
        accum = _make_accum()
        retry_result = _make_success_result()

        with patch(
            "temper_ai.stage.executors._sequential_retry.retry_agent_with_backoff",
            return_value=retry_result,
        ) as mock_retry:
            action, stored = _handle_retry_policy(
                "agent_a", result, error_handling, ctx, "agent_a", accum
            )
        assert action == "store"
        mock_retry.assert_called_once()

    def test_permanent_error_stores_without_retry(self):
        ctx = _make_ctx()
        result = _make_failure_result(error_type=ErrorCode.VALIDATION_ERROR.value)
        error_handling = _make_error_handling(max_retries=3)
        accum = _make_accum()

        action, stored = _handle_retry_policy(
            "agent_a", result, error_handling, ctx, "agent_a", accum
        )
        assert action == "store"

    def test_transient_with_zero_retries_stores(self):
        ctx = _make_ctx()
        result = _make_failure_result(error_type=ErrorCode.LLM_TIMEOUT.value)
        error_handling = _make_error_handling(max_retries=0)
        accum = _make_accum()

        action, stored = _handle_retry_policy(
            "agent_a", result, error_handling, ctx, "agent_a", accum
        )
        assert action == "store"


# ---------------------------------------------------------------------------
# _handle_agent_failure
# ---------------------------------------------------------------------------


class TestHandleAgentFailure:
    def test_halt_stage_returns_break(self):
        ctx = _make_ctx()
        result = _make_failure_result()
        error_handling = _make_error_handling(policy="halt_stage")
        accum = _make_accum()

        action, stored = _handle_agent_failure(
            "agent_a", result, error_handling, ctx, "agent_a", accum
        )
        assert action == "break"

    def test_skip_agent_returns_continue(self):
        ctx = _make_ctx()
        result = _make_failure_result()
        error_handling = _make_error_handling(policy="skip_agent")
        accum = _make_accum()

        action, stored = _handle_agent_failure(
            "agent_a", result, error_handling, ctx, "agent_a", accum
        )
        assert action == "continue"

    def test_retry_agent_delegates_to_handle_retry(self):
        ctx = _make_ctx()
        result = _make_failure_result(error_type=ErrorCode.LLM_TIMEOUT.value)
        error_handling = _make_error_handling(policy="retry_agent", max_retries=2)
        accum = _make_accum()
        retry_result = _make_success_result()

        with patch(
            "temper_ai.stage.executors._sequential_retry.retry_agent_with_backoff",
            return_value=retry_result,
        ):
            action, stored = _handle_agent_failure(
                "agent_a", result, error_handling, ctx, "agent_a", accum
            )
        assert action == "store"

    def test_continue_with_remaining_returns_store(self):
        ctx = _make_ctx()
        result = _make_failure_result()
        error_handling = _make_error_handling(policy="continue_with_remaining")
        accum = _make_accum()

        action, stored = _handle_agent_failure(
            "agent_a", result, error_handling, ctx, "agent_a", accum
        )
        assert action == "store"


# ---------------------------------------------------------------------------
# _store_failure_result
# ---------------------------------------------------------------------------


class TestStoreFailureResult:
    def test_stores_success_result_as_success_status(self):
        result = _make_success_result("agent_a")
        statuses: dict = {}
        outputs: dict = {}
        metrics: dict = {}
        _store_failure_result(result, statuses, outputs, metrics)
        assert statuses["agent_a"] == "success"

    def test_stores_failed_result_as_failed_status(self):
        result = _make_failure_result("agent_b")
        statuses: dict = {}
        outputs: dict = {}
        metrics: dict = {}
        _store_failure_result(result, statuses, outputs, metrics)
        assert statuses["agent_b"][StateKeys.STATUS] == "failed"

    def test_stores_output_data(self):
        result = _make_failure_result("agent_c")
        outputs: dict = {}
        _store_failure_result(result, {}, outputs, {})
        assert "agent_c" in outputs

    def test_stores_metrics(self):
        result = _make_success_result("agent_d")
        metrics: dict = {}
        _store_failure_result(result, {}, {}, metrics)
        assert "agent_d" in metrics


# ---------------------------------------------------------------------------
# _process_agent_failure
# ---------------------------------------------------------------------------


class TestProcessAgentFailure:
    def test_returns_break_on_halt_stage(self):
        ctx = _make_ctx()
        result = _make_failure_result()
        error_handling = _make_error_handling(policy="halt_stage")
        accum = _make_accum()

        loop_action = _process_agent_failure(
            "agent_a", result, error_handling, ctx, "agent_a", accum
        )
        assert loop_action == "break"

    def test_returns_continue_on_skip_agent(self):
        ctx = _make_ctx()
        result = _make_failure_result()
        error_handling = _make_error_handling(policy="skip_agent")
        accum = _make_accum()

        loop_action = _process_agent_failure(
            "agent_a", result, error_handling, ctx, "agent_a", accum
        )
        assert loop_action == "continue"

    def test_returns_none_on_store(self):
        ctx = _make_ctx()
        result = _make_failure_result()
        error_handling = _make_error_handling(policy="continue_with_remaining")
        accum = _make_accum()

        loop_action = _process_agent_failure(
            "agent_a", result, error_handling, ctx, "agent_a", accum
        )
        assert loop_action is None

    def test_status_stored_in_accum_on_failure(self):
        ctx = _make_ctx()
        result = _make_failure_result()
        error_handling = _make_error_handling(policy="continue_with_remaining")
        accum = _make_accum()

        _process_agent_failure("agent_a", result, error_handling, ctx, "agent_a", accum)
        assert accum.statuses["agent_a"][StateKeys.STATUS] == "failed"
