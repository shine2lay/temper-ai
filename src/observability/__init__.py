"""Observability system for tracking workflow, stage, and agent executions."""

# Backend abstraction
from .backend import ObservabilityBackend

# Backend implementations
from .backends import (
    SQLObservabilityBackend,
    PrometheusObservabilityBackend,
    S3ObservabilityBackend,
)

# Buffer for batch operations
from .buffer import ObservabilityBuffer

# Models
from .models import (
    WorkflowExecution,
    StageExecution,
    AgentExecution,
    LLMCall,
    ToolExecution,
    CollaborationEvent,
    AgentMeritScore,
    DecisionOutcome,
    SystemMetric,
    SchemaVersion,
)

# Database
from .database import (
    DatabaseManager,
    init_database,
    get_database,
    get_session,
)

# Migrations
from .migrations import (
    create_schema,
    drop_schema,
    reset_schema,
)

# Console
from .console import (
    WorkflowVisualizer,
    StreamingVisualizer,
    print_workflow_tree,
)

# Formatters
from .formatters import (
    format_duration,
    format_timestamp,
    format_tokens,
    format_cost,
    status_to_color,
    status_to_icon,
)

# Tracker
from .tracker import (
    ExecutionTracker,
    ExecutionContext,
)

# Hooks
from .hooks import (
    get_tracker,
    set_tracker,
    reset_tracker,
    track_workflow,
    track_stage,
    track_agent,
    ExecutionHook,
)

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
