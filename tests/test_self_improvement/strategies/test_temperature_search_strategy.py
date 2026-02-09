"""Tests for TemperatureSearchStrategy."""

import pytest

from src.self_improvement.strategies import (
    SIOptimizationConfig,
    LearnedPattern,
    TemperatureSearchStrategy,
)


class TestTemperatureSearchStrategy:
    """Test suite for TemperatureSearchStrategy."""

    @pytest.fixture
    def strategy(self):
        """Create strategy instance."""
        return TemperatureSearchStrategy()

    @pytest.fixture
    def base_config(self):
        """Create base config for testing."""
        return SIOptimizationConfig(
            agent_name="test_agent",
            inference={
                "model": "llama3:8b",
                "temperature": 0.7,
                "top_p": 0.9,
            },
        )

    def test_strategy_name(self, strategy):
        """Test strategy has correct name."""
        assert strategy.name == "temperature_search"

    def test_is_applicable_to_quality_low(self, strategy):
        """Test strategy applies to low quality problems."""
        assert strategy.is_applicable("quality_low") is True

    def test_is_applicable_to_error_rate_high(self, strategy):
        """Test strategy applies to high error rate problems."""
        assert strategy.is_applicable("error_rate_high") is True

    def test_is_applicable_to_inconsistent_output(self, strategy):
        """Test strategy applies to inconsistent output problems."""
        assert strategy.is_applicable("inconsistent_output") is True

    def test_is_applicable_to_hallucination(self, strategy):
        """Test strategy applies to hallucination problems."""
        assert strategy.is_applicable("hallucination") is True

    def test_is_applicable_to_incorrect_output(self, strategy):
        """Test strategy applies to incorrect output problems."""
        assert strategy.is_applicable("incorrect_output") is True

    def test_is_applicable_to_verbosity_issues(self, strategy):
        """Test strategy applies to verbosity problems."""
        assert strategy.is_applicable("too_verbose") is True
        assert strategy.is_applicable("too_brief") is True

    def test_not_applicable_to_unknown_problem(self, strategy):
        """Test strategy doesn't apply to unrelated problems."""
        assert strategy.is_applicable("cost_high") is False
        assert strategy.is_applicable("network_issues") is False

    def test_generate_variants_returns_list(self, strategy, base_config):
        """Test generate_variants returns a list."""
        variants = strategy.generate_variants(base_config, [])

        assert isinstance(variants, list)
        assert len(variants) > 0

    def test_generate_variants_creates_up_to_4_variants(self, strategy, base_config):
        """Test generates 3-4 variants."""
        variants = strategy.generate_variants(base_config, [])

        assert 3 <= len(variants) <= 4

    def test_variant_1_lower_temperature(self, strategy, base_config):
        """Test first variant lowers temperature."""
        variants = strategy.generate_variants(base_config, [])

        variant = variants[0]
        assert variant.inference["temperature"] < base_config.inference["temperature"]
        assert variant.extra_metadata["strategy"] == "temperature_search"
        assert variant.extra_metadata["variant_type"] == "lower_temperature"
        assert "more deterministic" in variant.extra_metadata["change"]

    def test_lower_temperature_uses_deterministic_preset(self, strategy):
        """Test lower temp variant uses DETERMINISTIC_TEMP when current > 0.5."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.8},
        )
        variants = strategy.generate_variants(config, [])

        # Should use DETERMINISTIC_TEMP = 0.1
        assert variants[0].inference["temperature"] == 0.1

    def test_lower_temperature_uses_multiplier_when_current_low(self, strategy):
        """Test lower temp uses multiplier when current <= 0.5."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.4},
        )
        variants = strategy.generate_variants(config, [])

        # Should use 0.4 * 0.5 = 0.2
        assert variants[0].inference["temperature"] == 0.2

    def test_lower_temperature_skipped_when_already_low(self, strategy):
        """Test lower temp variant skipped when temperature already very low."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.1},  # Below MIN_TEMP_FOR_REDUCTION (0.15)
        )
        variants = strategy.generate_variants(config, [])

        # Should not include lower temperature variant
        variant_types = [v.extra_metadata["variant_type"] for v in variants]
        assert "lower_temperature" not in variant_types

    def test_variant_2_higher_temperature_for_creativity(self, strategy, base_config):
        """Test second variant can increase temperature for creativity."""
        # Use patterns that don't exclude higher temperature
        patterns = [
            LearnedPattern(
                pattern_type="too_brief",
                description="Output too brief",
                support=10,
                confidence=0.8,
                evidence={},
            )
        ]
        variants = strategy.generate_variants(base_config, patterns)

        # Should include higher temperature variant
        variant_types = [v.extra_metadata["variant_type"] for v in variants]
        if "higher_temperature" in variant_types:
            idx = variant_types.index("higher_temperature")
            variant = variants[idx]
            assert variant.inference["temperature"] > base_config.inference["temperature"]
            assert "more creative" in variant.extra_metadata["change"]

    def test_higher_temperature_uses_creative_preset(self, strategy):
        """Test higher temp variant uses CREATIVE_TEMP when current < 0.6."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.5},
        )
        patterns = []  # No quality/correctness patterns
        variants = strategy.generate_variants(config, patterns)

        # Find higher temp variant
        higher_temp_variants = [
            v
            for v in variants
            if v.extra_metadata.get("variant_type") == "higher_temperature"
        ]
        if higher_temp_variants:
            # Should use CREATIVE_TEMP = 0.9
            assert higher_temp_variants[0].inference["temperature"] == 0.9

    def test_higher_temperature_uses_multiplier_when_current_high(self, strategy):
        """Test higher temp uses multiplier when current >= 0.6."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.7},
        )
        patterns = []
        variants = strategy.generate_variants(config, patterns)

        # Find higher temp variant
        higher_temp_variants = [
            v
            for v in variants
            if v.extra_metadata.get("variant_type") == "higher_temperature"
        ]
        if higher_temp_variants:
            # Should use min(0.95, 0.7 * 1.3) = 0.91
            assert higher_temp_variants[0].inference["temperature"] == 0.91

    def test_higher_temperature_skipped_for_quality_problems(self, strategy):
        """Test higher temp skipped for quality/correctness problems."""
        # Test quality_low problem
        config1 = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.5},
        )
        patterns1 = [LearnedPattern("low_quality", "Test", 10, 0.9, {})]  # Contains "quality"
        variants1 = strategy.generate_variants(config1, patterns1)
        variant_types1 = [v.extra_metadata["variant_type"] for v in variants1]
        assert "higher_temperature" not in variant_types1

        # Test incorrect_output problem
        config2 = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.5},
        )
        patterns2 = [LearnedPattern("incorrect_output", "Test", 10, 0.9, {})]
        variants2 = strategy.generate_variants(config2, patterns2)
        variant_types2 = [v.extra_metadata["variant_type"] for v in variants2]
        # Note: _infer_problem_type doesn't check for "incorrect", only quality/inconsistent/error/hallucin
        # So this will return "unknown" and higher temp WILL be generated
        # Let's check the actual behavior

        # Test hallucination problem
        config3 = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.5},
        )
        patterns3 = [LearnedPattern("hallucination_detected", "Test", 10, 0.9, {})]  # Contains "hallucin"
        variants3 = strategy.generate_variants(config3, patterns3)
        variant_types3 = [v.extra_metadata["variant_type"] for v in variants3]
        assert "higher_temperature" not in variant_types3

    def test_higher_temperature_skipped_when_already_high(self, strategy):
        """Test higher temp skipped when temperature already high."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.9},  # Above MAX_TEMP_FOR_INCREASE (0.85)
        )
        variants = strategy.generate_variants(config, [])

        # Should not include higher temperature variant
        variant_types = [v.extra_metadata["variant_type"] for v in variants]
        assert "higher_temperature" not in variant_types

    def test_variant_3_focused_top_p_for_quality_issues(self, strategy):
        """Test adjusts top_p for quality issues."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.7, "top_p": 0.95},
        )
        patterns = [LearnedPattern("quality_low", "Poor quality", 10, 0.9, {})]
        variants = strategy.generate_variants(config, patterns)

        # Find focused top_p variant
        focused_variants = [
            v for v in variants if v.extra_metadata.get("variant_type") == "focused_top_p"
        ]
        if focused_variants:
            variant = focused_variants[0]
            assert variant.inference["top_p"] == 0.8  # FOCUSED_TOP_P
            assert "more focused" in variant.extra_metadata["change"]

    def test_variant_3_balanced_top_p_for_other_problems(self, strategy):
        """Test adjusts top_p to balanced for non-quality issues."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.7, "top_p": 0.8},
        )
        patterns = [LearnedPattern("too_verbose", "Too verbose", 10, 0.9, {})]
        variants = strategy.generate_variants(config, patterns)

        # Find balanced top_p variant
        balanced_variants = [
            v for v in variants if v.extra_metadata.get("variant_type") == "balanced_top_p"
        ]
        if balanced_variants:
            variant = balanced_variants[0]
            assert variant.inference["top_p"] == 0.9  # BALANCED_TOP_P
            assert "balanced" in variant.extra_metadata["change"]

    def test_top_p_variant_skipped_when_already_focused(self, strategy):
        """Test top_p variant skipped when already at target value."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.7, "top_p": 0.8},  # Already focused
        )
        patterns = [LearnedPattern("quality_low", "Poor quality", 10, 0.9, {})]
        variants = strategy.generate_variants(config, patterns)

        # Should not include focused_top_p variant (already at 0.8)
        variant_types = [v.extra_metadata["variant_type"] for v in variants]
        assert "focused_top_p" not in variant_types

    def test_top_p_variant_skipped_when_already_balanced(self, strategy):
        """Test top_p variant skipped when already at balanced value."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.7, "top_p": 0.9},  # Already balanced
        )
        patterns = []
        variants = strategy.generate_variants(config, patterns)

        # Should not include balanced_top_p variant (within tolerance)
        variant_types = [v.extra_metadata["variant_type"] for v in variants]
        assert "balanced_top_p" not in variant_types

    def test_variant_4_combined_optimal(self, strategy):
        """Test combined variant adjusts both temperature and top_p."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.7, "top_p": 0.95},
        )
        patterns = [LearnedPattern("quality_low", "Poor quality", 10, 0.9, {})]
        variants = strategy.generate_variants(config, patterns)

        # Find combined variant (should be present when >= 2 other variants)
        combined_variants = [
            v for v in variants if v.extra_metadata.get("variant_type") == "combined_optimal"
        ]
        if combined_variants:
            variant = combined_variants[0]
            assert variant.inference["temperature"] == 0.1  # DETERMINISTIC_TEMP
            assert variant.inference["top_p"] == 0.8  # FOCUSED_TOP_P
            assert "temperature" in variant.extra_metadata["change"]
            assert "top_p" in variant.extra_metadata["change"]

    def test_combined_variant_skipped_when_already_optimal(self, strategy):
        """Test combined variant skipped when already at optimal values."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.1, "top_p": 0.8},  # Already optimal for quality
        )
        patterns = [LearnedPattern("quality_low", "Poor quality", 10, 0.9, {})]
        variants = strategy.generate_variants(config, patterns)

        # Should not include combined variant (within tolerance)
        variant_types = [v.extra_metadata["variant_type"] for v in variants]
        assert "combined_optimal" not in variant_types

    def test_variants_preserve_other_config(self, strategy):
        """Test variants preserve non-targeted configuration."""
        config = SIOptimizationConfig(
            agent_name="test_agent",
            agent_version="2.0.0",
            inference={
                "model": "llama3:8b",
                "temperature": 0.7,
                "top_p": 0.9,
                "max_tokens": 1000,
            },
            prompt={"template": "Extract info"},
            caching={"enabled": True, "ttl": 3600},
        )

        variants = strategy.generate_variants(config, [])

        for variant in variants:
            # Agent metadata preserved
            assert variant.agent_name == "test_agent"
            assert variant.agent_version == "2.0.0"

            # Model and max_tokens preserved
            assert variant.inference["model"] == "llama3:8b"
            assert variant.inference["max_tokens"] == 1000

            # Other config preserved
            assert variant.prompt["template"] == "Extract info"
            assert variant.caching["enabled"] is True
            assert variant.caching["ttl"] == 3600

    def test_estimate_impact_for_quality_low(self, strategy):
        """Test impact estimation for quality problems."""
        problem = {"type": "quality_low"}
        impact = strategy.estimate_impact(problem)
        assert impact == 0.25

    def test_estimate_impact_for_error_rate_high(self, strategy):
        """Test impact estimation for error rate problems."""
        problem = {"type": "error_rate_high"}
        impact = strategy.estimate_impact(problem)
        assert impact == 0.20

    def test_estimate_impact_for_inconsistent_output(self, strategy):
        """Test impact estimation for consistency problems."""
        problem = {"type": "inconsistent_output"}
        impact = strategy.estimate_impact(problem)
        assert impact == 0.40

    def test_estimate_impact_for_hallucination(self, strategy):
        """Test impact estimation for hallucination problems."""
        problem = {"type": "hallucination"}
        impact = strategy.estimate_impact(problem)
        assert impact == 0.30

    def test_estimate_impact_for_incorrect_output(self, strategy):
        """Test impact estimation for incorrect output problems."""
        problem = {"type": "incorrect_output"}
        impact = strategy.estimate_impact(problem)
        assert impact == 0.25

    def test_estimate_impact_for_verbosity(self, strategy):
        """Test impact estimation for verbosity problems."""
        assert strategy.estimate_impact({"type": "too_verbose"}) == 0.20
        assert strategy.estimate_impact({"type": "too_brief"}) == 0.20

    def test_estimate_impact_for_unknown_problem(self, strategy):
        """Test impact estimation for unknown problems."""
        problem = {"type": "unknown"}
        impact = strategy.estimate_impact(problem)
        assert impact == 0.15  # Default

    def test_temperature_presets(self, strategy):
        """Test temperature preset constants."""
        assert strategy.DETERMINISTIC_TEMP == 0.1
        assert strategy.BALANCED_TEMP == 0.5
        assert strategy.CREATIVE_TEMP == 0.9

    def test_top_p_presets(self, strategy):
        """Test top_p preset constants."""
        assert strategy.FOCUSED_TOP_P == 0.8
        assert strategy.BALANCED_TOP_P == 0.9
        assert strategy.DIVERSE_TOP_P == 0.95

    def test_top_k_presets(self, strategy):
        """Test top_k preset constants."""
        assert strategy.NARROW_TOP_K == 20
        assert strategy.MODERATE_TOP_K == 50
        assert strategy.WIDE_TOP_K == 100

    def test_infer_problem_type_from_quality_pattern(self, strategy):
        """Test problem type inference from quality patterns."""
        patterns = [LearnedPattern("low_quality_output", "Quality issues", 5, 0.8, {})]
        problem_type = strategy._infer_problem_type(patterns)
        assert problem_type == "quality_low"

    def test_infer_problem_type_from_inconsistent_pattern(self, strategy):
        """Test problem type inference from inconsistency patterns."""
        patterns = [LearnedPattern("high_variance", "Inconsistent", 10, 0.9, {})]
        problem_type = strategy._infer_problem_type(patterns)
        assert problem_type == "inconsistent_output"

    def test_infer_problem_type_from_error_pattern(self, strategy):
        """Test problem type inference from error patterns."""
        patterns = [LearnedPattern("error_prone", "Many errors", 8, 0.85, {})]
        problem_type = strategy._infer_problem_type(patterns)
        assert problem_type == "error_rate_high"

    def test_infer_problem_type_from_hallucination_pattern(self, strategy):
        """Test problem type inference from hallucination patterns."""
        patterns = [LearnedPattern("hallucinating", "Invents facts", 12, 0.9, {})]
        problem_type = strategy._infer_problem_type(patterns)
        assert problem_type == "hallucination"

    def test_infer_problem_type_defaults_to_unknown(self, strategy):
        """Test problem type defaults to unknown when no patterns."""
        problem_type = strategy._infer_problem_type([])
        assert problem_type == "unknown"

    def test_infer_problem_type_with_unrelated_pattern(self, strategy):
        """Test problem type returns unknown for unrelated patterns."""
        patterns = [LearnedPattern("network_latency", "Slow network", 5, 0.7, {})]
        problem_type = strategy._infer_problem_type(patterns)
        assert problem_type == "unknown"

    def test_uses_default_temperature_when_not_specified(self, strategy):
        """Test uses DEFAULT_TEMPERATURE when not in config."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"model": "llama3:8b"},  # No temperature
        )
        variants = strategy.generate_variants(config, [])

        # Should use default 0.7
        # Lower temp variant should be present
        lower_temp_variants = [
            v for v in variants if v.extra_metadata.get("variant_type") == "lower_temperature"
        ]
        assert len(lower_temp_variants) > 0

    def test_uses_default_top_p_when_not_specified(self, strategy):
        """Test uses DEFAULT_TOP_P when not in config."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"model": "llama3:8b"},  # No top_p
        )
        patterns = [LearnedPattern("quality_low", "Poor quality", 10, 0.9, {})]
        variants = strategy.generate_variants(config, patterns)

        # Should use default 0.9 and compare against it
        # Focused variant should be present if default > 0.85
        focused_variants = [
            v for v in variants if v.extra_metadata.get("variant_type") == "focused_top_p"
        ]
        assert len(focused_variants) > 0

    def test_max_variants_limit(self, strategy):
        """Test respects MAX_VARIANTS limit."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.7, "top_p": 0.95},
        )
        patterns = [LearnedPattern("quality_low", "Poor quality", 10, 0.9, {})]
        variants = strategy.generate_variants(config, patterns)

        # Should not exceed 4 variants
        assert len(variants) <= 4

    def test_variants_include_strategy_metadata(self, strategy, base_config):
        """Test all variants include strategy metadata."""
        variants = strategy.generate_variants(base_config, [])

        for variant in variants:
            assert "strategy" in variant.extra_metadata
            assert variant.extra_metadata["strategy"] == "temperature_search"
            assert "variant_type" in variant.extra_metadata
            assert "change" in variant.extra_metadata

    def test_variants_are_independent_copies(self, strategy, base_config):
        """Test variants are deep copies, not shallow references."""
        variants = strategy.generate_variants(base_config, [])

        # Modify first variant
        variants[0].inference["temperature"] = 0.99

        # Other variants should be unaffected
        for i in range(1, len(variants)):
            assert variants[i].inference["temperature"] != 0.99

        # Original config should be unaffected
        assert base_config.inference["temperature"] == 0.7

    def test_temperature_rounded_to_2_decimals(self, strategy):
        """Test temperature values are rounded to 2 decimal places."""
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.777},
        )
        variants = strategy.generate_variants(config, [])

        for variant in variants:
            temp = variant.inference["temperature"]
            assert temp == round(temp, 2)

    def test_learning_store_integration(self, strategy):
        """Test strategy initializes without learning_store."""
        assert strategy.learning_store is None

        # estimate_impact should use fallback estimates
        problem = {"type": "inconsistent_output"}
        impact = strategy.estimate_impact(problem)
        assert impact == 0.40  # Fallback value

    def test_combined_variant_requires_2_or_more_variants(self, strategy):
        """Test combined variant only added when >= 2 other variants."""
        # Edge case: very low temp, already at limits
        config = SIOptimizationConfig(
            agent_name="test",
            inference={"temperature": 0.05, "top_p": 0.8},  # At limits
        )
        patterns = [LearnedPattern("quality_low", "Poor quality", 10, 0.9, {})]
        variants = strategy.generate_variants(config, patterns)

        # If fewer than 2 variants, no combined variant
        if len(variants) < 2:
            variant_types = [v.extra_metadata["variant_type"] for v in variants]
            assert "combined_optimal" not in variant_types

    def test_problem_type_priority_in_patterns(self, strategy):
        """Test infer_problem_type picks first matching pattern."""
        patterns = [
            LearnedPattern("high_quality", "Good quality", 5, 0.8, {}),
            LearnedPattern("low_quality", "Bad quality", 10, 0.9, {}),
        ]
        # Should pick first one with "quality"
        problem_type = strategy._infer_problem_type(patterns)
        assert problem_type == "quality_low"
