"""Core service interface.

This module provides the abstract base class for all framework services.
"""

from abc import ABC, abstractmethod


class Service(ABC):
    """Abstract base class for all framework services.

    Services are singleton components that provide infrastructure
    functionality (e.g., safety enforcement, observability, caching).

    Attributes:
        name: Unique service identifier
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Service name for registration and lookup."""
        pass

    def initialize(self) -> None:  # noqa: B027
        """Initialize service resources.

        Called once during framework startup.
        Override to set up connections, load config, etc.
        """
        pass

    def shutdown(self) -> None:  # noqa: B027
        """Clean up service resources.

        Called during framework shutdown.
        Override to close connections, flush buffers, etc.
        """
        pass
