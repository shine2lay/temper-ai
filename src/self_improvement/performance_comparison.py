"""
Performance Comparison for M5 Self-Improvement System.

Compares agent performance profiles (current vs baseline) to detect improvements
or regressions. Used by ImprovementDetector to identify optimization opportunities.

Design Principles:
- Metric-by-metric comparison
- Statistical significance checks
- Clear improvement/regression signals
- Handles missing metrics gracefully
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.self_improvement.constants import PROMPT_IMPROVEMENT_THRESHOLD
from src.self_improvement.data_models import AgentPerformanceProfile

logger = logging.getLogger(__name__)


@dataclass
class MetricChange:
    """
    Represents change in a single metric between two profiles.

    Attributes:
        metric_name: Name of the metric (e.g., "success_rate")
        stat_name: Statistical measure (e.g., "mean", "p95")
        baseline_value: Value in baseline profile
        current_value: Value in current profile
        absolute_change: current_value - baseline_value
        relative_change: Percentage change ((current - baseline) / baseline)
        is_improvement: Whether change is positive (higher is better for most metrics)
    """
    metric_name: str
    stat_name: str
    baseline_value: float
    current_value: float
    absolute_change: float
    relative_change: float
    is_improvement: bool

    def __repr__(self) -> str:
        """String representation for debugging."""
        direction = "↑" if self.is_improvement else "↓"
        return (
            f"MetricChange({self.metric_name}.{self.stat_name}: "
            f"{self.baseline_value:.3f} → {self.current_value:.3f} "
            f"[{self.relative_change:+.1%}] {direction})"
        )


@dataclass
class PerformanceComparison:
    """
    Result of comparing current vs baseline performance profiles.

    Attributes:
        agent_name: Name of agent being compared
        baseline_window: Time window for baseline profile
        current_window: Time window for current profile
        baseline_executions: Number of executions in baseline
        current_executions: Number of executions in current
        metric_changes: List of MetricChange objects for each metric
        overall_improvement: Whether overall performance improved
        improvement_score: Aggregated improvement score (-1.0 to +1.0)
    """
    agent_name: str
    baseline_window: str
    current_window: str
    baseline_executions: int
    current_executions: int
    metric_changes: List[MetricChange] = field(default_factory=list)
    overall_improvement: bool = False
    improvement_score: float = 0.0

    def get_metric_change(self, metric_name: str, stat_name: str = "mean") -> Optional[MetricChange]:
        """
        Get change for a specific metric.

        Args:
            metric_name: Name of the metric
            stat_name: Statistical measure (default: "mean")

        Returns:
            MetricChange or None if not found
        """
        for change in self.metric_changes:
            if change.metric_name == metric_name and change.stat_name == stat_name:
                return change
        return None

    def get_improvements(self) -> List[MetricChange]:
        """Get list of metrics that improved."""
        return [c for c in self.metric_changes if c.is_improvement]

    def get_regressions(self) -> List[MetricChange]:
        """Get list of metrics that regressed."""
        return [c for c in self.metric_changes if not c.is_improvement]

    def __repr__(self) -> str:
        """String representation for debugging."""
        direction = "IMPROVED" if self.overall_improvement else "REGRESSED"
        return (
            f"PerformanceComparison({self.agent_name}: {direction}, "
            f"score={self.improvement_score:+.2f}, "
            f"{len(self.get_improvements())} improvements, "
            f"{len(self.get_regressions())} regressions)"
        )


class PerformanceComparisonError(Exception):
    """Base exception for performance comparison errors."""
    pass


class IncomparableProfilesError(PerformanceComparisonError):
    """Raised when profiles cannot be compared (different agents, no common metrics)."""
    pass


def _validate_comparison_inputs(
    baseline: AgentPerformanceProfile,
    current: AgentPerformanceProfile,
    min_improvement_threshold: float
) -> None:
    """Validate inputs for profile comparison."""
    if baseline.agent_name != current.agent_name:
        raise IncomparableProfilesError(
            f"Cannot compare profiles from different agents: "
            f"{baseline.agent_name} vs {current.agent_name}"
        )

    if min_improvement_threshold < 0 or min_improvement_threshold > 1:
        raise ValueError(
            f"min_improvement_threshold must be 0.0-1.0, got {min_improvement_threshold}"
        )


def _compare_metric_values(
    baseline: AgentPerformanceProfile,
    current: AgentPerformanceProfile,
    common_metrics: List[tuple],
    min_improvement_threshold: float
) -> List[MetricChange]:
    """Compare metric values between profiles."""
    metric_changes = []
    for metric_name, stat_name in common_metrics:
        baseline_value = baseline.get_metric(metric_name, stat_name)
        current_value = current.get_metric(metric_name, stat_name)

        if baseline_value is None or current_value is None:
            logger.debug(f"Skipping {metric_name}.{stat_name}: missing value")
            continue

        # Calculate changes
        absolute_change = current_value - baseline_value
        relative_change = absolute_change / baseline_value if baseline_value != 0 else 0.0

        # Determine if improvement
        is_improvement = _is_improvement(metric_name, absolute_change, min_improvement_threshold)

        change = MetricChange(
            metric_name=metric_name,
            stat_name=stat_name,
            baseline_value=baseline_value,
            current_value=current_value,
            absolute_change=absolute_change,
            relative_change=relative_change,
            is_improvement=is_improvement
        )
        metric_changes.append(change)
        logger.debug(f"Metric change: {change}")

    return metric_changes


def compare_profiles(
    baseline: AgentPerformanceProfile,
    current: AgentPerformanceProfile,
    min_improvement_threshold: float = PROMPT_IMPROVEMENT_THRESHOLD,
    metric_weights: Optional[Dict[str, float]] = None
) -> PerformanceComparison:
    """Compare current vs baseline performance profiles."""
    # Validate inputs
    _validate_comparison_inputs(baseline, current, min_improvement_threshold)

    logger.info(
        f"Comparing profiles: agent={baseline.agent_name}, "
        f"baseline={baseline.total_executions} executions, "
        f"current={current.total_executions} executions"
    )

    # Find common metrics
    common_metrics = _find_common_metrics(baseline, current)

    if not common_metrics:
        raise IncomparableProfilesError(
            f"No common metrics between baseline and current profiles for {baseline.agent_name}"
        )

    # Compare metrics
    metric_changes = _compare_metric_values(
        baseline, current, common_metrics, min_improvement_threshold
    )

    # Calculate overall improvement
    improvement_score = _calculate_improvement_score(metric_changes, metric_weights)
    overall_improvement = improvement_score > 0

    # Create comparison result
    comparison = PerformanceComparison(
        agent_name=baseline.agent_name,
        baseline_window=f"{baseline.window_start.isoformat()} to {baseline.window_end.isoformat()}",
        current_window=f"{current.window_start.isoformat()} to {current.window_end.isoformat()}",
        baseline_executions=baseline.total_executions,
        current_executions=current.total_executions,
        metric_changes=metric_changes,
        overall_improvement=overall_improvement,
        improvement_score=improvement_score
    )

    logger.info(
        f"Comparison complete: {comparison.agent_name} "
        f"{'IMPROVED' if overall_improvement else 'REGRESSED'} "
        f"(score: {improvement_score:+.2f})"
    )

    return comparison


def _find_common_metrics(
    baseline: AgentPerformanceProfile,
    current: AgentPerformanceProfile
) -> List[tuple]:
    """
    Find metrics present in both profiles.

    Returns:
        List of (metric_name, stat_name) tuples
    """
    common = []

    for metric_name in baseline.metrics:
        if metric_name in current.metrics:
            # Find common stat names (mean, std, p95, etc.)
            baseline_stats = set(baseline.metrics[metric_name].keys())
            current_stats = set(current.metrics[metric_name].keys())
            common_stats = baseline_stats & current_stats

            for stat_name in common_stats:
                common.append((metric_name, stat_name))

    logger.debug(f"Found {len(common)} common metric stats")
    return common


def _is_improvement(
    metric_name: str,
    change: float,
    threshold: float
) -> bool:
    """
    Determine if metric change represents improvement.

    Args:
        metric_name: Name of the metric
        change: Absolute change (current - baseline)
        threshold: Minimum change to consider significant

    Returns:
        True if improvement, False if regression

    Note:
        - For most metrics (success_rate, quality_score), higher is better
        - For cost and duration metrics, lower is better
    """
    # Metrics where lower is better
    lower_is_better = ["cost_usd", "duration_seconds", "error_rate"]

    # Check if change is significant enough
    if abs(change) < threshold:
        # Change too small to matter - call it neutral (not improvement)
        return False

    # Determine improvement based on metric type
    if any(m in metric_name for m in lower_is_better):
        # Lower is better (cost, duration)
        return change < 0
    else:
        # Higher is better (success_rate, quality_score, etc.)
        return change > 0


def _calculate_improvement_score(
    metric_changes: List[MetricChange],
    metric_weights: Optional[Dict[str, float]] = None
) -> float:
    """
    Calculate aggregated improvement score from metric changes.

    Args:
        metric_changes: List of MetricChange objects
        metric_weights: Optional weights for each metric (default: equal weights)

    Returns:
        Improvement score from -1.0 (total regression) to +1.0 (total improvement)

    Algorithm:
        - Each metric contributes +1 for improvement, -1 for regression
        - Weighted by metric importance (if weights provided)
        - Normalized to [-1.0, +1.0] range
    """
    if not metric_changes:
        return 0.0

    # Default weights: equal for all metrics
    if metric_weights is None:
        metric_weights = {}

    total_weight = 0.0
    weighted_sum = 0.0

    for change in metric_changes:
        # Get weight for this metric (default 1.0)
        weight = metric_weights.get(change.metric_name, 1.0)

        # Contribution: +weight for improvement, -weight for regression
        contribution = weight if change.is_improvement else -weight

        weighted_sum += contribution
        total_weight += weight

    # Normalize to [-1.0, +1.0]
    if total_weight == 0:
        return 0.0

    score = weighted_sum / total_weight
    return max(-1.0, min(1.0, score))  # Clamp to valid range
