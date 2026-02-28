"""
Database models for A/B testing and experimentation.

Models:
- Experiment: Experiment definition with variants and success criteria
- Variant: Configuration variant within an experiment
- VariantAssignment: Assignment of workflow execution to variant
- ExperimentResult: Statistical analysis results
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlmodel import Column, Field, Index, Relationship, SQLModel

from temper_ai.experimentation.constants import FK_EXPERIMENTS_ID
from temper_ai.shared.constants.limits import THRESHOLD_LARGE_COUNT
from temper_ai.shared.constants.probabilities import FRACTION_HALF, PROB_NEAR_CERTAIN
from temper_ai.storage.database.datetime_utils import utcnow


# Enum types for type safety
class ExperimentStatus(StrEnum):
    """Experiment lifecycle status."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class AssignmentStrategyType(StrEnum):
    """Variant assignment strategy types."""

    RANDOM = "random"
    HASH = "hash"
    STRATIFIED = "stratified"
    BANDIT = "bandit"


class ConfigType(StrEnum):
    """Configuration override types."""

    AGENT = "agent"
    STAGE = "stage"
    WORKFLOW = "workflow"
    PROMPT = "prompt"


class ExecutionStatus(StrEnum):
    """Workflow execution status in experiment context."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RecommendationType(StrEnum):
    """Experiment analysis recommendation types."""

    CONTINUE = "continue"
    STOP_WINNER = "stop_winner"
    STOP_NO_DIFFERENCE = "stop_no_difference"
    STOP_GUARDRAIL_VIOLATION = "stop_guardrail_violation"


class Experiment(SQLModel, table=True):
    """
    A/B test experiment definition.

    Represents an experiment testing multiple configuration variants
    against each other to determine which performs better according
    to specified success metrics.

    Attributes:
        id: Unique experiment identifier (UUID)
        name: Human-readable experiment name (unique)
        description: Detailed description of experiment hypothesis
        status: Current experiment status (draft, running, paused, etc.)
        assignment_strategy: Strategy for assigning variants (random, hash, etc.)
        traffic_allocation: Traffic percentage per variant {"control": 0.5, "variant_a": 0.5}
        primary_metric: Main success metric (e.g., "total_cost_usd", "duration_seconds")
        secondary_metrics: Additional metrics to track
        guardrail_metrics: Safety constraints [{"metric": "error_rate", "max_value": 0.05}]
        confidence_level: Statistical confidence level (default: 0.95 for 95%)
        min_sample_size_per_variant: Minimum samples before analysis
        winner_variant_id: Variant ID of winner (if determined)
        total_executions: Total workflow executions in experiment
        created_at: Experiment creation timestamp
        started_at: When experiment was started
        stopped_at: When experiment was stopped

    Example:
        >>> experiment = Experiment(
        ...     id="exp-001",
        ...     name="temperature_optimization",
        ...     description="Test if higher temperature improves creativity",
        ...     status=ExperimentStatus.DRAFT,
        ...     assignment_strategy=AssignmentStrategyType.HASH,
        ...     traffic_allocation={"control": 0.5, "high_temp": 0.5},
        ...     primary_metric="output_quality_score",
        ...     confidence_level=0.95,
        ...     min_sample_size_per_variant=100
        ... )
    """

    __tablename__ = "experiments"

    # Identity
    id: str = Field(primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str

    # Status
    status: ExperimentStatus = Field(default=ExperimentStatus.DRAFT, index=True)

    # Assignment configuration
    assignment_strategy: AssignmentStrategyType = Field(
        default=AssignmentStrategyType.RANDOM
    )
    traffic_allocation: dict[str, float] = Field(sa_column=Column(JSON))

    # Success criteria
    primary_metric: str
    secondary_metrics: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    guardrail_metrics: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON)
    )

    # Statistical settings
    confidence_level: float = Field(default=PROB_NEAR_CERTAIN)
    min_sample_size_per_variant: int = Field(default=THRESHOLD_LARGE_COUNT)

    # Results (cached)
    winner_variant_id: str | None = None
    winning_confidence: float | None = None
    total_executions: int = Field(default=0)

    # Metadata
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_by: str | None = None
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Timestamps
    created_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime, default=utcnow, onupdate=func.now()),
    )

    # Relationships
    variants: list["Variant"] = Relationship(
        back_populates="experiment", cascade_delete=True
    )
    assignments: list["VariantAssignment"] = Relationship(
        back_populates="experiment", cascade_delete=True
    )
    results: list["ExperimentResult"] = Relationship(
        back_populates="experiment", cascade_delete=True
    )


class Variant(SQLModel, table=True):
    """
    Configuration variant within an experiment.

    Represents a specific configuration being tested in an A/B experiment.
    One variant is typically the control (baseline), others are treatments.

    Attributes:
        id: Unique variant identifier (UUID)
        experiment_id: Parent experiment ID
        name: Variant name ("control", "variant_a", etc.)
        description: Description of what this variant tests
        is_control: Whether this is the control/baseline variant
        config_type: Type of configuration being overridden
        config_overrides: Configuration overrides to apply
        allocated_traffic: Target traffic percentage (0.0 to 1.0)
        actual_traffic: Actual traffic received (updated periodically)
        total_executions: Number of workflow executions assigned
        successful_executions: Number of successful executions
        failed_executions: Number of failed executions

    Example:
        >>> variant = Variant(
        ...     id="var-001",
        ...     experiment_id="exp-001",
        ...     name="high_temperature",
        ...     description="Temperature set to 0.9",
        ...     is_control=False,
        ...     config_type=ConfigType.AGENT,
        ...     config_overrides={"inference": {"temperature": 0.9}},
        ...     allocated_traffic=0.5
        ... )
    """

    __tablename__ = "variants"

    # Identity
    id: str = Field(primary_key=True)
    experiment_id: str = Field(
        sa_column=Column(
            String, ForeignKey(FK_EXPERIMENTS_ID, ondelete="CASCADE"), index=True
        )
    )
    name: str
    description: str
    is_control: bool = Field(default=False)

    # Configuration
    config_type: ConfigType = Field(default=ConfigType.AGENT)
    config_overrides: dict[str, Any] = Field(sa_column=Column(JSON))

    # Traffic allocation
    allocated_traffic: float = Field(default=FRACTION_HALF)
    actual_traffic: float = Field(default=0.0)

    # Metrics (cached aggregates)
    total_executions: int = Field(default=0)
    successful_executions: int = Field(default=0)
    failed_executions: int = Field(default=0)

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)

    # Relationships
    experiment: Experiment = Relationship(back_populates="variants")
    assignments: list["VariantAssignment"] = Relationship(
        back_populates="variant", cascade_delete=True
    )


class VariantAssignment(SQLModel, table=True):
    """
    Assignment of a workflow execution to a specific variant.

    Tracks which variant was assigned to each workflow execution,
    along with execution status and collected metrics.

    Attributes:
        id: Unique assignment identifier (UUID)
        experiment_id: Parent experiment ID
        variant_id: Assigned variant ID
        workflow_execution_id: Workflow execution ID (unique, one assignment per workflow)
        assigned_at: Assignment timestamp
        assignment_strategy: Strategy used for this assignment
        assignment_context: Context used for assignment (e.g., {"user_id": "123"})
        execution_status: Current execution status
        execution_started_at: When workflow execution started
        execution_completed_at: When workflow execution completed
        metrics: Denormalized metrics for fast aggregation

    Example:
        >>> assignment = VariantAssignment(
        ...     id="asn-001",
        ...     experiment_id="exp-001",
        ...     variant_id="var-001",
        ...     workflow_execution_id="wf-123",
        ...     assignment_strategy=AssignmentStrategyType.HASH,
        ...     execution_status=ExecutionStatus.PENDING
        ... )
    """

    __tablename__ = "variant_assignments"

    # Identity
    id: str = Field(primary_key=True)
    experiment_id: str = Field(
        sa_column=Column(
            String, ForeignKey(FK_EXPERIMENTS_ID, ondelete="CASCADE"), index=True
        )
    )
    variant_id: str = Field(
        sa_column=Column(
            String, ForeignKey("variants.id", ondelete="CASCADE"), index=True
        )
    )
    workflow_execution_id: str = Field(
        index=True, unique=True
    )  # One assignment per workflow

    # Assignment metadata
    assigned_at: datetime = Field(default_factory=utcnow, index=True)
    assignment_strategy: AssignmentStrategyType
    assignment_context: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )

    # Execution tracking
    execution_status: ExecutionStatus = Field(
        default=ExecutionStatus.PENDING, index=True
    )
    execution_started_at: datetime | None = None
    execution_completed_at: datetime | None = None

    # Metrics (denormalized for performance)
    metrics: dict[str, float] | None = Field(default=None, sa_column=Column(JSON))

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Relationships
    experiment: Experiment = Relationship(back_populates="assignments")
    variant: Variant = Relationship(back_populates="assignments")


class ExperimentResult(SQLModel, table=True):
    """
    Statistical analysis results for an experiment.

    Stores the results of statistical analysis comparing experiment variants,
    including aggregated metrics, hypothesis test results, and recommendations.

    Attributes:
        id: Unique result identifier (UUID)
        experiment_id: Parent experiment ID
        analyzed_at: When analysis was performed
        sample_size: Total number of executions analyzed
        variant_metrics: Aggregated metrics per variant
        statistical_tests: Hypothesis test results
        guardrail_violations: List of guardrail violations detected
        recommendation: Recommended action (continue, stop_winner, etc.)
        recommended_winner: Variant ID of recommended winner (if any)
        confidence: Confidence in recommendation (0.0 to 1.0)

    Example:
        >>> result = ExperimentResult(
        ...     id="res-001",
        ...     experiment_id="exp-001",
        ...     analyzed_at=utcnow(),
        ...     sample_size=250,
        ...     variant_metrics={
        ...         "control": {"mean": 45.2, "std": 5.1, "median": 44.0, "count": 125},
        ...         "variant_a": {"mean": 38.7, "std": 4.8, "median": 37.5, "count": 125}
        ...     },
        ...     recommendation=RecommendationType.STOP_WINNER,
        ...     recommended_winner="variant_a",
        ...     confidence=0.98
        ... )
    """

    __tablename__ = "experiment_results"

    # Identity
    id: str = Field(primary_key=True)
    experiment_id: str = Field(
        sa_column=Column(
            String, ForeignKey(FK_EXPERIMENTS_ID, ondelete="CASCADE"), index=True
        )
    )

    # Analysis metadata
    analyzed_at: datetime = Field(default_factory=utcnow, index=True)
    sample_size: int

    # Variant metrics (aggregated)
    variant_metrics: dict[str, dict[str, Any]] = Field(sa_column=Column(JSON))
    # Example: {
    #   "control": {"mean": 45.2, "std": 5.1, "median": 44.0, "p95": 52.3, "count": 150},
    #   "variant_a": {"mean": 38.7, "std": 4.8, "median": 37.5, "p95": 46.2, "count": 145}
    # }

    # Statistical tests
    statistical_tests: dict[str, dict[str, Any]] = Field(sa_column=Column(JSON))
    # Example: {
    #   "control_vs_variant_a": {
    #     "metric": "duration_seconds",
    #     "test": "t-test",
    #     "p_value": 0.003,
    #     "statistically_significant": True,
    #     "confidence_interval": [4.2, 8.8],
    #     "improvement": 0.144  # 14.4% improvement
    #   }
    # }

    # Guardrail checks
    guardrail_violations: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    # Example: [{"variant": "variant_a", "metric": "error_rate", "value": 0.08, "threshold": 0.05}]

    # Recommendations
    recommendation: RecommendationType
    recommended_winner: str | None = None
    confidence: float

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Relationships
    experiment: Experiment = Relationship(back_populates="results")


# Composite indexes for query performance
Index("idx_experiment_status_created", Experiment.status, Experiment.created_at)  # type: ignore[arg-type]
Index("idx_variant_experiment_name", Variant.experiment_id, Variant.name)
Index(
    "idx_assignment_experiment_variant",
    VariantAssignment.experiment_id,
    VariantAssignment.variant_id,
)
Index("idx_assignment_status_completed", VariantAssignment.execution_status, VariantAssignment.execution_completed_at)  # type: ignore[arg-type]
Index("idx_result_experiment_analyzed", ExperimentResult.experiment_id, ExperimentResult.analyzed_at)  # type: ignore[arg-type]
