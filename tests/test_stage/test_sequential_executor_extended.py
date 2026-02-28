"""Extended tests for temper_ai/stage/executors/sequential.py.

Covers uncovered paths:
- _concatenate_agent_outputs (empty / single / multi)
- SequentialStageExecutor._try_synthesis (success / exception fallback)
- SequentialStageExecutor._resolve_final_output (collaboration / no collaboration / single agent)
- SequentialStageExecutor._store_stage_output (failed / degraded / completed status, synthesis result, context_meta)
- SequentialStageExecutor._persist_stage_output (tracker present / absent / exception)
- SequentialStageExecutor._execute_with_convergence
- SequentialStageExecutor._execute_once (script_outputs merge, structured fields)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from temper_ai.agent.strategies.base import SynthesisResult
from temper_ai.stage.executors.sequential import (
    SequentialStageExecutor,
    StageOutputData,
    _concatenate_agent_outputs,
)
from temper_ai.stage.executors.state_keys import StateKeys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_synthesis_result(decision="yes", method="consensus", confidence=0.9):
    return SynthesisResult(
        decision=decision,
        confidence=confidence,
        method=method,
        votes={"yes": 1},
        conflicts=[],
        reasoning="ok",
        metadata={},
    )


def _make_agent_outputs(*agents):
    """Create dict of agent outputs."""
    result = {}
    for name, output in agents:
        result[name] = {
            StateKeys.OUTPUT: output,
            StateKeys.REASONING: "reason",
            StateKeys.CONFIDENCE: 0.9,
        }
    return result


def _make_stage_output_data(
    agents=None,
    agent_outputs=None,
    agent_statuses=None,
    synthesis_result=None,
    final_output="done",
):
    return StageOutputData(
        final_output=final_output,
        synthesis_result=synthesis_result,
        agent_outputs=agent_outputs or {},
        agent_statuses=agent_statuses or {},
        agent_metrics={},
        agents=agents or [],
    )


def _make_executor():
    return SequentialStageExecutor()


# ---------------------------------------------------------------------------
# _concatenate_agent_outputs
# ---------------------------------------------------------------------------


class TestConcatenateAgentOutputs:
    def test_empty_outputs_returns_empty_string(self):
        result = _concatenate_agent_outputs({})
        assert result == ""

    def test_single_agent_returns_its_output(self):
        outputs = {"a": {StateKeys.OUTPUT: "hello"}}
        result = _concatenate_agent_outputs(outputs)
        assert result == "hello"

    def test_multiple_agents_joined_with_double_newline(self):
        outputs = {
            "a": {StateKeys.OUTPUT: "part1"},
            "b": {StateKeys.OUTPUT: "part2"},
        }
        result = _concatenate_agent_outputs(outputs)
        assert result == "part1\n\npart2"

    def test_skips_empty_output_values(self):
        outputs = {
            "a": {StateKeys.OUTPUT: "real"},
            "b": {StateKeys.OUTPUT: ""},
            "c": {StateKeys.OUTPUT: None},
        }
        result = _concatenate_agent_outputs(outputs)
        assert result == "real"

    def test_all_empty_outputs_returns_empty_string(self):
        outputs = {"a": {StateKeys.OUTPUT: ""}, "b": {StateKeys.OUTPUT: ""}}
        result = _concatenate_agent_outputs(outputs)
        assert result == ""


# ---------------------------------------------------------------------------
# _try_synthesis
# ---------------------------------------------------------------------------


class TestTrySynthesis:
    def test_returns_decision_and_result_on_success(self):
        executor = _make_executor()
        agent_outputs = _make_agent_outputs(("a", "yes"), ("b", "no"))
        synth = _make_synthesis_result(decision="yes")

        with patch.object(executor, "_run_synthesis", return_value=synth):
            result = executor._try_synthesis(
                agent_outputs, MagicMock(), "stage1", {}, MagicMock(), ["a", "b"]
            )
        assert result is not None
        decision, synthesis_result = result
        assert decision == "yes"
        assert synthesis_result is synth

    def test_returns_none_on_runtime_error(self):
        executor = _make_executor()
        agent_outputs = _make_agent_outputs(("a", "yes"))

        with patch.object(executor, "_run_synthesis", side_effect=RuntimeError("fail")):
            result = executor._try_synthesis(
                agent_outputs, MagicMock(), "stage1", {}, MagicMock(), ["a"]
            )
        assert result is None

    def test_returns_none_on_value_error(self):
        executor = _make_executor()
        agent_outputs = _make_agent_outputs(("a", "yes"))

        with patch.object(executor, "_run_synthesis", side_effect=ValueError("bad")):
            result = executor._try_synthesis(
                agent_outputs, MagicMock(), "stage1", {}, MagicMock(), ["a"]
            )
        assert result is None

    def test_returns_none_on_key_error(self):
        executor = _make_executor()
        agent_outputs = _make_agent_outputs(("a", "yes"))

        with patch.object(executor, "_run_synthesis", side_effect=KeyError("missing")):
            result = executor._try_synthesis(
                agent_outputs, MagicMock(), "stage1", {}, MagicMock(), ["a"]
            )
        assert result is None


# ---------------------------------------------------------------------------
# _resolve_final_output
# ---------------------------------------------------------------------------


class TestResolveFinalOutput:
    def test_uses_concatenation_when_no_collaboration(self):
        executor = _make_executor()
        agent_outputs = _make_agent_outputs(("a", "out_a"), ("b", "out_b"))

        with patch(
            "temper_ai.stage.executors.sequential.get_collaboration", return_value=None
        ):
            final, synth = executor._resolve_final_output(
                agent_outputs, MagicMock(), "stage1", {}, MagicMock(), ["a", "b"]
            )
        assert "out_a" in final
        assert synth is None

    def test_uses_concatenation_for_single_agent(self):
        executor = _make_executor()
        agent_outputs = _make_agent_outputs(("a", "only"))

        with patch(
            "temper_ai.stage.executors.sequential.get_collaboration",
            return_value={"mode": "consensus"},
        ):
            final, synth = executor._resolve_final_output(
                agent_outputs, MagicMock(), "stage1", {}, MagicMock(), ["a"]
            )
        # Only 1 agent → no synthesis needed
        assert final == "only"
        assert synth is None

    def test_uses_synthesis_for_multiple_agents_with_collaboration(self):
        executor = _make_executor()
        agent_outputs = _make_agent_outputs(("a", "yes"), ("b", "no"))
        expected_synth = _make_synthesis_result(decision="yes")

        with (
            patch(
                "temper_ai.stage.executors.sequential.get_collaboration",
                return_value={"mode": "consensus"},
            ),
            patch.object(
                executor, "_try_synthesis", return_value=("yes", expected_synth)
            ),
        ):
            final, synth = executor._resolve_final_output(
                agent_outputs, MagicMock(), "stage1", {}, MagicMock(), ["a", "b"]
            )
        assert final == "yes"
        assert synth is expected_synth

    def test_falls_back_to_concatenation_when_synthesis_fails(self):
        executor = _make_executor()
        agent_outputs = _make_agent_outputs(("a", "yes"), ("b", "no"))

        with (
            patch(
                "temper_ai.stage.executors.sequential.get_collaboration",
                return_value={"mode": "consensus"},
            ),
            patch.object(executor, "_try_synthesis", return_value=None),
        ):
            final, synth = executor._resolve_final_output(
                agent_outputs, MagicMock(), "stage1", {}, MagicMock(), ["a", "b"]
            )
        assert "yes" in final or "no" in final
        assert synth is None


# ---------------------------------------------------------------------------
# _store_stage_output
# ---------------------------------------------------------------------------


class TestStoreStageOutput:
    def test_completed_status_when_all_succeed(self):
        state: dict = {}
        data = _make_stage_output_data(
            agents=["a", "b"],
            agent_statuses={"a": "success", "b": "success"},
        )
        SequentialStageExecutor._store_stage_output(state, "stage1", data)
        assert (
            state[StateKeys.STAGE_OUTPUTS]["stage1"][StateKeys.STAGE_STATUS]
            == "completed"
        )

    def test_failed_status_when_all_fail(self):
        state: dict = {}
        data = _make_stage_output_data(
            agents=["a"],
            agent_statuses={"a": {"status": "failed"}},
        )
        SequentialStageExecutor._store_stage_output(state, "stage1", data)
        assert (
            state[StateKeys.STAGE_OUTPUTS]["stage1"][StateKeys.STAGE_STATUS] == "failed"
        )

    def test_degraded_status_when_some_fail(self):
        state: dict = {}
        data = _make_stage_output_data(
            agents=["a", "b"],
            agent_statuses={"a": "success", "b": {"status": "failed"}},
        )
        SequentialStageExecutor._store_stage_output(state, "stage1", data)
        assert (
            state[StateKeys.STAGE_OUTPUTS]["stage1"][StateKeys.STAGE_STATUS]
            == "degraded"
        )

    def test_synthesis_result_stored(self):
        state: dict = {}
        synth = _make_synthesis_result()
        data = _make_stage_output_data(synthesis_result=synth)
        SequentialStageExecutor._store_stage_output(state, "stage1", data)
        assert "synthesis_result" in state[StateKeys.STAGE_OUTPUTS]["stage1"]

    def test_no_synthesis_result_not_in_output(self):
        state: dict = {}
        data = _make_stage_output_data(synthesis_result=None)
        SequentialStageExecutor._store_stage_output(state, "stage1", data)
        assert "synthesis_result" not in state[StateKeys.STAGE_OUTPUTS]["stage1"]

    def test_stage_outputs_initialised_when_missing(self):
        state: dict = {}  # No stage_outputs key
        data = _make_stage_output_data()
        SequentialStageExecutor._store_stage_output(state, "stage1", data)
        assert StateKeys.STAGE_OUTPUTS in state

    def test_context_meta_propagated(self):
        state: dict = {"_context_meta": {"source": "test"}}
        data = _make_stage_output_data()
        SequentialStageExecutor._store_stage_output(state, "stage1", data)
        assert "_context_meta" in state[StateKeys.STAGE_OUTPUTS]["stage1"]

    def test_structured_fields_included(self):
        state: dict = {}
        data = _make_stage_output_data()
        structured = {"key": "val"}
        SequentialStageExecutor._store_stage_output(
            state, "stage1", data, structured=structured
        )
        assert state[StateKeys.STAGE_OUTPUTS]["stage1"]["structured"] == structured

    def test_current_stage_updated(self):
        state: dict = {}
        data = _make_stage_output_data()
        SequentialStageExecutor._store_stage_output(state, "my_stage", data)
        assert state[StateKeys.CURRENT_STAGE] == "my_stage"


# ---------------------------------------------------------------------------
# _persist_stage_output
# ---------------------------------------------------------------------------


class TestPersistStageOutput:
    def test_no_op_when_no_tracker(self):
        state = {
            StateKeys.CURRENT_STAGE_ID: "sid-1",
            StateKeys.STAGE_OUTPUTS: {"stage1": {"out": "x"}},
        }
        SequentialStageExecutor._persist_stage_output(state, "stage1", None)

    def test_no_op_when_no_stage_id(self):
        from temper_ai.shared.core.protocols import TrackerProtocol

        tracker = MagicMock(spec=TrackerProtocol)
        tracker.set_stage_output = MagicMock()
        # No CURRENT_STAGE_ID in state
        state = {StateKeys.STAGE_OUTPUTS: {"stage1": {"out": "x"}}}
        SequentialStageExecutor._persist_stage_output(state, "stage1", tracker)
        tracker.set_stage_output.assert_not_called()

    def test_calls_set_stage_output_when_valid(self):
        from temper_ai.shared.core.protocols import TrackerProtocol

        tracker = MagicMock(spec=TrackerProtocol)
        tracker.set_stage_output = MagicMock()
        state = {
            StateKeys.CURRENT_STAGE_ID: "sid-1",
            StateKeys.STAGE_OUTPUTS: {"stage1": {"out": "x"}},
        }
        SequentialStageExecutor._persist_stage_output(state, "stage1", tracker)
        tracker.set_stage_output.assert_called_once()

    def test_logs_warning_on_exception(self):
        from temper_ai.shared.core.protocols import TrackerProtocol

        tracker = MagicMock(spec=TrackerProtocol)
        tracker.set_stage_output = MagicMock(side_effect=RuntimeError("fail"))
        state = {
            StateKeys.CURRENT_STAGE_ID: "sid-1",
            StateKeys.STAGE_OUTPUTS: {"stage1": {"out": "x"}},
        }
        SequentialStageExecutor._persist_stage_output(state, "stage1", tracker)
        # No exception raised

    def test_no_op_when_tracker_not_protocol_instance(self):
        tracker = object()  # Not a TrackerProtocol
        state = {
            StateKeys.CURRENT_STAGE_ID: "sid-1",
            StateKeys.STAGE_OUTPUTS: {"stage1": {"out": "x"}},
        }
        SequentialStageExecutor._persist_stage_output(state, "stage1", tracker)


# ---------------------------------------------------------------------------
# _execute_with_convergence
# ---------------------------------------------------------------------------


class TestExecuteWithConvergence:
    def test_stops_when_converged(self):
        executor = _make_executor()

        state: dict = {StateKeys.STAGE_OUTPUTS: {}}
        convergence_cfg = MagicMock()
        convergence_cfg.max_iterations = 10

        call_count = [0]

        def fake_execute_once(stage_name, stage_config, s, config_loader):
            call_count[0] += 1
            return {
                StateKeys.STAGE_OUTPUTS: {"stage1": {StateKeys.OUTPUT: "same_output"}}
            }

        with (
            patch.object(executor, "_execute_once", side_effect=fake_execute_once),
            patch(
                "temper_ai.stage.convergence.StageConvergenceDetector"
            ) as MockDetector,
        ):
            mock_detector = MockDetector.return_value
            # Converge on second check (after iteration 1)
            mock_detector.has_converged.side_effect = [False, True]
            executor._execute_with_convergence(
                "stage1", MagicMock(), state, MagicMock(), convergence_cfg
            )

        # Should have stopped after convergence
        assert call_count[0] >= 2

    def test_runs_max_iterations_without_convergence(self):
        executor = _make_executor()
        convergence_cfg = MagicMock()
        convergence_cfg.max_iterations = 3

        iteration_state: dict = {StateKeys.STAGE_OUTPUTS: {}}

        def fake_execute_once(stage_name, stage_config, s, config_loader):
            s.setdefault(StateKeys.STAGE_OUTPUTS, {})
            s[StateKeys.STAGE_OUTPUTS]["stage1"] = {
                StateKeys.OUTPUT: "different_each_time"
            }
            return s

        with (
            patch.object(executor, "_execute_once", side_effect=fake_execute_once),
            patch(
                "temper_ai.stage.convergence.StageConvergenceDetector"
            ) as MockDetector,
        ):
            mock_detector = MockDetector.return_value
            mock_detector.has_converged.return_value = False

            executor._execute_with_convergence(
                "stage1", MagicMock(), iteration_state, MagicMock(), convergence_cfg
            )

        # With max_iterations=3 and no convergence, has_converged called 2 times
        # (iteration 0: previous_output=None → skip; iteration 1,2: check)
        assert (
            mock_detector.has_converged.call_count == convergence_cfg.max_iterations - 1
        )


# ---------------------------------------------------------------------------
# _execute_once: script_outputs merge
# ---------------------------------------------------------------------------


class TestExecuteOnceScriptOutputs:
    def test_merges_script_outputs_into_structured(self):
        executor = _make_executor()
        state = {StateKeys.STAGE_OUTPUTS: {}}
        config_loader = MagicMock()

        agent_outputs = {
            "script_agent": {
                StateKeys.OUTPUT: "result",
                "script_outputs": {"key": "val_from_script"},
            }
        }

        with (
            patch.object(
                executor,
                "_run_agents_tracked",
                return_value=(agent_outputs, {"script_agent": "success"}, {}),
            ),
            patch(
                "temper_ai.stage.executors.sequential.get_collaboration",
                return_value=None,
            ),
            patch(
                "temper_ai.stage.executors.sequential.get_convergence",
                return_value=None,
            ),
            patch(
                "temper_ai.stage.executors.sequential.get_stage_agents",
                return_value=["script_agent"],
            ),
            patch(
                "temper_ai.stage.executors.sequential.get_error_handling",
                return_value=MagicMock(),
            ),
            patch(
                "temper_ai.stage.executors.sequential.stage_config_to_dict",
                return_value={},
            ),
            patch.object(executor, "_extract_structured_fields", return_value={}),
            patch.object(executor, "_persist_stage_output"),
        ):
            result = executor._execute_once("stage1", MagicMock(), state, config_loader)

        stage_out = result[StateKeys.STAGE_OUTPUTS]["stage1"]
        assert stage_out["structured"].get("key") == "val_from_script"
