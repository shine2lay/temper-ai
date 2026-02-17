"""Tests for InMemoryAdapter."""

import threading

from src.memory._schemas import MemoryScope
from src.memory.adapters.in_memory import InMemoryAdapter
from src.memory.constants import (
    MEMORY_TYPE_CROSS_SESSION,
    MEMORY_TYPE_EPISODIC,
    MEMORY_TYPE_PROCEDURAL,
)


class TestInMemoryAdapterBasic:
    """Basic CRUD tests for InMemoryAdapter."""

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

    def test_config_parameter_ignored(self):
        """Config arg is accepted but not used."""
        adapter = InMemoryAdapter(config={"key": "value"})
        assert adapter is not None


class TestInMemoryAdapterSearch:
    """Search-related tests for InMemoryAdapter."""

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
        # "short" in "short" gives score 1.0; in long string gives lower score
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
        # "hello" in "hello" = 1.0 score; "hello" in longer string = lower
        assert len(results) == 2
        assert results[0].relevance_score >= results[1].relevance_score

    def test_empty_query_search(self, scope, adapter):
        adapter.add(scope, "anything", MEMORY_TYPE_EPISODIC)
        results = adapter.search(scope, "")
        # Empty query matches everything via substring
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


class TestInMemoryAdapterIsolation:
    """Scope isolation and thread safety tests."""

    def test_scope_isolation(self, adapter):
        """Different scopes should not share data."""
        scope_a = MemoryScope(tenant_id="a", workflow_name="wf", agent_name="ag")
        scope_b = MemoryScope(tenant_id="b", workflow_name="wf", agent_name="ag")
        adapter.add(scope_a, "for A", MEMORY_TYPE_EPISODIC)
        adapter.add(scope_b, "for B", MEMORY_TYPE_EPISODIC)
        assert len(adapter.get_all(scope_a)) == 1
        assert len(adapter.get_all(scope_b)) == 1
        assert adapter.get_all(scope_a)[0].content == "for A"

    def test_thread_safety_concurrent_add(self, scope, adapter):
        """Concurrent adds should not lose entries."""
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

    def test_thread_safety_concurrent_read_write(self, scope, adapter):
        """Concurrent reads and writes should not crash."""
        adapter.add(scope, "seed", MEMORY_TYPE_EPISODIC)
        errors = []

        def reader():
            try:
                for _ in range(10):
                    adapter.get_all(scope)
                    adapter.search(scope, "seed")
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(10):
                    adapter.add(scope, f"w-{i}", MEMORY_TYPE_EPISODIC)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads += [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
