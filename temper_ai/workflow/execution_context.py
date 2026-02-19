"""Workflow execution context type definition.

Canonical location for WorkflowExecutionContext TypedDict used
throughout the framework as the runtime context bag.
"""
from typing import Any, Dict, List, Optional

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
    stage_outputs: Dict[str, Any]

    # Arbitrary user-supplied workflow inputs (survives LangGraph dataclass coercion)
    workflow_inputs: Dict[str, Any]

    # Common workflow inputs
    topic: Optional[str]
    depth: Optional[str]
    focus_areas: Optional[List[str]]
    query: Optional[str]
    input: Optional[str]
    context: Optional[str]
    data: Any

    # Infrastructure (non-serializable)
    tracker: Optional[TrackerProtocol]
    tool_registry: Optional[DomainToolRegistryProtocol]
    config_loader: Optional[ConfigLoaderProtocol]
    visualizer: Optional[VisualizerProtocol]

    # Server / isolation
    workspace_root: Optional[str]
    run_id: Optional[str]

    # UI/display
    show_details: bool
    detail_console: Any  # Rich Console or None
    stream_callback: Optional[Any]  # StreamCallback or None

    # Quality gate retry tracking (parallel executor)
    stage_retry_counts: Dict[str, int]

    # Conversation history for stage:agent re-invocations
    conversation_histories: Dict[str, Any]

    # Parallel executor internal state
    agent_outputs: Dict[str, Any]
    agent_statuses: Dict[str, Any]
    agent_metrics: Dict[str, Any]
    errors: Dict[str, Any]
    stage_input: Dict[str, Any]


# Deprecated alias for backward compatibility
WorkflowStateDict = WorkflowExecutionContext
