"""Database management and models for the framework."""
from src.database.manager import (
    DatabaseManager,
    get_database,
    get_session,
    init_database,
    reset_database,
    IsolationLevel,
)
from src.database.models import (
    # Execution tracking
    WorkflowExecution,
    StageExecution,
    AgentExecution,
    LLMCall,
    ToolExecution,
    CollaborationEvent,
    # Merit and learning
    AgentMeritScore,
    DecisionOutcome,
    # System metrics
    SystemMetric,
    SchemaVersion,
    # Rollback
    RollbackSnapshotDB,
    RollbackEvent,
)
from src.database.datetime_utils import (
    utcnow,
    ensure_utc,
    validate_utc_aware,
    safe_duration_seconds,
)

__all__ = [
    # Manager
    "DatabaseManager",
    "get_database",
    "get_session",
    "init_database",
    "reset_database",
    "IsolationLevel",
    # Models
    "WorkflowExecution",
    "StageExecution",
    "AgentExecution",
    "LLMCall",
    "ToolExecution",
    "CollaborationEvent",
    "AgentMeritScore",
    "DecisionOutcome",
    "SystemMetric",
    "SchemaVersion",
    "RollbackSnapshotDB",
    "RollbackEvent",
    # Utils
    "utcnow",
    "ensure_utc",
    "validate_utc_aware",
    "safe_duration_seconds",
]
