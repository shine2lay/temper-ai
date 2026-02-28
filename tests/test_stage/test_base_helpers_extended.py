"""Extended tests for temper_ai/stage/executors/_base_helpers.py.

Covers uncovered paths:
- _record_agent_tracking (success / exception path)
- _execute_agent_with_tracking (full path, missing tracker)
- _execute_agent_without_tracking
- invoke_leader_agent (with tracker / without tracker)
- _dispatch_leader_evaluation (dispatcher present / absent)
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.stage.executors._base_helpers import (
    AgentExecutionParams,
    _dispatch_leader_evaluation,
    _execute_agent_with_tracking,
    _execute_agent_without_tracking,
    _record_agent_tracking,
    invoke_leader_agent,
)
from temper_ai.stage.executors.state_keys import StateKeys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    output="result",
    reasoning="because",
    confidence=0.9,
    tokens=100,
    estimated_cost_usd=0.01,
    tool_calls=None,
):
    resp = MagicMock()
    resp.output = output
    resp.reasoning = reasoning
    resp.confidence = confidence
    resp.tokens = tokens
    resp.estimated_cost_usd = estimated_cost_usd
    resp.tool_calls = tool_calls or []
    resp.metadata = {"_agent_execution_id": ""}
    return resp


def _make_exec_params(tracker=None, extra_metadata=None):
    resp = _make_response()
    agent = MagicMock()
    agent.execute.return_value = resp
    return AgentExecutionParams(
        agent=agent,
        input_data={"key": "val"},
        current_stage_id="sid-1",
        stage_name="my-stage",
        agent_name="my-agent",
        state={StateKeys.WORKFLOW_ID: "wf-1"},
        execution_mode="sequential",
        tracker=tracker,
        agent_config=MagicMock(),
        agent_config_dict={"agent": {}},
        extra_metadata=extra_metadata,
    )


def _make_tracker_context_manager(agent_id="agent-123"):
    """Return a MagicMock tracker whose track_agent context manager yields agent_id."""
    tracker = MagicMock()

    @contextmanager
    def _cm(*args, **kwargs):
        yield agent_id

    tracker.track_agent = MagicMock(side_effect=_cm)
    return tracker


# ---------------------------------------------------------------------------
# _record_agent_tracking
# ---------------------------------------------------------------------------


class TestRecordAgentTracking:
    def test_calls_set_agent_output_on_tracker(self):
        tracker = MagicMock()
        response = _make_response(tokens=50, tool_calls=[MagicMock()])
        _record_agent_tracking(tracker, "agent-id", response, "my-agent", "sequential")
        tracker.set_agent_output.assert_called_once()

    def test_logs_warning_on_exception(self):
        tracker = MagicMock()
        tracker.set_agent_output.side_effect = RuntimeError("fail")
        response = _make_response()
        # Should not raise, just log
        _record_agent_tracking(tracker, "agent-id", response, "my-agent", "sequential")

    def test_no_tool_calls_sends_zero(self):
        tracker = MagicMock()
        response = _make_response(tool_calls=None)
        _record_agent_tracking(tracker, "agent-id", response, "my-agent", "sequential")
        call_kwargs = tracker.set_agent_output.call_args[0][0]
        assert call_kwargs.num_tool_calls == 0

    def test_zero_tokens_gives_zero_llm_calls(self):
        tracker = MagicMock()
        response = _make_response(tokens=0)
        _record_agent_tracking(tracker, "agent-id", response, "my-agent", "sequential")
        call_kwargs = tracker.set_agent_output.call_args[0][0]
        assert call_kwargs.num_llm_calls == 0

    def test_positive_tokens_gives_one_llm_call(self):
        tracker = MagicMock()
        response = _make_response(tokens=100)
        _record_agent_tracking(tracker, "agent-id", response, "my-agent", "sequential")
        call_kwargs = tracker.set_agent_output.call_args[0][0]
        assert call_kwargs.num_llm_calls == 1


# ---------------------------------------------------------------------------
# _execute_agent_with_tracking
# ---------------------------------------------------------------------------


class TestExecuteAgentWithTracking:
    def test_raises_when_tracker_is_none(self):
        params = _make_exec_params(tracker=None)
        with pytest.raises(ValueError, match="requires a tracker"):
            _execute_agent_with_tracking(params)

    def test_executes_agent_and_returns_response(self):
        tracker = _make_tracker_context_manager("agent-xyz")
        params = _make_exec_params(tracker=tracker)

        with (
            patch(
                "temper_ai.stage.executors._agent_execution.config_to_tracking_dict",
                return_value={},
            ),
            patch(
                "temper_ai.stage.executors._base_helpers._create_execution_context",
                return_value=MagicMock(),
            ),
            patch("temper_ai.stage.executors._base_helpers._record_agent_tracking"),
        ):
            result = _execute_agent_with_tracking(params)

        params.agent.execute.assert_called_once()
        assert result is params.agent.execute.return_value

    def test_sets_agent_execution_id_in_metadata(self):
        tracker = _make_tracker_context_manager("agent-abc")
        params = _make_exec_params(tracker=tracker)

        with (
            patch(
                "temper_ai.stage.executors._agent_execution.config_to_tracking_dict",
                return_value={},
            ),
            patch(
                "temper_ai.stage.executors._base_helpers._create_execution_context",
                return_value=MagicMock(),
            ),
            patch("temper_ai.stage.executors._base_helpers._record_agent_tracking"),
        ):
            result = _execute_agent_with_tracking(params)

        assert result.metadata["_agent_execution_id"] == "agent-abc"


# ---------------------------------------------------------------------------
# _execute_agent_without_tracking
# ---------------------------------------------------------------------------


class TestExecuteAgentWithoutTracking:
    def test_executes_agent_and_returns_response(self):
        params = _make_exec_params()

        with patch(
            "temper_ai.stage.executors._base_helpers._create_execution_context",
            return_value=MagicMock(),
        ):
            result = _execute_agent_without_tracking(params)

        params.agent.execute.assert_called_once()
        assert result is params.agent.execute.return_value

    def test_removes_tracker_from_input_data(self):
        params = _make_exec_params()
        params.input_data[StateKeys.TRACKER] = MagicMock()

        with patch(
            "temper_ai.stage.executors._base_helpers._create_execution_context",
            return_value=MagicMock(),
        ):
            _execute_agent_without_tracking(params)

        assert StateKeys.TRACKER not in params.input_data

    def test_sets_agent_execution_id_in_metadata(self):
        params = _make_exec_params()

        with patch(
            "temper_ai.stage.executors._base_helpers._create_execution_context",
            return_value=MagicMock(),
        ):
            result = _execute_agent_without_tracking(params)

        assert "_agent_execution_id" in result.metadata
        assert result.metadata["_agent_execution_id"].startswith("agent-")


# ---------------------------------------------------------------------------
# _dispatch_leader_evaluation
# ---------------------------------------------------------------------------


class TestDispatchLeaderEvaluation:
    def _make_response_with_metadata(self):
        resp = _make_response()
        resp.metadata = {"_agent_execution_id": "exec-1", "_rendered_prompt": "prompt"}
        return resp

    def test_no_op_when_no_dispatcher(self):
        state = {}
        resp = self._make_response_with_metadata()
        # Should not raise
        _dispatch_leader_evaluation("leader", resp, {}, "stage1", state, 1.0)

    def test_calls_dispatcher_when_present(self):
        dispatcher = MagicMock()
        state = {StateKeys.EVALUATION_DISPATCHER: dispatcher}
        resp = self._make_response_with_metadata()
        _dispatch_leader_evaluation("leader", resp, {}, "stage1", state, 1.0)
        dispatcher.dispatch.assert_called_once()

    def test_passes_correct_agent_name(self):
        dispatcher = MagicMock()
        state = {StateKeys.EVALUATION_DISPATCHER: dispatcher}
        resp = self._make_response_with_metadata()
        _dispatch_leader_evaluation("my_leader", resp, {}, "stage1", state, 0.5)
        call_kwargs = dispatcher.dispatch.call_args.kwargs
        assert call_kwargs["agent_name"] == "my_leader"

    def test_includes_model_from_config_dict(self):
        dispatcher = MagicMock()
        state = {StateKeys.EVALUATION_DISPATCHER: dispatcher}
        resp = self._make_response_with_metadata()
        config_dict = {"agent": {"inference": {"model": "gpt-4"}}}
        _dispatch_leader_evaluation("leader", resp, config_dict, "stage1", state, 1.0)
        call_kwargs = dispatcher.dispatch.call_args.kwargs
        assert call_kwargs["agent_context"]["model"] == "gpt-4"


# ---------------------------------------------------------------------------
# invoke_leader_agent
# ---------------------------------------------------------------------------


class TestInvokeLeaderAgent:
    def _make_state(self, tracker=None, dispatcher=None):
        state = {StateKeys.WORKFLOW_ID: "wf-1"}
        if tracker is not None:
            state[StateKeys.TRACKER] = tracker
        if dispatcher is not None:
            state[StateKeys.EVALUATION_DISPATCHER] = dispatcher
        return state

    def test_returns_agent_output_without_tracker(self):
        config_loader = MagicMock()
        config_loader.load_agent.return_value = {"agent": {"name": "leader"}}
        state = self._make_state()

        resp = _make_response()
        mock_agent = MagicMock()
        mock_agent.execute.return_value = resp

        with (
            patch("temper_ai.storage.schemas.agent_config.AgentConfig") as mock_cfg,
            patch("temper_ai.agent.utils.agent_factory.AgentFactory") as mock_factory,
            patch(
                "temper_ai.stage.executors._base_helpers._execute_agent_without_tracking",
                return_value=resp,
            ),
            patch(
                "temper_ai.stage.executors._base_helpers._build_agent_output",
                return_value=MagicMock(),
            ) as mock_build,
        ):
            mock_cfg.return_value = MagicMock()
            mock_factory.create.return_value = mock_agent

            invoke_leader_agent("leader", "team text", "stage1", state, config_loader)

        mock_build.assert_called_once()

    def test_uses_tracker_when_present(self):
        from contextlib import contextmanager

        tracker = MagicMock()

        @contextmanager
        def _cm(*args, **kwargs):
            yield "agent-1"

        tracker.track_agent = MagicMock(side_effect=_cm)

        config_loader = MagicMock()
        config_loader.load_agent.return_value = {"agent": {"name": "leader"}}
        state = self._make_state(tracker=tracker)

        resp = _make_response()
        mock_agent = MagicMock()
        mock_agent.execute.return_value = resp

        with (
            patch("temper_ai.storage.schemas.agent_config.AgentConfig") as mock_cfg,
            patch("temper_ai.agent.utils.agent_factory.AgentFactory") as mock_factory,
            patch(
                "temper_ai.stage.executors._base_helpers._execute_agent_with_tracking",
                return_value=resp,
            ) as mock_with_tracker,
            patch(
                "temper_ai.stage.executors._base_helpers._build_agent_output",
                return_value=MagicMock(),
            ),
            patch(
                "temper_ai.stage.executors._base_helpers._dispatch_leader_evaluation"
            ),
        ):
            mock_cfg.return_value = MagicMock()
            mock_factory.create.return_value = mock_agent

            invoke_leader_agent("leader", "team text", "stage1", state, config_loader)

        mock_with_tracker.assert_called_once()
