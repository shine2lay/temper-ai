"""Tests for the SQL-backed memory store."""

import pytest

from temper_ai.memory import SqlMemoryStore

SCOPE = "project:/repo"
OTHER = "project:/other"


@pytest.fixture
def store():
    # conftest's autouse fixture gives each test a fresh in-memory database.
    return SqlMemoryStore()


class TestSqlMemoryStore:
    def test_store_and_recall(self, store):
        store.store("reviewer", SCOPE, "Uses FastAPI + SQLModel")

        recalled = store.recall("reviewer", SCOPE)

        assert [m.content for m in recalled] == ["Uses FastAPI + SQLModel"]

    def test_recall_is_most_recent_first(self, store):
        store.store("reviewer", SCOPE, "first")
        store.store("reviewer", SCOPE, "second")

        assert [m.content for m in store.recall("reviewer", SCOPE)] == ["second", "first"]

    def test_recall_respects_limit(self, store):
        for i in range(5):
            store.store("reviewer", SCOPE, f"note {i}")

        assert len(store.recall("reviewer", SCOPE, limit=2)) == 2

    def test_memories_are_scoped_per_agent_and_project(self, store):
        store.store("reviewer", SCOPE, "belongs to this repo")
        store.store("reviewer", OTHER, "belongs elsewhere")
        store.store("planner", SCOPE, "belongs to another agent")

        assert [m.content for m in store.recall("reviewer", SCOPE)] == ["belongs to this repo"]

    def test_search_matches_content_case_insensitively(self, store):
        store.store("reviewer", SCOPE, "Prefers PyTest over unittest")
        store.store("reviewer", SCOPE, "Deploys with docker compose")

        found = store.search("pytest", "reviewer", SCOPE)

        assert [m.content for m in found] == ["Prefers PyTest over unittest"]

    def test_search_without_a_query_behaves_like_recall(self, store):
        store.store("reviewer", SCOPE, "a")
        store.store("reviewer", SCOPE, "b")

        assert len(store.search("", "reviewer", SCOPE)) == 2

    def test_metadata_round_trips(self, store):
        store.store("reviewer", SCOPE, "with metadata", metadata={"run": "abc", "n": 2})

        assert store.recall("reviewer", SCOPE)[0].metadata == {"run": "abc", "n": 2}

    def test_clear_returns_count_and_only_clears_that_scope(self, store):
        store.store("reviewer", SCOPE, "one")
        store.store("reviewer", SCOPE, "two")
        store.store("reviewer", OTHER, "kept")

        assert store.clear("reviewer", SCOPE) == 2
        assert store.recall("reviewer", SCOPE) == []
        assert [m.content for m in store.recall("reviewer", OTHER)] == ["kept"]

    def test_clear_on_empty_scope_is_zero(self, store):
        assert store.clear("nobody", SCOPE) == 0

    def test_survives_a_new_store_instance(self, store):
        """The point of this backend: memory outlives the object that wrote it
        (and, in production, the process and container that wrote it)."""
        store.store("reviewer", SCOPE, "persisted")

        assert [m.content for m in SqlMemoryStore().recall("reviewer", SCOPE)] == ["persisted"]
