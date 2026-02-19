"""LangGraph-specific workflow state dataclass.

This module provides a combined dataclass that extends WorkflowDomainState
with infrastructure fields for use with LangGraph StateGraph.

LangGraph requires a dataclass schema for StateGraph. Since our architecture
separates domain state from execution context, we extend WorkflowDomainState
with infrastructure fields for LangGraph execution while maintaining the
separation for checkpointing.

Design:
- Inherits all fields from WorkflowDomainState (domain data)
- Adds infrastructure fields (tracker, tool_registry, etc.)
- Used only for LangGraph StateGraph definition
- Checkpointing still uses WorkflowDomainState for serialization
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from typing_extensions import Annotated

from temper_ai.workflow.domain_state import WorkflowDomainState


def _merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dicts for LangGraph parallel branch state reduction.

    When parallel branches both update the same dict field (e.g. stage_outputs),
    LangGraph calls this reducer to merge the updates instead of last-write-wins.

    Args:
        left: Existing dict from prior state
        right: Update dict from a parallel branch

    Returns:
        Merged dict (right wins on key conflicts)
    """
    merged = left.copy()
    merged.update(right)
    return merged


def _keep_latest(left: Any, right: Any) -> Any:
    """Reducer that keeps the latest (rightmost) value.

    Args:
        left: Prior value
        right: New value from a branch

    Returns:
        The new value
    """
    return right


@dataclass
class LangGraphWorkflowState(WorkflowDomainState):
    """Combined workflow state for LangGraph execution.

    Extends WorkflowDomainState with infrastructure components needed
    during LangGraph graph execution.  All domain fields (stage_outputs,
    workflow_id, topic, etc.) are inherited from the parent class.

    LangGraph requires a dataclass schema to properly handle state updates
    from nodes. This combined state allows nodes to access both domain data
    and infrastructure components while maintaining proper state management.

    Infrastructure Fields:
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

    # Override parent fields with Annotated reducers for LangGraph parallel
    # branch state merging.  Without these, parallel fan-out branches that both
    # update the same field would cause InvalidUpdateError.
    # Dict fields use _merge_dicts (union); scalar fields use _keep_latest.
    stage_outputs: Annotated[Dict[str, Any], _merge_dicts] = field(default_factory=dict)
    current_stage: Annotated[str, _keep_latest] = ""
    workflow_id: Annotated[str, _keep_latest] = ""
    stage_loop_counts: Annotated[Dict[str, int], _merge_dicts] = field(default_factory=dict)
    conversation_histories: Annotated[Dict[str, Any], _merge_dicts] = field(default_factory=dict)
    topic: Annotated[Optional[str], _keep_latest] = None
    depth: Annotated[Optional[str], _keep_latest] = None
    focus_areas: Annotated[Optional[List[str]], _keep_latest] = None
    query: Annotated[Optional[str], _keep_latest] = None
    input: Annotated[Optional[str], _keep_latest] = None
    context: Annotated[Optional[str], _keep_latest] = None
    data: Annotated[Optional[Dict[str, Any]], _keep_latest] = None
    workflow_inputs: Annotated[Dict[str, Any], _merge_dicts] = field(default_factory=dict)
    version: Annotated[str, _keep_latest] = "1.0"
    created_at: Annotated[datetime, _keep_latest] = field(
        default_factory=lambda: datetime.now(UTC)
    )
    metadata: Annotated[Dict[str, Any], _merge_dicts] = field(default_factory=dict)

    # Infrastructure components (added on top of inherited domain fields)
    # Also need reducers for parallel branch compatibility.
    tracker: Annotated[Optional[Any], _keep_latest] = None
    tool_registry: Annotated[Optional[Any], _keep_latest] = None
    config_loader: Annotated[Optional[Any], _keep_latest] = None
    visualizer: Annotated[Optional[Any], _keep_latest] = None

    # Cache for to_dict() results (performance optimization)
    # Note: init=True (default) is needed because LangGraph's _coerce_state passes
    # ALL dataclass fields as kwargs during state construction, including internal ones.
    _dict_cache: Annotated[Optional[Dict[str, Any]], _keep_latest] = field(default=None, repr=False)
    _dict_cache_exclude_internal: Annotated[Optional[Dict[str, Any]], _keep_latest] = field(default=None, repr=False)

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

    def to_dict(self, exclude_none: bool = False, exclude_internal: bool = False) -> Dict[str, Any]:
        """Convert state to dictionary with caching.

        Args:
            exclude_none: Accepted for backward compatibility with
                WorkflowDomainState.to_dict() (no-op here).
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
