"""Tests for ERC721WorkflowStrategy."""

import copy

import pytest

from src.self_improvement.strategies import (
    SIOptimizationConfig,
    LearnedPattern,
    ERC721WorkflowStrategy,
)


class TestERC721WorkflowStrategy:
    """Test suite for ERC721WorkflowStrategy."""

    @pytest.fixture
    def strategy(self):
        """Create strategy instance."""
        return ERC721WorkflowStrategy()

    @pytest.fixture
    def base_config(self):
        """Create base config for testing."""
        return SIOptimizationConfig(
            agent_name="erc721_agent",
            inference={
                "model": "llama3:8b",
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            prompt={
                "template": "Generate Solidity code",
                "inline": "",
            },
        )

    def test_strategy_name(self, strategy):
        """Test strategy has correct name."""
        assert strategy.name == "erc721_workflow"

    def test_is_applicable_to_quality_low(self, strategy):
        """Test strategy applies to low quality problems."""
        assert strategy.is_applicable("quality_low") is True

    def test_is_applicable_to_error_rate_high(self, strategy):
        """Test strategy applies to high error rate problems."""
        assert strategy.is_applicable("error_rate_high") is True

    def test_is_applicable_to_inconsistent_output(self, strategy):
        """Test strategy applies to inconsistent output problems."""
        assert strategy.is_applicable("inconsistent_output") is True

    def test_not_applicable_to_unknown_problem(self, strategy):
        """Test strategy doesn't apply to unrelated problems."""
        assert strategy.is_applicable("cost_high") is False
        assert strategy.is_applicable("speed_low") is False
        assert strategy.is_applicable("network_issues") is False

    def test_generate_variants_returns_list(self, strategy, base_config):
        """Test generate_variants returns a list."""
        variants = strategy.generate_variants(base_config, [])

        assert isinstance(variants, list)
        assert len(variants) > 0

    def test_generate_variants_creates_3_variants(self, strategy, base_config):
        """Test generates exactly 3 variants."""
        variants = strategy.generate_variants(base_config, [])

        assert len(variants) == 3

    def test_variant_1_lower_temperature(self, strategy, base_config):
        """Test first variant lowers temperature for determinism."""
        variants = strategy.generate_variants(base_config, [])

        variant_temp = variants[0]
        original_temp = base_config.inference["temperature"]
        new_temp = variant_temp.inference["temperature"]

        # Temperature should be reduced by 50%
        assert new_temp < original_temp
        assert new_temp == round(original_temp * 0.5, 2)
        assert variant_temp.extra_metadata["strategy"] == "erc721_workflow"
        assert variant_temp.extra_metadata["variant_type"] == "lower_temperature"

    def test_variant_1_minimum_temperature(self, strategy):
        """Test temperature reduction respects minimum threshold."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"model": "llama3:8b", "temperature": 0.08},
        )
        variants = strategy.generate_variants(config, [])

        # Should use minimum of 0.05 (PROB_MINIMAL)
        assert variants[0].inference["temperature"] == 0.05

    def test_variant_2_code_specialized_model(self, strategy, base_config):
        """Test second variant uses code-specialized model."""
        variants = strategy.generate_variants(base_config, [])

        variant_model = variants[1]
        original_model = base_config.inference["model"]
        new_model = variant_model.inference["model"]

        # Should switch to a code model
        assert new_model != original_model
        assert new_model in strategy.CODE_MODELS
        assert variant_model.extra_metadata["strategy"] == "erc721_workflow"
        assert variant_model.extra_metadata["variant_type"] == "code_model"

    def test_variant_2_picks_different_code_model(self, strategy):
        """Test variant 2 excludes current model when picking code model."""
        # Start with a code model
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"model": "codellama:13b"},
        )
        variants = strategy.generate_variants(config, [])

        # Second variant should pick a different code model
        new_model = variants[1].inference["model"]
        assert new_model != "codellama:13b"
        assert new_model in strategy.CODE_MODELS

    def test_variant_3_enhanced_prompt(self, strategy, base_config):
        """Test third variant enhances prompt with Solidity example."""
        variants = strategy.generate_variants(base_config, [])

        variant_prompt = variants[2]
        original_inline = base_config.prompt.get("inline", "")
        new_inline = variant_prompt.prompt["inline"]

        # Should add Solidity example
        assert len(new_inline) > len(original_inline)
        assert "REFERENCE EXAMPLE" in new_inline
        assert strategy.SOLIDITY_EXAMPLE in new_inline
        assert "ERC721" in new_inline
        assert "OpenZeppelin" in new_inline
        assert variant_prompt.extra_metadata["strategy"] == "erc721_workflow"
        assert variant_prompt.extra_metadata["variant_type"] == "enhanced_prompt"

    def test_variant_3_doesnt_duplicate_example(self, strategy):
        """Test variant 3 doesn't add example if already present."""
        config = SIOptimizationConfig(
            agent_name="test",
            prompt={"inline": strategy.SOLIDITY_EXAMPLE},
        )
        variants = strategy.generate_variants(config, [])

        # Should not duplicate the example
        variant_inline = variants[2].prompt["inline"]
        # Count occurrences of a unique string from the example
        count = variant_inline.count("contract MyNFT is ERC721")
        assert count == 1  # Should appear only once

    def test_variants_preserve_other_config(self, strategy):
        """Test variants preserve non-targeted configuration."""
        config = SIOptimizationConfig(
            agent_name="test_agent",
            agent_version="2.0.0",
            inference={
                "model": "llama3:8b",
                "temperature": 0.7,
                "max_tokens": 1000,
                "top_p": 0.9,
            },
            prompt={
                "template": "Extract info",
                "inline": "",
            },
            caching={"enabled": True, "ttl": 3600},
            retry={"max_retries": 3},
        )

        variants = strategy.generate_variants(config, [])

        for i, variant in enumerate(variants):
            # Agent metadata preserved
            assert variant.agent_name == "test_agent"
            assert variant.agent_version == "2.0.0"

            # Unchanged inference params preserved
            if i == 0:
                # Variant 1 changes temperature
                assert variant.inference["temperature"] != config.inference["temperature"]
            elif i == 1:
                # Variant 2 changes model
                assert variant.inference["model"] != config.inference["model"]

            # Other params always preserved
            assert variant.inference.get("max_tokens") == 1000
            assert variant.inference.get("top_p") == 0.9
            assert variant.prompt["template"] == "Extract info"
            assert variant.caching["enabled"] is True
            assert variant.caching["ttl"] == 3600
            assert variant.retry["max_retries"] == 3

    def test_variants_are_independent_copies(self, strategy, base_config):
        """Test variants are deep copies, not shallow references."""
        variants = strategy.generate_variants(base_config, [])

        # Modify first variant
        variants[0].inference["temperature"] = 0.99

        # Other variants should be unaffected
        assert variants[1].inference["temperature"] != 0.99
        assert variants[2].inference["temperature"] != 0.99

        # Original config should be unaffected
        assert base_config.inference["temperature"] == 0.7

    def test_estimate_impact_for_quality_low(self, strategy):
        """Test impact estimation for quality problems."""
        problem = {"type": "quality_low", "current_quality": 0.5}
        impact = strategy.estimate_impact(problem)

        assert impact == 0.35  # 35% improvement expected

    def test_estimate_impact_for_error_rate_high(self, strategy):
        """Test impact estimation for error rate problems."""
        problem = {"type": "error_rate_high", "error_rate": 0.3}
        impact = strategy.estimate_impact(problem)

        assert impact == 0.30  # 30% reduction expected

    def test_estimate_impact_for_inconsistent_output(self, strategy):
        """Test impact estimation for inconsistency problems."""
        problem = {"type": "inconsistent_output", "variance": 0.8}
        impact = strategy.estimate_impact(problem)

        assert impact == 0.25  # 25% improvement expected

    def test_estimate_impact_for_unknown_problem(self, strategy):
        """Test impact estimation for unknown problems."""
        problem = {"type": "unknown"}
        impact = strategy.estimate_impact(problem)

        assert impact == 0.1  # Default 10%

    def test_estimate_impact_with_problem_type_field(self, strategy):
        """Test impact works with problem_type field instead of type."""
        problem = {"problem_type": "quality_low"}
        impact = strategy.estimate_impact(problem)

        assert impact == 0.35

    def test_code_models_list_contains_expected_models(self, strategy):
        """Test CODE_MODELS contains expected code-specialized models."""
        assert "codellama:13b" in strategy.CODE_MODELS
        assert "codellama:7b" in strategy.CODE_MODELS
        assert "deepseek-coder:6.7b" in strategy.CODE_MODELS
        assert "qwen2.5-coder:7b" in strategy.CODE_MODELS
        assert len(strategy.CODE_MODELS) == 4

    def test_solidity_example_contains_key_elements(self, strategy):
        """Test SOLIDITY_EXAMPLE contains key Solidity patterns."""
        example = strategy.SOLIDITY_EXAMPLE

        # Key OpenZeppelin v5 patterns
        assert "pragma solidity ^0.8.20" in example
        assert "import" in example
        assert "@openzeppelin/contracts" in example
        assert "ERC721" in example
        assert "Ownable" in example
        assert "constructor()" in example
        assert "Ownable(msg.sender)" in example
        assert "function mint(" in example
        assert "onlyOwner" in example

    def test_generate_variants_with_quality_low_pattern(self, strategy, base_config):
        """Test generates appropriate variants for quality problems."""
        patterns = [
            LearnedPattern(
                pattern_type="quality_low",
                description="Code generation produces invalid Solidity",
                support=10,
                confidence=0.9,
                evidence={"avg_quality": 0.4},
            )
        ]

        variants = strategy.generate_variants(base_config, patterns)

        # All 3 variants should be generated regardless of patterns
        assert len(variants) == 3

        # Verify variant characteristics
        assert variants[0].inference["temperature"] < base_config.inference["temperature"]
        assert variants[1].inference["model"] in strategy.CODE_MODELS
        assert strategy.SOLIDITY_EXAMPLE in variants[2].prompt["inline"]

    def test_generate_variants_with_error_rate_high_pattern(self, strategy, base_config):
        """Test generates appropriate variants for high error rate."""
        patterns = [
            LearnedPattern(
                pattern_type="error_rate_high",
                description="Many compilation failures",
                support=15,
                confidence=0.85,
                evidence={"error_rate": 0.45},
            )
        ]

        variants = strategy.generate_variants(base_config, patterns)

        assert len(variants) == 3
        # Lower temperature should help reduce errors
        assert variants[0].inference["temperature"] < 0.7

    def test_generate_variants_with_inconsistent_output_pattern(self, strategy, base_config):
        """Test generates appropriate variants for inconsistent output."""
        patterns = [
            LearnedPattern(
                pattern_type="inconsistent_output",
                description="Output varies significantly across runs",
                support=8,
                confidence=0.8,
                evidence={"output_variance": 0.6},
            )
        ]

        variants = strategy.generate_variants(base_config, patterns)

        assert len(variants) == 3
        # Lower temperature is key for consistency
        assert variants[0].inference["temperature"] < base_config.inference["temperature"]

    def test_generate_variants_with_multiple_patterns(self, strategy, base_config):
        """Test handles multiple learned patterns."""
        patterns = [
            LearnedPattern("quality_low", "Poor quality", 10, 0.9, {}),
            LearnedPattern("error_rate_high", "High errors", 8, 0.85, {}),
        ]

        variants = strategy.generate_variants(base_config, patterns)

        # Should still generate all 3 variants
        assert len(variants) == 3

    def test_generate_variants_with_empty_patterns(self, strategy, base_config):
        """Test works with empty pattern list (MVP scenario)."""
        variants = strategy.generate_variants(base_config, [])

        # Should generate all 3 variants even without patterns
        assert len(variants) == 3

    def test_default_temperature_constant(self, strategy):
        """Test DEFAULT_CODE_TEMPERATURE is properly set."""
        from src.self_improvement.strategies.erc721_strategy import DEFAULT_CODE_TEMPERATURE

        assert DEFAULT_CODE_TEMPERATURE == 0.7

    def test_impact_constants(self, strategy):
        """Test impact estimation constants are properly set."""
        from src.self_improvement.strategies.erc721_strategy import (
            IMPACT_QUALITY_LOW,
            IMPACT_ERROR_RATE_HIGH,
            IMPACT_INCONSISTENT_OUTPUT,
            IMPACT_DEFAULT,
        )

        assert IMPACT_QUALITY_LOW == 0.35
        assert IMPACT_ERROR_RATE_HIGH == 0.30
        assert IMPACT_INCONSISTENT_OUTPUT == 0.25
        assert IMPACT_DEFAULT == 0.1

    def test_metadata_change_descriptions(self, strategy, base_config):
        """Test variants include descriptive change metadata."""
        variants = strategy.generate_variants(base_config, [])

        # Variant 1: temperature change
        assert "change" in variants[0].extra_metadata
        assert "temperature" in variants[0].extra_metadata["change"]
        assert "0.7" in variants[0].extra_metadata["change"]

        # Variant 2: model change
        assert "change" in variants[1].extra_metadata
        assert "model" in variants[1].extra_metadata["change"]

        # Variant 3: prompt enhancement
        assert "change" in variants[2].extra_metadata
        assert "Solidity" in variants[2].extra_metadata["change"]

    def test_temperature_reduction_rounds_to_2_decimals(self, strategy):
        """Test temperature is rounded to 2 decimal places."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.77},
        )
        variants = strategy.generate_variants(config, [])

        # 0.77 * 0.5 = 0.385, rounded to 0.39 or similar
        new_temp = variants[0].inference["temperature"]
        assert isinstance(new_temp, float)
        # Check it has at most 2 decimal places
        assert new_temp == round(new_temp, 2)

    def test_uses_default_temperature_when_not_specified(self, strategy):
        """Test uses DEFAULT_CODE_TEMPERATURE when temperature not in config."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"model": "llama3:8b"},  # No temperature
        )
        variants = strategy.generate_variants(config, [])

        # Should use default 0.7, reduced by 50% to 0.35
        assert variants[0].inference["temperature"] == 0.35

    def test_learning_store_integration(self, strategy):
        """Test strategy initializes without learning_store."""
        # Default initialization has no learning_store
        assert strategy.learning_store is None

        # estimate_impact should use fallback estimates
        problem = {"type": "quality_low"}
        impact = strategy.estimate_impact(problem)
        assert impact == 0.35  # Fallback value

    def test_variant_types_are_unique(self, strategy, base_config):
        """Test each variant has a unique variant_type."""
        variants = strategy.generate_variants(base_config, [])

        variant_types = [v.extra_metadata["variant_type"] for v in variants]
        assert len(variant_types) == len(set(variant_types))
        assert "lower_temperature" in variant_types
        assert "code_model" in variant_types
        assert "enhanced_prompt" in variant_types

    def test_code_model_variant_skipped_if_no_alternatives(self, strategy):
        """Test handles case where all code models match current model."""
        # Edge case: If we somehow had only one code model
        # The implementation should still work (pick from CODE_MODELS list)
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"model": "codellama:13b"},
        )
        variants = strategy.generate_variants(config, [])

        # Should still generate 3 variants
        assert len(variants) == 3

        # Second variant should use a different code model
        assert variants[1].inference["model"] != "codellama:13b"
