"""Tests for cross-agent memory sharing."""

from unittest.mock import MagicMock, patch

from temper_ai.agent.base_agent import AgentResponse
from temper_ai.memory._schemas import MemoryScope
from temper_ai.memory.constants import MEMORY_TYPE_EPISODIC
from temper_ai.memory.service import MemoryService
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    MemoryConfig,
    PromptConfig,
)


def _make_shared_config(shared_namespace="team_shared"):
    """Create config with shared_namespace set."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="sharing_agent",
            description="test",
            inference=InferenceConfig(provider="ollama", model="m"),
            prompt=PromptConfig(inline="Hi"),
            memory=MemoryConfig(
                enabled=True,
                type="episodic",
                scope="cross_session",
                provider="in_memory",
                shared_namespace=shared_namespace,
                relevance_threshold=0.0,
            ),
            error_handling=ErrorHandlingConfig(),
            tools=[],
        )
    )


def _make_agent(config):
    """Create a StandardAgent with mocked LLM and ToolRegistry."""
    with patch("temper_ai.agent.base_agent.create_llm_from_config") as mock_factory, \
         patch("temper_ai.agent.base_agent.ToolRegistry"):
        mock_factory.return_value = MagicMock()
        from temper_ai.agent.standard_agent import StandardAgent
        agent = StandardAgent(config)
    return agent


class TestSharedScopeBuilding:
    """Verify shared scope key format."""

    def test_build_shared_scope_format(self):
        svc = MemoryService(provider_name="in_memory")
        base = svc.build_scope(tenant_id="t", workflow_name="wf", agent_name="ag1")
        shared = svc.build_shared_scope(base, "team_ns")
        assert shared.namespace == "team_ns"
        assert shared.agent_name == ""
        assert shared.tenant_id == "t"
        # scope_key uses namespace when set
        assert "team_ns" in shared.scope_key

    def test_shared_scope_different_from_private(self):
        svc = MemoryService(provider_name="in_memory")
        private = svc.build_scope(tenant_id="t", workflow_name="wf", agent_name="ag1")
        shared = svc.build_shared_scope(private, "team")
        assert private.scope_key != shared.scope_key


class TestDualScopeRetrieval:
    """Memories from both scopes returned."""

    def test_retrieves_from_both_scopes(self):
        svc = MemoryService(provider_name="in_memory")
        private = svc.build_scope(tenant_id="t", workflow_name="wf", agent_name="ag1")
        shared = svc.build_shared_scope(private, "team")

        svc.store_episodic(private, "private finding about Python")
        svc.store_episodic(shared, "shared finding about Python")

        context = svc.retrieve_with_shared(private, shared, "Python")
        assert "private finding" in context
        assert "shared finding" in context

    def test_empty_scopes_return_empty(self):
        svc = MemoryService(provider_name="in_memory")
        private = svc.build_scope(tenant_id="t", workflow_name="wf", agent_name="ag1")
        shared = svc.build_shared_scope(private, "team")

        context = svc.retrieve_with_shared(private, shared, "anything")
        assert context == ""


class TestDeduplication:
    """Same content in both scopes not duplicated."""

    def test_duplicate_content_deduplicated(self):
        svc = MemoryService(provider_name="in_memory")
        private = svc.build_scope(tenant_id="t", workflow_name="wf", agent_name="ag1")
        shared = svc.build_shared_scope(private, "team")

        svc.store_episodic(private, "same content about testing")
        svc.store_episodic(shared, "same content about testing")

        context = svc.retrieve_with_shared(private, shared, "testing")
        # Count occurrences - should appear only once
        assert context.count("same content about testing") == 1


class TestSharedStorage:
    """After run, memory in both private and shared scopes."""

    def test_on_after_run_stores_in_both_scopes(self):
        config = _make_shared_config()
        agent = _make_agent(config)

        result = AgentResponse(output="shared output data", metadata={})
        agent._on_after_run(result)

        svc = agent._get_memory_service()
        private = agent._build_memory_scope()
        shared = svc.build_shared_scope(private, "team_shared")

        private_entries = svc.list_memories(private, memory_type=MEMORY_TYPE_EPISODIC)
        shared_entries = svc.list_memories(shared, memory_type=MEMORY_TYPE_EPISODIC)

        assert len(private_entries) == 1
        assert len(shared_entries) == 1
        assert private_entries[0].content == "shared output data"
        assert shared_entries[0].content == "shared output data"

    def test_shared_entry_has_source_agent_metadata(self):
        config = _make_shared_config()
        agent = _make_agent(config)

        result = AgentResponse(output="tagged output", metadata={})
        agent._on_after_run(result)

        svc = agent._get_memory_service()
        private = agent._build_memory_scope()
        shared = svc.build_shared_scope(private, "team_shared")

        shared_entries = svc.list_memories(shared)
        assert shared_entries[0].metadata.get("source_agent") == "sharing_agent"


class TestNoSharingWhenDisabled:
    """Without config, only private scope used."""

    def test_no_shared_storage_without_namespace(self):
        config = AgentConfig(
            agent=AgentConfigInner(
                name="solo_agent",
                description="test",
                inference=InferenceConfig(provider="ollama", model="m"),
                prompt=PromptConfig(inline="Hi"),
                memory=MemoryConfig(
                    enabled=True, type="episodic", scope="cross_session",
                    provider="in_memory",
                ),
                error_handling=ErrorHandlingConfig(),
                tools=[],
            )
        )
        agent = _make_agent(config)

        result = AgentResponse(output="solo output", metadata={})
        agent._on_after_run(result)

        svc = agent._get_memory_service()
        private = agent._build_memory_scope()
        entries = svc.list_memories(private)
        assert len(entries) == 1

    def test_inject_uses_only_private_when_no_namespace(self):
        config = AgentConfig(
            agent=AgentConfigInner(
                name="solo_agent",
                description="test",
                inference=InferenceConfig(provider="ollama", model="m"),
                prompt=PromptConfig(inline="Hi"),
                memory=MemoryConfig(
                    enabled=True, type="episodic", scope="cross_session",
                    provider="in_memory", relevance_threshold=0.0,
                ),
                error_handling=ErrorHandlingConfig(),
                tools=[],
            )
        )
        agent = _make_agent(config)

        svc = agent._get_memory_service()
        scope = agent._build_memory_scope()
        svc.store_episodic(scope, "private memory about testing")

        template = agent._inject_memory_context("prompt", {"topic": "testing"})
        assert "private memory" in template
