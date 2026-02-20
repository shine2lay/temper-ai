"""Tests for tool result caching (R0.3)."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.tool_cache import ToolResultCache, _CacheEntry
from temper_ai.tools.tool_cache_constants import (
    DEFAULT_CACHE_MAX_SIZE,
    DEFAULT_CACHE_TTL_SECONDS,
)
from temper_ai.tools._executor_helpers import (
    _is_tool_cacheable,
    check_tool_cache,
    store_tool_cache,
)


# ---------------------------------------------------------------------------
# Helper fixtures / mock tools
# ---------------------------------------------------------------------------

class ReadOnlyTool(BaseTool):
    """Tool that does NOT modify state (cacheable by default)."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="search", description="Search tool", modifies_state=False,
        )

    def get_parameters_schema(self) -> dict:
        return {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result=f"found: {kwargs.get('q')}")


class StatefulTool(BaseTool):
    """Tool that modifies state (not cacheable by default)."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="file_write", description="Write file", modifies_state=True,
        )

    def get_parameters_schema(self) -> dict:
        return {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="written")


class ExplicitCacheableTool(BaseTool):
    """Tool with explicit cacheable=True despite modifying state."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="idempotent_write", description="Idempotent",
            modifies_state=True, cacheable=True,
        )

    def get_parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="ok")


class ExplicitNonCacheableTool(BaseTool):
    """Read-only tool that explicitly opts out of caching."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="volatile_search", description="Volatile",
            modifies_state=False, cacheable=False,
        )

    def get_parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="volatile")


@pytest.fixture
def cache() -> ToolResultCache:
    return ToolResultCache(max_size=4, ttl_seconds=2)


# ---------------------------------------------------------------------------
# ToolResultCache unit tests
# ---------------------------------------------------------------------------

class TestToolResultCache:

    def test_miss_returns_none(self, cache: ToolResultCache) -> None:
        assert cache.get("search", {"q": "hello"}) is None

    def test_put_and_get(self, cache: ToolResultCache) -> None:
        result = ToolResult(success=True, result="found")
        cache.put("search", {"q": "hello"}, result)
        cached = cache.get("search", {"q": "hello"})
        assert cached is not None
        assert cached.result == "found"

    def test_different_params_different_entries(self, cache: ToolResultCache) -> None:
        r1 = ToolResult(success=True, result="a")
        r2 = ToolResult(success=True, result="b")
        cache.put("search", {"q": "a"}, r1)
        cache.put("search", {"q": "b"}, r2)
        assert cache.get("search", {"q": "a"}).result == "a"  # type: ignore[union-attr]
        assert cache.get("search", {"q": "b"}).result == "b"  # type: ignore[union-attr]

    def test_ttl_expiry(self, cache: ToolResultCache) -> None:
        result = ToolResult(success=True, result="data")
        cache.put("search", {"q": "ttl"}, result)
        assert cache.get("search", {"q": "ttl"}) is not None

        # Simulate time passing beyond TTL
        with patch("temper_ai.tools.tool_cache.time.time", return_value=time.time() + 3):
            assert cache.get("search", {"q": "ttl"}) is None

    def test_lru_eviction(self) -> None:
        cache = ToolResultCache(max_size=2, ttl_seconds=60)
        r1 = ToolResult(success=True, result="first")
        r2 = ToolResult(success=True, result="second")
        r3 = ToolResult(success=True, result="third")

        cache.put("t", {"k": "1"}, r1)
        cache.put("t", {"k": "2"}, r2)
        cache.put("t", {"k": "3"}, r3)

        # First entry should be evicted (LRU)
        assert cache.get("t", {"k": "1"}) is None
        assert cache.get("t", {"k": "2"}) is not None
        assert cache.get("t", {"k": "3"}) is not None

    def test_lru_access_refreshes_order(self) -> None:
        cache = ToolResultCache(max_size=2, ttl_seconds=60)
        r1 = ToolResult(success=True, result="first")
        r2 = ToolResult(success=True, result="second")
        r3 = ToolResult(success=True, result="third")

        cache.put("t", {"k": "1"}, r1)
        cache.put("t", {"k": "2"}, r2)

        # Access k=1 to make it recently used
        cache.get("t", {"k": "1"})

        # Add k=3 -> k=2 should be evicted (least recently used)
        cache.put("t", {"k": "3"}, r3)

        assert cache.get("t", {"k": "1"}) is not None
        assert cache.get("t", {"k": "2"}) is None
        assert cache.get("t", {"k": "3"}) is not None

    def test_invalidate_all(self, cache: ToolResultCache) -> None:
        cache.put("a", {"x": 1}, ToolResult(success=True, result="a"))
        cache.put("b", {"x": 1}, ToolResult(success=True, result="b"))
        removed = cache.invalidate()
        assert removed == 2
        assert cache.stats()["size"] == 0

    def test_invalidate_by_tool_name(self, cache: ToolResultCache) -> None:
        cache.put("search", {"q": "1"}, ToolResult(success=True, result="s1"))
        cache.put("search", {"q": "2"}, ToolResult(success=True, result="s2"))
        cache.put("calc", {"x": 1}, ToolResult(success=True, result="c1"))
        removed = cache.invalidate(tool_name="search")
        assert removed == 2
        assert cache.get("calc", {"x": 1}) is not None

    def test_clear(self, cache: ToolResultCache) -> None:
        cache.put("a", {}, ToolResult(success=True, result="v"))
        cache.clear()
        assert cache.stats()["size"] == 0

    def test_stats(self, cache: ToolResultCache) -> None:
        result = ToolResult(success=True, result="data")
        cache.put("t", {"k": 1}, result)

        cache.get("t", {"k": 1})  # hit
        cache.get("t", {"k": 2})  # miss

        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["max_size"] == 4

    def test_eviction_count_tracked(self) -> None:
        cache = ToolResultCache(max_size=1, ttl_seconds=60)
        cache.put("t", {"k": "1"}, ToolResult(success=True, result="a"))
        cache.put("t", {"k": "2"}, ToolResult(success=True, result="b"))
        assert cache.stats()["evictions"] == 1

    def test_put_updates_existing_entry(self, cache: ToolResultCache) -> None:
        cache.put("t", {"k": 1}, ToolResult(success=True, result="v1"))
        cache.put("t", {"k": 1}, ToolResult(success=True, result="v2"))
        assert cache.get("t", {"k": 1}).result == "v2"  # type: ignore[union-attr]
        assert cache.stats()["size"] == 1

    def test_thread_safety(self) -> None:
        cache = ToolResultCache(max_size=100, ttl_seconds=60)
        errors: list[str] = []
        barrier = threading.Barrier(10)

        def writer(idx: int) -> None:
            try:
                barrier.wait(timeout=5)
                for i in range(20):
                    cache.put(f"tool_{idx}", {"i": i}, ToolResult(success=True, result=f"{idx}-{i}"))
                    cache.get(f"tool_{idx}", {"i": i})
            except (RuntimeError, ValueError, threading.BrokenBarrierError) as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"
        assert cache.stats()["size"] <= 100

    def test_default_constants(self) -> None:
        assert DEFAULT_CACHE_MAX_SIZE == 256
        assert DEFAULT_CACHE_TTL_SECONDS == 300


# ---------------------------------------------------------------------------
# _is_tool_cacheable tests
# ---------------------------------------------------------------------------

class TestIsToolCacheable:

    def test_readonly_tool_cacheable(self) -> None:
        assert _is_tool_cacheable(ReadOnlyTool()) is True

    def test_stateful_tool_not_cacheable(self) -> None:
        assert _is_tool_cacheable(StatefulTool()) is False

    def test_explicit_cacheable_overrides(self) -> None:
        assert _is_tool_cacheable(ExplicitCacheableTool()) is True

    def test_explicit_non_cacheable_overrides(self) -> None:
        assert _is_tool_cacheable(ExplicitNonCacheableTool()) is False


# ---------------------------------------------------------------------------
# check_tool_cache / store_tool_cache integration
# ---------------------------------------------------------------------------

class TestCacheHelpers:

    def test_check_returns_none_when_no_cache(self) -> None:
        executor = MagicMock()
        executor._tool_cache = None
        assert check_tool_cache(executor, ReadOnlyTool(), {"q": "x"}) is None

    def test_check_returns_none_for_non_cacheable(self) -> None:
        executor = MagicMock()
        executor._tool_cache = ToolResultCache()
        assert check_tool_cache(executor, StatefulTool(), {"path": "/x"}) is None

    def test_store_skips_when_no_cache(self) -> None:
        executor = MagicMock()
        executor._tool_cache = None
        store_tool_cache(executor, ReadOnlyTool(), {"q": "x"}, ToolResult(success=True, result="ok"))
        assert executor._tool_cache is None  # unchanged, no error

    def test_store_skips_non_cacheable(self) -> None:
        cache = ToolResultCache()
        executor = MagicMock()
        executor._tool_cache = cache
        store_tool_cache(executor, StatefulTool(), {"path": "/x"}, ToolResult(success=True, result="ok"))
        assert cache.stats()["size"] == 0

    def test_store_skips_failed_result(self) -> None:
        cache = ToolResultCache()
        executor = MagicMock()
        executor._tool_cache = cache
        store_tool_cache(executor, ReadOnlyTool(), {"q": "x"}, ToolResult(success=False, error="fail"))
        assert cache.stats()["size"] == 0

    def test_roundtrip_check_store(self) -> None:
        cache = ToolResultCache()
        executor = MagicMock()
        executor._tool_cache = cache
        tool = ReadOnlyTool()
        params = {"q": "test"}
        result = ToolResult(success=True, result="found: test")

        assert check_tool_cache(executor, tool, params) is None
        store_tool_cache(executor, tool, params, result)
        cached = check_tool_cache(executor, tool, params)
        assert cached is not None
        assert cached.result == "found: test"
