"""
Tests for experimentation database models.
"""

from src.experimentation.models import (
    AssignmentStrategyType,
    ConfigType,
    ExecutionStatus,
    Experiment,
    ExperimentResult,
    ExperimentStatus,
    RecommendationType,
    Variant,
    VariantAssignment,
)


class TestExperiment:
    """Test Experiment model."""

    def test_create_experiment(self):
        """Test creating an experiment."""
        experiment = Experiment(
            id="exp-001",
            name="test_experiment",
            description="Test experiment description",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 0.5, "variant_a": 0.5},
            primary_metric="duration_seconds",
            secondary_metrics=["cost_usd", "tokens"],
            confidence_level=0.95,
            min_sample_size_per_variant=100,
        )

        assert experiment.id == "exp-001"
        assert experiment.name == "test_experiment"
        assert experiment.status == ExperimentStatus.DRAFT
        assert experiment.assignment_strategy == AssignmentStrategyType.RANDOM
        assert experiment.traffic_allocation == {"control": 0.5, "variant_a": 0.5}
        assert experiment.primary_metric == "duration_seconds"
        assert len(experiment.secondary_metrics) == 2


class TestVariant:
    """Test Variant model."""

    def test_create_variant(self):
        """Test creating a variant."""
        variant = Variant(
            id="var-001",
            experiment_id="exp-001",
            name="high_temperature",
            description="Temperature set to 0.9",
            is_control=False,
            config_type=ConfigType.AGENT,
            config_overrides={"inference": {"temperature": 0.9}},
            allocated_traffic=0.5,
        )

        assert variant.id == "var-001"
        assert variant.experiment_id == "exp-001"
        assert variant.name == "high_temperature"
        assert variant.is_control is False
        assert variant.config_type == ConfigType.AGENT
        assert variant.allocated_traffic == 0.5
        assert variant.config_overrides["inference"]["temperature"] == 0.9


class TestVariantAssignment:
    """Test VariantAssignment model."""

    def test_create_assignment(self):
        """Test creating a variant assignment."""
        assignment = VariantAssignment(
            id="asn-001",
            experiment_id="exp-001",
            variant_id="var-001",
            workflow_execution_id="wf-123",
            assignment_strategy=AssignmentStrategyType.HASH,
            execution_status=ExecutionStatus.PENDING,
        )

        assert assignment.id == "asn-001"
        assert assignment.experiment_id == "exp-001"
        assert assignment.variant_id == "var-001"
        assert assignment.workflow_execution_id == "wf-123"
        assert assignment.assignment_strategy == AssignmentStrategyType.HASH
        assert assignment.execution_status == ExecutionStatus.PENDING


class TestExperimentResult:
    """Test ExperimentResult model."""

    def test_create_result(self):
        """Test creating an experiment result."""
        result = ExperimentResult(
            id="res-001",
            experiment_id="exp-001",
            sample_size=250,
            variant_metrics={
                "control": {"mean": 45.2, "std": 5.1, "count": 125},
                "variant_a": {"mean": 38.7, "std": 4.8, "count": 125},
            },
            statistical_tests={
                "control_vs_variant_a": {
                    "p_value": 0.003,
                    "significant": True,
                    "improvement": 0.144,
                }
            },
            guardrail_violations=[],
            recommendation=RecommendationType.STOP_WINNER,
            recommended_winner="variant_a",
            confidence=0.98,
        )

        assert result.id == "res-001"
        assert result.experiment_id == "exp-001"
        assert result.sample_size == 250
        assert result.recommendation == RecommendationType.STOP_WINNER
        assert result.recommended_winner == "variant_a"
        assert result.confidence == 0.98
