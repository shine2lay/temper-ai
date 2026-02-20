"""Tests for persistent agent memory scope integration in StandardAgent (M9)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_agent_config(
    persistent=False,
    agent_id=None,
    cross_pollination=None,
    name="test_agent",
    memory_enabled=True,
):
    """Build a minimal AgentConfig-like mock for StandardAgent tests."""
    mem_cfg = MagicMock()
    mem_cfg.enabled = memory_enabled
    mem_cfg.tenant_id = "default"
    mem_cfg.memory_namespace = None
    mem_cfg.retrieval_k = 3
    mem_cfg.relevance_threshold = 0.7
    mem_cfg.decay_factor = 1.0
    mem_cfg.max_episodes = 10
    mem_cfg.auto_extract_procedural = False
    mem_cfg.shared_namespace = None
    mem_cfg.provider = "in_memory"

    inner = MagicMock()
    inner.name = name
    inner.persistent = persistent
    inner.agent_id = agent_id
    inner.cross_pollination = cross_pollination
    inner.memory = mem_cfg
    inner.reasoning = MagicMock(enabled=False)
    inner.context_management = MagicMock(enabled=False)
    inner.output_schema = None
    inner.output_guardrails = MagicMock(enabled=False)
    inner.safety = MagicMock(
        max_tool_calls_per_execution=10,
        max_execution_time_seconds=600,
    )
    inner.prompt_optimization = None
    inner.dialogue_aware = False

    config = MagicMock()
    config.agent = inner
    return config


class TestPersistentMemoryScope:
    def _build_scope_via_agent(self, persistent, agent_id=None, workflow_name="wf-1"):
        """Helper: build scope using the StandardAgent._build_memory_scope logic."""
        from temper_ai.memory._schemas import MemoryScope
        from temper_ai.registry.constants import PERSISTENT_NAMESPACE_PREFIX

        # Simulate what StandardAgent._build_memory_scope does
        base_scope = MemoryScope(
            tenant_id="default",
            workflow_name=workflow_name,
            agent_name="test_agent",
            namespace=None,
        )
        if persistent:
            base_scope = MemoryScope(
                tenant_id=base_scope.tenant_id,
                workflow_name="",
                agent_name=base_scope.agent_name,
                namespace=f"{PERSISTENT_NAMESPACE_PREFIX}test_agent",
                agent_id=agent_id,
            )
        return base_scope

    def test_non_persistent_uses_normal_scope(self):
        scope = self._build_scope_via_agent(persistent=False)
        assert scope.workflow_name == "wf-1"
        assert scope.namespace is None

    def test_persistent_uses_persistent_namespace(self):
        scope = self._build_scope_via_agent(persistent=True)
        assert scope.namespace == "persistent__test_agent"

    def test_persistent_namespace_format(self):
        scope = self._build_scope_via_agent(persistent=True)
        assert scope.namespace.startswith("persistent__")
        assert "test_agent" in scope.namespace

    def test_persistent_clears_workflow_name(self):
        scope = self._build_scope_via_agent(persistent=True)
        assert scope.workflow_name == ""

    def test_persistent_includes_agent_id_when_set(self):
        scope = self._build_scope_via_agent(persistent=True, agent_id="agent-uuid-123")
        assert scope.agent_id == "agent-uuid-123"

    def test_persistent_scope_key_uses_agent_id(self):
        scope = self._build_scope_via_agent(persistent=True, agent_id="myid")
        assert "myid" in scope.scope_key


class TestInjectPersistentContext:
    def _make_standard_agent_mock(self, persistent=False, agent_id=None, cross_pollination=None):
        """Build a StandardAgent-like mock to test _inject_persistent_context."""
        from temper_ai.agent.standard_agent import StandardAgent

        config = _make_agent_config(
            persistent=persistent,
            agent_id=agent_id,
            cross_pollination=cross_pollination,
        )

        with patch.object(StandardAgent, "__init__", lambda self, c: None):
            agent = StandardAgent.__new__(StandardAgent)
            agent.config = config
            agent.name = "test_agent"
            agent._memory_service = None
            return agent

    def test_non_persistent_is_noop(self):
        agent = self._make_standard_agent_mock(persistent=False)
        result = agent._inject_persistent_context("my prompt", None)
        assert result == "my prompt"

    def test_persistent_injects_execution_mode(self):
        agent = self._make_standard_agent_mock(persistent=True)
        from temper_ai.agent._m9_context_helpers import EXECUTION_MODE_SECTION

        result = agent._inject_persistent_context("my prompt", None)
        assert EXECUTION_MODE_SECTION in result

    def test_persistent_desk_mode_without_context(self):
        agent = self._make_standard_agent_mock(persistent=True)
        result = agent._inject_persistent_context("my prompt", None)
        assert "conversation mode" in result

    def test_persistent_project_mode_with_workflow_context(self):
        from temper_ai.shared.core.context import ExecutionContext

        agent = self._make_standard_agent_mock(persistent=True)
        ctx = ExecutionContext(workflow_id="wf-abc")
        result = agent._inject_persistent_context("my prompt", ctx)
        assert "workflow pipeline" in result

    def test_persistent_injects_goals_when_agent_id_set(self):
        agent = self._make_standard_agent_mock(persistent=True, agent_id="agent-42")
        mock_goals_text = "Active Goals:\n- Ship feature"
        with patch(
            "temper_ai.goals.agent_goals.AgentGoalService.format_goals_context",
            return_value=mock_goals_text,
        ):
            result = agent._inject_persistent_context("my prompt", None)
            assert "Active Goals:" in result

    def test_persistent_skips_goals_when_no_agent_id(self):
        agent = self._make_standard_agent_mock(persistent=True, agent_id=None)
        with patch(
            "temper_ai.goals.agent_goals.AgentGoalService.format_goals_context"
        ) as mock_goals:
            agent._inject_persistent_context("my prompt", None)
            mock_goals.assert_not_called()

    def test_persistent_cross_pollination_when_configured(self):
        cross_cfg = MagicMock()
        cross_cfg.enabled = True
        cross_cfg.subscribe_to = ["agent-b"]
        cross_cfg.retrieval_k = 5
        cross_cfg.relevance_threshold = 0.7
        agent = self._make_standard_agent_mock(persistent=True, cross_pollination=cross_cfg)
        agent._memory_service = MagicMock()

        with patch(
            "temper_ai.memory.cross_pollination.retrieve_subscribed_knowledge",
            return_value=[{"agent_name": "agent-b", "content": "insight", "relevance_score": 0.9}],
        ), patch(
            "temper_ai.memory.cross_pollination.format_cross_pollination_context",
            return_value="[From agent-b]: insight",
        ):
            result = agent._inject_persistent_context("my prompt", None)
            assert "[From agent-b]: insight" in result


class TestMaybePublishPersistentOutput:
    def _make_agent(self, persistent=False, publish_output=False):
        from temper_ai.agent.standard_agent import StandardAgent

        cross_cfg = None
        if publish_output:
            cross_cfg = MagicMock()
            cross_cfg.publish_output = True

        config = _make_agent_config(persistent=persistent, cross_pollination=cross_cfg)
        with patch.object(StandardAgent, "__init__", lambda self, c: None):
            agent = StandardAgent.__new__(StandardAgent)
            agent.config = config
            agent.name = "test_agent"
            agent._memory_service = MagicMock()
            return agent

    def test_does_not_publish_when_not_persistent(self):
        agent = self._make_agent(persistent=False, publish_output=True)
        result = MagicMock(output="some output")
        with patch("temper_ai.memory.cross_pollination.publish_knowledge") as mock_pub:
            agent._maybe_publish_persistent_output(result)
            mock_pub.assert_not_called()

    def test_does_not_publish_when_publish_output_false(self):
        agent = self._make_agent(persistent=True, publish_output=False)
        result = MagicMock(output="some output")
        with patch("temper_ai.memory.cross_pollination.publish_knowledge") as mock_pub:
            agent._maybe_publish_persistent_output(result)
            mock_pub.assert_not_called()

    def test_publishes_when_persistent_and_publish_output_true(self):
        agent = self._make_agent(persistent=True, publish_output=True)
        result = MagicMock(output="agent output text")
        with patch(
            "temper_ai.memory.cross_pollination.publish_knowledge",
            return_value="entry-abc",
        ) as mock_pub:
            agent._maybe_publish_persistent_output(result)
            mock_pub.assert_called_once()

    def test_skips_publish_when_output_empty(self):
        agent = self._make_agent(persistent=True, publish_output=True)
        result = MagicMock(output="")
        with patch("temper_ai.memory.cross_pollination.publish_knowledge") as mock_pub:
            agent._maybe_publish_persistent_output(result)
            mock_pub.assert_not_called()
