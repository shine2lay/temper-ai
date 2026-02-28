"""Tests for temper_ai/stage/executors/_dialogue_helpers.py.

Covers all major uncovered code paths:
- _extract_agent_role (metadata paths)
- _prepare_dialogue_input
- _curate_history_and_resolve_context (strategy / no-strategy)
- _build_and_execute_dialogue_agent (tracker / no-tracker)
- _invoke_single_dialogue_agent
- reinvoke_agents_with_dialogue
- fallback_consensus_synthesis
- record_dialogue_outputs_and_cost
- track_dialogue_round (tracker present/absent/exception)
- _build_dialogue_event_data (stances, empty outputs)
- _enrich_with_round_metrics (success / import error)
- check_dialogue_convergence (converged / not-converged)
- _check_convergence_and_track (min_rounds not reached / reached)
- execute_dialogue_round
- run_dialogue_rounds (convergence / budget / max-rounds)
- record_initial_round
- build_final_synthesis_result (converged / budget / max_rounds)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.stage.executors._dialogue_helpers import (
    DialogueReinvocationParams,
    DialogueRoundParams,
    DialogueRoundsParams,
    DialogueTrackingParams,
    FinalSynthesisResultParams,
    _build_dialogue_event_data,
    _check_convergence_and_track,
    _curate_history_and_resolve_context,
    _enrich_with_round_metrics,
    _extract_agent_role,
    _prepare_dialogue_input,
    build_final_synthesis_result,
    check_dialogue_convergence,
    execute_dialogue_round,
    fallback_consensus_synthesis,
    record_dialogue_outputs_and_cost,
    record_initial_round,
    reinvoke_agents_with_dialogue,
    run_dialogue_rounds,
    track_dialogue_round,
)
from temper_ai.stage.executors.state_keys import StateKeys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_output(name="agent_a", decision="yes", confidence=0.9, cost=0.01):
    out = MagicMock()
    out.agent_name = name
    out.decision = decision
    out.reasoning = "because"
    out.confidence = confidence
    out.metadata = {StateKeys.COST_USD: cost}
    return out


def _make_strategy(
    mode="consensus",
    min_rounds=1,
    max_rounds=3,
    convergence_threshold=0.8,
    cost_budget_usd=None,
):
    s = MagicMock()
    s.mode = mode
    s.min_rounds = min_rounds
    s.max_rounds = max_rounds
    s.convergence_threshold = convergence_threshold
    s.cost_budget_usd = cost_budget_usd
    s.calculate_convergence.return_value = 0.9
    synth = MagicMock()
    synth.decision = "final_decision"
    synth.confidence = 0.9
    synth.method = "consensus"
    synth.metadata = {}
    s.synthesize.return_value = synth
    return s


# ---------------------------------------------------------------------------
# _extract_agent_role
# ---------------------------------------------------------------------------


class TestExtractAgentRole:
    def test_returns_none_when_no_metadata(self):
        agent_config = MagicMock()
        agent_config.agent.metadata = None
        result = _extract_agent_role(agent_config)
        assert result is None

    def test_returns_none_when_no_metadata_attr(self):
        agent_config = MagicMock()
        agent_config.agent = MagicMock(spec=[])
        # agent has no 'metadata' attribute
        result = _extract_agent_role(agent_config)
        assert result is None

    def test_returns_tag_when_present(self):
        agent_config = MagicMock()
        agent_config.agent.metadata = MagicMock()
        agent_config.agent.metadata.tags = ["expert"]
        # no role attribute → fallback
        del agent_config.agent.metadata.role
        result = _extract_agent_role(agent_config)
        assert result == "expert"

    def test_returns_role_when_both_present(self):
        agent_config = MagicMock()
        agent_config.agent.metadata = MagicMock()
        agent_config.agent.metadata.tags = ["tag1"]
        agent_config.agent.metadata.role = "my_role"
        result = _extract_agent_role(agent_config)
        assert result == "my_role"

    def test_returns_none_when_tags_empty(self):
        agent_config = MagicMock()
        agent_config.agent.metadata = MagicMock()
        agent_config.agent.metadata.tags = []
        del agent_config.agent.metadata.role
        result = _extract_agent_role(agent_config)
        assert result is None


# ---------------------------------------------------------------------------
# _prepare_dialogue_input
# ---------------------------------------------------------------------------


class TestPrepareDialogueInput:
    def test_includes_dialogue_history(self):
        state = {"key": "val"}
        history = [{"agent": "a", "round": 0, "output": "x"}]
        result = _prepare_dialogue_input(state, history, 1, 3, "expert", {})
        assert result["dialogue_history"] == history

    def test_includes_round_number_and_max_rounds(self):
        result = _prepare_dialogue_input({}, [], 2, 5, None, {})
        assert result["round_number"] == 2
        assert result["max_rounds"] == 5

    def test_includes_agent_role(self):
        result = _prepare_dialogue_input({}, [], 1, 3, "critic", {})
        assert result["agent_role"] == "critic"

    def test_merges_mode_context(self):
        result = _prepare_dialogue_input({}, [], 1, 3, None, {"extra_key": "extra_val"})
        assert result["extra_key"] == "extra_val"

    def test_state_values_preserved(self):
        state = {"workflow_id": "wf-1", "user_query": "test"}
        result = _prepare_dialogue_input(state, [], 1, 3, None, {})
        assert result["workflow_id"] == "wf-1"
        assert result["user_query"] == "test"


# ---------------------------------------------------------------------------
# _curate_history_and_resolve_context
# ---------------------------------------------------------------------------


class TestCurateHistoryAndResolveContext:
    def test_no_strategy_returns_original_history(self):
        history = [{"agent": "a"}]
        curated, ctx = _curate_history_and_resolve_context(None, history, 1, "agent_a")
        assert curated is history
        assert ctx == {}

    def test_non_stance_strategy_returns_original_history(self):
        # Use a plain object that doesn't satisfy the StanceCuratingStrategy protocol
        strategy = type("NonStanceStrategy", (), {})()
        history = [{"agent": "b"}]
        curated, ctx = _curate_history_and_resolve_context(
            strategy, history, 2, "agent_b"
        )
        assert curated is history

    def test_stance_strategy_calls_curate_and_get_round_context(self):
        from temper_ai.stage.executors._protocols import StanceCuratingStrategy

        strategy = MagicMock(spec=StanceCuratingStrategy)
        strategy.curate_dialogue_history.return_value = [{"curated": True}]
        strategy.get_round_context.return_value = {"mode": "debate"}

        history = [{"agent": "a"}]
        curated, ctx = _curate_history_and_resolve_context(
            strategy, history, 1, "agent_a"
        )
        strategy.curate_dialogue_history.assert_called_once()
        strategy.get_round_context.assert_called_once_with(1, "agent_a")
        assert curated == [{"curated": True}]
        assert ctx == {"mode": "debate"}


# ---------------------------------------------------------------------------
# fallback_consensus_synthesis
# ---------------------------------------------------------------------------


class TestFallbackConsensusSynthesis:
    def test_returns_synthesis_result_with_fallback_method(self):
        outputs = [_make_agent_output("a"), _make_agent_output("b")]
        with (
            patch(
                "temper_ai.agent.strategies.base.extract_majority_decision",
                return_value="yes",
            ),
            patch(
                "temper_ai.agent.strategies.base.calculate_vote_distribution",
                return_value={"yes": 2},
            ),
            patch("temper_ai.agent.strategies.base.SynthesisResult") as mock_synth,
        ):
            mock_synth.return_value = MagicMock()
            fallback_consensus_synthesis(outputs)
            call_kwargs = mock_synth.call_args.kwargs
            assert call_kwargs["method"] == "fallback_consensus"

    def test_confidence_computed_from_votes(self):
        outputs = [_make_agent_output("a"), _make_agent_output("b")]
        with (
            patch(
                "temper_ai.agent.strategies.base.extract_majority_decision",
                return_value="yes",
            ),
            patch(
                "temper_ai.agent.strategies.base.calculate_vote_distribution",
                return_value={"yes": 2},
            ),
            patch("temper_ai.agent.strategies.base.SynthesisResult") as mock_synth,
        ):
            mock_synth.return_value = MagicMock()
            fallback_consensus_synthesis(outputs)
            call_kwargs = mock_synth.call_args.kwargs
            # confidence = votes["yes"] / len(outputs) = 2/2 = 1.0
            assert call_kwargs["confidence"] == 1.0

    def test_no_decision_uses_prob_medium(self):
        outputs = [_make_agent_output("a")]
        with (
            patch(
                "temper_ai.agent.strategies.base.extract_majority_decision",
                return_value=None,
            ),
            patch(
                "temper_ai.agent.strategies.base.calculate_vote_distribution",
                return_value={},
            ),
            patch("temper_ai.agent.strategies.base.SynthesisResult") as mock_synth,
            patch("temper_ai.shared.constants.probabilities.PROB_MEDIUM", 0.5),
        ):
            mock_synth.return_value = MagicMock()
            fallback_consensus_synthesis(outputs)
            call_kwargs = mock_synth.call_args.kwargs
            assert call_kwargs["confidence"] == 0.5


# ---------------------------------------------------------------------------
# record_dialogue_outputs_and_cost
# ---------------------------------------------------------------------------


class TestRecordDialogueOutputsAndCost:
    def test_appends_entry_for_each_output(self):
        outputs = [
            _make_agent_output("a", cost=0.05),
            _make_agent_output("b", cost=0.1),
        ]
        history: list = []
        stances = {"a": "agree", "b": "disagree"}
        record_dialogue_outputs_and_cost(outputs, 1, stances, history)
        assert len(history) == 2
        assert history[0]["agent"] == "a"
        assert history[0]["stance"] == "agree"
        assert history[1]["stance"] == "disagree"

    def test_cost_is_sum_of_output_costs(self):
        outputs = [
            _make_agent_output("a", cost=0.05),
            _make_agent_output("b", cost=0.10),
        ]
        history: list = []
        cost = record_dialogue_outputs_and_cost(outputs, 1, {}, history)
        assert abs(cost - 0.15) < 1e-9

    def test_no_stance_entry_when_stance_empty(self):
        outputs = [_make_agent_output("a")]
        history: list = []
        record_dialogue_outputs_and_cost(outputs, 1, {"a": ""}, history)
        assert "stance" not in history[0]

    def test_round_number_stored_in_history(self):
        outputs = [_make_agent_output("a")]
        history: list = []
        record_dialogue_outputs_and_cost(outputs, 3, {}, history)
        assert history[0]["round"] == 3


# ---------------------------------------------------------------------------
# track_dialogue_round
# ---------------------------------------------------------------------------


class TestTrackDialogueRound:
    def test_no_op_when_tracker_is_none(self):
        params = DialogueTrackingParams(
            tracker=None,
            strategy=_make_strategy(),
            state={},
            current_outputs=[],
            round_num=1,
            round_outcome="in_progress",
        )
        # Should not raise
        track_dialogue_round(params)

    def test_no_op_when_tracker_not_protocol(self):
        params = DialogueTrackingParams(
            tracker=object(),
            strategy=_make_strategy(),
            state={},
            current_outputs=[],
            round_num=1,
            round_outcome="in_progress",
        )
        track_dialogue_round(params)  # No exception

    def test_calls_track_collaboration_event_when_valid_tracker(self):
        from temper_ai.shared.core.protocols import TrackerProtocol

        tracker = MagicMock(spec=TrackerProtocol)
        strategy = _make_strategy()
        outputs = [_make_agent_output("a")]
        params = DialogueTrackingParams(
            tracker=tracker,
            strategy=strategy,
            state={StateKeys.CURRENT_STAGE_ID: "stage-1"},
            current_outputs=outputs,
            round_num=1,
            round_outcome="converged",
        )
        with patch(
            "temper_ai.observability._tracker_helpers.CollaborationEventData",
            autospec=True,
        ):
            track_dialogue_round(params)
        tracker.track_collaboration_event.assert_called_once()

    def test_logs_warning_on_exception(self):
        from temper_ai.shared.core.protocols import TrackerProtocol

        tracker = MagicMock(spec=TrackerProtocol)
        tracker.track_collaboration_event.side_effect = RuntimeError("boom")
        strategy = _make_strategy()
        outputs = [_make_agent_output("a")]
        params = DialogueTrackingParams(
            tracker=tracker,
            strategy=strategy,
            state={},
            current_outputs=outputs,
            round_num=1,
            round_outcome="in_progress",
        )
        with patch(
            "temper_ai.observability._tracker_helpers.CollaborationEventData",
            autospec=True,
        ):
            # Should not raise, just log warning
            track_dialogue_round(params)


# ---------------------------------------------------------------------------
# _build_dialogue_event_data
# ---------------------------------------------------------------------------


class TestBuildDialogueEventData:
    def test_includes_agent_count(self):
        outputs = [_make_agent_output("a"), _make_agent_output("b")]
        params = DialogueTrackingParams(
            tracker=None,
            strategy=_make_strategy(),
            state={},
            current_outputs=outputs,
            round_num=1,
            round_outcome="in_progress",
        )
        with patch(
            "temper_ai.stage.executors._dialogue_helpers._enrich_with_round_metrics"
        ):
            data = _build_dialogue_event_data(params, ["a", "b"])
        assert data["agent_count"] == 2

    def test_avg_confidence_computed(self):
        out_a = _make_agent_output("a", confidence=0.8)
        out_b = _make_agent_output("b", confidence=0.6)
        params = DialogueTrackingParams(
            tracker=None,
            strategy=_make_strategy(),
            state={},
            current_outputs=[out_a, out_b],
            round_num=1,
            round_outcome="in_progress",
        )
        with patch(
            "temper_ai.stage.executors._dialogue_helpers._enrich_with_round_metrics"
        ):
            data = _build_dialogue_event_data(params, ["a", "b"])
        assert abs(data["avg_confidence"] - 0.7) < 1e-9

    def test_stance_distribution_included_when_stances_present(self):
        outputs = [_make_agent_output("a")]
        params = DialogueTrackingParams(
            tracker=None,
            strategy=_make_strategy(),
            state={},
            current_outputs=outputs,
            round_num=1,
            round_outcome="in_progress",
            agent_stances={"a": "agree", "b": "agree"},
        )
        with patch(
            "temper_ai.stage.executors._dialogue_helpers._enrich_with_round_metrics"
        ):
            data = _build_dialogue_event_data(params, ["a"])
        assert "stance_distribution" in data
        assert data["stance_distribution"]["agree"] == 2

    def test_empty_outputs_gives_zero_avg_confidence(self):
        params = DialogueTrackingParams(
            tracker=None,
            strategy=_make_strategy(),
            state={},
            current_outputs=[],
            round_num=1,
            round_outcome="in_progress",
        )
        with patch(
            "temper_ai.stage.executors._dialogue_helpers._enrich_with_round_metrics"
        ):
            data = _build_dialogue_event_data(params, [])
        assert data["avg_confidence"] == 0.0


# ---------------------------------------------------------------------------
# _enrich_with_round_metrics
# ---------------------------------------------------------------------------


class TestEnrichWithRoundMetrics:
    def test_enriches_event_data_on_success(self):
        outputs = [_make_agent_output("a")]
        params = DialogueTrackingParams(
            tracker=None,
            strategy=_make_strategy(),
            state={},
            current_outputs=outputs,
            round_num=1,
            round_outcome="in_progress",
        )
        mock_metrics = MagicMock()
        mock_metrics.confidence_trajectory = [0.5, 0.8]
        mock_metrics.convergence_speed = 1.0
        mock_metrics.stance_changes = 0

        event_data: dict = {}
        with patch(
            "temper_ai.observability.dialogue_metrics.compute_round_metrics",
            return_value=mock_metrics,
        ):
            _enrich_with_round_metrics(params, event_data)

        assert event_data["confidence_trajectory"] == [0.5, 0.8]
        assert event_data["convergence_speed"] == 1.0

    def test_does_not_raise_on_import_error(self):
        params = DialogueTrackingParams(
            tracker=None,
            strategy=_make_strategy(),
            state={},
            current_outputs=[],
            round_num=1,
            round_outcome="in_progress",
        )
        event_data: dict = {}
        with patch(
            "temper_ai.observability.dialogue_metrics.compute_round_metrics",
            side_effect=ImportError("missing"),
        ):
            _enrich_with_round_metrics(params, event_data)
        # Should not raise, event_data remains empty for metric keys
        assert "confidence_trajectory" not in event_data

    def test_does_not_raise_on_general_exception(self):
        params = DialogueTrackingParams(
            tracker=None,
            strategy=_make_strategy(),
            state={},
            current_outputs=[],
            round_num=1,
            round_outcome="in_progress",
        )
        event_data: dict = {}
        with patch(
            "temper_ai.observability.dialogue_metrics.compute_round_metrics",
            side_effect=RuntimeError("fail"),
        ):
            _enrich_with_round_metrics(params, event_data)
        assert "confidence_trajectory" not in event_data


# ---------------------------------------------------------------------------
# check_dialogue_convergence
# ---------------------------------------------------------------------------


class TestCheckDialogueConvergence:
    def test_returns_converged_true_when_above_threshold(self):
        strategy = _make_strategy(convergence_threshold=0.8)
        strategy.calculate_convergence.return_value = 0.85
        current = [_make_agent_output("a")]
        previous = [_make_agent_output("a")]
        score, converged, outcome = check_dialogue_convergence(
            strategy, current, previous, 1, "stage1"
        )
        assert converged is True
        assert outcome == "converged"
        assert abs(score - 0.85) < 1e-9

    def test_returns_converged_false_when_below_threshold(self):
        strategy = _make_strategy(convergence_threshold=0.8)
        strategy.calculate_convergence.return_value = 0.5
        current = [_make_agent_output("a")]
        previous = [_make_agent_output("a")]
        score, converged, outcome = check_dialogue_convergence(
            strategy, current, previous, 1, "stage1"
        )
        assert converged is False
        assert outcome == "in_progress"

    def test_at_exact_threshold_returns_converged(self):
        strategy = _make_strategy(convergence_threshold=0.8)
        strategy.calculate_convergence.return_value = 0.8
        current = [_make_agent_output("a")]
        previous = []
        score, converged, outcome = check_dialogue_convergence(
            strategy, current, previous, 2, "stage2"
        )
        assert converged is True


# ---------------------------------------------------------------------------
# _check_convergence_and_track
# ---------------------------------------------------------------------------


class TestCheckConvergenceAndTrack:
    def test_skips_convergence_check_before_min_rounds(self):
        strategy = _make_strategy(min_rounds=3)
        current = [_make_agent_output("a")]
        params = DialogueRoundParams(
            round_num=1,
            reinvoke_fn=MagicMock(),
            agents=["agent_a"],
            strategy=strategy,
            stage_name="stage1",
            state={},
            config_loader=MagicMock(),
            tracker=None,
            dialogue_history=[],
            previous_outputs=current,
        )
        with patch("temper_ai.stage.executors._dialogue_helpers.track_dialogue_round"):
            score, converged, conv_round, outcome = _check_convergence_and_track(
                params, current, {}, "in_progress", None
            )
        assert converged is False
        assert conv_round == -1

    def test_checks_convergence_at_min_rounds(self):
        strategy = _make_strategy(min_rounds=1, convergence_threshold=0.5)
        strategy.calculate_convergence.return_value = 0.9
        current = [_make_agent_output("a")]
        previous = [_make_agent_output("a")]
        params = DialogueRoundParams(
            round_num=1,
            reinvoke_fn=MagicMock(),
            agents=["agent_a"],
            strategy=strategy,
            stage_name="stage1",
            state={},
            config_loader=MagicMock(),
            tracker=None,
            dialogue_history=[],
            previous_outputs=previous,
        )
        with patch("temper_ai.stage.executors._dialogue_helpers.track_dialogue_round"):
            score, converged, conv_round, outcome = _check_convergence_and_track(
                params, current, {}, "in_progress", None
            )
        assert converged is True
        assert conv_round == 1


# ---------------------------------------------------------------------------
# record_initial_round
# ---------------------------------------------------------------------------


class TestRecordInitialRound:
    def test_appends_to_history(self):
        out = _make_agent_output("a", decision="start", confidence=0.7, cost=0.03)
        history: list = []
        record_initial_round([out], history)
        assert len(history) == 1
        assert history[0]["agent"] == "a"
        assert history[0]["round"] == 0

    def test_returns_total_cost(self):
        out_a = _make_agent_output("a", cost=0.02)
        out_b = _make_agent_output("b", cost=0.03)
        history: list = []
        cost = record_initial_round([out_a, out_b], history)
        assert abs(cost - 0.05) < 1e-9

    def test_empty_outputs_returns_zero_cost(self):
        history: list = []
        cost = record_initial_round([], history)
        assert cost == 0.0
        assert history == []


# ---------------------------------------------------------------------------
# build_final_synthesis_result
# ---------------------------------------------------------------------------


class TestBuildFinalSynthesisResult:
    def _make_params(self, converged=True, conv_round=1, cost=0.5, budget=None):
        strategy = _make_strategy()
        strategy.cost_budget_usd = budget
        return FinalSynthesisResultParams(
            strategy=strategy,
            current_outputs=[_make_agent_output("a")],
            final_round=2,
            total_cost=cost,
            dialogue_history=[],
            converged=converged,
            convergence_round=conv_round,
            stage_name="test_stage",
        )

    def test_converged_sets_early_stop_convergence(self):
        params = self._make_params(converged=True, conv_round=1)
        result = build_final_synthesis_result(params)
        assert result.metadata["early_stop_reason"] == "convergence"
        assert result.metadata["convergence_round"] == 1
        assert result.metadata["converged"] is True

    def test_budget_exceeded_sets_early_stop_budget(self):
        params = self._make_params(converged=False, cost=1.0, budget=0.5)
        result = build_final_synthesis_result(params)
        assert result.metadata["early_stop_reason"] == "budget"

    def test_max_rounds_sets_early_stop_max_rounds(self):
        params = self._make_params(converged=False, cost=0.1, budget=None)
        result = build_final_synthesis_result(params)
        assert result.metadata["early_stop_reason"] == "max_rounds"

    def test_dialogue_rounds_stored(self):
        params = self._make_params()
        result = build_final_synthesis_result(params)
        # final_round=2 → 2+1=3 rounds
        assert result.metadata["dialogue_rounds"] == 3

    def test_total_cost_stored(self):
        params = self._make_params(cost=0.42)
        result = build_final_synthesis_result(params)
        assert result.metadata["total_cost_usd"] == 0.42

    def test_dialogue_history_stored(self):
        params = self._make_params()
        result = build_final_synthesis_result(params)
        assert "dialogue_history" in result.metadata


# ---------------------------------------------------------------------------
# run_dialogue_rounds
# ---------------------------------------------------------------------------


class TestRunDialogueRounds:
    def _make_params(self, strategy, executor, agents, state=None, tracker=None):
        return DialogueRoundsParams(
            executor=executor,
            strategy=strategy,
            agents=agents,
            stage_name="test_stage",
            state=state or {},
            config_loader=MagicMock(),
            tracker=tracker,
            dialogue_history=[],
            initial_outputs=[_make_agent_output("a")],
            total_cost=0.0,
        )

    def test_stops_on_convergence(self):
        strategy = _make_strategy(min_rounds=1, max_rounds=5, convergence_threshold=0.5)
        strategy.calculate_convergence.return_value = 0.9

        executor = MagicMock()
        outputs = [_make_agent_output("a", cost=0.01)]
        llm_providers = {}
        executor._reinvoke_agents_with_dialogue.return_value = (outputs, llm_providers)

        # Patch execute_dialogue_round to simulate convergence on first round
        with patch(
            "temper_ai.stage.executors._dialogue_helpers.execute_dialogue_round"
        ) as mock_exec:
            mock_exec.return_value = (
                outputs,  # current_outputs
                0.01,  # round_cost
                0.9,  # conv_score
                True,  # converged
                1,  # convergence_round
                "converged",  # round_outcome
            )
            params = self._make_params(strategy, executor, ["agent_a"])
            final_round, cur_out, total_cost, converged, conv_round = (
                run_dialogue_rounds(params)
            )
        assert converged is True
        assert conv_round == 1

    def test_stops_on_budget_exceeded(self):
        strategy = _make_strategy(min_rounds=1, max_rounds=5, cost_budget_usd=0.1)
        strategy.calculate_convergence.return_value = 0.1  # Won't converge

        executor = MagicMock()

        # Round returns high cost but no convergence
        with patch(
            "temper_ai.stage.executors._dialogue_helpers.execute_dialogue_round"
        ) as mock_exec:
            mock_exec.return_value = (
                [_make_agent_output("a")],
                0.5,  # round_cost exceeds budget
                0.1,
                False,
                -1,
                "in_progress",
            )
            params = self._make_params(strategy, executor, ["agent_a"])
            final_round, cur_out, total_cost, converged, conv_round = (
                run_dialogue_rounds(params)
            )
        assert converged is False
        assert total_cost >= 0.1  # budget check triggered

    def test_runs_max_rounds_without_convergence(self):
        strategy = _make_strategy(
            min_rounds=1, max_rounds=3, convergence_threshold=0.99
        )
        strategy.calculate_convergence.return_value = 0.1

        executor = MagicMock()
        call_count = [0]

        def fake_execute(round_params):
            call_count[0] += 1
            return (
                [_make_agent_output("a")],
                0.01,
                0.1,
                False,
                -1,
                "in_progress",
            )

        with patch(
            "temper_ai.stage.executors._dialogue_helpers.execute_dialogue_round",
            side_effect=fake_execute,
        ):
            params = self._make_params(strategy, executor, ["agent_a"])
            final_round, cur_out, total_cost, converged, conv_round = (
                run_dialogue_rounds(params)
            )
        # max_rounds=3, loop runs for range(1, 3) = 2 rounds
        assert call_count[0] == 2
        assert converged is False


# ---------------------------------------------------------------------------
# execute_dialogue_round
# ---------------------------------------------------------------------------


class TestExecuteDialogueRound:
    def test_returns_correct_structure(self):
        strategy = _make_strategy(min_rounds=1, convergence_threshold=0.5)
        strategy.calculate_convergence.return_value = 0.9

        outputs = [_make_agent_output("a", cost=0.05)]
        llm_providers = {}

        reinvoke_fn = MagicMock(return_value=(outputs, llm_providers))
        params = DialogueRoundParams(
            round_num=1,
            reinvoke_fn=reinvoke_fn,
            agents=["agent_a"],
            strategy=strategy,
            stage_name="stage1",
            state={},
            config_loader=MagicMock(),
            tracker=None,
            dialogue_history=[],
            previous_outputs=outputs,
        )
        with patch("temper_ai.stage.executors._dialogue_helpers.track_dialogue_round"):
            result = execute_dialogue_round(params)
        cur_out, cost, score, converged, conv_round, outcome = result
        assert len(cur_out) == 1
        assert cost == pytest.approx(0.05)

    def test_extracts_stances_for_stance_strategy(self):
        from temper_ai.stage.executors._protocols import StanceCuratingStrategy

        # Create a class satisfying StanceCuratingStrategy protocol
        class _StanceStub:
            min_rounds = 1
            max_rounds = 3
            convergence_threshold = 0.5

            def curate_dialogue_history(
                self, dialogue_history, current_round, agent_name
            ):
                return dialogue_history

            def get_round_context(self, round_num, agent_name):
                return {}

            def extract_stances(self, outputs, llm_providers):
                return {"a": "agree"}

            def calculate_convergence(self, current_outputs, previous_outputs):
                return 0.9

        strategy = _StanceStub()
        assert isinstance(strategy, StanceCuratingStrategy)
        synth = MagicMock()
        synth.metadata = {}

        outputs = [_make_agent_output("a", cost=0.01)]
        llm_providers = {"a": MagicMock()}
        reinvoke_fn = MagicMock(return_value=(outputs, llm_providers))

        params = DialogueRoundParams(
            round_num=1,
            reinvoke_fn=reinvoke_fn,
            agents=["agent_a"],
            strategy=strategy,
            stage_name="stage1",
            state={},
            config_loader=MagicMock(),
            tracker=None,
            dialogue_history=[],
            previous_outputs=outputs,
        )
        with (
            patch("temper_ai.stage.executors._dialogue_helpers.track_dialogue_round"),
            patch.object(
                strategy, "extract_stances", wraps=strategy.extract_stances
            ) as spy_extract,
        ):
            execute_dialogue_round(params)
        spy_extract.assert_called_once()


# ---------------------------------------------------------------------------
# reinvoke_agents_with_dialogue
# ---------------------------------------------------------------------------


class TestReinvokeAgentsWithDialogue:
    def test_invokes_agent_for_each_ref(self):
        params = DialogueReinvocationParams(
            agents=["agent_a", "agent_b"],
            stage_name="stage1",
            state={},
            config_loader=MagicMock(),
            dialogue_history=[],
            round_number=1,
            max_rounds=3,
            strategy=_make_strategy(),
            extract_agent_name_fn=lambda ref: ref,
        )
        fake_output = _make_agent_output("agent_a")
        fake_llm = MagicMock()
        with patch(
            "temper_ai.stage.executors._dialogue_helpers._invoke_single_dialogue_agent",
            return_value=(fake_output, fake_llm),
        ):
            outputs, providers = reinvoke_agents_with_dialogue(params)
        assert len(outputs) == 2
        assert len(providers) == 2

    def test_uses_extract_agent_name_fn(self):
        called_names = []

        def name_fn(ref):
            called_names.append(ref)
            return ref

        params = DialogueReinvocationParams(
            agents=["my_agent"],
            stage_name="stage1",
            state={},
            config_loader=MagicMock(),
            dialogue_history=[],
            round_number=1,
            max_rounds=3,
            strategy=_make_strategy(),
            extract_agent_name_fn=name_fn,
        )
        fake_output = _make_agent_output("my_agent")
        with patch(
            "temper_ai.stage.executors._dialogue_helpers._invoke_single_dialogue_agent",
            return_value=(fake_output, MagicMock()),
        ):
            reinvoke_agents_with_dialogue(params)
        assert "my_agent" in called_names
