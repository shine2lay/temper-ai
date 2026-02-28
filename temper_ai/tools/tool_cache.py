"""Tool result caching with LRU eviction and TTL expiry (R0.3).

Only caches results from tools where ``modifies_state=False`` (read-only tools
like search, calculator). State-modifying tools (bash, file_write) are never cached.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from temper_ai.tools.base import ToolResult
from temper_ai.tools.tool_cache_constants import (
    CACHE_KEY_SEPARATOR,
    DEFAULT_CACHE_MAX_SIZE,
    DEFAULT_TOOL_CACHE_TTL_SECONDS,
)

logger = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    """Internal cache entry with metadata."""

    result: ToolResult
    timestamp: float
    tool_name: str


@dataclass
class _CacheStats:
    """Tracks cache hit/miss/eviction statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0


class ToolResultCache:
    """LRU cache for read-only tool results with TTL expiry.

    Thread-safe via a reentrant lock. Entries are evicted when the cache
    exceeds ``max_size`` (oldest-first) or when their TTL expires.
    """

    def __init__(
        self,
        max_size: int = DEFAULT_CACHE_MAX_SIZE,
        ttl_seconds: int = DEFAULT_TOOL_CACHE_TTL_SECONDS,
    ) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._stats = _CacheStats()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, tool_name: str, params: dict[str, Any]) -> ToolResult | None:
        """Look up a cached result. Returns ``None`` on miss or TTL expiry."""
        key = self._build_key(tool_name, params)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._stats.misses += 1
                return None

            if self._is_expired(entry):
                del self._entries[key]
                self._stats.misses += 1
                return None

            # Move to end for LRU ordering
            self._entries.move_to_end(key)
            self._stats.hits += 1
            return entry.result

    def put(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: ToolResult,
    ) -> None:
        """Store a result, evicting the oldest entry if over capacity."""
        key = self._build_key(tool_name, params)
        now = time.time()
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                self._entries[key] = _CacheEntry(
                    result=result,
                    timestamp=now,
                    tool_name=tool_name,
                )
                return

            self._entries[key] = _CacheEntry(
                result=result,
                timestamp=now,
                tool_name=tool_name,
            )
            self._evict_if_needed()

    def invalidate(self, tool_name: str | None = None) -> int:
        """Remove entries. If *tool_name* given, remove only that tool's entries.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            if tool_name is None:
                count = len(self._entries)
                self._entries.clear()
                return count

            keys_to_remove = [
                k for k, v in self._entries.items() if v.tool_name == tool_name
            ]
            for k in keys_to_remove:
                del self._entries[k]
            return len(keys_to_remove)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            return {
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "size": len(self._entries),
                "max_size": self._max_size,
                "evictions": self._stats.evictions,
                "ttl_seconds": self._ttl_seconds,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_key(self, tool_name: str, params: dict[str, Any]) -> str:
        """Build a deterministic cache key from tool name and params."""
        raw = (
            tool_name
            + CACHE_KEY_SEPARATOR
            + json.dumps(
                params,
                sort_keys=True,
                default=str,
            )
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def _is_expired(self, entry: _CacheEntry) -> bool:
        """Check whether a cache entry has exceeded its TTL."""
        return (time.time() - entry.timestamp) > self._ttl_seconds

    def _evict_if_needed(self) -> None:
        """Evict oldest entries until size is within limit. Caller holds lock."""
        while len(self._entries) > self._max_size:
            self._entries.popitem(last=False)
            self._stats.evictions += 1
