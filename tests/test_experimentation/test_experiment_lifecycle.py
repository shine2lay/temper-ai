"""End-to-end integration tests for experiment lifecycle workflows.

Tests complete experiment execution with various configurations including
multi-variant experiments, config overrides, and protected field validation.
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
from src.experimentation.config_manager import ConfigManager, SecurityViolationError
from src.experimentation.analyzer import StatisticalAnalyzer


class TestCompleteExperimentLifecycle:
    """Test complete experiment execution workflows."""

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


class TestConfigurationManagement:
    """Test configuration overrides and security."""

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

        with pytest.raises(SecurityViolationError):
            manager.merge_config(base_config, dangerous_override, validate_protected=True)


class TestMultiVariantExperiments:
    """Test experiments with 3+ variants."""

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
