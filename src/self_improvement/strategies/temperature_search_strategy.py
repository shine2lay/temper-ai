"""
Temperature Search Strategy for M5 self-improvement system.

Systematically varies temperature and other sampling parameters to optimize
the quality/consistency/creativity tradeoff for agent outputs.
"""
import copy
from typing import Dict, List, Optional

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

    def _create_lower_temp_variant(
        self,
        current_config: SIOptimizationConfig,
        current_temp: float
    ) -> Optional[SIOptimizationConfig]:
        """Create lower temperature variant."""
        if current_temp <= MIN_TEMP_FOR_REDUCTION:
            return None

        target_temp = (
            self.DETERMINISTIC_TEMP if current_temp > TEMP_BOUNDARY_BALANCED
            else current_temp * LOW_TEMP_MULTIPLIER
        )
        variant = copy.deepcopy(current_config)
        variant.inference[PARAM_TEMPERATURE] = round(target_temp, 2)
        variant.extra_metadata[META_STRATEGY] = self.name
        variant.extra_metadata[META_VARIANT_TYPE] = "lower_temperature"
        variant.extra_metadata[META_CHANGE] = (
            f"{LOG_TEMPERATURE_PREFIX}{current_temp} -> {target_temp:.2f} (more deterministic)"
        )
        return variant

    def _create_higher_temp_variant(
        self,
        current_config: SIOptimizationConfig,
        current_temp: float,
        problem_type: str
    ) -> Optional[SIOptimizationConfig]:
        """Create higher temperature variant if appropriate."""
        skip_problems = (PROBLEM_QUALITY_LOW, PROBLEM_INCORRECT_OUTPUT, PROBLEM_HALLUCINATION)
        if problem_type in skip_problems or current_temp >= MAX_TEMP_FOR_INCREASE:
            return None

        target_temp = (
            self.CREATIVE_TEMP if current_temp < CREATIVE_TEMP_THRESHOLD
            else min(MAX_CREATIVE_TEMP, current_temp * HIGH_TEMP_MULTIPLIER)
        )
        variant = copy.deepcopy(current_config)
        variant.inference[PARAM_TEMPERATURE] = round(target_temp, 2)
        variant.extra_metadata[META_STRATEGY] = self.name
        variant.extra_metadata[META_VARIANT_TYPE] = "higher_temperature"
        variant.extra_metadata[META_CHANGE] = (
            f"{LOG_TEMPERATURE_PREFIX}{current_temp} -> {target_temp:.2f} (more creative)"
        )
        return variant

    def _create_top_p_variant(
        self,
        current_config: SIOptimizationConfig,
        current_top_p: float,
        problem_type: str
    ) -> Optional[SIOptimizationConfig]:
        """Create top_p adjustment variant."""
        quality_problems = (PROBLEM_QUALITY_LOW, PROBLEM_ERROR_RATE_HIGH, PROBLEM_INCORRECT_OUTPUT)

        if problem_type in quality_problems:
            if current_top_p <= TOP_P_INCREASE_THRESHOLD:
                return None
            target_top_p = self.FOCUSED_TOP_P
            variant_type = "focused_top_p"
            change_desc = "more focused"
        else:
            if abs(current_top_p - self.BALANCED_TOP_P) <= TOP_P_TOLERANCE:
                return None
            target_top_p = self.BALANCED_TOP_P
            variant_type = "balanced_top_p"
            change_desc = "balanced"

        variant = copy.deepcopy(current_config)
        variant.inference[PARAM_TOP_P] = target_top_p
        variant.extra_metadata[META_STRATEGY] = self.name
        variant.extra_metadata[META_VARIANT_TYPE] = variant_type
        variant.extra_metadata[META_CHANGE] = (
            f"top_p: {current_top_p} -> {target_top_p} ({change_desc})"
        )
        return variant

    def _create_combined_variant(
        self,
        current_config: SIOptimizationConfig,
        current_temp: float,
        current_top_p: float,
        problem_type: str
    ) -> Optional[SIOptimizationConfig]:
        """Create combined temperature + top_p variant."""
        quality_problems = (PROBLEM_QUALITY_LOW, PROBLEM_ERROR_RATE_HIGH, PROBLEM_INCORRECT_OUTPUT)

        if problem_type in quality_problems:
            optimal_temp = self.DETERMINISTIC_TEMP
            optimal_top_p = self.FOCUSED_TOP_P
        else:
            optimal_temp = self.BALANCED_TEMP
            optimal_top_p = self.BALANCED_TOP_P

        # Check if different from current
        temp_changed = abs(current_temp - optimal_temp) > TEMP_COMPARISON_TOLERANCE
        top_p_changed = abs(current_top_p - optimal_top_p) > TOP_P_TOLERANCE

        if not (temp_changed or top_p_changed):
            return None

        variant = copy.deepcopy(current_config)
        variant.inference[PARAM_TEMPERATURE] = optimal_temp
        variant.inference[PARAM_TOP_P] = optimal_top_p
        variant.extra_metadata[META_STRATEGY] = self.name
        variant.extra_metadata[META_VARIANT_TYPE] = "combined_optimal"
        variant.extra_metadata[META_CHANGE] = (
            f"temperature: {current_temp} -> {optimal_temp}, "
            f"top_p: {current_top_p} -> {optimal_top_p}"
        )
        return variant

    def generate_variants(
        self, current_config: SIOptimizationConfig, patterns: List[LearnedPattern]
    ) -> List[SIOptimizationConfig]:
        """Generate improved configuration variants."""
        variants = []
        current_temp = current_config.inference.get(PARAM_TEMPERATURE, DEFAULT_TEMPERATURE)
        current_top_p = current_config.inference.get(PARAM_TOP_P, DEFAULT_TOP_P)
        problem_type = self._infer_problem_type(patterns)

        # Generate all variant types
        if variant := self._create_lower_temp_variant(current_config, current_temp):
            variants.append(variant)

        if variant := self._create_higher_temp_variant(current_config, current_temp, problem_type):
            variants.append(variant)

        if variant := self._create_top_p_variant(current_config, current_top_p, problem_type):
            variants.append(variant)

        # Only add combined if we have 2+ variants
        if len(variants) >= 2:
            if variant := self._create_combined_variant(
                current_config, current_temp, current_top_p, problem_type
            ):
                variants.append(variant)

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
