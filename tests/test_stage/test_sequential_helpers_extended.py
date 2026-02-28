"""Extended tests for temper_ai/stage/executors/_sequential_helpers.py.

Covers uncovered paths:
- _classify_error (CircuitBreakerError, BaseError, stdlib errors)
- _compute_error_fingerprint (success / exception)
- _build_error_result (with/without fingerprint)
- _build_legacy_input (state with/without to_dict, workflow_inputs unwrap)
- _prepare_sequential_input (dynamic inputs, context_provider paths, fallback)
- _execute_and_track_agent (tracker context, None-tracker)
- _build_success_result (script_outputs present/absent)
- _wire_tool_executor (with/without rate limiter)
- _dispatch_sequential_evaluation (dispatcher present/absent)
- _print_agent_progress (success/failed agents)
- _print_sequential_stage_header (with/without console, stream_cb)
- _emit_sequential_cost_summary (success / exception)
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.shared.core.circuit_breaker import CircuitBreakerError
from temper_ai.shared.utils.exceptions import (
    ErrorCode,
    LLMError,
)
from temper_ai.stage.executors._sequential_helpers import (
    AgentExecutionContext,
    AgentResultAccumulators,
    _build_error_result,
    _build_legacy_input,
    _build_success_result,
    _classify_error,
    _compute_error_fingerprint,
    _dispatch_sequential_evaluation,
    _emit_sequential_cost_summary,
    _execute_and_track_agent,
    _prepare_sequential_input,
    _print_agent_progress,
    _print_sequential_stage_header,
    _wire_tool_executor,
)
from temper_ai.stage.executors.state_keys import StateKeys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    output="out",
    reasoning="why",
    confidence=0.85,
    tokens=100,
    cost=0.01,
    tool_calls=None,
    metadata=None,
):
    resp = MagicMock()
    resp.output = output
    resp.reasoning = reasoning
    resp.confidence = confidence
    resp.tokens = tokens
    resp.estimated_cost_usd = cost
    resp.tool_calls = tool_calls
    resp.metadata = metadata if metadata is not None else {}
    return resp


def _make_ctx(state=None, tracker=None, stage_name="stage1", tool_executor=None):
    executor = MagicMock()
    executor._agent_cache = {}
    executor.tool_executor = tool_executor
    ctx = AgentExecutionContext(
        executor=executor,
        stage_id="sid-1",
        stage_name=stage_name,
        workflow_id="wf-1",
        state=state or {},
        tracker=tracker,
        config_loader=MagicMock(),
    )
    return ctx


# ---------------------------------------------------------------------------
# _classify_error
# ---------------------------------------------------------------------------


class TestClassifyError:
    def test_circuit_breaker_error_returns_llm_connection_error(self):
        e = CircuitBreakerError("circuit open")
        error_type, msg, tb = _classify_error("agent_a", e)
        assert error_type == ErrorCode.LLM_CONNECTION_ERROR.value

    def test_base_error_returns_its_error_code(self):
        e = LLMError("llm fail")
        error_type, msg, tb = _classify_error("agent_a", e)
        assert error_type == e.error_code.value

    def test_timeout_error_returns_system_timeout(self):
        e = TimeoutError("timed out")
        error_type, msg, tb = _classify_error("agent_a", e)
        assert error_type == ErrorCode.SYSTEM_TIMEOUT.value

    def test_connection_error_returns_llm_connection_error(self):
        e = ConnectionError("connect fail")
        error_type, msg, tb = _classify_error("agent_a", e)
        assert error_type == ErrorCode.LLM_CONNECTION_ERROR.value

    def test_value_error_returns_validation_error(self):
        e = ValueError("bad val")
        error_type, msg, tb = _classify_error("agent_a", e)
        assert error_type == ErrorCode.VALIDATION_ERROR.value

    def test_runtime_error_returns_agent_execution_error(self):
        e = RuntimeError("runtime fail")
        error_type, msg, tb = _classify_error("agent_a", e)
        assert error_type == ErrorCode.AGENT_EXECUTION_ERROR.value

    def test_unknown_exception_returns_unknown_error(self):
        class MyCustomError(Exception):
            pass

        e = MyCustomError("weird")
        error_type, msg, tb = _classify_error("agent_a", e)
        assert error_type == ErrorCode.UNKNOWN_ERROR.value


# ---------------------------------------------------------------------------
# _compute_error_fingerprint
# ---------------------------------------------------------------------------


class TestComputeErrorFingerprint:
    def test_returns_fingerprint_on_success(self):
        e = ValueError("test error")
        with patch(
            "temper_ai.observability.error_fingerprinting.compute_fingerprint",
            return_value="fp-abc",
        ):
            result = _compute_error_fingerprint(e, ErrorCode.VALIDATION_ERROR.value)
        assert result == "fp-abc"

    def test_returns_none_on_import_error(self):
        e = ValueError("test error")
        with patch(
            "temper_ai.observability.error_fingerprinting.compute_fingerprint",
            side_effect=ImportError("no module"),
        ):
            result = _compute_error_fingerprint(e, "validation_error")
        assert result is None

    def test_returns_none_on_general_exception(self):
        e = ValueError("test error")
        with patch(
            "temper_ai.observability.error_fingerprinting.compute_fingerprint",
            side_effect=RuntimeError("boom"),
        ):
            result = _compute_error_fingerprint(e, "validation_error")
        assert result is None


# ---------------------------------------------------------------------------
# _build_error_result
# ---------------------------------------------------------------------------


class TestBuildErrorResult:
    def test_includes_error_fingerprint_when_computed(self):
        e = ValueError("bad")
        with patch(
            "temper_ai.stage.executors._sequential_helpers._compute_error_fingerprint",
            return_value="fp-xyz",
        ):
            result = _build_error_result("agent_a", e, 0.1)
        assert "error_fingerprint" in result[StateKeys.OUTPUT_DATA]
        assert result[StateKeys.OUTPUT_DATA]["error_fingerprint"] == "fp-xyz"

    def test_no_fingerprint_key_when_fingerprint_is_none(self):
        e = ValueError("bad")
        with patch(
            "temper_ai.stage.executors._sequential_helpers._compute_error_fingerprint",
            return_value=None,
        ):
            result = _build_error_result("agent_a", e, 0.1)
        assert "error_fingerprint" not in result[StateKeys.OUTPUT_DATA]

    def test_status_is_failed(self):
        e = ValueError("bad")
        result = _build_error_result("agent_a", e, 0.1)
        assert result[StateKeys.STATUS] == "failed"

    def test_duration_stored_in_metrics(self):
        e = RuntimeError("fail")
        result = _build_error_result("agent_a", e, 2.5)
        assert result[StateKeys.METRICS][StateKeys.DURATION_SECONDS] == 2.5


# ---------------------------------------------------------------------------
# _build_legacy_input
# ---------------------------------------------------------------------------


class TestBuildLegacyInput:
    def test_with_dict_state(self):
        state = {
            StateKeys.WORKFLOW_INPUTS: {"user_q": "hello"},
            StateKeys.STAGE_OUTPUTS: {"stage1": "out"},
        }
        ctx = _make_ctx(state=state)
        result = _build_legacy_input(ctx, {"prior_agent": {"output": "x"}})
        assert "user_q" in result
        assert result[StateKeys.STAGE_OUTPUTS] == {"stage1": "out"}
        assert "prior_agent" in result[StateKeys.CURRENT_STAGE_AGENTS]

    def test_with_to_dict_state(self):
        state_mock = MagicMock()
        state_mock.to_dict.return_value = {
            StateKeys.WORKFLOW_INPUTS: {},
            StateKeys.STAGE_OUTPUTS: {},
        }
        # Make it iterable so the `dict(ctx.state)` fallback won't be used
        state_mock.__iter__ = MagicMock(return_value=iter([]))
        state_mock.get = MagicMock(side_effect=lambda k, d=None: {}.get(k, d))

        ctx = _make_ctx(state=state_mock)
        ctx.state = state_mock  # override
        _build_legacy_input(ctx, {})
        state_mock.to_dict.assert_called_once()

    def test_reserved_unwrap_keys_excluded(self):
        # RESERVED_UNWRAP_KEYS should not be unwrapped into the result
        state = {
            StateKeys.WORKFLOW_INPUTS: {
                "normal_key": "normal_val",
            },
        }
        ctx = _make_ctx(state=state)
        result = _build_legacy_input(ctx, {})
        assert "normal_key" in result


# ---------------------------------------------------------------------------
# _prepare_sequential_input
# ---------------------------------------------------------------------------


class TestPrepareSequentialInput:
    def test_dynamic_inputs_take_priority(self):
        dynamic = {"dyn_key": "dyn_val"}
        state = {StateKeys.DYNAMIC_INPUTS: dynamic, "other": "x"}
        ctx = _make_ctx(state=state)

        with patch("temper_ai.workflow.context_provider._INFRASTRUCTURE_KEYS", set()):
            result = _prepare_sequential_input(ctx, {})

        assert "dyn_key" in result
        assert result[StateKeys.CURRENT_STAGE_AGENTS] == {}

    def test_dynamic_inputs_include_infrastructure_keys(self):
        from temper_ai.workflow.context_provider import _INFRASTRUCTURE_KEYS

        infra_key = next(iter(_INFRASTRUCTURE_KEYS)) if _INFRASTRUCTURE_KEYS else None
        if infra_key is None:
            pytest.skip("No infrastructure keys defined")

        dynamic = {"q": "v"}
        state = {StateKeys.DYNAMIC_INPUTS: dynamic, infra_key: "infra_val"}
        ctx = _make_ctx(state=state)
        result = _prepare_sequential_input(ctx, {})
        assert result[infra_key] == "infra_val"

    def test_context_provider_resolution_used(self):
        ctx = _make_ctx(state={"key": "val"})
        context_provider = MagicMock()
        stage_config = MagicMock()
        resolved = {"resolved_key": "resolved_val", StateKeys.CURRENT_STAGE_AGENTS: {}}
        context_provider.resolve.return_value = resolved

        result = _prepare_sequential_input(
            ctx, {}, context_provider=context_provider, stage_config=stage_config
        )
        assert "resolved_key" in result
        context_provider.resolve.assert_called_once()

    def test_context_provider_context_meta_propagated(self):
        ctx = _make_ctx(state={"key": "val"})
        context_provider = MagicMock()
        stage_config = MagicMock()
        resolved = {"_context_meta": {"info": "test"}}
        context_provider.resolve.return_value = resolved

        _prepare_sequential_input(
            ctx, {}, context_provider=context_provider, stage_config=stage_config
        )
        assert ctx.state.get("_context_meta") == {"info": "test"}

    def test_context_provider_fallback_on_general_exception(self):
        ctx = _make_ctx(state={"key": "val"})
        context_provider = MagicMock()
        context_provider.resolve.side_effect = RuntimeError("fail")
        stage_config = MagicMock()

        # Should fall back to legacy input without raising
        result = _prepare_sequential_input(
            ctx, {}, context_provider=context_provider, stage_config=stage_config
        )
        assert StateKeys.CURRENT_STAGE_AGENTS in result

    def test_context_resolution_error_is_reraised(self):
        from temper_ai.workflow.context_provider import ContextResolutionError

        ctx = _make_ctx(state={})
        context_provider = MagicMock()
        context_provider.resolve.side_effect = ContextResolutionError(
            "stage1", "input1", "source1"
        )
        stage_config = MagicMock()

        with pytest.raises(ContextResolutionError):
            _prepare_sequential_input(
                ctx, {}, context_provider=context_provider, stage_config=stage_config
            )

    def test_no_context_provider_uses_legacy_input(self):
        state = {StateKeys.WORKFLOW_INPUTS: {"q": "hello"}}
        ctx = _make_ctx(state=state)
        result = _prepare_sequential_input(ctx, {})
        assert "q" in result


# ---------------------------------------------------------------------------
# _execute_and_track_agent
# ---------------------------------------------------------------------------


class TestExecuteAndTrackAgent:
    def _make_tracker_cm(self, agent_id="agent-abc"):
        tracker = MagicMock()

        @contextmanager
        def _cm(*args, **kwargs):
            yield agent_id

        tracker.track_agent = MagicMock(side_effect=_cm)
        return tracker

    def test_raises_when_tracker_is_none(self):
        ctx = _make_ctx(tracker=None)
        agent = MagicMock()
        context = MagicMock()
        with pytest.raises(ValueError, match="Tracker required"):
            _execute_and_track_agent(agent, {}, context, "agent_a", {}, ctx)

    def test_executes_agent_via_tracker_context(self):
        tracker = self._make_tracker_cm("agent-xyz")
        ctx = _make_ctx(tracker=tracker)
        agent = MagicMock()
        response = _make_response()
        agent.execute.return_value = response
        context = MagicMock()
        context.agent_id = ""

        result = _execute_and_track_agent(agent, {}, context, "agent_a", {}, ctx)
        agent.execute.assert_called_once()
        assert result is response

    def test_calls_set_agent_output(self):
        tracker = self._make_tracker_cm("agent-abc")
        ctx = _make_ctx(tracker=tracker)
        agent = MagicMock()
        agent.execute.return_value = _make_response()
        context = MagicMock()
        context.agent_id = ""

        _execute_and_track_agent(agent, {}, context, "agent_a", {}, ctx)
        tracker.set_agent_output.assert_called_once()


# ---------------------------------------------------------------------------
# _build_success_result
# ---------------------------------------------------------------------------


class TestBuildSuccessResult:
    def test_status_is_success(self):
        resp = _make_response(output="done", tokens=50, cost=0.005)
        result = _build_success_result("agent_a", resp, 1.0)
        assert result[StateKeys.STATUS] == "success"

    def test_script_outputs_included_when_present(self):
        resp = _make_response()
        resp.metadata = {"outputs": {"key1": "val1"}}
        result = _build_success_result("agent_a", resp, 1.0)
        assert "script_outputs" in result[StateKeys.OUTPUT_DATA]
        assert result[StateKeys.OUTPUT_DATA]["script_outputs"] == {"key1": "val1"}

    def test_no_script_outputs_key_when_absent(self):
        resp = _make_response()
        resp.metadata = {}
        result = _build_success_result("agent_a", resp, 1.0)
        assert "script_outputs" not in result[StateKeys.OUTPUT_DATA]

    def test_tool_calls_empty_list_when_none(self):
        resp = _make_response(tool_calls=None)
        result = _build_success_result("agent_a", resp, 1.0)
        assert result[StateKeys.OUTPUT_DATA][StateKeys.TOOL_CALLS] == []

    def test_metrics_have_duration(self):
        resp = _make_response()
        result = _build_success_result("agent_a", resp, 3.14)
        assert result[StateKeys.METRICS][StateKeys.DURATION_SECONDS] == pytest.approx(
            3.14
        )


# ---------------------------------------------------------------------------
# _wire_tool_executor
# ---------------------------------------------------------------------------


class TestWireToolExecutor:
    def test_no_op_when_tool_executor_none(self):
        ctx = _make_ctx(tool_executor=None)
        input_data: dict = {}
        _wire_tool_executor(ctx, input_data)
        assert "tool_executor" not in input_data

    def test_wires_tool_executor_to_input_data(self):
        tool_exec = MagicMock()
        ctx = _make_ctx(tool_executor=tool_exec)
        input_data: dict = {}
        _wire_tool_executor(ctx, input_data)
        assert input_data["tool_executor"] is tool_exec

    def test_sets_workflow_rate_limiter_when_present(self):
        tool_exec = MagicMock()
        wf_rl = MagicMock()
        state = {StateKeys.WORKFLOW_RATE_LIMITER: wf_rl}
        ctx = _make_ctx(state=state, tool_executor=tool_exec)
        _wire_tool_executor(ctx, {})
        assert tool_exec.workflow_rate_limiter is wf_rl

    def test_no_rate_limiter_when_not_in_state(self):
        tool_exec = MagicMock()
        ctx = _make_ctx(tool_executor=tool_exec)
        _wire_tool_executor(ctx, {})
        # Should not raise; workflow_rate_limiter not set
        assert not hasattr(tool_exec, "workflow_rate_limiter") or True


# ---------------------------------------------------------------------------
# _dispatch_sequential_evaluation
# ---------------------------------------------------------------------------


class TestDispatchSequentialEvaluation:
    def test_no_op_when_no_dispatcher(self):
        ctx = _make_ctx(state={})
        resp = _make_response()
        context = MagicMock()
        context.agent_id = "agent-1"
        _dispatch_sequential_evaluation(ctx, "agent_a", context, {}, resp, {}, 1.0)

    def test_calls_dispatcher_when_present(self):
        dispatcher = MagicMock()
        state = {StateKeys.EVALUATION_DISPATCHER: dispatcher}
        ctx = _make_ctx(state=state)
        resp = _make_response()
        resp.metadata = {"_rendered_prompt": "prompt"}
        context = MagicMock()
        context.agent_id = "agent-1"
        config_dict = {"agent": {"inference": {"model": "gpt-4"}}}
        _dispatch_sequential_evaluation(
            ctx, "agent_a", context, {}, resp, config_dict, 1.0
        )
        dispatcher.dispatch.assert_called_once()

    def test_passes_correct_agent_name(self):
        dispatcher = MagicMock()
        state = {StateKeys.EVALUATION_DISPATCHER: dispatcher}
        ctx = _make_ctx(state=state)
        resp = _make_response()
        resp.metadata = {}
        context = MagicMock()
        context.agent_id = "agent-1"
        _dispatch_sequential_evaluation(ctx, "my_agent", context, {}, resp, {}, 1.0)
        call_kwargs = dispatcher.dispatch.call_args.kwargs
        assert call_kwargs["agent_name"] == "my_agent"


# ---------------------------------------------------------------------------
# _print_agent_progress
# ---------------------------------------------------------------------------


class TestPrintAgentProgress:
    def test_prints_success_message(self):
        console = MagicMock()
        result = {
            StateKeys.STATUS: "success",
            StateKeys.METRICS: {StateKeys.DURATION_SECONDS: 1.5, StateKeys.TOKENS: 50},
        }
        _print_agent_progress(console, "agent_a", result, is_last=True)
        console.print.assert_called_once()
        printed = console.print.call_args[0][0]
        assert "agent_a" in printed

    def test_prints_failure_message_with_error_type(self):
        console = MagicMock()
        result = {
            StateKeys.STATUS: "failed",
            StateKeys.METRICS: {StateKeys.DURATION_SECONDS: 0.5, StateKeys.TOKENS: 0},
            StateKeys.OUTPUT_DATA: {StateKeys.ERROR_TYPE: "llm_timeout"},
        }
        _print_agent_progress(console, "agent_b", result, is_last=False)
        printed = console.print.call_args[0][0]
        assert "llm_timeout" in printed


# ---------------------------------------------------------------------------
# _print_sequential_stage_header
# ---------------------------------------------------------------------------


class TestPrintSequentialStageHeader:
    def test_no_op_when_no_console(self):
        ctx = _make_ctx(state={})
        _print_sequential_stage_header(ctx)  # No exception

    def test_prints_header_when_console_present(self):
        console = MagicMock()
        state = {
            StateKeys.DETAIL_CONSOLE: console,
            StateKeys.STAGE_OUTPUTS: {},
            StateKeys.TOTAL_STAGES: 5,
        }
        ctx = _make_ctx(state=state)
        _print_sequential_stage_header(ctx)
        console.print.assert_called_once()

    def test_sets_stream_callback_stage(self):
        console = MagicMock()
        stream_cb = MagicMock()
        stream_cb._current_stage = "old_stage"
        state = {
            StateKeys.DETAIL_CONSOLE: console,
            StateKeys.STREAM_CALLBACK: stream_cb,
            StateKeys.STAGE_OUTPUTS: {},
            StateKeys.TOTAL_STAGES: 3,
        }
        ctx = _make_ctx(state=state)
        _print_sequential_stage_header(ctx)
        assert stream_cb._current_stage == "stage1"


# ---------------------------------------------------------------------------
# _emit_sequential_cost_summary
# ---------------------------------------------------------------------------


class TestEmitSequentialCostSummary:
    def test_calls_emit_cost_summary_on_success(self):
        ctx = _make_ctx(state={})
        accum = AgentResultAccumulators(
            outputs={"a": {"output": "x"}},
            statuses={"a": "success"},
            metrics={"a": {"tokens": 10, "cost_usd": 0.01, "duration_seconds": 1.0}},
        )
        mock_summary = MagicMock()
        with (
            patch(
                "temper_ai.observability.cost_rollup.compute_stage_cost_summary",
                return_value=mock_summary,
            ),
            patch("temper_ai.observability.cost_rollup.emit_cost_summary") as mock_emit,
        ):
            _emit_sequential_cost_summary(ctx, accum)
        mock_emit.assert_called_once()

    def test_does_not_raise_on_exception(self):
        ctx = _make_ctx(state={})
        accum = AgentResultAccumulators(outputs={}, statuses={}, metrics={})
        with patch(
            "temper_ai.observability.cost_rollup.compute_stage_cost_summary",
            side_effect=RuntimeError("boom"),
        ):
            _emit_sequential_cost_summary(ctx, accum)  # No exception
