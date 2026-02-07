"""Core protocol definitions for framework-wide interfaces.

This module provides Protocol definitions for common patterns used across
the framework, enabling type checking and structural subtyping without
tight coupling between components.
"""
from typing import Protocol, TypeVar, List, Optional, runtime_checkable

T = TypeVar('T')


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

    def list_all(self) -> List[str]:
        """Get names of all registered items.

        Returns:
            List of unique item names (may be sorted or unsorted)
        """
        ...

    def count(self) -> int:
        """Get total number of registered items.

        Returns:
            Total count of items in the registry
        """
        ...
