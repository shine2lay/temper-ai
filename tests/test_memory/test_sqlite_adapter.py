"""Tests for SQLiteAdapter."""

import os
import threading

import pytest

from temper_ai.memory._schemas import MemoryScope
from temper_ai.memory.adapters.sqlite_adapter import SQLiteAdapter
from temper_ai.memory.constants import (
    MEMORY_TYPE_CROSS_SESSION,
    MEMORY_TYPE_EPISODIC,
    MEMORY_TYPE_PROCEDURAL,
)


@pytest.fixture
def db_path(tmp_path):
    """Return a temporary DB file path."""
    return str(tmp_path / "test_memory.db")


@pytest.fixture
def adapter(db_path):
    """A fresh SQLiteAdapter backed by a temp file."""
    return SQLiteAdapter(config={"db_path": db_path})


@pytest.fixture
def fts_adapter(db_path):
    """A fresh SQLiteAdapter with FTS5 enabled."""
    return SQLiteAdapter(config={"db_path": db_path, "use_fts": True})


@pytest.fixture
def scope():
    """A standard test scope."""
    return MemoryScope(tenant_id="test", workflow_name="wf", agent_name="agent")


class TestSQLiteAdapterBasic:
    """Basic CRUD tests for SQLiteAdapter."""

    def test_add_returns_id(self, scope, adapter):
        mid = adapter.add(scope, "test content", MEMORY_TYPE_EPISODIC)
        assert isinstance(mid, str)
        assert len(mid) > 0

    def test_add_and_get_all(self, scope, adapter):
        adapter.add(scope, "entry1", MEMORY_TYPE_EPISODIC)
        entries = adapter.get_all(scope)
        assert len(entries) == 1
        assert entries[0].content == "entry1"

    def test_add_multiple_entries(self, scope, adapter):
        adapter.add(scope, "one", MEMORY_TYPE_EPISODIC)
        adapter.add(scope, "two", MEMORY_TYPE_PROCEDURAL)
        adapter.add(scope, "three", MEMORY_TYPE_CROSS_SESSION)
        entries = adapter.get_all(scope)
        assert len(entries) == 3

    def test_add_with_metadata(self, scope, adapter):
        adapter.add(scope, "meta test", MEMORY_TYPE_EPISODIC, metadata={"key": "val"})
        entries = adapter.get_all(scope)
        assert entries[0].metadata == {"key": "val"}

    def test_delete_existing(self, scope, adapter):
        mid = adapter.add(scope, "to delete", MEMORY_TYPE_EPISODIC)
        assert adapter.delete(scope, mid) is True
        assert len(adapter.get_all(scope)) == 0

    def test_delete_nonexistent(self, scope, adapter):
        assert adapter.delete(scope, "no-such-id") is False

    def test_delete_all(self, scope, adapter):
        adapter.add(scope, "a", MEMORY_TYPE_EPISODIC)
        adapter.add(scope, "b", MEMORY_TYPE_PROCEDURAL)
        count = adapter.delete_all(scope)
        assert count == 2
        assert len(adapter.get_all(scope)) == 0

    def test_delete_all_empty_scope(self, scope, adapter):
        count = adapter.delete_all(scope)
        assert count == 0


class TestSQLiteAdapterSearch:
    """Search-related tests for SQLiteAdapter."""

    def test_search_substring_match(self, scope, adapter):
        adapter.add(scope, "the quick brown fox", MEMORY_TYPE_EPISODIC)
        results = adapter.search(scope, "brown")
        assert len(results) == 1
        assert "brown" in results[0].content

    def test_search_no_match(self, scope, adapter):
        adapter.add(scope, "hello world", MEMORY_TYPE_EPISODIC)
        results = adapter.search(scope, "xyz123")
        assert len(results) == 0

    def test_search_limit(self, scope, adapter):
        for i in range(10):
            adapter.add(scope, f"item {i} test", MEMORY_TYPE_EPISODIC)
        results = adapter.search(scope, "test", limit=3)
        assert len(results) == 3

    def test_search_threshold(self, scope, adapter):
        adapter.add(scope, "short", MEMORY_TYPE_EPISODIC)
        adapter.add(scope, "a very long string with word short in it", MEMORY_TYPE_EPISODIC)
        results = adapter.search(scope, "short", threshold=0.9)
        assert len(results) == 1
        assert results[0].content == "short"

    def test_search_filter_by_type(self, scope, adapter):
        adapter.add(scope, "epi memory test", MEMORY_TYPE_EPISODIC)
        adapter.add(scope, "proc memory test", MEMORY_TYPE_PROCEDURAL)
        results = adapter.search(scope, "test", memory_type=MEMORY_TYPE_EPISODIC)
        assert len(results) == 1
        assert results[0].memory_type == MEMORY_TYPE_EPISODIC

    def test_search_relevance_sorting(self, scope, adapter):
        adapter.add(scope, "hello world is great", MEMORY_TYPE_EPISODIC)
        adapter.add(scope, "hello", MEMORY_TYPE_EPISODIC)
        results = adapter.search(scope, "hello")
        assert len(results) == 2
        assert results[0].relevance_score >= results[1].relevance_score

    def test_empty_query_search(self, scope, adapter):
        adapter.add(scope, "anything", MEMORY_TYPE_EPISODIC)
        results = adapter.search(scope, "")
        assert len(results) == 1

    def test_case_insensitive_search(self, scope, adapter):
        adapter.add(scope, "Hello World", MEMORY_TYPE_EPISODIC)
        results = adapter.search(scope, "hello world")
        assert len(results) == 1

    def test_get_all_filter_by_type(self, scope, adapter):
        adapter.add(scope, "epi", MEMORY_TYPE_EPISODIC)
        adapter.add(scope, "proc", MEMORY_TYPE_PROCEDURAL)
        entries = adapter.get_all(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        assert len(entries) == 1
        assert entries[0].memory_type == MEMORY_TYPE_PROCEDURAL


class TestSQLiteAdapterIsolation:
    """Scope isolation and thread safety tests."""

    def test_scope_isolation(self, adapter):
        scope_a = MemoryScope(tenant_id="a", workflow_name="wf", agent_name="ag")
        scope_b = MemoryScope(tenant_id="b", workflow_name="wf", agent_name="ag")
        adapter.add(scope_a, "for A", MEMORY_TYPE_EPISODIC)
        adapter.add(scope_b, "for B", MEMORY_TYPE_EPISODIC)
        assert len(adapter.get_all(scope_a)) == 1
        assert len(adapter.get_all(scope_b)) == 1
        assert adapter.get_all(scope_a)[0].content == "for A"

    def test_thread_safety_concurrent_add(self, scope, adapter):
        num_threads = 8
        entries_per_thread = 10
        barrier = threading.Barrier(num_threads)

        def add_entries():
            barrier.wait()
            for i in range(entries_per_thread):
                adapter.add(scope, f"entry-{i}", MEMORY_TYPE_EPISODIC)

        threads = [threading.Thread(target=add_entries) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = len(adapter.get_all(scope))
        assert total == num_threads * entries_per_thread


class TestSQLiteAdapterPersistence:
    """Verify data survives adapter recreation."""

    def test_data_persists_across_instances(self, scope, db_path):
        adapter1 = SQLiteAdapter(config={"db_path": db_path})
        adapter1.add(scope, "persistent data", MEMORY_TYPE_EPISODIC)

        # Create a new adapter pointing to the same file
        adapter2 = SQLiteAdapter(config={"db_path": db_path})
        entries = adapter2.get_all(scope)
        assert len(entries) == 1
        assert entries[0].content == "persistent data"

    def test_data_persists_with_metadata(self, scope, db_path):
        adapter1 = SQLiteAdapter(config={"db_path": db_path})
        adapter1.add(scope, "meta data", MEMORY_TYPE_PROCEDURAL, metadata={"k": "v"})

        adapter2 = SQLiteAdapter(config={"db_path": db_path})
        entries = adapter2.get_all(scope)
        assert entries[0].metadata == {"k": "v"}
        assert entries[0].memory_type == MEMORY_TYPE_PROCEDURAL


class TestSQLiteAdapterFTS5:
    """Tests for FTS5 full-text search mode."""

    def test_fts_search_basic(self, scope, fts_adapter):
        fts_adapter.add(scope, "machine learning is powerful", MEMORY_TYPE_EPISODIC)
        fts_adapter.add(scope, "gardening tips for spring", MEMORY_TYPE_EPISODIC)
        results = fts_adapter.search(scope, "machine learning")
        assert len(results) >= 1
        assert "machine" in results[0].content

    def test_fts_delete_cleans_index(self, scope, fts_adapter):
        mid = fts_adapter.add(scope, "indexed content", MEMORY_TYPE_EPISODIC)
        fts_adapter.delete(scope, mid)
        results = fts_adapter.search(scope, "indexed")
        assert len(results) == 0

    def test_fts_delete_all_cleans_index(self, scope, fts_adapter):
        fts_adapter.add(scope, "first indexed", MEMORY_TYPE_EPISODIC)
        fts_adapter.add(scope, "second indexed", MEMORY_TYPE_EPISODIC)
        fts_adapter.delete_all(scope)
        results = fts_adapter.search(scope, "indexed")
        assert len(results) == 0

    def test_fts_filter_by_type(self, scope, fts_adapter):
        fts_adapter.add(scope, "episodic indexed text", MEMORY_TYPE_EPISODIC)
        fts_adapter.add(scope, "procedural indexed text", MEMORY_TYPE_PROCEDURAL)
        results = fts_adapter.search(scope, "indexed", memory_type=MEMORY_TYPE_EPISODIC)
        assert len(results) == 1
        assert results[0].memory_type == MEMORY_TYPE_EPISODIC


class TestSQLiteAdapterConfig:
    """Tests for configuration options."""

    def test_custom_db_path(self, tmp_path):
        custom_path = str(tmp_path / "custom.db")
        adapter = SQLiteAdapter(config={"db_path": custom_path})
        scope = MemoryScope(tenant_id="t", workflow_name="w", agent_name="a")
        adapter.add(scope, "test", MEMORY_TYPE_EPISODIC)
        assert os.path.exists(custom_path)

    def test_default_config(self, tmp_path, monkeypatch):
        """Adapter works with no config (uses defaults)."""
        monkeypatch.chdir(tmp_path)
        adapter = SQLiteAdapter()
        scope = MemoryScope(tenant_id="t", workflow_name="w", agent_name="a")
        mid = adapter.add(scope, "default test", MEMORY_TYPE_EPISODIC)
        assert isinstance(mid, str)
