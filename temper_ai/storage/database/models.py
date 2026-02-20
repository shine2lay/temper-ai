"""
Observability database models.

Full schema for tracking workflow, stage, agent, LLM, tool executions
and learning/merit systems.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlmodel import Column, Field, Relationship, SQLModel

from temper_ai.shared.constants.sizes import BYTES_PER_MB
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
    workflow_version: Optional[str] = None
    workflow_config_snapshot: Dict[str, Any] = Field(sa_column=Column(JSON))  # noqa: duplicate

    # Trigger info
    trigger_type: Optional[str] = None
    trigger_id: Optional[str] = None
    trigger_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Status
    status: str = Field(index=True)  # running | completed | failed | halted | timeout
    error_message: Optional[str] = None
    error_stack_trace: Optional[str] = None
    error_fingerprint: Optional[str] = Field(default=None, index=True)

    # Context
    optimization_target: Optional[str] = None
    product_type: Optional[str] = None
    environment: Optional[str] = None

    # Metrics
    total_cost_usd: Optional[float] = None
    total_tokens: Optional[int] = None
    total_llm_calls: Optional[int] = None
    total_tool_calls: Optional[int] = None

    # Metadata
    tags: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Cost attribution
    cost_attribution_tags: Optional[Dict[str, str]] = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=utcnow)

    # Relationships
    stages: List["StageExecution"] = Relationship(
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
            String, ForeignKey(FK_WORKFLOW_EXECUTIONS_ID, ondelete=FK_CASCADE), index=True
        )
    )

    # Identity
    stage_name: str = Field(index=True)
    stage_version: Optional[str] = None
    stage_config_snapshot: Dict[str, Any] = Field(sa_column=Column(JSON))  # noqa: duplicate

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Status
    status: str = Field(index=True)
    error_message: Optional[str] = None
    error_fingerprint: Optional[str] = Field(default=None, index=True)

    # Data
    input_data: Optional[Dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )  # noqa: duplicate
    output_data: Optional[Dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )  # noqa: duplicate

    # Metrics
    num_agents_executed: Optional[int] = None
    num_agents_succeeded: Optional[int] = None
    num_agents_failed: Optional[int] = None
    collaboration_rounds: Optional[int] = None

    # Metadata
    extra_metadata: Optional[Dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )  # noqa: duplicate

    # Data lineage
    output_lineage: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    workflow: WorkflowExecution = Relationship(back_populates="stages")
    agents: List["AgentExecution"] = Relationship(
        back_populates="stage", sa_relationship_kwargs={CASCADE_SIMPLE: CASCADE_ALL_DELETE_ORPHAN}
    )
    collaboration_events: List["CollaborationEvent"] = Relationship(
        back_populates="stage", sa_relationship_kwargs={CASCADE_SIMPLE: CASCADE_ALL_DELETE_ORPHAN}
    )

    def __init__(self, **data: Any) -> None:
        """Initialize with JSON size validation."""
        if "stage_config_snapshot" in data:
            validate_json_size(
                data["stage_config_snapshot"],
                max_bytes=BYTES_PER_MB,
                field_name="stage_config_snapshot",
            )

        if "input_data" in data and data["input_data"]:
            validate_json_size(
                data["input_data"], max_bytes=BYTES_PER_MB, field_name="input_data"
            )

        if "output_data" in data and data["output_data"]:
            validate_json_size(
                data["output_data"], max_bytes=BYTES_PER_MB, field_name="output_data"
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
        sa_column=Column(String, ForeignKey(FK_STAGE_EXECUTIONS_ID, ondelete="CASCADE"), index=True)
    )

    # Identity
    agent_name: str = Field(index=True)
    agent_version: Optional[str] = None
    agent_config_snapshot: Dict[str, Any] = Field(sa_column=Column(JSON))

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Status
    status: str = Field(index=True)
    error_message: Optional[str] = None
    error_fingerprint: Optional[str] = Field(default=None, index=True)
    retry_count: int = 0

    # Core data
    reasoning: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    output_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Performance metrics
    llm_duration_seconds: Optional[float] = None
    tool_duration_seconds: Optional[float] = None

    # LLM metrics
    total_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    num_llm_calls: Optional[int] = None

    # Tool metrics
    num_tool_calls: Optional[int] = None

    # Collaboration data
    votes_cast: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    conflicts_with_agents: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    final_decision: Optional[str] = None
    confidence_score: Optional[float] = None

    # Quality metrics
    output_quality_score: Optional[float] = None
    reasoning_quality_score: Optional[float] = None

    # Metadata
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    stage: StageExecution = Relationship(back_populates="agents")
    llm_calls: List["LLMCall"] = Relationship(
        back_populates="agent", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    tool_executions: List["ToolExecution"] = Relationship(
        back_populates="agent", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    def __init__(self, **data: Any) -> None:
        """Initialize with JSON size validation."""
        if "agent_config_snapshot" in data:
            validate_json_size(
                data["agent_config_snapshot"],
                max_bytes=BYTES_PER_MB,
                field_name="agent_config_snapshot",
            )

        if "input_data" in data and data["input_data"]:
            validate_json_size(
                data["input_data"], max_bytes=BYTES_PER_MB, field_name="input_data"
            )

        if "output_data" in data and data["output_data"]:
            validate_json_size(
                data["output_data"], max_bytes=BYTES_PER_MB, field_name="output_data"
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
        sa_column=Column(String, ForeignKey(FK_AGENT_EXECUTIONS_ID, ondelete="CASCADE"), index=True)
    )

    # Provider info
    provider: str = Field(index=True)
    model: str = Field(index=True)
    base_url: Optional[str] = None

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: Optional[datetime] = None
    latency_ms: Optional[int] = None

    # Request/Response
    prompt: Optional[str] = None
    response: Optional[str] = None

    # Token metrics
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    # Cost
    estimated_cost_usd: Optional[float] = None

    # Parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None

    # Status
    status: str = Field(index=True)
    error_message: Optional[str] = None
    error_fingerprint: Optional[str] = Field(default=None, index=True)
    http_status_code: Optional[int] = None

    # Retry info
    retry_count: int = 0

    # Failover tracking
    failover_sequence: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    failover_from_provider: Optional[str] = None

    # Prompt versioning
    prompt_template_hash: Optional[str] = Field(default=None, max_length=16)  # noqa: duplicate
    prompt_template_source: Optional[str] = None

    # Metadata
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    agent: AgentExecution = Relationship(back_populates="llm_calls")


class ToolExecution(SQLModel, table=True):
    """Tool execution tracking."""

    __tablename__ = "tool_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'error', 'timeout', 'cancelled')",
            name="tool_valid_status",
        ),
    )

    id: str = Field(primary_key=True)
    agent_execution_id: str = Field(
        sa_column=Column(String, ForeignKey(FK_AGENT_EXECUTIONS_ID, ondelete="CASCADE"), index=True)
    )

    # Tool info
    tool_name: str = Field(index=True)
    tool_version: Optional[str] = None

    # Timing
    start_time: datetime = Field(default_factory=utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Input/Output
    input_params: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    output_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Status
    status: str = Field(index=True)
    error_message: Optional[str] = None
    error_fingerprint: Optional[str] = Field(default=None, index=True)
    retry_count: int = 0

    # Safety
    safety_checks_applied: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    approval_required: bool = Field(default=False, index=True)
    approved_by: Optional[str] = None
    approval_timestamp: Optional[datetime] = None

    # Metadata
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    agent: AgentExecution = Relationship(back_populates="tool_executions")


class CollaborationEvent(SQLModel, table=True):
    """Collaboration and synthesis tracking."""

    __tablename__ = "collaboration_events"

    id: str = Field(primary_key=True)
    stage_execution_id: str = Field(
        sa_column=Column(String, ForeignKey(FK_STAGE_EXECUTIONS_ID, ondelete="CASCADE"), index=True)
    )

    # Event type
    event_type: str = Field(index=True)  # vote | conflict | resolution | consensus | debate_round
    timestamp: datetime = Field(default_factory=utcnow)
    round_number: Optional[int] = None

    # Participants
    agents_involved: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))

    # Data
    event_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Outcome
    resolution_strategy: Optional[str] = None
    outcome: Optional[str] = None
    confidence_score: Optional[float] = None

    # Metadata
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    stage: StageExecution = Relationship(back_populates="collaboration_events")


class AgentMeritScore(SQLModel, table=True):
    """Agent reputation/merit tracking."""

    __tablename__ = "agent_merit_scores"
    __table_args__ = (UniqueConstraint("agent_name", "domain", name="uq_merit_agent_domain"),)

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
    success_rate: Optional[float] = None
    average_confidence: Optional[float] = None
    expertise_score: Optional[float] = None

    # Time-based metrics (with decay)
    last_30_days_success_rate: Optional[float] = None
    last_90_days_success_rate: Optional[float] = None

    # Timestamps
    first_decision_date: Optional[datetime] = None
    last_decision_date: Optional[datetime] = None
    last_updated: datetime = Field(default_factory=utcnow)

    # Metadata
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


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
    agent_execution_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String, ForeignKey(FK_AGENT_EXECUTIONS_ID, ondelete="CASCADE"), nullable=True
        ),
    )
    stage_execution_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String, ForeignKey(FK_STAGE_EXECUTIONS_ID, ondelete="CASCADE"), nullable=True
        ),
    )
    workflow_execution_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String, ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=True
        ),
    )

    # Decision info
    decision_type: str = Field(index=True)
    decision_data: Dict[str, Any] = Field(sa_column=Column(JSON))

    # Validation
    validation_method: Optional[str] = None
    validation_timestamp: Optional[datetime] = None
    validation_duration_seconds: Optional[float] = None

    # Outcome
    outcome: str = Field(index=True)  # success | failure | neutral | mixed
    impact_metrics: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Learning
    lessons_learned: Optional[str] = None
    should_repeat: Optional[bool] = None
    tags: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))

    # Metadata
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


class SystemMetric(SQLModel, table=True):
    """Aggregated system metrics."""

    __tablename__ = "system_metrics"

    id: str = Field(primary_key=True)
    metric_name: str = Field(index=True)
    metric_value: float
    metric_unit: Optional[str] = None

    # Dimensions
    workflow_name: Optional[str] = Field(default=None, index=True)
    stage_name: Optional[str] = None
    agent_name: Optional[str] = None
    environment: Optional[str] = None

    # Time
    timestamp: datetime = Field(default_factory=utcnow, index=True)
    aggregation_period: Optional[str] = None  # minute | hour | day

    # Metadata
    tags: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


class SchemaVersion(SQLModel, table=True):
    """Track applied database migrations."""

    __tablename__ = "schema_version"

    id: Optional[int] = Field(default=None, primary_key=True)
    version: str = Field(index=True, unique=True)
    applied_at: datetime = Field(default_factory=utcnow)
    description: Optional[str] = None


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
    sample_message: Optional[str] = None  # One raw example

    # Trending
    occurrence_count: int = Field(default=1)
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)

    # Context (capped JSON arrays)
    recent_workflow_ids: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    recent_agent_names: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))

    # Lifecycle
    resolved: bool = Field(default=False)
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None


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
    context: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


# Create composite indexes for common query patterns
# Performance optimization: Composite indices for common query patterns
# - Foreign key + name/type: For filtering related entities
# - Status/name + timestamp: For time-range queries with filtering
# - end_time indices: For completion time queries and duration calculations

Index("idx_workflow_status", WorkflowExecution.status, WorkflowExecution.start_time)  # type: ignore[arg-type]
Index("idx_workflow_name", WorkflowExecution.workflow_name, WorkflowExecution.start_time)  # type: ignore[arg-type]
Index("idx_workflow_end_time", WorkflowExecution.end_time)  # type: ignore[arg-type]  # For completion time queries
Index("idx_stage_workflow", StageExecution.workflow_execution_id, StageExecution.stage_name)
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
Index("idx_collab_stage", CollaborationEvent.stage_execution_id, CollaborationEvent.event_type)
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
    workflow_execution_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey("workflow_executions.id", ondelete="CASCADE"),
            index=True,
            nullable=True,
        ),
    )
    checkpoint_id: Optional[str] = None

    action: Dict[str, Any] = Field(sa_column=Column(JSON))
    context: Dict[str, Any] = Field(sa_column=Column(JSON))
    file_snapshots: Dict[str, Any] = Field(sa_column=Column(JSON))
    state_snapshots: Dict[str, Any] = Field(sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=utcnow, index=True)
    expires_at: Optional[datetime] = None


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
    operator: Optional[str] = None

    reverted_items: List[str] = Field(sa_column=Column(JSON))
    failed_items: List[str] = Field(sa_column=Column(JSON))
    errors: List[str] = Field(sa_column=Column(JSON))

    executed_at: datetime = Field(default_factory=utcnow, index=True)

    # Metadata for manual rollbacks
    reason: Optional[str] = None
    rollback_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


# Indexes for rollback tables
Index("idx_error_fp_classification", ErrorFingerprint.classification, ErrorFingerprint.last_seen)  # type: ignore[arg-type]
Index("idx_error_fp_last_seen", ErrorFingerprint.last_seen)  # type: ignore[arg-type]

Index("idx_rollback_snapshots_workflow", RollbackSnapshotDB.workflow_execution_id, RollbackSnapshotDB.created_at)  # type: ignore[arg-type]
Index("idx_rollback_events_snapshot", RollbackEvent.snapshot_id, RollbackEvent.executed_at)  # type: ignore[arg-type]
Index("idx_rollback_events_trigger", RollbackEvent.trigger, RollbackEvent.executed_at)  # type: ignore[arg-type]
Index("idx_rollback_snapshots_expires", RollbackSnapshotDB.expires_at)  # type: ignore[arg-type]  # For cleanup of expired snapshots

# Alert record indexes
Index("idx_alert_rule_time", AlertRecord.rule_name, AlertRecord.timestamp)  # type: ignore[arg-type]
