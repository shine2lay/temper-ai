"""Core protocol definitions for framework-wide interfaces.

This module provides Protocol definitions for common patterns used across
the framework, enabling type checking and structural subtyping without
tight coupling between components.
"""
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Protocol, TypeVar, runtime_checkable

T = TypeVar('T', covariant=True)


@runtime_checkable
class Registry(Protocol[T]):
    """Protocol for registry pattern implementations.

    A registry is a central location for storing and retrieving items
    by name. This protocol defines the minimal interface that all
    registry implementations should provide.

    Type parameter T represents the type of items stored in the registry.

    Example:
        >>> class MyRegistry:
        ...     def get(self, name: str) -> Optional[MyItem]:
        ...         ...
        ...     def list_all(self) -> List[str]:
        ...         ...
        ...     def count(self) -> int:
        ...         ...
        >>>
        >>> registry: Registry[MyItem] = MyRegistry()
        >>> isinstance(registry, Registry)
        True
    """

    def get(self, name: str) -> Optional[T]:
        """Get an item by name.

        Args:
            name: Unique identifier for the item

        Returns:
            Item instance if found, None otherwise
        """
        ...

    def list(self) -> List[str]:
        """Get names of all registered items.

        Returns:
            List of unique item names (may be sorted or unsorted)
        """
        ...

    # Backward compatibility alias
    def list_all(self) -> List[str]:
        """DEPRECATED: Use list() instead.

        Returns:
            List of unique item names (may be sorted or unsorted)
        """
        ...


@runtime_checkable
class ToolRegistryProtocol(Protocol):
    """Protocol for tool registries.

    Provides type-safe interface for tool registration and retrieval.

    Example:
        >>> class MyToolRegistry:
        ...     def register_tool(self, name: str, tool_class: type) -> None:
        ...         ...
        ...     def get_tool(self, name: str) -> Optional[Any]:
        ...         ...
        >>>
        >>> registry: ToolRegistryProtocol = MyToolRegistry()
    """

    def register_tool(self, name: str, tool_class: type) -> None:
        """Register a tool class by name.

        Args:
            name: Unique tool identifier
            tool_class: Tool class to register
        """
        ...

    def get_tool(self, name: str) -> Optional[Any]:
        """Get a tool instance by name.

        Args:
            name: Tool identifier

        Returns:
            Tool instance or None
        """
        ...

    def list_tools(self) -> List[str]:
        """Get names of all registered tools.

        Returns:
            List of tool names
        """
        ...


@runtime_checkable
class PolicyRegistryProtocol(Protocol):
    """Protocol for safety policy registries.

    Provides type-safe interface for policy registration and retrieval.

    Example:
        >>> class MyPolicyRegistry:
        ...     def register_policy(self, policy: Any) -> None:
        ...         ...
        ...     def get_policy(self, name: str) -> Optional[Any]:
        ...         ...
        >>>
        >>> registry: PolicyRegistryProtocol = MyPolicyRegistry()
    """

    def register_policy(self, policy: Any) -> None:
        """Register a safety policy.

        Args:
            policy: Policy instance to register
        """
        ...

    def get_policy(self, name: str) -> Optional[Any]:
        """Get a policy by name.

        Args:
            name: Policy identifier

        Returns:
            Policy instance or None
        """
        ...

    def list_policies(self) -> List[str]:
        """Get names of all registered policies.

        Returns:
            List of policy names
        """
        ...


@runtime_checkable
class StrategyRegistryProtocol(Protocol):
    """Protocol for strategy registries.

    Provides type-safe interface for strategy registration and retrieval.

    Example:
        >>> class MyStrategyRegistry:
        ...     def register_strategy(self, name: str, strategy_class: type) -> None:
        ...         ...
        ...     def get_strategy(self, name: str) -> Optional[Any]:
        ...         ...
        >>>
        >>> registry: StrategyRegistryProtocol = MyStrategyRegistry()
    """

    def register_strategy(self, name: str, strategy_class: type) -> None:
        """Register a strategy class by name.

        Args:
            name: Unique strategy identifier
            strategy_class: Strategy class to register
        """
        ...

    def get_strategy(self, name: str) -> Optional[Any]:
        """Get a strategy instance by name.

        Args:
            name: Strategy identifier

        Returns:
            Strategy instance or None
        """
        ...

    def list_strategies(self) -> List[str]:
        """Get names of all registered strategies.

        Returns:
            List of strategy names
        """
        ...

    def count(self) -> int:
        """Get total number of registered items.

        Returns:
            Total count of items in the registry
        """
        ...


# ---------------------------------------------------------------------------
# Execution infrastructure protocols (canonical location, re-exported by
# ``temper_ai.workflow.domain_state`` for backward compatibility)
# ---------------------------------------------------------------------------


@runtime_checkable
class TrackerProtocol(Protocol):
    """Minimal interface for an execution tracker."""

    @contextmanager
    def track_stage(
        self,
        stage_name: str,
        stage_config: Dict[str, Any],
        workflow_id: str,
        input_data: Dict[str, Any],
    ) -> Iterator[str]:
        """Track stage execution."""
        ...

    @contextmanager
    def track_agent(
        self,
        agent_name: str,
        agent_config: Dict[str, Any],
        stage_id: str,
        input_data: Dict[str, Any],
    ) -> Iterator[str]:
        """Track agent execution."""
        ...

    def set_agent_output(
        self,
        agent_id: str,
        output_data: Dict[str, Any],
        reasoning: Optional[str] = None,
        total_tokens: Optional[int] = None,
        estimated_cost_usd: Optional[float] = None,
        num_llm_calls: int = 0,
        num_tool_calls: int = 0,
    ) -> None:
        """Set agent output."""
        ...

    def track_collaboration_event(
        self,
        event_type: str,
        stage_name: str,
        agents: List[str],
        decision: Optional[str],
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track collaboration event."""
        ...


@runtime_checkable
class DomainToolRegistryProtocol(Protocol):
    """Minimal interface for a tool registry in domain state context."""

    def get(self, name: str, version: Optional[str] = None) -> Any:
        """Get tool by name and optional version."""
        ...


@runtime_checkable
class ConfigLoaderProtocol(Protocol):
    """Minimal interface for a configuration loader."""

    def load_agent(self, agent_name: str) -> Dict[str, Any]:
        """Load agent configuration by name."""
        ...

    def load_stage(self, stage_name: str) -> Dict[str, Any]:
        """Load stage configuration by name."""
        ...


@runtime_checkable
class VisualizerProtocol(Protocol):
    """Minimal interface for a workflow visualizer."""

    def update(self, state: Dict[str, Any]) -> None:
        """Update visualizer with workflow state."""
        ...
