"""Memory store interface and shared types.

All memory backends implement MemoryStoreBase. The interface is deliberately
simple — backend-specific features (like mem0's infer mode) are configuration
concerns inside the adapter, not exposed here.

MemoryEntry is the store's return type. MemoryService converts to list[str]
for v1 template consumption, but the rich objects are available for future
features (relevance scores, timestamps, metadata filtering).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MemoryEntry:
    """A single memory record returned by the store."""

    content: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    relevance_score: float = 0.0


class MemoryStoreBase(ABC):
    """Interface all memory backends implement.

    Scoping: agent_name + scope together form the memory partition.
    v1 uses scope as a flat string (e.g., "project:/path/to/repo").
    Future: scope can become a MemoryScope dataclass that produces the same string.
    """

    @abstractmethod
    def store(
        self,
        agent_name: str,
        scope: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """Store content as memory. Returns memory ID.

        What happens internally depends on the backend:
        - mem0: LLM extracts facts + deduplicates against existing memories
        - in_memory: stores raw content as-is
        """
        ...

    @abstractmethod
    def recall(
        self,
        agent_name: str,
        scope: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Get memories for agent+scope, most recent first."""
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        agent_name: str,
        scope: str,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """Semantic search for memories relevant to query."""
        ...

    @abstractmethod
    def clear(self, agent_name: str, scope: str) -> int:
        """Delete all memories for agent+scope. Returns count deleted."""
        ...
