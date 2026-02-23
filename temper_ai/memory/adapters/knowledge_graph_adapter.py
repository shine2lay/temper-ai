"""Adapter that bridges the portfolio KnowledgeGraph to MemoryStoreProtocol.

The knowledge graph is read-only from the memory perspective: add/delete
operations are no-ops, while search and get_all translate KG concepts into
MemoryEntry objects with ``memory_type="semantic"``.
"""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.memory._schemas import MemoryEntry, MemoryScope
from temper_ai.memory.constants import DEFAULT_RETRIEVAL_LIMIT

logger = logging.getLogger(__name__)

MEMORY_TYPE_SEMANTIC = "semantic"


class KnowledgeGraphMemoryAdapter:
    """Read-only adapter exposing portfolio KG concepts as memories."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self._db_url: str | None = config.get("database_url")
        self._store: Any = None
        self._query: Any = None

    # -- Lazy init (avoid importing heavy portfolio deps at import time) --

    def _ensure_initialized(self) -> None:
        """Lazily import and create PortfolioStore + KnowledgeQuery."""
        if self._query is not None:
            return
        from temper_ai.portfolio.knowledge_graph import KnowledgeQuery
        from temper_ai.portfolio.store import PortfolioStore

        self._store = PortfolioStore(database_url=self._db_url)
        self._query = KnowledgeQuery(self._store)

    # -- MemoryStoreProtocol -----------------------------------------------

    def add(
        self,
        scope: MemoryScope,
        content: str,
        memory_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """KG is read-only from memory perspective. Returns empty string."""
        return ""

    def search(
        self,
        scope: MemoryScope,
        query: str,
        limit: int = DEFAULT_RETRIEVAL_LIMIT,
        threshold: float = 0.0,
        memory_type: str | None = None,
    ) -> list[MemoryEntry]:
        """Search KG concepts by keyword substring match."""
        if memory_type and memory_type != MEMORY_TYPE_SEMANTIC:
            return []
        self._ensure_initialized()
        concepts = self._store.list_concepts()
        query_lower = query.lower()
        results: list[MemoryEntry] = []
        for concept in concepts:
            name_lower = concept.name.lower()
            if query_lower and query_lower not in name_lower:
                continue
            score = len(query_lower) / max(len(name_lower), 1) if query_lower else 0.0
            score = min(score, 1.0)
            if score < threshold:
                continue
            results.append(self._concept_to_entry(concept, score))
        results.sort(key=lambda e: e.relevance_score, reverse=True)
        return results[:limit]

    def get_all(
        self,
        scope: MemoryScope,
        memory_type: str | None = None,
    ) -> list[MemoryEntry]:
        """Return all KG concepts as MemoryEntry objects."""
        if memory_type and memory_type != MEMORY_TYPE_SEMANTIC:
            return []
        self._ensure_initialized()
        concepts = self._store.list_concepts()
        return [self._concept_to_entry(c) for c in concepts]

    def delete(self, scope: MemoryScope, memory_id: str) -> bool:
        """KG is not deletable via memory interface."""
        return False

    def delete_all(self, scope: MemoryScope) -> int:
        """KG is not deletable via memory interface."""
        return 0

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _concept_to_entry(
        concept: Any,
        score: float = 0.0,
    ) -> MemoryEntry:
        """Convert a KGConceptRecord to a MemoryEntry."""
        description = f"{concept.concept_type}: {concept.name}"
        return MemoryEntry(
            id=concept.id,
            content=description,
            memory_type=MEMORY_TYPE_SEMANTIC,
            metadata={
                "concept_type": concept.concept_type,
                "name": concept.name,
            },
            created_at=concept.created_at,
            relevance_score=score,
        )
