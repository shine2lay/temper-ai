"""Tests for MemoryService — the agent-facing wrapper."""

import pytest

from temper_ai.memory.base import MemoryEntry
from temper_ai.memory.in_memory_store import InMemoryStore
from temper_ai.memory.service import MemoryService


@pytest.fixture
def service():
    return MemoryService(InMemoryStore())


class TestStore:
    def test_store_returns_id(self, service):
        mem_id = service.store("agent_a", "scope1", "test content")
        assert isinstance(mem_id, str)
        assert len(mem_id) > 0

    def test_store_with_metadata(self, service):
        service.store("agent_a", "scope1", "fact", metadata={"run_id": "run-1"})
        entries = service.recall_entries("agent_a", "scope1")
        assert entries[0].metadata == {"run_id": "run-1"}


class TestRecall:
    def test_recall_returns_strings(self, service):
        service.store("agent_a", "scope1", "FastAPI project")
        service.store("agent_a", "scope1", "Uses SQLModel")
        memories = service.recall("agent_a", "scope1")
        assert isinstance(memories, list)
        assert all(isinstance(m, str) for m in memories)
        assert "FastAPI project" in memories
        assert "Uses SQLModel" in memories

    def test_recall_empty(self, service):
        memories = service.recall("agent_a", "scope1")
        assert memories == []

    def test_recall_respects_limit(self, service):
        for i in range(10):
            service.store("agent_a", "scope1", f"fact {i}")
        memories = service.recall("agent_a", "scope1", limit=3)
        assert len(memories) == 3

    def test_recall_scoped_by_agent(self, service):
        service.store("agent_a", "scope1", "A knows this")
        service.store("agent_b", "scope1", "B knows this")
        assert service.recall("agent_a", "scope1") == ["A knows this"]
        assert service.recall("agent_b", "scope1") == ["B knows this"]


class TestRecallEntries:
    def test_returns_memory_entry_objects(self, service):
        service.store("agent_a", "scope1", "content")
        entries = service.recall_entries("agent_a", "scope1")
        assert len(entries) == 1
        assert isinstance(entries[0], MemoryEntry)
        assert entries[0].content == "content"
        assert entries[0].id  # has an ID
        assert entries[0].created_at  # has a timestamp


class TestSearch:
    def test_search_returns_strings(self, service):
        service.store("agent_a", "scope1", "Uses FastAPI framework")
        service.store("agent_a", "scope1", "Has PostgreSQL")
        results = service.search("FastAPI", "agent_a", "scope1")
        assert isinstance(results, list)
        assert all(isinstance(r, str) for r in results)
        assert len(results) == 1
        assert "FastAPI" in results[0]

    def test_search_entries_returns_objects(self, service):
        service.store("agent_a", "scope1", "Uses FastAPI")
        entries = service.search_entries("FastAPI", "agent_a", "scope1")
        assert len(entries) == 1
        assert isinstance(entries[0], MemoryEntry)

    def test_search_no_results(self, service):
        service.store("agent_a", "scope1", "Uses Django")
        results = service.search("FastAPI", "agent_a", "scope1")
        assert results == []


class TestClear:
    def test_clear_removes_all(self, service):
        service.store("agent_a", "scope1", "fact 1")
        service.store("agent_a", "scope1", "fact 2")
        count = service.clear("agent_a", "scope1")
        assert count == 2
        assert service.recall("agent_a", "scope1") == []

    def test_clear_scoped(self, service):
        service.store("agent_a", "scope1", "scope1 fact")
        service.store("agent_a", "scope2", "scope2 fact")
        service.clear("agent_a", "scope1")
        assert service.recall("agent_a", "scope1") == []
        assert service.recall("agent_a", "scope2") == ["scope2 fact"]


class TestMemoryFlow:
    """Test the full memory flow as it would happen during agent execution."""

    def test_agent_memory_lifecycle(self, service):
        agent = "code_reviewer"
        scope = "project:/home/user/myapp"

        # Run 1: agent stores observations
        service.store(agent, scope, "Project uses FastAPI + SQLModel",
                      metadata={"run_id": "run-1"})
        service.store(agent, scope, "Test coverage is 80%+",
                      metadata={"run_id": "run-1"})

        # Run 2: agent recalls previous observations
        memories = service.recall(agent, scope)
        assert len(memories) == 2
        assert "FastAPI" in memories[0] or "FastAPI" in memories[1]

        # Run 2: agent stores new observations
        service.store(agent, scope, "Auth uses JWT tokens",
                      metadata={"run_id": "run-2"})

        # Run 3: agent recalls all observations
        memories = service.recall(agent, scope)
        assert len(memories) == 3

    def test_same_agent_different_scopes(self, service):
        """Same agent identity, different projects — separate memories."""
        agent = "senior_engineer"
        service.store(agent, "project:/app1", "App1 uses React")
        service.store(agent, "project:/app2", "App2 uses Vue")

        assert service.recall(agent, "project:/app1") == ["App1 uses React"]
        assert service.recall(agent, "project:/app2") == ["App2 uses Vue"]

    def test_different_agents_same_scope(self, service):
        """Different agents working on same project — separate memories."""
        scope = "project:/myapp"
        service.store("security_reviewer", scope, "Found SQL injection risk")
        service.store("quality_reviewer", scope, "Code follows PEP8")

        sec_memories = service.recall("security_reviewer", scope)
        qual_memories = service.recall("quality_reviewer", scope)

        assert len(sec_memories) == 1
        assert "SQL injection" in sec_memories[0]
        assert len(qual_memories) == 1
        assert "PEP8" in qual_memories[0]
