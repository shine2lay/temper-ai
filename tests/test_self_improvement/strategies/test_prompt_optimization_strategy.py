"""Tests for prompt optimization strategy."""
from unittest.mock import Mock

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

    def test_generate_variants_all_already_present(self):
        """Test variant generation when all enhancements already present."""
        strategy = PromptOptimizationStrategy()

        # Config with all enhancements
        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={
                "system": "You are a helpful assistant\n" + strategy.SPECIFICITY_GUIDE,
                "inline": strategy.COT_GUIDE + "\n" + strategy.FORMAT_GUIDE
            }
        )

        variants = strategy.generate_variants(current_config, [])

        # No variants should be generated
        assert len(variants) == 0

    def test_generate_variants_partial_duplicates(self):
        """Test variant generation with some enhancements present."""
        strategy = PromptOptimizationStrategy()

        # Only CoT present
        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={
                "system": "You are a helpful assistant",
                "inline": strategy.COT_GUIDE
            }
        )

        variants = strategy.generate_variants(current_config, [])

        # Should generate specificity and format variants
        variant_types = [v.extra_metadata.get("variant_type") for v in variants]
        assert "chain_of_thought" not in variant_types
        assert "specificity" in variant_types
        assert "output_format" in variant_types

    def test_estimate_impact_with_empty_problem_dict(self):
        """Test impact estimation with empty problem dict."""
        strategy = PromptOptimizationStrategy()

        impact = strategy.estimate_impact({})

        assert impact == 0.15  # Default impact

    def test_estimate_impact_case_sensitivity(self):
        """Test that problem type matching is case-sensitive."""
        strategy = PromptOptimizationStrategy()

        # Lowercase (should match)
        impact_lower = strategy.estimate_impact({"problem_type": "quality_low"})
        assert impact_lower == 0.40

        # Uppercase (should not match, return default)
        impact_upper = strategy.estimate_impact({"problem_type": "QUALITY_LOW"})
        assert impact_upper == 0.15  # Default

    def test_is_applicable_all_problem_types(self):
        """Test applicability for all applicable problem types."""
        strategy = PromptOptimizationStrategy()

        applicable_types = [
            "quality_low",
            "error_rate_high",
            "inconsistent_output",
            "hallucination",
            "incorrect_output"
        ]

        for problem_type in applicable_types:
            assert strategy.is_applicable(problem_type) is True

    def test_is_applicable_edge_cases(self):
        """Test applicability edge cases."""
        strategy = PromptOptimizationStrategy()

        # Empty string
        assert strategy.is_applicable("") is False

        # None (will raise)
        # Can't test None directly as it would raise TypeError

        # Similar but not exact match
        assert strategy.is_applicable("quality_low_performance") is False
        assert strategy.is_applicable("high_error_rate") is False

    def test_generate_variants_metadata_complete(self):
        """Test that all variants have complete metadata."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        for variant in variants:
            assert "strategy" in variant.extra_metadata
            assert variant.extra_metadata["strategy"] == "prompt_optimization"
            assert "variant_type" in variant.extra_metadata
            assert "change" in variant.extra_metadata
            assert isinstance(variant.extra_metadata["change"], str)
            assert len(variant.extra_metadata["change"]) > 0

    def test_generate_variants_empty_prompt(self):
        """Test variant generation with empty prompt strings."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        # Should generate all 3 base variants
        assert len(variants) >= 3

        # Variants should add content to empty strings
        for variant in variants:
            if variant.extra_metadata["variant_type"] == "chain_of_thought":
                assert strategy.COT_GUIDE in variant.prompt["inline"]
            elif variant.extra_metadata["variant_type"] == "specificity":
                assert strategy.SPECIFICITY_GUIDE in variant.prompt["system"]
            elif variant.extra_metadata["variant_type"] == "output_format":
                assert strategy.FORMAT_GUIDE in variant.prompt["inline"]

    def test_generate_variants_max_limit(self):
        """Test that variant count never exceeds limit."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        # Max 4 variants (SMALL_ITEM_LIMIT - 1 = 5 - 1 = 4)
        assert len(variants) <= 4

    def test_generate_variants_combined_not_generated_if_insufficient(self):
        """Test combined variant not generated if fewer than 2 other variants."""
        strategy = PromptOptimizationStrategy()

        # Only format variant missing (1 variant would be generated)
        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={
                "system": "You are a helpful assistant\n" + strategy.SPECIFICITY_GUIDE,
                "inline": strategy.COT_GUIDE
            }
        )

        variants = strategy.generate_variants(current_config, [])

        # Should only generate format variant (< 2)
        assert len(variants) == 1
        assert variants[0].extra_metadata["variant_type"] == "output_format"

        # No combined variant
        combined_variants = [
            v for v in variants if v.extra_metadata.get("variant_type") == "combined"
        ]
        assert len(combined_variants) == 0

    def test_variants_independent_modifications(self):
        """Test that variants are independent (modifying one doesn't affect others)."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        variants = strategy.generate_variants(current_config, [])

        # Modify first variant
        variants[0].prompt["system"] = "MODIFIED"

        # Other variants should be unchanged
        for i, variant in enumerate(variants[1:], 1):
            assert variant.prompt["system"] != "MODIFIED"

    def test_estimate_impact_all_problem_types_have_values(self):
        """Test that all applicable problem types have defined impact values."""
        strategy = PromptOptimizationStrategy()

        applicable_types = [
            "quality_low",
            "error_rate_high",
            "inconsistent_output",
            "hallucination",
            "incorrect_output"
        ]

        for problem_type in applicable_types:
            impact = strategy.estimate_impact({"problem_type": problem_type})
            assert impact > 0.0
            assert impact <= 1.0
            assert impact != 0.15  # Not default

    def test_generate_variants_with_none_prompt_values(self):
        """Test variant generation raises TypeError when prompt values are None."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": None, "inline": None}
        )

        # None prompt values cause TypeError on 'in' check
        with pytest.raises(TypeError):
            strategy.generate_variants(current_config, [])

    def test_name_property_immutable(self):
        """Test that strategy name is consistent."""
        strategy1 = PromptOptimizationStrategy()
        strategy2 = PromptOptimizationStrategy()

        assert strategy1.name == "prompt_optimization"
        assert strategy2.name == "prompt_optimization"
        assert strategy1.name == strategy2.name

    def test_guide_constants_are_strings(self):
        """Test that guide constants are non-empty strings."""
        strategy = PromptOptimizationStrategy()

        assert isinstance(strategy.COT_GUIDE, str)
        assert isinstance(strategy.SPECIFICITY_GUIDE, str)
        assert isinstance(strategy.FORMAT_GUIDE, str)

        assert len(strategy.COT_GUIDE) > 0
        assert len(strategy.SPECIFICITY_GUIDE) > 0
        assert len(strategy.FORMAT_GUIDE) > 0

    def test_generate_variants_patterns_parameter_unused(self):
        """Test that patterns parameter doesn't affect output (currently unused)."""
        strategy = PromptOptimizationStrategy()

        current_config = SIOptimizationConfig(
            agent_name="test_agent",
            prompt={"system": "You are a helpful assistant", "inline": ""}
        )

        # Generate with empty patterns
        variants1 = strategy.generate_variants(current_config, [])

        # Generate with mock patterns
        mock_patterns = [Mock(), Mock(), Mock()]
        variants2 = strategy.generate_variants(current_config, mock_patterns)

        # Should generate same variants
        assert len(variants1) == len(variants2)

    def test_estimate_impact_with_learning_store(self):
        """Test impact estimation delegates to parent when learning_store is set."""
        mock_store = Mock()
        mock_store.get_average_improvement.return_value = 0.5
        mock_store.get_sample_count.return_value = 10
        strategy = PromptOptimizationStrategy(learning_store=mock_store)

        impact = strategy.estimate_impact({"problem_type": "quality_low"})

        # With learning_store, delegates to super().estimate_impact()
        # which does Bayesian updating with prior_weight=10, data_weight=10
        # weighted = (0.1 * 10 + 0.5 * 10) / (10 + 10) = 6.0 / 20 = 0.3
        assert isinstance(impact, float)
        assert 0.0 < impact <= 1.0
        mock_store.get_average_improvement.assert_called_once()
        mock_store.get_sample_count.assert_called_once()
