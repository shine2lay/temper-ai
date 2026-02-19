"""Integration tests for StandardAgent with memory enabled."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent.base_agent import AgentResponse
from temper_ai.memory._schemas import MemoryScope
from temper_ai.memory.constants import MEMORY_TYPE_EPISODIC, MEMORY_TYPE_PROCEDURAL
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    MemoryConfig,
    PromptConfig,
)


def _make_config(memory_enabled=True):
    """Create an AgentConfig with memory settings."""
    memory_kwargs = {"enabled": memory_enabled, "provider": "in_memory"}
    if memory_enabled:
        memory_kwargs["type"] = "episodic"
        memory_kwargs["scope"] = "cross_session"

    return AgentConfig(
        agent=AgentConfigInner(
            name="test_agent",
            description="test agent",
            inference=InferenceConfig(provider="ollama", model="test-model"),
            prompt=PromptConfig(inline="Hello {{ topic }}"),
            memory=MemoryConfig(**memory_kwargs),
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


class TestMemoryDisabledByDefault:
    """Tests for default memory behavior."""

    def test_memory_disabled_by_default(self):
        config = AgentConfig(
            agent=AgentConfigInner(
                name="no_mem",
                description="test",
                inference=InferenceConfig(provider="ollama", model="m"),
                prompt=PromptConfig(inline="Hi"),
                error_handling=ErrorHandlingConfig(),
                tools=[],
            )
        )
        assert config.agent.memory.enabled is False


class TestMemoryInjection:
    """Tests for memory context injection into prompts."""

    def test_build_prompt_without_memory(self):
        """When memory is disabled, prompt is unchanged."""
        config = _make_config(memory_enabled=False)
        agent = _make_agent(config)
        template = agent._inject_memory_context("base prompt", {"topic": "AI"})
        assert template == "base prompt"

    def test_build_prompt_with_memory_appends_context(self):
        """When memory is enabled and has results, context is appended."""
        config = _make_config(memory_enabled=True)
        agent = _make_agent(config)
        # Override threshold to 0.0 so simple substring matching works
        agent.config.agent.memory.relevance_threshold = 0.0

        # Pre-populate memory
        svc = agent._get_memory_service()
        scope = agent._build_memory_scope()
        svc.store_episodic(scope, "previous finding about AI")

        template = agent._inject_memory_context("base prompt", {"topic": "AI"})
        assert "previous finding about AI" in template
        assert template.startswith("base prompt")

    def test_inject_memory_context_graceful_degradation(self):
        """If memory service raises, template is returned unchanged."""
        config = _make_config(memory_enabled=True)
        agent = _make_agent(config)

        with patch.object(
            agent, "_get_memory_service",
            side_effect=RuntimeError("memory down"),
        ):
            template = agent._inject_memory_context("safe prompt", {"x": "y"})
        assert template == "safe prompt"


class TestMemoryAfterRun:
    """Tests for episodic memory storage after agent run."""

    def test_on_after_run_stores_episodic(self):
        """After run, output should be stored as episodic memory."""
        config = _make_config(memory_enabled=True)
        agent = _make_agent(config)

        result = AgentResponse(output="important output", metadata={})
        returned = agent._on_after_run(result)

        assert returned is result
        # Verify memory was stored
        scope = agent._build_memory_scope()
        entries = agent._get_memory_service().list_memories(scope)
        assert len(entries) == 1
        assert entries[0].content == "important output"

    def test_on_after_run_graceful_degradation(self):
        """If memory storage fails, result is still returned."""
        config = _make_config(memory_enabled=True)
        agent = _make_agent(config)

        with patch.object(
            agent, "_get_memory_service",
            side_effect=RuntimeError("storage down"),
        ):
            result = AgentResponse(output="output", metadata={})
            returned = agent._on_after_run(result)
        assert returned is result

    def test_on_after_run_skips_when_disabled(self):
        """With memory disabled, _on_after_run should be a no-op."""
        config = _make_config(memory_enabled=False)
        agent = _make_agent(config)
        result = AgentResponse(output="output", metadata={})
        returned = agent._on_after_run(result)
        assert returned is result


class TestMemoryServiceLifecycle:
    """Tests for lazy memory service creation."""

    def test_memory_service_lazy_creation(self):
        """Service should not be created until first use."""
        config = _make_config(memory_enabled=True)
        agent = _make_agent(config)
        assert agent._memory_service is None

        # First access creates it
        svc = agent._get_memory_service()
        assert svc is not None
        assert agent._memory_service is svc

    def test_memory_scope_uses_config_fields(self):
        """Scope should use tenant_id from config."""
        config = _make_config(memory_enabled=True)
        agent = _make_agent(config)
        scope = agent._build_memory_scope()
        assert scope.agent_name == "test_agent"
        assert isinstance(scope, MemoryScope)


def _make_extraction_config():
    """Create config with auto_extract_procedural enabled."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="extractor_agent",
            description="test agent",
            inference=InferenceConfig(provider="ollama", model="test-model"),
            prompt=PromptConfig(inline="Hello"),
            memory=MemoryConfig(
                enabled=True,
                type="episodic",
                scope="cross_session",
                provider="in_memory",
                auto_extract_procedural=True,
            ),
            error_handling=ErrorHandlingConfig(),
            tools=[],
        )
    )


class TestProceduralExtraction:
    """Tests for auto procedural extraction on after_run."""

    def test_on_after_run_extracts_procedural_when_enabled(self):
        config = _make_extraction_config()
        agent = _make_agent(config)

        # Mock LLM to return patterns
        mock_response = MagicMock()
        mock_response.content = "1. Always validate input\n2. Log errors"
        agent.llm.complete = MagicMock(return_value=mock_response)

        result = AgentResponse(output="some agent output", metadata={})
        agent._on_after_run(result)

        scope = agent._build_memory_scope()
        entries = agent._get_memory_service().list_memories(
            scope, memory_type=MEMORY_TYPE_PROCEDURAL,
        )
        assert len(entries) == 2
        assert "Always validate input" in entries[0].content

    def test_on_after_run_skips_extraction_when_disabled(self):
        config = _make_config(memory_enabled=True)
        agent = _make_agent(config)

        result = AgentResponse(output="some output", metadata={})
        agent._on_after_run(result)

        scope = agent._build_memory_scope()
        procedural = agent._get_memory_service().list_memories(
            scope, memory_type=MEMORY_TYPE_PROCEDURAL,
        )
        assert len(procedural) == 0

    def test_on_after_run_graceful_on_extraction_error(self):
        config = _make_extraction_config()
        agent = _make_agent(config)

        # Make LLM raise
        agent.llm.complete = MagicMock(side_effect=RuntimeError("LLM down"))

        result = AgentResponse(output="output text", metadata={})
        returned = agent._on_after_run(result)

        # Should still return result despite extraction failure
        assert returned is result
        # Episodic should still be stored
        scope = agent._build_memory_scope()
        entries = agent._get_memory_service().list_memories(
            scope, memory_type=MEMORY_TYPE_EPISODIC,
        )
        assert len(entries) == 1
