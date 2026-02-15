"""Tests for collaboration strategy base classes and utilities.

This test module verifies:
- Abstract base class cannot be instantiated
- Dataclass validation works correctly
- Utility functions produce expected results
- Conflict detection identifies disagreements
- Feature detection and metadata work
"""

import pytest

from src.agent.strategies.base import (
    AgentOutput,
    CollaborationStrategy,
    Conflict,
    SynthesisMethod,
    SynthesisResult,
    calculate_consensus_confidence,
    calculate_vote_distribution,
    extract_majority_decision,
)


class TestCollaborationStrategy:
    """Test CollaborationStrategy abstract base class."""

    def test_collaboration_strategy_is_abstract(self):
        """CollaborationStrategy cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            CollaborationStrategy()

    def test_synthesize_method_is_abstract(self):
        """synthesize() method is abstract."""
        assert hasattr(CollaborationStrategy, 'synthesize')
        assert getattr(CollaborationStrategy.synthesize, '__isabstractmethod__', False)

    def test_get_capabilities_method_is_abstract(self):
        """get_capabilities() method is abstract."""
        assert hasattr(CollaborationStrategy, 'get_capabilities')
        assert getattr(CollaborationStrategy.get_capabilities, '__isabstractmethod__', False)

    def test_get_metadata_has_default_implementation(self):
        """get_metadata() has a default implementation."""
        # Create concrete strategy for testing
        class MockStrategy(CollaborationStrategy):
            def synthesize(self, agent_outputs, config):
                pass
            def get_capabilities(self):
                return {}

        strategy = MockStrategy()
        metadata = strategy.get_metadata()

        assert "name" in metadata
        assert metadata["name"] == "MockStrategy"
        assert "version" in metadata
        assert "description" in metadata
        assert "config_schema" in metadata


class TestAgentOutput:
    """Test AgentOutput dataclass."""

    def test_agent_output_valid_creation(self):
        """Test creating valid AgentOutput."""
        output = AgentOutput(
            agent_name="test_agent",
            decision="yes",
            reasoning="because it makes sense",
            confidence=0.9,
            metadata={"tokens": 100}
        )

        assert output.agent_name == "test_agent"
        assert output.decision == "yes"
        assert output.reasoning == "because it makes sense"
        assert output.confidence == 0.9
        assert output.metadata == {"tokens": 100}

    def test_agent_output_confidence_too_high(self):
        """Test AgentOutput rejects confidence > 1."""
        with pytest.raises(ValueError, match="Confidence must be between 0 and 1"):
            AgentOutput(
                agent_name="test",
                decision="yes",
                reasoning="reason",
                confidence=1.5,
                metadata={}
            )

    def test_agent_output_confidence_too_low(self):
        """Test AgentOutput rejects confidence < 0."""
        with pytest.raises(ValueError, match="Confidence must be between 0 and 1"):
            AgentOutput(
                agent_name="test",
                decision="yes",
                reasoning="reason",
                confidence=-0.1,
                metadata={}
            )

    def test_agent_output_confidence_edge_cases(self):
        """Test AgentOutput accepts confidence of exactly 0 and 1."""
        # confidence = 0.0
        output_zero = AgentOutput("test", "yes", "reason", 0.0, {})
        assert output_zero.confidence == 0.0

        # confidence = 1.0
        output_one = AgentOutput("test", "yes", "reason", 1.0, {})
        assert output_one.confidence == 1.0

    def test_agent_output_empty_agent_name(self):
        """Test AgentOutput rejects empty agent_name."""
        with pytest.raises(ValueError, match="agent_name cannot be empty"):
            AgentOutput(
                agent_name="",
                decision="yes",
                reasoning="reason",
                confidence=0.9,
                metadata={}
            )

    def test_agent_output_default_metadata(self):
        """Test AgentOutput uses empty dict as default metadata."""
        output = AgentOutput(
            agent_name="test",
            decision="yes",
            reasoning="reason",
            confidence=0.9
        )
        assert output.metadata == {}


class TestConflict:
    """Test Conflict dataclass."""

    def test_conflict_valid_creation(self):
        """Test creating valid Conflict."""
        conflict = Conflict(
            agents=["agent1", "agent2", "agent3"],
            decisions=["Option A", "Option B"],
            disagreement_score=0.67,
            context={"num_rounds": 3}
        )

        assert conflict.agents == ["agent1", "agent2", "agent3"]
        assert conflict.decisions == ["Option A", "Option B"]
        assert conflict.disagreement_score == 0.67
        assert conflict.context == {"num_rounds": 3}

    def test_conflict_disagreement_score_too_high(self):
        """Test Conflict rejects disagreement_score > 1."""
        with pytest.raises(ValueError, match="disagreement_score must be between 0 and 1"):
            Conflict(
                agents=["a1", "a2"],
                decisions=["yes", "no"],
                disagreement_score=1.5,
                context={}
            )

    def test_conflict_disagreement_score_too_low(self):
        """Test Conflict rejects disagreement_score < 0."""
        with pytest.raises(ValueError, match="disagreement_score must be between 0 and 1"):
            Conflict(
                agents=["a1", "a2"],
                decisions=["yes", "no"],
                disagreement_score=-0.1,
                context={}
            )

    def test_conflict_default_context(self):
        """Test Conflict uses empty dict as default context."""
        conflict = Conflict(
            agents=["a1"],
            decisions=["yes"],
            disagreement_score=0.5
        )
        assert conflict.context == {}

    def test_conflict_empty_agents(self):
        """Test Conflict rejects empty agents list."""
        with pytest.raises(ValueError, match="Conflict must have at least one agent"):
            Conflict(
                agents=[],
                decisions=["yes"],
                disagreement_score=0.5,
                context={}
            )

    def test_conflict_empty_decisions(self):
        """Test Conflict rejects empty decisions list."""
        with pytest.raises(ValueError, match="Conflict must have at least one decision"):
            Conflict(
                agents=["a1"],
                decisions=[],
                disagreement_score=0.5,
                context={}
            )


class TestSynthesisResult:
    """Test SynthesisResult dataclass."""

    def test_synthesis_result_valid_creation(self):
        """Test creating valid SynthesisResult."""
        result = SynthesisResult(
            decision="Option A",
            confidence=0.85,
            method="consensus",
            votes={"Option A": 3, "Option B": 1},
            conflicts=[],
            reasoning="Majority voted for Option A",
            metadata={"rounds": 1}
        )

        assert result.decision == "Option A"
        assert result.confidence == 0.85
        assert result.method == "consensus"
        assert result.votes == {"Option A": 3, "Option B": 1}
        assert result.conflicts == []
        assert result.reasoning == "Majority voted for Option A"
        assert result.metadata == {"rounds": 1}

    def test_synthesis_result_confidence_boundaries(self):
        """Test SynthesisResult validates confidence score."""
        with pytest.raises(ValueError, match="Confidence must be between 0 and 1"):
            SynthesisResult(
                decision="yes",
                confidence=1.2,
                method="consensus",
                votes={},
                conflicts=[],
                reasoning="test",
                metadata={}
            )

    def test_synthesis_result_default_metadata(self):
        """Test SynthesisResult uses empty dict as default metadata."""
        result = SynthesisResult(
            decision="yes",
            confidence=0.8,
            method="consensus",
            votes={},
            conflicts=[],
            reasoning="test"
        )
        assert result.metadata == {}


class TestSynthesisMethod:
    """Test SynthesisMethod enum."""

    def test_synthesis_method_has_all_values(self):
        """Test enum has all expected synthesis methods."""
        assert SynthesisMethod.CONSENSUS.value == "consensus"
        assert SynthesisMethod.WEIGHTED_MERGE.value == "weighted_merge"
        assert SynthesisMethod.BEST_OF.value == "best_of"
        assert SynthesisMethod.DEBATE_EXTRACT.value == "debate_extract"
        assert SynthesisMethod.HIERARCHICAL.value == "hierarchical"

    def test_synthesis_method_membership(self):
        """Test enum membership checking."""
        assert SynthesisMethod.CONSENSUS in SynthesisMethod
        assert SynthesisMethod.WEIGHTED_MERGE in SynthesisMethod


class TestValidateInputs:
    """Test validate_inputs() method."""

    def test_validate_inputs_empty_list(self):
        """Test validation rejects empty agent_outputs."""
        class MockStrategy(CollaborationStrategy):
            def synthesize(self, agent_outputs, config):
                pass
            def get_capabilities(self):
                return {}

        strategy = MockStrategy()

        with pytest.raises(ValueError, match="agent_outputs cannot be empty"):
            strategy.validate_inputs([])

    def test_validate_inputs_wrong_type(self):
        """Test validation rejects non-AgentOutput instances."""
        class MockStrategy(CollaborationStrategy):
            def synthesize(self, agent_outputs, config):
                pass
            def get_capabilities(self):
                return {}

        strategy = MockStrategy()

        with pytest.raises(ValueError, match="All outputs must be AgentOutput instances"):
            strategy.validate_inputs([{"agent": "test"}])

    def test_validate_inputs_duplicate_agent_names(self):
        """Test validation rejects duplicate agent names."""
        class MockStrategy(CollaborationStrategy):
            def synthesize(self, agent_outputs, config):
                pass
            def get_capabilities(self):
                return {}

        strategy = MockStrategy()
        outputs = [
            AgentOutput("agent1", "yes", "r1", 0.9, {}),
            AgentOutput("agent1", "no", "r2", 0.8, {}),  # Duplicate name
        ]

        with pytest.raises(ValueError, match="Duplicate agent names detected.*agent1.*2"):
            strategy.validate_inputs(outputs)

    def test_validate_inputs_valid_outputs(self):
        """Test validation passes for valid outputs."""
        class MockStrategy(CollaborationStrategy):
            def synthesize(self, agent_outputs, config):
                pass
            def get_capabilities(self):
                return {}

        strategy = MockStrategy()
        outputs = [
            AgentOutput("agent1", "yes", "r1", 0.9, {}),
            AgentOutput("agent2", "yes", "r2", 0.8, {}),
        ]

        # Should not raise
        strategy.validate_inputs(outputs)
        assert True  # Verifies no exception raised


class TestDetectConflicts:
    """Test detect_conflicts() method."""

    def test_detect_conflicts_no_conflict(self):
        """Test no conflicts detected when all agents agree."""
        class MockStrategy(CollaborationStrategy):
            def synthesize(self, agent_outputs, config):
                pass
            def get_capabilities(self):
                return {}

        strategy = MockStrategy()
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "yes", "r2", 0.8, {}),
            AgentOutput("a3", "yes", "r3", 0.7, {}),
        ]

        conflicts = strategy.detect_conflicts(outputs, threshold=0.3)
        assert len(conflicts) == 0

    def test_detect_conflicts_minor_disagreement(self):
        """Test conflict detected for minor disagreement."""
        class MockStrategy(CollaborationStrategy):
            def synthesize(self, agent_outputs, config):
                pass
            def get_capabilities(self):
                return {}

        strategy = MockStrategy()
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "yes", "r2", 0.8, {}),
            AgentOutput("a3", "no", "r3", 0.7, {}),  # 1 dissenter
        ]

        conflicts = strategy.detect_conflicts(outputs, threshold=0.3)
        assert len(conflicts) == 1
        assert conflicts[0].disagreement_score > 0.3
        # disagreement_score = 1 - (2/3) = 0.33
        assert 0.32 < conflicts[0].disagreement_score < 0.34

    def test_detect_conflicts_threshold_filtering(self):
        """Test conflicts below threshold are filtered out."""
        class MockStrategy(CollaborationStrategy):
            def synthesize(self, agent_outputs, config):
                pass
            def get_capabilities(self):
                return {}

        strategy = MockStrategy()
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "yes", "r2", 0.8, {}),
            AgentOutput("a3", "no", "r3", 0.7, {}),
        ]

        # High threshold should filter out this minor conflict
        conflicts = strategy.detect_conflicts(outputs, threshold=0.5)
        assert len(conflicts) == 0

    def test_detect_conflicts_context_metadata(self):
        """Test conflict includes context metadata."""
        class MockStrategy(CollaborationStrategy):
            def synthesize(self, agent_outputs, config):
                pass
            def get_capabilities(self):
                return {}

        strategy = MockStrategy()
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "no", "r2", 0.8, {}),
        ]

        conflicts = strategy.detect_conflicts(outputs, threshold=0.3)
        assert len(conflicts) == 1

        context = conflicts[0].context
        assert "num_decisions" in context
        assert context["num_decisions"] == 2
        assert "largest_group_size" in context
        assert context["largest_group_size"] == 1
        assert "decision_distribution" in context


class TestUtilityFunctions:
    """Test utility functions."""

    def test_calculate_consensus_confidence_unanimous(self):
        """Test confidence calculation for unanimous decision."""
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "yes", "r2", 0.8, {}),
            AgentOutput("a3", "yes", "r3", 0.7, {}),
        ]

        confidence = calculate_consensus_confidence(outputs, "yes")
        # 3/3 agents * avg(0.9, 0.8, 0.7) = 1.0 * 0.8 = 0.8
        assert 0.79 < confidence < 0.81

    def test_calculate_consensus_confidence_majority(self):
        """Test confidence calculation for majority decision."""
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "yes", "r2", 0.8, {}),
            AgentOutput("a3", "no", "r3", 0.7, {}),
        ]

        confidence = calculate_consensus_confidence(outputs, "yes")
        # 2/3 agents * avg(0.9, 0.8) = 0.667 * 0.85 = 0.567
        assert 0.55 < confidence < 0.60

    def test_calculate_consensus_confidence_no_supporters(self):
        """Test confidence is 0 when no agents support decision."""
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "yes", "r2", 0.8, {}),
        ]

        confidence = calculate_consensus_confidence(outputs, "no")
        assert confidence == 0.0

    def test_extract_majority_decision_clear_majority(self):
        """Test extracting decision with clear majority."""
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "yes", "r2", 0.8, {}),
            AgentOutput("a3", "no", "r3", 0.7, {}),
        ]

        decision = extract_majority_decision(outputs)
        assert decision == "yes"

    def test_extract_majority_decision_tie(self):
        """Test extracting decision returns None for tie."""
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "no", "r2", 0.8, {}),
        ]

        decision = extract_majority_decision(outputs)
        assert decision is None

    def test_extract_majority_decision_empty(self):
        """Test extracting decision from empty list returns None."""
        decision = extract_majority_decision([])
        assert decision is None

    def test_calculate_vote_distribution(self):
        """Test vote distribution calculation."""
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "yes", "r2", 0.8, {}),
            AgentOutput("a3", "no", "r3", 0.7, {}),
        ]

        votes = calculate_vote_distribution(outputs)
        assert votes == {"yes": 2, "no": 1}

    def test_calculate_vote_distribution_unanimous(self):
        """Test vote distribution for unanimous decision."""
        outputs = [
            AgentOutput("a1", "yes", "r1", 0.9, {}),
            AgentOutput("a2", "yes", "r2", 0.8, {}),
        ]

        votes = calculate_vote_distribution(outputs)
        assert votes == {"yes": 2}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
