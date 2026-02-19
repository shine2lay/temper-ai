"""State management for workflow execution.

Provides state initialization and init-node factory functions
for LangGraph compiler and executors.
"""
import logging
import uuid
from typing import Any, Callable, Dict, Optional

from temper_ai.workflow.domain_state import (
    ConfigLoaderProtocol,
    DomainToolRegistryProtocol,
    TrackerProtocol,
)
from temper_ai.workflow.execution_context import WorkflowExecutionContext
from temper_ai.workflow.langgraph_state import LangGraphWorkflowState
from temper_ai.shared.constants.sizes import UUID_HEX_SHORT_LENGTH

logger = logging.getLogger(__name__)

# Keys managed by the framework that must not be overwritten by user input_data.
RESERVED_STATE_KEYS = frozenset({
    "stage_outputs",
    "current_stage",
    "workflow_id",
    "workflow_inputs",
    "stage_loop_counts",
    "tracker",
    "tool_registry",
    "config_loader",
    "visualizer",
    "show_details",
    "detail_console",
    "stream_callback",
})


def initialize_state(
    input_data: Dict[str, Any],
    workflow_id: Optional[str] = None,
    tracker: Optional[TrackerProtocol] = None,
    tool_registry: Optional[DomainToolRegistryProtocol] = None,
    config_loader: Optional[ConfigLoaderProtocol] = None,
) -> WorkflowExecutionContext:
    """Create and initialize workflow state as a plain dict.

    Args:
        input_data: Input data for workflow (topic, query, etc.)
        workflow_id: Optional workflow execution ID
        tracker: Optional ExecutionTracker instance
        tool_registry: Optional ToolRegistry instance
        config_loader: Optional ConfigLoader instance

    Returns:
        Initialized state dict ready for LangGraph execution
    """
    # Validate that input_data doesn't overwrite framework-reserved keys
    conflicting_keys = set(input_data.keys()) & RESERVED_STATE_KEYS
    if conflicting_keys:
        raise ValueError(
            f"input_data contains reserved state keys that would overwrite "
            f"framework-managed state: {sorted(conflicting_keys)}. "
            f"Reserved keys: {sorted(RESERVED_STATE_KEYS)}"
        )

    state: Dict[str, Any] = {
        "stage_outputs": {},
        "current_stage": "",
        "workflow_inputs": input_data,
    }

    state["workflow_id"] = workflow_id or f"wf-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"
    if tracker:
        state["tracker"] = tracker
    if tool_registry:
        state["tool_registry"] = tool_registry
    if config_loader:
        state["config_loader"] = config_loader

    return state  # type: ignore[return-value]


def create_init_node() -> Callable[[LangGraphWorkflowState], Dict[str, Any]]:
    """Create LangGraph initialization node.

    Creates a node function that initializes workflow state fields
    at the start of graph execution. This ensures state is properly
    initialized even if created externally.

    Returns:
        Callable node function for LangGraph (accepts LangGraphWorkflowState, returns dict update)

    Example:
        >>> init_node = create_init_node()
        >>> graph.add_node("init", init_node)
    """
    def init_node(state: LangGraphWorkflowState) -> Dict[str, Any]:
        """Initialize workflow execution state.

        Ensures stage_outputs and workflow_id are properly initialized
        even if the state was created externally without them.

        Args:
            state: Current workflow state (LangGraphWorkflowState dataclass from LangGraph)

        Returns:
            Dict with fields to update in state
        """
        updates = {}

        # Initialize stage outputs tracker if not present or None
        if state.stage_outputs is None:
            updates["stage_outputs"] = {}  # type: ignore[unreachable]

        # Set workflow ID if not present
        if not state.workflow_id or state.workflow_id == "":
            updates["workflow_id"] = f"wf-{uuid.uuid4().hex[:UUID_HEX_SHORT_LENGTH]}"

        return updates

    return init_node
