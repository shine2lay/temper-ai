"""Database management and models for the framework."""
from src.database.datetime_utils import (
    ensure_utc,
    safe_duration_seconds,
    utcnow,
    validate_utc_aware,
)
from src.database.manager import (
    DatabaseManager,
    IsolationLevel,
    get_database,
    get_session,
    init_database,
    reset_database,
)
from src.database.models import (
    AgentExecution,
    # Merit and learning
    AgentMeritScore,
    CollaborationEvent,
    DecisionOutcome,
    LLMCall,
    RollbackEvent,
    # Rollback
    RollbackSnapshotDB,
    SchemaVersion,
    StageExecution,
    # System metrics
    SystemMetric,
    ToolExecution,
    # Execution tracking
    WorkflowExecution,
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
