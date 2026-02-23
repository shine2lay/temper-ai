"""Workflow execution context type definition.

Canonical location for WorkflowExecutionContext TypedDict used
throughout the framework as the runtime context bag.
"""

from typing import Any

from typing_extensions import TypedDict

from temper_ai.shared.core.protocols import (
    ConfigLoaderProtocol,
    DomainToolRegistryProtocol,
    TrackerProtocol,
    VisualizerProtocol,
)


class WorkflowExecutionContext(TypedDict, total=False):
    """Canonical type hints for the workflow execution context.

    This is the single authoritative definition of the runtime context bag
    used throughout the framework. All other modules should import from here.

    Contains domain data, infrastructure services, UI concerns, and
    executor internals. All keys are optional (total=False) since different
    executors and lifecycle phases populate different subsets.
    """

    # Core workflow identity
    workflow_id: str
    current_stage: str

    # Accumulated stage outputs: stage_name -> stage output dict
    stage_outputs: dict[str, Any]

    # Arbitrary user-supplied workflow inputs (survives LangGraph dataclass coercion)
    workflow_inputs: dict[str, Any]

    # Common workflow inputs
    topic: str | None
    depth: str | None
    focus_areas: list[str] | None
    query: str | None
    input: str | None
    context: str | None
    data: Any

    # Infrastructure (non-serializable)
    tracker: TrackerProtocol | None
    tool_registry: DomainToolRegistryProtocol | None
    config_loader: ConfigLoaderProtocol | None
    visualizer: VisualizerProtocol | None

    # Server / isolation
    workspace_root: str | None
    run_id: str | None

    # UI/display
    show_details: bool
    detail_console: Any  # Rich Console or None
    stream_callback: Any | None  # StreamCallback or None

    # Quality gate retry tracking (parallel executor)
    stage_retry_counts: dict[str, int]

    # Conversation history for stage:agent re-invocations
    conversation_histories: dict[str, Any]

    # Parallel executor internal state
    agent_outputs: dict[str, Any]
    agent_statuses: dict[str, Any]
    agent_metrics: dict[str, Any]
    errors: dict[str, Any]
    stage_input: dict[str, Any]


# Deprecated alias for backward compatibility
WorkflowStateDict = WorkflowExecutionContext
