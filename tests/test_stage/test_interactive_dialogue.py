"""Tests for interactive turn-taking dialogue mode.

Covers:
- run_interactive_turns() — single agent per turn, round-robin, convergence, budget
- _invoke_single_interactive_agent()
- _all_agents_converged() / _find_previous_output()
- _track_interactive_turn()
- _run_interactive_synthesis() integration
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from temper_ai.agent.strategies.base import AgentOutput
from temper_ai.stage.executors._dialogue_helpers import (
    InteractiveTurnsParams,
    SingleInteractiveAgentParams,
    _all_agents_converged,
    _find_previous_output,
    _track_interactive_turn,
    run_interactive_turns,
)
from temper_ai.stage.executors.state_keys import StateKeys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_output(name="agent_a", decision="yes", confidence=0.9, cost=0.01):
    return AgentOutput(
        agent_name=name,
        decision=decision,
        reasoning=f"reasoning for {decision}",
        confidence=confidence,
        metadata={StateKeys.COST_USD: cost},
    )


def _make_strategy(
    mode="interactive",
    min_rounds=2,
    max_rounds=12,
    convergence_threshold=0.85,
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
    synth.decision = "final"
    synth.confidence = 0.9
    synth.method = "consensus"
    synth.metadata = {}
    s.synthesize.return_value = synth
    return s


def _make_interactive_params(
    agents,
    initial_outputs,
    strategy=None,
    max_turns=6,
    min_cycles=2,
    total_cost=0.0,
):
    if strategy is None:
        strategy = _make_strategy(max_rounds=max_turns, min_rounds=min_cycles)
    return InteractiveTurnsParams(
        executor=MagicMock(),
        strategy=strategy,
        agents=agents,
        stage_name="test_stage",
        state={},
        config_loader=MagicMock(),
        tracker=None,
        initial_outputs=initial_outputs,
        total_cost=total_cost,
        max_turns=max_turns,
        min_cycles=min_cycles,
        extract_agent_name_fn=lambda ref: ref,
    )


# ---------------------------------------------------------------------------
# run_interactive_turns
# ---------------------------------------------------------------------------


class TestRunInteractiveTurns:

    def test_single_agent_per_turn(self):
        """Verify only one agent invoked per turn."""
        agents = ["agent_a", "agent_b", "agent_c"]
        initial = [_make_output(n) for n in agents]
        params = _make_interactive_params(agents, initial, max_turns=4, min_cycles=10)

        invoked_agents = []

        def fake_invoke(single_params):
            invoked_agents.append(single_params.agent_name)
            return _make_output(single_params.agent_name), MagicMock()

        with (
            patch(
                "temper_ai.stage.executors._dialogue_helpers._invoke_single_interactive_agent",
                side_effect=fake_invoke,
            ),
            patch(
                "temper_ai.stage.executors._dialogue_helpers._track_interactive_turn",
            ),
        ):
            run_interactive_turns(params)

        # Each turn invokes exactly one agent
        assert len(invoked_agents) == 3  # turns 1, 2, 3

    def test_round_robin_order(self):
        """Agents cycle A->B->C->A->B->C."""
        agents = ["agent_a", "agent_b", "agent_c"]
        initial = [_make_output(n) for n in agents]
        params = _make_interactive_params(agents, initial, max_turns=7, min_cycles=100)

        invoked_agents = []

        def fake_invoke(single_params):
            invoked_agents.append(single_params.agent_name)
            return _make_output(single_params.agent_name), MagicMock()

        with (
            patch(
                "temper_ai.stage.executors._dialogue_helpers._invoke_single_interactive_agent",
                side_effect=fake_invoke,
            ),
            patch(
                "temper_ai.stage.executors._dialogue_helpers._track_interactive_turn",
            ),
        ):
            run_interactive_turns(params)

        # turn 1 -> idx 1 -> agent_b
        # turn 2 -> idx 2 -> agent_c
        # turn 3 -> idx 0 -> agent_a
        # turn 4 -> idx 1 -> agent_b
        # turn 5 -> idx 2 -> agent_c
        # turn 6 -> idx 0 -> agent_a
        assert invoked_agents == [
            "agent_b",
            "agent_c",
            "agent_a",
            "agent_b",
            "agent_c",
            "agent_a",
        ]

    def test_conversation_grows_each_turn(self):
        """Each turn adds one entry to conversation."""
        agents = ["agent_a", "agent_b"]
        initial = [_make_output(n) for n in agents]
        params = _make_interactive_params(agents, initial, max_turns=4, min_cycles=100)

        conversation_sizes = []

        def fake_invoke(single_params):
            conversation_sizes.append(len(single_params.conversation))
            return _make_output(single_params.agent_name), MagicMock()

        with (
            patch(
                "temper_ai.stage.executors._dialogue_helpers._invoke_single_interactive_agent",
                side_effect=fake_invoke,
            ),
            patch(
                "temper_ai.stage.executors._dialogue_helpers._track_interactive_turn",
            ),
        ):
            run_interactive_turns(params)

        # Initial seeds 2 entries; turn 1 sees 2, turn 2 sees 3, turn 3 sees 4
        assert conversation_sizes == [2, 3, 4]

    def test_previous_speakers_populated(self):
        """Agents receive previous_speakers in their input."""
        agents = ["agent_a", "agent_b"]
        initial = [_make_output(n) for n in agents]
        params = _make_interactive_params(agents, initial, max_turns=3, min_cycles=100)

        captured_params: list[SingleInteractiveAgentParams] = []

        def fake_invoke(single_params):
            captured_params.append(single_params)
            return _make_output(single_params.agent_name), MagicMock()

        with (
            patch(
                "temper_ai.stage.executors._dialogue_helpers._invoke_single_interactive_agent",
                side_effect=fake_invoke,
            ),
            patch(
                "temper_ai.stage.executors._dialogue_helpers._track_interactive_turn",
            ),
        ):
            run_interactive_turns(params)

        # Turn 1: agent_b speaks. Conversation has [a@0, b@0].
        # Turn 2: agent_a speaks. Conversation has [a@0, b@0, b@1].
        assert len(captured_params) == 2
        # Each agent sees the conversation context
        assert captured_params[0].agent_name == "agent_b"
        assert captured_params[1].agent_name == "agent_a"

    def test_convergence_after_min_cycles(self):
        """No convergence check before min_cycles complete."""
        agents = ["agent_a", "agent_b"]
        initial = [_make_output(n) for n in agents]
        strategy = _make_strategy(
            max_rounds=10, min_rounds=2, convergence_threshold=0.5
        )
        # Always returns high convergence
        strategy.calculate_convergence.return_value = 1.0

        params = _make_interactive_params(
            agents,
            initial,
            strategy=strategy,
            max_turns=10,
            min_cycles=2,
        )

        turn_count = [0]

        def fake_invoke(single_params):
            turn_count[0] += 1
            return _make_output(single_params.agent_name), MagicMock()

        with (
            patch(
                "temper_ai.stage.executors._dialogue_helpers._invoke_single_interactive_agent",
                side_effect=fake_invoke,
            ),
            patch(
                "temper_ai.stage.executors._dialogue_helpers._track_interactive_turn",
            ),
        ):
            _, _, _, converged, convergence_turn = run_interactive_turns(params)

        # With 2 agents and min_cycles=2, convergence can't happen until turn >= 4
        # (cycle = turn // 2). Turn 4 => cycle 2 >= min_cycles 2.
        assert converged is True
        assert convergence_turn >= 4

    def test_per_agent_convergence(self):
        """Each agent compared to own prior output for convergence."""
        agents = ["agent_a", "agent_b"]
        initial = [_make_output(n, decision="initial") for n in agents]
        strategy = _make_strategy(
            max_rounds=10, min_rounds=1, convergence_threshold=0.8
        )

        convergence_calls = []

        def fake_convergence(current, previous):
            convergence_calls.append((current[0].agent_name, previous[0].agent_name))
            return 0.9

        strategy.calculate_convergence.side_effect = fake_convergence

        params = _make_interactive_params(
            agents,
            initial,
            strategy=strategy,
            max_turns=10,
            min_cycles=1,
        )

        def fake_invoke(single_params):
            return (
                _make_output(single_params.agent_name, decision="stable"),
                MagicMock(),
            )

        with (
            patch(
                "temper_ai.stage.executors._dialogue_helpers._invoke_single_interactive_agent",
                side_effect=fake_invoke,
            ),
            patch(
                "temper_ai.stage.executors._dialogue_helpers._track_interactive_turn",
            ),
        ):
            run_interactive_turns(params)

        # Convergence should compare each agent to their own prior
        agent_names_checked = {c[0] for c in convergence_calls}
        assert "agent_a" in agent_names_checked
        assert "agent_b" in agent_names_checked

    def test_budget_stop_mid_conversation(self):
        """Stops when cost_budget exceeded."""
        agents = ["agent_a", "agent_b"]
        initial = [_make_output(n, cost=0.0) for n in agents]
        strategy = _make_strategy(
            max_rounds=10,
            min_rounds=100,
            cost_budget_usd=0.05,
        )

        params = _make_interactive_params(
            agents,
            initial,
            strategy=strategy,
            max_turns=10,
            min_cycles=100,
        )

        def fake_invoke(single_params):
            return _make_output(single_params.agent_name, cost=0.03), MagicMock()

        with (
            patch(
                "temper_ai.stage.executors._dialogue_helpers._invoke_single_interactive_agent",
                side_effect=fake_invoke,
            ),
            patch(
                "temper_ai.stage.executors._dialogue_helpers._track_interactive_turn",
            ),
        ):
            final_turn, _, total_cost, converged, _ = run_interactive_turns(params)

        assert converged is False
        assert total_cost >= 0.05
        # Should stop after 2 turns (0.03 + 0.03 = 0.06 >= 0.05)
        assert final_turn <= 2

    def test_max_turns_reached(self):
        """Stops at max_turns."""
        agents = ["agent_a", "agent_b"]
        initial = [_make_output(n) for n in agents]
        params = _make_interactive_params(agents, initial, max_turns=4, min_cycles=100)

        turn_count = [0]

        def fake_invoke(single_params):
            turn_count[0] += 1
            return _make_output(single_params.agent_name), MagicMock()

        with (
            patch(
                "temper_ai.stage.executors._dialogue_helpers._invoke_single_interactive_agent",
                side_effect=fake_invoke,
            ),
            patch(
                "temper_ai.stage.executors._dialogue_helpers._track_interactive_turn",
            ),
        ):
            final_turn, _, _, converged, _ = run_interactive_turns(params)

        assert converged is False
        # max_turns=4, range(1,4) = 3 turns
        assert turn_count[0] == 3
        assert final_turn == 3


# ---------------------------------------------------------------------------
# _all_agents_converged
# ---------------------------------------------------------------------------


class TestAllAgentsConverged:

    def test_false_when_too_few_entries(self):
        conversation = [
            {
                "agent": "a",
                "turn": 0,
                "output": "x",
                "reasoning": "r",
                "confidence": 0.9,
            },
        ]
        outputs = {"a": _make_output("a")}
        strategy = _make_strategy()
        assert _all_agents_converged(outputs, conversation, strategy, 1) is False

    def test_false_when_agent_has_no_previous(self):
        conversation = [
            {
                "agent": "a",
                "turn": 0,
                "output": "x",
                "reasoning": "r",
                "confidence": 0.9,
            },
            {
                "agent": "b",
                "turn": 1,
                "output": "y",
                "reasoning": "r",
                "confidence": 0.9,
            },
        ]
        outputs = {
            "a": _make_output("a"),
            "b": _make_output("b"),
        }
        strategy = _make_strategy()
        # agent_b only has 1 entry, agent_a only has 1 entry
        assert _all_agents_converged(outputs, conversation, strategy, 2) is False

    def test_true_when_all_converged(self):
        conversation = [
            {
                "agent": "a",
                "turn": 0,
                "output": "x",
                "reasoning": "r",
                "confidence": 0.9,
            },
            {
                "agent": "b",
                "turn": 1,
                "output": "y",
                "reasoning": "r",
                "confidence": 0.9,
            },
            {
                "agent": "a",
                "turn": 2,
                "output": "x",
                "reasoning": "r",
                "confidence": 0.9,
            },
            {
                "agent": "b",
                "turn": 3,
                "output": "y",
                "reasoning": "r",
                "confidence": 0.9,
            },
        ]
        outputs = {
            "a": _make_output("a", decision="x"),
            "b": _make_output("b", decision="y"),
        }
        strategy = _make_strategy(convergence_threshold=0.5)
        strategy.calculate_convergence.return_value = 0.95
        assert _all_agents_converged(outputs, conversation, strategy, 2) is True

    def test_false_when_one_agent_below_threshold(self):
        conversation = [
            {
                "agent": "a",
                "turn": 0,
                "output": "x",
                "reasoning": "r",
                "confidence": 0.9,
            },
            {
                "agent": "b",
                "turn": 1,
                "output": "y",
                "reasoning": "r",
                "confidence": 0.9,
            },
            {
                "agent": "a",
                "turn": 2,
                "output": "x",
                "reasoning": "r",
                "confidence": 0.9,
            },
            {
                "agent": "b",
                "turn": 3,
                "output": "z",
                "reasoning": "r",
                "confidence": 0.9,
            },
        ]
        outputs = {
            "a": _make_output("a", decision="x"),
            "b": _make_output("b", decision="z"),
        }
        strategy = _make_strategy(convergence_threshold=0.9)

        call_count = [0]

        def fake_convergence(current, previous):
            call_count[0] += 1
            # First agent converged, second not
            if call_count[0] == 1:
                return 0.95
            return 0.5

        strategy.calculate_convergence.side_effect = fake_convergence
        assert _all_agents_converged(outputs, conversation, strategy, 2) is False


# ---------------------------------------------------------------------------
# _find_previous_output
# ---------------------------------------------------------------------------


class TestFindPreviousOutput:

    def test_returns_none_when_single_entry(self):
        conversation = [
            {
                "agent": "a",
                "turn": 0,
                "output": "x",
                "reasoning": "r",
                "confidence": 0.9,
            },
        ]
        assert _find_previous_output(conversation, "a") is None

    def test_returns_none_when_agent_not_found(self):
        conversation = [
            {
                "agent": "b",
                "turn": 0,
                "output": "x",
                "reasoning": "r",
                "confidence": 0.9,
            },
        ]
        assert _find_previous_output(conversation, "a") is None

    def test_returns_second_to_last_output(self):
        conversation = [
            {
                "agent": "a",
                "turn": 0,
                "output": "first",
                "reasoning": "r1",
                "confidence": 0.8,
            },
            {
                "agent": "b",
                "turn": 1,
                "output": "bval",
                "reasoning": "rb",
                "confidence": 0.7,
            },
            {
                "agent": "a",
                "turn": 2,
                "output": "second",
                "reasoning": "r2",
                "confidence": 0.9,
            },
        ]
        result = _find_previous_output(conversation, "a")
        assert result is not None
        assert result.decision == "first"
        assert result.reasoning == "r1"
        assert result.confidence == 0.8
        assert isinstance(result, AgentOutput)


# ---------------------------------------------------------------------------
# _track_interactive_turn
# ---------------------------------------------------------------------------


class TestTrackInteractiveTurn:

    def test_calls_track_dialogue_round(self):
        output = _make_output("agent_a")
        strategy = _make_strategy()
        with patch(
            "temper_ai.stage.executors._dialogue_helpers.track_dialogue_round"
        ) as mock_track:
            _track_interactive_turn(None, strategy, {}, output, 1, "agent_a")
        mock_track.assert_called_once()
        params = mock_track.call_args[0][0]
        assert params.round_num == 1
        assert params.current_outputs == [output]
        assert params.round_outcome == "in_progress"


# ---------------------------------------------------------------------------
# Integration: _run_interactive_synthesis
# ---------------------------------------------------------------------------


class TestRunInteractiveSynthesisEndToEnd:

    def test_interactive_synthesis_end_to_end(self):
        """3 mock agents, interactive mode, run through executor."""
        from temper_ai.agent.strategies.constants import STRATEGY_NAME_INTERACTIVE

        strategy = _make_strategy(
            mode=STRATEGY_NAME_INTERACTIVE,
            max_rounds=5,
            min_rounds=1,
            convergence_threshold=0.5,
        )
        strategy.calculate_convergence.return_value = 1.0

        initial_outputs = [
            _make_output("a", cost=0.01),
            _make_output("b", cost=0.01),
            _make_output("c", cost=0.01),
        ]

        def fake_invoke(single_params):
            return _make_output(single_params.agent_name, cost=0.01), MagicMock()

        executor = MagicMock()
        executor._extract_agent_name = lambda ref: ref

        with (
            patch(
                "temper_ai.stage.executors._dialogue_helpers._invoke_single_interactive_agent",
                side_effect=fake_invoke,
            ),
            patch(
                "temper_ai.stage.executors._dialogue_helpers.track_dialogue_round",
            ),
        ):
            from temper_ai.stage.executors._dialogue_helpers import (
                InteractiveTurnsParams,
                run_interactive_turns,
            )

            final_turn, last_outputs, total_cost, converged, convergence_turn = (
                run_interactive_turns(
                    InteractiveTurnsParams(
                        executor=executor,
                        strategy=strategy,
                        agents=["a", "b", "c"],
                        stage_name="test_stage",
                        state={},
                        config_loader=MagicMock(),
                        tracker=None,
                        initial_outputs=initial_outputs,
                        total_cost=0.03,
                        max_turns=5,
                        min_cycles=1,
                        extract_agent_name_fn=lambda ref: ref,
                    )
                )
            )

        assert converged is True
        assert convergence_turn >= 3  # At least one full cycle
        assert len(last_outputs) == 3
        assert total_cost > 0.03  # Had some additional cost
