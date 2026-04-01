"""In-memory store — dict-based, zero external deps.

Useful for:
- Unit tests (no mem0 needed)
- Default fallback (memory works instantly without config)
- Quick prototyping (memories live for process lifetime)

Not persistent — memories are lost on restart.
No semantic search — search() does substring matching on content.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

from temper_ai.memory.base import MemoryEntry, MemoryStoreBase


class InMemoryStore(MemoryStoreBase):
    """Thread-safe in-memory store backed by a dict."""

    def __init__(self):
        self._memories: dict[str, list[MemoryEntry]] = {}
        self._lock = threading.Lock()

    def _key(self, agent_name: str, scope: str) -> str:
        return f"{scope}:{agent_name}"

    def store(
        self,
        agent_name: str,
        scope: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        key = self._key(agent_name, scope)
        entry = MemoryEntry(
            content=content,
            id=uuid.uuid4().hex,
            metadata=metadata or {},
            created_at=datetime.now(UTC),
        )
        with self._lock:
            if key not in self._memories:
                self._memories[key] = []
            self._memories[key].append(entry)
        return entry.id

    def recall(
        self,
        agent_name: str,
        scope: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        key = self._key(agent_name, scope)
        with self._lock:
            entries = list(self._memories.get(key, []))
        # Most recent first
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    def search(
        self,
        query: str,
        agent_name: str,
        scope: str,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """Substring search — no semantic search without embeddings."""
        key = self._key(agent_name, scope)
        query_lower = query.lower()
        with self._lock:
            entries = list(self._memories.get(key, []))
        matches = [e for e in entries if query_lower in e.content.lower()]
        return matches[:limit]

    def clear(self, agent_name: str, scope: str) -> int:
        key = self._key(agent_name, scope)
        with self._lock:
            entries = self._memories.pop(key, [])
        return len(entries)
