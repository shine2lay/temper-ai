"""State management for workflow execution.

Provides centralized state initialization, validation, and utilities
for LangGraph compiler and executors.
"""
from typing import Dict, Any, Optional, Callable
import uuid

from src.compiler.state import WorkflowState, create_initial_state
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
        tracker: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        config_loader: Optional[Any] = None
    ) -> WorkflowState:
        """Create and initialize workflow state.

        Args:
            input_data: Input data for workflow (topic, query, etc.)
            workflow_id: Optional workflow execution ID
            tracker: Optional ExecutionTracker instance
            tool_registry: Optional ToolRegistry instance
            config_loader: Optional ConfigLoader instance

        Returns:
            Initialized WorkflowState ready for execution

        Example:
            >>> state = manager.initialize_state(
            ...     {"input": "Analyze market trends"},
            ...     workflow_id="wf-custom-123"
            ... )
        """
        # Prepare state kwargs
        state_kwargs = {**input_data}

        # Set workflow ID
        if workflow_id:
            state_kwargs["workflow_id"] = workflow_id

        # Set infrastructure components
        if tracker:
            state_kwargs["tracker"] = tracker
        if tool_registry:
            state_kwargs["tool_registry"] = tool_registry
        if config_loader:
            state_kwargs["config_loader"] = config_loader

        # Create state using factory function
        return create_initial_state(**state_kwargs)

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

    def validate_state(self, state: WorkflowState) -> tuple[bool, list[str]]:
        """Validate workflow state consistency.

        Args:
            state: Workflow state to validate

        Returns:
            Tuple of (is_valid, error_messages)

        Example:
            >>> valid, errors = manager.validate_state(state)
            >>> if not valid:
            ...     print(f"State validation failed: {errors}")
        """
        return state.validate()

    def prepare_stage_input(
        self,
        state: WorkflowState,
        include_previous_outputs: bool = True
    ) -> Dict[str, Any]:
        """Prepare input data for stage execution.

        Extracts relevant data from state for passing to stage executors.

        Args:
            state: Current workflow state
            include_previous_outputs: Whether to include outputs from previous stages

        Returns:
            Dictionary of input data for stage

        Example:
            >>> input_data = manager.prepare_stage_input(state)
            >>> executor.execute_stage(..., input_data=input_data)
        """
        # Convert state to dict, excluding internal objects
        stage_input = state.to_dict(exclude_internal=True)

        # Optionally exclude previous stage outputs for isolation
        if not include_previous_outputs:
            stage_input.pop("stage_outputs", None)

        return stage_input

    def merge_stage_output(
        self,
        state: WorkflowState,
        stage_name: str,
        output: Any
    ) -> WorkflowState:
        """Merge stage output into workflow state.

        Updates state with output from a completed stage.

        Args:
            state: Current workflow state
            stage_name: Name of the completed stage
            output: Output data from the stage

        Returns:
            Updated workflow state

        Example:
            >>> state = manager.merge_stage_output(
            ...     state,
            ...     "research",
            ...     {"findings": [...]}
            ... )
        """
        state.set_stage_output(stage_name, output)
        return state

    def get_state_snapshot(self, state: WorkflowState) -> Dict[str, Any]:
        """Get serializable snapshot of workflow state.

        Creates a JSON-serializable snapshot for persistence,
        logging, or debugging.

        Args:
            state: Workflow state

        Returns:
            Serializable state snapshot

        Example:
            >>> snapshot = manager.get_state_snapshot(state)
            >>> json.dump(snapshot, file)
        """
        return state.to_dict(exclude_none=True, exclude_internal=True)

    def restore_state_from_snapshot(
        self,
        snapshot: Dict[str, Any]
    ) -> WorkflowState:
        """Restore workflow state from snapshot.

        Recreates WorkflowState from a previously saved snapshot.

        Args:
            snapshot: State snapshot dictionary

        Returns:
            Restored WorkflowState instance

        Example:
            >>> snapshot = json.load(file)
            >>> state = manager.restore_state_from_snapshot(snapshot)
        """
        return WorkflowState.from_dict(snapshot)
