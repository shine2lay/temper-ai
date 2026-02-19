"""Tests for conflict resolution strategies."""

import pytest

from temper_ai.agent.strategies.base import AgentOutput, Conflict
from temper_ai.agent.strategies.conflict_resolution import (
    ConflictResolutionStrategy,
    HighestConfidenceResolver,
    MeritWeightedResolver,
    RandomTiebreakerResolver,
    ResolutionMethod,
    ResolutionResult,
    create_resolver,
)


def test_resolution_strategy_is_abstract():
    """ConflictResolutionStrategy cannot be instantiated directly."""
    with pytest.raises(TypeError):
        ConflictResolutionStrategy()


def test_resolution_result_boundaries():
    """Test ResolutionResult validation."""
    # Valid result
    result = ResolutionResult(
        decision="yes",
        method="test",
        reasoning="test reasoning",
        success=True,
        confidence=0.9,
        metadata={}
    )
    assert result.confidence == 0.9
    assert result.success is True

    # Invalid confidence (> 1)
    with pytest.raises(ValueError, match="Confidence must be"):
        ResolutionResult("yes", "test", "test", True, 1.5, {})

    # Invalid confidence (< 0)
    with pytest.raises(ValueError, match="Confidence must be"):
        ResolutionResult("yes", "test", "test", True, -0.1, {})


def test_highest_confidence_resolver():
    """Test highest confidence resolution."""
    resolver = HighestConfidenceResolver()

    outputs = [
        AgentOutput("a1", "yes", "r1", 0.9, {}),
        AgentOutput("a2", "no", "r2", 0.7, {}),
        AgentOutput("a3", "yes", "r3", 0.8, {})
    ]

    conflict = Conflict(
        agents=["a1", "a2"],
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    result = resolver.resolve(conflict, outputs, {})

    assert result.success
    assert result.decision == "yes"  # a1 has highest confidence
    assert result.confidence == 0.9
    assert result.metadata["winner"] == "a1"
    assert "all_confidences" in result.metadata
    assert result.metadata["all_confidences"]["a1"] == 0.9
    assert result.metadata["all_confidences"]["a2"] == 0.7


def test_highest_confidence_resolver_capabilities():
    """Test highest confidence resolver capabilities."""
    resolver = HighestConfidenceResolver()
    caps = resolver.get_capabilities()

    assert caps["deterministic"] is True
    assert caps["supports_negotiation"] is False
    assert caps["supports_escalation"] is False


def test_random_tiebreaker_deterministic():
    """Test random tiebreaker with seed is deterministic."""
    resolver1 = RandomTiebreakerResolver(seed=42)
    resolver2 = RandomTiebreakerResolver(seed=42)

    outputs = [
        AgentOutput("a1", "yes", "r1", 0.9, {}),
        AgentOutput("a2", "no", "r2", 0.8, {})
    ]

    conflict = Conflict(
        agents=["a1", "a2"],
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    result1 = resolver1.resolve(conflict, outputs, {})
    result2 = resolver2.resolve(conflict, outputs, {})

    # Same seed should produce same result
    assert result1.decision == result2.decision
    assert result1.metadata["winner"] == result2.metadata["winner"]


def test_random_tiebreaker_capabilities():
    """Test random tiebreaker capabilities."""
    # Deterministic with seed
    resolver_with_seed = RandomTiebreakerResolver(seed=42)
    caps = resolver_with_seed.get_capabilities()
    assert caps["deterministic"] is True

    # Non-deterministic without seed
    resolver_no_seed = RandomTiebreakerResolver()
    caps = resolver_no_seed.get_capabilities()
    assert caps["deterministic"] is False


def test_random_tiebreaker_metadata():
    """Test random tiebreaker includes metadata."""
    resolver = RandomTiebreakerResolver(seed=42)

    outputs = [
        AgentOutput("a1", "yes", "r1", 0.9, {}),
        AgentOutput("a2", "no", "r2", 0.8, {})
    ]

    conflict = Conflict(
        agents=["a1", "a2"],
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    result = resolver.resolve(conflict, outputs, {})

    assert result.success
    assert "seed" in result.metadata
    assert result.metadata["seed"] == 42
    assert "candidates" in result.metadata
    assert set(result.metadata["candidates"]) == {"a1", "a2"}


def test_merit_weighted_resolver():
    """Test merit-weighted resolution."""
    resolver = MeritWeightedResolver()

    outputs = [
        AgentOutput("expert", "yes", "r1", 0.8, {"merit": 0.95}),
        AgentOutput("novice", "no", "r2", 0.9, {"merit": 0.6})
    ]

    conflict = Conflict(
        agents=["expert", "novice"],
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    result = resolver.resolve(conflict, outputs, {})

    assert result.success
    assert result.decision == "yes"  # expert has higher merit
    assert result.metadata["winner"] == "expert"
    assert result.metadata["merit_scores"]["expert"] == 0.95
    assert result.metadata["merit_scores"]["novice"] == 0.6


def test_merit_weighted_resolver_fallback_to_confidence():
    """Test merit-weighted resolver uses confidence when merit not provided."""
    resolver = MeritWeightedResolver()

    outputs = [
        AgentOutput("a1", "yes", "r1", 0.9, {}),  # No merit, uses confidence
        AgentOutput("a2", "no", "r2", 0.7, {})  # No merit, uses confidence
    ]

    conflict = Conflict(
        agents=["a1", "a2"],
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    result = resolver.resolve(conflict, outputs, {})

    assert result.success
    assert result.decision == "yes"  # a1 has higher confidence as proxy
    assert result.metadata["winner"] == "a1"
    # Merit scores should equal confidence when merit not provided
    assert result.metadata["merit_scores"]["a1"] == 0.9
    assert result.metadata["merit_scores"]["a2"] == 0.7


def test_merit_weighted_resolver_capabilities():
    """Test merit-weighted resolver capabilities."""
    resolver = MeritWeightedResolver()
    caps = resolver.get_capabilities()

    assert caps["deterministic"] is True
    assert caps["supports_merit_weighting"] is True


def test_resolver_factory():
    """Test resolver factory function."""
    # Highest confidence
    resolver = create_resolver(ResolutionMethod.HIGHEST_CONFIDENCE)
    assert isinstance(resolver, HighestConfidenceResolver)

    # Random with seed
    resolver = create_resolver(
        ResolutionMethod.RANDOM_TIEBREAKER,
        {"seed": 42}
    )
    assert isinstance(resolver, RandomTiebreakerResolver)
    assert resolver.seed == 42

    # Random without seed
    resolver = create_resolver(ResolutionMethod.RANDOM_TIEBREAKER)
    assert isinstance(resolver, RandomTiebreakerResolver)
    assert resolver.seed is None

    # Merit weighted
    resolver = create_resolver(ResolutionMethod.MERIT_WEIGHTED)
    assert isinstance(resolver, MeritWeightedResolver)


def test_resolver_factory_unsupported_method():
    """Test resolver factory raises error for unsupported method."""
    with pytest.raises(ValueError, match="Unsupported resolution method"):
        create_resolver(ResolutionMethod.ESCALATION)


def test_validate_inputs_missing_agents():
    """Test validation catches agents not in outputs."""
    resolver = HighestConfidenceResolver()

    outputs = [AgentOutput("a1", "yes", "r1", 0.9, {})]

    conflict = Conflict(
        agents=["a1", "a2"],  # a2 not in outputs
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    with pytest.raises(ValueError, match="not in outputs"):
        resolver.resolve(conflict, outputs, {})


def test_validate_inputs_empty_outputs():
    """Test validation catches empty outputs."""
    resolver = HighestConfidenceResolver()

    conflict = Conflict(
        agents=["a1"],
        decisions=["yes"],
        disagreement_score=0.0,
        context={}
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        resolver.resolve(conflict, [], {})


def test_validate_inputs_wrong_type():
    """Test validation catches wrong output type."""
    resolver = HighestConfidenceResolver()

    # Use dict instead of AgentOutput
    outputs = [{"agent_name": "a1", "decision": "yes"}]

    conflict = Conflict(
        agents=["a1"],
        decisions=["yes"],
        disagreement_score=0.0,
        context={}
    )

    with pytest.raises(ValueError, match="must be AgentOutput instances"):
        resolver.resolve(conflict, outputs, {})  # type: ignore


def test_validate_inputs_wrong_conflict_type():
    """Test validation catches wrong conflict type."""
    resolver = HighestConfidenceResolver()

    outputs = [AgentOutput("a1", "yes", "r1", 0.9, {})]

    # Use dict instead of Conflict
    conflict = {"agents": ["a1"], "decisions": ["yes"]}

    with pytest.raises(ValueError, match="must be a Conflict instance"):
        resolver.resolve(conflict, outputs, {})  # type: ignore


def test_get_metadata():
    """Test get_metadata returns expected info."""
    resolver = HighestConfidenceResolver()
    metadata = resolver.get_metadata()

    assert metadata["name"] == "HighestConfidenceResolver"
    assert metadata["version"] == "1.0"
    assert "description" in metadata
    assert "config_schema" in metadata


def test_integration_with_conflict_dataclass():
    """Test integration with Conflict from base.py."""
    # Create conflict using base.py's Conflict class
    conflict = Conflict(
        agents=["agent1", "agent2", "agent3"],
        decisions=["Option A", "Option B"],
        disagreement_score=0.67,
        context={"num_decisions": 2, "largest_group_size": 2}
    )

    outputs = [
        AgentOutput("agent1", "Option A", "I think A is best", 0.9, {}),
        AgentOutput("agent2", "Option A", "I agree with A", 0.85, {}),
        AgentOutput("agent3", "Option B", "B is better", 0.8, {})
    ]

    resolver = HighestConfidenceResolver()
    result = resolver.resolve(conflict, outputs, {})

    assert result.success
    assert result.decision == "Option A"  # agent1 has highest confidence
    assert result.confidence == 0.9


def test_resolution_result_metadata_default():
    """Test ResolutionResult metadata defaults to empty dict."""
    result = ResolutionResult(
        decision="yes",
        method="test",
        reasoning="test",
        success=True,
        confidence=0.9
        # metadata not provided
    )

    assert result.metadata == {}
    assert isinstance(result.metadata, dict)
