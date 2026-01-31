# Task: m1-01-observability-db - Implement observability database schema with SQLModel

**Priority:** CRITICAL
**Effort:** 3-4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement the complete observability database schema using SQLModel as defined in TECHNICAL_SPECIFICATION.md Section 8. This includes all tables for workflow/stage/agent tracking, LLM calls, tool executions, collaboration events, merit scores, and decision outcomes.

---

## Files to Create

- `src/observability/__init__.py` - Package exports
- `src/observability/models.py` - All SQLModel table definitions
- `src/observability/database.py` - Database connection and session management
- `src/observability/migrations.py` - Schema migration utilities
- `tests/test_observability/test_models.py` - Model tests
- `tests/test_observability/test_database.py` - Database connection tests

---

## Files to Modify

None (new implementation)

---

## Acceptance Criteria

### Core Functionality
- [x] - [ ] WorkflowExecution model with all fields from spec
- [x] - [ ] StageExecution model with all fields from spec
- [x] - [ ] AgentExecution model with all fields from spec
- [x] - [ ] LLMCall model with all fields from spec
- [x] - [ ] ToolExecution model with all fields from spec
- [x] - [ ] CollaborationEvent model with all fields from spec
- [x] - [ ] AgentMeritScore model with all fields from spec
- [x] - [ ] DecisionOutcome model with all fields from spec
- [x] - [ ] SystemMetric model with all fields from spec
- [x] - [ ] All relationships defined (ForeignKey references)
- [x] - [ ] All indexes created per spec

### Database Management
- [x] - [x] - [ ] Support both SQLite (dev) and PostgreSQL (production)
- [x] - [ ] Database initialization function
- [x] - [ ] Connection pooling configured
- [x] - [ ] Session management with context manager
- [x] - [ ] Graceful connection handling and retries

### Schema Features
- [x] - [ ] JSON fields for config snapshots and metadata
- [x] - [ ] Timestamp fields with automatic defaults
- [x] - [ ] Proper types (TEXT, INTEGER, REAL, TIMESTAMP, JSON)
- [x] - [ ] Nullable fields marked correctly
- [x] - [ ] Unique constraints where needed

### Testing
- [x] - [ ] Unit tests for each model (create, read, update)
- [x] - [ ] Test relationships between models
- [x] - [ ] Test database initialization (SQLite)
- [x] - [ ] Test session management
- [x] - [ ] Test JSON field serialization/deserialization
- [x] - [ ] Coverage > 90%

### Documentation
- [x] - [ ] Docstrings for all models
- [x] - [ ] Docstrings for database functions
- [x] - [ ] Type hints throughout

---

## Implementation Details

**src/observability/models.py:**

```python
"""
Observability database models.

Full schema for tracking workflow, stage, agent, LLM, tool executions
and learning/merit systems.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlmodel import Field, SQLModel, Relationship, JSON, Column
from sqlalchemy import Index


class WorkflowExecution(SQLModel, table=True):
    """Top-level workflow execution tracking."""

    __tablename__ = "workflow_executions"

    id: str = Field(primary_key=True)
    workflow_name: str = Field(index=True)
    workflow_version: Optional[str] = None
    workflow_config_snapshot: Dict[str, Any] = Field(sa_column=Column(JSON))

    # Trigger info
    trigger_type: Optional[str] = None
    trigger_id: Optional[str] = None
    trigger_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Timing
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Status
    status: str = Field(index=True)  # running | completed | failed | halted | timeout
    error_message: Optional[str] = None
    error_stack_trace: Optional[str] = None

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
    metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    stages: List["StageExecution"] = Relationship(back_populates="workflow")


class StageExecution(SQLModel, table=True):
    """Stage execution tracking."""

    __tablename__ = "stage_executions"

    id: str = Field(primary_key=True)
    workflow_execution_id: str = Field(foreign_key="workflow_executions.id", index=True)

    # Identity
    stage_name: str = Field(index=True)
    stage_version: Optional[str] = None
    stage_config_snapshot: Dict[str, Any] = Field(sa_column=Column(JSON))

    # Timing
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Status
    status: str = Field(index=True)
    error_message: Optional[str] = None

    # Data
    input_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    output_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Metrics
    num_agents_executed: Optional[int] = None
    num_agents_succeeded: Optional[int] = None
    num_agents_failed: Optional[int] = None
    collaboration_rounds: Optional[int] = None

    # Metadata
    metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    workflow: WorkflowExecution = Relationship(back_populates="stages")
    agents: List["AgentExecution"] = Relationship(back_populates="stage")
    collaboration_events: List["CollaborationEvent"] = Relationship(back_populates="stage")


class AgentExecution(SQLModel, table=True):
    """Agent execution tracking."""

    __tablename__ = "agent_executions"

    id: str = Field(primary_key=True)
    stage_execution_id: str = Field(foreign_key="stage_executions.id", index=True)

    # Identity
    agent_name: str = Field(index=True)
    agent_version: Optional[str] = None
    agent_config_snapshot: Dict[str, Any] = Field(sa_column=Column(JSON))

    # Timing
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Status
    status: str = Field(index=True)
    error_message: Optional[str] = None
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
    metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    stage: StageExecution = Relationship(back_populates="agents")
    llm_calls: List["LLMCall"] = Relationship(back_populates="agent")
    tool_executions: List["ToolExecution"] = Relationship(back_populates="agent")


class LLMCall(SQLModel, table=True):
    """Detailed LLM call tracking."""

    __tablename__ = "llm_calls"

    id: str = Field(primary_key=True)
    agent_execution_id: str = Field(foreign_key="agent_executions.id", index=True)

    # Provider info
    provider: str = Field(index=True)
    model: str = Field(index=True)
    base_url: Optional[str] = None

    # Timing
    start_time: datetime = Field(default_factory=datetime.utcnow)
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
    http_status_code: Optional[int] = None

    # Retry info
    retry_count: int = 0

    # Metadata
    metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    agent: AgentExecution = Relationship(back_populates="llm_calls")


class ToolExecution(SQLModel, table=True):
    """Tool execution tracking."""

    __tablename__ = "tool_executions"

    id: str = Field(primary_key=True)
    agent_execution_id: str = Field(foreign_key="agent_executions.id", index=True)

    # Tool info
    tool_name: str = Field(index=True)
    tool_version: Optional[str] = None

    # Timing
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Input/Output
    input_params: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    output_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Status
    status: str = Field(index=True)
    error_message: Optional[str] = None
    retry_count: int = 0

    # Safety
    safety_checks_applied: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    approval_required: bool = False
    approved_by: Optional[str] = None
    approval_timestamp: Optional[datetime] = None

    # Metadata
    metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    agent: AgentExecution = Relationship(back_populates="tool_executions")


class CollaborationEvent(SQLModel, table=True):
    """Collaboration and synthesis tracking."""

    __tablename__ = "collaboration_events"

    id: str = Field(primary_key=True)
    stage_execution_id: str = Field(foreign_key="stage_executions.id", index=True)

    # Event type
    event_type: str = Field(index=True)  # vote | conflict | resolution | consensus | debate_round
    timestamp: datetime = Field(default_factory=datetime.utcnow)
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
    metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Relationships
    stage: StageExecution = Relationship(back_populates="collaboration_events")


class AgentMeritScore(SQLModel, table=True):
    """Agent reputation/merit tracking."""

    __tablename__ = "agent_merit_scores"

    id: str = Field(primary_key=True)
    agent_name: str = Field(index=True)
    domain: str = Field(index=True)  # e.g., "market_research", "code_generation"

    # Cumulative scores
    total_decisions: int = 0
    successful_decisions: int = 0
    failed_decisions: int = 0
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
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Metadata
    metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


class DecisionOutcome(SQLModel, table=True):
    """Decision outcome tracking for learning loop."""

    __tablename__ = "decision_outcomes"

    id: str = Field(primary_key=True)
    agent_execution_id: Optional[str] = Field(default=None, foreign_key="agent_executions.id")
    stage_execution_id: Optional[str] = Field(default=None, foreign_key="stage_executions.id")
    workflow_execution_id: Optional[str] = Field(default=None, foreign_key="workflow_executions.id")

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
    metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


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
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    aggregation_period: Optional[str] = None  # minute | hour | day

    # Metadata
    tags: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


# Create indexes
Index("idx_workflow_status", WorkflowExecution.status, WorkflowExecution.start_time)
Index("idx_workflow_name", WorkflowExecution.workflow_name, WorkflowExecution.start_time)
Index("idx_stage_workflow", StageExecution.workflow_execution_id, StageExecution.stage_name)
Index("idx_stage_status", StageExecution.status, StageExecution.start_time)
Index("idx_agent_stage", AgentExecution.stage_execution_id, AgentExecution.agent_name)
Index("idx_agent_name", AgentExecution.agent_name, AgentExecution.start_time)
Index("idx_llm_agent", LLMCall.agent_execution_id, LLMCall.start_time)
Index("idx_llm_model", LLMCall.model, LLMCall.start_time)
Index("idx_llm_status", LLMCall.status, LLMCall.start_time)
Index("idx_tool_agent", ToolExecution.agent_execution_id, ToolExecution.tool_name)
Index("idx_tool_name", ToolExecution.tool_name, ToolExecution.start_time)
Index("idx_tool_status", ToolExecution.status, ToolExecution.start_time)
Index("idx_collab_stage", CollaborationEvent.stage_execution_id, CollaborationEvent.event_type)
Index("idx_merit_agent", AgentMeritScore.agent_name, AgentMeritScore.domain)
Index("idx_merit_score", AgentMeritScore.expertise_score.desc())
Index("idx_outcome_agent", DecisionOutcome.agent_execution_id, DecisionOutcome.outcome)
Index("idx_outcome_type", DecisionOutcome.decision_type, DecisionOutcome.outcome)
Index("idx_outcome_validation", DecisionOutcome.validation_timestamp.desc())
Index("idx_metrics_name", SystemMetric.metric_name, SystemMetric.timestamp)
Index("idx_metrics_workflow", SystemMetric.workflow_name, SystemMetric.timestamp)
```

**src/observability/database.py:**

```python
"""Database connection and session management."""
from contextlib import contextmanager
from typing import Generator, Optional
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
import os


class DatabaseManager:
    """Manages database connections and sessions."""

    def __init__(self, database_url: Optional[str] = None):
        """Initialize database manager.

        Args:
            database_url: Database URL. If None, uses DATABASE_URL env var
                         or defaults to SQLite.
        """
        if database_url is None:
            database_url = os.getenv(
                "DATABASE_URL",
                "sqlite:///./meta_autonomous.db"
            )

        self.database_url = database_url
        self.engine = self._create_engine()

    def _create_engine(self) -> Engine:
        """Create SQLAlchemy engine with appropriate settings."""
        if self.database_url.startswith("sqlite"):
            # SQLite settings
            engine = create_engine(
                self.database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False
            )
        else:
            # PostgreSQL settings
            engine = create_engine(
                self.database_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                echo=False
            )

        return engine

    def create_all_tables(self):
        """Create all tables in the database."""
        SQLModel.metadata.create_all(self.engine)

    def drop_all_tables(self):
        """Drop all tables. Use with caution!"""
        SQLModel.metadata.drop_all(self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context manager for database sessions.

        Usage:
            with db_manager.session() as session:
                workflow = WorkflowExecution(...)
                session.add(workflow)
                session.commit()
        """
        session = Session(self.engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# Global instance (can be configured)
_db_manager: Optional[DatabaseManager] = None


def init_database(database_url: Optional[str] = None) -> DatabaseManager:
    """Initialize global database manager.

    Args:
        database_url: Database URL. If None, uses default.

    Returns:
        Initialized DatabaseManager instance.
    """
    global _db_manager
    _db_manager = DatabaseManager(database_url)
    _db_manager.create_all_tables()
    return _db_manager


def get_database() -> DatabaseManager:
    """Get global database manager instance.

    Raises:
        RuntimeError: If database not initialized.
    """
    if _db_manager is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db_manager


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get database session from global manager.

    Usage:
        with get_session() as session:
            workflow = session.query(WorkflowExecution).first()
    """
    db = get_database()
    with db.session() as session:
        yield session
```

---

## Test Strategy

Create comprehensive tests in `tests/test_observability/`:

1. **test_models.py**: Test each model can be created, fields serialize correctly
2. **test_database.py**: Test database initialization, session management, transactions
3. **test_relationships.py**: Test ForeignKey relationships work correctly

---

## Success Metrics

- [x] - [ ] All 9 models implemented with correct fields
- [x] - [ ] Database initializes successfully for SQLite
- [x] - [ ] Session context manager works correctly
- [x] - [ ] All tests pass
- [x] - [ ] Test coverage > 90%
- [x] - [ ] No mypy type errors

---

## Dependencies

- **Blocked by:** m1-00-structure (completed)
- **Blocks:** m1-07-integration
- **Integrates with:** All observability features

---

## Design References

- TECHNICAL_SPECIFICATION.md Section 8: Observability System
- SQLModel documentation: https://sqlmodel.tiangolo.com/
- SQLAlchemy JSON column documentation

---

## Notes

- Use SQLModel (combines Pydantic + SQLAlchemy) for type safety
- JSON columns work differently in SQLite vs Postgres - test both
- Relationships use back_populates for bidirectional access
- All timestamps should use UTC (datetime.utcnow)
- Don't forget to export models from `__init__.py`
