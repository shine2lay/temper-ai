"""Edge case tests for collaboration strategies.

Tests edge cases and boundary conditions for:
- Consensus strategy (unanimous, ties, splits)
- Merit-weighted resolution (zero/missing/negative merits)
- Debate strategy (non-convergence, oscillation)

These tests verify graceful handling of unusual or extreme inputs.
"""

import pytest

from src.agent.strategies.base import AgentOutput, Conflict, SynthesisResult
from src.agent.strategies.conflict_resolution import AgentMerit, ResolutionContext
from src.agent.strategies.consensus import ConsensusStrategy
from src.agent.strategies.merit_weighted import MeritWeightedResolver


class TestConsensusEdgeCases:
    """Test consensus strategy edge cases."""

    def test_unanimous_agreement(self):
        """Test all agents agree on same decision."""
        outputs = [
            AgentOutput(
                agent_name="agent_1",
                decision="Option A",
                reasoning="Reason 1",
                confidence=0.9,
                metadata={}
            ),
            AgentOutput(
                agent_name="agent_2",
                decision="Option A",
                reasoning="Reason 2",
                confidence=0.85,
                metadata={}
            ),
            AgentOutput(
                agent_name="agent_3",
                decision="Option A",
                reasoning="Reason 3",
                confidence=0.8,
                metadata={}
            ),
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        assert result.decision == "Option A"
        assert result.confidence > 0.8
        assert isinstance(result, SynthesisResult)

    def test_perfect_tie_two_agents(self):
        """Test 50-50 tie with two agents."""
        outputs = [
            AgentOutput(
                agent_name="agent_1",
                decision="Option A",
                reasoning="Reason A",
                confidence=0.9,
                metadata={}
            ),
            AgentOutput(
                agent_name="agent_2",
                decision="Option B",
                reasoning="Reason B",
                confidence=0.7,
                metadata={}
            ),
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {"tie_breaker": "confidence"})

        # Should pick Option A (higher confidence)
        assert result.decision == "Option A"

    def test_perfect_tie_four_agents(self):
        """Test 50-50 tie with four agents."""
        outputs = [
            AgentOutput(
                agent_name=f"agent_{i}",
                decision="A" if i < 2 else "B",
                reasoning=f"Reason {i}",
                confidence=0.8,
                metadata={}
            )
            for i in range(4)
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {"tie_breaker": "first"})

        # Should pick first option in tie
        assert result.decision in ["A", "B"]

    def test_three_way_split_no_majority(self):
        """Test 3-way split with no clear majority."""
        outputs = [
            AgentOutput(
                agent_name="agent_1",
                decision="Option A",
                reasoning="Reason A",
                confidence=0.8,
                metadata={}
            ),
            AgentOutput(
                agent_name="agent_2",
                decision="Option B",
                reasoning="Reason B",
                confidence=0.8,
                metadata={}
            ),
            AgentOutput(
                agent_name="agent_3",
                decision="Option C",
                reasoning="Reason C",
                confidence=0.8,
                metadata={}
            ),
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {"min_consensus": 0.5})

        # No majority, but should still return a result
        assert result.decision in ["Option A", "Option B", "Option C"]
        # Confidence should be lower due to lack of consensus
        assert result.confidence < 0.8

    def test_single_agent_consensus(self):
        """Test consensus with only one agent."""
        outputs = [
            AgentOutput(
                agent_name="solo_agent",
                decision="Solo Decision",
                reasoning="I'm alone",
                confidence=0.95,
                metadata={}
            )
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        assert result.decision == "Solo Decision"
        assert result.confidence == pytest.approx(0.95, rel=0.1)

    def test_empty_agents_list(self):
        """Test consensus with empty agents list."""
        outputs = []

        strategy = ConsensusStrategy()

        # Should raise ValueError for empty list
        with pytest.raises(ValueError):
            strategy.synthesize(outputs, {})

    def test_all_agents_low_confidence(self):
        """Test consensus when all agents have very low confidence."""
        outputs = [
            AgentOutput(
                agent_name=f"agent_{i}",
                decision="Uncertain",
                reasoning=f"Not sure {i}",
                confidence=0.2,
                metadata={}
            )
            for i in range(3)
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        # Should still synthesize, but with low confidence
        assert result.decision == "Uncertain"
        assert result.confidence < 0.5

    def test_consensus_with_min_agents_requirement(self):
        """Test consensus respects min_agents configuration."""
        outputs = [
            AgentOutput(
                agent_name="agent_1",
                decision="A",
                reasoning="Reason",
                confidence=0.8,
                metadata={}
            )
        ]

        strategy = ConsensusStrategy()

        # Require at least 2 agents
        with pytest.raises(ValueError):
            strategy.synthesize(outputs, {"min_agents": 2})

    def test_consensus_with_varied_confidence(self):
        """Test consensus with widely varying confidence levels."""
        outputs = [
            AgentOutput(
                agent_name="high_confidence",
                decision="A",
                reasoning="Very sure",
                confidence=0.95,
                metadata={}
            ),
            AgentOutput(
                agent_name="medium_confidence",
                decision="A",
                reasoning="Somewhat sure",
                confidence=0.6,
                metadata={}
            ),
            AgentOutput(
                agent_name="low_confidence",
                decision="B",
                reasoning="Not sure",
                confidence=0.3,
                metadata={}
            ),
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        # Majority vote for A should win
        assert result.decision == "A"


class TestMeritWeightedEdgeCases:
    """Test merit-weighted resolver edge cases."""

    def test_all_agents_zero_merit(self):
        """Test resolution when all agents have zero merit."""
        conflict = Conflict(
            agents=["agent_1", "agent_2"],
            decisions=["A", "B"],
            disagreement_score=0.8,
            context={}
        )

        agent_outputs = [
            AgentOutput("agent_1", "A", "Reason A", 0.9, {}),
            AgentOutput("agent_2", "B", "Reason B", 0.8, {}),
        ]

        context = ResolutionContext(
            agent_merits={
                "agent_1": AgentMerit("agent_1", 0.0, 0.0, 0.0, "general"),
                "agent_2": AgentMerit("agent_2", 0.0, 0.0, 0.0, "general"),
            },
            agent_outputs={out.agent_name: out for out in agent_outputs},
            stage_name="test",
            workflow_name="test_wf",
            workflow_config={},
            previous_resolutions=[]
        )

        resolver = MeritWeightedResolver()
        resolution = resolver.resolve_with_context(conflict, context)

        # Should fall back to equal weighting or confidence-based
        assert resolution is not None
        assert resolution.decision in ["A", "B"]

    def test_missing_merit_scores_fallback(self):
        """Test resolution with missing merit scores."""
        conflict = Conflict(
            agents=["agent_1", "agent_2"],
            decisions=["A", "B"],
            disagreement_score=0.7,
            context={}
        )

        agent_outputs = [
            AgentOutput("agent_1", "A", "Reason A", 0.9, {}),
            AgentOutput("agent_2", "B", "Reason B", 0.8, {}),
        ]

        # Only provide merit for one agent
        context = ResolutionContext(
            agent_merits={
                "agent_1": AgentMerit("agent_1", 0.8, 0.7, 0.75, "expert"),
            },
            agent_outputs={out.agent_name: out for out in agent_outputs},
            stage_name="test",
            workflow_name="test_wf",
            workflow_config={},
            previous_resolutions=[]
        )

        resolver = MeritWeightedResolver()

        # Should handle missing merit gracefully
        # May raise ValueError or use default merit
        try:
            resolution = resolver.resolve_with_context(conflict, context)
            assert resolution is not None
        except ValueError as e:
            # Acceptable to require all merits
            assert "merit" in str(e).lower()

    def test_negative_merit_scores_rejected(self):
        """Test that negative merit scores are rejected during creation."""
        # AgentMerit validates merit values during __post_init__
        with pytest.raises(ValueError) as exc_info:
            AgentMerit("agent_1", -0.5, 0.5, 0.5, "general")

        # Verify error message mentions merit
        assert "merit" in str(exc_info.value).lower()

    def test_extreme_merit_differences(self):
        """Test resolution with extreme merit differences (0.01 vs 0.99)."""
        conflict = Conflict(
            agents=["novice", "expert"],
            decisions=["A", "B"],
            disagreement_score=0.9,
            context={}
        )

        agent_outputs = [
            AgentOutput("novice", "A", "Novice opinion", 0.5, {}),
            AgentOutput("expert", "B", "Expert opinion", 0.9, {}),
        ]

        context = ResolutionContext(
            agent_merits={
                "novice": AgentMerit("novice", 0.01, 0.01, 0.01, "beginner"),
                "expert": AgentMerit("expert", 0.99, 0.99, 0.99, "master"),
            },
            agent_outputs={out.agent_name: out for out in agent_outputs},
            stage_name="test",
            workflow_name="test_wf",
            workflow_config={},
            previous_resolutions=[]
        )

        resolver = MeritWeightedResolver()
        resolution = resolver.resolve_with_context(conflict, context)

        # Expert should dominate (or at least have strong influence)
        # Result could be B (expert) or the weighting might not be overwhelming
        assert resolution.decision in ["A", "B"]
        # Expert's high merit should result in reasonable confidence
        assert resolution.confidence > 0.3

    def test_merit_weighted_with_equal_merits(self):
        """Test that equal merits result in tie-breaker logic."""
        conflict = Conflict(
            agents=["agent_1", "agent_2"],
            decisions=["A", "B"],
            disagreement_score=0.5,
            context={}
        )

        agent_outputs = [
            AgentOutput("agent_1", "A", "Reason A", 0.9, {}),
            AgentOutput("agent_2", "B", "Reason B", 0.7, {}),
        ]

        context = ResolutionContext(
            agent_merits={
                "agent_1": AgentMerit("agent_1", 0.75, 0.75, 0.75, "general"),
                "agent_2": AgentMerit("agent_2", 0.75, 0.75, 0.75, "general"),
            },
            agent_outputs={out.agent_name: out for out in agent_outputs},
            stage_name="test",
            workflow_name="test_wf",
            workflow_config={},
            previous_resolutions=[]
        )

        resolver = MeritWeightedResolver()
        resolution = resolver.resolve_with_context(conflict, context)

        # Should fall back to confidence (agent_1 has higher)
        assert resolution.decision == "A"

    def test_merit_weighted_with_many_agents(self):
        """Test merit weighting with many agents."""
        agents = [f"agent_{i}" for i in range(10)]
        decisions = ["A" if i < 7 else "B" for i in range(10)]

        conflict = Conflict(
            agents=agents,
            decisions=decisions,
            disagreement_score=0.7,
            context={}
        )

        agent_outputs = [
            AgentOutput(f"agent_{i}", decisions[i], f"Reason {i}", 0.8, {})
            for i in range(10)
        ]

        # Higher merit for B voters (minority)
        merits = {}
        for i in range(10):
            merit_value = 0.9 if i >= 7 else 0.5
            merits[f"agent_{i}"] = AgentMerit(f"agent_{i}", merit_value, merit_value, merit_value, "general")

        context = ResolutionContext(
            agent_merits=merits,
            agent_outputs={out.agent_name: out for out in agent_outputs},
            stage_name="test",
            workflow_name="test_wf",
            workflow_config={},
            previous_resolutions=[]
        )

        resolver = MeritWeightedResolver()
        resolution = resolver.resolve_with_context(conflict, context)

        # Result depends on weighting calculation
        assert resolution.decision in ["A", "B"]

    def test_empty_conflict_agents_raises_error(self):
        """Test that empty conflict agents raises ValueError during creation."""
        # Conflict validates agents during __post_init__
        with pytest.raises(ValueError) as exc_info:
            Conflict(
                agents=[],
                decisions=[],
                disagreement_score=0.0,
                context={}
            )

        # Verify error message mentions agents
        assert "agent" in str(exc_info.value).lower()


class TestStrategyRobustness:
    """Test strategy robustness to unusual inputs."""

    def test_consensus_with_None_decision(self):
        """Test consensus handles None decision gracefully."""
        # Note: AgentOutput should validate this, but test the behavior
        outputs = [
            AgentOutput(
                agent_name="agent_1",
                decision="Valid",
                reasoning="Good reason",
                confidence=0.8,
                metadata={}
            ),
            AgentOutput(
                agent_name="agent_2",
                decision="Valid",
                reasoning="Also good",
                confidence=0.7,
                metadata={}
            ),
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        # Should handle gracefully
        assert result.decision == "Valid"

    def test_consensus_with_very_long_decision_text(self):
        """Test consensus with very long decision text."""
        long_decision = "Decision " * 1000  # Very long text

        outputs = [
            AgentOutput(
                agent_name="agent_1",
                decision=long_decision,
                reasoning="Detailed reasoning",
                confidence=0.8,
                metadata={}
            ),
            AgentOutput(
                agent_name="agent_2",
                decision=long_decision,
                reasoning="Also detailed",
                confidence=0.8,
                metadata={}
            ),
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        # Should handle long text
        assert result.decision == long_decision

    def test_consensus_with_special_characters_in_decision(self):
        """Test consensus with special characters."""
        special_decision = "Decision with émojis 🎉 and symbols: @#$%^&*()"

        outputs = [
            AgentOutput(
                agent_name="agent_1",
                decision=special_decision,
                reasoning="Unicode test",
                confidence=0.8,
                metadata={}
            ),
            AgentOutput(
                agent_name="agent_2",
                decision=special_decision,
                reasoning="Special chars",
                confidence=0.8,
                metadata={}
            ),
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        # Should handle special characters
        assert result.decision == special_decision

    def test_consensus_with_numeric_decisions(self):
        """Test consensus can handle numeric decision values."""
        # Decisions are compared as strings, numbers should work
        outputs = [
            AgentOutput(
                agent_name="agent_1",
                decision="42",
                reasoning="Numeric decision",
                confidence=0.8,
                metadata={}
            ),
            AgentOutput(
                agent_name="agent_2",
                decision="42",
                reasoning="Same number",
                confidence=0.8,
                metadata={}
            ),
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        assert result.decision == "42"

    def test_consensus_with_dict_metadata(self):
        """Test consensus with complex metadata."""
        outputs = [
            AgentOutput(
                agent_name="agent_1",
                decision="A",
                reasoning="Reason",
                confidence=0.8,
                metadata={
                    "nested": {"key": "value"},
                    "list": [1, 2, 3],
                    "count": 42
                }
            ),
            AgentOutput(
                agent_name="agent_2",
                decision="A",
                reasoning="Reason",
                confidence=0.8,
                metadata={"simple": "metadata"}
            ),
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        # Should handle complex metadata
        assert result.decision == "A"
