"""
Tests for ImprovementStrategy interface.

Verifies that:
1. Abstract methods are enforced (cannot instantiate base class)
2. Concrete implementations must implement required methods
3. Data classes work correctly
4. Default estimate_impact works
"""

import pytest
from typing import List

from src.self_improvement.strategies.strategy import (
    ImprovementStrategy,
    AgentConfig,
    LearnedPattern,
)


class MockStrategy(ImprovementStrategy):
    """Concrete strategy for testing."""

    @property
    def name(self) -> str:
        return "mock_strategy"

    def generate_variants(
        self, current_config: AgentConfig, patterns: List[LearnedPattern]
    ) -> List[AgentConfig]:
        # Generate 2 simple variants
        variant1 = AgentConfig(
            inference={"model": "gpt-3.5-turbo"},
            prompt=current_config.prompt,
            caching=current_config.caching,
        )
        variant2 = AgentConfig(
            inference={"model": "gpt-4"},
            prompt=current_config.prompt,
            caching=current_config.caching,
        )
        return [variant1, variant2]

    def is_applicable(self, problem_type: str) -> bool:
        return problem_type in ["cost_high", "speed_low"]


class TestImprovementStrategy:
    """Test ImprovementStrategy abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        """Cannot create instance of abstract ImprovementStrategy."""
        with pytest.raises(TypeError):
            ImprovementStrategy()  # type: ignore

    def test_concrete_strategy_has_name(self):
        """Concrete strategy must implement name property."""
        strategy = MockStrategy()
        assert strategy.name == "mock_strategy"

    def test_concrete_strategy_generates_variants(self):
        """Concrete strategy must implement generate_variants."""
        strategy = MockStrategy()
        current = AgentConfig(
            inference={"model": "gpt-4", "temperature": 0.7},
            prompt={"template": "default"},
        )
        patterns = [
            LearnedPattern(
                pattern_type="cost_high",
                description="Costs too high",
                support=10,
                confidence=0.9,
                evidence={},
            )
        ]

        variants = strategy.generate_variants(current, patterns)

        assert isinstance(variants, list)
        assert len(variants) == 2
        assert all(isinstance(v, AgentConfig) for v in variants)
        assert variants[0].inference["model"] == "gpt-3.5-turbo"
        assert variants[1].inference["model"] == "gpt-4"

    def test_concrete_strategy_checks_applicability(self):
        """Concrete strategy must implement is_applicable."""
        strategy = MockStrategy()

        assert strategy.is_applicable("cost_high") is True
        assert strategy.is_applicable("speed_low") is True
        assert strategy.is_applicable("quality_low") is False

    def test_default_estimate_impact(self):
        """Default estimate_impact returns 0.1."""
        strategy = MockStrategy()
        problem = {"type": "cost_high", "severity": 0.8}

        impact = strategy.estimate_impact(problem)

        assert impact == 0.1

    def test_estimate_impact_can_be_overridden(self):
        """Subclass can override estimate_impact."""

        class CustomStrategy(MockStrategy):
            def estimate_impact(self, problem: dict) -> float:
                return 0.5

        strategy = CustomStrategy()
        assert strategy.estimate_impact({}) == 0.5


class TestAgentConfig:
    """Test AgentConfig data class."""

    def test_agent_config_creation(self):
        """Can create AgentConfig with all fields."""
        config = AgentConfig(
            inference={"model": "gpt-4", "temperature": 0.7},
            prompt={"template": "You are a helpful assistant"},
            caching={"enabled": True, "ttl": 3600},
            metadata={"version": "1.0"},
        )

        assert config.inference["model"] == "gpt-4"
        assert config.prompt["template"] == "You are a helpful assistant"
        assert config.caching["enabled"] is True
        assert config.metadata["version"] == "1.0"

    def test_agent_config_defaults(self):
        """AgentConfig uses empty dicts as defaults."""
        config = AgentConfig()

        assert config.inference == {}
        assert config.prompt == {}
        assert config.caching == {}
        assert config.metadata == {}

    def test_agent_config_partial(self):
        """Can create AgentConfig with partial fields."""
        config = AgentConfig(inference={"model": "gpt-4"})

        assert config.inference == {"model": "gpt-4"}
        assert config.prompt == {}
        assert config.caching == {}


class TestLearnedPattern:
    """Test LearnedPattern data class."""

    def test_learned_pattern_creation(self):
        """Can create LearnedPattern with all fields."""
        pattern = LearnedPattern(
            pattern_type="slow_response",
            description="Response time > 2s",
            support=15,
            confidence=0.85,
            evidence={"avg_latency": 2.3, "samples": 15},
        )

        assert pattern.pattern_type == "slow_response"
        assert pattern.description == "Response time > 2s"
        assert pattern.support == 15
        assert pattern.confidence == 0.85
        assert pattern.evidence["avg_latency"] == 2.3

    def test_learned_pattern_required_fields(self):
        """LearnedPattern requires core fields."""
        pattern = LearnedPattern(
            pattern_type="test", description="Test pattern", support=1, confidence=0.5
        )

        assert pattern.pattern_type == "test"
        assert pattern.description == "Test pattern"
        assert pattern.support == 1
        assert pattern.confidence == 0.5
        assert pattern.evidence == {}  # Default empty dict

    def test_learned_pattern_confidence_range(self):
        """Confidence values are between 0 and 1."""
        low = LearnedPattern("test", "Low confidence", 1, 0.1)
        high = LearnedPattern("test", "High confidence", 100, 0.95)

        assert 0.0 <= low.confidence <= 1.0
        assert 0.0 <= high.confidence <= 1.0

    def test_learned_pattern_validates_confidence_too_high(self):
        """LearnedPattern rejects confidence > 1.0."""
        with pytest.raises(ValueError, match="Confidence must be in range"):
            LearnedPattern("test", "Test", 1, confidence=1.5)

    def test_learned_pattern_validates_confidence_too_low(self):
        """LearnedPattern rejects confidence < 0.0."""
        with pytest.raises(ValueError, match="Confidence must be in range"):
            LearnedPattern("test", "Test", 1, confidence=-0.1)

    def test_learned_pattern_validates_negative_support(self):
        """LearnedPattern rejects negative support."""
        with pytest.raises(ValueError, match="Support must be non-negative"):
            LearnedPattern("test", "Test", support=-1, confidence=0.5)

    def test_learned_pattern_validates_empty_pattern_type(self):
        """LearnedPattern rejects empty pattern_type."""
        with pytest.raises(ValueError, match="pattern_type cannot be empty"):
            LearnedPattern("", "Test", 1, 0.5)

    def test_learned_pattern_accepts_edge_values(self):
        """LearnedPattern accepts 0.0 and 1.0 confidence, 0 support."""
        min_conf = LearnedPattern("test", "Min", 0, 0.0)
        max_conf = LearnedPattern("test", "Max", 0, 1.0)

        assert min_conf.confidence == 0.0
        assert max_conf.confidence == 1.0
        assert min_conf.support == 0


class TestStrategyIntegration:
    """Integration tests for strategy system."""

    def test_strategy_with_empty_patterns(self):
        """Strategy works with empty pattern list (MVP scenario)."""
        strategy = MockStrategy()
        current = AgentConfig(inference={"model": "gpt-4"})
        patterns = []

        variants = strategy.generate_variants(current, patterns)

        # Should still generate variants even without patterns
        assert len(variants) == 2

    def test_strategy_with_multiple_patterns(self):
        """Strategy receives multiple learned patterns."""
        strategy = MockStrategy()
        current = AgentConfig(inference={"model": "gpt-4"})
        patterns = [
            LearnedPattern("cost", "High cost", 20, 0.9, {}),
            LearnedPattern("latency", "Slow", 15, 0.8, {}),
            LearnedPattern("quality", "Low quality", 5, 0.6, {}),
        ]

        variants = strategy.generate_variants(current, patterns)

        # Strategy should process multiple patterns successfully
        assert isinstance(variants, list)
        assert len(variants) > 0

    def test_missing_abstract_method_raises_error(self):
        """Forgetting to implement abstract method raises TypeError."""

        with pytest.raises(TypeError):

            class IncompleteStrategy(ImprovementStrategy):  # type: ignore
                @property
                def name(self) -> str:
                    return "incomplete"

                # Missing generate_variants and is_applicable

            # Attempting to instantiate should raise TypeError
            IncompleteStrategy()
