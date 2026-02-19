"""In-memory adapter for testing and fallback use."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from temper_ai.memory._schemas import MemoryEntry, MemoryScope
from temper_ai.memory.constants import DEFAULT_RETRIEVAL_LIMIT


class InMemoryAdapter:
    """Dict-based memory store. Thread-safe via RLock.

    Search uses simple substring matching (no embeddings).
    Suitable for testing and as a fallback when Mem0 is unavailable.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._store: Dict[str, List[MemoryEntry]] = {}
        self._lock = threading.RLock()

    def add(
        self,
        scope: MemoryScope,
        content: str,
        memory_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store a memory entry and return its ID."""
        entry = MemoryEntry(
            content=content,
            memory_type=memory_type,
            metadata=metadata or {},
        )
        with self._lock:
            self._store.setdefault(scope.scope_key, []).append(entry)
        return entry.id

    def search(
        self,
        scope: MemoryScope,
        query: str,
        limit: int = DEFAULT_RETRIEVAL_LIMIT,
        threshold: float = 0.0,
        memory_type: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Search memories by substring match within a scope."""
        query_lower = query.lower()
        with self._lock:
            entries = list(self._store.get(scope.scope_key, []))

        results: List[MemoryEntry] = []
        for entry in entries:
            if memory_type and entry.memory_type != memory_type:
                continue
            content_lower = entry.content.lower()
            if query_lower in content_lower:
                # Simple relevance: ratio of query length to content length
                score = len(query_lower) / max(len(content_lower), 1)
                entry.relevance_score = min(score, 1.0)
                if entry.relevance_score >= threshold:
                    results.append(entry)

        results.sort(key=lambda e: e.relevance_score, reverse=True)
        return results[:limit]

    def get_all(
        self,
        scope: MemoryScope,
        memory_type: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Return all memories for a scope, optionally filtered by type."""
        with self._lock:
            entries = list(self._store.get(scope.scope_key, []))
        if memory_type:
            return [e for e in entries if e.memory_type == memory_type]
        return entries

    def delete(self, scope: MemoryScope, memory_id: str) -> bool:
        """Delete a single memory by ID."""
        with self._lock:
            entries = self._store.get(scope.scope_key, [])
            for i, entry in enumerate(entries):
                if entry.id == memory_id:
                    entries.pop(i)
                    return True
        return False

    def delete_all(self, scope: MemoryScope) -> int:
        """Delete all memories for a scope."""
        with self._lock:
            entries = self._store.pop(scope.scope_key, [])
        return len(entries)
