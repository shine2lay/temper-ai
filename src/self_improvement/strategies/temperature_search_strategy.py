"""
Temperature Search Strategy for M5 self-improvement system.

Systematically varies temperature and other sampling parameters to optimize
the quality/consistency/creativity tradeoff for agent outputs.
"""
import copy
from typing import Dict, List

from src.self_improvement.constants import LOG_TEMPERATURE_PREFIX
from src.self_improvement.strategies.strategy import (
    ImprovementStrategy,
    LearnedPattern,
    SIOptimizationConfig,
)

# Temperature threshold constants
MIN_TEMP_FOR_REDUCTION = 0.15  # Minimum temperature before skipping reduction variant
MAX_TEMP_FOR_INCREASE = 0.85  # Maximum temperature before skipping increase variant
TEMP_BOUNDARY_BALANCED = 0.5  # Boundary between low and balanced temperature
CREATIVE_TEMP_THRESHOLD = 0.6  # Threshold for creative temperature consideration
MAX_CREATIVE_TEMP = 0.95  # Maximum creative temperature limit

# Temperature multipliers
LOW_TEMP_MULTIPLIER = 0.5  # Multiplier for reducing temperature
HIGH_TEMP_MULTIPLIER = 1.3  # Multiplier for increasing temperature

# Top-p threshold constants
TOP_P_INCREASE_THRESHOLD = 0.85  # Threshold for increasing top_p (focused sampling)
TOP_P_TOLERANCE = 0.05  # Tolerance for comparing top_p values
TEMP_COMPARISON_TOLERANCE = 0.05  # Tolerance for comparing temperature values

# Variant limits
MAX_VARIANTS = 4  # Maximum number of variants to generate

# Default inference parameter values
DEFAULT_TEMPERATURE = 0.7  # Default temperature if not specified
DEFAULT_TOP_P = 0.9  # Default top_p if not specified

# Problem type constants
PROBLEM_QUALITY_LOW = "quality_low"
PROBLEM_ERROR_RATE_HIGH = "error_rate_high"
PROBLEM_INCONSISTENT_OUTPUT = "inconsistent_output"
PROBLEM_HALLUCINATION = "hallucination"
PROBLEM_INCORRECT_OUTPUT = "incorrect_output"
PROBLEM_TOO_VERBOSE = "too_verbose"
PROBLEM_TOO_BRIEF = "too_brief"
PROBLEM_UNKNOWN = "unknown"

# Metadata key constants
META_STRATEGY = "strategy"
META_VARIANT_TYPE = "variant_type"
META_CHANGE = "change"

# Inference parameter key constants
PARAM_TEMPERATURE = "temperature"
PARAM_TOP_P = "top_p"

# Expected impact estimates by problem type
IMPACT_QUALITY_LOW = 0.25  # Moderate impact on quality issues
IMPACT_ERROR_RATE_HIGH = 0.20  # Some impact on error rates
IMPACT_INCONSISTENT_OUTPUT = 0.40  # High impact on consistency
IMPACT_HALLUCINATION = 0.30  # Good impact on hallucination
IMPACT_INCORRECT_OUTPUT = 0.25  # Moderate impact on correctness
IMPACT_TOO_VERBOSE = 0.20  # Some impact on verbosity
IMPACT_TOO_BRIEF = 0.20  # Some impact on brevity
IMPACT_DEFAULT = 0.15  # Default impact for unknown problem types


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
        current_temp = current_config.inference.get(PARAM_TEMPERATURE, DEFAULT_TEMPERATURE)
        current_top_p = current_config.inference.get(PARAM_TOP_P, DEFAULT_TOP_P)
        # Infer problem type from patterns (if available)
        problem_type = self._infer_problem_type(patterns)

        # Variant 1: Lower temperature (more deterministic)
        # Always generate this unless temperature is already very low
        if current_temp > MIN_TEMP_FOR_REDUCTION:
            target_temp = self.DETERMINISTIC_TEMP if current_temp > TEMP_BOUNDARY_BALANCED else current_temp * LOW_TEMP_MULTIPLIER
            variant_low_temp = copy.deepcopy(current_config)
            variant_low_temp.inference[PARAM_TEMPERATURE] = round(target_temp, 2)
            variant_low_temp.extra_metadata[META_STRATEGY] = self.name
            variant_low_temp.extra_metadata[META_VARIANT_TYPE] = "lower_temperature"
            variant_low_temp.extra_metadata[META_CHANGE] = (
                f"{LOG_TEMPERATURE_PREFIX}{current_temp} -> {target_temp:.2f} (more deterministic)"
            )
            variants.append(variant_low_temp)

        # Variant 2: Higher temperature (more creative)
        # Only if problem suggests need for creativity or diversity
        # Skip higher temperature for quality/correctness problems
        if problem_type not in (PROBLEM_QUALITY_LOW, PROBLEM_INCORRECT_OUTPUT, PROBLEM_HALLUCINATION) and current_temp < MAX_TEMP_FOR_INCREASE:
            target_temp = self.CREATIVE_TEMP if current_temp < CREATIVE_TEMP_THRESHOLD else min(MAX_CREATIVE_TEMP, current_temp * HIGH_TEMP_MULTIPLIER)
            variant_high_temp = copy.deepcopy(current_config)
            variant_high_temp.inference[PARAM_TEMPERATURE] = round(target_temp, 2)
            variant_high_temp.extra_metadata[META_STRATEGY] = self.name
            variant_high_temp.extra_metadata[META_VARIANT_TYPE] = "higher_temperature"
            variant_high_temp.extra_metadata[META_CHANGE] = (
                f"{LOG_TEMPERATURE_PREFIX}{current_temp} -> {target_temp:.2f} (more creative)"
            )
            variants.append(variant_high_temp)

        # Variant 3: Adjusted top_p for better quality/diversity balance
        # For quality issues, use more focused sampling
        if problem_type in (PROBLEM_QUALITY_LOW, PROBLEM_ERROR_RATE_HIGH, PROBLEM_INCORRECT_OUTPUT):
            if current_top_p > TOP_P_INCREASE_THRESHOLD:
                target_top_p = self.FOCUSED_TOP_P
                variant_top_p = copy.deepcopy(current_config)
                variant_top_p.inference[PARAM_TOP_P] = target_top_p
                variant_top_p.extra_metadata[META_STRATEGY] = self.name
                variant_top_p.extra_metadata[META_VARIANT_TYPE] = "focused_top_p"
                variant_top_p.extra_metadata[META_CHANGE] = (
                    f"top_p: {current_top_p} -> {target_top_p} (more focused)"
                )
                variants.append(variant_top_p)
        else:
            # For other problems, try balanced or diverse sampling
            if abs(current_top_p - self.BALANCED_TOP_P) > TOP_P_TOLERANCE:
                target_top_p = self.BALANCED_TOP_P
                variant_top_p = copy.deepcopy(current_config)
                variant_top_p.inference[PARAM_TOP_P] = target_top_p
                variant_top_p.extra_metadata[META_STRATEGY] = self.name
                variant_top_p.extra_metadata[META_VARIANT_TYPE] = "balanced_top_p"
                variant_top_p.extra_metadata[META_CHANGE] = (
                    f"top_p: {current_top_p} -> {target_top_p} (balanced)"
                )
                variants.append(variant_top_p)

        # Variant 4: Combined optimal temperature + top_p
        # Only add if we have 2+ variants already
        if len(variants) >= 2:
            # Choose optimal temperature based on problem type
            if problem_type in (PROBLEM_QUALITY_LOW, PROBLEM_ERROR_RATE_HIGH, PROBLEM_INCORRECT_OUTPUT):
                optimal_temp = self.DETERMINISTIC_TEMP
                optimal_top_p = self.FOCUSED_TOP_P
            else:
                optimal_temp = self.BALANCED_TEMP
                optimal_top_p = self.BALANCED_TOP_P

            # Only add if different from current
            if abs(current_temp - optimal_temp) > TEMP_COMPARISON_TOLERANCE or abs(current_top_p - optimal_top_p) > TOP_P_TOLERANCE:
                variant_combined = copy.deepcopy(current_config)
                variant_combined.inference[PARAM_TEMPERATURE] = optimal_temp
                variant_combined.inference[PARAM_TOP_P] = optimal_top_p
                variant_combined.extra_metadata[META_STRATEGY] = self.name
                variant_combined.extra_metadata[META_VARIANT_TYPE] = "combined_optimal"
                variant_combined.extra_metadata[META_CHANGE] = (
                    f"temperature: {current_temp} -> {optimal_temp}, "
                    f"top_p: {current_top_p} -> {optimal_top_p}"
                )
                variants.append(variant_combined)

        return variants[:MAX_VARIANTS]

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
            PROBLEM_QUALITY_LOW,
            PROBLEM_ERROR_RATE_HIGH,
            PROBLEM_INCONSISTENT_OUTPUT,
            PROBLEM_HALLUCINATION,
            PROBLEM_INCORRECT_OUTPUT,
            PROBLEM_TOO_VERBOSE,
            PROBLEM_TOO_BRIEF,
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
        problem_type = problem.get("problem_type", problem.get("type", PROBLEM_UNKNOWN))

        impact_by_type = {
            PROBLEM_QUALITY_LOW: IMPACT_QUALITY_LOW,
            PROBLEM_ERROR_RATE_HIGH: IMPACT_ERROR_RATE_HIGH,
            PROBLEM_INCONSISTENT_OUTPUT: IMPACT_INCONSISTENT_OUTPUT,
            PROBLEM_HALLUCINATION: IMPACT_HALLUCINATION,
            PROBLEM_INCORRECT_OUTPUT: IMPACT_INCORRECT_OUTPUT,
            PROBLEM_TOO_VERBOSE: IMPACT_TOO_VERBOSE,
            PROBLEM_TOO_BRIEF: IMPACT_TOO_BRIEF,
        }

        return impact_by_type.get(problem_type, IMPACT_DEFAULT)

    def _infer_problem_type(self, patterns: List[LearnedPattern]) -> str:
        """
        Infer problem type from learned patterns.

        Args:
            patterns: Learned patterns from execution history

        Returns:
            Inferred problem type (or "unknown" if unclear)
        """
        if not patterns:
            return PROBLEM_UNKNOWN

        # Map pattern types to problem types
        for pattern in patterns:
            pattern_type_lower = pattern.pattern_type.lower()
            if "quality" in pattern_type_lower:
                return PROBLEM_QUALITY_LOW
            elif "inconsistent" in pattern_type_lower or "variance" in pattern_type_lower:
                return PROBLEM_INCONSISTENT_OUTPUT
            elif "error" in pattern_type_lower:
                return PROBLEM_ERROR_RATE_HIGH
            elif "hallucin" in pattern_type_lower:
                return PROBLEM_HALLUCINATION

        return PROBLEM_UNKNOWN
