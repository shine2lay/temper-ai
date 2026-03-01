"""
Observability database models.

Full schema for tracking workflow, stage, agent, LLM, tool executions
and learning/merit systems.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlmodel import Column, Field, Relationship, SQLModel

from temper_ai.shared.constants.sizes import (
    BYTES_PER_MB,
    DB_JSON_CONFIG_MAX_BYTES,
    DB_JSON_DATA_MAX_BYTES,
)
from temper_ai.storage.database.constants import (
    CASCADE_ALL_DELETE_ORPHAN,
    CASCADE_SIMPLE,
    FIELD_EXTRA_METADATA,
    FIELD_WORKFLOW_CONFIG_SNAPSHOT,
    FK_AGENT_EXECUTIONS_ID,
    FK_CASCADE,
    FK_STAGE_EXECUTIONS_ID,
    FK_WORKFLOW_EXECUTIONS_ID,
    STATUS_CONSTRAINT,
)
from temper_ai.storage.database.datetime_utils import utcnow
from temper_ai.storage.database.validators import validate_json_size

PROMPT_TEMPLATE_HASH_LENGTH = 16  # Max chars for prompt template hash identifier


class WorkflowExecution(SQLModel, table=True):
    """Top-level workflow execution tracking."""

    __tablename__ = "workflow_executions"
    __table_args__ = (
        CheckConstraint(
            STATUS_CONSTRAINT,
            name="wf_valid_status",
        ),
    )

    id: str = Field(primary_key=True)
    workflow_name: str = Field(index=True)
    workflow_version: str | None = None
    workflow_config_snapshot: dict[str, Any] = Field(
        sa_column=Column(JSON)
    )  # noqa: duplicate

    # Trigger info
    trigger_type: str | None = None
    trigger_id: str | None = None
    trigger_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: datetime | None = None
    duration_seconds: float | None = None

    # Status
    status: str = Field(index=True)  # running | completed | failed | halted | timeout
    error_message: str | None = None
    error_stack_trace: str | None = None
    error_fingerprint: str | None = Field(default=None, index=True)

    # Context
    optimization_target: str | None = None
    product_type: str | None = None
    environment: str | None = None

    # Metrics
    total_cost_usd: float | None = None
    total_tokens: int | None = None
    total_llm_calls: int | None = None
    total_tool_calls: int | None = None

    # Metadata
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Cost attribution
    cost_attribution_tags: dict[str, str] | None = Field(
        default=None, sa_column=Column(JSON)
    )

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow)

    # Relationships
    stages: list["StageExecution"] = Relationship(
        back_populates="workflow",
        sa_relationship_kwargs={CASCADE_SIMPLE: CASCADE_ALL_DELETE_ORPHAN},
    )

    def __init__(self, **data: Any) -> None:
        """Initialize with JSON size validation."""
        # Validate large JSON fields before persisting
        if FIELD_WORKFLOW_CONFIG_SNAPSHOT in data:
            validate_json_size(
                data[FIELD_WORKFLOW_CONFIG_SNAPSHOT],
                max_bytes=2 * BYTES_PER_MB,  # Workflows can be larger
                field_name=FIELD_WORKFLOW_CONFIG_SNAPSHOT,
            )

        if FIELD_EXTRA_METADATA in data and data[FIELD_EXTRA_METADATA]:
            validate_json_size(
                data[FIELD_EXTRA_METADATA],
                max_bytes=BYTES_PER_MB // 2,
                field_name=FIELD_EXTRA_METADATA,
            )

        super().__init__(**data)


class StageExecution(SQLModel, table=True):
    """Stage execution tracking."""

    __tablename__ = "stage_executions"
    __table_args__ = (
        CheckConstraint(
            STATUS_CONSTRAINT,
            name="stage_valid_status",
        ),
    )

    id: str = Field(primary_key=True)
    workflow_execution_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(FK_WORKFLOW_EXECUTIONS_ID, ondelete=FK_CASCADE),
            index=True,
        )
    )

    # Identity
    stage_name: str = Field(index=True)
    stage_version: str | None = None
    stage_config_snapshot: dict[str, Any] = Field(
        sa_column=Column(JSON)
    )  # noqa: duplicate

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: datetime | None = None
    duration_seconds: float | None = None

    # Status
    status: str = Field(index=True)
    error_message: str | None = None
    error_fingerprint: str | None = Field(default=None, index=True)

    # Data
    input_data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )  # noqa: duplicate
    output_data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )  # noqa: duplicate

    # Metrics
    num_agents_executed: int | None = None
    num_agents_succeeded: int | None = None
    num_agents_failed: int | None = None
    collaboration_rounds: int | None = None

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )  # noqa: duplicate

    # Data lineage
    output_lineage: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)

    # Relationships
    workflow: WorkflowExecution = Relationship(back_populates="stages")
    agents: list["AgentExecution"] = Relationship(
        back_populates="stage",
        sa_relationship_kwargs={CASCADE_SIMPLE: CASCADE_ALL_DELETE_ORPHAN},
    )
    collaboration_events: list["CollaborationEvent"] = Relationship(
        back_populates="stage",
        sa_relationship_kwargs={CASCADE_SIMPLE: CASCADE_ALL_DELETE_ORPHAN},
    )

    def __init__(self, **data: Any) -> None:
        """Initialize with JSON size validation."""
        if "stage_config_snapshot" in data:
            validate_json_size(
                data["stage_config_snapshot"],
                max_bytes=DB_JSON_CONFIG_MAX_BYTES,
                field_name="stage_config_snapshot",
            )

        if "input_data" in data and data["input_data"]:
            validate_json_size(
                data["input_data"],
                max_bytes=DB_JSON_DATA_MAX_BYTES,
                field_name="input_data",
            )

        if "output_data" in data and data["output_data"]:
            validate_json_size(
                data["output_data"],
                max_bytes=DB_JSON_DATA_MAX_BYTES,
                field_name="output_data",
            )

        super().__init__(**data)


class AgentExecution(SQLModel, table=True):
    """Agent execution tracking."""

    __tablename__ = "agent_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'halted', 'timeout')",
            name="agent_valid_status",
        ),
    )

    id: str = Field(primary_key=True)
    stage_execution_id: str = Field(
        sa_column=Column(
            String, ForeignKey(FK_STAGE_EXECUTIONS_ID, ondelete="CASCADE"), index=True
        )
    )

    # Identity
    agent_name: str = Field(index=True)
    agent_version: str | None = None
    agent_config_snapshot: dict[str, Any] = Field(sa_column=Column(JSON))

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: datetime | None = None
    duration_seconds: float | None = None

    # Status
    status: str = Field(index=True)
    error_message: str | None = None
    error_fingerprint: str | None = Field(default=None, index=True)
    retry_count: int = 0

    # Core data
    reasoning: str | None = None
    input_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    output_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Performance metrics
    llm_duration_seconds: float | None = None
    tool_duration_seconds: float | None = None

    # LLM metrics
    total_tokens: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost_usd: float | None = None
    num_llm_calls: int | None = None

    # Tool metrics
    num_tool_calls: int | None = None

    # Collaboration data
    votes_cast: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    conflicts_with_agents: list[str] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    final_decision: str | None = None
    confidence_score: float | None = None

    # Quality metrics
    output_quality_score: float | None = None
    reasoning_quality_score: float | None = None

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)

    # Relationships
    stage: StageExecution = Relationship(back_populates="agents")
    llm_calls: list["LLMCall"] = Relationship(
        back_populates="agent", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    tool_executions: list["ToolExecution"] = Relationship(
        back_populates="agent", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    def __init__(self, **data: Any) -> None:
        """Initialize with JSON size validation."""
        if "agent_config_snapshot" in data:
            validate_json_size(
                data["agent_config_snapshot"],
                max_bytes=DB_JSON_CONFIG_MAX_BYTES,
                field_name="agent_config_snapshot",
            )

        if "input_data" in data and data["input_data"]:
            validate_json_size(
                data["input_data"],
                max_bytes=DB_JSON_DATA_MAX_BYTES,
                field_name="input_data",
            )

        if "output_data" in data and data["output_data"]:
            validate_json_size(
                data["output_data"],
                max_bytes=DB_JSON_DATA_MAX_BYTES,
                field_name="output_data",
            )

        super().__init__(**data)


class LLMCall(SQLModel, table=True):
    """Detailed LLM call tracking."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'error', 'timeout', 'cancelled')",
            name="llm_valid_status",
        ),
    )

    id: str = Field(primary_key=True)
    agent_execution_id: str = Field(
        sa_column=Column(
            String, ForeignKey(FK_AGENT_EXECUTIONS_ID, ondelete="CASCADE"), index=True
        )
    )

    # Provider info
    provider: str = Field(index=True)
    model: str = Field(index=True)
    base_url: str | None = None

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: datetime | None = None
    latency_ms: int | None = None

    # Request/Response
    prompt: str | None = None
    response: str | None = None

    # Token metrics
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    # Cost
    estimated_cost_usd: float | None = None

    # Parameters
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None

    # Status
    status: str = Field(index=True)
    error_message: str | None = None
    error_fingerprint: str | None = Field(default=None, index=True)
    http_status_code: int | None = None

    # Retry info
    retry_count: int = 0

    # Failover tracking
    failover_sequence: list[str] | None = Field(default=None, sa_column=Column(JSON))
    failover_from_provider: str | None = None

    # Prompt versioning  # noqa
    prompt_template_hash: str | None = Field(
        default=None, max_length=PROMPT_TEMPLATE_HASH_LENGTH
    )
    prompt_template_source: str | None = None

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)

    # Relationships
    agent: AgentExecution = Relationship(back_populates="llm_calls")


class ToolExecution(SQLModel, table=True):
    """Tool execution tracking."""

    __tablename__ = "tool_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'error', 'failed', 'timeout', 'cancelled')",
            name="tool_valid_status",
        ),
    )

    id: str = Field(primary_key=True)
    agent_execution_id: str = Field(
        sa_column=Column(
            String, ForeignKey(FK_AGENT_EXECUTIONS_ID, ondelete="CASCADE"), index=True
        )
    )

    # Tool info
    tool_name: str = Field(index=True)
    tool_version: str | None = None

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: datetime | None = None
    duration_seconds: float | None = None

    # Input/Output
    input_params: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    output_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Status
    status: str = Field(index=True)
    error_message: str | None = None
    error_fingerprint: str | None = Field(default=None, index=True)
    retry_count: int = 0

    # Safety
    safety_checks_applied: list[str] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    approval_required: bool = Field(default=False, index=True)
    approved_by: str | None = None
    approval_timestamp: datetime | None = None

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)

    # Relationships
    agent: AgentExecution = Relationship(back_populates="tool_executions")


class CollaborationEvent(SQLModel, table=True):
    """Collaboration and synthesis tracking."""

    __tablename__ = "collaboration_events"

    id: str = Field(primary_key=True)
    stage_execution_id: str = Field(
        sa_column=Column(
            String, ForeignKey(FK_STAGE_EXECUTIONS_ID, ondelete="CASCADE"), index=True
        )
    )

    # Event type
    event_type: str = Field(
        index=True
    )  # vote | conflict | resolution | consensus | debate_round
    timestamp: datetime = Field(default_factory=utcnow)
    round_number: int | None = None

    # Participants
    agents_involved: list[str] | None = Field(default=None, sa_column=Column(JSON))

    # Data
    event_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Outcome
    resolution_strategy: str | None = None
    outcome: str | None = None
    confidence_score: float | None = None

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)

    # Relationships
    stage: StageExecution = Relationship(back_populates="collaboration_events")


class AgentMeritScore(SQLModel, table=True):
    """Agent reputation/merit tracking."""

    __tablename__ = "agent_merit_scores"
    __table_args__ = (
        UniqueConstraint("agent_name", "domain", name="uq_merit_agent_domain"),
    )

    id: str = Field(primary_key=True)
    agent_name: str = Field(index=True)
    domain: str = Field(index=True)  # e.g., "market_research", "code_generation"

    # Cumulative scores
    total_decisions: int = 0
    successful_decisions: int = 0
    failed_decisions: int = 0
    mixed_decisions: int = 0
    overridden_decisions: int = 0

    # Calculated metrics
    success_rate: float | None = None
    average_confidence: float | None = None
    expertise_score: float | None = None

    # Time-based metrics (with decay)
    last_30_days_success_rate: float | None = None
    last_90_days_success_rate: float | None = None

    # Timestamps
    first_decision_date: datetime | None = None
    last_decision_date: datetime | None = None
    last_updated: datetime = Field(default_factory=utcnow)

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)


class DecisionOutcome(SQLModel, table=True):
    """Decision outcome tracking for learning loop."""

    __tablename__ = "decision_outcomes"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success', 'failure', 'neutral', 'mixed')",
            name="outcome_valid_value",
        ),
    )

    id: str = Field(primary_key=True)
    agent_execution_id: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(FK_AGENT_EXECUTIONS_ID, ondelete="CASCADE"),
            nullable=True,
        ),
    )
    stage_execution_id: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey(FK_STAGE_EXECUTIONS_ID, ondelete="CASCADE"),
            nullable=True,
        ),
    )
    workflow_execution_id: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # Decision info
    decision_type: str = Field(index=True)
    decision_data: dict[str, Any] = Field(sa_column=Column(JSON))

    # Validation
    validation_method: str | None = None
    validation_timestamp: datetime | None = None
    validation_duration_seconds: float | None = None

    # Outcome
    outcome: str = Field(index=True)  # success | failure | neutral | mixed
    impact_metrics: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Learning
    lessons_learned: str | None = None
    should_repeat: bool | None = None
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))

    # Metadata
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)


class SystemMetric(SQLModel, table=True):
    """Aggregated system metrics."""

    __tablename__ = "system_metrics"

    id: str = Field(primary_key=True)
    metric_name: str = Field(index=True)
    metric_value: float
    metric_unit: str | None = None

    # Dimensions
    workflow_name: str | None = Field(default=None, index=True)
    stage_name: str | None = None
    agent_name: str | None = None
    environment: str | None = None

    # Time
    timestamp: datetime = Field(default_factory=utcnow, index=True)
    aggregation_period: str | None = None  # minute | hour | day

    # Metadata
    tags: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    extra_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)


class SchemaVersion(SQLModel, table=True):
    """Track applied database migrations."""

    __tablename__ = "schema_version"

    id: int | None = Field(default=None, primary_key=True)
    version: str = Field(index=True, unique=True)
    applied_at: datetime = Field(default_factory=utcnow)
    description: str | None = None


class ErrorFingerprint(SQLModel, table=True):
    """Aggregated error fingerprint for dedup and trend analysis."""

    __tablename__ = "error_fingerprints"

    fingerprint: str = Field(primary_key=True)  # 16-char hex hash

    # Identity
    error_type: str = Field(index=True)  # Exception class name
    error_code: str = Field(index=True)  # Canonical error code
    classification: str = Field(index=True)  # transient | permanent | safety | unknown

    # Messages
    normalized_message: str  # Deterministic, for display
    sample_message: str | None = None  # One raw example

    # Trending
    occurrence_count: int = Field(default=1)
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)

    # Context (capped JSON arrays)
    recent_workflow_ids: list[str] | None = Field(default=None, sa_column=Column(JSON))
    recent_agent_names: list[str] | None = Field(default=None, sa_column=Column(JSON))

    # Lifecycle
    resolved: bool = Field(default=False)
    resolved_at: datetime | None = None
    resolution_note: str | None = None

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)


class AlertRecord(SQLModel, table=True):
    """Persisted alert record for historical analysis."""

    __tablename__ = "alert_records"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    rule_name: str = Field(index=True)
    severity: str = Field(index=True)
    message: str
    metric_value: float
    threshold: float
    timestamp: datetime = Field(default_factory=utcnow, index=True)
    context: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)


# Create composite indexes for common query patterns
# Performance optimization: Composite indices for common query patterns
# - Foreign key + name/type: For filtering related entities
# - Status/name + timestamp: For time-range queries with filtering
# - end_time indices: For completion time queries and duration calculations

Index("idx_workflow_status", WorkflowExecution.status, WorkflowExecution.start_time)  # type: ignore[arg-type]
Index("idx_workflow_name", WorkflowExecution.workflow_name, WorkflowExecution.start_time)  # type: ignore[arg-type]
Index("idx_workflow_end_time", WorkflowExecution.end_time)  # type: ignore[arg-type]  # For completion time queries
Index(
    "idx_stage_workflow",
    StageExecution.workflow_execution_id,
    StageExecution.stage_name,
)
Index("idx_stage_status", StageExecution.status, StageExecution.start_time)  # type: ignore[arg-type]
Index("idx_stage_end_time", StageExecution.end_time)  # type: ignore[arg-type]  # For stage completion queries
Index("idx_agent_stage", AgentExecution.stage_execution_id, AgentExecution.agent_name)
Index("idx_agent_name", AgentExecution.agent_name, AgentExecution.start_time)  # type: ignore[arg-type]
Index("idx_agent_end_time", AgentExecution.end_time)  # type: ignore[arg-type]  # For agent completion queries
Index("idx_llm_agent", LLMCall.agent_execution_id, LLMCall.start_time)  # type: ignore[arg-type]
Index("idx_llm_model", LLMCall.model, LLMCall.start_time)  # type: ignore[arg-type]
Index("idx_llm_status", LLMCall.status, LLMCall.start_time)  # type: ignore[arg-type]
Index("idx_tool_agent", ToolExecution.agent_execution_id, ToolExecution.tool_name)
Index("idx_tool_name", ToolExecution.tool_name, ToolExecution.start_time)  # type: ignore[arg-type]
Index("idx_tool_status", ToolExecution.status, ToolExecution.start_time)  # type: ignore[arg-type]
Index(
    "idx_collab_stage",
    CollaborationEvent.stage_execution_id,
    CollaborationEvent.event_type,
)
Index("idx_merit_agent", AgentMeritScore.agent_name, AgentMeritScore.domain)
Index("idx_outcome_agent", DecisionOutcome.agent_execution_id, DecisionOutcome.outcome)  # type: ignore[arg-type]
Index("idx_outcome_type", DecisionOutcome.decision_type, DecisionOutcome.outcome)
Index("idx_outcome_validation_ts", DecisionOutcome.validation_timestamp)  # type: ignore[arg-type]  # For time-range queries
Index("idx_metrics_name", SystemMetric.metric_name, SystemMetric.timestamp)  # type: ignore[arg-type]
Index("idx_metrics_workflow", SystemMetric.workflow_name, SystemMetric.timestamp)  # type: ignore[arg-type]


class RollbackSnapshotDB(SQLModel, table=True):
    """Rollback snapshot persistence for observability."""

    __tablename__ = "rollback_snapshots"

    id: str = Field(primary_key=True)
    workflow_execution_id: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            index=True,
            nullable=True,
        ),
    )
    checkpoint_id: str | None = None

    action: dict[str, Any] = Field(sa_column=Column(JSON))
    context: dict[str, Any] = Field(sa_column=Column(JSON))
    file_snapshots: dict[str, Any] = Field(sa_column=Column(JSON))
    state_snapshots: dict[str, Any] = Field(sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=utcnow, index=True)
    expires_at: datetime | None = None

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)


class RollbackEvent(SQLModel, table=True):
    """Rollback execution audit trail."""

    __tablename__ = "rollback_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'partial', 'failed')",
            name="rollback_valid_status",
        ),
    )

    id: str = Field(primary_key=True)
    snapshot_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("rollback_snapshots.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
    )

    status: str = Field(index=True)  # completed | partial | failed
    trigger: str = Field(index=True)  # auto | manual | approval_rejection
    operator: str | None = None

    reverted_items: list[str] = Field(sa_column=Column(JSON))
    failed_items: list[str] = Field(sa_column=Column(JSON))
    errors: list[str] = Field(sa_column=Column(JSON))

    executed_at: datetime = Field(default_factory=utcnow, index=True)

    # Metadata for manual rollbacks
    reason: str | None = None
    rollback_metadata: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )

    # Multi-tenancy
    tenant_id: str | None = Field(default=None, index=True)


# Indexes for rollback tables
Index("idx_error_fp_classification", ErrorFingerprint.classification, ErrorFingerprint.last_seen)  # type: ignore[arg-type]
Index("idx_error_fp_last_seen", ErrorFingerprint.last_seen)  # type: ignore[arg-type]

Index("idx_rollback_snapshots_workflow", RollbackSnapshotDB.workflow_execution_id, RollbackSnapshotDB.created_at)  # type: ignore[arg-type]
Index("idx_rollback_events_snapshot", RollbackEvent.snapshot_id, RollbackEvent.executed_at)  # type: ignore[arg-type]
Index("idx_rollback_events_trigger", RollbackEvent.trigger, RollbackEvent.executed_at)  # type: ignore[arg-type]
Index("idx_rollback_snapshots_expires", RollbackSnapshotDB.expires_at)  # type: ignore[arg-type]  # For cleanup of expired snapshots

# Alert record indexes
Index("idx_alert_rule_time", AlertRecord.rule_name, AlertRecord.timestamp)  # type: ignore[arg-type]

# M9: Import new models for SQLModel metadata registration
from temper_ai.events.models import EventLog, EventSubscription  # noqa: F401

# Optimization: Per-agent evaluation results (imported for SQLModel metadata registration)
from temper_ai.storage.database.models_evaluation import (  # noqa: F401
    AgentEvaluationResult as AgentEvaluationResult,
)
from temper_ai.storage.database.models_registry import AgentRegistryDB  # noqa: F401

# Multi-tenancy: Access control + DB-backed config storage
from temper_ai.storage.database.models_tenancy import (  # noqa: F401
    AgentConfigDB,
    APIKey,
    StageConfigDB,
    Tenant,
    TenantMembership,
    UserDB,
    WorkflowConfigDB,
)
