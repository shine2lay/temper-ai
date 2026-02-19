"""Observability system for tracking workflow, stage, and agent executions.

Heavy submodules (backends, console, database, migrations, formatters, buffer)
are lazily imported via __getattr__ to avoid pulling in SQLAlchemy/Rich at
module load time. Lightweight re-exports (backend ABC, context, models, hooks,
tracker) remain eager.
"""
from typing import Any

# Lightweight / frequently-used — keep eager
from temper_ai.shared.core.context import ExecutionContext

from .backend import ObservabilityBackend
from .hooks import (
    ExecutionHook,
    atrack_agent,  # noqa: F401
    atrack_stage,  # noqa: F401
    atrack_workflow,  # noqa: F401
    get_tracker,
    reset_tracker,
    set_tracker,
    track_agent,
    track_stage,
    track_workflow,
)
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
from .tracker import ExecutionTracker

# Lazy-import mapping for heavy submodules
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Backend implementations
    "SQLObservabilityBackend": (".backends", "SQLObservabilityBackend"),
    "PrometheusObservabilityBackend": (".backends", "PrometheusObservabilityBackend"),
    "S3ObservabilityBackend": (".backends", "S3ObservabilityBackend"),
    # Composite / OTEL
    "CompositeBackend": (".backends", "CompositeBackend"),
    "OTelBackend": (".backends", "OTelBackend"),
    # Buffer
    "ObservabilityBuffer": (".buffer", "ObservabilityBuffer"),
    # Console
    "WorkflowVisualizer": (".console", "WorkflowVisualizer"),
    "StreamingVisualizer": (".console", "StreamingVisualizer"),
    "print_workflow_tree": (".console", "print_workflow_tree"),
    # Database
    "DatabaseManager": (".database", "DatabaseManager"),
    "init_database": (".database", "init_database"),
    "get_database": (".database", "get_database"),
    "get_session": (".database", "get_session"),
    # Formatters
    "format_duration": (".formatters", "format_duration"),
    "format_timestamp": (".formatters", "format_timestamp"),
    "format_tokens": (".formatters", "format_tokens"),
    "format_cost": (".formatters", "format_cost"),
    "status_to_color": (".formatters", "status_to_color"),
    "status_to_icon": (".formatters", "status_to_icon"),
    # Migrations
    "create_schema": (".migrations", "create_schema"),
    "drop_schema": (".migrations", "drop_schema"),
    "reset_schema": (".migrations", "reset_schema"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        import importlib

        mod = importlib.import_module(module_path, __name__)
        val = getattr(mod, attr)
        # Cache on module to avoid repeated lookup
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Backend
    "ObservabilityBackend",
    "SQLObservabilityBackend",
    "PrometheusObservabilityBackend",
    "S3ObservabilityBackend",
    "CompositeBackend",
    "OTelBackend",
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
