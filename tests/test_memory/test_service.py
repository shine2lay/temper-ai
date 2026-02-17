"""Tests for MemoryService."""

import pytest

from src.memory._schemas import MemoryScope
from src.memory.constants import (
    DEFAULT_TENANT_ID,
    MEMORY_TYPE_CROSS_SESSION,
    MEMORY_TYPE_EPISODIC,
    MEMORY_TYPE_PROCEDURAL,
)
from src.memory.service import MemoryService


class TestMemoryServiceInit:
    """Initialization tests."""

    def test_init_default_provider(self, service):
        assert service is not None

    def test_init_custom_provider(self):
        # in_memory is the only provider available without external deps
        svc = MemoryService(provider_name="in_memory")
        assert svc is not None

    def test_unknown_provider_raises(self):
        with pytest.raises(KeyError, match="Unknown memory provider"):
            MemoryService(provider_name="nonexistent")


class TestMemoryServiceScope:
    """Scope building tests."""

    def test_build_scope(self, service):
        scope = service.build_scope(
            tenant_id="t1",
            workflow_name="wf1",
            agent_name="ag1",
        )
        assert isinstance(scope, MemoryScope)
        assert scope.tenant_id == "t1"
        assert scope.workflow_name == "wf1"
        assert scope.agent_name == "ag1"

    def test_build_scope_with_namespace(self, service):
        scope = service.build_scope(
            tenant_id="t1",
            workflow_name="wf1",
            agent_name="ag1",
            namespace="ns1",
        )
        assert scope.namespace == "ns1"
        # Namespace overrides workflow_name in key
        assert "ns1" in scope.scope_key


class TestMemoryServiceStorage:
    """Store and retrieve tests."""

    def test_store_episodic(self, service):
        scope = service.build_scope()
        mid = service.store_episodic(scope, "episodic content")
        assert isinstance(mid, str)
        entries = service.list_memories(scope)
        assert len(entries) == 1
        assert entries[0].memory_type == MEMORY_TYPE_EPISODIC

    def test_store_procedural(self, service):
        scope = service.build_scope()
        mid = service.store_procedural(scope, "procedural content")
        assert isinstance(mid, str)
        entries = service.list_memories(scope)
        assert len(entries) == 1
        assert entries[0].memory_type == MEMORY_TYPE_PROCEDURAL

    def test_store_cross_session(self, service):
        scope = service.build_scope()
        mid = service.store_cross_session(scope, "cross content")
        assert isinstance(mid, str)
        entries = service.list_memories(scope)
        assert len(entries) == 1
        assert entries[0].memory_type == MEMORY_TYPE_CROSS_SESSION

    def test_list_memories(self, service):
        scope = service.build_scope()
        service.store_episodic(scope, "a")
        service.store_procedural(scope, "b")
        entries = service.list_memories(scope)
        assert len(entries) == 2

    def test_list_memories_filtered_by_type(self, service):
        scope = service.build_scope()
        service.store_episodic(scope, "epi")
        service.store_procedural(scope, "proc")
        entries = service.list_memories(scope, memory_type=MEMORY_TYPE_EPISODIC)
        assert len(entries) == 1
        assert entries[0].memory_type == MEMORY_TYPE_EPISODIC

    def test_clear_memories(self, service):
        scope = service.build_scope()
        service.store_episodic(scope, "to clear")
        count = service.clear_memories(scope)
        assert count == 1
        assert len(service.list_memories(scope)) == 0


class TestMemoryServiceRetrieval:
    """Context retrieval tests."""

    def test_retrieve_context_empty(self, service):
        scope = service.build_scope()
        ctx = service.retrieve_context(scope, "anything")
        assert ctx == ""

    def test_retrieve_context_with_matches(self, service):
        scope = service.build_scope()
        service.store_episodic(scope, "important finding about testing")
        ctx = service.retrieve_context(scope, "testing")
        assert "testing" in ctx

    def test_retrieve_context_formats_markdown(self, service):
        scope = service.build_scope()
        service.store_episodic(scope, "relevant content here")
        ctx = service.retrieve_context(scope, "relevant")
        assert ctx.startswith("# Relevant Memories")
