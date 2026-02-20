"""Tests for ConsensusStrategy collaboration strategy.

This test module verifies:
- Unanimous consensus (all agents agree)
- Majority consensus (>50% agree)
- Tie-breaking by confidence and first-vote
- Weak consensus detection (below threshold)
- Edge cases (single agent, empty outputs)
- Configuration options (min_agents, min_consensus, tie_breaker)
- Capability and metadata reporting
"""

import pytest

from temper_ai.agent.strategies.base import AgentOutput
from temper_ai.agent.strategies.consensus import ConsensusStrategy

# Realistic metadata for agent outputs (replacing empty dicts)
REALISTIC_METADATA_RESEARCH = {
    "sources": 12,
    "confidence_factors": ["literature_review", "expert_consensus"],
    "evidence_quality": "high"
}

REALISTIC_METADATA_ANALYSIS = {
    "sample_size": 5000,
    "statistical_significance": 0.01,
    "method": "quantitative_analysis"
}

REALISTIC_METADATA_SYNTHESIS = {
    "supporting_evidence": "strong",
    "risk_level": "low",
    "implementation_difficulty": "moderate"
}


class TestConsensusStrategy:
    """Test ConsensusStrategy implementation."""

    def test_unanimous_consensus(self):
        """Test unanimous decision (all agents agree)."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, REALISTIC_METADATA_RESEARCH),
            AgentOutput("agent2", "Option A", "reason2", 0.8, REALISTIC_METADATA_ANALYSIS),
            AgentOutput("agent3", "Option A", "reason3", 0.85, REALISTIC_METADATA_SYNTHESIS)
        ]

        result = strategy.synthesize(outputs, {})

        assert result.decision == "Option A"
        assert result.confidence > 0.8  # High confidence for unanimous
        assert result.method == "consensus"
        assert result.votes["Option A"] == 3
        assert len(result.conflicts) == 0  # No conflicts when all agree
        assert "100.0% support" in result.reasoning
        assert "(3/3 agents)" in result.reasoning
        assert "Dissenting" not in result.reasoning  # No dissenters in unanimous
        assert "Vote breakdown:" not in result.reasoning  # Omitted when unanimous
        assert result.metadata["total_agents"] == 3
        assert result.metadata["decision_support"] == 1.0

    def test_majority_consensus(self):
        """Test majority decision (2/3 agents agree)."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, REALISTIC_METADATA_RESEARCH),
            AgentOutput("agent2", "Option A", "reason2", 0.8, REALISTIC_METADATA_ANALYSIS),
            AgentOutput("agent3", "Option B", "reason3", 0.7, REALISTIC_METADATA_SYNTHESIS)
        ]

        result = strategy.synthesize(outputs, {})

        assert result.decision == "Option A"
        # Confidence: (2/3) * avg(0.9, 0.8) = 0.667 * 0.85 = 0.567
        assert 0.55 < result.confidence < 0.60
        assert result.method == "consensus"
        assert result.votes == {"Option A": 2, "Option B": 1}
        assert len(result.conflicts) == 1  # Disagreement detected
        assert "66.7% support" in result.reasoning
        assert "agent1, agent2" in result.reasoning
        assert "agent3" in result.reasoning
        assert "Vote breakdown:" in result.reasoning  # Present when not unanimous

    def test_tie_breaking_by_confidence(self):
        """Test tie-breaking using confidence."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, REALISTIC_METADATA_RESEARCH),
            AgentOutput("agent2", "Option B", "reason2", 0.7, REALISTIC_METADATA_ANALYSIS)
        ]

        result = strategy.synthesize(outputs, {"tie_breaker": "confidence"})

        # Option A has higher confidence (0.9 vs 0.7)
        assert result.decision == "Option A"
        assert result.votes == {"Option A": 1, "Option B": 1}
        assert "50.0% support" in result.reasoning

    def test_tie_breaking_by_first(self):
        """Test tie-breaking using first-vote — first encountered decision wins."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option B", "reason1", 0.7, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.9, {})
        ]

        result = strategy.synthesize(outputs, {"tie_breaker": "first"})

        # "Option B" is encountered first (agent1), so it wins with "first" tie-breaker
        assert result.decision == "Option B"
        assert result.votes == {"Option A": 1, "Option B": 1}

    def test_no_majority_creates_weak_consensus(self):
        """Test 3-way split with no majority."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.8, {}),
            AgentOutput("agent2", "Option B", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option C", "reason3", 0.8, {})
        ]

        result = strategy.synthesize(outputs, {})

        # Should still return a decision but with weak consensus flag
        assert result.decision in ["Option A", "Option B", "Option C"]
        assert result.confidence < 0.5  # Low confidence
        assert result.method == "consensus_weak"
        assert result.metadata["needs_conflict_resolution"] is True
        assert result.metadata["decision_support"] < 0.51
        assert "No clear majority" in result.reasoning

    def test_min_consensus_threshold_not_met(self):
        """Test custom minimum consensus threshold."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option B", "reason3", 0.7, {}),
            AgentOutput("agent4", "Option C", "reason4", 0.7, {})
        ]

        # 2/4 = 50% support, below 75% threshold
        result = strategy.synthesize(outputs, {"min_consensus": 0.75})

        assert result.method == "consensus_weak"
        assert result.metadata["needs_conflict_resolution"] is True
        assert result.metadata["decision_support"] == 0.5
        assert result.metadata["min_consensus"] == 0.75
        assert "below 75.0% threshold" in result.reasoning

    def test_min_consensus_threshold_met(self):
        """Test that high consensus meets high threshold."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option A", "reason3", 0.85, {}),
            AgentOutput("agent4", "Option B", "reason4", 0.7, {})
        ]

        # 3/4 = 75% support, meets 75% threshold
        result = strategy.synthesize(outputs, {"min_consensus": 0.75})

        assert result.method == "consensus"
        assert result.decision == "Option A"
        assert result.metadata["decision_support"] == 0.75

    def test_single_agent(self):
        """Test edge case with single agent."""
        strategy = ConsensusStrategy()
        outputs = [AgentOutput("agent1", "Option A", "reason", 0.9, {})]

        result = strategy.synthesize(outputs, {})

        assert result.decision == "Option A"
        assert result.confidence == 0.9  # 100% support * 0.9 confidence
        assert result.method == "consensus"
        assert result.votes == {"Option A": 1}
        assert "100.0% support" in result.reasoning

    def test_empty_outputs_raises(self):
        """Test that empty outputs raises ValueError."""
        strategy = ConsensusStrategy()

        with pytest.raises(ValueError, match="cannot be empty"):
            strategy.synthesize([], {})

    def test_min_agents_enforcement(self):
        """Test minimum agents requirement."""
        strategy = ConsensusStrategy()
        outputs = [AgentOutput("agent1", "Option A", "reason", 0.9, {})]

        with pytest.raises(ValueError, match="Need at least 2 agents"):
            strategy.synthesize(outputs, {"min_agents": 2})

    def test_min_agents_met(self):
        """Test that min_agents requirement is satisfied."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {})
        ]

        # Should not raise
        result = strategy.synthesize(outputs, {"min_agents": 2})
        assert result.decision == "Option A"

    def test_invalid_min_consensus_too_high(self):
        """Test that invalid min_consensus > 1.0 raises ValueError."""
        strategy = ConsensusStrategy()
        outputs = [AgentOutput("agent1", "Option A", "reason", 0.9, {})]

        with pytest.raises(ValueError, match="min_consensus must be between 0 and 1"):
            strategy.synthesize(outputs, {"min_consensus": 1.5})

    def test_invalid_min_consensus_negative(self):
        """Test that negative min_consensus raises ValueError."""
        strategy = ConsensusStrategy()
        outputs = [AgentOutput("agent1", "Option A", "reason", 0.9, {})]

        with pytest.raises(ValueError, match="min_consensus must be between 0 and 1"):
            strategy.synthesize(outputs, {"min_consensus": -0.1})

    def test_invalid_tie_breaker(self):
        """Test that invalid tie_breaker raises ValueError."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option B", "reason2", 0.8, {})
        ]

        with pytest.raises(ValueError, match="tie_breaker must be 'confidence' or 'first'"):
            strategy.synthesize(outputs, {"tie_breaker": "invalid"})

    def test_capabilities(self):
        """Test strategy capabilities reporting."""
        strategy = ConsensusStrategy()
        caps = strategy.get_capabilities()

        assert caps["supports_debate"] is False
        assert caps["supports_convergence"] is False
        assert caps["supports_merit_weighting"] is False
        assert caps["supports_partial_participation"] is True
        assert caps["supports_async"] is False
        assert caps["deterministic"] is True
        assert caps["requires_conflict_resolver"] is True

    def test_metadata(self):
        """Test strategy metadata."""
        strategy = ConsensusStrategy()
        metadata = strategy.get_metadata()

        assert metadata["name"] == "ConsensusStrategy"
        assert "version" in metadata
        assert "description" in metadata
        assert "config_schema" in metadata
        assert "min_agents" in metadata["config_schema"]
        assert "min_consensus" in metadata["config_schema"]
        assert "tie_breaker" in metadata["config_schema"]

        # Check config schema details
        assert metadata["config_schema"]["min_agents"]["default"] == 1
        assert metadata["config_schema"]["min_consensus"]["default"] == 0.51
        assert metadata["config_schema"]["tie_breaker"]["default"] == "confidence"

    def test_vote_counts_in_metadata(self):
        """Test that vote details are tracked in metadata."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option B", "reason3", 0.7, {})
        ]

        result = strategy.synthesize(outputs, {})

        assert "supporters" in result.metadata
        assert "dissenters" in result.metadata
        assert result.metadata["supporters"] == ["agent1", "agent2"]
        assert result.metadata["dissenters"] == ["agent3"]
        # Use approximate comparison for floating point
        assert abs(result.metadata["avg_supporter_confidence"] - 0.85) < 0.001

    def test_reasoning_includes_vote_breakdown(self):
        """Test that reasoning includes detailed vote breakdown."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option B", "reason3", 0.7, {}),
            AgentOutput("agent4", "Option C", "reason4", 0.6, {})
        ]

        result = strategy.synthesize(outputs, {})

        # Should have vote breakdown in reasoning (only in strong consensus)
        if result.method == "consensus":
            assert "Vote breakdown:" in result.reasoning
            # Check that votes are represented
            assert "Option A" in result.reasoning
            assert "Option B" in result.reasoning

    def test_conflict_detection(self):
        """Test that conflicts are properly detected."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
            AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
            AgentOutput("agent3", "Option B", "reason3", 0.7, {})
        ]

        result = strategy.synthesize(outputs, {})

        # Should detect conflict
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert len(conflict.agents) == 3
        assert len(conflict.decisions) == 2
        assert conflict.disagreement_score > 0.3

    def test_type_consistency_with_integer_decisions(self):
        """Test that integer decision types are preserved."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", 1, "reason1", 0.9, {}),
            AgentOutput("agent2", 1, "reason2", 0.8, {}),
            AgentOutput("agent3", 2, "reason3", 0.7, {})
        ]

        result = strategy.synthesize(outputs, {})

        # Decision should be integer, not string
        assert result.decision == 1
        assert isinstance(result.decision, int)
        assert result.votes == {1: 2, 2: 1}
        assert 1 in result.votes  # Not "1"

    def test_type_consistency_with_mixed_types(self):
        """Test that different decision types don't get falsely grouped."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", 1, "reason1", 0.9, {}),  # int
            AgentOutput("agent2", "1", "reason2", 0.8, {}),  # str
        ]

        result = strategy.synthesize(outputs, {})

        # int(1) and str("1") should NOT be grouped together
        assert result.votes == {1: 1, "1": 1}
        assert 1 in result.votes
        assert "1" in result.votes


class TestConsensusTieBreaking:
    """Test tie-breaking logic in detail."""

    def test_tie_break_confidence_clear_winner(self):
        """Test confidence-based tie-breaking with clear winner."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "A", "r1", 0.95, {}),
            AgentOutput("agent2", "B", "r2", 0.6, {})
        ]

        result = strategy.synthesize(outputs, {"tie_breaker": "confidence"})
        assert result.decision == "A"

    def test_tie_break_confidence_three_way(self):
        """Test confidence-based tie-breaking with 3-way tie."""
        strategy = ConsensusStrategy()
        outputs = [
            AgentOutput("agent1", "A", "r1", 0.9, {}),
            AgentOutput("agent2", "B", "r2", 0.95, {}),  # Highest
            AgentOutput("agent3", "C", "r3", 0.7, {})
        ]

        result = strategy.synthesize(outputs, {"tie_breaker": "confidence"})
        # B should win due to highest confidence
        assert result.decision == "B"

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
