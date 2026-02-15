"""Domain state and execution context separation for checkpoint/resume.

This module provides the fundamental separation between:
- WorkflowDomainState: Pure serializable domain data (can be checkpointed)
- ExecutionContext: Infrastructure components (recreated on resume)

This separation is CRITICAL for checkpoint/resume capability (m3.2-06).

Design Principles:
- Domain state contains ONLY serializable workflow data
- ExecutionContext contains ONLY infrastructure components
- Clear boundary enables checkpoint serialization
- Infrastructure can be recreated from configuration on resume

Example:
    >>> domain = WorkflowDomainState(workflow_id="wf-123", input="analyze data")
    >>> context = ExecutionContext(tracker=my_tracker, tool_registry=my_registry)
    >>> # Save checkpoint
    >>> checkpoint = domain.to_dict()  # Only domain data serialized
    >>> json.dump(checkpoint, file)
    >>>
    >>> # Resume from checkpoint
    >>> domain = WorkflowDomainState.from_dict(json.load(file))
    >>> context = ExecutionContext(...) # Recreate infrastructure
"""
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from src.shared.constants.execution import DEFAULT_VERSION, WORKFLOW_ID_PREFIX
from src.shared.core.protocols import (  # noqa: F401
    ConfigLoaderProtocol,
    DomainToolRegistryProtocol,
    TrackerProtocol,
    VisualizerProtocol,
)

# Workflow ID format constants
WORKFLOW_ID_HEX_LENGTH = 12  # Length of hex portion in workflow IDs (wf-<12 hex chars>)

# ---------------------------------------------------------------------------
# Protocol definitions for InfrastructureContext field types
# (canonical in src.shared.core.protocols, re-exported above for compat)
# ---------------------------------------------------------------------------

@dataclass
class WorkflowDomainState:
    """Pure serializable workflow domain state.

    Contains ONLY data that represents the workflow's business logic state.
    All fields are JSON-serializable for checkpoint persistence.

    This state can be:
    - Saved to disk/database as checkpoints
    - Serialized to JSON
    - Transmitted over network
    - Loaded to resume execution

    Core State Fields:
        stage_outputs: Outputs from completed stages
        current_stage: Currently executing stage name
        workflow_id: Unique workflow execution ID

    Workflow Inputs (all optional):
        topic: Research/analysis topic
        depth: Analysis depth level
        focus_areas: List of focus areas
        query: User query/question
        input: Generic input data
        context: Execution context data
        data: Additional data payload

    Metadata:
        version: State schema version for migrations
        created_at: Timestamp when state was created
        metadata: Additional metadata dictionary

    Example:
        >>> state = WorkflowDomainState(
        ...     workflow_id="wf-abc123",
        ...     input="Analyze market trends",
        ...     topic="Market Analysis"
        ... )
        >>> state.set_stage_output("research", {"findings": [...]})
        >>>
        >>> # Serialize for checkpoint
        >>> checkpoint = state.to_dict()
        >>> json.dump(checkpoint, file)
        >>>
        >>> # Restore from checkpoint
        >>> restored = WorkflowDomainState.from_dict(checkpoint)
    """

    # Core workflow state (required fields with defaults)
    stage_outputs: Dict[str, Any] = field(default_factory=dict)
    current_stage: str = ""
    workflow_id: str = field(default_factory=lambda: f"{WORKFLOW_ID_PREFIX}{uuid.uuid4().hex[:WORKFLOW_ID_HEX_LENGTH]}")
    stage_loop_counts: Dict[str, int] = field(default_factory=dict)

    # Common workflow inputs (all optional)
    topic: Optional[str] = None
    depth: Optional[str] = None
    focus_areas: Optional[List[str]] = None
    query: Optional[str] = None
    input: Optional[str] = None
    context: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    # Arbitrary user-supplied workflow inputs (survives LangGraph dataclass coercion)
    workflow_inputs: Dict[str, Any] = field(default_factory=dict)

    # Metadata and versioning
    version: str = DEFAULT_VERSION
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate state after initialization."""
        # Ensure focus_areas is a list if provided
        if self.focus_areas is not None and not isinstance(self.focus_areas, list):
            self.focus_areas = [self.focus_areas]  # type: ignore

        # Validate workflow_id format
        if not self.workflow_id.startswith(WORKFLOW_ID_PREFIX):
            self.workflow_id = f"{WORKFLOW_ID_PREFIX}{self.workflow_id}"

        # Ensure stage_outputs is a dict
        if not isinstance(self.stage_outputs, dict):
            self.stage_outputs = {}  # type: ignore

    def set_stage_output(self, stage_name: str, output: Any) -> None:
        """Set output for a completed stage.

        Args:
            stage_name: Name of the stage
            output: Stage output data (must be serializable)

        Example:
            >>> state.set_stage_output("research", {"findings": [...]})
        """
        self.stage_outputs[stage_name] = output
        self.current_stage = stage_name

    def get_stage_output(self, stage_name: str, default: Any = None) -> Any:
        """Get output from a completed stage.

        Args:
            stage_name: Name of the stage
            default: Default value if stage not found

        Returns:
            Stage output data or default

        Example:
            >>> research_output = state.get_stage_output("research")
        """
        return self.stage_outputs.get(stage_name, default)

    def has_stage_output(self, stage_name: str) -> bool:
        """Check if a stage has completed and has output.

        Args:
            stage_name: Name of the stage

        Returns:
            True if stage has output, False otherwise

        Example:
            >>> if state.has_stage_output("research"):
            ...     print("Research complete")
        """
        return stage_name in self.stage_outputs

    def get_previous_outputs(self) -> Dict[str, Any]:
        """Get all previous stage outputs.

        Returns:
            Dictionary of all stage outputs

        Example:
            >>> previous = state.get_previous_outputs()
            >>> research_data = previous.get("research")
        """
        return self.stage_outputs.copy()

    def to_dict(self, exclude_none: bool = False, exclude_internal: bool = False) -> Dict[str, Any]:
        """Convert state to dictionary for serialization.

        All fields are guaranteed serializable (no infrastructure objects).

        Args:
            exclude_none: Exclude None values from output
            exclude_internal: Accepted for backward compatibility (no-op,
                domain state has no internal/infrastructure fields)

        Returns:
            Dictionary representation of state (JSON-serializable)

        Example:
            >>> state_dict = state.to_dict(exclude_none=True)
            >>> json.dump(state_dict, file)  # Safe - all fields serializable
        """
        from dataclasses import fields

        state_dict = {}
        for f in fields(self):
            key = f.name
            value = getattr(self, key)

            # Skip None values if requested
            if exclude_none and value is None:
                continue

            # Handle datetime serialization
            if isinstance(value, datetime):
                value = value.isoformat()

            state_dict[key] = value

        return state_dict

    def to_typed_dict(self) -> Dict[str, Any]:
        """Convert to dict for LangGraph node compatibility.

        LangGraph nodes call ``state.to_typed_dict()`` to obtain a plain
        dict that can be passed to stage executors.  This is an alias for
        ``to_dict()`` so that ``WorkflowDomainState`` satisfies the same
        duck-typing contract as ``LangGraphWorkflowState``.
        """
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkflowDomainState':
        """Create WorkflowDomainState from dictionary.

        Used for deserializing checkpoints.

        Args:
            data: State dictionary (from checkpoint or serialization)

        Returns:
            WorkflowDomainState instance

        Example:
            >>> checkpoint = json.load(file)
            >>> state = WorkflowDomainState.from_dict(checkpoint)
        """
        # Handle datetime deserialization
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])

        # Filter to only known domain fields
        known_fields = {
            "stage_outputs", "current_stage", "workflow_id", "stage_loop_counts",
            "topic", "depth", "focus_areas", "query", "input", "context", "data",
            "workflow_inputs", "version", "created_at", "metadata"
        }

        filtered_data = {k: v for k, v in data.items() if k in known_fields}

        # Store extra fields in workflow_inputs so they reach agents
        extra_fields = {k: v for k, v in data.items() if k not in known_fields}
        if extra_fields:
            existing_wi = filtered_data.get("workflow_inputs", {})
            if isinstance(existing_wi, dict):
                existing_wi.update(extra_fields)
            else:
                existing_wi = extra_fields
            filtered_data["workflow_inputs"] = existing_wi

        return cls(**filtered_data)

    def validate(self) -> tuple[bool, List[str]]:
        """Validate state consistency.

        Returns:
            Tuple of (is_valid, error_messages)

        Example:
            >>> valid, errors = state.validate()
            >>> if not valid:
            ...     print("Validation errors:", errors)
        """
        errors = []

        # Validate workflow_id format
        if not self.workflow_id or not self.workflow_id.startswith("wf-"):
            errors.append(f"Invalid workflow_id format: {self.workflow_id}")

        # Validate stage_outputs is a dict
        if not isinstance(self.stage_outputs, dict):
            errors.append(f"stage_outputs must be a dict, got {type(self.stage_outputs)}")  # type: ignore

        # Validate focus_areas is a list (if set)
        if self.focus_areas is not None and not isinstance(self.focus_areas, list):
            errors.append(f"focus_areas must be a list, got {type(self.focus_areas)}")  # type: ignore

        # Validate version format
        if not self.version or not isinstance(self.version, str):
            errors.append(f"Invalid version format: {self.version}")

        return len(errors) == 0, errors

    def copy(self) -> 'WorkflowDomainState':
        """Create a copy of the state with deep-copied mutable fields.

        Returns:
            New WorkflowDomainState instance with independent copied data

        Example:
            >>> new_state = state.copy()
            >>> # Modifying new_state won't affect original
        """
        import copy as copy_module
        state_dict = self.to_dict()
        # Deep copy mutable fields to ensure independence
        if "stage_outputs" in state_dict:
            state_dict["stage_outputs"] = copy_module.deepcopy(state_dict["stage_outputs"])
        if "metadata" in state_dict:
            state_dict["metadata"] = copy_module.deepcopy(state_dict["metadata"])
        if "workflow_inputs" in state_dict:
            state_dict["workflow_inputs"] = copy_module.deepcopy(state_dict["workflow_inputs"])
        if "stage_loop_counts" in state_dict:
            state_dict["stage_loop_counts"] = copy_module.deepcopy(state_dict["stage_loop_counts"])
        if "focus_areas" in state_dict and state_dict["focus_areas"] is not None:
            state_dict["focus_areas"] = list(state_dict["focus_areas"])
        return WorkflowDomainState.from_dict(state_dict)

    def __repr__(self) -> str:
        """String representation of state."""
        return (
            f"WorkflowDomainState(workflow_id='{self.workflow_id}', "
            f"current_stage='{self.current_stage}', "
            f"num_stages={len(self.stage_outputs)}, "
            f"version='{self.version}')"
        )


@dataclass
class InfrastructureContext:
    """Infrastructure components for workflow execution.

    Contains ONLY non-serializable infrastructure objects that are
    created/injected at runtime and recreated on workflow resume.

    This context is NOT checkpointed - it's recreated from configuration
    when resuming a workflow from a checkpoint.

    Infrastructure Components:
        tracker: ExecutionTracker for observability
        tool_registry: ToolRegistry for agent tool access
        config_loader: ConfigLoader for stage/agent configurations
        visualizer: Optional workflow visualizer

    Design:
        - All fields are optional (can execute with minimal infrastructure)
        - None of these objects are serialized in checkpoints
        - On resume: recreate from config, not from checkpoint

    Example:
        >>> from src.observability.tracker import ExecutionTracker
        >>> from src.tools.registry import ToolRegistry
        >>> from src.workflow.config_loader import ConfigLoader
        >>>
        >>> # Create infrastructure
        >>> context = InfrastructureContext(
        ...     tracker=ExecutionTracker(),
        ...     tool_registry=ToolRegistry(),
        ...     config_loader=ConfigLoader()
        ... )
    """

    # Infrastructure components (all optional, typed via Protocols)
    tracker: Optional[TrackerProtocol] = None
    tool_registry: Optional[DomainToolRegistryProtocol] = None
    config_loader: Optional[ConfigLoaderProtocol] = None
    visualizer: Optional[VisualizerProtocol] = None

    def __repr__(self) -> str:
        """String representation of context."""
        components = []
        if self.tracker:
            components.append("tracker")
        if self.tool_registry:
            components.append("tool_registry")
        if self.config_loader:
            components.append("config_loader")
        if self.visualizer:
            components.append("visualizer")

        return f"InfrastructureContext(components=[{', '.join(components)}])"


class DomainExecutionContext(InfrastructureContext):
    """Backward-compatible alias.

    DEPRECATED: Use InfrastructureContext directly.
    """
    def __init_subclass__(cls, **kwargs: Any) -> None:
        import warnings
        warnings.warn(
            "DomainExecutionContext is deprecated. Use InfrastructureContext.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init_subclass__(**kwargs)


def __getattr__(name: str) -> object:
    """Module-level __getattr__ for backward-compatible access to ExecutionContext."""
    if name == "ExecutionContext":
        import warnings
        warnings.warn(
            "Importing ExecutionContext from src.workflow.domain_state is deprecated. "
            "Use InfrastructureContext (or DomainExecutionContext) instead. "
            "For the agent/tracking execution context, use src.shared.core.context.ExecutionContext.",
            DeprecationWarning,
            stacklevel=2,
        )
        return InfrastructureContext
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_initial_domain_state(**kwargs: Any) -> WorkflowDomainState:
    """Create initial workflow domain state with given inputs.

    Convenience function for creating state with custom inputs.

    Args:
        **kwargs: Any workflow input fields

    Returns:
        Initialized WorkflowDomainState

    Example:
        >>> state = create_initial_domain_state(
        ...     input="Analyze market trends",
        ...     topic="Market Analysis",
        ...     depth="comprehensive"
        ... )
    """
    return WorkflowDomainState(**kwargs)


def merge_domain_states(
    base_state: WorkflowDomainState,
    updates: Dict[str, Any]
) -> WorkflowDomainState:
    """Merge updates into base domain state.

    Creates a new state with updates applied to base state.

    Args:
        base_state: Base workflow domain state
        updates: Dictionary of field updates

    Returns:
        New WorkflowDomainState with updates applied

    Example:
        >>> updated_state = merge_domain_states(
        ...     base_state,
        ...     {"current_stage": "analysis", "data": new_data}
        ... )
    """
    state_dict = base_state.to_dict()
    state_dict.update(updates)
    return WorkflowDomainState.from_dict(state_dict)
