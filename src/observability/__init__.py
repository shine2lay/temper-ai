"""Observability system for tracking workflow, stage, and agent executions."""

# Backend abstraction
# Canonical ExecutionContext (re-exported for backward compatibility)
from src.core.context import ExecutionContext

from .backend import ObservabilityBackend

# Backend implementations
from .backends import (
    PrometheusObservabilityBackend,
    S3ObservabilityBackend,
    SQLObservabilityBackend,
)

# Buffer for batch operations
from .buffer import ObservabilityBuffer

# Console
from .console import (
    StreamingVisualizer,
    WorkflowVisualizer,
    print_workflow_tree,
)

# Database
from .database import (
    DatabaseManager,
    get_database,
    get_session,
    init_database,
)

# Formatters
from .formatters import (
    format_cost,
    format_duration,
    format_timestamp,
    format_tokens,
    status_to_color,
    status_to_icon,
)

# Hooks
from .hooks import (
    ExecutionHook,
    get_tracker,
    reset_tracker,
    set_tracker,
    track_agent,
    track_stage,
    track_workflow,
)

# Migrations
from .migrations import (
    create_schema,
    drop_schema,
    reset_schema,
)

# Models
from .models import (
    AgentExecution,
    AgentMeritScore,
    CollaborationEvent,
    DecisionOutcome,
    LLMCall,
    SchemaVersion,
    StageExecution,
    SystemMetric,
    ToolExecution,
    WorkflowExecution,
)

# Tracker
from .tracker import ExecutionTracker

__all__ = [
    # Backend
    "ObservabilityBackend",
    "SQLObservabilityBackend",
    "PrometheusObservabilityBackend",
    "S3ObservabilityBackend",
    "ObservabilityBuffer",
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
    # Database
    "DatabaseManager",
    "init_database",
    "get_database",
    "get_session",
    # Migrations
    "create_schema",
    "drop_schema",
    "reset_schema",
    # Console
    "WorkflowVisualizer",
    "StreamingVisualizer",
    "print_workflow_tree",
    # Formatters
    "format_duration",
    "format_timestamp",
    "format_tokens",
    "format_cost",
    "status_to_color",
    "status_to_icon",
    # Tracker
    "ExecutionTracker",
    "ExecutionContext",
    # Hooks
    "get_tracker",
    "set_tracker",
    "reset_tracker",
    "track_workflow",
    "track_stage",
    "track_agent",
    "ExecutionHook",
]
