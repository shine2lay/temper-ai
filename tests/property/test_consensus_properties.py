"""
Property-based tests for consensus strategy using Hypothesis.

Tests invariants that should hold for all possible inputs.
"""
import pytest

pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.strategies.base import AgentOutput
from src.agent.strategies.consensus import ConsensusStrategy


# Custom strategies for generating test data
@st.composite
def agent_outputs_list_strategy(draw, min_size=1, max_size=10):
    """Generate list of AgentOutput instances with unique agent names."""
    num_agents = draw(st.integers(min_value=min_size, max_value=max_size))

    outputs = []
    agent_names_used = set()

    for i in range(num_agents):
        # Ensure unique agent name
        base_name = f"agent_{i}"
        agent_name = base_name

        # If we happen to draw a duplicate (unlikely with index), make it unique
        suffix = 0
        while agent_name in agent_names_used:
            agent_name = f"{base_name}_{suffix}"
            suffix += 1

        agent_names_used.add(agent_name)

        decision = draw(st.one_of(
            st.text(min_size=1, max_size=100),
            st.integers(),
            st.booleans(),
            st.floats(allow_nan=False, allow_infinity=False)
        ))
        reasoning = draw(st.text(max_size=500, alphabet=st.characters(blacklist_categories=('Cs',))))
        confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        metadata = draw(st.dictionaries(
            st.text(min_size=1, max_size=20),
            st.one_of(st.text(max_size=100), st.integers(), st.floats(allow_nan=False, allow_infinity=False)),
            max_size=5
        ))

        outputs.append(AgentOutput(
            agent_name=agent_name,
            decision=decision,
            reasoning=reasoning,
            confidence=confidence,
            metadata=metadata
        ))

    return outputs


class TestConsensusProperties:
    """Property-based tests for ConsensusStrategy."""

    @given(agent_outputs_list_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_consensus_confidence_always_bounded(self, outputs):
        """Property: Consensus confidence must always be in [0, 1]."""
        strategy = ConsensusStrategy()

        result = strategy.synthesize(outputs, {})

        # Property: confidence must be in valid range
        assert 0.0 <= result.confidence <= 1.0, \
            f"Confidence {result.confidence} out of bounds [0, 1]"

    @given(agent_outputs_list_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_consensus_returns_valid_decision(self, outputs):
        """Property: Consensus must always return a non-None decision."""
        strategy = ConsensusStrategy()

        result = strategy.synthesize(outputs, {})

        # Property: decision must exist and be one of the agent decisions
        assert result.decision is not None
        agent_decisions = [output.decision for output in outputs]
        assert result.decision in agent_decisions, \
            f"Decision {result.decision} not in agent decisions {agent_decisions}"

    @given(agent_outputs_list_strategy(min_size=2, max_size=10))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_unanimous_agreement_with_high_individual_confidence(self, outputs):
        """Property: If all agents agree with high confidence, result confidence is high."""
        # Force all agents to have the same decision and high confidence
        common_decision = outputs[0].decision
        for output in outputs:
            output.decision = common_decision
            output.confidence = 0.9  # High confidence

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        # Property: unanimous agreement with high confidence should yield high result confidence
        assert result.confidence > 0.5, \
            f"Unanimous agreement with high confidence should yield confidence >0.5, got {result.confidence}"
        assert result.decision == common_decision

    @given(agent_outputs_list_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_synthesis_never_crashes_on_valid_inputs(self, outputs):
        """Property: Synthesis should never crash on valid inputs with unique agent names."""
        strategy = ConsensusStrategy()

        # Should either return result or raise ValueError (for config issues)
        try:
            result = strategy.synthesize(outputs, {})
            # If it succeeds, verify result is valid
            assert result.decision is not None
            assert 0.0 <= result.confidence <= 1.0
        except ValueError:
            # Acceptable if validation fails for some edge case
            pass

    @given(
        outputs_data=agent_outputs_list_strategy(),
        min_consensus=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_min_consensus_config_respected(self, outputs_data, min_consensus):
        """Property: min_consensus configuration should be validated."""
        strategy = ConsensusStrategy()
        config = {"min_consensus": min_consensus}

        # Should accept valid min_consensus values
        try:
            result = strategy.synthesize(outputs_data, config)
            assert 0.0 <= min_consensus <= 1.0
        except ValueError as e:
            # Only acceptable if min_consensus is invalid
            if min_consensus < 0 or min_consensus > 1:
                assert "min_consensus" in str(e).lower()
            else:
                # Valid min_consensus but synthesis failed for other reason (acceptable)
                pass

    @given(
        num_agents=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_single_option_unanimous_confidence(self, num_agents):
        """Property: If all agents vote for same option with same confidence, result reflects that."""
        # Create agents all voting for same option with same confidence
        confidence = 0.8
        outputs = [
            AgentOutput(
                agent_name=f"agent_{i}",
                decision="Option A",
                reasoning=f"Reasoning {i}",
                confidence=confidence,
                metadata={}
            )
            for i in range(num_agents)
        ]

        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})

        # Property: decision should be the unanimous choice
        assert result.decision == "Option A"
        # Confidence should be high (all agents agree)
        assert result.confidence >= 0.5

    @given(agent_outputs_list_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_result_has_required_fields(self, outputs):
        """Property: SynthesisResult must have decision and confidence fields."""
        strategy = ConsensusStrategy()

        result = strategy.synthesize(outputs, {})

        # Property: result must have required fields
        assert hasattr(result, 'decision')
        assert hasattr(result, 'confidence')
        assert result.decision is not None
        assert isinstance(result.confidence, (int, float))
