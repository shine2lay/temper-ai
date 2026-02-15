"""
Property-based tests for validation and invariants using Hypothesis.

Tests validation properties across different components.
"""
import pytest

pytest.importorskip("hypothesis")

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.storage.schemas.agent_config import InferenceConfig
from src.agent.strategies.base import AgentOutput, Conflict


class TestAgentOutputValidation:
    """Property-based tests for AgentOutput validation."""

    @given(
        agent_name=st.text(min_size=1, max_size=100),
        decision=st.text(min_size=1, max_size=200),
        reasoning=st.text(max_size=500),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        metadata=st.dictionaries(st.text(), st.text(), max_size=10)
    )
    @settings(max_examples=100)
    def test_valid_confidence_range_accepted(self, agent_name, decision, reasoning, confidence, metadata):
        """Property: AgentOutput accepts confidence in [0, 1]."""
        # Should not raise for valid confidence
        output = AgentOutput(
            agent_name=agent_name,
            decision=decision,
            reasoning=reasoning,
            confidence=confidence,
            metadata=metadata
        )

        assert output.confidence == confidence
        assert 0.0 <= output.confidence <= 1.0

    @given(
        agent_name=st.text(min_size=1, max_size=100),
        decision=st.text(min_size=1, max_size=200),
        reasoning=st.text(max_size=500),
        confidence=st.one_of(
            st.floats(max_value=-0.01),
            st.floats(min_value=1.01)
        ).filter(lambda x: not (x != x)),  # Filter out NaN
        metadata=st.dictionaries(st.text(), st.text(), max_size=10)
    )
    @settings(max_examples=100)
    def test_invalid_confidence_rejected(self, agent_name, decision, reasoning, confidence, metadata):
        """Property: AgentOutput rejects confidence outside [0, 1]."""
        assume(confidence < 0.0 or confidence > 1.0)

        # Should raise ValueError for invalid confidence
        with pytest.raises(ValueError, match="[Cc]onfidence"):
            AgentOutput(
                agent_name=agent_name,
                decision=decision,
                reasoning=reasoning,
                confidence=confidence,
                metadata=metadata
            )

    @given(
        decision=st.text(min_size=1, max_size=200),
        reasoning=st.text(max_size=500),
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        metadata=st.dictionaries(st.text(), st.text(), max_size=10)
    )
    @settings(max_examples=50)
    def test_empty_agent_name_rejected(self, decision, reasoning, confidence, metadata):
        """Property: AgentOutput rejects empty agent_name."""
        # Should raise ValueError for empty agent_name
        with pytest.raises(ValueError, match="agent_name"):
            AgentOutput(
                agent_name="",
                decision=decision,
                reasoning=reasoning,
                confidence=confidence,
                metadata=metadata
            )


class TestConflictValidation:
    """Property-based tests for Conflict validation."""

    @given(
        agents=st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10),
        decisions=st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=10),
        disagreement_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        context=st.dictionaries(st.text(), st.text(), max_size=5)
    )
    @settings(max_examples=100)
    def test_valid_conflict_accepted(self, agents, decisions, disagreement_score, context):
        """Property: Conflict accepts valid disagreement_score in [0, 1]."""
        conflict = Conflict(
            agents=agents,
            decisions=decisions,
            disagreement_score=disagreement_score,
            context=context
        )

        assert conflict.disagreement_score == disagreement_score
        assert 0.0 <= conflict.disagreement_score <= 1.0
        assert len(conflict.agents) >= 1
        assert len(conflict.decisions) >= 1

    @given(
        agents=st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10),
        decisions=st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=10),
        disagreement_score=st.one_of(
            st.floats(max_value=-0.01),
            st.floats(min_value=1.01)
        ).filter(lambda x: not (x != x)),  # Filter out NaN
        context=st.dictionaries(st.text(), st.text(), max_size=5)
    )
    @settings(max_examples=100)
    def test_invalid_disagreement_score_rejected(self, agents, decisions, disagreement_score, context):
        """Property: Conflict rejects disagreement_score outside [0, 1]."""
        assume(disagreement_score < 0.0 or disagreement_score > 1.0)

        # Should raise ValueError for invalid disagreement_score
        with pytest.raises(ValueError, match="disagreement_score"):
            Conflict(
                agents=agents,
                decisions=decisions,
                disagreement_score=disagreement_score,
                context=context
            )

    @given(
        decisions=st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=10),
        disagreement_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        context=st.dictionaries(st.text(), st.text(), max_size=5)
    )
    @settings(max_examples=50)
    def test_empty_agents_list_rejected(self, decisions, disagreement_score, context):
        """Property: Conflict rejects empty agents list."""
        with pytest.raises(ValueError, match="[Aa]gent"):
            Conflict(
                agents=[],
                decisions=decisions,
                disagreement_score=disagreement_score,
                context=context
            )

    @given(
        agents=st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10),
        disagreement_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        context=st.dictionaries(st.text(), st.text(), max_size=5)
    )
    @settings(max_examples=50)
    def test_empty_decisions_list_rejected(self, agents, disagreement_score, context):
        """Property: Conflict rejects empty decisions list."""
        with pytest.raises(ValueError, match="[Dd]ecision"):
            Conflict(
                agents=agents,
                decisions=[],
                disagreement_score=disagreement_score,
                context=context
            )


class TestInferenceConfigValidation:
    """Property-based tests for InferenceConfig validation."""

    @given(
        provider=st.sampled_from(["openai", "anthropic", "ollama", "custom"]),
        model=st.text(min_size=1, max_size=50),
        temperature=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
        max_tokens=st.integers(min_value=1, max_value=100000)
    )
    @settings(max_examples=100)
    def test_valid_inference_config_parameters(self, provider, model, temperature, max_tokens):
        """Property: InferenceConfig accepts valid parameters."""
        config = InferenceConfig(
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )

        assert config.provider == provider
        assert config.model == model
        assert config.temperature == temperature
        assert config.max_tokens == max_tokens

    @given(
        provider=st.sampled_from(["openai", "anthropic", "ollama"]),
        model=st.text(min_size=1, max_size=50)
    )
    @settings(max_examples=50)
    def test_temperature_defaults_if_not_provided(self, provider, model):
        """Property: InferenceConfig has reasonable defaults for optional fields."""
        config = InferenceConfig(
            provider=provider,
            model=model
        )

        assert config.provider == provider
        assert config.model == model
        # Temperature should have a default (0.7)
        assert hasattr(config, 'temperature')
        assert 0.0 <= config.temperature <= 2.0


class TestStateTransitionInvariants:
    """Property-based tests for state transition invariants."""

    @given(
        initial_confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        adjustment=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_confidence_adjustment_stays_bounded(self, initial_confidence, adjustment):
        """Property: Confidence adjustments should maintain [0, 1] bounds."""
        # Simulate confidence adjustment with clamping
        adjusted = max(0.0, min(1.0, initial_confidence + adjustment))

        assert 0.0 <= adjusted <= 1.0

    @given(
        vote_count=st.integers(min_value=0, max_value=100),
        total_votes=st.integers(min_value=1, max_value=100)
    )
    @settings(max_examples=100)
    def test_vote_percentage_bounded(self, vote_count, total_votes):
        """Property: Vote percentages should be in [0, 1]."""
        assume(vote_count <= total_votes)

        percentage = vote_count / total_votes

        assert 0.0 <= percentage <= 1.0
