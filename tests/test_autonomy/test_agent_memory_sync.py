"""Tests for orchestrator._run_agent_memory_sync (M9 agent memory sync step)."""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, call, patch

import time

import pytest

from temper_ai.autonomy._schemas import (
    AutonomousLoopConfig,
    PostExecutionReport,
    WorkflowRunContext,
)
from temper_ai.autonomy.orchestrator import PostExecutionOrchestrator
from temper_ai.registry._schemas import AgentRegistryEntry
from temper_ai.storage.database.datetime_utils import utcnow

# Patch targets for lazy imports inside _run_agent_memory_sync
_STORE_CLS = "temper_ai.registry.store.AgentRegistryStore"
_SYNC_FN = "temper_ai.agent._m9_context_helpers.sync_workflow_learnings_to_agent"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> AutonomousLoopConfig:
    defaults: Dict[str, Any] = {
        "enabled": True,
        "learning_enabled": False,
        "goals_enabled": False,
        "portfolio_enabled": False,
        "agent_memory_sync_enabled": True,
    }
    defaults.update(overrides)
    return AutonomousLoopConfig(**defaults)


def _make_context(**overrides: Any) -> WorkflowRunContext:
    defaults: Dict[str, Any] = {
        "workflow_id": "wf-m9-001",
        "workflow_name": "test_workflow",
        "result": {},
        "duration_seconds": 5.0,
        "status": "completed",
    }
    defaults.update(overrides)
    return WorkflowRunContext(**defaults)


def _make_agent_entry(name: str, agent_id: Optional[str] = None) -> AgentRegistryEntry:
    return AgentRegistryEntry(
        id=agent_id or f"id-{name}",
        name=name,
        config_snapshot={},
        registered_at=utcnow(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunAgentMemorySyncDisabled:
    """When agent_memory_sync_enabled=False the step is not executed."""

    def test_disabled_flag_not_in_steps_when_false(self) -> None:
        config = _make_config(agent_memory_sync_enabled=False)
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context()

        report = PostExecutionReport()
        with patch.object(orch, "_run_agent_memory_sync") as mock_sync:
            orch._run_subsystems(ctx, report, time.monotonic())
            mock_sync.assert_not_called()

    def test_disabled_produces_no_errors(self) -> None:
        config = _make_config(agent_memory_sync_enabled=False)
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context()
        report = orch.run(ctx)
        assert report.errors == []


class TestRunAgentMemorySyncEnabled:
    """When enabled, _run_agent_memory_sync is called during _run_subsystems."""

    @patch.object(PostExecutionOrchestrator, "_run_agent_memory_sync")
    def test_enabled_calls_agent_memory_sync(self, mock_sync: MagicMock) -> None:
        mock_sync.return_value = {"agents_synced": 0, "results": []}
        config = _make_config(agent_memory_sync_enabled=True)
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context()

        report = PostExecutionReport()
        orch._run_subsystems(ctx, report, time.monotonic())

        mock_sync.assert_called_once()

    def test_enabled_report_has_memory_sync_result(self) -> None:
        config = _make_config(agent_memory_sync_enabled=True)
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context()

        mock_store_instance = MagicMock()
        mock_store_instance.list_all.return_value = []

        with patch(_STORE_CLS, return_value=mock_store_instance):
            report = PostExecutionReport()
            result = orch._run_agent_memory_sync(ctx, report)

        assert result is not None
        assert result["agents_synced"] == 0
        assert result["results"] == []


class TestRunAgentMemorySyncNoAgents:
    """When no active agents exist, sync returns empty results."""

    def test_no_active_agents_returns_empty(self) -> None:
        config = _make_config()
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context()

        mock_store_instance = MagicMock()
        mock_store_instance.list_all.return_value = []

        with patch(_STORE_CLS, return_value=mock_store_instance):
            report = PostExecutionReport()
            result = orch._run_agent_memory_sync(ctx, report)

        assert result == {"agents_synced": 0, "results": []}
        mock_store_instance.list_all.assert_called_once_with(status_filter="active")


class TestRunAgentMemorySyncMultipleAgents:
    """With multiple active agents, all are synced."""

    def test_multiple_agents_all_synced(self) -> None:
        config = _make_config()
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context(workflow_name="my_workflow")

        agents = [_make_agent_entry("agent-a"), _make_agent_entry("agent-b")]
        mock_store_instance = MagicMock()
        mock_store_instance.list_all.return_value = agents

        sync_side_effects: List[Dict[str, Any]] = [
            {"synced": True, "entry_id": "eid-1"},
            {"synced": True, "entry_id": "eid-2"},
        ]

        with patch(_STORE_CLS, return_value=mock_store_instance):
            with patch(_SYNC_FN, side_effect=sync_side_effects) as mock_sync_fn:
                report = PostExecutionReport()
                result = orch._run_agent_memory_sync(ctx, report)

        assert result["agents_synced"] == 2
        assert len(result["results"]) == 2
        assert mock_sync_fn.call_count == 2

        first_call = mock_sync_fn.call_args_list[0]
        assert first_call.kwargs["agent_name"] == "agent-a"
        assert first_call.kwargs["workflow_name"] == "my_workflow"
        second_call = mock_sync_fn.call_args_list[1]
        assert second_call.kwargs["agent_name"] == "agent-b"


class TestRunAgentMemorySyncFailureHandling:
    """Sync failures are caught and included in errors, not re-raised."""

    def test_store_error_appended_to_report_errors(self) -> None:
        config = _make_config()
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context()

        with patch(_STORE_CLS, side_effect=RuntimeError("DB unavailable")):
            report = PostExecutionReport()
            result = orch._run_agent_memory_sync(ctx, report)

        assert result is None
        assert len(report.errors) == 1
        assert "Agent memory sync error" in report.errors[0]
        assert "DB unavailable" in report.errors[0]

    def test_individual_sync_failure_is_graceful(self) -> None:
        """sync_workflow_learnings_to_agent returning failure dict doesn't raise."""
        config = _make_config()
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context()

        agents = [_make_agent_entry("agent-fail")]
        mock_store_instance = MagicMock()
        mock_store_instance.list_all.return_value = agents

        with patch(_STORE_CLS, return_value=mock_store_instance):
            with patch(
                _SYNC_FN,
                return_value={"synced": False, "error": "memory unavailable"},
            ):
                report = PostExecutionReport()
                result = orch._run_agent_memory_sync(ctx, report)

        assert result["agents_synced"] == 1
        assert result["results"][0]["synced"] is False
        # No errors appended — failure was returned as a result dict
        assert report.errors == []


class TestPostExecutionReportMemorySyncField:
    """PostExecutionReport includes memory_sync_result field."""

    def test_report_has_memory_sync_result_field(self) -> None:
        report = PostExecutionReport()
        assert report.memory_sync_result is None

    def test_report_memory_sync_result_assignable(self) -> None:
        report = PostExecutionReport()
        report.memory_sync_result = {"agents_synced": 3, "results": []}
        assert report.memory_sync_result["agents_synced"] == 3


class TestOrchestratorRunCallsMemorySync:
    """Full orchestrator.run() invokes _run_agent_memory_sync when enabled."""

    def test_run_sets_memory_sync_result_when_enabled(self) -> None:
        config = _make_config(agent_memory_sync_enabled=True)
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context()

        agents = [_make_agent_entry("agent-x")]
        mock_store_instance = MagicMock()
        mock_store_instance.list_all.return_value = agents

        with patch(_STORE_CLS, return_value=mock_store_instance):
            with patch(
                _SYNC_FN,
                return_value={"synced": True, "entry_id": "e-1"},
            ):
                report = orch.run(ctx)

        assert report.memory_sync_result is not None
        assert report.memory_sync_result["agents_synced"] == 1
