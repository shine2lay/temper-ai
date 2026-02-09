"""
Statistical analyzer for M5 experiment results.

Provides statistical analysis of experiment results to determine winning configurations
using t-tests and confidence intervals.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from scipy import stats  # type: ignore[import-untyped]

from src.self_improvement.constants import (
    DEFAULT_ALPHA,
    DEFAULT_CONFIDENCE_LEVEL,
)

logger = logging.getLogger(__name__)

# Composite score weights for variant comparison
COMPOSITE_SCORE_QUALITY_WEIGHT = 0.7  # Primary factor
COMPOSITE_SCORE_SPEED_WEIGHT = 0.2    # Secondary factor
COMPOSITE_SCORE_COST_WEIGHT = 0.1     # Tertiary factor


@dataclass
class VariantResults:
    """Results for a single experiment variant."""
    variant_id: str
    variant_name: str
    sample_size: int
    quality_scores: List[float]
    speed_scores: List[float]
    cost_scores: List[float]

    @property
    def quality_mean(self) -> float:
        """Mean quality score."""
        return float(np.mean(self.quality_scores)) if self.quality_scores else 0.0

    @property
    def quality_std(self) -> float:
        """Standard deviation of quality scores."""
        return float(np.std(self.quality_scores, ddof=1)) if len(self.quality_scores) > 1 else 0.0

    @property
    def speed_mean(self) -> float:
        """Mean speed (duration) score."""
        return float(np.mean(self.speed_scores)) if self.speed_scores else 0.0

    @property
    def cost_mean(self) -> float:
        """Mean cost score."""
        return float(np.mean(self.cost_scores)) if self.cost_scores else 0.0


@dataclass
class ComparisonResult:
    """Statistical comparison between control and variant."""
    variant_id: str
    variant_name: str

    # Quality comparison
    quality_improvement: float  # Percentage improvement vs control
    quality_p_value: float
    quality_significant: bool

    # Speed comparison (lower is better)
    speed_improvement: float  # Percentage improvement (negative = slower)
    speed_p_value: float
    speed_significant: bool

    # Cost comparison (lower is better)
    cost_improvement: float  # Percentage improvement (negative = more expensive)
    cost_p_value: float
    cost_significant: bool

    # Composite score (higher is better)
    composite_score: float

    # Winner determination
    is_better_than_control: bool
    recommendation: str


@dataclass
class ExperimentAnalysis:
    """Complete analysis of an experiment."""
    experiment_id: str
    control_results: VariantResults
    variant_comparisons: List[ComparisonResult]
    winner: Optional[ComparisonResult]
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL


class SIStatisticalAnalyzer:
    """
    Analyzes experiment results using statistical tests.

    Compares variants against control using t-tests for statistical significance.
    Determines winner based on composite score weighted by:
    - Quality (primary, weight=COMPOSITE_SCORE_QUALITY_WEIGHT)
    - Speed (secondary, weight=COMPOSITE_SCORE_SPEED_WEIGHT)
    - Cost (tertiary, weight=COMPOSITE_SCORE_COST_WEIGHT)
    """

    def __init__(
        self,
        significance_level: float = DEFAULT_ALPHA,
        quality_weight: float = COMPOSITE_SCORE_QUALITY_WEIGHT,
        speed_weight: float = COMPOSITE_SCORE_SPEED_WEIGHT,
        cost_weight: float = COMPOSITE_SCORE_COST_WEIGHT,
    ):
        """
        Initialize statistical analyzer.

        Args:
            significance_level: P-value threshold for statistical significance (default: DEFAULT_ALPHA)
            quality_weight: Weight for quality in composite score (default: COMPOSITE_SCORE_QUALITY_WEIGHT)
            speed_weight: Weight for speed in composite score (default: COMPOSITE_SCORE_SPEED_WEIGHT)
            cost_weight: Weight for cost in composite score (default: COMPOSITE_SCORE_COST_WEIGHT)
        """
        self.significance_level = significance_level
        self.quality_weight = quality_weight
        self.speed_weight = speed_weight
        self.cost_weight = cost_weight

        # Validate weights sum to 1.0
        total_weight = quality_weight + speed_weight + cost_weight
        if not np.isclose(total_weight, 1.0):
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")

    def analyze_experiment(
        self,
        control: VariantResults,
        variants: List[VariantResults],
        experiment_id: str
    ) -> ExperimentAnalysis:
        """
        Analyze experiment results and determine winner.

        Args:
            control: Results for control group
            variants: Results for variant groups
            experiment_id: Experiment identifier

        Returns:
            ExperimentAnalysis with comparisons and winner
        """
        # Compare each variant against control
        comparisons = []
        for variant in variants:
            comparison = self._compare_variant_to_control(control, variant)
            comparisons.append(comparison)

        # Select winner (highest composite score among significant improvements)
        winner = self._select_winner(comparisons)

        return ExperimentAnalysis(
            experiment_id=experiment_id,
            control_results=control,
            variant_comparisons=comparisons,
            winner=winner,
            confidence_level=1.0 - self.significance_level,
        )

    def _compare_variant_to_control(
        self,
        control: VariantResults,
        variant: VariantResults
    ) -> ComparisonResult:
        """Compare a single variant against control."""

        # Quality comparison (higher is better)
        quality_improvement, quality_p, quality_sig = self._compare_metric(
            control.quality_scores,
            variant.quality_scores,
            higher_is_better=True
        )

        # Speed comparison (lower is better)
        speed_improvement, speed_p, speed_sig = self._compare_metric(
            control.speed_scores,
            variant.speed_scores,
            higher_is_better=False
        )

        # Cost comparison (lower is better)
        cost_improvement, cost_p, cost_sig = self._compare_metric(
            control.cost_scores,
            variant.cost_scores,
            higher_is_better=False
        )

        # Calculate composite score
        composite = self._calculate_composite_score(
            quality_improvement,
            speed_improvement,
            cost_improvement
        )

        # Determine if better than control
        is_better = bool(
            quality_sig and quality_improvement > 0 and
            composite > 0  # Overall improvement
        )

        # Generate recommendation
        recommendation = self._generate_recommendation(
            is_better,
            quality_improvement,
            quality_sig,
            speed_improvement,
            cost_improvement,
            composite
        )

        return ComparisonResult(
            variant_id=variant.variant_id,
            variant_name=variant.variant_name,
            quality_improvement=quality_improvement,
            quality_p_value=quality_p,
            quality_significant=quality_sig,
            speed_improvement=speed_improvement,
            speed_p_value=speed_p,
            speed_significant=speed_sig,
            cost_improvement=cost_improvement,
            cost_p_value=cost_p,
            cost_significant=cost_sig,
            composite_score=composite,
            is_better_than_control=is_better,
            recommendation=recommendation,
        )

    def _compare_metric(
        self,
        control_values: List[float],
        variant_values: List[float],
        higher_is_better: bool = True
    ) -> tuple[float, float, bool]:
        """
        Compare metric between control and variant using t-test.

        Returns:
            (improvement_percentage, p_value, is_significant)
        """
        if not control_values or not variant_values:
            return 0.0, 1.0, False

        control_mean = np.mean(control_values)
        variant_mean = np.mean(variant_values)

        # Calculate percentage improvement
        if control_mean != 0:
            if higher_is_better:
                improvement = ((variant_mean - control_mean) / control_mean) * 100
            else:
                # For metrics where lower is better, flip the sign
                improvement = ((control_mean - variant_mean) / control_mean) * 100
        else:
            improvement = np.float64(0.0)

        # Check for zero variance (constant values)
        control_std = np.std(control_values, ddof=1) if len(control_values) > 1 else 0
        variant_std = np.std(variant_values, ddof=1) if len(variant_values) > 1 else 0

        # Perform two-sample t-test
        # For higher_is_better: test if variant > control (one-tailed)
        # For lower_is_better: test if variant < control (one-tailed)
        try:
            # If both groups have zero variance, no statistical test is meaningful
            if control_std == 0 and variant_std == 0:
                # Both groups are constant - difference is deterministic
                if higher_is_better:
                    # For higher_is_better, variant > control means improvement
                    is_significant = variant_mean > control_mean
                else:
                    # For lower_is_better, variant < control means improvement
                    is_significant = variant_mean < control_mean
                p_value = 0.0 if is_significant else 1.0
            else:
                if higher_is_better:
                    # One-tailed test: variant > control
                    t_stat, p_value = stats.ttest_ind(variant_values, control_values)
                    p_value = p_value / 2 if t_stat > 0 else 1 - (p_value / 2)
                else:
                    # One-tailed test: variant < control
                    t_stat, p_value = stats.ttest_ind(control_values, variant_values)
                    p_value = p_value / 2 if t_stat > 0 else 1 - (p_value / 2)

                is_significant = bool(p_value < self.significance_level)
        except (ValueError, TypeError) as e:
            # Handle edge cases (NaN values, invalid array shapes from scipy)
            logger.warning(f"Statistical test failed: {e}, treating as non-significant")
            p_value = 1.0
            is_significant = False

        return float(improvement), float(p_value), bool(is_significant)

    def _calculate_composite_score(
        self,
        quality_improvement: float,
        speed_improvement: float,
        cost_improvement: float
    ) -> float:
        """
        Calculate weighted composite score.

        Higher is better. Positive means overall improvement.
        """
        composite = (
            self.quality_weight * quality_improvement +
            self.speed_weight * speed_improvement +
            self.cost_weight * cost_improvement
        )
        return composite

    def _select_winner(
        self,
        comparisons: List[ComparisonResult]
    ) -> Optional[ComparisonResult]:
        """
        Select winner from comparisons.

        Winner must:
        1. Have statistically significant quality improvement
        2. Have highest composite score among significant improvements
        """
        # Filter to only variants with significant quality improvements
        candidates = [
            c for c in comparisons
            if c.is_better_than_control
        ]

        if not candidates:
            return None

        # Select highest composite score
        winner = max(candidates, key=lambda c: c.composite_score)
        return winner

    def _generate_recommendation(
        self,
        is_better: bool,
        quality_improvement: float,
        quality_significant: bool,
        speed_improvement: float,
        cost_improvement: float,
        composite: float
    ) -> str:
        """Generate human-readable recommendation."""
        if not is_better:
            if not quality_significant:
                return "No statistically significant quality improvement"
            if quality_improvement <= 0:
                return "Quality decreased compared to control"
            if composite <= 0:
                return "Overall improvement is negative despite quality gain"
            return "Quality improved but not statistically significant"

        # Build recommendation for winner
        parts = [f"Quality improved by {quality_improvement:.1f}%"]

        if abs(speed_improvement) > 1:
            if speed_improvement > 0:
                parts.append(f"speed improved by {speed_improvement:.1f}%")
            else:
                parts.append(f"speed decreased by {abs(speed_improvement):.1f}%")

        if abs(cost_improvement) > 1:
            if cost_improvement > 0:
                parts.append(f"cost reduced by {cost_improvement:.1f}%")
            else:
                parts.append(f"cost increased by {abs(cost_improvement):.1f}%")

        recommendation = "RECOMMENDED: " + ", ".join(parts)
        recommendation += f". Overall composite score: {composite:.1f}%"

        return recommendation


def create_variant_results(
    variant_id: str,
    variant_name: str,
    quality_scores: List[float],
    speed_scores: List[float],
    cost_scores: Optional[List[float]] = None
) -> VariantResults:
    """
    Helper function to create VariantResults.

    Args:
        variant_id: Unique identifier for variant
        variant_name: Human-readable name
        quality_scores: List of quality measurements (0-1 scale)
        speed_scores: List of speed measurements (seconds)
        cost_scores: List of cost measurements (USD), optional

    Returns:
        VariantResults instance
    """
    if cost_scores is None:
        cost_scores = [0.0] * len(quality_scores)

    return VariantResults(
        variant_id=variant_id,
        variant_name=variant_name,
        sample_size=len(quality_scores),
        quality_scores=quality_scores,
        speed_scores=speed_scores,
        cost_scores=cost_scores,
    )
