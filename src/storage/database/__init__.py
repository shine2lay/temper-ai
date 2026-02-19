"""Database management and models for the framework."""

from src.storage.database.datetime_utils import (
    ensure_utc,
    safe_duration_seconds,
    utcnow,
    validate_utc_aware,
)
from src.storage.database.manager import (
    DatabaseManager,
    IsolationLevel,
    get_database,
    get_session,
    init_database,
    reset_database,
)
from src.storage.database.models import (
    AgentExecution,
    # Merit and learning
    AgentMeritScore,
    # Alerting
    AlertRecord,
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
    "AlertRecord",
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
