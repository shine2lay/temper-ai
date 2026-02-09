"""Tests for prompt optimization strategy."""
import pytest
from src.self_improvement.strategies.prompt_optimization_strategy import PromptOptimizationStrategy
from src.self_improvement.strategies.strategy import SIOptimizationConfig


class TestPromptOptimizationStrategy:
    """Test PromptOptimizationStrategy functionality."""

    def test_name(self):
        """Test strategy name."""
        strategy = PromptOptimizationStrategy()

        assert strategy.name == "prompt_optimization"

    def test_is_applicable_quality_low(self):
        """Test applicability for quality_low problem."""
        strategy = PromptOptimizationStrategy()

        assert strategy.is_applicable("quality_low") is True

    def test_is_applicable_error_rate_high(self):
        """Test applicability for error_rate_high problem."""
        strategy = PromptOptimizationStrategy()

        assert strategy.is_applicable("error_rate_high") is True

    def test_is_applicable_inconsistent_output(self):
        """Test applicability for inconsistent_output problem."""
        strategy = PromptOptimizationStrategy()

        assert strategy.is_applicable("inconsistent_output") is True

    def test_is_applicable_hallucination(self):
        """Test applicability for hallucination problem."""
        strategy = PromptOptimizationStrategy()

        assert strategy.is_applicable("hallucination") is True

    def test_is_applicable_incorrect_output(self):
        """Test applicability for incorrect_output problem."""
        strategy = PromptOptimizationStrategy()

        assert strategy.is_applicable("incorrect_output") is True

    def test_is_applicable_not_applicable(self):
        """Test non-applicable problem types."""
        strategy = PromptOptimizationStrategy()

        assert strategy.is_applicable("cost_high") is False
        assert strategy.is_applicable("speed_low") is False
        assert strategy.is_applicable("unknown_problem") is False

    def test_generate_variants_all_new(self):
        """Test generating variants when all are new."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        # Should generate at least 3 variants (CoT, specificity, format)
        assert len(variants) >= 3
        assert len(variants) <= 4  # Max 4 variants

        # Check variant types
        variant_types = [v.extra_metadata.get("variant_type") for v in variants]
        assert "chain_of_thought" in variant_types
        assert "specificity" in variant_types
        assert "output_format" in variant_types

    def test_generate_variants_cot(self):
        """Test chain-of-thought variant generation."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        # Find CoT variant
        cot_variant = next(
            v for v in variants if v.extra_metadata.get("variant_type") == "chain_of_thought"
        )

        assert strategy.COT_GUIDE in cot_variant.prompt["inline"]
        assert cot_variant.extra_metadata["strategy"] == "prompt_optimization"
        assert "chain-of-thought" in cot_variant.extra_metadata["change"]

    def test_generate_variants_specificity(self):
        """Test specificity variant generation."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        # Find specificity variant
        spec_variant = next(
            v for v in variants if v.extra_metadata.get("variant_type") == "specificity"
        )

        assert strategy.SPECIFICITY_GUIDE in spec_variant.prompt["system"]
        assert "specificity guide" in spec_variant.extra_metadata["change"]

    def test_generate_variants_format(self):
        """Test format variant generation."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        # Find format variant
        format_variant = next(
            v for v in variants if v.extra_metadata.get("variant_type") == "output_format"
        )

        assert strategy.FORMAT_GUIDE in format_variant.prompt["inline"]
        assert "output format" in format_variant.extra_metadata["change"]

    def test_generate_variants_combined(self):
        """Test combined variant generation."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        # Combined variant should exist if at least 2 other variants generated
        if len(variants) >= 3:
            combined_variants = [
                v for v in variants if v.extra_metadata.get("variant_type") == "combined"
            ]

            if combined_variants:
                combined = combined_variants[0]
                assert strategy.SPECIFICITY_GUIDE in combined.prompt["system"]
                assert strategy.FORMAT_GUIDE in combined.prompt["inline"]

    def test_generate_variants_no_duplicates_cot(self):
        """Test that CoT variant not generated if already present."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={
                "system": "You are a helpful assistant",
                "inline": strategy.COT_GUIDE
            }
        )

        variants = strategy.generate_variants(current_config, [])

        # CoT variant should not be generated
        cot_variants = [
            v for v in variants if v.extra_metadata.get("variant_type") == "chain_of_thought"
        ]
        assert len(cot_variants) == 0

    def test_generate_variants_no_duplicates_specificity(self):
        """Test that specificity variant not generated if already present."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={
                "system": "You are a helpful assistant\n" + strategy.SPECIFICITY_GUIDE,
                "inline": ""
            }
        )

        variants = strategy.generate_variants(current_config, [])

        # Specificity variant should not be generated
        spec_variants = [
            v for v in variants if v.extra_metadata.get("variant_type") == "specificity"
        ]
        assert len(spec_variants) == 0

    def test_generate_variants_no_duplicates_format(self):
        """Test that format variant not generated if already present."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={
                "system": "You are a helpful assistant",
                "inline": strategy.FORMAT_GUIDE
            }
        )

        variants = strategy.generate_variants(current_config, [])

        # Format variant should not be generated
        format_variants = [
            v for v in variants if v.extra_metadata.get("variant_type") == "output_format"
        ]
        assert len(format_variants) == 0

    def test_generate_variants_limit(self):
        """Test that variant count is limited."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        # Max 4 variants
        assert len(variants) <= 4

    def test_estimate_impact_no_learning_store(self):
        """Test impact estimation without learning store."""
        strategy = PromptOptimizationStrategy()

        # Test different problem types
        impact_quality = strategy.estimate_impact({"problem_type": "quality_low"})
        assert impact_quality == 0.40

        impact_error = strategy.estimate_impact({"problem_type": "error_rate_high"})
        assert impact_error == 0.30

        impact_inconsistent = strategy.estimate_impact({"problem_type": "inconsistent_output"})
        assert impact_inconsistent == 0.35

        impact_hallucination = strategy.estimate_impact({"problem_type": "hallucination"})
        assert impact_hallucination == 0.45

        impact_incorrect = strategy.estimate_impact({"problem_type": "incorrect_output"})
        assert impact_incorrect == 0.35

    def test_estimate_impact_unknown_problem(self):
        """Test impact estimation for unknown problem type."""
        strategy = PromptOptimizationStrategy()

        impact = strategy.estimate_impact({"problem_type": "unknown_problem"})
        assert impact == 0.15  # Default impact

    def test_estimate_impact_type_key(self):
        """Test impact estimation with 'type' key instead of 'problem_type'."""
        strategy = PromptOptimizationStrategy()

        impact = strategy.estimate_impact({"type": "quality_low"})
        assert impact == 0.40

    def test_variants_preserve_config(self):
        """Test that variants don't modify original config."""
        strategy = PromptOptimizationStrategy()

        original_system = "You are a helpful assistant"
        original_inline = "Some instructions"
        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": original_system, "inline": original_inline}
        )

        strategy.generate_variants(current_config, [])

        # Original should be unchanged
        assert current_config.prompt["system"] == original_system
        assert current_config.prompt["inline"] == original_inline
