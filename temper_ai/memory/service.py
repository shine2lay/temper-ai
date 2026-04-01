"""Agent-facing memory service.

Thin wrapper over MemoryStoreBase. Returns list[str] for template consumption.
The store returns MemoryEntry objects — the service simplifies for the common case
while preserving access to rich objects via recall_entries() for future features.
"""

from __future__ import annotations

from temper_ai.memory.base import MemoryEntry, MemoryStoreBase


class MemoryService:
    """High-level memory operations for agents.

    Singleton per server — agent isolation happens through scope keys,
    not through separate instances.
    """

    def __init__(self, store: MemoryStoreBase):
        self._store = store

    def store(
        self,
        agent_name: str,
        scope: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """Store content as memory. Backend handles extraction + dedup internally.

        Returns memory ID.
        """
        return self._store.store(agent_name, scope, content, metadata)

    def recall(
        self,
        agent_name: str,
        scope: str,
        limit: int = 10,
    ) -> list[str]:
        """Get memories as strings for template injection.

        Returns list[str] — just the content. For full MemoryEntry objects
        with scores/metadata, use recall_entries().
        """
        entries = self._store.recall(agent_name, scope, limit)
        return [e.content for e in entries]

    def recall_entries(
        self,
        agent_name: str,
        scope: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Get full MemoryEntry objects. For future features (scores, UI display)."""
        return self._store.recall(agent_name, scope, limit)

    def search(
        self,
        query: str,
        agent_name: str,
        scope: str,
        limit: int = 5,
    ) -> list[str]:
        """Semantic search. Returns list[str] for template injection."""
        entries = self._store.search(query, agent_name, scope, limit)
        return [e.content for e in entries]

    def search_entries(
        self,
        query: str,
        agent_name: str,
        scope: str,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """Semantic search returning full MemoryEntry objects."""
        return self._store.search(query, agent_name, scope, limit)

    def clear(self, agent_name: str, scope: str) -> int:
        """Delete all memories for agent+scope."""
        return self._store.clear(agent_name, scope)
