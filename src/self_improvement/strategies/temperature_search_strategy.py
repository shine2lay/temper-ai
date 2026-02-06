"""
Temperature Search Strategy for M5 self-improvement system.

Systematically varies temperature and other sampling parameters to optimize
the quality/consistency/creativity tradeoff for agent outputs.
"""
import copy
from typing import Dict, List

from src.self_improvement.strategies.strategy import (
    ImprovementStrategy,
    LearnedPattern,
    SIOptimizationConfig,
)


class TemperatureSearchStrategy(ImprovementStrategy):
    """
    Strategy that optimizes agent performance by tuning sampling parameters.

    Applicable when output quality, consistency, or creativity needs adjustment.
    Generates variants that systematically vary:
    1. Temperature (controls randomness/creativity)
    2. Top-p (nucleus sampling threshold)
    3. Top-k (limits vocabulary to top k tokens)

    Example:
        >>> strategy = TemperatureSearchStrategy()
        >>> current = SIOptimizationConfig(
        ...     inference={'temperature': 0.7, 'top_p': 0.9}
        ... )
        >>> variants = strategy.generate_variants(current, [])
        >>> len(variants)
        3
        >>> # Variants: lower temp, higher temp, tuned top_p
    """

    # Temperature presets for different use cases
    DETERMINISTIC_TEMP = 0.1  # For tasks requiring high consistency
    BALANCED_TEMP = 0.5  # Balanced quality and variety
    CREATIVE_TEMP = 0.9  # For tasks needing creativity

    # Top-p presets
    FOCUSED_TOP_P = 0.8  # More focused, less diverse
    BALANCED_TOP_P = 0.9  # Standard balance
    DIVERSE_TOP_P = 0.95  # More diverse outputs

    # Top-k presets
    NARROW_TOP_K = 20  # Very focused vocabulary
    MODERATE_TOP_K = 50  # Moderate vocabulary
    WIDE_TOP_K = 100  # Wider vocabulary

    def __init__(self, learning_store=None):
        """
        Initialize strategy with optional learning store.

        Args:
            learning_store: Optional StrategyLearningStore for learning from outcomes
        """
        super().__init__(learning_store)

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "temperature_search"

    def generate_variants(
        self, current_config: SIOptimizationConfig, patterns: List[LearnedPattern]
    ) -> List[SIOptimizationConfig]:
        """Generate improved configuration variants.

        Generates 3-4 variants:
        1. Lower temperature (more deterministic)
        2. Higher temperature (more creative) - if problem suggests it
        3. Adjusted top_p for better quality/diversity balance
        4. Combined: optimal temperature + top_p (if both need adjustment)

        Args:
            current_config: Current agent configuration
            patterns: Learned patterns (used to prioritize variants)

        Returns:
            List of 3-4 configuration variants
        """
        variants = []
        current_temp = current_config.inference.get("temperature", 0.7)
        current_top_p = current_config.inference.get("top_p", 0.9)
        # Infer problem type from patterns (if available)
        problem_type = self._infer_problem_type(patterns)

        # Variant 1: Lower temperature (more deterministic)
        # Always generate this unless temperature is already very low
        if current_temp > 0.15:
            target_temp = self.DETERMINISTIC_TEMP if current_temp > 0.5 else current_temp * 0.5
            variant_low_temp = copy.deepcopy(current_config)
            variant_low_temp.inference["temperature"] = round(target_temp, 2)
            variant_low_temp.extra_metadata["strategy"] = self.name
            variant_low_temp.extra_metadata["variant_type"] = "lower_temperature"
            variant_low_temp.extra_metadata["change"] = (
                f"temperature: {current_temp} -> {target_temp:.2f} (more deterministic)"
            )
            variants.append(variant_low_temp)

        # Variant 2: Higher temperature (more creative)
        # Only if problem suggests need for creativity or diversity
        if problem_type in ("quality_low", "incorrect_output", "hallucination"):
            # For these problems, we actually want lower temperature, so skip this variant
            pass
        elif current_temp < 0.85:
            target_temp = self.CREATIVE_TEMP if current_temp < 0.6 else min(0.95, current_temp * 1.3)
            variant_high_temp = copy.deepcopy(current_config)
            variant_high_temp.inference["temperature"] = round(target_temp, 2)
            variant_high_temp.extra_metadata["strategy"] = self.name
            variant_high_temp.extra_metadata["variant_type"] = "higher_temperature"
            variant_high_temp.extra_metadata["change"] = (
                f"temperature: {current_temp} -> {target_temp:.2f} (more creative)"
            )
            variants.append(variant_high_temp)

        # Variant 3: Adjusted top_p for better quality/diversity balance
        # For quality issues, use more focused sampling
        if problem_type in ("quality_low", "error_rate_high", "incorrect_output"):
            if current_top_p > 0.85:
                target_top_p = self.FOCUSED_TOP_P
                variant_top_p = copy.deepcopy(current_config)
                variant_top_p.inference["top_p"] = target_top_p
                variant_top_p.extra_metadata["strategy"] = self.name
                variant_top_p.extra_metadata["variant_type"] = "focused_top_p"
                variant_top_p.extra_metadata["change"] = (
                    f"top_p: {current_top_p} -> {target_top_p} (more focused)"
                )
                variants.append(variant_top_p)
        else:
            # For other problems, try balanced or diverse sampling
            if abs(current_top_p - self.BALANCED_TOP_P) > 0.05:
                target_top_p = self.BALANCED_TOP_P
                variant_top_p = copy.deepcopy(current_config)
                variant_top_p.inference["top_p"] = target_top_p
                variant_top_p.extra_metadata["strategy"] = self.name
                variant_top_p.extra_metadata["variant_type"] = "balanced_top_p"
                variant_top_p.extra_metadata["change"] = (
                    f"top_p: {current_top_p} -> {target_top_p} (balanced)"
                )
                variants.append(variant_top_p)

        # Variant 4: Combined optimal temperature + top_p
        # Only add if we have 2+ variants already
        if len(variants) >= 2:
            # Choose optimal temperature based on problem type
            if problem_type in ("quality_low", "error_rate_high", "incorrect_output"):
                optimal_temp = self.DETERMINISTIC_TEMP
                optimal_top_p = self.FOCUSED_TOP_P
            else:
                optimal_temp = self.BALANCED_TEMP
                optimal_top_p = self.BALANCED_TOP_P

            # Only add if different from current
            if abs(current_temp - optimal_temp) > 0.05 or abs(current_top_p - optimal_top_p) > 0.05:
                variant_combined = copy.deepcopy(current_config)
                variant_combined.inference["temperature"] = optimal_temp
                variant_combined.inference["top_p"] = optimal_top_p
                variant_combined.extra_metadata["strategy"] = self.name
                variant_combined.extra_metadata["variant_type"] = "combined_optimal"
                variant_combined.extra_metadata["change"] = (
                    f"temperature: {current_temp} -> {optimal_temp}, "
                    f"top_p: {current_top_p} -> {optimal_top_p}"
                )
                variants.append(variant_combined)

        return variants[:4]  # Limit to 4 variants max

    def is_applicable(self, problem_type: str) -> bool:
        """Check if strategy applies to the problem.

        Applicable for most output quality issues:
        - quality_low: Poor output quality
        - error_rate_high: High failure rate
        - inconsistent_output: Output varies too much
        - hallucination: Inventing information
        - incorrect_output: Wrong answers

        Args:
            problem_type: Type of problem detected

        Returns:
            True if strategy can help
        """
        applicable_types = {
            "quality_low",
            "error_rate_high",
            "inconsistent_output",
            "hallucination",
            "incorrect_output",
            "too_verbose",
            "too_brief",
        }
        return problem_type in applicable_types

    def estimate_impact(self, problem: Dict) -> float:
        """Estimate expected improvement.

        Uses historical outcomes from learning_store if available,
        otherwise falls back to problem-type-specific estimates.

        Args:
            problem: Problem details

        Returns:
            Estimated improvement (0.0-1.0)
        """
        # If learning store available, use learned estimate
        if self.learning_store:
            # Call parent's learned estimate (uses Bayesian updating)
            return super().estimate_impact(problem)

        # Fallback: Problem-type-specific estimates (used as priors if no data)
        problem_type = problem.get("problem_type", problem.get("type", "unknown"))

        impact_by_type = {
            "quality_low": 0.25,  # Moderate impact on quality
            "error_rate_high": 0.20,  # Some impact on errors
            "inconsistent_output": 0.40,  # High impact on consistency
            "hallucination": 0.30,  # Good impact on hallucination
            "incorrect_output": 0.25,  # Moderate impact on correctness
            "too_verbose": 0.20,  # Some impact on verbosity
            "too_brief": 0.20,  # Some impact on brevity
        }

        return impact_by_type.get(problem_type, 0.15)

    def _infer_problem_type(self, patterns: List[LearnedPattern]) -> str:
        """
        Infer problem type from learned patterns.

        Args:
            patterns: Learned patterns from execution history

        Returns:
            Inferred problem type (or "unknown" if unclear)
        """
        if not patterns:
            return "unknown"

        # Map pattern types to problem types
        for pattern in patterns:
            pattern_type_lower = pattern.pattern_type.lower()
            if "quality" in pattern_type_lower:
                return "quality_low"
            elif "inconsistent" in pattern_type_lower or "variance" in pattern_type_lower:
                return "inconsistent_output"
            elif "error" in pattern_type_lower:
                return "error_rate_high"
            elif "hallucin" in pattern_type_lower:
                return "hallucination"

        return "unknown"
