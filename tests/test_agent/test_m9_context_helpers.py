"""Tests for M9 persistent agent context helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent._m9_context_helpers import (
    CROSS_POLLINATION_SECTION,
    DESK_MODE,
    EXECUTION_MODE_SECTION,
    GOALS_SECTION,
    PROJECT_MODE,
    detect_execution_mode,
    inject_cross_pollination_context,
    inject_execution_mode_context,
    inject_project_goal_context,
    sync_workflow_learnings_to_agent,
)


class TestDetectExecutionMode:
    def test_returns_project_when_workflow_id_present(self):
        ctx = {"workflow_id": "wf-123"}
        assert detect_execution_mode(ctx) == PROJECT_MODE

    def test_returns_desk_when_no_workflow_id(self):
        ctx = {}
        assert detect_execution_mode(ctx) == DESK_MODE

    def test_returns_desk_when_workflow_id_is_none(self):
        ctx = {"workflow_id": None}
        assert detect_execution_mode(ctx) == DESK_MODE

    def test_returns_desk_when_workflow_id_is_empty_string(self):
        ctx = {"workflow_id": ""}
        assert detect_execution_mode(ctx) == DESK_MODE

    def test_ignores_other_keys(self):
        ctx = {"stage_id": "s-1", "agent_id": "a-1"}
        assert detect_execution_mode(ctx) == DESK_MODE


class TestInjectExecutionModeContext:
    def test_project_mode_appends_pipeline_text(self):
        result = inject_execution_mode_context("Base prompt", PROJECT_MODE)
        assert EXECUTION_MODE_SECTION in result
        assert "workflow pipeline" in result

    def test_desk_mode_appends_conversation_text(self):
        result = inject_execution_mode_context("Base prompt", DESK_MODE)
        assert EXECUTION_MODE_SECTION in result
        assert "conversation mode" in result

    def test_original_template_preserved(self):
        template = "My original template"
        result = inject_execution_mode_context(template, DESK_MODE)
        assert result.startswith(template)

    def test_unknown_mode_defaults_to_desk_text(self):
        result = inject_execution_mode_context("Base", "unknown_mode")
        assert "conversation mode" in result


class TestInjectProjectGoalContext:
    def test_injects_goal_context_when_goals_present(self):
        goal_service = MagicMock()
        goal_service.format_goals_context.return_value = "Active Goals:\n- Fix bug"
        result = inject_project_goal_context("Base", "agent-1", goal_service)
        assert GOALS_SECTION in result
        assert "Active Goals:" in result
        goal_service.format_goals_context.assert_called_once_with("agent-1", max_chars=1000)

    def test_returns_original_when_no_goals(self):
        goal_service = MagicMock()
        goal_service.format_goals_context.return_value = ""
        result = inject_project_goal_context("Base", "agent-1", goal_service)
        assert result == "Base"

    def test_returns_original_on_exception(self):
        goal_service = MagicMock()
        goal_service.format_goals_context.side_effect = RuntimeError("store error")
        result = inject_project_goal_context("Base", "agent-1", goal_service)
        assert result == "Base"

    def test_passes_custom_max_chars(self):
        goal_service = MagicMock()
        goal_service.format_goals_context.return_value = "Goals"
        inject_project_goal_context("Base", "agent-1", goal_service, max_chars=500)
        goal_service.format_goals_context.assert_called_once_with("agent-1", max_chars=500)


class TestInjectCrossPollinationContext:
    def _make_config(self, enabled=True, subscribe_to=None, retrieval_k=5, relevance_threshold=0.7):
        cfg = MagicMock()
        cfg.enabled = enabled
        cfg.subscribe_to = subscribe_to or ["agent-b"]
        cfg.retrieval_k = retrieval_k
        cfg.relevance_threshold = relevance_threshold
        return cfg

    def test_returns_original_when_config_disabled(self):
        cfg = self._make_config(enabled=False)
        result = inject_cross_pollination_context("Base", cfg, MagicMock(), "query")
        assert result == "Base"

    def test_returns_original_when_config_is_none(self):
        result = inject_cross_pollination_context("Base", None, MagicMock(), "query")
        assert result == "Base"

    def test_returns_original_when_no_subscriptions(self):
        cfg = self._make_config(subscribe_to=[])
        result = inject_cross_pollination_context("Base", cfg, MagicMock(), "query")
        assert result == "Base"

    def test_injects_cross_pollination_when_results_present(self):
        cfg = self._make_config()
        memory_svc = MagicMock()
        mock_results = [{"agent_name": "agent-b", "content": "insight", "relevance_score": 0.9}]
        with patch(
            "temper_ai.memory.cross_pollination.retrieve_subscribed_knowledge",
            return_value=mock_results,
        ) as mock_retrieve, patch(
            "temper_ai.memory.cross_pollination.format_cross_pollination_context",
            return_value="[From agent-b]: insight",
        ) as mock_format:
            result = inject_cross_pollination_context("Base", cfg, memory_svc, "my query")
            assert CROSS_POLLINATION_SECTION in result
            assert "[From agent-b]: insight" in result
            mock_retrieve.assert_called_once()
            mock_format.assert_called_once()

    def test_returns_original_when_no_relevant_results(self):
        cfg = self._make_config()
        memory_svc = MagicMock()
        with patch(
            "temper_ai.memory.cross_pollination.retrieve_subscribed_knowledge",
            return_value=[],
        ), patch(
            "temper_ai.memory.cross_pollination.format_cross_pollination_context",
            return_value="",
        ):
            result = inject_cross_pollination_context("Base", cfg, memory_svc, "query")
            assert result == "Base"

    def test_returns_original_on_exception(self):
        cfg = self._make_config()
        memory_svc = MagicMock()
        with patch(
            "temper_ai.memory.cross_pollination.retrieve_subscribed_knowledge",
            side_effect=RuntimeError("network error"),
        ):
            result = inject_cross_pollination_context("Base", cfg, memory_svc, "query")
            assert result == "Base"


class TestSyncWorkflowLearningsToAgent:
    def test_success_returns_synced_true(self):
        memory_svc = MagicMock()
        with patch(
            "temper_ai.memory.cross_pollination.publish_knowledge",
            return_value="entry-123",
        ) as mock_publish:
            result = sync_workflow_learnings_to_agent(
                "agent-id-1", "researcher", "my-workflow", memory_svc
            )
            assert result["synced"] is True
            assert result["entry_id"] == "entry-123"
            mock_publish.assert_called_once()
            call_kwargs = mock_publish.call_args[1]
            assert call_kwargs["agent_name"] == "researcher"
            assert "my-workflow" in call_kwargs["content"]

    def test_failure_returns_error_dict(self):
        memory_svc = MagicMock()
        with patch(
            "temper_ai.memory.cross_pollination.publish_knowledge",
            side_effect=OSError("disk full"),
        ):
            result = sync_workflow_learnings_to_agent(
                "agent-id-1", "researcher", "my-workflow", memory_svc
            )
            assert result["synced"] is False
            assert "disk full" in result["error"]
