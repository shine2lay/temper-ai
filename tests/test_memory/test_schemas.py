"""Tests for memory data schemas (MemoryScope, MemoryEntry, MemorySearchResult)."""

import uuid
from datetime import datetime, timezone

import pytest

from temper_ai.memory._schemas import MemoryEntry, MemoryScope, MemorySearchResult
from temper_ai.memory.constants import DEFAULT_TENANT_ID, SCOPE_SEPARATOR


class TestMemoryScope:
    """Tests for MemoryScope dataclass."""

    def test_defaults(self):
        scope = MemoryScope()
        assert scope.tenant_id == DEFAULT_TENANT_ID
        assert scope.workflow_name == ""
        assert scope.agent_name == ""
        assert scope.namespace is None

    def test_scope_key(self):
        scope = MemoryScope(
            tenant_id="tenant1",
            workflow_name="wf1",
            agent_name="agent1",
        )
        assert scope.scope_key == "tenant1:wf1:agent1"

    def test_scope_key_with_namespace(self):
        """Namespace overrides workflow_name in the key."""
        scope = MemoryScope(
            tenant_id="t",
            workflow_name="wf",
            agent_name="a",
            namespace="ns",
        )
        assert scope.scope_key == "t:ns:a"

    def test_frozen(self):
        """MemoryScope should be immutable."""
        scope = MemoryScope()
        with pytest.raises(AttributeError):
            scope.tenant_id = "new"  # type: ignore[misc]

    def test_scope_key_separator(self):
        scope = MemoryScope(tenant_id="a", workflow_name="b", agent_name="c")
        assert SCOPE_SEPARATOR in scope.scope_key
        parts = scope.scope_key.split(SCOPE_SEPARATOR)
        assert len(parts) == 3

    def test_scope_key_empty_fields(self):
        scope = MemoryScope(tenant_id="t")
        assert scope.scope_key == "t::"


class TestMemoryEntry:
    """Tests for MemoryEntry dataclass."""

    def test_defaults(self):
        entry = MemoryEntry(content="test", memory_type="episodic")
        assert entry.content == "test"
        assert entry.memory_type == "episodic"
        assert len(entry.id) > 0
        assert isinstance(entry.created_at, datetime)
        assert entry.relevance_score == 0.0

    def test_auto_id(self):
        """Each entry gets a unique auto-generated ID."""
        e1 = MemoryEntry(content="a", memory_type="episodic")
        e2 = MemoryEntry(content="b", memory_type="episodic")
        assert e1.id != e2.id

    def test_custom_fields(self):
        entry = MemoryEntry(
            content="custom",
            memory_type="procedural",
            id="my-id",
            metadata={"key": "val"},
            relevance_score=0.95,
        )
        assert entry.id == "my-id"
        assert entry.metadata == {"key": "val"}
        assert entry.relevance_score == 0.95

    def test_metadata_default(self):
        entry = MemoryEntry(content="x", memory_type="episodic")
        assert entry.metadata == {}

    def test_created_at_utc(self):
        entry = MemoryEntry(content="x", memory_type="episodic")
        assert entry.created_at.tzinfo == timezone.utc


class TestMemorySearchResult:
    """Tests for MemorySearchResult dataclass."""

    def test_defaults(self):
        scope = MemoryScope()
        result = MemorySearchResult(entries=[], query="q", scope=scope)
        assert result.entries == []
        assert result.query == "q"
        assert result.scope == scope
        assert result.search_time_ms == 0.0

    def test_with_entries(self):
        entry = MemoryEntry(content="c", memory_type="episodic")
        scope = MemoryScope()
        result = MemorySearchResult(
            entries=[entry],
            query="test",
            scope=scope,
            search_time_ms=42.0,
        )
        assert len(result.entries) == 1
        assert result.search_time_ms == 42.0
