"""Tests for M9 memory schemas: CrossPollinationConfig and updated MemoryScope."""
import pytest
from pydantic import ValidationError

from temper_ai.memory._m9_schemas import (
    CrossPollinationConfig,
    DEFAULT_RETRIEVAL_K_POLLINATION,
    DEFAULT_RELEVANCE_THRESHOLD_POLLINATION,
    MAX_PUBLISHED_ENTRIES,
)
from temper_ai.memory._schemas import MemoryScope
from temper_ai.memory.constants import DEFAULT_TENANT_ID, SCOPE_SEPARATOR


class TestCrossPollinationConfig:
    """Tests for CrossPollinationConfig pydantic model."""

    def test_defaults(self):
        cfg = CrossPollinationConfig()
        assert cfg.enabled is False
        assert cfg.publish_output is False
        assert cfg.subscribe_to == []
        assert cfg.max_published_entries == MAX_PUBLISHED_ENTRIES
        assert cfg.retrieval_k == DEFAULT_RETRIEVAL_K_POLLINATION
        assert cfg.relevance_threshold == DEFAULT_RELEVANCE_THRESHOLD_POLLINATION

    def test_all_fields(self):
        cfg = CrossPollinationConfig(
            enabled=True,
            publish_output=True,
            subscribe_to=["agent-a", "agent-b"],
            max_published_entries=10,
            retrieval_k=3,
            relevance_threshold=0.9,
        )
        assert cfg.enabled is True
        assert cfg.publish_output is True
        assert cfg.subscribe_to == ["agent-a", "agent-b"]
        assert cfg.max_published_entries == 10
        assert cfg.retrieval_k == 3
        assert cfg.relevance_threshold == 0.9

    def test_max_published_entries_must_be_positive(self):
        with pytest.raises(ValidationError):
            CrossPollinationConfig(max_published_entries=0)

    def test_retrieval_k_must_be_positive(self):
        with pytest.raises(ValidationError):
            CrossPollinationConfig(retrieval_k=0)

    def test_relevance_threshold_min_bound(self):
        with pytest.raises(ValidationError):
            CrossPollinationConfig(relevance_threshold=-0.1)

    def test_relevance_threshold_max_bound(self):
        with pytest.raises(ValidationError):
            CrossPollinationConfig(relevance_threshold=1.1)

    def test_relevance_threshold_boundary_valid(self):
        cfg_low = CrossPollinationConfig(relevance_threshold=0.0)
        assert cfg_low.relevance_threshold == 0.0

        cfg_high = CrossPollinationConfig(relevance_threshold=1.0)
        assert cfg_high.relevance_threshold == 1.0

    def test_subscribe_to_empty_list_default(self):
        cfg1 = CrossPollinationConfig()
        cfg2 = CrossPollinationConfig()
        cfg1.subscribe_to.append("x")
        assert cfg2.subscribe_to == []


class TestMemoryScopeM9:
    """Tests for M9 additions to MemoryScope."""

    def test_agent_id_defaults_to_none(self):
        scope = MemoryScope()
        assert scope.agent_id is None

    def test_scope_key_uses_agent_id_when_set(self):
        scope = MemoryScope(
            tenant_id="t",
            workflow_name="wf",
            agent_name="agent-name",
            agent_id="agent-uuid-123",
        )
        assert scope.scope_key == "t:wf:agent-uuid-123"

    def test_scope_key_falls_back_to_agent_name_without_agent_id(self):
        scope = MemoryScope(
            tenant_id="t",
            workflow_name="wf",
            agent_name="agent-name",
        )
        assert scope.scope_key == "t:wf:agent-name"

    def test_scope_key_with_namespace_and_agent_id(self):
        scope = MemoryScope(
            tenant_id="t",
            workflow_name="wf",
            agent_name="agent-name",
            namespace="ns",
            agent_id="pid-001",
        )
        assert scope.scope_key == "t:ns:pid-001"

    def test_scope_key_separator_count(self):
        scope = MemoryScope(
            tenant_id="a", workflow_name="b", agent_id="c"
        )
        parts = scope.scope_key.split(SCOPE_SEPARATOR)
        assert len(parts) == 3

    def test_frozen_agent_id(self):
        scope = MemoryScope(agent_id="x")
        with pytest.raises(AttributeError):
            scope.agent_id = "y"  # type: ignore[misc]

    def test_backward_compat_no_agent_id(self):
        """Existing code without agent_id still works correctly."""
        scope = MemoryScope(tenant_id="tenant1", workflow_name="wf1", agent_name="agent1")
        assert scope.scope_key == "tenant1:wf1:agent1"
        assert scope.agent_id is None
