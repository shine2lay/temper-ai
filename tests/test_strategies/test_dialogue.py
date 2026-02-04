"""Tests for DialogueOrchestrator collaboration strategy.

This test module verifies the DialogueOrchestrator implementation including:
- Initialization and configuration validation
- requires_requery property behavior
- synthesize() method and consensus delegation
- get_capabilities() reporting
- Data structure instantiation (DialogueRound, DialogueHistory)
- Edge cases (single agent, empty outputs)

Note: Multi-round dialogue execution logic is tested via executor integration
tests in test_executors/test_sequential.py and test_executors/test_parallel.py
"""

import pytest
from src.strategies.dialogue import (
    DialogueOrchestrator,
    DialogueRound,
    DialogueHistory
)
from src.strategies.base import AgentOutput, SynthesisResult


# Realistic metadata for agent outputs
REALISTIC_METADATA_RESEARCH = {
    "sources": 12,
    "confidence_factors": ["literature_review", "expert_consensus"],
    "evidence_quality": "high",
    "cost_usd": 0.5
}

REALISTIC_METADATA_ANALYSIS = {
    "sample_size": 5000,
    "statistical_significance": 0.01,
    "method": "quantitative_analysis",
    "cost_usd": 0.5
}

REALISTIC_METADATA_SYNTHESIS = {
    "supporting_evidence": "strong",
    "risk_level": "low",
    "implementation_difficulty": "moderate",
    "cost_usd": 0.5
}


class TestDialogueOrchestratorInitialization:
    """Test DialogueOrchestrator initialization and configuration."""

    def test_default_initialization(self):
        """Test initialization with default parameters."""
        strategy = DialogueOrchestrator()

        assert strategy.max_rounds == 3
        assert strategy.convergence_threshold == 0.85
        assert strategy.cost_budget_usd is None
        assert strategy.min_rounds == 1

    def test_custom_initialization(self):
        """Test initialization with custom parameters."""
        strategy = DialogueOrchestrator(
            max_rounds=5,
            convergence_threshold=0.90,
            cost_budget_usd=20.0,
            min_rounds=2
        )

        assert strategy.max_rounds == 5
        assert strategy.convergence_threshold == 0.90
        assert strategy.cost_budget_usd == 20.0
        assert strategy.min_rounds == 2

    def test_invalid_max_rounds_raises(self):
        """Test that max_rounds < 1 raises ValueError."""
        with pytest.raises(ValueError, match="max_rounds must be >= 1"):
            DialogueOrchestrator(max_rounds=0)

        with pytest.raises(ValueError, match="max_rounds must be >= 1"):
            DialogueOrchestrator(max_rounds=-1)

    def test_invalid_min_rounds_raises(self):
        """Test that min_rounds < 1 raises ValueError."""
        with pytest.raises(ValueError, match="min_rounds must be >= 1"):
            DialogueOrchestrator(min_rounds=0)

        with pytest.raises(ValueError, match="min_rounds must be >= 1"):
            DialogueOrchestrator(min_rounds=-1)

    def test_invalid_convergence_threshold_too_high(self):
        """Test that convergence_threshold > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="convergence_threshold must be in"):
            DialogueOrchestrator(convergence_threshold=1.5)

    def test_invalid_convergence_threshold_negative(self):
        """Test that negative convergence_threshold raises ValueError."""
        with pytest.raises(ValueError, match="convergence_threshold must be in"):
            DialogueOrchestrator(convergence_threshold=-0.1)

    def test_valid_convergence_threshold_boundaries(self):
        """Test that convergence_threshold boundaries (0.0, 1.0) are valid."""
        strategy_zero = DialogueOrchestrator(convergence_threshold=0.0)
        assert strategy_zero.convergence_threshold == 0.0

        strategy_one = DialogueOrchestrator(convergence_threshold=1.0)
        assert strategy_one.convergence_threshold == 1.0

    def test_invalid_cost_budget_negative(self):
        """Test that negative cost_budget_usd raises ValueError."""
        with pytest.raises(ValueError, match="cost_budget_usd must be > 0"):
            DialogueOrchestrator(cost_budget_usd=-10.0)

    def test_invalid_cost_budget_zero(self):
        """Test that zero cost_budget_usd raises ValueError."""
        with pytest.raises(ValueError, match="cost_budget_usd must be > 0"):
            DialogueOrchestrator(cost_budget_usd=0.0)

    def test_none_cost_budget_allowed(self):
        """Test that None cost_budget_usd is valid (unlimited)."""
        strategy = DialogueOrchestrator(cost_budget_usd=None)
        assert strategy.cost_budget_usd is None


class TestDialogueOrchestratorProperties:
    """Test DialogueOrchestrator properties."""

    def test_requires_requery_always_true(self):
        """Test that requires_requery always returns True."""
        strategy = DialogueOrchestrator()
        assert strategy.requires_requery is True

        # Test with different configurations
        strategy_custom = DialogueOrchestrator(
            max_rounds=10,
            convergence_threshold=0.95
        )
        assert strategy_custom.requires_requery is True

    def test_requires_requery_is_property(self):
        """Test that requires_requery is a read-only property."""
        strategy = DialogueOrchestrator()

        # Verify it's a property, not just an attribute
        assert hasattr(DialogueOrchestrator, 'requires_requery')
        assert isinstance(
            getattr(type(strategy), 'requires_requery'),
            property
        )


class TestDialogueOrchestratorSynthesize:
    """Test DialogueOrchestrator synthesize() method."""

    def test_synthesize_unanimous_decision(self):
        """Test synthesis with unanimous agent agreement."""
        strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, REALISTIC_METADATA_RESEARCH),
            AgentOutput("agent2", "Option A", "reason2", 0.8, REALISTIC_METADATA_ANALYSIS),
            AgentOutput("agent3", "Option A", "reason3", 0.85, REALISTIC_METADATA_SYNTHESIS)
        ]

        result = strategy.synthesize(outputs, {})

        assert result.decision == "Option A"
        assert result.confidence > 0.8  # High confidence for unanimous
        assert result.metadata["strategy"] == "dialogue"
        assert result.metadata["synthesis_method"] == "consensus_from_final_round"
        assert result.votes["Option A"] == 3

    def test_synthesize_majority_decision(self):
        """Test synthesis with majority decision (2/3 agree)."""
        strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, REALISTIC_METADATA_RESEARCH),
            AgentOutput("agent2", "Option A", "reason2", 0.8, REALISTIC_METADATA_ANALYSIS),
            AgentOutput("agent3", "Option B", "reason3", 0.7, REALISTIC_METADATA_SYNTHESIS)
        ]

        result = strategy.synthesize(outputs, {})

        assert result.decision == "Option A"
        assert result.votes == {"Option A": 2, "Option B": 1}
        assert result.metadata["strategy"] == "dialogue"
        assert result.metadata["synthesis_method"] == "consensus_from_final_round"

    def test_synthesize_delegates_to_consensus(self):
        """Test that synthesize delegates to ConsensusStrategy."""
        strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {})
        ]

        result = strategy.synthesize(outputs, {})

        # Consensus strategy metadata should be present
        assert result.method == "consensus"
        # Dialogue-specific metadata added
        assert result.metadata["strategy"] == "dialogue"
        assert result.metadata["synthesis_method"] == "consensus_from_final_round"

    def test_synthesize_with_single_agent(self):
        """Test synthesis with single agent (edge case)."""
        strategy = DialogueOrchestrator()
        outputs = [AgentOutput("agent1", "Option A", "reason", 0.9, {})]

        result = strategy.synthesize(outputs, {})

        assert result.decision == "Option A"
        assert result.confidence == 0.9  # 100% support * 0.9 confidence
        assert result.metadata["strategy"] == "dialogue"

    def test_synthesize_empty_outputs_raises(self):
        """Test that empty outputs raises ValueError."""
        strategy = DialogueOrchestrator()

        with pytest.raises(ValueError, match="cannot be empty"):
            strategy.synthesize([], {})

    def test_synthesize_passes_config_to_consensus(self):
        """Test that config is passed to consensus strategy."""
        strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option B", "reason3", 0.7, {}),
            AgentOutput("agent4", "Option C", "reason4", 0.6, {})
        ]

        # Pass min_consensus config to consensus strategy
        result = strategy.synthesize(outputs, {"min_consensus": 0.75})

        # Should use weak consensus since 2/4 = 50% < 75%
        assert result.method == "consensus_weak"
        assert result.metadata["needs_conflict_resolution"] is True

    def test_synthesize_preserves_agent_metadata(self):
        """Test that agent metadata is preserved in synthesis."""
        strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "A", "r", 0.9, {"cost_usd": 0.5, "tokens": 1000}),
            AgentOutput("agent2", "A", "r", 0.8, {"cost_usd": 0.6, "tokens": 1200})
        ]

        result = strategy.synthesize(outputs, {})

        # Result should still be valid
        assert result.decision == "A"
        assert result.metadata["strategy"] == "dialogue"


class TestDialogueOrchestratorCapabilities:
    """Test DialogueOrchestrator get_capabilities() method."""

    def test_get_capabilities(self):
        """Test that capabilities are correctly reported."""
        strategy = DialogueOrchestrator()
        caps = strategy.get_capabilities()

        assert caps["supports_debate"] is True
        assert caps["supports_convergence"] is True
        assert caps["supports_merit_weighting"] is False
        assert caps["supports_partial_participation"] is False
        assert caps["supports_async"] is False
        assert caps["supports_streaming"] is False

    def test_capabilities_are_consistent(self):
        """Test that capabilities match implementation."""
        strategy = DialogueOrchestrator()
        caps = strategy.get_capabilities()

        # Dialogue requires requery, so supports_debate should be True
        assert caps["supports_debate"] is True
        assert strategy.requires_requery is True

    def test_capabilities_independent_of_config(self):
        """Test that capabilities don't change with configuration."""
        strategy_default = DialogueOrchestrator()
        strategy_custom = DialogueOrchestrator(
            max_rounds=10,
            convergence_threshold=0.95,
            cost_budget_usd=50.0
        )

        caps_default = strategy_default.get_capabilities()
        caps_custom = strategy_custom.get_capabilities()

        assert caps_default == caps_custom


class TestDialogueRoundDataClass:
    """Test DialogueRound dataclass."""

    def test_dialogue_round_creation(self):
        """Test creating a dialogue round."""
        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]

        round_data = DialogueRound(
            round_number=0,
            agent_outputs=outputs,
            convergence_score=0.5,
            position_stability_score=0.75,
            new_insights=True,
            round_cost_usd=1.0,
            cumulative_cost_usd=1.0,
            metadata={"duration_seconds": 5.2}
        )

        assert round_data.round_number == 0
        assert len(round_data.agent_outputs) == 1
        assert round_data.convergence_score == 0.5
        assert round_data.position_stability_score == 0.75
        assert round_data.new_insights is True
        assert round_data.round_cost_usd == 1.0
        assert round_data.cumulative_cost_usd == 1.0
        assert round_data.metadata["duration_seconds"] == 5.2

    def test_dialogue_round_default_values(self):
        """Test dialogue round with default values."""
        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]

        round_data = DialogueRound(
            round_number=0,
            agent_outputs=outputs
        )

        assert round_data.convergence_score == 0.0
        assert round_data.position_stability_score == 0.0
        assert round_data.new_insights is True
        assert round_data.round_cost_usd == 0.0
        assert round_data.cumulative_cost_usd == 0.0
        assert round_data.metadata == {}

    def test_dialogue_round_cost_tracking(self):
        """Test cost tracking across rounds."""
        outputs1 = [AgentOutput("a1", "A", "r", 0.8, {"cost_usd": 0.5})]
        outputs2 = [AgentOutput("a1", "A", "r", 0.8, {"cost_usd": 0.5})]

        round1 = DialogueRound(
            round_number=0,
            agent_outputs=outputs1,
            round_cost_usd=0.5,
            cumulative_cost_usd=0.5
        )

        round2 = DialogueRound(
            round_number=1,
            agent_outputs=outputs2,
            round_cost_usd=0.5,
            cumulative_cost_usd=1.0  # Cumulative
        )

        assert round1.cumulative_cost_usd == 0.5
        assert round2.cumulative_cost_usd == 1.0

    def test_dialogue_round_multiple_agents(self):
        """Test dialogue round with multiple agents."""
        outputs = [
            AgentOutput("a1", "A", "r1", 0.9, {}),
            AgentOutput("a2", "A", "r2", 0.8, {}),
            AgentOutput("a3", "B", "r3", 0.7, {})
        ]

        round_data = DialogueRound(
            round_number=0,
            agent_outputs=outputs
        )

        assert len(round_data.agent_outputs) == 3
        assert round_data.agent_outputs[0].agent_name == "a1"
        assert round_data.agent_outputs[1].agent_name == "a2"
        assert round_data.agent_outputs[2].agent_name == "a3"


class TestDialogueHistoryDataClass:
    """Test DialogueHistory dataclass."""

    def test_dialogue_history_creation(self):
        """Test creating dialogue history."""
        outputs = [AgentOutput("a1", "A", "r", 0.8, {})]
        round1 = DialogueRound(round_number=0, agent_outputs=outputs)
        round2 = DialogueRound(round_number=1, agent_outputs=outputs)

        history = DialogueHistory(
            rounds=[round1, round2],
            total_rounds=2,
            converged=True,
            convergence_round=1,
            early_stop_reason="convergence",
            total_cost_usd=2.0,
            agent_participation={"a1": 2}
        )

        assert len(history.rounds) == 2
        assert history.total_rounds == 2
        assert history.converged is True
        assert history.convergence_round == 1
        assert history.early_stop_reason == "convergence"
        assert history.total_cost_usd == 2.0
        assert history.agent_participation["a1"] == 2

    def test_dialogue_history_default_values(self):
        """Test dialogue history with default values."""
        history = DialogueHistory()

        assert history.rounds == []
        assert history.total_rounds == 0
        assert history.converged is False
        assert history.convergence_round == 0
        assert history.early_stop_reason is None
        assert history.total_cost_usd == 0.0
        assert history.agent_participation == {}

    def test_dialogue_history_early_stop_reasons(self):
        """Test different early stop reasons."""
        # Convergence stop
        history_converged = DialogueHistory(
            rounds=[],
            total_rounds=2,
            converged=True,
            convergence_round=1,
            early_stop_reason="convergence"
        )
        assert history_converged.early_stop_reason == "convergence"

        # Budget stop
        history_budget = DialogueHistory(
            rounds=[],
            total_rounds=1,
            converged=False,
            early_stop_reason="budget"
        )
        assert history_budget.early_stop_reason == "budget"

        # Max rounds stop
        history_max = DialogueHistory(
            rounds=[],
            total_rounds=3,
            converged=False,
            early_stop_reason="max_rounds"
        )
        assert history_max.early_stop_reason == "max_rounds"

    def test_dialogue_history_agent_participation_tracking(self):
        """Test agent participation tracking."""
        history = DialogueHistory(
            rounds=[],
            total_rounds=3,
            agent_participation={
                "agent1": 3,
                "agent2": 3,
                "agent3": 2  # Joined late or dropped early
            }
        )

        assert history.agent_participation["agent1"] == 3
        assert history.agent_participation["agent2"] == 3
        assert history.agent_participation["agent3"] == 2

    def test_dialogue_history_no_convergence(self):
        """Test history when dialogue doesn't converge."""
        history = DialogueHistory(
            rounds=[],
            total_rounds=3,
            converged=False,
            convergence_round=0,  # Not converged
            early_stop_reason="max_rounds"
        )

        assert history.converged is False
        assert history.convergence_round == 0
        assert history.early_stop_reason == "max_rounds"


class TestDialogueOrchestratorEdgeCases:
    """Test edge cases and error conditions."""

    def test_single_round_configuration(self):
        """Test dialogue with max_rounds=1 (no multi-round)."""
        strategy = DialogueOrchestrator(max_rounds=1)
        outputs = [
            AgentOutput("agent1", "A", "r1", 0.9, {}),
            AgentOutput("agent2", "A", "r2", 0.8, {})
        ]

        result = strategy.synthesize(outputs, {})

        assert result.decision == "A"
        assert result.metadata["strategy"] == "dialogue"

    def test_high_convergence_threshold(self):
        """Test with very high convergence threshold."""
        strategy = DialogueOrchestrator(convergence_threshold=0.99)

        # Configuration should be valid
        assert strategy.convergence_threshold == 0.99

    def test_low_convergence_threshold(self):
        """Test with very low convergence threshold."""
        strategy = DialogueOrchestrator(convergence_threshold=0.1)

        # Configuration should be valid
        assert strategy.convergence_threshold == 0.1

    def test_min_rounds_greater_than_max_rounds(self):
        """Test that min_rounds > max_rounds is allowed (executor enforces)."""
        # This is allowed at strategy level, executor handles the logic
        strategy = DialogueOrchestrator(min_rounds=5, max_rounds=3)

        assert strategy.min_rounds == 5
        assert strategy.max_rounds == 3

    def test_synthesize_with_conflicting_agents(self):
        """Test synthesis with complete disagreement."""
        strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", "A", "r1", 0.8, {}),
            AgentOutput("agent2", "B", "r2", 0.8, {}),
            AgentOutput("agent3", "C", "r3", 0.8, {})
        ]

        result = strategy.synthesize(outputs, {})

        # Should still return a result (consensus handles tie-breaking)
        assert result.decision in ["A", "B", "C"]
        assert result.method in ["consensus_weak", "consensus"]
        assert result.metadata["strategy"] == "dialogue"

    def test_synthesize_with_different_decision_types(self):
        """Test synthesis with different decision types (int, str, etc.)."""
        strategy = DialogueOrchestrator()
        outputs = [
            AgentOutput("agent1", 1, "reason1", 0.9, {}),
            AgentOutput("agent2", 1, "reason2", 0.8, {}),
            AgentOutput("agent3", 2, "reason3", 0.7, {})
        ]

        result = strategy.synthesize(outputs, {})

        # Decision type should be preserved (int, not str)
        assert result.decision == 1
        assert isinstance(result.decision, int)
        assert result.votes == {1: 2, 2: 1}


class TestDialogueOrchestratorIntegration:
    """Test integration scenarios and realistic use cases."""

    def test_architecture_decision_scenario(self):
        """Test realistic scenario: architecture decision dialogue."""
        strategy = DialogueOrchestrator(
            max_rounds=3,
            convergence_threshold=0.85,
            cost_budget_usd=10.0
        )

        # Simulate final round outputs after dialogue
        outputs = [
            AgentOutput(
                "architect",
                "Use microservices",
                "Better scalability and team autonomy",
                0.85,
                {"cost_usd": 0.5, "dialogue_rounds": 3}
            ),
            AgentOutput(
                "security_engineer",
                "Use microservices",
                "Agreed after reviewing security controls",
                0.80,
                {"cost_usd": 0.5, "dialogue_rounds": 3}
            ),
            AgentOutput(
                "performance_engineer",
                "Use microservices",
                "Performance concerns addressed in round 2",
                0.75,
                {"cost_usd": 0.5, "dialogue_rounds": 3}
            )
        ]

        result = strategy.synthesize(outputs, {})

        assert result.decision == "Use microservices"
        assert result.confidence > 0.75  # Unanimous decision
        assert result.votes["Use microservices"] == 3
        assert result.metadata["strategy"] == "dialogue"

    def test_cost_tracking_scenario(self):
        """Test realistic scenario with cost tracking."""
        strategy = DialogueOrchestrator(cost_budget_usd=5.0)

        outputs = [
            AgentOutput("a1", "A", "r1", 0.9, {"cost_usd": 1.5}),
            AgentOutput("a2", "A", "r2", 0.8, {"cost_usd": 1.5})
        ]

        result = strategy.synthesize(outputs, {})

        # Total cost: 3.0 USD (within budget)
        assert result.decision == "A"
        assert result.metadata["strategy"] == "dialogue"

    def test_multiple_rounds_data_structure(self):
        """Test building complete dialogue history structure."""
        # This tests the data structures support full dialogue tracking
        outputs_r1 = [
            AgentOutput("a1", "A", "initial", 0.75, {"cost_usd": 0.5}),
            AgentOutput("a2", "B", "initial", 0.75, {"cost_usd": 0.5})
        ]
        outputs_r2 = [
            AgentOutput("a1", "A", "still A", 0.80, {"cost_usd": 0.5}),
            AgentOutput("a2", "A", "changed to A", 0.75, {"cost_usd": 0.5})
        ]

        round1 = DialogueRound(
            round_number=0,
            agent_outputs=outputs_r1,
            convergence_score=0.0,  # First round
            position_stability_score=0.0,
            new_insights=True,
            round_cost_usd=1.0,
            cumulative_cost_usd=1.0
        )

        round2 = DialogueRound(
            round_number=1,
            agent_outputs=outputs_r2,
            convergence_score=1.0,  # All agents converged
            position_stability_score=0.5,  # 1/2 changed
            new_insights=False,
            round_cost_usd=1.0,
            cumulative_cost_usd=2.0
        )

        history = DialogueHistory(
            rounds=[round1, round2],
            total_rounds=2,
            converged=True,
            convergence_round=1,
            early_stop_reason="convergence",
            total_cost_usd=2.0,
            agent_participation={"a1": 2, "a2": 2}
        )

        # Verify complete history tracking
        assert len(history.rounds) == 2
        assert history.converged is True
        assert history.total_cost_usd == 2.0
        assert history.agent_participation == {"a1": 2, "a2": 2}

        # Verify rounds
        assert history.rounds[0].round_number == 0
        assert history.rounds[1].round_number == 1
        assert history.rounds[1].convergence_score == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
