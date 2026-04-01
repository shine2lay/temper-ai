"""Mem0-backed memory store.

mem0 handles internally:
- Fact extraction from raw content (LLM call 1 when infer=True)
- Deduplication + consolidation against existing memories (LLM call 2)
- Vector storage (ChromaDB by default)
- Embeddings (sentence-transformers by default)
- Semantic search

The `infer` behavior is a mem0-specific config option, not exposed in our interface.
By default infer=True, meaning mem0 extracts + deduplicates.

Requires: pip install temper-ai[memory]  (installs mem0ai)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from temper_ai.memory.base import MemoryEntry, MemoryStoreBase
from temper_ai.memory.exceptions import MemoryBackendError, MemoryDependencyError

logger = logging.getLogger(__name__)


def _ensure_mem0() -> Any:
    """Import mem0 or raise with install instructions."""
    try:
        from mem0 import Memory
        return Memory
    except ImportError as exc:
        raise MemoryDependencyError(
            "mem0ai is required for the Mem0 memory backend. "
            'Install with: pip install temper-ai[memory]'
        ) from exc


class Mem0Store(MemoryStoreBase):
    """Memory store backed by mem0 library."""

    def __init__(self, mem0_config: dict | None = None):
        """Initialize Mem0 backend.

        Args:
            mem0_config: Passed directly to Memory.from_config().
                If not provided, uses defaults (ChromaDB + HuggingFace embeddings).

                mem0-specific options (not part of our MemoryStoreBase interface):
                - infer: True (default) — mem0 extracts facts + deduplicates
                - custom_fact_extraction_prompt: override extraction prompt
                - custom_update_memory_prompt: override consolidation prompt
        """
        Memory = _ensure_mem0()

        config = dict(mem0_config) if mem0_config else self._default_config()
        # Extract mem0-specific options before passing to Memory
        self._infer = config.pop("infer", True)

        try:
            self._memory = Memory.from_config(config)
        except Exception as exc:
            raise MemoryBackendError(
                f"Failed to initialize mem0: {exc}"
            ) from exc

    @staticmethod
    def _default_config() -> dict:
        """Default: ChromaDB + HuggingFace embeddings + OpenAI-compatible LLM."""
        return {
            "llm": {
                "provider": "openai",
                "config": {
                    "model": os.environ.get("TEMPER_LLM_MODEL", "gpt-4o-mini"),
                    "openai_base_url": os.environ.get(
                        "TEMPER_LLM_BASE_URL", "https://api.openai.com/v1"
                    ),
                    "api_key": os.environ.get("OPENAI_API_KEY", ""),
                },
            },
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": "temper_memories",
                    "path": os.environ.get("TEMPER_MEMORY_PATH", "./data/memory"),
                },
            },
            "embedder": {
                "provider": "huggingface",
                "config": {"model": "all-MiniLM-L6-v2"},
            },
        }

    def _user_id(self, agent_name: str, scope: str) -> str:
        """Build mem0 user_id from agent+scope. This is our partition key."""
        return f"{scope}:{agent_name}"

    def store(
        self,
        agent_name: str,
        scope: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        try:
            result = self._memory.add(
                content,
                user_id=self._user_id(agent_name, scope),
                metadata=metadata or {},
                infer=self._infer,
            )
        except Exception as exc:
            raise MemoryBackendError(f"mem0 store failed: {exc}") from exc

        # mem0 returns various formats depending on version
        if isinstance(result, list) and result:
            first = result[0]
            return str(first.get("id", "")) if isinstance(first, dict) else ""
        if isinstance(result, dict):
            return str(result.get("id", ""))
        return ""

    def recall(
        self,
        agent_name: str,
        scope: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        try:
            results = self._memory.get_all(user_id=self._user_id(agent_name, scope))
        except Exception as exc:
            raise MemoryBackendError(f"mem0 recall failed: {exc}") from exc

        raw = results.get("results", []) if isinstance(results, dict) else results
        return [self._to_entry(item) for item in raw[:limit]]

    def search(
        self,
        query: str,
        agent_name: str,
        scope: str,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        try:
            results = self._memory.search(
                query, user_id=self._user_id(agent_name, scope), limit=limit
            )
        except Exception as exc:
            raise MemoryBackendError(f"mem0 search failed: {exc}") from exc

        raw = results.get("results", []) if isinstance(results, dict) else results
        return [self._to_entry(item) for item in raw]

    def clear(self, agent_name: str, scope: str) -> int:
        entries = self.recall(agent_name, scope, limit=10000)
        count = 0
        for entry in entries:
            try:
                self._memory.delete(entry.id)
                count += 1
            except Exception:
                logger.debug("Failed to delete memory %s", entry.id, exc_info=True)
        return count

    @staticmethod
    def _to_entry(raw: dict) -> MemoryEntry:
        return MemoryEntry(
            content=raw.get("memory", raw.get("text", "")),
            id=str(raw.get("id", "")),
            metadata=raw.get("metadata", {}),
            relevance_score=raw.get("score", 0.0),
        )
