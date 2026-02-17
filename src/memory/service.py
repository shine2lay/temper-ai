"""Agent-facing memory service orchestrator."""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.memory._schemas import MemoryEntry, MemoryScope, MemorySearchResult
from src.memory.protocols import MemoryStoreProtocol
from src.memory.constants import (
    DEFAULT_RETRIEVAL_LIMIT,
    DEFAULT_TENANT_ID,
    LATENCY_BUDGET_MS,
    MAX_MEMORY_CONTEXT_CHARS,
    MEMORY_TYPE_CROSS_SESSION,
    MEMORY_TYPE_EPISODIC,
    MEMORY_TYPE_PROCEDURAL,
    SECONDS_PER_DAY,
)
from src.memory.formatter import format_memory_context
from src.memory.registry import MemoryProviderRegistry

logger = logging.getLogger(__name__)

MS_PER_SECOND = 1000


def _apply_decay(entries: List[MemoryEntry], decay_factor: float) -> List[MemoryEntry]:
    """Apply exponential time-decay to entry relevance scores.

    Each entry's score is multiplied by ``decay_factor ^ age_days``.
    A ``decay_factor`` of 1.0 means no decay (backward compatible).
    """
    if decay_factor >= 1.0:
        return entries
    now = datetime.now(timezone.utc)
    for entry in entries:
        age_seconds = max((now - entry.created_at).total_seconds(), 0)
        age_days = age_seconds / SECONDS_PER_DAY
        entry.relevance_score *= math.pow(decay_factor, age_days)
    return entries


def _enforce_max_episodes(
    adapter: MemoryStoreProtocol, scope: MemoryScope, max_episodes: int,
) -> None:
    """Delete oldest entries when count exceeds *max_episodes*."""
    entries = adapter.get_all(scope)
    if len(entries) <= max_episodes:
        return
    # Sort oldest-first (by created_at)
    entries.sort(key=lambda e: e.created_at)
    to_delete = len(entries) - max_episodes
    for entry in entries[:to_delete]:
        adapter.delete(scope, entry.id)


class MemoryService:
    """High-level memory operations for agents.

    Wraps a memory store adapter (InMemory or Mem0) and provides
    convenience methods for scoped storage and retrieval.
    """

    def __init__(
        self,
        provider_name: str = "in_memory",
        provider_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        cls = MemoryProviderRegistry.get_instance().get_provider_class(provider_name)
        adapter = cls(config=provider_config) if provider_config else cls()
        self._adapter: MemoryStoreProtocol = adapter

    def build_scope(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        workflow_name: str = "",
        agent_name: str = "",
        namespace: Optional[str] = None,
    ) -> MemoryScope:
        """Build a MemoryScope from components."""
        return MemoryScope(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            agent_name=agent_name,
            namespace=namespace,
        )

    def retrieve_context(
        self,
        scope: MemoryScope,
        query: str,
        retrieval_k: int = DEFAULT_RETRIEVAL_LIMIT,
        relevance_threshold: float = 0.0,
        max_chars: int = MAX_MEMORY_CONTEXT_CHARS,
        decay_factor: float = 1.0,
    ) -> str:
        """Search memories and format as markdown for prompt injection.

        When *decay_factor* < 1.0, older entries' scores are reduced via
        exponential decay, re-filtered by *relevance_threshold*, and re-sorted.

        Returns empty string if no matches or on error.
        Logs a warning if search latency exceeds the budget.
        """
        start = time.monotonic()
        entries = self._adapter.search(
            scope=scope,
            query=query,
            limit=retrieval_k,
            threshold=relevance_threshold,
        )
        elapsed_ms = (time.monotonic() - start) * MS_PER_SECOND

        if elapsed_ms > LATENCY_BUDGET_MS:
            logger.warning(
                "Memory search latency %.0fms exceeds budget %dms",
                elapsed_ms,
                LATENCY_BUDGET_MS,
            )

        if decay_factor < 1.0:
            entries = _apply_decay(entries, decay_factor)
            entries = [e for e in entries if e.relevance_score >= relevance_threshold]
            entries.sort(key=lambda e: e.relevance_score, reverse=True)

        result = MemorySearchResult(
            entries=entries,
            query=query,
            scope=scope,
            search_time_ms=elapsed_ms,
        )
        return format_memory_context(result, max_chars=max_chars)

    def store_episodic(
        self,
        scope: MemoryScope,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        max_episodes: int = 0,
    ) -> str:
        """Store an episodic memory. Returns the memory ID.

        When *max_episodes* > 0, oldest entries exceeding the limit are pruned.
        """
        memory_id = self._adapter.add(scope, content, MEMORY_TYPE_EPISODIC, metadata)
        if max_episodes > 0:
            _enforce_max_episodes(self._adapter, scope, max_episodes)
        return memory_id

    def store_procedural(
        self,
        scope: MemoryScope,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        max_episodes: int = 0,
    ) -> str:
        """Store a procedural memory. Returns the memory ID.

        When *max_episodes* > 0, oldest entries exceeding the limit are pruned.
        """
        memory_id = self._adapter.add(scope, content, MEMORY_TYPE_PROCEDURAL, metadata)
        if max_episodes > 0:
            _enforce_max_episodes(self._adapter, scope, max_episodes)
        return memory_id

    def store_cross_session(
        self,
        scope: MemoryScope,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        max_episodes: int = 0,
    ) -> str:
        """Store a cross-session memory. Returns the memory ID.

        When *max_episodes* > 0, oldest entries exceeding the limit are pruned.
        """
        memory_id = self._adapter.add(scope, content, MEMORY_TYPE_CROSS_SESSION, metadata)
        if max_episodes > 0:
            _enforce_max_episodes(self._adapter, scope, max_episodes)
        return memory_id

    def search(
        self,
        scope: MemoryScope,
        query: str,
        limit: int = DEFAULT_RETRIEVAL_LIMIT,
        threshold: float = 0.0,
        memory_type: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Search memories by query within a scope."""
        return self._adapter.search(
            scope=scope, query=query, limit=limit,
            threshold=threshold, memory_type=memory_type,
        )

    def clear_memories(self, scope: MemoryScope) -> int:
        """Delete all memories for a scope. Returns count deleted."""
        return self._adapter.delete_all(scope)

    def list_memories(
        self,
        scope: MemoryScope,
        memory_type: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """List all memories for a scope, optionally filtered by type."""
        return self._adapter.get_all(scope, memory_type=memory_type)

    @staticmethod
    def build_shared_scope(scope: MemoryScope, shared_namespace: str) -> MemoryScope:
        """Build a shared scope by replacing namespace and clearing agent_name."""
        return MemoryScope(
            tenant_id=scope.tenant_id,
            workflow_name=scope.workflow_name,
            agent_name="",
            namespace=shared_namespace,
        )

    def retrieve_with_shared(
        self,
        scope: MemoryScope,
        shared_scope: MemoryScope,
        query: str,
        retrieval_k: int = DEFAULT_RETRIEVAL_LIMIT,
        relevance_threshold: float = 0.0,
        max_chars: int = MAX_MEMORY_CONTEXT_CHARS,
        decay_factor: float = 1.0,
    ) -> str:
        """Search both private and shared scopes, deduplicate, and format."""
        private = self._adapter.search(
            scope=scope, query=query,
            limit=retrieval_k, threshold=relevance_threshold,
        )
        shared = self._adapter.search(
            scope=shared_scope, query=query,
            limit=retrieval_k, threshold=relevance_threshold,
        )

        # Deduplicate by content
        seen_content: set = set()
        merged: List[MemoryEntry] = []
        for entry in private + shared:
            if entry.content not in seen_content:
                seen_content.add(entry.content)
                merged.append(entry)

        if decay_factor < 1.0:
            merged = _apply_decay(merged, decay_factor)
            merged = [e for e in merged if e.relevance_score >= relevance_threshold]

        merged.sort(key=lambda e: e.relevance_score, reverse=True)
        merged = merged[:retrieval_k]

        result = MemorySearchResult(
            entries=merged,
            query=query,
            scope=scope,
        )
        return format_memory_context(result, max_chars=max_chars)
