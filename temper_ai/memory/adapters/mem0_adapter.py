"""Mem0-backed memory adapter for production use.

Requires: pip install -e ".[memory]"
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from temper_ai.memory._schemas import MemoryEntry, MemoryScope
from temper_ai.memory.constants import DEFAULT_RETRIEVAL_LIMIT, LATENCY_BUDGET_MS

logger = logging.getLogger(__name__)

MS_PER_SECOND = 1000
DEFAULT_COLLECTION_NAME = "maf_memory"
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def _ensure_mem0_available() -> Any:
    """Import mem0 or raise with install instructions."""
    try:
        import mem0  # noqa: F401

        return mem0
    except ImportError as exc:
        raise ImportError(
            "mem0ai is required for the Mem0 memory adapter. "
            'Install with: pip install -e ".[memory]"'
        ) from exc


class Mem0Adapter:
    """Memory store backed by Mem0 with vector search.

    Supports sentence-transformers (default) and Ollama embeddings.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        mem0_module = _ensure_mem0_available()
        mem0_config = config or self._default_config()
        self._memory = mem0_module.Memory.from_config(mem0_config)

    @staticmethod
    def _default_config() -> dict[str, Any]:
        """Default config using ChromaDB + sentence-transformers."""
        return {
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": DEFAULT_COLLECTION_NAME,
                },
            },
            "embedder": {
                "provider": "sentence_transformer",
                "config": {
                    "model": DEFAULT_EMBEDDING_MODEL,
                },
            },
        }

    def add(
        self,
        scope: MemoryScope,
        content: str,
        memory_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a memory via Mem0."""
        combined_metadata = dict(metadata or {})
        combined_metadata["memory_type"] = memory_type

        result = self._memory.add(
            content,
            user_id=scope.scope_key,
            metadata=combined_metadata,
        )
        # Mem0 returns a list of results; extract the first ID
        if isinstance(result, list) and result:
            first = result[0]
            if isinstance(first, dict):
                return str(first.get("id", uuid.uuid4().hex))
        if isinstance(result, dict):
            return str(result.get("id", uuid.uuid4().hex))
        return uuid.uuid4().hex

    def search(
        self,
        scope: MemoryScope,
        query: str,
        limit: int = DEFAULT_RETRIEVAL_LIMIT,
        threshold: float = 0.0,
        memory_type: str | None = None,
    ) -> list[MemoryEntry]:
        """Search memories via Mem0 vector search."""
        start = time.monotonic()
        results = self._memory.search(
            query,
            user_id=scope.scope_key,
            limit=limit,
        )
        elapsed_ms = (time.monotonic() - start) * MS_PER_SECOND

        if elapsed_ms > LATENCY_BUDGET_MS:
            logger.warning(
                "Mem0 search latency %.0fms exceeds budget %dms",
                elapsed_ms,
                LATENCY_BUDGET_MS,
            )

        entries: list[MemoryEntry] = []
        raw_results = (
            results.get("results", []) if isinstance(results, dict) else results
        )
        for item in raw_results:
            item_metadata = item.get("metadata", {})
            item_type = item_metadata.get("memory_type", "")
            if memory_type and item_type != memory_type:
                continue

            score = item.get("score", 0.0)
            if score < threshold:
                continue

            entries.append(
                MemoryEntry(
                    id=str(item.get("id", uuid.uuid4().hex)),
                    content=item.get("memory", item.get("text", "")),
                    memory_type=item_type,
                    metadata=item_metadata,
                    created_at=datetime.now(UTC),
                    relevance_score=score,
                )
            )

        return entries[:limit]

    def get_all(
        self,
        scope: MemoryScope,
        memory_type: str | None = None,
    ) -> list[MemoryEntry]:
        """Return all memories for a scope via Mem0."""
        results = self._memory.get_all(user_id=scope.scope_key)
        raw = results.get("results", []) if isinstance(results, dict) else results

        entries: list[MemoryEntry] = []
        for item in raw:
            item_metadata = item.get("metadata", {})
            item_type = item_metadata.get("memory_type", "")
            if memory_type and item_type != memory_type:
                continue
            entries.append(
                MemoryEntry(
                    id=str(item.get("id", uuid.uuid4().hex)),
                    content=item.get("memory", item.get("text", "")),
                    memory_type=item_type,
                    metadata=item_metadata,
                    created_at=datetime.now(UTC),
                )
            )
        return entries

    def delete(self, scope: MemoryScope, memory_id: str) -> bool:
        """Delete a single memory by ID."""
        try:
            self._memory.delete(memory_id)
            return True
        except Exception:  # noqa: BLE001 — Mem0 may raise various errors
            logger.debug("Failed to delete memory %s", memory_id, exc_info=True)
            return False

    def delete_all(self, scope: MemoryScope) -> int:
        """Delete all memories for a scope."""
        entries = self.get_all(scope)
        count = 0
        for entry in entries:
            if self.delete(scope, entry.id):
                count += 1
        return count
