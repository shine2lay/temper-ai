"""Extended tests for temper_ai/stage/executors/parallel.py.

Covers uncovered paths:
- _print_stage_header (with/without detail console, with stream_cb)
- _persist_stage_output (with tracker / without / exception)
- _extract_collab_config
- ParallelStageExecutor._get_wall_clock_timeout
- ParallelStageExecutor._get_agents
- ParallelStageExecutor._build_agent_output_list
- ParallelStageExecutor._get_max_retries (dict / object with quality_gates / default)
- ParallelStageExecutor._handle_stage_error (skip / re-raise)
- ParallelStageExecutor._filter_leader_from_agents (import error / no leader / with leader)
- ParallelStageExecutor._create_agent_node
- ParallelStageExecutor._apply_synthesis_to_state (continue / done paths)
- ParallelStageExecutor.execute_stage (no tracker path)
- ParallelStageExecutor._execute_stage_core exhausted retries
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent.strategies.base import SynthesisResult
from temper_ai.stage.executors.base import ParallelRunner
from temper_ai.stage.executors.parallel import (
    ParallelStageExecutor,
    _extract_collab_config,
    _persist_stage_output,
    _print_stage_header,
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


class FakeParallelRunner(ParallelRunner):
    def __init__(self, result: dict | None = None):
        self._result = result or {
            "agent_outputs": {
                "agent_a": {
                    "output": "test",
                    "reasoning": "r",
                    "confidence": 0.9,
                    "metadata": {},
                },
                "__aggregate_metrics__": {},
            },
            "agent_statuses": {"agent_a": "success"},
            "agent_metrics": {},
        }

    def run_parallel(self, nodes, initial_state, *, init_node=None, collect_node=None):
        return dict(self._result)


def _make_executor(runner=None, synthesis_coordinator=None):
    exec = ParallelStageExecutor(
        parallel_runner=runner or FakeParallelRunner(),
        synthesis_coordinator=synthesis_coordinator,
    )
    return exec


# ---------------------------------------------------------------------------
# _print_stage_header
# ---------------------------------------------------------------------------


class TestPrintStageHeader:
    def test_no_op_when_show_details_false(self):
        state = {StateKeys.SHOW_DETAILS: False}
        _print_stage_header(state, "stage1")  # No exception

    def test_no_op_when_no_detail_console(self):
        state = {StateKeys.SHOW_DETAILS: True}
        _print_stage_header(state, "stage1")  # No exception

    def test_prints_header_when_enabled(self):
        console = MagicMock()
        state = {
            StateKeys.SHOW_DETAILS: True,
            StateKeys.DETAIL_CONSOLE: console,
            StateKeys.STAGE_OUTPUTS: {},
            StateKeys.TOTAL_STAGES: 5,
        }
        _print_stage_header(state, "stage1")
        console.print.assert_called_once()

    def test_sets_stream_callback_stage(self):
        console = MagicMock()
        stream_cb = MagicMock()
        stream_cb._current_stage = "old"
        state = {
            StateKeys.SHOW_DETAILS: True,
            StateKeys.DETAIL_CONSOLE: console,
            StateKeys.STREAM_CALLBACK: stream_cb,
            StateKeys.STAGE_OUTPUTS: {},
            StateKeys.TOTAL_STAGES: 2,
        }
        _print_stage_header(state, "my_stage")
        assert stream_cb._current_stage == "my_stage"


# ---------------------------------------------------------------------------
# _persist_stage_output
# ---------------------------------------------------------------------------


class TestPersistStageOutput:
    def test_no_op_when_no_tracker(self):
        _persist_stage_output(None, "sid-1", {}, "stage1")  # No exception

    def test_no_op_when_no_stage_id(self):
        tracker = MagicMock()
        _persist_stage_output(tracker, None, {}, "stage1")  # No exception

    def test_calls_set_stage_output_when_valid(self):
        from temper_ai.shared.core.protocols import TrackerProtocol

        tracker = MagicMock(spec=TrackerProtocol)
        # TrackerProtocol spec doesn't include set_stage_output; add it manually
        tracker.set_stage_output = MagicMock()
        state = {StateKeys.STAGE_OUTPUTS: {"stage1": {"output": "x"}}}
        _persist_stage_output(tracker, "sid-1", state, "stage1")
        tracker.set_stage_output.assert_called_once()

    def test_logs_warning_on_exception(self):
        from temper_ai.shared.core.protocols import TrackerProtocol

        tracker = MagicMock(spec=TrackerProtocol)
        tracker.set_stage_output = MagicMock(side_effect=RuntimeError("fail"))
        state = {StateKeys.STAGE_OUTPUTS: {"stage1": {"output": "x"}}}
        # Should not raise
        _persist_stage_output(tracker, "sid-1", state, "stage1")

    def test_no_op_when_stage_out_is_none(self):
        from temper_ai.shared.core.protocols import TrackerProtocol

        tracker = MagicMock(spec=TrackerProtocol)
        tracker.set_stage_output = MagicMock()
        state = {StateKeys.STAGE_OUTPUTS: {"stage1": None}}
        _persist_stage_output(tracker, "sid-1", state, "stage1")
        tracker.set_stage_output.assert_not_called()


# ---------------------------------------------------------------------------
# _extract_collab_config
# ---------------------------------------------------------------------------


class TestExtractCollabConfig:
    def test_delegates_to_get_collaboration_inner_config(self):
        stage_config = MagicMock()
        with patch(
            "temper_ai.stage.executors.parallel.get_collaboration_inner_config",
            return_value={"mode": "consensus"},
        ) as mock_fn:
            result = _extract_collab_config(stage_config)
        mock_fn.assert_called_once_with(stage_config)
        assert result == {"mode": "consensus"}


# ---------------------------------------------------------------------------
# ParallelStageExecutor._get_max_retries
# ---------------------------------------------------------------------------


class TestGetMaxRetries:
    def test_from_dict_stage_config(self):
        stage_config = {"quality_gates": {"max_retries": 5}}
        result = ParallelStageExecutor._get_max_retries(stage_config)
        assert result == 5

    def test_default_when_dict_has_no_quality_gates(self):
        stage_config = {}
        result = ParallelStageExecutor._get_max_retries(stage_config)
        from temper_ai.stage._schemas import QualityGatesConfig

        default = QualityGatesConfig.model_fields["max_retries"].default
        assert result == default

    def test_from_object_with_quality_gates(self):
        stage_config = MagicMock()
        stage_config.quality_gates = MagicMock()
        stage_config.quality_gates.max_retries = 7
        result = ParallelStageExecutor._get_max_retries(stage_config)
        assert result == 7

    def test_default_when_no_quality_gates_attr(self):
        stage_config = MagicMock()
        stage_config.quality_gates = None
        result = ParallelStageExecutor._get_max_retries(stage_config)
        from temper_ai.stage._schemas import QualityGatesConfig

        default = QualityGatesConfig.model_fields["max_retries"].default
        assert result == default


# ---------------------------------------------------------------------------
# ParallelStageExecutor._handle_stage_error
# ---------------------------------------------------------------------------


class TestHandleStageError:
    def test_reraises_when_policy_is_halt(self):
        state = {StateKeys.STAGE_OUTPUTS: {}}
        stage_config = {"error_handling": {"on_stage_failure": "halt"}}
        exc = RuntimeError("fail")
        executor = _make_executor()
        with pytest.raises(RuntimeError):
            executor._handle_stage_error("stage1", stage_config, state, exc)

    def test_skips_and_continues_when_policy_is_skip(self):
        state = {StateKeys.STAGE_OUTPUTS: {}}
        stage_config = {"error_handling": {"on_stage_failure": "skip"}}
        exc = RuntimeError("fail")
        executor = _make_executor()
        result = executor._handle_stage_error("stage1", stage_config, state, exc)
        assert result[StateKeys.STAGE_OUTPUTS].get("stage1") is None

    def test_reraises_for_non_dict_config_without_skip(self):
        state = {StateKeys.STAGE_OUTPUTS: {}}
        stage_config = MagicMock()
        # Non-dict config → stage_dict = {} → on_failure defaults to "halt"
        exc = RuntimeError("fail")
        executor = _make_executor()
        with pytest.raises(RuntimeError):
            executor._handle_stage_error("stage1", stage_config, state, exc)


# ---------------------------------------------------------------------------
# ParallelStageExecutor._filter_leader_from_agents
# ---------------------------------------------------------------------------


class TestFilterLeaderFromAgents:
    def test_returns_all_agents_on_import_error(self):
        executor = _make_executor()
        agents = ["agent_a", "agent_b"]

        with patch(
            "temper_ai.agent.strategies.registry.get_strategy_from_config",
            side_effect=ImportError("no module"),
        ):
            result = executor._filter_leader_from_agents(agents, MagicMock())
        assert result is agents

    def test_returns_all_agents_when_no_leader_strategy(self):
        executor = _make_executor()
        agents = ["agent_a", "agent_b"]
        # A plain MagicMock is NOT a LeaderCapableStrategy instance
        mock_strategy = MagicMock(spec=[])  # no attrs → not a LeaderCapableStrategy

        with patch(
            "temper_ai.agent.strategies.registry.get_strategy_from_config",
            return_value=mock_strategy,
        ):
            result = executor._filter_leader_from_agents(agents, MagicMock())
        assert result is agents

    def test_filters_leader_from_agents(self):
        executor = _make_executor()
        agents = ["agent_a", "leader_agent", "agent_b"]

        from temper_ai.stage.executors._protocols import LeaderCapableStrategy

        class FakeLeaderStrategy(LeaderCapableStrategy):
            requires_leader_synthesis = True

            def get_leader_agent_name(self, collab_config):
                return "leader_agent"

            def format_team_outputs(self, outputs):
                return "text"

            def synthesize(self, outputs, collab_config):
                return MagicMock()

        mock_strategy = FakeLeaderStrategy()

        with (
            patch(
                "temper_ai.agent.strategies.registry.get_strategy_from_config",
                return_value=mock_strategy,
            ),
            patch(
                "temper_ai.stage.executors.parallel._extract_collab_config",
                return_value={},
            ),
        ):
            result = executor._filter_leader_from_agents(agents, MagicMock())

        assert "leader_agent" not in result
        assert len(result) == 2

    def test_returns_all_when_no_leader_name(self):
        executor = _make_executor()
        agents = ["agent_a", "agent_b"]

        from temper_ai.stage.executors._protocols import LeaderCapableStrategy

        class FakeLeaderStrategy(LeaderCapableStrategy):
            requires_leader_synthesis = True

            def get_leader_agent_name(self, collab_config):
                return None

            def format_team_outputs(self, outputs):
                return ""

            def synthesize(self, outputs, collab_config):
                return MagicMock()

        mock_strategy = FakeLeaderStrategy()

        with (
            patch(
                "temper_ai.agent.strategies.registry.get_strategy_from_config",
                return_value=mock_strategy,
            ),
            patch(
                "temper_ai.stage.executors.parallel._extract_collab_config",
                return_value={},
            ),
        ):
            result = executor._filter_leader_from_agents(agents, MagicMock())
        assert result is agents


# ---------------------------------------------------------------------------
# ParallelStageExecutor._apply_synthesis_to_state (continue/done)
# ---------------------------------------------------------------------------


class TestApplySynthesisToState:
    def test_returns_continue_when_quality_gate_fails(self):
        executor = _make_executor()
        synth = _make_synthesis_result(confidence=0.1)  # low confidence

        state = {StateKeys.STAGE_OUTPUTS: {}}
        parallel_result = {"agent_outputs": {}, "agent_statuses": {}}

        with patch(
            "temper_ai.stage.executors.parallel.handle_quality_gate_failure",
            return_value="continue",
        ):
            with patch(
                "temper_ai.stage.executors.parallel.validate_quality_gates",
                return_value=(False, ["confidence too low"]),
            ):
                action = executor._apply_synthesis_to_state(
                    parallel_ctx=(parallel_result, {}, {}),
                    synth=synth,
                    stage_name="stage1",
                    stage_config={},
                    state=state,
                    wall_clock=(0.0, 60.0),
                    tracking_ctx=(None, None),
                )
        assert action == "continue"

    def test_returns_done_and_updates_state_on_pass(self):
        executor = _make_executor()
        synth = _make_synthesis_result()
        state = {StateKeys.STAGE_OUTPUTS: {}}

        with (
            patch(
                "temper_ai.stage.executors.parallel.validate_quality_gates",
                return_value=(True, []),
            ),
            patch(
                "temper_ai.stage.executors.parallel.handle_quality_gate_failure",
                return_value="done",
            ),
            patch("temper_ai.stage.executors.parallel.update_state_with_results"),
            patch("temper_ai.stage.executors.parallel._persist_stage_output"),
            patch.object(executor, "_extract_structured_fields", return_value={}),
        ):
            action = executor._apply_synthesis_to_state(
                parallel_ctx=({"agent_outputs": {}, "agent_statuses": {}}, {}, {}),
                synth=synth,
                stage_name="stage1",
                stage_config={},
                state=state,
                wall_clock=(0.0, 60.0),
                tracking_ctx=(None, None),
            )
        assert action == "done"


# ---------------------------------------------------------------------------
# ParallelStageExecutor.execute_stage without tracker
# ---------------------------------------------------------------------------


class TestExecuteStageNoTracker:
    def test_executes_without_tracker(self):
        synth = _make_synthesis_result()
        coordinator = MagicMock()
        coordinator.synthesize.return_value = synth

        executor = _make_executor(synthesis_coordinator=coordinator)

        state = {StateKeys.STAGE_OUTPUTS: {}}
        config_loader = MagicMock()
        config_loader.load_agent.return_value = {"agent": {"name": "agent_a"}}

        with (
            patch.object(
                executor, "_execute_stage_core", return_value=state
            ) as mock_core,
        ):
            result = executor.execute_stage(
                "stage1",
                {"stage": {"agents": ["agent_a"]}},
                state,
                config_loader,
            )
        mock_core.assert_called_once()
        assert result is state


# ---------------------------------------------------------------------------
# ParallelStageExecutor._execute_stage_core exhausted retries
# ---------------------------------------------------------------------------


class TestExecuteStageCoreExhaustedRetries:
    def test_raises_runtime_error_after_max_retries_exhausted(self):
        executor = _make_executor()

        stage_config = {"quality_gates": {"max_retries": 1}}
        state = {StateKeys.STAGE_OUTPUTS: {}, StateKeys.WORKFLOW_ID: "wf-1"}

        # Always return "continue" to force retry exhaustion
        with (
            patch.object(executor, "_get_agents", return_value=["agent_a"]),
            patch.object(
                executor,
                "_run_parallel_and_synthesize",
                return_value=(
                    {"agent_outputs": {}, "agent_statuses": {}},
                    {},
                    {},
                    _make_synthesis_result(),
                ),
            ),
            patch.object(
                executor, "_apply_synthesis_to_state", return_value="continue"
            ),
        ):
            with pytest.raises(RuntimeError, match="exhausted"):
                executor._execute_stage_core(
                    "stage1",
                    stage_config,
                    state,
                    MagicMock(),
                )


# ---------------------------------------------------------------------------
# ParallelStageExecutor._build_agent_output_list
# ---------------------------------------------------------------------------


class TestBuildAgentOutputList:
    def test_builds_list_from_dict(self):
        agent_outputs_dict = {
            "agent_a": {"output": "yes", "reasoning": "r", "confidence": 0.9},
            "agent_b": {"output": "no", "reasoning": "r2", "confidence": 0.8},
        }
        result = ParallelStageExecutor._build_agent_output_list(agent_outputs_dict)
        assert len(result) == 2
        names = {o.agent_name for o in result}
        assert names == {"agent_a", "agent_b"}

    def test_empty_dict_returns_empty_list(self):
        result = ParallelStageExecutor._build_agent_output_list({})
        assert result == []

    def test_uses_default_confidence_when_missing(self):
        from temper_ai.shared.constants.probabilities import PROB_VERY_HIGH

        agent_outputs_dict = {"agent_a": {"output": "yes"}}
        result = ParallelStageExecutor._build_agent_output_list(agent_outputs_dict)
        assert result[0].confidence == PROB_VERY_HIGH
