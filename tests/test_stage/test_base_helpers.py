"""Tests for temper_ai/stage/executors/_base_helpers.py.

Covers:
- prepare_tracking_input (NON_SERIALIZABLE_KEYS filtering + truncation)
- _truncate_tracking_data (within/over limit behaviour)
- _create_execution_context (metadata, workflow_id)
- _build_agent_output (AgentOutput construction)
- _get_stage_id (from state or generated)
- _save_conversation_turn (create/append/no-op paths)
- AgentExecutionParams (dataclass construction)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from temper_ai.stage.executors._base_helpers import (
    AgentExecutionParams,
    _build_agent_output,
    _create_execution_context,
    _get_stage_id,
    _save_conversation_turn,
    _truncate_tracking_data,
    prepare_tracking_input,
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
    metadata=None,
):
    """Return a MagicMock that looks like an AgentResponse."""
    resp = MagicMock()
    resp.output = output
    resp.reasoning = reasoning
    resp.confidence = confidence
    resp.tokens = tokens
    resp.estimated_cost_usd = estimated_cost_usd
    resp.tool_calls = tool_calls if tool_calls is not None else []
    resp.metadata = metadata if metadata is not None else {}
    return resp


# ---------------------------------------------------------------------------
# TestPrepareTrackingInput
# ---------------------------------------------------------------------------


class TestPrepareTrackingInput:
    """prepare_tracking_input filters NON_SERIALIZABLE_KEYS and sanitizes."""

    def test_removes_tracker_key(self):
        data = {"tracker": object(), "user_query": "hello"}
        result = prepare_tracking_input(data)
        assert "tracker" not in result
        assert result["user_query"] == "hello"

    def test_removes_tool_registry_key(self):
        data = {"tool_registry": object(), "val": 42}
        result = prepare_tracking_input(data)
        assert "tool_registry" not in result
        assert result["val"] == 42

    def test_removes_all_non_serializable_keys(self):
        non_ser_keys = list(StateKeys.NON_SERIALIZABLE_KEYS)
        data = {k: object() for k in non_ser_keys}
        data["keep_me"] = "yes"
        result = prepare_tracking_input(data)
        for key in non_ser_keys:
            assert key not in result
        assert result["keep_me"] == "yes"

    def test_keeps_normal_string_keys(self):
        data = {"question": "what?", "context": "some text"}
        result = prepare_tracking_input(data)
        assert result["question"] == "what?"
        assert result["context"] == "some text"

    def test_keeps_nested_dict_keys(self):
        data = {"meta": {"nested": True}, "tracker": object()}
        result = prepare_tracking_input(data)
        assert "meta" in result
        assert "tracker" not in result

    def test_empty_dict_returns_empty(self):
        result = prepare_tracking_input({})
        assert result == {}

    def test_only_non_serializable_keys_returns_empty(self):
        data = dict.fromkeys(StateKeys.NON_SERIALIZABLE_KEYS, "x")
        result = prepare_tracking_input(data)
        assert result == {}

    def test_returns_dict(self):
        result = prepare_tracking_input({"a": 1})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestTruncateTrackingData
# ---------------------------------------------------------------------------


class TestTruncateTrackingData:
    """_truncate_tracking_data handles size limits correctly."""

    def test_small_data_returned_as_is(self):
        data = {"key": "value", "number": 42}
        result = _truncate_tracking_data(data)
        assert result == data

    def test_large_stage_outputs_are_truncated(self):
        # Build a payload that exceeds 4 MB limit
        big_value = "x" * (10000)  # per-value >4096 → truncated at first threshold
        # Wrap in enough stage_outputs to push total over limit
        stage_outputs = {f"stage_{i}": big_value for i in range(500)}
        data = {"stage_outputs": stage_outputs, "other": "ok"}
        result = _truncate_tracking_data(data)
        # At least some values should be truncated
        truncated_outputs = result["stage_outputs"]
        truncated_count = sum(
            1
            for v in truncated_outputs.values()
            if isinstance(v, str) and v.startswith("[truncated:")
        )
        assert truncated_count > 0

    def test_small_stage_output_values_kept_as_is(self):
        # Values ≤256 bytes should survive truncation even if total is over limit
        small_value = "short"
        big_filler = "y" * 10000
        stage_outputs = {"important": small_value}
        # pad with large stages to exceed the 4MB total limit
        stage_outputs.update({f"big_{i}": big_filler for i in range(500)})
        data = {"stage_outputs": stage_outputs}
        result = _truncate_tracking_data(data)
        # The small value should remain unchanged
        assert result["stage_outputs"]["important"] == small_value

    def test_non_serializable_data_returned_as_is(self):
        """If json.dumps raises TypeError/ValueError, return data unchanged."""
        data = {"key": "safe_value"}
        with patch("json.dumps", side_effect=TypeError("boom")):
            result = _truncate_tracking_data(data)
        assert result is data

    def test_no_stage_outputs_key_no_crash(self):
        # Large data without stage_outputs key — no KeyError
        data = {"other": "a" * 100}
        result = _truncate_tracking_data(data)
        assert "other" in result


# ---------------------------------------------------------------------------
# TestCreateExecutionContext
# ---------------------------------------------------------------------------


class TestCreateExecutionContext:
    """_create_execution_context builds ExecutionContext with correct fields."""

    def _call(self, state=None, extra_metadata=None):
        state = state or {}
        with patch("temper_ai.shared.core.context.ExecutionContext") as mock_ctx_cls:
            mock_ctx_cls.return_value = MagicMock()
            _create_execution_context(
                state=state,
                current_stage_id="sid-1",
                agent_id="agent-1",
                stage_name="my-stage",
                agent_name="my-agent",
                execution_mode="sequential",
                extra_metadata=extra_metadata,
            )
            return mock_ctx_cls.call_args

    def test_standard_metadata_fields_present(self):
        call_args = self._call()
        kwargs = call_args.kwargs
        meta = kwargs["metadata"]
        assert meta["stage_name"] == "my-stage"
        assert meta["agent_name"] == "my-agent"
        assert meta["execution_mode"] == "sequential"

    def test_extra_metadata_merged(self):
        call_args = self._call(extra_metadata={"custom_key": "custom_val"})
        kwargs = call_args.kwargs
        meta = kwargs["metadata"]
        assert meta["custom_key"] == "custom_val"
        assert meta["stage_name"] == "my-stage"

    def test_workflow_id_from_state(self):
        state = {StateKeys.WORKFLOW_ID: "wf-xyz"}
        call_args = self._call(state=state)
        kwargs = call_args.kwargs
        assert kwargs["workflow_id"] == "wf-xyz"

    def test_workflow_id_defaults_to_status_unknown_when_missing(self):
        from temper_ai.shared.constants.execution import STATUS_UNKNOWN

        call_args = self._call(state={})
        kwargs = call_args.kwargs
        assert kwargs["workflow_id"] == STATUS_UNKNOWN

    def test_stage_id_and_agent_id_passed(self):
        call_args = self._call()
        kwargs = call_args.kwargs
        assert kwargs["stage_id"] == "sid-1"
        assert kwargs["agent_id"] == "agent-1"

    def test_no_extra_metadata_does_not_crash(self):
        call_args = self._call(extra_metadata=None)
        assert call_args is not None


# ---------------------------------------------------------------------------
# TestBuildAgentOutput
# ---------------------------------------------------------------------------


class TestBuildAgentOutput:
    """_build_agent_output creates AgentOutput with correct fields."""

    def _call(self, agent_name="builder", role=None, extra_metadata=None):
        resp = _make_response()
        with patch("temper_ai.agent.strategies.base.AgentOutput") as mock_cls:
            mock_cls.return_value = MagicMock()
            if role is not None:
                _build_agent_output(
                    agent_name, resp, role=role, extra_metadata=extra_metadata
                )
            else:
                _build_agent_output(agent_name, resp, extra_metadata=extra_metadata)
            return mock_cls.call_args

    def test_agent_name_passed(self):
        call_args = self._call(agent_name="my-agent")
        assert call_args.kwargs["agent_name"] == "my-agent"

    def test_decision_is_response_output(self):
        call_args = self._call()
        assert call_args.kwargs["decision"] == "result"

    def test_reasoning_is_response_reasoning(self):
        call_args = self._call()
        assert call_args.kwargs["reasoning"] == "because"

    def test_confidence_is_response_confidence(self):
        call_args = self._call()
        assert call_args.kwargs["confidence"] == 0.9

    def test_role_defaults_to_agent_role_leader(self):
        from temper_ai.shared.constants.execution import AGENT_ROLE_LEADER

        call_args = self._call()
        meta = call_args.kwargs["metadata"]
        assert meta["role"] == AGENT_ROLE_LEADER

    def test_custom_role_passed_through(self):
        call_args = self._call(role="member")
        meta = call_args.kwargs["metadata"]
        assert meta["role"] == "member"

    def test_extra_metadata_merged(self):
        call_args = self._call(extra_metadata={"extra_key": "extra_val"})
        meta = call_args.kwargs["metadata"]
        assert meta["extra_key"] == "extra_val"

    def test_tokens_and_cost_in_metadata(self):
        call_args = self._call()
        meta = call_args.kwargs["metadata"]
        assert StateKeys.TOKENS in meta
        assert StateKeys.COST_USD in meta


# ---------------------------------------------------------------------------
# TestGetStageId
# ---------------------------------------------------------------------------


class TestGetStageId:
    """_get_stage_id returns from state or generates a uuid-based ID."""

    def test_returns_current_stage_id_from_state(self):
        state = {StateKeys.CURRENT_STAGE_ID: "stage-abc"}
        result = _get_stage_id(state)
        assert result == "stage-abc"

    def test_generates_id_when_key_missing(self):
        state = {}
        result = _get_stage_id(state)
        assert result.startswith("stage-")

    def test_generated_id_is_unique(self):
        state = {}
        id1 = _get_stage_id(state)
        id2 = _get_stage_id(state)
        assert id1 != id2

    def test_generated_id_contains_hex(self):
        state = {}
        result = _get_stage_id(state)
        hex_part = result[len("stage-") :]
        int(hex_part, 16)  # Should not raise

    def test_none_value_triggers_generation(self):
        state = {StateKeys.CURRENT_STAGE_ID: None}
        result = _get_stage_id(state)
        assert result.startswith("stage-")


# ---------------------------------------------------------------------------
# TestSaveConversationTurn
# ---------------------------------------------------------------------------


class TestSaveConversationTurn:
    """_save_conversation_turn persists user/assistant turns in state."""

    def _make_history_mock(self, to_dict_return=None):
        h = MagicMock()
        h.to_dict.return_value = to_dict_return or {"turns": []}
        return h

    def test_creates_new_history_when_none_exists(self):
        state: dict = {}
        resp = _make_response(output="answer", metadata={"_user_message": "question"})

        mock_history = self._make_history_mock({"turns": [{"user": "question"}]})
        with patch(
            "temper_ai.llm.conversation.ConversationHistory",
            return_value=mock_history,
        ):
            _save_conversation_turn(state, "key1", {}, resp)

        assert StateKeys.CONVERSATION_HISTORIES in state
        assert "key1" in state[StateKeys.CONVERSATION_HISTORIES]

    def test_appends_to_existing_history(self):
        existing_history = MagicMock()
        existing_history.to_dict.return_value = {"turns": ["existing"]}
        state: dict = {StateKeys.CONVERSATION_HISTORIES: {"key1": {}}}
        resp = _make_response(output="answer", metadata={"_user_message": "q2"})

        with patch("temper_ai.llm.conversation.ConversationHistory") as mock_hist_cls:
            _save_conversation_turn(
                state, "key1", {"_conversation_history": existing_history}, resp
            )
            # Should NOT create a new ConversationHistory since one was provided
            mock_hist_cls.assert_not_called()

        existing_history.append_turn.assert_called_once()

    def test_no_op_when_response_has_no_output(self):
        state: dict = {}
        resp = _make_response(output=None)
        resp.output = None  # Explicitly set to None

        _save_conversation_turn(state, "key1", {}, resp)

        assert StateKeys.CONVERSATION_HISTORIES not in state

    def test_uses_rendered_prompt_fallback(self):
        state: dict = {}
        resp = _make_response(
            output="answer",
            metadata={"_rendered_prompt": "rendered q"},
        )

        mock_history = self._make_history_mock()
        with patch(
            "temper_ai.llm.conversation.ConversationHistory",
            return_value=mock_history,
        ):
            _save_conversation_turn(state, "key1", {}, resp)

        mock_history.append_turn.assert_called_once_with(
            user_content="rendered q",
            assistant_content="answer",
        )

    def test_conversation_histories_initialised_if_absent(self):
        state: dict = {}
        resp = _make_response(output="ok", metadata={"_user_message": "hi"})

        mock_history = self._make_history_mock()
        with patch(
            "temper_ai.llm.conversation.ConversationHistory",
            return_value=mock_history,
        ):
            _save_conversation_turn(state, "new_key", {}, resp)

        assert StateKeys.CONVERSATION_HISTORIES in state


# ---------------------------------------------------------------------------
# TestAgentExecutionParams
# ---------------------------------------------------------------------------


class TestAgentExecutionParams:
    """AgentExecutionParams dataclass construction and defaults."""

    def _make_params(self, **overrides):
        defaults = {
            "agent": MagicMock(),
            "input_data": {"q": "hi"},
            "current_stage_id": "sid",
            "stage_name": "stage",
            "agent_name": "agent",
            "state": {},
            "execution_mode": "sequential",
        }
        defaults.update(overrides)
        return AgentExecutionParams(**defaults)

    def test_required_fields_set(self):
        p = self._make_params()
        assert p.stage_name == "stage"
        assert p.agent_name == "agent"
        assert p.execution_mode == "sequential"

    def test_tracker_defaults_to_none(self):
        p = self._make_params()
        assert p.tracker is None

    def test_agent_config_defaults_to_none(self):
        p = self._make_params()
        assert p.agent_config is None

    def test_agent_config_dict_defaults_to_none(self):
        p = self._make_params()
        assert p.agent_config_dict is None

    def test_tracking_input_defaults_to_none(self):
        p = self._make_params()
        assert p.tracking_input is None

    def test_extra_metadata_defaults_to_none(self):
        p = self._make_params()
        assert p.extra_metadata is None

    def test_custom_values_stored(self):
        tracker = MagicMock()
        p = self._make_params(tracker=tracker, extra_metadata={"k": "v"})
        assert p.tracker is tracker
        assert p.extra_metadata == {"k": "v"}
