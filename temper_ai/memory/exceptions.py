"""Memory module exceptions."""

from temper_ai.shared.exceptions import TemperError


class MemoryError(TemperError):
    """Base exception for memory operations."""


class MemoryBackendError(MemoryError):
    """Backend-specific error (e.g., mem0 connection failure)."""


class MemoryDependencyError(MemoryError):
    """Required dependency not installed for the configured backend."""
