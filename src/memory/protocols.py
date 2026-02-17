"""Runtime-checkable protocol for memory store adapters."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from src.memory._schemas import MemoryEntry, MemoryScope
from src.memory.constants import DEFAULT_RETRIEVAL_LIMIT


@runtime_checkable
class MemoryStoreProtocol(Protocol):
    """Protocol that all memory store adapters must implement."""

    def add(
        self,
        scope: MemoryScope,
        content: str,
        memory_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store a memory and return its ID."""
        ...

    def search(
        self,
        scope: MemoryScope,
        query: str,
        limit: int = DEFAULT_RETRIEVAL_LIMIT,
        threshold: float = 0.0,
        memory_type: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Search memories by query within a scope."""
        ...

    def get_all(
        self,
        scope: MemoryScope,
        memory_type: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Return all memories for a scope."""
        ...

    def delete(self, scope: MemoryScope, memory_id: str) -> bool:
        """Delete a single memory by ID. Returns True if found."""
        ...

    def delete_all(self, scope: MemoryScope) -> int:
        """Delete all memories for a scope. Returns count deleted."""
        ...
