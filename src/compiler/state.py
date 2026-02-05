"""Workflow state management with validation and versioning.

DEPRECATED: This module provides a compatibility facade over the new separated
domain state and execution context architecture. New code should use:
- WorkflowDomainState for serializable domain data
- ExecutionContext for infrastructure components

See: src/compiler/domain_state.py for the new architecture.

Migration Path:
    Old (deprecated):
        >>> state = WorkflowState(workflow_id="wf-123", tracker=my_tracker)
        >>> state.set_stage_output("research", data)

    New (recommended):
        >>> domain = WorkflowDomainState(workflow_id="wf-123")
        >>> context = ExecutionContext(tracker=my_tracker)
        >>> domain.set_stage_output("research", data)
"""
import warnings
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.compiler.domain_state import (
    WorkflowDomainState,
    InfrastructureContext,
    create_initial_domain_state,
    merge_domain_states
)

# Backward-compatible alias for external consumers
ExecutionContext = InfrastructureContext


class WorkflowState:
    """DEPRECATED: Compatibility facade over separated domain state and execution context.

    This class provides backward compatibility during migration to the new
    separated architecture. It internally uses:
    - WorkflowDomainState for serializable domain data
    - ExecutionContext for infrastructure components

    **DEPRECATION WARNING**: This facade is maintained for backward compatibility
    but will be removed in a future version. New code should use:
    - WorkflowDomainState for domain state
    - ExecutionContext for infrastructure

    The separation enables checkpoint/resume by clearly distinguishing:
    - What gets saved (domain state)
    - What gets recreated (execution context)

    Migration:
        Old (deprecated):
            >>> state = WorkflowState(workflow_id="wf-123", tracker=tracker)

        New (recommended):
            >>> domain = WorkflowDomainState(workflow_id="wf-123")
            >>> context = ExecutionContext(tracker=tracker)

    Core State Fields (delegated to domain):
        stage_outputs: Outputs from completed stages
        current_stage: Currently executing stage name
        workflow_id: Unique workflow execution ID

    Infrastructure (delegated to context):
        tracker: ExecutionTracker instance (optional)
        tool_registry: ToolRegistry instance (optional)
        config_loader: ConfigLoader instance (optional)
        visualizer: Optional visualizer instance

    Workflow Inputs (delegated to domain):
        topic, depth, focus_areas, query, input, context, data

    Metadata (delegated to domain):
        version, created_at, metadata
    """

    def __init__(self, **kwargs: Any):
        """Initialize workflow state from keyword arguments.

        Args:
            **kwargs: Any combination of domain and context fields
        """
        warnings.warn(
            "WorkflowState is deprecated. Use WorkflowDomainState for domain data "
            "and InfrastructureContext for infrastructure components. "
            "See src/compiler/domain_state.py for the new architecture.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Separate domain and context fields from kwargs
        domain_fields = {
            "stage_outputs", "current_stage", "workflow_id",
            "topic", "depth", "focus_areas", "query", "input", "context", "data",
            "version", "created_at", "metadata"
        }
        context_fields = {
            "tracker", "tool_registry", "config_loader", "visualizer"
        }

        # Extract domain kwargs
        domain_kwargs = {k: v for k, v in kwargs.items() if k in domain_fields}

        # Extract context kwargs
        context_kwargs = {k: v for k, v in kwargs.items() if k in context_fields}

        # Create separated state objects
        self._domain = WorkflowDomainState(**domain_kwargs) if domain_kwargs else WorkflowDomainState()
        self._context = ExecutionContext(**context_kwargs) if context_kwargs else ExecutionContext()

    @property
    def domain(self) -> WorkflowDomainState:
        """Get domain state (serializable workflow data).

        Returns:
            WorkflowDomainState instance

        Example:
            >>> checkpoint = state.domain.to_dict()  # Only domain data
            >>> json.dump(checkpoint, file)
        """
        return self._domain

    @property
    def execution_context(self) -> ExecutionContext:
        """Get execution context (infrastructure components).

        Returns:
            ExecutionContext instance

        Example:
            >>> tracker = state.execution_context.tracker
        """
        return self._context

    # Property accessors for domain fields (delegate to _domain)
    @property
    def stage_outputs(self) -> Dict[str, Any]:
        """Get stage outputs (delegates to domain)."""
        return self._domain.stage_outputs

    @stage_outputs.setter
    def stage_outputs(self, value: Dict[str, Any]) -> None:
        """Set stage outputs (delegates to domain)."""
        self._domain.stage_outputs = value

    @property
    def current_stage(self) -> str:
        """Get current stage (delegates to domain)."""
        return self._domain.current_stage

    @current_stage.setter
    def current_stage(self, value: str) -> None:
        """Set current stage (delegates to domain)."""
        self._domain.current_stage = value

    @property
    def workflow_id(self) -> str:
        """Get workflow ID (delegates to domain)."""
        return self._domain.workflow_id

    @workflow_id.setter
    def workflow_id(self, value: str) -> None:
        """Set workflow ID (delegates to domain)."""
        self._domain.workflow_id = value

    @property
    def topic(self) -> Optional[str]:
        """Get topic (delegates to domain)."""
        return self._domain.topic

    @topic.setter
    def topic(self, value: Optional[str]) -> None:
        """Set topic (delegates to domain)."""
        self._domain.topic = value

    @property
    def depth(self) -> Optional[str]:
        """Get depth (delegates to domain)."""
        return self._domain.depth

    @depth.setter
    def depth(self, value: Optional[str]) -> None:
        """Set depth (delegates to domain)."""
        self._domain.depth = value

    @property
    def focus_areas(self) -> Optional[List[str]]:
        """Get focus areas (delegates to domain)."""
        return self._domain.focus_areas

    @focus_areas.setter
    def focus_areas(self, value: Optional[List[str]]) -> None:
        """Set focus areas (delegates to domain)."""
        self._domain.focus_areas = value

    @property
    def query(self) -> Optional[str]:
        """Get query (delegates to domain)."""
        return self._domain.query

    @query.setter
    def query(self, value: Optional[str]) -> None:
        """Set query (delegates to domain)."""
        self._domain.query = value

    @property
    def input(self) -> Optional[str]:
        """Get input (delegates to domain)."""
        return self._domain.input

    @input.setter
    def input(self, value: Optional[str]) -> None:
        """Set input (delegates to domain)."""
        self._domain.input = value

    @property
    def context(self) -> Optional[str]:
        """Get context (delegates to domain)."""
        return self._domain.context

    @context.setter
    def context(self, value: Optional[str]) -> None:
        """Set context (delegates to domain)."""
        self._domain.context = value

    @property
    def data(self) -> Optional[Any]:
        """Get data (delegates to domain)."""
        return self._domain.data

    @data.setter
    def data(self, value: Optional[Any]) -> None:
        """Set data (delegates to domain)."""
        self._domain.data = value

    @property
    def version(self) -> str:
        """Get version (delegates to domain)."""
        return self._domain.version

    @version.setter
    def version(self, value: str) -> None:
        """Set version (delegates to domain)."""
        self._domain.version = value

    @property
    def created_at(self) -> datetime:
        """Get created_at (delegates to domain)."""
        return self._domain.created_at

    @created_at.setter
    def created_at(self, value: datetime) -> None:
        """Set created_at (delegates to domain)."""
        self._domain.created_at = value

    @property
    def metadata(self) -> Dict[str, Any]:
        """Get metadata (delegates to domain)."""
        return self._domain.metadata

    @metadata.setter
    def metadata(self, value: Dict[str, Any]) -> None:
        """Set metadata (delegates to domain)."""
        self._domain.metadata = value

    # Property accessors for context fields (delegate to _context)
    @property
    def tracker(self) -> Optional[Any]:
        """Get tracker (delegates to context)."""
        return self._context.tracker

    @tracker.setter
    def tracker(self, value: Optional[Any]) -> None:
        """Set tracker (delegates to context)."""
        self._context.tracker = value

    @property
    def tool_registry(self) -> Optional[Any]:
        """Get tool_registry (delegates to context)."""
        return self._context.tool_registry

    @tool_registry.setter
    def tool_registry(self, value: Optional[Any]) -> None:
        """Set tool_registry (delegates to context)."""
        self._context.tool_registry = value

    @property
    def config_loader(self) -> Optional[Any]:
        """Get config_loader (delegates to context)."""
        return self._context.config_loader

    @config_loader.setter
    def config_loader(self, value: Optional[Any]) -> None:
        """Set config_loader (delegates to context)."""
        self._context.config_loader = value

    @property
    def visualizer(self) -> Optional[Any]:
        """Get visualizer (delegates to context)."""
        return self._context.visualizer

    @visualizer.setter
    def visualizer(self, value: Optional[Any]) -> None:
        """Set visualizer (delegates to context)."""
        self._context.visualizer = value

    def set_stage_output(self, stage_name: str, output: Any) -> None:
        """Set output for a completed stage (delegates to domain).

        Args:
            stage_name: Name of the stage
            output: Stage output data

        Example:
            >>> state.set_stage_output("research", {"findings": [...]})
        """
        self._domain.set_stage_output(stage_name, output)

    def get_stage_output(self, stage_name: str, default: Any = None) -> Any:
        """Get output from a completed stage (delegates to domain).

        Args:
            stage_name: Name of the stage
            default: Default value if stage not found

        Returns:
            Stage output data or default

        Example:
            >>> research_output = state.get_stage_output("research")
        """
        return self._domain.get_stage_output(stage_name, default)

    def has_stage_output(self, stage_name: str) -> bool:
        """Check if a stage has completed and has output (delegates to domain).

        Args:
            stage_name: Name of the stage

        Returns:
            True if stage has output, False otherwise

        Example:
            >>> if state.has_stage_output("research"):
            ...     print("Research complete")
        """
        return self._domain.has_stage_output(stage_name)

    def get_previous_outputs(self) -> Dict[str, Any]:
        """Get all previous stage outputs (delegates to domain).

        Returns:
            Dictionary of all stage outputs

        Example:
            >>> previous = state.get_previous_outputs()
            >>> research_data = previous.get("research")
        """
        return self._domain.get_previous_outputs()

    def to_dict(self, exclude_none: bool = False, exclude_internal: bool = False) -> Dict[str, Any]:
        """Convert state to dictionary (delegates to domain/context).

        Args:
            exclude_none: Exclude None values
            exclude_internal: Exclude internal objects (tracker, registry, loader)

        Returns:
            Dictionary representation of state

        Note:
            When exclude_internal=True, only domain state is included (serializable).
            This is the recommended mode for checkpointing.

        Example:
            >>> # For checkpointing (domain only)
            >>> checkpoint = state.to_dict(exclude_none=True, exclude_internal=True)
            >>> json.dump(checkpoint, file)
            >>>
            >>> # For full state (including infrastructure)
            >>> full_state = state.to_dict()
        """
        if exclude_internal:
            # Only domain state (serializable)
            return self._domain.to_dict(exclude_none=exclude_none)
        else:
            # Combine domain and context
            state_dict = self._domain.to_dict(exclude_none=exclude_none)

            # Add context fields
            if self._context.tracker is not None or not exclude_none:
                state_dict["tracker"] = self._context.tracker
            if self._context.tool_registry is not None or not exclude_none:
                state_dict["tool_registry"] = self._context.tool_registry
            if self._context.config_loader is not None or not exclude_none:
                state_dict["config_loader"] = self._context.config_loader
            if self._context.visualizer is not None or not exclude_none:
                state_dict["visualizer"] = self._context.visualizer

            return state_dict

    def to_typed_dict(self) -> Dict[str, Any]:
        """Convert to TypedDict-compatible dictionary for LangGraph.

        LangGraph expects a plain dict, so this converts the dataclass
        to a dict format compatible with the existing TypedDict interface.

        Returns:
            Dictionary compatible with LangGraph StateGraph

        Example:
            >>> graph_state = state.to_typed_dict()
            >>> result = graph.invoke(graph_state)
        """
        return self.to_dict(exclude_none=False, exclude_internal=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkflowState':
        """Create WorkflowState from dictionary (creates separated domain/context).

        Args:
            data: State dictionary

        Returns:
            WorkflowState instance with separated domain and context

        Example:
            >>> # From checkpoint (domain only)
            >>> state = WorkflowState.from_dict(checkpoint_data)
            >>>
            >>> # From full state (domain + context)
            >>> state = WorkflowState.from_dict(full_state_data)
        """
        # Separate domain and context fields
        domain_fields = {
            "stage_outputs", "current_stage", "workflow_id",
            "topic", "depth", "focus_areas", "query", "input", "context", "data",
            "version", "created_at", "metadata"
        }
        context_fields = {
            "tracker", "tool_registry", "config_loader", "visualizer"
        }

        # Extract domain data
        domain_data = {k: v for k, v in data.items() if k in domain_fields}

        # Extract context data
        context_data = {k: v for k, v in data.items() if k in context_fields}

        # Create WorkflowState with separated structures
        state = cls()  # Creates empty domain and context
        state._domain = WorkflowDomainState.from_dict(domain_data)
        state._context = ExecutionContext(**context_data)

        return state

    def validate(self) -> tuple[bool, List[str]]:
        """Validate state consistency (delegates to domain).

        Returns:
            Tuple of (is_valid, error_messages)

        Example:
            >>> valid, errors = state.validate()
            >>> if not valid:
            ...     print("Validation errors:", errors)
        """
        return self._domain.validate()

    def copy(self) -> 'WorkflowState':
        """Create a shallow copy of the state.

        Returns:
            New WorkflowState instance with copied domain and context

        Example:
            >>> new_state = state.copy()
        """
        new_state = WorkflowState()
        new_state._domain = self._domain.copy()
        # Context is not deep-copied (infrastructure references are shared)
        new_state._context = ExecutionContext(
            tracker=self._context.tracker,
            tool_registry=self._context.tool_registry,
            config_loader=self._context.config_loader,
            visualizer=self._context.visualizer
        )
        return new_state

    def __repr__(self) -> str:
        """String representation of state."""
        return (
            f"WorkflowState(workflow_id='{self.workflow_id}', "
            f"current_stage='{self.current_stage}', "
            f"num_stages={len(self.stage_outputs)}, "
            f"version='{self.version}')"
        )

    # Dict-like interface for backward compatibility with LangGraph
    def __getitem__(self, key: str) -> Any:
        """Get item like a dict for backward compatibility.

        Args:
            key: Field name

        Returns:
            Field value

        Raises:
            KeyError: If field doesn't exist

        Example:
            >>> workflow_id = state["workflow_id"]  # Same as state.workflow_id
        """
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(f"'{key}' not found in WorkflowState")

    def __setitem__(self, key: str, value: Any) -> None:
        """Set item like a dict for backward compatibility.

        Args:
            key: Field name
            value: Field value

        Example:
            >>> state["current_stage"] = "analysis"  # Same as state.current_stage = "analysis"
        """
        setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        """Check if key exists in state.

        Args:
            key: Field name

        Returns:
            True if field exists

        Example:
            >>> if "tracker" in state:
            ...     print("Tracker available")
        """
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """Get item with default like a dict.

        Args:
            key: Field name
            default: Default value if key not found

        Returns:
            Field value or default

        Example:
            >>> tracker = state.get("tracker", None)
        """
        return getattr(self, key, default)


def create_initial_state(**kwargs: Any) -> WorkflowState:
    """Create initial workflow state with given inputs.

    Convenience function for creating state with custom inputs.

    Args:
        **kwargs: Any workflow input fields

    Returns:
        Initialized WorkflowState

    Example:
        >>> state = create_initial_state(
        ...     input="Analyze market trends",
        ...     topic="Market Analysis",
        ...     depth="comprehensive"
        ... )
    """
    return WorkflowState(**kwargs)


def merge_states(base_state: WorkflowState, updates: Dict[str, Any]) -> WorkflowState:
    """Merge updates into base state.

    Creates a new state with updates applied to base state.

    Args:
        base_state: Base workflow state
        updates: Dictionary of field updates

    Returns:
        New WorkflowState with updates applied

    Example:
        >>> updated_state = merge_states(
        ...     base_state,
        ...     {"current_stage": "analysis", "data": new_data}
        ... )
    """
    state_dict = base_state.to_dict()
    state_dict.update(updates)
    return WorkflowState.from_dict(state_dict)
