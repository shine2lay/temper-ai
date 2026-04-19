"""Tests for InMemoryStore — the dict-based memory backend."""

import threading

from temper_ai.memory.base import MemoryEntry
from temper_ai.memory.in_memory_store import InMemoryStore


class TestStore:
    def test_store_returns_id(self):
        store = InMemoryStore()
        mem_id = store.store("agent_a", "project:/tmp", "FastAPI project")
        assert isinstance(mem_id, str)
        assert len(mem_id) > 0

    def test_store_with_metadata(self):
        store = InMemoryStore()
        store.store("agent_a", "project:/tmp", "fact", metadata={"run_id": "run-1"})
        entries = store.recall("agent_a", "project:/tmp")
        assert entries[0].metadata == {"run_id": "run-1"}

    def test_store_multiple(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "fact 1")
        store.store("agent_a", "scope1", "fact 2")
        store.store("agent_a", "scope1", "fact 3")
        entries = store.recall("agent_a", "scope1")
        assert len(entries) == 3


class TestRecall:
    def test_recall_empty(self):
        store = InMemoryStore()
        entries = store.recall("agent_a", "scope1")
        assert entries == []

    def test_recall_returns_memory_entries(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "test content")
        entries = store.recall("agent_a", "scope1")
        assert len(entries) == 1
        assert isinstance(entries[0], MemoryEntry)
        assert entries[0].content == "test content"

    def test_recall_most_recent_first(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "first")
        store.store("agent_a", "scope1", "second")
        store.store("agent_a", "scope1", "third")
        entries = store.recall("agent_a", "scope1")
        assert entries[0].content == "third"
        assert entries[2].content == "first"

    def test_recall_respects_limit(self):
        store = InMemoryStore()
        for i in range(10):
            store.store("agent_a", "scope1", f"fact {i}")
        entries = store.recall("agent_a", "scope1", limit=3)
        assert len(entries) == 3

    def test_recall_scoped_by_agent(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "A's memory")
        store.store("agent_b", "scope1", "B's memory")
        entries_a = store.recall("agent_a", "scope1")
        entries_b = store.recall("agent_b", "scope1")
        assert len(entries_a) == 1
        assert entries_a[0].content == "A's memory"
        assert len(entries_b) == 1
        assert entries_b[0].content == "B's memory"

    def test_recall_scoped_by_scope(self):
        store = InMemoryStore()
        store.store("agent_a", "project:/repo1", "repo1 fact")
        store.store("agent_a", "project:/repo2", "repo2 fact")
        entries = store.recall("agent_a", "project:/repo1")
        assert len(entries) == 1
        assert entries[0].content == "repo1 fact"


class TestSearch:
    def test_search_finds_matching_content(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "Uses FastAPI framework")
        store.store("agent_a", "scope1", "Has 80% test coverage")
        store.store("agent_a", "scope1", "Uses PostgreSQL database")
        results = store.search("FastAPI", "agent_a", "scope1")
        assert len(results) == 1
        assert "FastAPI" in results[0].content

    def test_search_case_insensitive(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "Uses FastAPI")
        results = store.search("fastapi", "agent_a", "scope1")
        assert len(results) == 1

    def test_search_no_matches(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "Uses Django")
        results = store.search("FastAPI", "agent_a", "scope1")
        assert results == []

    def test_search_respects_limit(self):
        store = InMemoryStore()
        for i in range(10):
            store.store("agent_a", "scope1", f"FastAPI fact {i}")
        results = store.search("FastAPI", "agent_a", "scope1", limit=3)
        assert len(results) == 3

    def test_search_scoped(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "FastAPI in scope1")
        store.store("agent_a", "scope2", "FastAPI in scope2")
        results = store.search("FastAPI", "agent_a", "scope1")
        assert len(results) == 1
        assert "scope1" in results[0].content


class TestClear:
    def test_clear_removes_all(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "fact 1")
        store.store("agent_a", "scope1", "fact 2")
        count = store.clear("agent_a", "scope1")
        assert count == 2
        assert store.recall("agent_a", "scope1") == []

    def test_clear_returns_zero_if_empty(self):
        store = InMemoryStore()
        count = store.clear("agent_a", "scope1")
        assert count == 0

    def test_clear_scoped(self):
        store = InMemoryStore()
        store.store("agent_a", "scope1", "scope1 fact")
        store.store("agent_a", "scope2", "scope2 fact")
        store.clear("agent_a", "scope1")
        assert store.recall("agent_a", "scope1") == []
        assert len(store.recall("agent_a", "scope2")) == 1


class TestThreadSafety:
    def test_concurrent_stores(self):
        store = InMemoryStore()
        errors = []

        def store_many(agent_name, count):
            try:
                for i in range(count):
                    store.store(agent_name, "scope", f"fact {i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=store_many, args=("agent_a", 50)),
            threading.Thread(target=store_many, args=("agent_b", 50)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(store.recall("agent_a", "scope", limit=100)) == 50
        assert len(store.recall("agent_b", "scope", limit=100)) == 50
