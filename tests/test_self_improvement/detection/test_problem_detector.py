"""
Tests for ProblemDetector.

Tests problem detection logic for quality, cost, and speed issues.
"""


import pytest

from src.self_improvement.detection import (
    ProblemDetectionConfig,
    ProblemDetectionDataError,
    ProblemDetector,
    ProblemSeverity,
    ProblemType,
)
from src.self_improvement.performance_comparison import (
    MetricChange,
    PerformanceComparison,
)


class TestProblemDetector:
    """Test suite for ProblemDetector."""

    @pytest.fixture
    def detector(self):
        """Create detector with default config."""
        return ProblemDetector()

    def create_comparison(
        self,
        agent_name: str = "test_agent",
        metric_changes: list = None,
        current_executions: int = 100,
        baseline_executions: int = 100,
    ) -> PerformanceComparison:
        """Helper to create PerformanceComparison for testing."""
        return PerformanceComparison(
            agent_name=agent_name,
            baseline_window="30 days ago to 7 days ago",
            current_window="last 7 days",
            baseline_executions=baseline_executions,
            current_executions=current_executions,
            metric_changes=metric_changes or [],
            overall_improvement=False,
            improvement_score=0.0,
        )

    def test_detect_quality_problem(self, detector):
        """Test detection of quality degradation."""
        # Create comparison with quality drop: 0.85 → 0.70 (-17.6%)
        comparison = self.create_comparison(
            metric_changes=[
                MetricChange(
                    metric_name="extraction_quality",
                    stat_name="mean",
                    baseline_value=0.85,
                    current_value=0.70,
                    absolute_change=-0.15,
                    relative_change=-0.176,
                    is_improvement=False
                )
            ]
        )

        problems = detector.detect_problems(comparison)

        assert len(problems) == 1
        assert problems[0].problem_type == ProblemType.QUALITY_LOW
        assert problems[0].severity == ProblemSeverity.MEDIUM
        assert problems[0].agent_name == "test_agent"
        assert problems[0].metric_name == "extraction_quality"
        assert problems[0].baseline_value == 0.85
        assert problems[0].current_value == 0.70
        assert abs(problems[0].degradation_pct + 0.176) < 0.001

    def test_detect_cost_problem(self, detector):
        """Test detection of cost increase."""
        # Cost increase: 0.50 → 0.75 (+50%)
        comparison = self.create_comparison(
            metric_changes=[
                MetricChange(
                    metric_name="cost_usd",
                    stat_name="mean",
                    baseline_value=0.50,
                    current_value=0.75,
                    absolute_change=0.25,
                    relative_change=0.50,
                    is_improvement=False
                )
            ]
        )

        problems = detector.detect_problems(comparison)

        assert len(problems) == 1
        assert problems[0].problem_type == ProblemType.COST_HIGH
        assert problems[0].severity == ProblemSeverity.CRITICAL
        assert problems[0].degradation_pct == 0.50

    def test_detect_speed_problem(self, detector):
        """Test detection of speed degradation."""
        # Duration increase: 10.0 → 18.0 seconds (+80%)
        comparison = self.create_comparison(
            metric_changes=[
                MetricChange(
                    metric_name="duration_seconds",
                    stat_name="mean",
                    baseline_value=10.0,
                    current_value=18.0,
                    absolute_change=8.0,
                    relative_change=0.80,
                    is_improvement=False
                )
            ]
        )

        problems = detector.detect_problems(comparison)

        assert len(problems) == 1
        assert problems[0].problem_type == ProblemType.SPEED_LOW
        assert problems[0].severity == ProblemSeverity.CRITICAL
        assert problems[0].degradation_pct == 0.80

    def test_no_problems_within_thresholds(self, detector):
        """Test no detection when changes are within thresholds."""
        comparison = self.create_comparison(
            metric_changes=[
                # Quality: -5% (below 10% threshold)
                MetricChange(
                    metric_name="extraction_quality",
                    stat_name="mean",
                    baseline_value=0.85,
                    current_value=0.8075,
                    absolute_change=-0.0425,
                    relative_change=-0.05,
                    is_improvement=False
                ),
                # Cost: +15% (below 30% threshold)
                MetricChange(
                    metric_name="cost_usd",
                    stat_name="mean",
                    baseline_value=0.60,
                    current_value=0.69,
                    absolute_change=0.09,
                    relative_change=0.15,
                    is_improvement=False
                ),
            ]
        )

        problems = detector.detect_problems(comparison)
        assert len(problems) == 0

    def test_insufficient_current_executions(self, detector):
        """Test error when insufficient current executions."""
        comparison = self.create_comparison(
            current_executions=30,  # Below default threshold of 50
            baseline_executions=100,
        )

        with pytest.raises(ProblemDetectionDataError, match="Insufficient current executions"):
            detector.detect_problems(comparison)

    def test_improvement_not_detected_as_problem(self, detector):
        """Test that improvements are not detected as problems."""
        comparison = self.create_comparison(
            metric_changes=[
                # Quality improved (+20%)
                MetricChange(
                    metric_name="extraction_quality",
                    stat_name="mean",
                    baseline_value=0.70,
                    current_value=0.84,
                    absolute_change=0.14,
                    relative_change=0.20,
                    is_improvement=True
                ),
                # Cost decreased (-40%)
                MetricChange(
                    metric_name="cost_usd",
                    stat_name="mean",
                    baseline_value=0.80,
                    current_value=0.48,
                    absolute_change=-0.32,
                    relative_change=-0.40,
                    is_improvement=True
                ),
            ]
        )

        problems = detector.detect_problems(comparison)
        assert len(problems) == 0


class TestProblemDetectionConfig:
    """Test suite for ProblemDetectionConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ProblemDetectionConfig()

        assert config.quality_relative_threshold == 0.10
        assert config.quality_absolute_threshold == 0.05
        assert config.cost_relative_threshold == 0.30
        assert config.speed_relative_threshold == 0.50
        assert config.min_executions_for_detection == 50

    def test_invalid_quality_threshold(self):
        """Test validation of quality threshold."""
        with pytest.raises(ValueError, match="quality_relative_threshold must be in"):
            ProblemDetectionConfig(quality_relative_threshold=1.5)
