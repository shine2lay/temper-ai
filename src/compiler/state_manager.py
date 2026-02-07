"""State management for workflow execution.

Provides centralized state initialization, validation, and utilities
for LangGraph compiler and executors.
"""
import uuid
from typing import Any, Callable, Dict, List, Optional

from src.compiler.domain_state import (
    ConfigLoaderProtocol,
    ToolRegistryProtocol,
    TrackerProtocol,
)
from src.compiler.executors.base import WorkflowStateDict  # canonical definition
from src.compiler.langgraph_state import LangGraphWorkflowState


class StateManager:
    """Manages workflow state initialization and operations.

    Centralizes state-related logic that was previously scattered across
    the compiler and executors. Provides a clean interface for:
    - Creating initial workflow state
    - State initialization nodes for LangGraph
    - State validation
    - State utilities

    Example:
        >>> manager = StateManager()
        >>> state = manager.initialize_state({"input": "data"})
        >>> init_node = manager.create_init_node()
    """

    def __init__(self) -> None:
        """Initialize state manager."""
        pass

    def initialize_state(
        self,
        input_data: Dict[str, Any],
        workflow_id: Optional[str] = None,
        tracker: Optional[TrackerProtocol] = None,
        tool_registry: Optional[ToolRegistryProtocol] = None,
        config_loader: Optional[ConfigLoaderProtocol] = None,
    ) -> WorkflowStateDict:
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
        state: Dict[str, Any] = {
            "stage_outputs": {},
            "current_stage": "",
            **input_data,
        }

        state["workflow_id"] = workflow_id or f"wf-{uuid.uuid4().hex[:12]}"
        if tracker:
            state["tracker"] = tracker
        if tool_registry:
            state["tool_registry"] = tool_registry
        if config_loader:
            state["config_loader"] = config_loader

        return state  # type: ignore[return-value]

    def create_init_node(self) -> Callable[[LangGraphWorkflowState], Dict[str, Any]]:
        """Create LangGraph initialization node.

        Creates a node function that initializes workflow state fields
        at the start of graph execution. This ensures state is properly
        initialized even if created externally.

        Returns:
            Callable node function for LangGraph (accepts LangGraphWorkflowState, returns dict update)

        Example:
            >>> init_node = manager.create_init_node()
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
                updates["workflow_id"] = f"wf-{uuid.uuid4().hex[:12]}"

            return updates

        return init_node

    def validate_state(self, state: Dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate workflow state consistency.

        Args:
            state: Workflow state dict to validate

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors: list[str] = []
        if "stage_outputs" not in state:
            errors.append("Missing stage_outputs")
        if hasattr(state, "validate"):
            return state.validate()  # type: ignore[union-attr]
        return (len(errors) == 0, errors)

    def prepare_stage_input(
        self,
        state: Dict[str, Any],
        include_previous_outputs: bool = True
    ) -> Dict[str, Any]:
        """Prepare input data for stage execution.

        Args:
            state: Current workflow state
            include_previous_outputs: Whether to include outputs from previous stages

        Returns:
            Dictionary of input data for stage
        """
        # Exclude infrastructure keys
        internal_keys = {"tracker", "tool_registry", "config_loader", "visualizer"}
        stage_input = {k: v for k, v in state.items() if k not in internal_keys}

        if not include_previous_outputs:
            stage_input.pop("stage_outputs", None)

        return stage_input

    def merge_stage_output(
        self,
        state: Dict[str, Any],
        stage_name: str,
        output: Any
    ) -> Dict[str, Any]:
        """Merge stage output into workflow state.

        Args:
            state: Current workflow state
            stage_name: Name of the completed stage
            output: Output data from the stage

        Returns:
            Updated workflow state
        """
        state.setdefault("stage_outputs", {})[stage_name] = output
        state["current_stage"] = stage_name
        return state

    def get_state_snapshot(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Get serializable snapshot of workflow state.

        Args:
            state: Workflow state

        Returns:
            Serializable state snapshot (infrastructure keys excluded)
        """
        internal_keys = {"tracker", "tool_registry", "config_loader", "visualizer"}
        return {k: v for k, v in state.items() if k not in internal_keys and v is not None}

    def restore_state_from_snapshot(
        self,
        snapshot: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Restore workflow state from snapshot.

        Args:
            snapshot: State snapshot dictionary

        Returns:
            Restored state dict
        """
        state = {"stage_outputs": {}, "current_stage": "", **snapshot}
        return state
