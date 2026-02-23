"""
Comprehensive tests for experimentation database models.

Covers:
- Experiment model creation, defaults, validation, enums
- Variant model creation, defaults, validation
- VariantAssignment model creation, defaults
- ExperimentResult model creation
- Model relationships
- Enum types
"""

from datetime import UTC, datetime

from temper_ai.experimentation.models import (
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


class TestEnums:
    """Test enum types."""

    def test_experiment_status_enum(self):
        """Test ExperimentStatus enum values."""
        assert ExperimentStatus.DRAFT == "draft"
        assert ExperimentStatus.RUNNING == "running"
        assert ExperimentStatus.PAUSED == "paused"
        assert ExperimentStatus.STOPPED == "stopped"
        assert ExperimentStatus.COMPLETED == "completed"

    def test_assignment_strategy_enum(self):
        """Test AssignmentStrategyType enum values."""
        assert AssignmentStrategyType.RANDOM == "random"
        assert AssignmentStrategyType.HASH == "hash"
        assert AssignmentStrategyType.STRATIFIED == "stratified"
        assert AssignmentStrategyType.BANDIT == "bandit"

    def test_config_type_enum(self):
        """Test ConfigType enum values."""
        assert ConfigType.AGENT == "agent"
        assert ConfigType.STAGE == "stage"
        assert ConfigType.WORKFLOW == "workflow"
        assert ConfigType.PROMPT == "prompt"

    def test_execution_status_enum(self):
        """Test ExecutionStatus enum values."""
        assert ExecutionStatus.PENDING == "pending"
        assert ExecutionStatus.RUNNING == "running"
        assert ExecutionStatus.COMPLETED == "completed"
        assert ExecutionStatus.FAILED == "failed"

    def test_recommendation_type_enum(self):
        """Test RecommendationType enum values."""
        assert RecommendationType.CONTINUE == "continue"
        assert RecommendationType.STOP_WINNER == "stop_winner"
        assert RecommendationType.STOP_NO_DIFFERENCE == "stop_no_difference"
        assert RecommendationType.STOP_GUARDRAIL_VIOLATION == "stop_guardrail_violation"


class TestExperiment:
    """Test Experiment model."""

    def test_create_experiment_minimal(self):
        """Test creating an experiment with minimal required fields."""
        experiment = Experiment(
            id="exp-001",
            name="test_experiment",
            description="Test experiment description",
            traffic_allocation={"control": 0.5, "variant_a": 0.5},
            primary_metric="duration_seconds",
        )

        assert experiment.id == "exp-001"
        assert experiment.name == "test_experiment"
        assert experiment.description == "Test experiment description"
        assert experiment.traffic_allocation == {"control": 0.5, "variant_a": 0.5}
        assert experiment.primary_metric == "duration_seconds"

    def test_create_experiment_full(self):
        """Test creating an experiment with all fields."""
        experiment = Experiment(
            id="exp-001",
            name="test_experiment",
            description="Test experiment description",
            status=ExperimentStatus.DRAFT,
            assignment_strategy=AssignmentStrategyType.RANDOM,
            traffic_allocation={"control": 0.5, "variant_a": 0.5},
            primary_metric="duration_seconds",
            secondary_metrics=["cost_usd", "tokens"],
            guardrail_metrics=[{"metric": "error_rate", "max_value": 0.05}],
            confidence_level=0.95,
            min_sample_size_per_variant=100,
            tags=["important", "production"],
            created_by="user-123",
        )

        assert experiment.id == "exp-001"
        assert experiment.name == "test_experiment"
        assert experiment.status == ExperimentStatus.DRAFT
        assert experiment.assignment_strategy == AssignmentStrategyType.RANDOM
        assert experiment.traffic_allocation == {"control": 0.5, "variant_a": 0.5}
        assert experiment.primary_metric == "duration_seconds"
        assert len(experiment.secondary_metrics) == 2
        assert len(experiment.guardrail_metrics) == 1
        assert experiment.confidence_level == 0.95
        assert experiment.min_sample_size_per_variant == 100
        assert len(experiment.tags) == 2
        assert experiment.created_by == "user-123"

    def test_experiment_defaults(self):
        """Test default values for experiment fields."""
        experiment = Experiment(
            id="exp-001",
            name="test_experiment",
            description="Test",
            traffic_allocation={"control": 1.0},
            primary_metric="metric",
        )

        # Check defaults
        assert experiment.status == ExperimentStatus.DRAFT
        assert experiment.assignment_strategy == AssignmentStrategyType.RANDOM
        assert experiment.secondary_metrics == []
        assert experiment.guardrail_metrics is None
        assert experiment.confidence_level == 0.95  # PROB_NEAR_CERTAIN
        assert experiment.min_sample_size_per_variant == 100  # THRESHOLD_LARGE_COUNT
        assert experiment.winner_variant_id is None
        assert experiment.winning_confidence is None
        assert experiment.total_executions == 0
        assert experiment.tags == []
        assert experiment.created_by is None
        assert experiment.extra_metadata is None

    def test_experiment_timestamps(self):
        """Test experiment timestamp fields."""
        experiment = Experiment(
            id="exp-001",
            name="test_experiment",
            description="Test",
            traffic_allocation={"control": 1.0},
            primary_metric="metric",
        )

        # created_at should be set automatically
        assert isinstance(experiment.created_at, datetime)
        assert experiment.started_at is None
        assert experiment.stopped_at is None
        assert isinstance(experiment.updated_at, datetime)

    def test_experiment_winner_fields(self):
        """Test experiment winner tracking fields."""
        experiment = Experiment(
            id="exp-001",
            name="test_experiment",
            description="Test",
            traffic_allocation={"control": 0.5, "variant_a": 0.5},
            primary_metric="metric",
            winner_variant_id="variant_a",
            winning_confidence=0.98,
        )

        assert experiment.winner_variant_id == "variant_a"
        assert experiment.winning_confidence == 0.98

    def test_experiment_metadata(self):
        """Test experiment metadata fields."""
        extra = {"team": "data-science", "priority": "high"}
        experiment = Experiment(
            id="exp-001",
            name="test_experiment",
            description="Test",
            traffic_allocation={"control": 1.0},
            primary_metric="metric",
            extra_metadata=extra,
        )

        assert experiment.extra_metadata == extra
        assert experiment.extra_metadata["team"] == "data-science"


class TestVariant:
    """Test Variant model."""

    def test_create_variant_minimal(self):
        """Test creating a variant with minimal fields."""
        variant = Variant(
            id="var-001",
            experiment_id="exp-001",
            name="control",
            description="Control variant",
            config_overrides={},
        )

        assert variant.id == "var-001"
        assert variant.experiment_id == "exp-001"
        assert variant.name == "control"
        assert variant.description == "Control variant"
        assert variant.config_overrides == {}

    def test_create_variant_full(self):
        """Test creating a variant with all fields."""
        variant = Variant(
            id="var-001",
            experiment_id="exp-001",
            name="high_temperature",
            description="Temperature set to 0.9",
            is_control=False,
            config_type=ConfigType.AGENT,
            config_overrides={"inference": {"temperature": 0.9}},
            allocated_traffic=0.5,
            actual_traffic=0.48,
            total_executions=100,
            successful_executions=95,
            failed_executions=5,
        )

        assert variant.id == "var-001"
        assert variant.experiment_id == "exp-001"
        assert variant.name == "high_temperature"
        assert variant.is_control is False
        assert variant.config_type == ConfigType.AGENT
        assert variant.allocated_traffic == 0.5
        assert variant.actual_traffic == 0.48
        assert variant.config_overrides["inference"]["temperature"] == 0.9
        assert variant.total_executions == 100
        assert variant.successful_executions == 95
        assert variant.failed_executions == 5

    def test_variant_defaults(self):
        """Test default values for variant fields."""
        variant = Variant(
            id="var-001",
            experiment_id="exp-001",
            name="test",
            description="Test variant",
            config_overrides={},
        )

        assert variant.is_control is False
        assert variant.config_type == ConfigType.AGENT
        assert variant.allocated_traffic == 0.5  # FRACTION_HALF
        assert variant.actual_traffic == 0.0
        assert variant.total_executions == 0
        assert variant.successful_executions == 0
        assert variant.failed_executions == 0
        assert variant.extra_metadata is None

    def test_variant_timestamps(self):
        """Test variant timestamp fields."""
        variant = Variant(
            id="var-001",
            experiment_id="exp-001",
            name="test",
            description="Test",
            config_overrides={},
        )

        assert isinstance(variant.created_at, datetime)

    def test_variant_config_types(self):
        """Test different config types."""
        variant_agent = Variant(
            id="var-001",
            experiment_id="exp-001",
            name="agent_variant",
            description="Agent config variant",
            config_type=ConfigType.AGENT,
            config_overrides={"model": "gpt-4"},
        )
        assert variant_agent.config_type == ConfigType.AGENT

        variant_stage = Variant(
            id="var-002",
            experiment_id="exp-001",
            name="stage_variant",
            description="Stage config variant",
            config_type=ConfigType.STAGE,
            config_overrides={"timeout": 60},
        )
        assert variant_stage.config_type == ConfigType.STAGE


class TestVariantAssignment:
    """Test VariantAssignment model."""

    def test_create_assignment_minimal(self):
        """Test creating an assignment with minimal fields."""
        assignment = VariantAssignment(
            id="asn-001",
            experiment_id="exp-001",
            variant_id="var-001",
            workflow_execution_id="wf-123",
            assignment_strategy=AssignmentStrategyType.HASH,
        )

        assert assignment.id == "asn-001"
        assert assignment.experiment_id == "exp-001"
        assert assignment.variant_id == "var-001"
        assert assignment.workflow_execution_id == "wf-123"
        assert assignment.assignment_strategy == AssignmentStrategyType.HASH

    def test_create_assignment_full(self):
        """Test creating an assignment with all fields."""
        now = datetime.now(UTC)
        assignment = VariantAssignment(
            id="asn-001",
            experiment_id="exp-001",
            variant_id="var-001",
            workflow_execution_id="wf-123",
            assignment_strategy=AssignmentStrategyType.HASH,
            assignment_context={"user_id": "user-123"},
            execution_status=ExecutionStatus.COMPLETED,
            execution_started_at=now,
            execution_completed_at=now,
            metrics={"duration_seconds": 45.2, "cost_usd": 0.05},
        )

        assert assignment.id == "asn-001"
        assert assignment.experiment_id == "exp-001"
        assert assignment.variant_id == "var-001"
        assert assignment.workflow_execution_id == "wf-123"
        assert assignment.assignment_strategy == AssignmentStrategyType.HASH
        assert assignment.assignment_context == {"user_id": "user-123"}
        assert assignment.execution_status == ExecutionStatus.COMPLETED
        assert assignment.execution_started_at == now
        assert assignment.execution_completed_at == now
        assert assignment.metrics["duration_seconds"] == 45.2
        assert assignment.metrics["cost_usd"] == 0.05

    def test_assignment_defaults(self):
        """Test default values for assignment fields."""
        assignment = VariantAssignment(
            id="asn-001",
            experiment_id="exp-001",
            variant_id="var-001",
            workflow_execution_id="wf-123",
            assignment_strategy=AssignmentStrategyType.RANDOM,
        )

        assert assignment.execution_status == ExecutionStatus.PENDING
        assert assignment.assignment_context is None
        assert assignment.execution_started_at is None
        assert assignment.execution_completed_at is None
        assert assignment.metrics is None
        assert assignment.extra_metadata is None

    def test_assignment_timestamps(self):
        """Test assignment timestamp fields."""
        assignment = VariantAssignment(
            id="asn-001",
            experiment_id="exp-001",
            variant_id="var-001",
            workflow_execution_id="wf-123",
            assignment_strategy=AssignmentStrategyType.RANDOM,
        )

        assert isinstance(assignment.assigned_at, datetime)

    def test_assignment_metrics_structure(self):
        """Test assignment metrics can store various metric types."""
        assignment = VariantAssignment(
            id="asn-001",
            experiment_id="exp-001",
            variant_id="var-001",
            workflow_execution_id="wf-123",
            assignment_strategy=AssignmentStrategyType.RANDOM,
            metrics={
                "duration_seconds": 45.2,
                "cost_usd": 0.05,
                "token_count": 1500,
                "error_rate": 0.0,
            },
        )

        assert len(assignment.metrics) == 4
        assert assignment.metrics["duration_seconds"] == 45.2
        assert assignment.metrics["cost_usd"] == 0.05
        assert assignment.metrics["token_count"] == 1500
        assert assignment.metrics["error_rate"] == 0.0


class TestExperimentResult:
    """Test ExperimentResult model."""

    def test_create_result_minimal(self):
        """Test creating a result with minimal fields."""
        result = ExperimentResult(
            id="res-001",
            experiment_id="exp-001",
            sample_size=250,
            variant_metrics={},
            statistical_tests={},
            recommendation=RecommendationType.CONTINUE,
            confidence=0.5,
        )

        assert result.id == "res-001"
        assert result.experiment_id == "exp-001"
        assert result.sample_size == 250
        assert result.recommendation == RecommendationType.CONTINUE
        assert result.confidence == 0.5

    def test_create_result_full(self):
        """Test creating a result with all fields."""
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
            guardrail_violations=[
                {
                    "variant": "variant_a",
                    "metric": "error_rate",
                    "value": 0.08,
                    "threshold": 0.05,
                }
            ],
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
        assert len(result.variant_metrics) == 2
        assert len(result.statistical_tests) == 1
        assert len(result.guardrail_violations) == 1

    def test_result_defaults(self):
        """Test default values for result fields."""
        result = ExperimentResult(
            id="res-001",
            experiment_id="exp-001",
            sample_size=100,
            variant_metrics={},
            statistical_tests={},
            recommendation=RecommendationType.CONTINUE,
            confidence=0.5,
        )

        assert result.guardrail_violations == []
        assert result.recommended_winner is None
        assert result.extra_metadata is None

    def test_result_timestamps(self):
        """Test result timestamp fields."""
        result = ExperimentResult(
            id="res-001",
            experiment_id="exp-001",
            sample_size=100,
            variant_metrics={},
            statistical_tests={},
            recommendation=RecommendationType.CONTINUE,
            confidence=0.5,
        )

        assert isinstance(result.analyzed_at, datetime)

    def test_result_variant_metrics_structure(self):
        """Test variant metrics structure with detailed statistics."""
        result = ExperimentResult(
            id="res-001",
            experiment_id="exp-001",
            sample_size=300,
            variant_metrics={
                "control": {
                    "mean": 45.2,
                    "std": 5.1,
                    "median": 44.0,
                    "p50": 44.0,
                    "p95": 52.3,
                    "p99": 55.0,
                    "count": 150,
                },
                "variant_a": {
                    "mean": 38.7,
                    "std": 4.8,
                    "median": 37.5,
                    "p50": 37.5,
                    "p95": 46.2,
                    "p99": 48.0,
                    "count": 150,
                },
            },
            statistical_tests={},
            recommendation=RecommendationType.CONTINUE,
            confidence=0.5,
        )

        control_metrics = result.variant_metrics["control"]
        assert control_metrics["mean"] == 45.2
        assert control_metrics["std"] == 5.1
        assert control_metrics["median"] == 44.0
        assert control_metrics["p95"] == 52.3
        assert control_metrics["count"] == 150

    def test_result_statistical_tests_structure(self):
        """Test statistical tests structure with all fields."""
        result = ExperimentResult(
            id="res-001",
            experiment_id="exp-001",
            sample_size=250,
            variant_metrics={},
            statistical_tests={
                "control_vs_variant_a": {
                    "metric": "duration_seconds",
                    "test": "t-test",
                    "p_value": 0.003,
                    "statistically_significant": True,
                    "confidence_interval": [4.2, 8.8],
                    "improvement": 0.144,
                    "control_mean": 45.2,
                    "treatment_mean": 38.7,
                }
            },
            recommendation=RecommendationType.STOP_WINNER,
            recommended_winner="variant_a",
            confidence=0.98,
        )

        test_result = result.statistical_tests["control_vs_variant_a"]
        assert test_result["test"] == "t-test"
        assert test_result["p_value"] == 0.003
        assert test_result["statistically_significant"] is True
        assert test_result["improvement"] == 0.144
        assert len(test_result["confidence_interval"]) == 2

    def test_result_guardrail_violations_structure(self):
        """Test guardrail violations structure."""
        violations = [
            {
                "variant": "variant_a",
                "metric": "error_rate",
                "value": 0.08,
                "threshold": 0.05,
            },
            {
                "variant": "variant_b",
                "metric": "latency_p99",
                "value": 1500,
                "threshold": 1000,
            },
        ]

        result = ExperimentResult(
            id="res-001",
            experiment_id="exp-001",
            sample_size=250,
            variant_metrics={},
            statistical_tests={},
            guardrail_violations=violations,
            recommendation=RecommendationType.STOP_GUARDRAIL_VIOLATION,
            confidence=1.0,
        )

        assert len(result.guardrail_violations) == 2
        assert result.guardrail_violations[0]["variant"] == "variant_a"
        assert result.guardrail_violations[0]["metric"] == "error_rate"
        assert result.guardrail_violations[1]["variant"] == "variant_b"

    def test_result_recommendation_types(self):
        """Test different recommendation types."""
        # Continue
        result_continue = ExperimentResult(
            id="res-001",
            experiment_id="exp-001",
            sample_size=50,
            variant_metrics={},
            statistical_tests={},
            recommendation=RecommendationType.CONTINUE,
            confidence=0.0,
        )
        assert result_continue.recommendation == RecommendationType.CONTINUE

        # Stop winner
        result_winner = ExperimentResult(
            id="res-002",
            experiment_id="exp-001",
            sample_size=250,
            variant_metrics={},
            statistical_tests={},
            recommendation=RecommendationType.STOP_WINNER,
            recommended_winner="variant_a",
            confidence=0.98,
        )
        assert result_winner.recommendation == RecommendationType.STOP_WINNER
        assert result_winner.recommended_winner == "variant_a"

        # Stop no difference
        result_no_diff = ExperimentResult(
            id="res-003",
            experiment_id="exp-001",
            sample_size=500,
            variant_metrics={},
            statistical_tests={},
            recommendation=RecommendationType.STOP_NO_DIFFERENCE,
            confidence=0.95,
        )
        assert result_no_diff.recommendation == RecommendationType.STOP_NO_DIFFERENCE

        # Stop guardrail violation
        result_violation = ExperimentResult(
            id="res-004",
            experiment_id="exp-001",
            sample_size=100,
            variant_metrics={},
            statistical_tests={},
            guardrail_violations=[
                {
                    "variant": "variant_a",
                    "metric": "error_rate",
                    "value": 0.1,
                    "threshold": 0.05,
                }
            ],
            recommendation=RecommendationType.STOP_GUARDRAIL_VIOLATION,
            confidence=1.0,
        )
        assert (
            result_violation.recommendation
            == RecommendationType.STOP_GUARDRAIL_VIOLATION
        )
        assert len(result_violation.guardrail_violations) == 1
