"""Tests for OllamaModelSelectionStrategy."""

import pytest

from src.self_improvement.strategies import (
    OllamaModelSelectionStrategy,
    AgentConfig,
    LearnedPattern,
)
from src.self_improvement.model_registry import ModelRegistry


class TestOllamaModelSelectionStrategy:
    """Test suite for OllamaModelSelectionStrategy."""

    @pytest.fixture
    def registry(self):
        """Create model registry with default models."""
        return ModelRegistry()

    @pytest.fixture
    def strategy(self, registry):
        """Create strategy instance."""
        return OllamaModelSelectionStrategy(registry)

    def test_strategy_name(self, strategy):
        """Test strategy has correct name."""
        assert strategy.name == "ollama_model_selection"

    def test_is_applicable_to_quality_low(self, strategy):
        """Test strategy applies to low quality problems."""
        assert strategy.is_applicable("quality_low") is True

    def test_is_applicable_to_cost_high(self, strategy):
        """Test strategy applies to high cost problems."""
        assert strategy.is_applicable("cost_high") is True

    def test_is_applicable_to_speed_low(self, strategy):
        """Test strategy applies to slow response problems."""
        assert strategy.is_applicable("speed_low") is True

    def test_is_applicable_to_error_rate_high(self, strategy):
        """Test strategy applies to high error rate."""
        assert strategy.is_applicable("error_rate_high") is True

    def test_not_applicable_to_unknown_problem(self, strategy):
        """Test strategy doesn't apply to unrelated problems."""
        assert strategy.is_applicable("network_issues") is False
        assert strategy.is_applicable("disk_full") is False

    def test_generate_variants_returns_list(self, strategy):
        """Test generate_variants returns a list."""
        current = AgentConfig(agent_name="test_agent", inference={"model": "phi3:mini"})
        variants = strategy.generate_variants(current, [])

        assert isinstance(variants, list)
        assert len(variants) > 0

    def test_generate_variants_creates_2_to_4_variants(self, strategy):
        """Test generates 2-4 variants."""
        current = AgentConfig(agent_name="test_agent", inference={"model": "phi3:mini"})
        variants = strategy.generate_variants(current, [])

        # Should generate up to 4 variants (all other models except current)
        assert 2 <= len(variants) <= 4

    def test_variants_have_different_models(self, strategy):
        """Test each variant uses a different model."""
        current = AgentConfig(agent_name="test_agent", inference={"model": "phi3:mini"})
        variants = strategy.generate_variants(current, [])

        models = [v.inference["model"] for v in variants]
        # All models should be unique
        assert len(models) == len(set(models))

    def test_variants_exclude_current_model(self, strategy):
        """Test variants don't include the current model."""
        current_model = "llama3.1:8b"
        current = AgentConfig(agent_name="test_agent", inference={"model": current_model})
        variants = strategy.generate_variants(current, [])

        models = [v.inference["model"] for v in variants]
        assert current_model not in models

    def test_variants_include_metadata(self, strategy):
        """Test variants include strategy metadata."""
        current = AgentConfig(agent_name="test_agent", inference={"model": "phi3:mini"})
        variants = strategy.generate_variants(current, [])

        for variant in variants:
            assert "strategy" in variant.extra_metadata
            assert variant.extra_metadata["strategy"] == "ollama_model_selection"
            assert "model_size" in variant.extra_metadata
            assert "expected_quality" in variant.extra_metadata
            assert "expected_speed" in variant.extra_metadata

    def test_generate_variants_with_low_quality_pattern(self, strategy):
        """Test generates high-quality models for low quality problems."""
        current = AgentConfig(agent_name="test_agent", inference={"model": "phi3:mini"})
        patterns = [
            LearnedPattern(
                pattern_type="low_quality",
                description="Output quality is poor",
                support=10,
                confidence=0.9,
                evidence={"avg_quality": 0.4}
            )
        ]

        variants = strategy.generate_variants(current, patterns)

        # Should prioritize larger, higher-quality models
        # qwen2.5:32b should be first (highest quality)
        assert len(variants) > 0
        # First variant should be a high-quality model
        first_variant_quality = variants[0].extra_metadata["expected_quality"]
        assert first_variant_quality in ["high", "highest"]

    def test_generate_variants_with_high_cost_pattern(self, strategy):
        """Test generates fast/cheap models for cost problems."""
        current = AgentConfig(agent_name="test_agent", inference={"model": "qwen2.5:32b"})
        patterns = [
            LearnedPattern(
                pattern_type="high_cost",
                description="Cost is too high",
                support=15,
                confidence=0.85,
                evidence={"avg_cost_usd": 0.50}
            )
        ]

        variants = strategy.generate_variants(current, patterns)

        # Should prioritize smaller, faster models
        assert len(variants) > 0
        # First variant should be a fast model
        first_variant_speed = variants[0].extra_metadata["expected_speed"]
        assert first_variant_speed in ["very_fast", "fast"]

    def test_generate_variants_with_slow_response_pattern(self, strategy):
        """Test generates fast models for latency problems."""
        current = AgentConfig(agent_name="test_agent", inference={"model": "qwen2.5:32b"})
        patterns = [
            LearnedPattern(
                pattern_type="slow_response",
                description="Response time is slow",
                support=20,
                confidence=0.95,
                evidence={"avg_latency_ms": 5000}
            )
        ]

        variants = strategy.generate_variants(current, patterns)

        # Should prioritize faster models
        assert len(variants) > 0
        first_variant_speed = variants[0].extra_metadata["expected_speed"]
        assert first_variant_speed in ["very_fast", "fast"]

    def test_generate_variants_without_patterns_is_balanced(self, strategy):
        """Test generates balanced variants when no patterns provided."""
        current = AgentConfig(agent_name="test_agent", inference={"model": "phi3:mini"})
        variants = strategy.generate_variants(current, [])

        # Should generate diverse mix of models
        assert len(variants) > 0

        # Should have variety of sizes/qualities
        qualities = {v.extra_metadata["expected_quality"] for v in variants}
        assert len(qualities) > 1  # At least 2 different quality levels

    def test_variants_preserve_other_config(self, strategy):
        """Test variants preserve non-model configuration."""
        current = AgentConfig(
            agent_name="test_agent",
            inference={
                "model": "phi3:mini",
                "temperature": 0.7,
                "max_tokens": 1000,
            },
            prompt={"template": "Extract product info"},
            caching={"enabled": True, "ttl": 3600},
        )

        variants = strategy.generate_variants(current, [])

        for variant in variants:
            # Model should change
            assert variant.inference["model"] != current.inference["model"]

            # Other settings should be preserved
            assert variant.inference["temperature"] == 0.7
            assert variant.inference["max_tokens"] == 1000
            assert variant.prompt["template"] == "Extract product info"
            assert variant.caching["enabled"] is True
            assert variant.caching["ttl"] == 3600

    def test_estimate_impact_for_quality_low(self, strategy):
        """Test impact estimation for quality problems."""
        problem = {"type": "quality_low", "current_quality": 0.5}
        impact = strategy.estimate_impact(problem)

        assert impact == 0.4  # 40% improvement expected

    def test_estimate_impact_for_cost_high(self, strategy):
        """Test impact estimation for cost problems."""
        problem = {"type": "cost_high", "current_cost_usd": 1.0}
        impact = strategy.estimate_impact(problem)

        assert impact == 0.3  # 30% cost reduction expected

    def test_estimate_impact_for_speed_low(self, strategy):
        """Test impact estimation for latency problems."""
        problem = {"type": "speed_low", "avg_latency_ms": 2000}
        impact = strategy.estimate_impact(problem)

        assert impact == 0.3  # 30% speed improvement expected

    def test_estimate_impact_for_unknown_problem(self, strategy):
        """Test impact estimation for unknown problems."""
        problem = {"type": "unknown"}
        impact = strategy.estimate_impact(problem)

        assert impact == 0.1  # Default 10%

    def test_default_model_when_not_specified(self, strategy):
        """Test uses default model when current config has no model."""
        current = AgentConfig(agent_name="test_agent", inference={})  # No model specified
        variants = strategy.generate_variants(current, [])

        # Should still generate variants (excluding default phi3:mini)
        assert len(variants) > 0
        models = [v.inference["model"] for v in variants]
        assert "phi3:mini" not in models  # Shouldn't include default

    def test_quality_score_ordering(self, strategy):
        """Test quality scoring function."""
        from src.self_improvement.model_registry import ModelMetadata

        highest = ModelMetadata(
            name="test1", provider="ollama", size="32B",
            expected_quality="highest", expected_speed="slow"
        )
        high = ModelMetadata(
            name="test2", provider="ollama", size="8B",
            expected_quality="high", expected_speed="fast"
        )
        medium = ModelMetadata(
            name="test3", provider="ollama", size="3B",
            expected_quality="medium", expected_speed="very_fast"
        )

        assert strategy._quality_score(highest) > strategy._quality_score(high)
        assert strategy._quality_score(high) > strategy._quality_score(medium)

    def test_speed_score_ordering(self, strategy):
        """Test speed scoring function."""
        from src.self_improvement.model_registry import ModelMetadata

        very_fast = ModelMetadata(
            name="test1", provider="ollama", size="3B",
            expected_quality="medium", expected_speed="very_fast"
        )
        fast = ModelMetadata(
            name="test2", provider="ollama", size="8B",
            expected_quality="high", expected_speed="fast"
        )
        slow = ModelMetadata(
            name="test3", provider="ollama", size="32B",
            expected_quality="highest", expected_speed="slow"
        )

        assert strategy._speed_score(very_fast) > strategy._speed_score(fast)
        assert strategy._speed_score(fast) > strategy._speed_score(slow)

    def test_infer_problem_type_from_quality_pattern(self, strategy):
        """Test problem type inference from quality patterns."""
        patterns = [
            LearnedPattern(
                pattern_type="low_quality_output",
                description="Quality issues",
                support=5,
                confidence=0.8,
                evidence={}
            )
        ]

        problem_type = strategy._infer_problem_type(patterns)
        assert problem_type == "quality_low"

    def test_infer_problem_type_from_cost_pattern(self, strategy):
        """Test problem type inference from cost patterns."""
        patterns = [
            LearnedPattern(
                pattern_type="high_cost_per_request",
                description="Cost too high",
                support=10,
                confidence=0.9,
                evidence={}
            )
        ]

        problem_type = strategy._infer_problem_type(patterns)
        assert problem_type == "cost_high"

    def test_infer_problem_type_from_latency_pattern(self, strategy):
        """Test problem type inference from latency patterns."""
        patterns = [
            LearnedPattern(
                pattern_type="slow_execution",
                description="High latency",
                support=8,
                confidence=0.85,
                evidence={}
            )
        ]

        problem_type = strategy._infer_problem_type(patterns)
        assert problem_type == "speed_low"

    def test_infer_problem_type_defaults_to_balanced(self, strategy):
        """Test problem type defaults to balanced when no patterns."""
        problem_type = strategy._infer_problem_type([])
        assert problem_type == "balanced"

    def test_select_candidate_models_for_quality(self, strategy, registry):
        """Test candidate selection prioritizes quality."""
        candidates = strategy._select_candidate_models("phi3:mini", "quality_low")

        # Should be sorted by quality (highest first)
        assert len(candidates) > 0
        # qwen2.5:32b should be first (highest quality)
        assert candidates[0].expected_quality in ["highest", "high"]

    def test_select_candidate_models_for_speed(self, strategy, registry):
        """Test candidate selection prioritizes speed."""
        candidates = strategy._select_candidate_models("qwen2.5:32b", "speed_low")

        # Should be sorted by speed (fastest first)
        assert len(candidates) > 0
        assert candidates[0].expected_speed in ["very_fast", "fast"]

    def test_integration_with_model_registry(self, strategy, registry):
        """Test strategy correctly uses model registry."""
        # Verify strategy can access all registry models
        all_models = registry.get_all()
        assert len(all_models) == 4  # Default: phi3:mini, llama3.1:8b, mistral:7b, qwen2.5:32b

        # Generate variants should work with registry
        current = AgentConfig(agent_name="test_agent", inference={"model": "phi3:mini"})
        variants = strategy.generate_variants(current, [])

        # Should use models from registry
        variant_models = {v.inference["model"] for v in variants}
        registry_models = {m.name for m in all_models}

        # All variant models should exist in registry
        assert variant_models.issubset(registry_models)
