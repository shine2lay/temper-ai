"""
Unit tests for performance comparison functionality.

Tests cover:
- Profile comparison (improvement, regression, neutral)
- Metric change calculation
- Error handling (incomparable profiles)
- Improvement score calculation
- Edge cases (missing metrics, zero baseline)
"""

import pytest
from datetime import datetime, timedelta, timezone

from src.self_improvement.data_models import AgentPerformanceProfile
from src.self_improvement.performance_comparison import (
    compare_profiles,
    MetricChange,
    PerformanceComparison,
    IncomparableProfilesError,
    _is_improvement,
    _calculate_improvement_score,
    _find_common_metrics
)


def create_test_profile(
    agent_name: str,
    hours_ago: int,
    window_hours: int = 168,
    executions: int = 100,
    success_rate: float = 0.9,
    duration: float = 10.0,
    cost: float = 0.5
) -> AgentPerformanceProfile:
    """Helper to create test performance profile."""
    now = datetime.now(timezone.utc)
    return AgentPerformanceProfile(
        agent_name=agent_name,
        window_start=now - timedelta(hours=hours_ago + window_hours),
        window_end=now - timedelta(hours=hours_ago),
        total_executions=executions,
        metrics={
            "success_rate": {"mean": success_rate},
            "duration_seconds": {"mean": duration},
            "cost_usd": {"mean": cost}
        }
    )


class TestMetricChange:
    """Test MetricChange dataclass."""

    def test_metric_change_creation(self):
        """Test creating MetricChange."""
        change = MetricChange(
            metric_name="success_rate",
            stat_name="mean",
            baseline_value=0.8,
            current_value=0.9,
            absolute_change=0.1,
            relative_change=0.125,
            is_improvement=True
        )

        assert change.metric_name == "success_rate"
        assert change.stat_name == "mean"
        assert change.baseline_value == 0.8
        assert change.current_value == 0.9
        assert change.absolute_change == 0.1
        assert change.relative_change == 0.125
        assert change.is_improvement is True

    def test_metric_change_repr(self):
        """Test MetricChange string representation."""
        change = MetricChange(
            metric_name="duration_seconds",
            stat_name="mean",
            baseline_value=15.0,
            current_value=10.0,
            absolute_change=-5.0,
            relative_change=-0.333,
            is_improvement=True
        )

        repr_str = repr(change)
        assert "duration_seconds" in repr_str
        assert "15.000" in repr_str
        assert "10.000" in repr_str


class TestPerformanceComparison:
    """Test PerformanceComparison dataclass."""

    def test_get_metric_change(self):
        """Test retrieving specific metric change."""
        change1 = MetricChange("success_rate", "mean", 0.8, 0.9, 0.1, 0.125, True)
        change2 = MetricChange("cost_usd", "mean", 0.5, 0.3, -0.2, -0.4, True)

        comparison = PerformanceComparison(
            agent_name="test_agent",
            baseline_window="2026-01-01 to 2026-01-08",
            current_window="2026-01-25 to 2026-02-01",
            baseline_executions=100,
            current_executions=100,
            metric_changes=[change1, change2]
        )

        # Found
        result = comparison.get_metric_change("success_rate", "mean")
        assert result == change1

        # Not found
        result = comparison.get_metric_change("nonexistent", "mean")
        assert result is None

    def test_get_improvements(self):
        """Test getting list of improvements."""
        improvements = [
            MetricChange("success_rate", "mean", 0.8, 0.9, 0.1, 0.125, True),
            MetricChange("cost_usd", "mean", 0.5, 0.3, -0.2, -0.4, True)
        ]
        regressions = [
            MetricChange("duration_seconds", "mean", 10.0, 15.0, 5.0, 0.5, False)
        ]

        comparison = PerformanceComparison(
            agent_name="test_agent",
            baseline_window="baseline",
            current_window="current",
            baseline_executions=100,
            current_executions=100,
            metric_changes=improvements + regressions
        )

        result = comparison.get_improvements()
        assert len(result) == 2
        assert all(c.is_improvement for c in result)

    def test_get_regressions(self):
        """Test getting list of regressions."""
        improvements = [
            MetricChange("success_rate", "mean", 0.8, 0.9, 0.1, 0.125, True)
        ]
        regressions = [
            MetricChange("duration_seconds", "mean", 10.0, 15.0, 5.0, 0.5, False),
            MetricChange("cost_usd", "mean", 0.3, 0.5, 0.2, 0.67, False)
        ]

        comparison = PerformanceComparison(
            agent_name="test_agent",
            baseline_window="baseline",
            current_window="current",
            baseline_executions=100,
            current_executions=100,
            metric_changes=improvements + regressions
        )

        result = comparison.get_regressions()
        assert len(result) == 2
        assert all(not c.is_improvement for c in result)


class TestCompareProfiles:
    """Test compare_profiles function."""

    def test_improvement_scenario(self):
        """Test comparison when current improves over baseline."""
        baseline = create_test_profile(
            "my_agent", hours_ago=720,  # 30 days ago
            success_rate=0.8, duration=15.0, cost=0.5
        )
        current = create_test_profile(
            "my_agent", hours_ago=0,  # now
            success_rate=0.9, duration=10.0, cost=0.3
        )

        comparison = compare_profiles(baseline, current)

        # Verify overall improvement
        assert comparison.overall_improvement is True
        assert comparison.improvement_score > 0

        # Verify individual metrics
        success_change = comparison.get_metric_change("success_rate")
        assert success_change.is_improvement is True
        assert success_change.current_value > success_change.baseline_value

        duration_change = comparison.get_metric_change("duration_seconds")
        assert duration_change.is_improvement is True  # Lower is better
        assert duration_change.current_value < duration_change.baseline_value

        cost_change = comparison.get_metric_change("cost_usd")
        assert cost_change.is_improvement is True  # Lower is better
        assert cost_change.current_value < cost_change.baseline_value

    def test_regression_scenario(self):
        """Test comparison when current regresses from baseline."""
        baseline = create_test_profile(
            "my_agent", hours_ago=720,
            success_rate=0.9, duration=10.0, cost=0.3
        )
        current = create_test_profile(
            "my_agent", hours_ago=0,
            success_rate=0.7, duration=20.0, cost=0.6
        )

        comparison = compare_profiles(baseline, current)

        # Verify overall regression
        assert comparison.overall_improvement is False
        assert comparison.improvement_score < 0

        # Verify all metrics regressed
        assert len(comparison.get_regressions()) == 3
        assert len(comparison.get_improvements()) == 0

    def test_mixed_scenario(self):
        """Test comparison with some improvements and some regressions."""
        baseline = create_test_profile(
            "my_agent", hours_ago=720,
            success_rate=0.8, duration=10.0, cost=0.5
        )
        current = create_test_profile(
            "my_agent", hours_ago=0,
            success_rate=0.9,  # Improved
            duration=15.0,      # Regressed
            cost=0.3            # Improved
        )

        comparison = compare_profiles(baseline, current)

        # Should have both improvements and regressions
        assert len(comparison.get_improvements()) >= 1
        assert len(comparison.get_regressions()) >= 1

        # Overall depends on scoring
        # (2 improvements vs 1 regression -> likely improvement)
        assert comparison.improvement_score != 0

    def test_different_agents_error(self):
        """Test error when comparing profiles from different agents."""
        baseline = create_test_profile("agent1", hours_ago=720)
        current = create_test_profile("agent2", hours_ago=0)

        with pytest.raises(IncomparableProfilesError, match="different agents"):
            compare_profiles(baseline, current)

    def test_no_common_metrics_error(self):
        """Test error when profiles have no common metrics."""
        baseline = AgentPerformanceProfile(
            agent_name="my_agent",
            window_start=datetime.now(timezone.utc) - timedelta(days=30),
            window_end=datetime.now(timezone.utc) - timedelta(days=7),
            total_executions=100,
            metrics={"metric_a": {"mean": 1.0}}
        )
        current = AgentPerformanceProfile(
            agent_name="my_agent",
            window_start=datetime.now(timezone.utc) - timedelta(days=7),
            window_end=datetime.now(timezone.utc),
            total_executions=100,
            metrics={"metric_b": {"mean": 2.0}}
        )

        with pytest.raises(IncomparableProfilesError, match="No common metrics"):
            compare_profiles(baseline, current)

    def test_invalid_threshold_error(self):
        """Test error with invalid improvement threshold."""
        baseline = create_test_profile("agent", hours_ago=720)
        current = create_test_profile("agent", hours_ago=0)

        with pytest.raises(ValueError, match="min_improvement_threshold"):
            compare_profiles(baseline, current, min_improvement_threshold=1.5)

        with pytest.raises(ValueError, match="min_improvement_threshold"):
            compare_profiles(baseline, current, min_improvement_threshold=-0.1)

    def test_custom_metric_weights(self):
        """Test comparison with custom metric weights."""
        baseline = create_test_profile(
            "agent", hours_ago=720,
            success_rate=0.8, duration=10.0, cost=0.5
        )
        current = create_test_profile(
            "agent", hours_ago=0,
            success_rate=0.9, duration=10.1, cost=0.5
        )

        # Heavy weight on success_rate
        weights = {
            "success_rate": 10.0,
            "duration_seconds": 1.0,
            "cost_usd": 1.0
        }

        comparison = compare_profiles(baseline, current, metric_weights=weights)

        # Success rate improvement should dominate score
        assert comparison.improvement_score > 0

    def test_min_improvement_threshold(self):
        """Test minimum improvement threshold filtering."""
        baseline = create_test_profile(
            "agent", hours_ago=720,
            success_rate=0.900, duration=10.0
        )
        current = create_test_profile(
            "agent", hours_ago=0,
            success_rate=0.901,  # Only 0.1% improvement
            duration=10.0
        )

        # With high threshold, small change shouldn't count
        comparison = compare_profiles(baseline, current, min_improvement_threshold=0.05)

        # Success rate change too small to be improvement
        success_change = comparison.get_metric_change("success_rate")
        assert success_change.is_improvement is False


class TestIsImprovement:
    """Test _is_improvement helper function."""

    def test_higher_is_better(self):
        """Test metrics where higher is better."""
        # Success rate: higher is better
        assert _is_improvement("success_rate", 0.1, threshold=0.05) is True
        assert _is_improvement("success_rate", -0.1, threshold=0.05) is False

        # Quality score: higher is better
        assert _is_improvement("quality_score", 0.2, threshold=0.05) is True
        assert _is_improvement("quality_score", -0.2, threshold=0.05) is False

    def test_lower_is_better(self):
        """Test metrics where lower is better."""
        # Cost: lower is better
        assert _is_improvement("cost_usd", -0.1, threshold=0.05) is True
        assert _is_improvement("cost_usd", 0.1, threshold=0.05) is False

        # Duration: lower is better
        assert _is_improvement("duration_seconds", -2.0, threshold=0.05) is True
        assert _is_improvement("duration_seconds", 2.0, threshold=0.05) is False

        # Error rate: lower is better
        assert _is_improvement("error_rate", -0.05, threshold=0.01) is True
        assert _is_improvement("error_rate", 0.05, threshold=0.01) is False

    def test_change_below_threshold(self):
        """Test changes below threshold are not improvements."""
        # Change too small
        assert _is_improvement("success_rate", 0.01, threshold=0.05) is False
        assert _is_improvement("cost_usd", -0.01, threshold=0.05) is False


class TestCalculateImprovementScore:
    """Test _calculate_improvement_score helper function."""

    def test_all_improvements(self):
        """Test score with all improvements."""
        changes = [
            MetricChange("m1", "mean", 1.0, 2.0, 1.0, 1.0, True),
            MetricChange("m2", "mean", 1.0, 2.0, 1.0, 1.0, True),
            MetricChange("m3", "mean", 1.0, 2.0, 1.0, 1.0, True)
        ]

        score = _calculate_improvement_score(changes)
        assert score == 1.0  # Perfect improvement

    def test_all_regressions(self):
        """Test score with all regressions."""
        changes = [
            MetricChange("m1", "mean", 2.0, 1.0, -1.0, -0.5, False),
            MetricChange("m2", "mean", 2.0, 1.0, -1.0, -0.5, False),
            MetricChange("m3", "mean", 2.0, 1.0, -1.0, -0.5, False)
        ]

        score = _calculate_improvement_score(changes)
        assert score == -1.0  # Total regression

    def test_mixed_changes(self):
        """Test score with mixed improvements and regressions."""
        changes = [
            MetricChange("m1", "mean", 1.0, 2.0, 1.0, 1.0, True),
            MetricChange("m2", "mean", 2.0, 1.0, -1.0, -0.5, False)
        ]

        score = _calculate_improvement_score(changes)
        assert score == 0.0  # Neutral (1 improvement + 1 regression)

    def test_weighted_score(self):
        """Test weighted improvement score."""
        changes = [
            MetricChange("important", "mean", 1.0, 2.0, 1.0, 1.0, True),
            MetricChange("minor", "mean", 2.0, 1.0, -1.0, -0.5, False)
        ]

        weights = {"important": 10.0, "minor": 1.0}
        score = _calculate_improvement_score(changes, weights)

        # Important improvement should outweigh minor regression
        assert score > 0

    def test_empty_changes(self):
        """Test score with no changes."""
        score = _calculate_improvement_score([])
        assert score == 0.0


class TestFindCommonMetrics:
    """Test _find_common_metrics helper function."""

    def test_identical_metrics(self):
        """Test profiles with identical metrics."""
        profile1 = AgentPerformanceProfile(
            agent_name="agent",
            window_start=datetime.now(timezone.utc),
            window_end=datetime.now(timezone.utc),
            total_executions=100,
            metrics={
                "success_rate": {"mean": 0.9, "std": 0.05},
                "cost_usd": {"mean": 0.5}
            }
        )
        profile2 = AgentPerformanceProfile(
            agent_name="agent",
            window_start=datetime.now(timezone.utc),
            window_end=datetime.now(timezone.utc),
            total_executions=100,
            metrics={
                "success_rate": {"mean": 0.8, "std": 0.06},
                "cost_usd": {"mean": 0.6}
            }
        )

        common = _find_common_metrics(profile1, profile2)

        # Should find: success_rate.mean, success_rate.std, cost_usd.mean
        assert len(common) == 3
        assert ("success_rate", "mean") in common
        assert ("success_rate", "std") in common
        assert ("cost_usd", "mean") in common

    def test_partial_overlap(self):
        """Test profiles with partial metric overlap."""
        profile1 = AgentPerformanceProfile(
            agent_name="agent",
            window_start=datetime.now(timezone.utc),
            window_end=datetime.now(timezone.utc),
            total_executions=100,
            metrics={
                "metric_a": {"mean": 1.0},
                "metric_b": {"mean": 2.0}
            }
        )
        profile2 = AgentPerformanceProfile(
            agent_name="agent",
            window_start=datetime.now(timezone.utc),
            window_end=datetime.now(timezone.utc),
            total_executions=100,
            metrics={
                "metric_b": {"mean": 3.0},
                "metric_c": {"mean": 4.0}
            }
        )

        common = _find_common_metrics(profile1, profile2)

        # Only metric_b is common
        assert len(common) == 1
        assert ("metric_b", "mean") in common

    def test_no_overlap(self):
        """Test profiles with no common metrics."""
        profile1 = AgentPerformanceProfile(
            agent_name="agent",
            window_start=datetime.now(timezone.utc),
            window_end=datetime.now(timezone.utc),
            total_executions=100,
            metrics={"metric_a": {"mean": 1.0}}
        )
        profile2 = AgentPerformanceProfile(
            agent_name="agent",
            window_start=datetime.now(timezone.utc),
            window_end=datetime.now(timezone.utc),
            total_executions=100,
            metrics={"metric_b": {"mean": 2.0}}
        )

        common = _find_common_metrics(profile1, profile2)

        assert len(common) == 0
