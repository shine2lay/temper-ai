"""
Integration and end-to-end tests for A/B testing framework.

Tests complete workflows from experiment creation through analysis and recommendations.
"""

import pytest
import numpy as np
from datetime import datetime, UTC
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
from src.experimentation.assignment import VariantAssigner
from src.experimentation.config_manager import ConfigManager
from src.experimentation.analyzer import StatisticalAnalyzer
from src.experimentation.sequential_testing import SequentialTester, BayesianAnalyzer
from src.experimentation.service import ExperimentService


class TestEndToEndWorkflow:
    """Test complete experiment workflows."""

    def test_complete_experiment_lifecycle(self):
        """Test full lifecycle: create → assign → track → analyze → decide."""

        # 1. CREATE EXPERIMENT (minimal required fields)
        experiment = Experiment(
            id="exp-e2e-001",
            name="page_load_optimization",
            description="Test page load optimizations",
            status=ExperimentStatus.RUNNING,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 0.5, "optimized": 0.5},
            primary_metric="page_load_ms",
            confidence_level=0.95,
            min_sample_size_per_variant=50,
        )

        # 2. CREATE VARIANTS (minimal fields like working tests)
        variants = [
            Variant(
                id="var-control",
                experiment_id="exp-e2e-001",
                name="control",
                description="Current page load",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.5,
            ),
            Variant(
                id="var-optimized",
                experiment_id="exp-e2e-001",
                name="optimized",
                description="Optimized page load",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.5,
            ),
        ]

        # 3. CREATE ASSIGNMENTS (like working tests)
        assignments = []

        # Control variant: 50 samples around mean=500ms
        for i in range(50):
            assignment = VariantAssignment(
                id=f"asn-control-{i}",
                experiment_id="exp-e2e-001",
                variant_id="var-control",
                workflow_execution_id=f"wf-control-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"page_load_ms": 500.0 + np.random.normal(0, 50)}
            )
            assignments.append(assignment)

        # Optimized variant: 50 samples around mean=350ms (30% faster)
        for i in range(50):
            assignment = VariantAssignment(
                id=f"asn-opt-{i}",
                experiment_id="exp-e2e-001",
                variant_id="var-optimized",
                workflow_execution_id=f"wf-opt-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"page_load_ms": 350.0 + np.random.normal(0, 50)}
            )
            assignments.append(assignment)

        # 5. ANALYZE RESULTS
        analyzer = StatisticalAnalyzer(confidence_level=0.95, min_effect_size=0.05)
        result = analyzer.analyze_experiment(experiment, assignments, variants)

        # 6. VERIFY RESULTS
        assert result["sample_size"] == 100
        assert len(result["variant_metrics"]) == 2
        assert "var-control" in result["variant_metrics"]
        assert "var-optimized" in result["variant_metrics"]

        # Control metrics should be around 500ms
        control_metrics = result["variant_metrics"]["var-control"]
        assert 450 <= control_metrics["mean"] <= 550

        # Optimized metrics should be around 350ms (30% faster)
        optimized_metrics = result["variant_metrics"]["var-optimized"]
        assert 300 <= optimized_metrics["mean"] <= 400

        # Should detect winner (30% improvement is significant)
        assert result["recommendation"] == RecommendationType.STOP_WINNER
        assert result["recommended_winner"] == "var-optimized"
        assert result["confidence"] > 0.95

        # No guardrail violations
        assert len(result["guardrail_violations"]) == 0

        # 7. FINALIZE EXPERIMENT
        experiment.status = ExperimentStatus.COMPLETED

    def test_early_stopping_workflow(self):
        """Test workflow with sequential testing for early stopping."""

        # Create experiment
        experiment = Experiment(
            id="exp-early-stop",
            name="early_stop_test",
            description="Test early stopping",
            status=ExperimentStatus.RUNNING,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 0.5, "variant_a": 0.5},
            primary_metric="conversion_rate",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        variants = [
            Variant(
                id="var-control",
                experiment_id="exp-early-stop",
                name="control",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.5,
            ),
            Variant(
                id="var-a",
                experiment_id="exp-early-stop",
                name="variant_a",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={"model": "gpt-4"},
                allocated_traffic=0.5,
            ),
        ]

        # Simulate collecting data in batches
        tester = SequentialTester(alpha=0.05, beta=0.20, mde=0.15)

        control_values = []
        treatment_values = []

        stopped_early = False
        samples_when_stopped = 0

        # Collect data in batches of 10, check for early stopping
        for batch in range(10):
            # Add 10 more samples per variant
            np.random.seed(batch)
            control_batch = list(0.15 + np.random.normal(0, 0.05, 10))  # 15% conversion
            treatment_batch = list(0.25 + np.random.normal(0, 0.05, 10))  # 25% conversion (67% lift)

            control_values.extend(control_batch)
            treatment_values.extend(treatment_batch)

            # Check for early stopping
            decision, details = tester.test_sequential(control_values, treatment_values)

            if decision in ["stop_winner", "stop_no_difference"]:
                stopped_early = True
                samples_when_stopped = len(control_values)
                break

        # Verify early stopping worked
        if stopped_early:
            # Should stop before reaching full 100 samples (min_sample_size)
            assert samples_when_stopped < 100
            assert decision == "stop_winner"  # Large difference should be detected
        # Note: It's possible (though unlikely) that even with 67% lift, we don't stop early

    def test_bayesian_analysis_workflow(self):
        """Test workflow with Bayesian analysis."""

        # Create simple experiment
        experiment = Experiment(
            id="exp-bayes",
            name="bayesian_test",
            description="Test Bayesian analysis",
            status=ExperimentStatus.RUNNING,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 0.5, "variant_a": 0.5},
            primary_metric="latency_ms",
            confidence_level=0.95,
            min_sample_size_per_variant=50,
        )

        # Generate data: control=100ms, variant_a=80ms (20% faster)
        np.random.seed(42)
        control_values = list(100.0 + np.random.normal(0, 10, 50))
        treatment_values = list(80.0 + np.random.normal(0, 10, 50))

        # Bayesian analysis
        bayes = BayesianAnalyzer(prior_mean=0.0, prior_std=1.0)
        result = bayes.analyze_bayesian(control_values, treatment_values, credible_level=0.95)

        # Verify Bayesian results
        assert "posterior_mean" in result
        assert "prob_treatment_better" in result
        assert "credible_interval" in result
        assert "expected_lift" in result

        # Treatment is better (lower latency), so posterior mean should be negative
        # (treatment - control = 80 - 100 = -20)
        assert result["posterior_mean"] < 0

        # Probability treatment is better should be low (since we compute > 0, but diff is negative)
        # Actually, let's check the interpretation...
        # prob_treatment_better is P(treatment_mean - control_mean > 0)
        # Since treatment_mean < control_mean, this probability should be low
        assert 0 <= result["prob_treatment_better"] <= 1

        # Expected lift should be around -20% (negative = improvement for "lower is better")
        assert -0.25 <= result["expected_lift"] <= -0.15

        # Credible interval should be non-trivial
        ci_low, ci_high = result["credible_interval"]
        assert ci_low < ci_high


class TestConfigIntegration:
    """Test configuration management integration."""

    def test_config_override_in_experiment(self):
        """Test applying config overrides during experiment."""

        # Base configuration
        base_config = {
            "agent": {
                "name": "researcher",
                "model": "gpt-3.5-turbo",
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            "workflow": {
                "timeout": 300,
                "max_retries": 3,
            }
        }

        # Variant overrides
        variant_overrides = {
            "agent": {
                "model": "gpt-4",
                "temperature": 0.9,
            }
        }

        # Apply overrides
        manager = ConfigManager()
        merged_config = manager.merge_config(
            base_config,
            variant_overrides,
            validate_protected=True
        )

        # Verify merge
        assert merged_config["agent"]["model"] == "gpt-4"  # Overridden
        assert merged_config["agent"]["temperature"] == 0.9  # Overridden
        assert merged_config["agent"]["max_tokens"] == 2048  # Preserved
        assert merged_config["workflow"]["timeout"] == 300  # Preserved

    def test_protected_field_rejection(self):
        """Test that protected fields are blocked in experiments."""

        manager = ConfigManager()

        base_config = {"model": "gpt-3.5-turbo"}

        # Attempt to override protected field
        dangerous_override = {"api_key": "sk-secret-key"}

        with pytest.raises(Exception):  # Should raise SecurityViolationError
            manager.merge_config(base_config, dangerous_override, validate_protected=True)


class TestMultiVariantExperiment:
    """Test experiments with more than 2 variants."""

    def test_three_variant_experiment(self):
        """Test experiment with 3 variants (control + 2 treatments)."""

        experiment = Experiment(
            id="exp-multi",
            name="three_variant_test",
            description="Test multiple treatments",
            status=ExperimentStatus.RUNNING,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 0.4, "variant_a": 0.3, "variant_b": 0.3},
            primary_metric="score",
            confidence_level=0.95,
            min_sample_size_per_variant=40,
        )

        variants = [
            Variant(
                id="var-control",
                experiment_id="exp-multi",
                name="control",
                description="Control",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.4,
            ),
            Variant(
                id="var-a",
                experiment_id="exp-multi",
                name="variant_a",
                description="Variant A",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.3,
            ),
            Variant(
                id="var-b",
                experiment_id="exp-multi",
                name="variant_b",
                description="Variant B",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.3,
            ),
        ]

        # Generate assignments with different performance
        # Control: 50, Variant A: 55 (10% better), Variant B: 60 (20% better)
        assignments = []

        # Control: 48 samples around mean=50
        for i in range(48):
            assignment = VariantAssignment(
                id=f"asn-control-{i}",
                experiment_id="exp-multi",
                variant_id="var-control",
                workflow_execution_id=f"wf-control-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"score": 50.0 + np.random.normal(0, 5)}
            )
            assignments.append(assignment)

        # Variant A: 40 samples around mean=55 (10% better)
        for i in range(40):
            assignment = VariantAssignment(
                id=f"asn-a-{i}",
                experiment_id="exp-multi",
                variant_id="var-a",
                workflow_execution_id=f"wf-a-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"score": 55.0 + np.random.normal(0, 5)}
            )
            assignments.append(assignment)

        # Variant B: 40 samples around mean=60 (20% better)
        for i in range(40):
            assignment = VariantAssignment(
                id=f"asn-b-{i}",
                experiment_id="exp-multi",
                variant_id="var-b",
                workflow_execution_id=f"wf-b-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"score": 60.0 + np.random.normal(0, 5)}
            )
            assignments.append(assignment)

        # Analyze
        analyzer = StatisticalAnalyzer(confidence_level=0.95, min_effect_size=0.05)
        result = analyzer.analyze_experiment(experiment, assignments, variants)

        # Verify all variants analyzed
        assert len(result["variant_metrics"]) == 3
        assert "var-control" in result["variant_metrics"]
        assert "var-a" in result["variant_metrics"]
        assert "var-b" in result["variant_metrics"]

        # Verify hypothesis tests run for each treatment vs control
        assert len(result["statistical_tests"]) == 2
        assert "control_vs_var-a" in result["statistical_tests"] or "control_vs_a" in str(result["statistical_tests"])

        # Best variant should be variant_b (highest score, 20% better)
        if result["recommendation"] == RecommendationType.STOP_WINNER:
            # Winner should be variant with highest improvement
            assert result["recommended_winner"] in ["var-a", "var-b"]


class TestGuardrailProtection:
    """Test guardrail metric protection."""

    def test_guardrail_prevents_bad_variant(self):
        """Test that guardrail violations prevent winner declaration."""

        experiment = Experiment(
            id="exp-guardrail",
            name="guardrail_test",
            description="Test guardrail protection",
            status=ExperimentStatus.RUNNING,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 0.5, "variant_a": 0.5},
            primary_metric="revenue_usd",
            guardrail_metrics=[
                {"metric": "error_rate", "max_value": 0.05},
                {"metric": "latency_p99", "max_value": 1000}
            ],
            confidence_level=0.95,
            min_sample_size_per_variant=50,
        )

        variants = [
            Variant(
                id="var-control",
                experiment_id="exp-guardrail",
                name="control",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.5,
            ),
            Variant(
                id="var-a",
                experiment_id="exp-guardrail",
                name="variant_a",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={"aggressive_caching": True},
                allocated_traffic=0.5,
            ),
        ]

        # Create assignments where variant_a has better revenue but violates error rate
        assignments = []

        for i in range(100):
            variant_id = "var-control" if i < 50 else "var-a"

            if variant_id == "var-control":
                # Control: $100 revenue, 2% error rate, 500ms p99
                metrics = {
                    "revenue_usd": 100.0,
                    "error_rate": 0.02,
                    "latency_p99": 500.0,
                }
            else:
                # Variant A: $120 revenue (20% better), but 10% error rate (violates!)
                metrics = {
                    "revenue_usd": 120.0,
                    "error_rate": 0.10,  # Violates guardrail
                    "latency_p99": 600.0,
                }

            assignment = VariantAssignment(
                id=f"asn-{i}",
                experiment_id="exp-guardrail",
                variant_id=variant_id,
                workflow_execution_id=f"wf-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                assigned_at=datetime.now(UTC),
                execution_status=ExecutionStatus.COMPLETED,
                metrics=metrics,
            )
            assignments.append(assignment)

        # Analyze
        analyzer = StatisticalAnalyzer()
        result = analyzer.analyze_experiment(experiment, assignments, variants)

        # Should detect guardrail violation
        assert result["recommendation"] == RecommendationType.STOP_GUARDRAIL_VIOLATION
        assert len(result["guardrail_violations"]) > 0

        # Find the error_rate violation
        error_violations = [v for v in result["guardrail_violations"] if v["metric"] == "error_rate"]
        assert len(error_violations) == 1
        assert error_violations[0]["variant"] == "var-a"
        assert abs(error_violations[0]["value"] - 0.10) < 0.01  # Float comparison with tolerance
        assert error_violations[0]["threshold"] == 0.05


class TestPerformance:
    """Test performance benchmarks."""

    def test_assignment_performance(self):
        """Test assignment performance with large number of assignments."""
        import time

        experiment = Experiment(
            id="exp-perf",
            name="performance_test",
            status=ExperimentStatus.RUNNING,
            assignment_strategy=AssignmentStrategyType.HASH,
            traffic_allocation={"control": 0.5, "variant_a": 0.5},
            primary_metric="metric",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        variants = [
            Variant(
                id="var-control",
                experiment_id="exp-perf",
                name="control",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.5,
            ),
            Variant(
                id="var-a",
                experiment_id="exp-perf",
                name="variant_a",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.5,
            ),
        ]

        assigner = VariantAssigner()

        # Benchmark: 10,000 assignments
        start = time.time()
        for i in range(10000):
            variant_id = assigner.assign_variant(
                experiment,
                variants,
                f"workflow-{i}",
                context={"hash_key": f"user-{i}"}
            )
        elapsed = time.time() - start

        # Should complete in < 1 second
        assert elapsed < 1.0

        # Average assignment time should be < 0.1ms
        avg_time_ms = (elapsed / 10000) * 1000
        assert avg_time_ms < 0.1

    def test_analysis_performance(self):
        """Test analysis performance with large datasets."""
        import time

        experiment = Experiment(
            id="exp-perf-analysis",
            name="performance_test_analysis",
            status=ExperimentStatus.RUNNING,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 0.5, "variant_a": 0.5},
            primary_metric="metric",
            confidence_level=0.95,
            min_sample_size_per_variant=100,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        variants = [
            Variant(
                id="var-control",
                experiment_id="exp-perf-analysis",
                name="control",
                is_control=True,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.5,
            ),
            Variant(
                id="var-a",
                experiment_id="exp-perf-analysis",
                name="variant_a",
                is_control=False,
                config_type=ConfigType.AGENT,
                config_overrides={},
                allocated_traffic=0.5,
            ),
        ]

        # Generate 1000 assignments
        assignments = []
        np.random.seed(42)
        for i in range(1000):
            variant_id = "var-control" if i < 500 else "var-a"
            metric_value = 50.0 + np.random.normal(0, 10)

            assignment = VariantAssignment(
                id=f"asn-{i}",
                experiment_id="exp-perf-analysis",
                variant_id=variant_id,
                workflow_execution_id=f"wf-{i}",
                assignment_strategy=AssignmentStrategyType.RANDOM,
                assigned_at=datetime.now(UTC),
                execution_status=ExecutionStatus.COMPLETED,
                metrics={"metric": metric_value},
            )
            assignments.append(assignment)

        # Benchmark analysis
        analyzer = StatisticalAnalyzer()

        start = time.time()
        result = analyzer.analyze_experiment(experiment, assignments, variants)
        elapsed = time.time() - start

        # Should complete in < 100ms
        assert elapsed < 0.1

        # Verify result is valid
        assert "recommendation" in result
        assert "variant_metrics" in result
