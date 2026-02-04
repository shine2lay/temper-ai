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
        assert caps["supports_merit_weighting"] is True  # Phase 2.4 implemented
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


class TestDialogueOrchestratorConvergence:
    """Test convergence detection functionality."""

    def test_exact_match_convergence_all_unchanged(self):
        """Test exact match convergence when all agents unchanged."""
        strategy = DialogueOrchestrator(use_semantic_convergence=False)

        current = [
            AgentOutput("a1", "Option A", "r", 0.8, {}),
            AgentOutput("a2", "Option B", "r", 0.8, {})
        ]
        previous = [
            AgentOutput("a1", "Option A", "r", 0.7, {}),
            AgentOutput("a2", "Option B", "r", 0.7, {})
        ]

        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 1.0  # 100% unchanged

    def test_exact_match_convergence_half_changed(self):
        """Test exact match convergence when half changed."""
        strategy = DialogueOrchestrator(use_semantic_convergence=False)

        current = [
            AgentOutput("a1", "Option A", "r", 0.8, {}),
            AgentOutput("a2", "Option A", "r", 0.8, {})  # Changed from B
        ]
        previous = [
            AgentOutput("a1", "Option A", "r", 0.7, {}),
            AgentOutput("a2", "Option B", "r", 0.7, {})
        ]

        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 0.5  # 50% unchanged

    def test_exact_match_convergence_all_changed(self):
        """Test exact match convergence when all changed."""
        strategy = DialogueOrchestrator(use_semantic_convergence=False)

        current = [
            AgentOutput("a1", "Option B", "r", 0.8, {}),
            AgentOutput("a2", "Option A", "r", 0.8, {})
        ]
        previous = [
            AgentOutput("a1", "Option A", "r", 0.7, {}),
            AgentOutput("a2", "Option B", "r", 0.7, {})
        ]

        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 0.0  # 0% unchanged

    def test_exact_match_convergence_first_round(self):
        """Test convergence on first round returns 0.0."""
        strategy = DialogueOrchestrator(use_semantic_convergence=False)

        current = [AgentOutput("a1", "Option A", "r", 0.8, {})]
        previous = []

        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 0.0  # No previous round

    def test_use_semantic_convergence_flag(self):
        """Test use_semantic_convergence flag in initialization."""
        strategy_semantic = DialogueOrchestrator(use_semantic_convergence=True)
        assert strategy_semantic.use_semantic_convergence is True

        strategy_exact = DialogueOrchestrator(use_semantic_convergence=False)
        assert strategy_exact.use_semantic_convergence is False

    def test_semantic_convergence_with_similar_phrasing(self):
        """Test semantic convergence detects similar phrasing (if embeddings available)."""
        strategy = DialogueOrchestrator(use_semantic_convergence=True)

        # Try to import sentence_transformers
        try:
            import sentence_transformers  # noqa: F401
            embeddings_available = True
        except ImportError:
            embeddings_available = False
            pytest.skip("sentence-transformers not available")

        current = [
            AgentOutput("a1", "Use microservices architecture", "r", 0.8, {})
        ]
        previous = [
            AgentOutput("a1", "Adopt microservices approach", "r", 0.7, {})
        ]

        convergence = strategy.calculate_convergence(current, previous)

        # With semantic similarity, these should be detected as similar
        # (though maybe not 1.0 depending on embedding model)
        assert convergence > 0.5  # Should be high similarity

    def test_semantic_convergence_fallback_to_exact(self):
        """Test fallback to exact match when embeddings unavailable."""
        strategy = DialogueOrchestrator(use_semantic_convergence=True)

        # Force embeddings unavailable
        strategy._embeddings_available = False

        current = [
            AgentOutput("a1", "Use microservices", "r", 0.8, {})
        ]
        previous = [
            AgentOutput("a1", "Adopt microservices", "r", 0.7, {})
        ]

        convergence = strategy.calculate_convergence(current, previous)

        # Should fall back to exact match (different strings = 0.0)
        assert convergence == 0.0

    def test_convergence_with_integer_decisions(self):
        """Test convergence works with non-string decisions."""
        strategy = DialogueOrchestrator(use_semantic_convergence=False)

        current = [
            AgentOutput("a1", 1, "r", 0.8, {}),
            AgentOutput("a2", 2, "r", 0.8, {})
        ]
        previous = [
            AgentOutput("a1", 1, "r", 0.7, {}),
            AgentOutput("a2", 2, "r", 0.7, {})
        ]

        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 1.0  # Both unchanged

    def test_convergence_with_missing_agents(self):
        """Test convergence when agent sets differ."""
        strategy = DialogueOrchestrator(use_semantic_convergence=False)

        current = [
            AgentOutput("a1", "A", "r", 0.8, {}),
            AgentOutput("a2", "B", "r", 0.8, {})
        ]
        previous = [
            AgentOutput("a1", "A", "r", 0.7, {}),
            AgentOutput("a3", "C", "r", 0.7, {})  # Different agent
        ]

        convergence = strategy.calculate_convergence(current, previous)
        # Only a1 is common, and it's unchanged
        assert convergence == 1.0

    def test_convergence_with_no_common_agents(self):
        """Test convergence when no agents in common."""
        strategy = DialogueOrchestrator(use_semantic_convergence=False)

        current = [AgentOutput("a1", "A", "r", 0.8, {})]
        previous = [AgentOutput("a2", "B", "r", 0.7, {})]

        convergence = strategy.calculate_convergence(current, previous)
        assert convergence == 0.0  # No common agents

    def test_check_embeddings_available(self):
        """Test embeddings availability check."""
        strategy = DialogueOrchestrator(use_semantic_convergence=True)

        # Should cache result
        first_check = strategy._check_embeddings_available()
        second_check = strategy._check_embeddings_available()

        assert isinstance(first_check, bool)
        assert first_check == second_check  # Cached

    def test_exact_match_method_directly(self):
        """Test _calculate_exact_match_convergence directly."""
        strategy = DialogueOrchestrator()

        current = [
            AgentOutput("a1", "Same", "r", 0.8, {}),
            AgentOutput("a2", "Different", "r", 0.8, {})
        ]
        previous = [
            AgentOutput("a1", "Same", "r", 0.7, {}),
            AgentOutput("a2", "Changed", "r", 0.7, {})
        ]

        convergence = strategy._calculate_exact_match_convergence(current, previous)
        assert convergence == 0.5  # 1/2 unchanged


class TestDialogueOrchestratorSemanticEnhancements:
    """Test Phase 2 semantic convergence enhancements."""

    def test_initialization_with_semantic_flag(self):
        """Test initialization accepts use_semantic_convergence parameter."""
        strategy = DialogueOrchestrator(
            max_rounds=5,
            convergence_threshold=0.90,
            use_semantic_convergence=True
        )

        assert strategy.max_rounds == 5
        assert strategy.convergence_threshold == 0.90
        assert strategy.use_semantic_convergence is True

    def test_semantic_convergence_configuration(self):
        """Test semantic convergence can be enabled/disabled."""
        enabled = DialogueOrchestrator(use_semantic_convergence=True)
        disabled = DialogueOrchestrator(use_semantic_convergence=False)

        assert enabled.use_semantic_convergence is True
        assert disabled.use_semantic_convergence is False

    def test_capabilities_still_report_convergence_support(self):
        """Test capabilities report convergence support with semantic enhancement."""
        strategy = DialogueOrchestrator(use_semantic_convergence=True)
        caps = strategy.get_capabilities()

        assert caps["supports_convergence"] is True

    def test_convergence_with_empty_previous(self):
        """Test convergence handles empty previous outputs gracefully."""
        strategy = DialogueOrchestrator(use_semantic_convergence=True)

        current = [AgentOutput("a1", "A", "r", 0.8, {})]
        convergence = strategy.calculate_convergence(current, [])

        assert convergence == 0.0  # No previous round


class TestDialogueOrchestratorMeritWeighting:
    """Test Phase 2.4 merit-weighted synthesis."""

    def test_initialization_with_merit_weighting(self):
        """Test initialization accepts use_merit_weighting parameter."""
        strategy_enabled = DialogueOrchestrator(use_merit_weighting=True)
        strategy_disabled = DialogueOrchestrator(use_merit_weighting=False)

        assert strategy_enabled.use_merit_weighting is True
        assert strategy_disabled.use_merit_weighting is False

    def test_merit_domain_parameter(self):
        """Test merit_domain parameter."""
        strategy = DialogueOrchestrator(
            use_merit_weighting=True,
            merit_domain="architecture_decisions"
        )

        assert strategy.merit_domain == "architecture_decisions"

    def test_merit_weighted_synthesis_without_tracker(self):
        """Test merit-weighted synthesis falls back gracefully when no tracker."""
        strategy = DialogueOrchestrator(use_merit_weighting=True)

        outputs = [
            AgentOutput("a1", "Option A", "r1", 0.9, {}),
            AgentOutput("a2", "Option A", "r2", 0.8, {}),
            AgentOutput("a3", "Option B", "r3", 0.7, {})
        ]

        # Should not raise, should fall back to equal weights
        result = strategy.synthesize(outputs, {})

        assert result.decision == "Option A"  # Majority should still win
        assert result.method == "merit_weighted"
        assert result.metadata["synthesis_method"] == "merit_weighted"

    def test_capabilities_report_merit_weighting(self):
        """Test capabilities correctly report merit weighting support."""
        strategy = DialogueOrchestrator(use_merit_weighting=True)
        caps = strategy.get_capabilities()

        assert caps["supports_merit_weighting"] is True

    def test_get_merit_weights_fallback(self):
        """Test _get_merit_weights falls back to equal weights."""
        strategy = DialogueOrchestrator(use_merit_weighting=True)

        outputs = [
            AgentOutput("a1", "A", "r", 0.8, {}),
            AgentOutput("a2", "B", "r", 0.8, {})
        ]

        weights = strategy._get_merit_weights(outputs)

        # Should have weights for both agents
        assert "a1" in weights
        assert "a2" in weights
        # Should be equal (fallback)
        assert weights["a1"] == weights["a2"]

    def test_merit_weighted_synthesis_direct_call(self):
        """Test _merit_weighted_synthesis directly."""
        strategy = DialogueOrchestrator(use_merit_weighting=True)

        outputs = [
            AgentOutput("a1", "Option A", "strong", 0.9, {}),
            AgentOutput("a2", "Option A", "agree", 0.8, {}),
            AgentOutput("a3", "Option B", "weak", 0.6, {})
        ]

        result = strategy._merit_weighted_synthesis(outputs, {})

        assert result.decision == "Option A"
        assert result.method == "merit_weighted"
        assert "merit_weights" in result.metadata
        assert "weighted_votes" in result.metadata
        assert len(result.metadata["supporters"]) == 2
        assert len(result.metadata["dissenters"]) == 1

    def test_build_merit_weighted_reasoning(self):
        """Test _build_merit_weighted_reasoning generates clear explanation."""
        strategy = DialogueOrchestrator(use_merit_weighting=True)

        outputs = [
            AgentOutput("a1", "A", "r", 0.9, {}),
            AgentOutput("a2", "A", "r", 0.8, {})
        ]

        merit_weights = {"a1": 0.85, "a2": 0.75}
        weighted_votes = {"A": 1.6, "B": 0.3}

        reasoning = strategy._build_merit_weighted_reasoning(
            decision="A",
            support=0.84,
            agent_outputs=outputs,
            merit_weights=merit_weights,
            weighted_votes=weighted_votes
        )

        assert "Merit-weighted decision" in reasoning
        assert "84.0% weighted support" in reasoning
        assert "a1 (merit: 0.85)" in reasoning
        assert "a2 (merit: 0.75)" in reasoning

    def test_disabled_merit_weighting_uses_consensus(self):
        """Test that disabling merit weighting uses consensus strategy."""
        strategy = DialogueOrchestrator(use_merit_weighting=False)

        outputs = [
            AgentOutput("a1", "Option A", "r1", 0.9, {}),
            AgentOutput("a2", "Option A", "r2", 0.8, {})
        ]

        result = strategy.synthesize(outputs, {})

        # Should use consensus
        assert result.method == "consensus"
        assert result.metadata["synthesis_method"] == "consensus_from_final_round"

    def test_merit_weighting_with_single_agent(self):
        """Test merit weighting with single agent."""
        strategy = DialogueOrchestrator(use_merit_weighting=True)

        outputs = [AgentOutput("a1", "Option A", "reason", 0.9, {})]

        result = strategy.synthesize(outputs, {})

        assert result.decision == "Option A"
        assert result.method == "merit_weighted"

    def test_merit_weighting_with_tie(self):
        """Test merit weighting breaks ties by weight."""
        strategy = DialogueOrchestrator(use_merit_weighting=True)

        outputs = [
            AgentOutput("a1", "Option A", "r1", 0.8, {}),
            AgentOutput("a2", "Option B", "r2", 0.8, {})
        ]

        result = strategy.synthesize(outputs, {})

        # With equal weights, should pick one (deterministic based on dict ordering)
        assert result.decision in ["Option A", "Option B"]
        assert result.method == "merit_weighted"


class TestDialogueOrchestratorContextCuration:
    """Test Phase 2.3 context curation enhancements."""

    def test_initialization_with_context_strategy(self):
        """Test initialization accepts context_strategy parameter."""
        strategy_full = DialogueOrchestrator(context_strategy="full")
        strategy_recent = DialogueOrchestrator(context_strategy="recent")
        strategy_relevant = DialogueOrchestrator(context_strategy="relevant")

        assert strategy_full.context_strategy == "full"
        assert strategy_recent.context_strategy == "recent"
        assert strategy_relevant.context_strategy == "relevant"

    def test_invalid_context_strategy_raises(self):
        """Test that invalid context_strategy raises ValueError."""
        with pytest.raises(ValueError, match="context_strategy must be"):
            DialogueOrchestrator(context_strategy="invalid")

    def test_context_window_size_validation(self):
        """Test context_window_size validation."""
        with pytest.raises(ValueError, match="context_window_size must be >= 1"):
            DialogueOrchestrator(context_window_size=0)

        # Valid window size
        strategy = DialogueOrchestrator(context_window_size=3)
        assert strategy.context_window_size == 3

    def test_curate_full_strategy(self):
        """Test 'full' strategy returns all history."""
        strategy = DialogueOrchestrator(context_strategy="full")

        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a2", "round": 0, "output": "B", "reasoning": "r2", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "r3", "confidence": 0.9},
            {"agent": "a2", "round": 1, "output": "A", "reasoning": "r4", "confidence": 0.85},
        ]

        curated = strategy.curate_dialogue_history(history, current_round=2)
        assert len(curated) == 4  # All history returned

    def test_curate_recent_strategy(self):
        """Test 'recent' strategy returns only recent rounds."""
        strategy = DialogueOrchestrator(
            context_strategy="recent",
            context_window_size=1  # Only last round
        )

        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a2", "round": 0, "output": "B", "reasoning": "r2", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "r3", "confidence": 0.9},
            {"agent": "a2", "round": 1, "output": "A", "reasoning": "r4", "confidence": 0.85},
            {"agent": "a1", "round": 2, "output": "A", "reasoning": "r5", "confidence": 0.95},
            {"agent": "a2", "round": 2, "output": "A", "reasoning": "r6", "confidence": 0.90},
        ]

        curated = strategy.curate_dialogue_history(history, current_round=3)
        assert len(curated) == 2  # Only round 2 (last round)
        assert all(entry["round"] == 2 for entry in curated)

    def test_curate_recent_with_window_size_2(self):
        """Test 'recent' strategy with window size 2."""
        strategy = DialogueOrchestrator(
            context_strategy="recent",
            context_window_size=2  # Last 2 rounds
        )

        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "r2", "confidence": 0.9},
            {"agent": "a1", "round": 2, "output": "A", "reasoning": "r3", "confidence": 0.95},
        ]

        curated = strategy.curate_dialogue_history(history, current_round=3)
        assert len(curated) == 2  # Rounds 1 and 2
        assert {entry["round"] for entry in curated} == {1, 2}

    def test_curate_relevant_strategy_with_agent_name(self):
        """Test 'relevant' strategy filters by agent relevance."""
        strategy = DialogueOrchestrator(context_strategy="relevant")

        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "initial", "confidence": 0.8},
            {"agent": "a2", "round": 0, "output": "B", "reasoning": "a1 is wrong", "confidence": 0.8},
            {"agent": "a3", "round": 0, "output": "C", "reasoning": "unrelated", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "final", "confidence": 0.9},
        ]

        # Curate for agent a1
        curated = strategy.curate_dialogue_history(history, current_round=2, agent_name="a1")

        # Should include:
        # - Latest round (round 1)
        # - Agent a1's own contributions
        # - Entries mentioning "a1" (a2's comment)
        assert len(curated) >= 2
        assert any(entry["agent"] == "a1" for entry in curated)
        assert any("a1" in entry["reasoning"].lower() for entry in curated)

    def test_curate_relevant_without_agent_name_falls_back(self):
        """Test 'relevant' strategy falls back to recent when no agent_name."""
        strategy = DialogueOrchestrator(
            context_strategy="relevant",
            context_window_size=1
        )

        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "r2", "confidence": 0.9},
        ]

        curated = strategy.curate_dialogue_history(history, current_round=2, agent_name=None)
        # Should fall back to recent (window_size=1)
        assert len(curated) == 1
        assert curated[0]["round"] == 1

    def test_curate_empty_history(self):
        """Test curation with empty history."""
        strategy = DialogueOrchestrator(context_strategy="recent")

        curated = strategy.curate_dialogue_history([], current_round=0)
        assert curated == []

    def test_curate_recent_method_directly(self):
        """Test _curate_recent method directly."""
        strategy = DialogueOrchestrator(context_window_size=1)

        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "B", "reasoning": "r2", "confidence": 0.9},
        ]

        curated = strategy._curate_recent(history, current_round=2)
        assert len(curated) == 1
        assert curated[0]["round"] == 1

    def test_curate_relevant_method_directly(self):
        """Test _curate_relevant method directly."""
        strategy = DialogueOrchestrator()

        history = [
            {"agent": "a1", "round": 0, "output": "A", "reasoning": "r1", "confidence": 0.8},
            {"agent": "a2", "round": 0, "output": "B", "reasoning": "r2", "confidence": 0.8},
            {"agent": "a1", "round": 1, "output": "A", "reasoning": "r3", "confidence": 0.9},
        ]

        curated = strategy._curate_relevant(history, agent_name="a1")
        # Should include latest round and a1's contributions
        assert len(curated) >= 1
        assert any(entry["agent"] == "a1" for entry in curated)

    def test_context_curation_reduces_size(self):
        """Test that context curation actually reduces history size."""
        strategy_full = DialogueOrchestrator(context_strategy="full")
        strategy_recent = DialogueOrchestrator(context_strategy="recent", context_window_size=1)

        # Create large history (5 rounds, 2 agents each = 10 entries)
        history = []
        for round_num in range(5):
            history.append({"agent": "a1", "round": round_num, "output": "A", "reasoning": "r", "confidence": 0.8})
            history.append({"agent": "a2", "round": round_num, "output": "B", "reasoning": "r", "confidence": 0.8})

        curated_full = strategy_full.curate_dialogue_history(history, current_round=5)
        curated_recent = strategy_recent.curate_dialogue_history(history, current_round=5)

        assert len(curated_full) == 10  # All history
        assert len(curated_recent) == 2  # Only last round (2 agents)
        assert len(curated_recent) < len(curated_full)  # Reduction confirmed


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
