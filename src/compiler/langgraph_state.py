"""LangGraph-specific workflow state dataclass.

This module provides a combined dataclass that merges WorkflowDomainState
and ExecutionContext fields for use with LangGraph StateGraph.

LangGraph requires a dataclass schema for StateGraph. Since our architecture
separates domain state from execution context, we need a combined dataclass
for LangGraph execution while maintaining the separation for checkpointing.

Design:
- Inherits all fields from WorkflowDomainState (domain data)
- Adds all fields from ExecutionContext (infrastructure)
- Used only for LangGraph StateGraph definition
- Checkpointing still uses WorkflowDomainState for serialization
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime, UTC
import uuid


@dataclass
class LangGraphWorkflowState:
    """Combined workflow state for LangGraph execution.

    This dataclass combines fields from both WorkflowDomainState (domain data)
    and ExecutionContext (infrastructure) for use with LangGraph StateGraph.

    LangGraph requires a dataclass schema to properly handle state updates
    from nodes. This combined state allows nodes to access both domain data
    and infrastructure components while maintaining proper state management.

    Domain State Fields (from WorkflowDomainState):
        stage_outputs: Outputs from completed stages
        current_stage: Currently executing stage name
        workflow_id: Unique workflow execution ID
        topic, depth, focus_areas, query, input, context, data: Workflow inputs
        version, created_at, metadata: State metadata

    Infrastructure Fields (from ExecutionContext):
        tracker: ExecutionTracker for observability
        tool_registry: ToolRegistry for agent tool access
        config_loader: ConfigLoader for stage/agent configurations
        visualizer: Optional workflow visualizer

    Example:
        >>> # Used by LangGraph StateGraph
        >>> graph = StateGraph(LangGraphWorkflowState)
        >>> graph.add_node("init", init_node)
        >>> compiled = graph.compile()
        >>>
        >>> # Execute with combined state
        >>> result = compiled.invoke({
        ...     "topic": "Python typing",
        ...     "tracker": my_tracker,
        ...     "tool_registry": my_registry
        ... })
    """

    # Core workflow state (from WorkflowDomainState)
    stage_outputs: Dict[str, Any] = field(default_factory=dict)
    current_stage: str = ""
    workflow_id: str = field(default_factory=lambda: f"wf-{uuid.uuid4().hex[:12]}")

    # Common workflow inputs (from WorkflowDomainState)
    topic: Optional[str] = None
    depth: Optional[str] = None
    focus_areas: Optional[List[str]] = None
    query: Optional[str] = None
    input: Optional[str] = None
    context: Optional[str] = None
    data: Optional[Any] = None

    # Metadata and versioning (from WorkflowDomainState)
    version: str = "1.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Infrastructure components (from ExecutionContext)
    tracker: Optional[Any] = None
    tool_registry: Optional[Any] = None
    config_loader: Optional[Any] = None
    visualizer: Optional[Any] = None

    # Cache for to_dict() results (performance optimization)
    _dict_cache: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)
    _dict_cache_exclude_internal: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate state after initialization."""
        # Ensure focus_areas is a list if provided
        if self.focus_areas is not None and not isinstance(self.focus_areas, list):
            self.focus_areas = [self.focus_areas]  # type: ignore

        # Validate workflow_id format
        if not self.workflow_id.startswith("wf-"):
            self.workflow_id = f"wf-{self.workflow_id}"

        # Ensure stage_outputs is a dict
        if not isinstance(self.stage_outputs, dict):
            self.stage_outputs = {}  # type: ignore

    def __setattr__(self, name: str, value: Any) -> None:
        """Override setattr to invalidate cache on field modification.

        When any field is modified, cached dictionaries are invalidated
        to ensure to_dict() returns up-to-date state.

        Args:
            name: Field name
            value: New value
        """
        # Invalidate cache if modifying non-cache fields
        if not name.startswith('_dict_cache') and hasattr(self, '_dict_cache'):
            # Only invalidate if cache exists (avoid invalidating during __init__)
            if self._dict_cache is not None or self._dict_cache_exclude_internal is not None:
                object.__setattr__(self, '_dict_cache', None)
                object.__setattr__(self, '_dict_cache_exclude_internal', None)

        # Set the actual value
        object.__setattr__(self, name, value)

    def _invalidate_cache(self) -> None:
        """Invalidate dictionary cache when state is modified.

        This method should be called whenever any field is modified to ensure
        cached dictionaries are regenerated on next access.
        """
        self._dict_cache = None
        self._dict_cache_exclude_internal = None

    def to_dict(self, exclude_internal: bool = False) -> Dict[str, Any]:
        """Convert state to dictionary with caching.

        Args:
            exclude_internal: Exclude infrastructure objects (for serialization)

        Returns:
            Dictionary representation of state

        Note:
            When exclude_internal=True, only domain fields are included.
            This matches the interface expected by executors and checkpointing.

            Results are cached to avoid repeated dataclass field iteration.
            Cache is invalidated automatically when state is modified.

        Performance:
            - First call: O(n) where n = number of fields
            - Subsequent calls: O(1) (cache hit)

        Example:
            >>> # For executor (includes infrastructure)
            >>> state_dict = state.to_dict()
            >>>
            >>> # For checkpointing (domain only)
            >>> checkpoint = state.to_dict(exclude_internal=True)
        """
        # Check cache first - return shallow copy to prevent mutation of cached data
        if exclude_internal:
            if self._dict_cache_exclude_internal is not None:
                return dict(self._dict_cache_exclude_internal)
        else:
            if self._dict_cache is not None:
                return dict(self._dict_cache)

        # Cache miss - compute and cache
        from dataclasses import fields

        state_dict = {}
        for f in fields(self):
            key = f.name

            # Skip cache fields
            if key.startswith('_dict_cache'):
                continue

            value = getattr(self, key)

            # Skip infrastructure fields if requested
            if exclude_internal and key in ('tracker', 'tool_registry', 'config_loader', 'visualizer'):
                continue

            # Handle datetime serialization
            if isinstance(value, datetime):
                value = value.isoformat()

            state_dict[key] = value

        # Store in appropriate cache
        if exclude_internal:
            self._dict_cache_exclude_internal = state_dict
        else:
            self._dict_cache = state_dict

        # Return a shallow copy so callers cannot mutate the cached data
        return dict(state_dict)

    def to_typed_dict(self) -> Dict[str, Any]:
        """Convert to dict for LangGraph compatibility.

        LangGraph nodes receive state and expect dict updates.
        This method provides the full state as a dict including
        infrastructure for executor access.

        Returns:
            Dictionary with all state fields

        Example:
            >>> # In node function
            >>> state_dict = state.to_typed_dict()
            >>> executor.execute_stage(..., state=state_dict)
        """
        return self.to_dict(exclude_internal=False)
