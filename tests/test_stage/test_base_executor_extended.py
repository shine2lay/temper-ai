"""Extended tests for temper_ai/stage/executors/base.py.

Covers uncovered paths:
- ParallelRunner.run_parallel (abstract method documented)
- StageExecutor._extract_structured_fields (no extractor / no output / with extractor)
- StageExecutor._run_strategy_synthesis (leader / dialogue / default paths)
- StageExecutor._run_synthesis (coordinator fast-path / ImportError fallback)
- StageExecutor._run_dialogue_synthesis (budget stop / rounds)
- StageExecutor._budget_stop_result
- StageExecutor._run_leader_synthesis (no leader / success / exception fallback)
- StageExecutor._reinvoke_agents_with_dialogue
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from temper_ai.agent.strategies.base import SynthesisResult
from temper_ai.stage.executors.base import StageExecutor
from temper_ai.stage.executors.state_keys import StateKeys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_synthesis_result(decision="yes", method="consensus", confidence=0.9):
    result = SynthesisResult(
        decision=decision,
        confidence=confidence,
        method=method,
        votes={"yes": 1},
        conflicts=[],
        reasoning="ok",
        metadata={},
    )
    return result


def _make_agent_output(name="agent_a", decision="yes", confidence=0.9):
    from temper_ai.agent.strategies.base import AgentOutput

    return AgentOutput(
        agent_name=name,
        decision=decision,
        reasoning="because",
        confidence=confidence,
        metadata={},
    )


class ConcreteExecutor(StageExecutor):
    """Minimal concrete implementation for testing base class methods."""

    def execute_stage(
        self, stage_name, stage_config, state, config_loader, tool_registry=None
    ):
        return state

    def supports_stage_type(self, stage_type):
        return stage_type == "test"


# ---------------------------------------------------------------------------
# _extract_structured_fields
# ---------------------------------------------------------------------------


class TestExtractStructuredFields:
    def test_returns_empty_when_no_extractor(self):
        executor = ConcreteExecutor()
        executor.output_extractor = None
        result = executor._extract_structured_fields(
            MagicMock(), "some output", "stage1"
        )
        assert result == {}

    def test_returns_empty_when_no_raw_output(self):
        executor = ConcreteExecutor()
        executor.output_extractor = MagicMock()
        result = executor._extract_structured_fields(MagicMock(), "", "stage1")
        assert result == {}

    def test_returns_empty_when_no_output_decls(self):
        executor = ConcreteExecutor()
        executor.output_extractor = MagicMock()

        with (
            patch(
                "temper_ai.shared.utils.config_helpers.get_nested_value",
                return_value=None,
            ),
            patch(
                "temper_ai.workflow.context_schemas.parse_stage_outputs",
                return_value=None,
            ),
        ):
            result = executor._extract_structured_fields(
                MagicMock(), "output", "stage1"
            )
        assert result == {}

    def test_calls_extractor_with_output_decls(self):
        executor = ConcreteExecutor()
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = {"key": "value"}
        executor.output_extractor = mock_extractor

        with (
            patch(
                "temper_ai.shared.utils.config_helpers.get_nested_value",
                return_value={"key": "str"},
            ),
            patch(
                "temper_ai.workflow.context_schemas.parse_stage_outputs",
                return_value={"key": MagicMock()},
            ),
        ):
            result = executor._extract_structured_fields(
                MagicMock(), "raw output", "stage1"
            )
        assert result == {"key": "value"}
        mock_extractor.extract.assert_called_once()


# ---------------------------------------------------------------------------
# _run_synthesis (fast-path and fallback)
# ---------------------------------------------------------------------------


class TestRunSynthesis:
    def test_uses_coordinator_fast_path_when_present(self):
        executor = ConcreteExecutor()
        coordinator = MagicMock()
        expected = _make_synthesis_result()
        coordinator.synthesize.return_value = expected
        executor.synthesis_coordinator = coordinator

        outputs = [_make_agent_output()]
        result = executor._run_synthesis(outputs, MagicMock(), "stage1")
        coordinator.synthesize.assert_called_once()
        assert result is expected

    def test_falls_back_to_consensus_on_import_error(self):
        executor = ConcreteExecutor()
        # No synthesis_coordinator
        outputs = [_make_agent_output()]
        fallback = _make_synthesis_result(method="fallback_consensus")

        with (
            patch.object(
                executor,
                "_run_strategy_synthesis",
                side_effect=ImportError("no module"),
            ),
            patch(
                "temper_ai.stage.executors.base.fallback_consensus_synthesis",
                return_value=fallback,
            ) as mock_fallback,
        ):
            result = executor._run_synthesis(outputs, MagicMock(), "stage1")
        mock_fallback.assert_called_once()
        assert result is fallback


# ---------------------------------------------------------------------------
# _run_strategy_synthesis
# ---------------------------------------------------------------------------


class TestRunStrategySynthesis:
    def test_uses_leader_synthesis_when_leader_strategy(self):
        executor = ConcreteExecutor()
        outputs = [_make_agent_output()]
        stage_config = MagicMock()
        leader_result = _make_synthesis_result(method="leader")

        from temper_ai.stage.executors._protocols import LeaderCapableStrategy

        class FakeLeaderStrategy(LeaderCapableStrategy):
            requires_leader_synthesis = True

            def get_leader_agent_name(self, collab_config):
                return "leader"

            def format_team_outputs(self, outputs):
                return "text"

            def synthesize(self, outputs, collab_config):
                return leader_result

        mock_strategy = FakeLeaderStrategy()

        with (
            patch(
                "temper_ai.agent.strategies.registry.get_strategy_from_config",
                return_value=mock_strategy,
            ),
            patch.object(
                executor, "_run_leader_synthesis", return_value=leader_result
            ) as mock_leader,
        ):
            result = executor._run_strategy_synthesis(
                outputs, stage_config, "stage1", {}, MagicMock(), ["agent_a"]
            )
        mock_leader.assert_called_once()
        assert result is leader_result

    def test_uses_dialogue_synthesis_when_dialogue_strategy(self):
        executor = ConcreteExecutor()
        outputs = [_make_agent_output()]
        stage_config = MagicMock()
        dialogue_result = _make_synthesis_result(method="dialogue")

        from temper_ai.stage.executors._protocols import DialogueCapableStrategy

        class FakeDialogueStrategy(DialogueCapableStrategy):
            requires_requery = True

            def synthesize(self, outputs, collab_config):
                return dialogue_result

        mock_strategy = FakeDialogueStrategy()

        with (
            patch(
                "temper_ai.agent.strategies.registry.get_strategy_from_config",
                return_value=mock_strategy,
            ),
            patch.object(
                executor, "_run_dialogue_synthesis", return_value=dialogue_result
            ) as mock_dialogue,
        ):
            result = executor._run_strategy_synthesis(
                outputs,
                stage_config,
                "stage1",
                {},
                MagicMock(),
                ["agent_a"],
            )
        mock_dialogue.assert_called_once()
        assert result is dialogue_result

    def test_dialogue_fallback_logs_when_missing_state(self):
        executor = ConcreteExecutor()
        outputs = [_make_agent_output()]
        stage_config = MagicMock()
        default_result = _make_synthesis_result()

        from temper_ai.stage.executors._protocols import DialogueCapableStrategy

        class FakeDialogueStrategy(DialogueCapableStrategy):
            requires_requery = True

            def synthesize(self, agent_outputs, collab_config):
                return default_result

        mock_strategy = FakeDialogueStrategy()

        with (
            patch(
                "temper_ai.agent.strategies.registry.get_strategy_from_config",
                return_value=mock_strategy,
            ),
            patch(
                "temper_ai.stage._config_accessors.get_collaboration_inner_config",
                return_value={},
            ),
        ):
            # state=None triggers the warning log path
            result = executor._run_strategy_synthesis(
                outputs,
                stage_config,
                "stage1",
                None,  # state=None → warning
                None,
                None,
            )
        # Falls through to default synthesis
        assert result is default_result

    def test_default_synthesis_called_when_no_special_strategy(self):
        executor = ConcreteExecutor()
        outputs = [_make_agent_output()]
        stage_config = MagicMock()
        default_result = _make_synthesis_result()

        mock_strategy = MagicMock()
        mock_strategy.requires_leader_synthesis = False
        mock_strategy.requires_requery = False
        mock_strategy.synthesize.return_value = default_result

        with (
            patch(
                "temper_ai.agent.strategies.registry.get_strategy_from_config",
                return_value=mock_strategy,
            ),
            patch(
                "temper_ai.stage._config_accessors.get_collaboration_inner_config",
                return_value={},
            ),
        ):
            executor._run_strategy_synthesis(
                outputs, stage_config, "stage1", {}, MagicMock(), ["agent_a"]
            )
        mock_strategy.synthesize.assert_called_once()


# ---------------------------------------------------------------------------
# _budget_stop_result
# ---------------------------------------------------------------------------


class TestBudgetStopResult:
    def test_sets_early_stop_reason_to_budget(self):
        strategy = MagicMock()
        synth = _make_synthesis_result()
        strategy.synthesize.return_value = synth
        strategy.cost_budget_usd = 1.0

        result = StageExecutor._budget_stop_result(
            strategy, [_make_agent_output()], 2.0, "stage1"
        )
        assert result.metadata["early_stop_reason"] == "budget"

    def test_sets_dialogue_rounds_to_one(self):
        strategy = MagicMock()
        synth = _make_synthesis_result()
        strategy.synthesize.return_value = synth
        strategy.cost_budget_usd = 1.0

        result = StageExecutor._budget_stop_result(
            strategy, [_make_agent_output()], 2.0, "stage1"
        )
        assert result.metadata["dialogue_rounds"] == 1

    def test_stores_total_cost(self):
        strategy = MagicMock()
        synth = _make_synthesis_result()
        strategy.synthesize.return_value = synth
        strategy.cost_budget_usd = 0.5

        result = StageExecutor._budget_stop_result(
            strategy, [_make_agent_output()], 1.5, "stage1"
        )
        assert result.metadata["total_cost_usd"] == 1.5


# ---------------------------------------------------------------------------
# _run_dialogue_synthesis
# ---------------------------------------------------------------------------


class TestRunDialogueSynthesis:
    def _make_strategy(self, budget=None, max_rounds=3, min_rounds=1):
        strategy = MagicMock()
        strategy.cost_budget_usd = budget
        strategy.max_rounds = max_rounds
        strategy.min_rounds = min_rounds
        strategy.convergence_threshold = 0.5
        strategy.calculate_convergence.return_value = 0.9
        synth = _make_synthesis_result()
        strategy.synthesize.return_value = synth
        return strategy

    def test_budget_stop_when_initial_cost_exceeds_budget(self):
        executor = ConcreteExecutor()
        strategy = self._make_strategy(budget=0.001)

        initial_outputs = []
        # High-cost outputs to trigger budget stop
        out = MagicMock()
        out.agent_name = "agent_a"
        out.decision = "yes"
        out.reasoning = "r"
        out.confidence = 0.9
        out.metadata = {StateKeys.COST_USD: 10.0}
        initial_outputs = [out]

        with patch.object(
            executor, "_budget_stop_result", return_value=MagicMock()
        ) as mock_stop:
            with patch("temper_ai.stage.executors.base.track_dialogue_round"):
                executor._run_dialogue_synthesis(
                    initial_outputs=initial_outputs,
                    strategy=strategy,
                    stage_config=MagicMock(),
                    stage_name="stage1",
                    state={},
                    config_loader=MagicMock(),
                    agents=["agent_a"],
                )
        mock_stop.assert_called_once()

    def test_runs_dialogue_rounds_when_budget_ok(self):
        executor = ConcreteExecutor()
        strategy = self._make_strategy(budget=None, max_rounds=2)

        out = MagicMock()
        out.agent_name = "agent_a"
        out.decision = "yes"
        out.reasoning = "r"
        out.confidence = 0.9
        out.metadata = {StateKeys.COST_USD: 0.001}

        synth_result = _make_synthesis_result()
        synth_result.metadata = {}

        with (
            patch(
                "temper_ai.stage.executors.base.run_dialogue_rounds",
                return_value=(1, [out], 0.01, False, -1),
            ),
            patch(
                "temper_ai.stage.executors.base.build_final_synthesis_result",
                return_value=synth_result,
            ) as mock_build,
            patch("temper_ai.stage.executors.base.track_dialogue_round"),
        ):
            executor._run_dialogue_synthesis(
                initial_outputs=[out],
                strategy=strategy,
                stage_config=MagicMock(),
                stage_name="stage1",
                state={},
                config_loader=MagicMock(),
                agents=["agent_a"],
            )
        mock_build.assert_called_once()


# ---------------------------------------------------------------------------
# _run_leader_synthesis
# ---------------------------------------------------------------------------


class TestRunLeaderSynthesis:
    def _make_executor_with_mocks(self):
        executor = ConcreteExecutor()
        return executor

    def test_falls_back_to_consensus_when_no_leader_name(self):
        executor = self._make_executor_with_mocks()
        strategy = MagicMock()
        strategy.get_leader_agent_name.return_value = None
        expected = _make_synthesis_result()
        strategy.synthesize.return_value = expected

        with patch(
            "temper_ai.stage._config_accessors.get_collaboration_inner_config",
            return_value={},
        ):
            result = executor._run_leader_synthesis(
                [_make_agent_output()], strategy, MagicMock(), "stage1"
            )
        strategy.synthesize.assert_called_once()
        assert result is expected

    def test_raises_when_state_and_config_loader_missing(self):
        executor = self._make_executor_with_mocks()
        strategy = MagicMock()
        strategy.get_leader_agent_name.return_value = "leader"
        strategy.format_team_outputs.return_value = "team text"
        fallback = _make_synthesis_result()
        strategy.synthesize.return_value = fallback

        with patch(
            "temper_ai.stage._config_accessors.get_collaboration_inner_config",
            return_value={},
        ):
            # state=None triggers ValueError → falls back to consensus
            executor._run_leader_synthesis(
                [_make_agent_output()],
                strategy,
                MagicMock(),
                "stage1",
                state=None,
                config_loader=None,
            )
        strategy.synthesize.assert_called_once()

    def test_returns_leader_synthesis_on_success(self):
        executor = self._make_executor_with_mocks()
        strategy = MagicMock()
        strategy.get_leader_agent_name.return_value = "leader"
        strategy.format_team_outputs.return_value = "team outputs text"
        expected = _make_synthesis_result(method="leader")
        strategy.synthesize.return_value = expected

        leader_output = _make_agent_output("leader")

        with (
            patch(
                "temper_ai.stage._config_accessors.get_collaboration_inner_config",
                return_value={},
            ),
            patch.object(executor, "_invoke_leader_agent", return_value=leader_output),
        ):
            result = executor._run_leader_synthesis(
                [_make_agent_output()],
                strategy,
                MagicMock(),
                "stage1",
                state={},
                config_loader=MagicMock(),
            )
        assert result is expected

    def test_falls_back_on_leader_exception(self):
        executor = self._make_executor_with_mocks()
        strategy = MagicMock()
        strategy.get_leader_agent_name.return_value = "leader"
        strategy.format_team_outputs.return_value = "team text"
        fallback = _make_synthesis_result(method="consensus")
        strategy.synthesize.return_value = fallback

        with (
            patch(
                "temper_ai.stage._config_accessors.get_collaboration_inner_config",
                return_value={},
            ),
            patch.object(
                executor,
                "_invoke_leader_agent",
                side_effect=RuntimeError("leader failed"),
            ),
        ):
            result = executor._run_leader_synthesis(
                [_make_agent_output()],
                strategy,
                MagicMock(),
                "stage1",
                state={},
                config_loader=MagicMock(),
            )
        # Falls back to consensus
        strategy.synthesize.assert_called_once()
        assert result is fallback


# ---------------------------------------------------------------------------
# _reinvoke_agents_with_dialogue
# ---------------------------------------------------------------------------


class TestReinvokeAgentsWithDialogue:
    def test_delegates_to_reinvoke_agents_function(self):
        executor = ConcreteExecutor()
        params = MagicMock()
        expected = (["out"], {"agent_a": MagicMock()})

        with patch(
            "temper_ai.stage.executors._dialogue_helpers.reinvoke_agents_with_dialogue",
            return_value=expected,
        ) as mock_fn:
            result = executor._reinvoke_agents_with_dialogue(params)

        mock_fn.assert_called_once_with(params)
        assert result is expected

    def test_sets_extract_agent_name_fn_on_params(self):
        executor = ConcreteExecutor()
        params = MagicMock()
        params.extract_agent_name_fn = None

        with patch(
            "temper_ai.stage.executors._dialogue_helpers.reinvoke_agents_with_dialogue",
            return_value=([], {}),
        ):
            executor._reinvoke_agents_with_dialogue(params)

        # Should have been set to _extract_agent_name bound method
        assert params.extract_agent_name_fn == executor._extract_agent_name
