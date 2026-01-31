"""
Tests for statistical analysis engine.

Tests hypothesis testing, confidence intervals, guardrail checks, and winner determination.
"""

import pytest
import numpy as np
from src.experimentation.models import (
    Experiment,
    Variant,
    VariantAssignment,
    ExperimentStatus,
    AssignmentStrategyType,
    ConfigType,
    ExecutionStatus,
    RecommendationType,
)
from src.experimentation.analyzer import StatisticalAnalyzer


@pytest.fixture
def experiment():
    """Create test experiment."""
    return Experiment(
        id="exp-001",
        name="test_experiment",
        description="Test experiment",
        status=ExperimentStatus.RUNNING,
        assignment_strategy=AssignmentStrategyType.RANDOM,
        traffic_allocation={"control": 0.5, "variant_a": 0.5},
        primary_metric="duration_seconds",
        secondary_metrics=["cost_usd"],
        guardrail_metrics=[{"metric": "error_rate", "max_value": 0.05}],
        confidence_level=0.95,
        min_sample_size_per_variant=30,
    )


@pytest.fixture
def variants():
    """Create test variants."""
    return [
        Variant(
            id="var-control",
            experiment_id="exp-001",
            name="control",
            description="Control variant",
            is_control=True,
            config_type=ConfigType.AGENT,
            config_overrides={},
            allocated_traffic=0.5,
        ),
        Variant(
            id="var-a",
            experiment_id="exp-001",
            name="variant_a",
            description="Variant A",
            is_control=False,
            config_type=ConfigType.AGENT,
            config_overrides={"temperature": 0.9},
            allocated_traffic=0.5,
        ),
    ]


class TestStatisticalAnalyzer:
    """Test statistical analyzer."""

    def test_analyzer_initialization(self):
        """Test analyzer initialization."""
        analyzer = StatisticalAnalyzer(confidence_level=0.95)
        assert analyzer.confidence_level == 0.95

    def test_analyze_no_data(self, experiment, variants):
        """Test analysis with no completed executions."""
        analyzer = StatisticalAnalyzer()
        assignments = []

        result = analyzer.analyze_experiment(experiment, assignments, variants)

        assert result["sample_size"] == 0
        assert result["recommendation"] == RecommendationType.CONTINUE
        assert "reason" in result

    def test_analyze_insufficient_samples(self, experiment, variants):
        """Test analysis with insufficient sample size."""
        analyzer = StatisticalAnalyzer()

        # Create only 10 assignments (less than min_sample_size=30)
        assignments = []
        for i in range(10):
            variant_id = "var-control" if i < 5 else "var-a"
            assignment = VariantAssignment(
                id=f"asn-{i}",
                experiment_id="exp-001",
                variant_id=variant_id,
                workflow_execution_id=f"wf-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"duration_seconds": 50.0 + i}
            )
            assignments.append(assignment)

        result = analyzer.analyze_experiment(experiment, assignments, variants)

        assert result["recommendation"] == RecommendationType.CONTINUE
        assert "insufficient sample size" in result.get("reason", "").lower()

    def test_analyze_with_clear_winner(self, experiment, variants):
        """Test analysis with statistically significant difference."""
        analyzer = StatisticalAnalyzer()

        # Create assignments with clear difference:
        # Control: mean=50, variant_a: mean=30 (40% improvement)
        assignments = []

        # Control variant: 50 samples around mean=50
        for i in range(50):
            assignment = VariantAssignment(
                id=f"asn-control-{i}",
                experiment_id="exp-001",
                variant_id="var-control",
                workflow_execution_id=f"wf-control-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"duration_seconds": 50.0 + np.random.normal(0, 3)}
            )
            assignments.append(assignment)

        # Variant A: 50 samples around mean=30 (significantly better)
        for i in range(50):
            assignment = VariantAssignment(
                id=f"asn-a-{i}",
                experiment_id="exp-001",
                variant_id="var-a",
                workflow_execution_id=f"wf-a-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"duration_seconds": 30.0 + np.random.normal(0, 3)}
            )
            assignments.append(assignment)

        result = analyzer.analyze_experiment(experiment, assignments, variants)

        # Should detect significant difference
        assert result["sample_size"] == 100
        assert result["recommendation"] == RecommendationType.STOP_WINNER
        assert result["recommended_winner"] == "var-a"
        assert result["confidence"] > 0.95

    def test_analyze_no_difference(self, experiment, variants):
        """Test analysis with no significant difference."""
        analyzer = StatisticalAnalyzer()

        # Create assignments with same distribution
        assignments = []

        # Both variants: mean=50, std=5
        for i in range(100):
            variant_id = "var-control" if i < 50 else "var-a"
            assignment = VariantAssignment(
                id=f"asn-{i}",
                experiment_id="exp-001",
                variant_id=variant_id,
                workflow_execution_id=f"wf-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"duration_seconds": 50.0 + np.random.normal(0, 5)}
            )
            assignments.append(assignment)

        result = analyzer.analyze_experiment(experiment, assignments, variants)

        # Should not detect significant difference
        assert result["recommendation"] == RecommendationType.STOP_NO_DIFFERENCE
        assert result["recommended_winner"] is None

    def test_analyze_with_guardrail_violation(self, experiment, variants):
        """Test analysis with guardrail violation."""
        analyzer = StatisticalAnalyzer()

        # Create assignments where variant_a has high error rate
        assignments = []

        # Control variant: normal metrics
        for i in range(50):
            assignment = VariantAssignment(
                id=f"asn-control-{i}",
                experiment_id="exp-001",
                variant_id="var-control",
                workflow_execution_id=f"wf-control-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={
                    "duration_seconds": 50.0,
                    "error_rate": 0.02  # Within guardrail (< 0.05)
                }
            )
            assignments.append(assignment)

        # Variant A: guardrail violation
        for i in range(50):
            assignment = VariantAssignment(
                id=f"asn-a-{i}",
                experiment_id="exp-001",
                variant_id="var-a",
                workflow_execution_id=f"wf-a-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={
                    "duration_seconds": 30.0,  # Better performance
                    "error_rate": 0.10  # Violates guardrail (> 0.05)
                }
            )
            assignments.append(assignment)

        result = analyzer.analyze_experiment(experiment, assignments, variants)

        # Should detect guardrail violation
        assert result["recommendation"] == RecommendationType.STOP_GUARDRAIL_VIOLATION
        assert len(result["guardrail_violations"]) > 0
        assert result["guardrail_violations"][0]["variant"] == "var-a"


class TestVariantMetrics:
    """Test variant metrics calculation."""

    def test_calculate_basic_metrics(self, experiment, variants):
        """Test basic metric aggregation."""
        analyzer = StatisticalAnalyzer()

        # Create assignments with known values
        assignments = [
            VariantAssignment(
                id=f"asn-{i}",
                experiment_id="exp-001",
                variant_id="var-control",
                workflow_execution_id=f"wf-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"duration_seconds": float(value)}
            )
            for i, value in enumerate([10, 20, 30, 40, 50])
        ]

        variant_assignments = {"var-control": assignments}
        metrics = analyzer._calculate_variant_metrics(
            variant_assignments,
            "duration_seconds"
        )

        control_metrics = metrics["var-control"]
        assert control_metrics["count"] == 5
        assert control_metrics["mean"] == 30.0
        assert control_metrics["median"] == 30.0
        assert control_metrics["min"] == 10.0
        assert control_metrics["max"] == 50.0
        assert control_metrics["p50"] == 30.0

    def test_calculate_percentiles(self, experiment, variants):
        """Test percentile calculations."""
        analyzer = StatisticalAnalyzer()

        # Create 100 assignments with values 1-100
        assignments = [
            VariantAssignment(
                id=f"asn-{i}",
                experiment_id="exp-001",
                variant_id="var-control",
                workflow_execution_id=f"wf-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"duration_seconds": float(i + 1)}
            )
            for i in range(100)
        ]

        variant_assignments = {"var-control": assignments}
        metrics = analyzer._calculate_variant_metrics(
            variant_assignments,
            "duration_seconds"
        )

        control_metrics = metrics["var-control"]
        assert control_metrics["count"] == 100
        assert 50 <= control_metrics["p50"] <= 51
        assert 95 <= control_metrics["p95"] <= 96
        assert control_metrics["p99"] <= 100


class TestHypothesisTesting:
    """Test hypothesis testing functionality."""

    def test_t_test_significant_difference(self):
        """Test t-test with significant difference."""
        analyzer = StatisticalAnalyzer()

        control_values = [50.0] * 30  # Mean=50, no variance
        treatment_values = [30.0] * 30  # Mean=30, no variance

        result = analyzer._t_test(control_values, treatment_values, 0.95)

        assert result["test"] == "t-test"
        assert result["statistically_significant"] is True
        assert result["p_value"] < 0.05
        assert result["control_mean"] == 50.0
        assert result["treatment_mean"] == 30.0
        assert abs(result["improvement"] - (-0.4)) < 0.01  # 40% improvement

    def test_t_test_no_difference(self):
        """Test t-test with no difference."""
        analyzer = StatisticalAnalyzer()

        # Same distribution
        np.random.seed(42)
        control_values = list(50.0 + np.random.normal(0, 5, 30))
        treatment_values = list(50.0 + np.random.normal(0, 5, 30))

        result = analyzer._t_test(control_values, treatment_values, 0.95)

        assert result["test"] == "t-test"
        # Should not be significant (same distribution)
        # Note: There's a small chance of Type I error, but very unlikely with seed=42
        assert result["p_value"] > 0.01  # Much higher than 0.05

    def test_confidence_interval(self):
        """Test confidence interval calculation."""
        analyzer = StatisticalAnalyzer()

        control_values = [50.0] * 30
        treatment_values = [40.0] * 30

        ci_low, ci_high = analyzer._confidence_interval(
            control_values,
            treatment_values,
            0.95
        )

        # Difference should be 10 (50-40)
        # CI should be tight since no variance (may be exactly 10 with zero variance)
        assert ci_low <= 10
        assert ci_high >= 10
        assert ci_high - ci_low < 5  # Tight interval


class TestGuardrailChecks:
    """Test guardrail checking functionality."""

    def test_guardrail_no_violations(self):
        """Test guardrail check with no violations."""
        analyzer = StatisticalAnalyzer()

        variant_metrics = {
            "var-control": {"error_rate": 0.02},
            "var-a": {"error_rate": 0.03}
        }
        guardrail_metrics = [{"metric": "error_rate", "max_value": 0.05}]

        violations = analyzer._check_guardrails(variant_metrics, guardrail_metrics)

        assert len(violations) == 0

    def test_guardrail_with_violation(self):
        """Test guardrail check with violation."""
        analyzer = StatisticalAnalyzer()

        variant_metrics = {
            "var-control": {"error_rate": 0.02},
            "var-a": {"error_rate": 0.10}  # Exceeds threshold
        }
        guardrail_metrics = [{"metric": "error_rate", "max_value": 0.05}]

        violations = analyzer._check_guardrails(variant_metrics, guardrail_metrics)

        assert len(violations) == 1
        assert violations[0]["variant"] == "var-a"
        assert violations[0]["metric"] == "error_rate"
        assert violations[0]["value"] == 0.10
        assert violations[0]["threshold"] == 0.05

    def test_guardrail_multiple_metrics(self):
        """Test guardrail with multiple metrics."""
        analyzer = StatisticalAnalyzer()

        variant_metrics = {
            "var-control": {"error_rate": 0.02, "cost_usd": 0.10},
            "var-a": {"error_rate": 0.10, "cost_usd": 0.15}
        }
        guardrail_metrics = [
            {"metric": "error_rate", "max_value": 0.05},
            {"metric": "cost_usd", "max_value": 0.12}
        ]

        violations = analyzer._check_guardrails(variant_metrics, guardrail_metrics)

        # Both metrics violated on var-a
        assert len(violations) == 2
        violation_metrics = {v["metric"] for v in violations}
        assert "error_rate" in violation_metrics
        assert "cost_usd" in violation_metrics


class TestRecommendationGeneration:
    """Test recommendation generation logic."""

    def test_recommendation_guardrail_priority(self):
        """Test that guardrail violations take priority."""
        analyzer = StatisticalAnalyzer()

        statistical_tests = {
            "control_vs_variant_a": {
                "statistically_significant": True,
                "improvement": 0.5,
                "p_value": 0.001
            }
        }
        guardrail_violations = [
            {"variant": "var-a", "metric": "error_rate", "value": 0.10}
        ]

        recommendation, winner, confidence = analyzer._generate_recommendation(
            statistical_tests,
            guardrail_violations,
            0.95
        )

        # Guardrail violation should override statistical winner
        assert recommendation == RecommendationType.STOP_GUARDRAIL_VIOLATION
        assert winner is None
        assert confidence == 1.0

    def test_recommendation_clear_winner(self):
        """Test recommendation with clear winner."""
        analyzer = StatisticalAnalyzer()

        statistical_tests = {
            "control_vs_variant_a": {
                "statistically_significant": True,
                "improvement": 0.3,
                "p_value": 0.01
            }
        }
        guardrail_violations = []

        recommendation, winner, confidence = analyzer._generate_recommendation(
            statistical_tests,
            guardrail_violations,
            0.95
        )

        assert recommendation == RecommendationType.STOP_WINNER
        assert winner == "variant_a"
        assert confidence > 0.95

    def test_recommendation_no_difference(self):
        """Test recommendation with no significant difference."""
        analyzer = StatisticalAnalyzer()

        statistical_tests = {
            "control_vs_variant_a": {
                "statistically_significant": False,
                "improvement": 0.02,
                "p_value": 0.50
            }
        }
        guardrail_violations = []

        recommendation, winner, confidence = analyzer._generate_recommendation(
            statistical_tests,
            guardrail_violations,
            0.95
        )

        assert recommendation == RecommendationType.STOP_NO_DIFFERENCE
        assert winner is None


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_analyze_pending_executions_ignored(self, experiment, variants):
        """Test that pending executions are ignored in analysis."""
        analyzer = StatisticalAnalyzer()

        assignments = [
            VariantAssignment(
                id="asn-pending",
                experiment_id="exp-001",
                variant_id="var-control",
                workflow_execution_id="wf-pending",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.PENDING,  # Should be ignored
                metrics={"duration_seconds": 50.0}
            ),
            VariantAssignment(
                id="asn-running",
                experiment_id="exp-001",
                variant_id="var-control",
                workflow_execution_id="wf-running",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.RUNNING,  # Should be ignored
                metrics={"duration_seconds": 50.0}
            ),
        ]

        result = analyzer.analyze_experiment(experiment, assignments, variants)

        # No completed executions, should return inconclusive
        assert result["sample_size"] == 0

    def test_analyze_missing_metrics(self, experiment, variants):
        """Test analysis with missing metrics."""
        analyzer = StatisticalAnalyzer()

        assignments = [
            VariantAssignment(
                id="asn-1",
                experiment_id="exp-001",
                variant_id="var-control",
                workflow_execution_id="wf-1",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics=None  # Missing metrics
            ),
        ]

        result = analyzer.analyze_experiment(experiment, assignments, variants)

        # Should handle gracefully
        assert result["sample_size"] == 0
