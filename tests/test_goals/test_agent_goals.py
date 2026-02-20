"""Tests for AgentGoalService (M9)."""
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.goals.agent_goals import (
    ACTIVE_STATUSES,
    DEFAULT_GOAL_LIMIT,
    AgentGoalService,
)


def _make_record(
    goal_id: str,
    title: str,
    description: str,
    status: str,
    priority: float,
    agent_id: str,
) -> MagicMock:
    rec = MagicMock()
    rec.id = goal_id
    rec.title = title
    rec.description = description
    rec.status = status
    rec.priority_score = priority
    rec.source_product_type = agent_id
    return rec


class TestAgentGoalServiceInit:
    def test_init_without_store(self):
        svc = AgentGoalService()
        assert svc._store is None

    def test_init_with_store(self):
        mock_store = MagicMock()
        svc = AgentGoalService(goal_store=mock_store)
        assert svc._store is mock_store


class TestGetActiveGoalsForAgent:
    def _make_service_with_mock_store(self, records_by_status=None):
        records_by_status = records_by_status or {}
        store = MagicMock()
        store.list_proposals.side_effect = lambda status: records_by_status.get(status, [])
        svc = AgentGoalService(goal_store=store)
        return svc, store

    def test_returns_goals_for_matching_agent(self):
        rec = _make_record("g1", "Goal 1", "Desc 1", "approved", 0.9, "agent_a")
        svc, _ = self._make_service_with_mock_store({"approved": [rec], "in_progress": []})
        goals = svc.get_active_goals_for_agent("agent_a")
        assert len(goals) == 1
        assert goals[0]["title"] == "Goal 1"

    def test_excludes_goals_for_other_agents(self):
        rec = _make_record("g1", "Goal 1", "Desc", "approved", 0.9, "agent_b")
        svc, _ = self._make_service_with_mock_store({"approved": [rec], "in_progress": []})
        goals = svc.get_active_goals_for_agent("agent_a")
        assert goals == []

    def test_returns_goals_sorted_by_priority(self):
        rec_low = _make_record("g1", "Low", "Desc", "approved", 0.3, "agent_a")
        rec_high = _make_record("g2", "High", "Desc", "in_progress", 0.9, "agent_a")
        svc, _ = self._make_service_with_mock_store(
            {"approved": [rec_low], "in_progress": [rec_high]}
        )
        goals = svc.get_active_goals_for_agent("agent_a")
        assert goals[0]["title"] == "High"
        assert goals[1]["title"] == "Low"

    def test_respects_limit(self):
        records = [
            _make_record(f"g{i}", f"Goal {i}", "Desc", "approved", float(i), "agent_a")
            for i in range(10)
        ]
        svc, _ = self._make_service_with_mock_store({"approved": records, "in_progress": []})
        goals = svc.get_active_goals_for_agent("agent_a", limit=3)
        assert len(goals) == 3

    def test_goal_dict_has_required_keys(self):
        rec = _make_record("g1", "T", "D", "approved", 0.5, "agent_a")
        svc, _ = self._make_service_with_mock_store({"approved": [rec], "in_progress": []})
        goals = svc.get_active_goals_for_agent("agent_a")
        assert "id" in goals[0]
        assert "title" in goals[0]
        assert "description" in goals[0]
        assert "status" in goals[0]
        assert "priority" in goals[0]


class TestProposeAgentGoal:
    def test_calls_save_proposal_and_returns_id(self):
        store = MagicMock()
        store.save_proposal.return_value = None
        svc = AgentGoalService(goal_store=store)
        goal_data = {
            "goal_type": "performance_optimization",
            "title": "Speed up agent",
            "description": "Optimize execution path",
        }
        result = svc.propose_agent_goal("agent_a", goal_data)
        assert isinstance(result, str)
        assert len(result) > 0
        store.save_proposal.assert_called_once()
        saved_record = store.save_proposal.call_args[0][0]
        assert saved_record.id == result

    def test_sets_source_product_type_to_agent_id(self):
        store = MagicMock()
        svc = AgentGoalService(goal_store=store)
        goal_data = {
            "goal_type": "performance_optimization",
            "title": "Title",
            "description": "Desc",
        }
        svc.propose_agent_goal("agent_xyz", goal_data)
        record = store.save_proposal.call_args[0][0]
        assert record.source_product_type == "agent_xyz"


class TestFormatGoalsContext:
    def _make_service_with_goals(self, goals):
        svc = AgentGoalService.__new__(AgentGoalService)
        svc.get_active_goals_for_agent = MagicMock(return_value=goals)
        return svc

    def test_no_goals_returns_empty_string(self):
        svc = self._make_service_with_goals([])
        result = svc.format_goals_context("agent_a")
        assert result == ""

    def test_with_goals_contains_header(self):
        goals = [{"id": "g1", "title": "T1", "description": "D1", "status": "approved", "priority": 0.9}]
        svc = self._make_service_with_goals(goals)
        result = svc.format_goals_context("agent_a")
        assert "Active Goals:" in result
        assert "T1" in result

    def test_respects_max_chars(self):
        goals = [{"id": "g1", "title": "T", "description": "D" * 500, "status": "approved", "priority": 0.9}]
        svc = self._make_service_with_goals(goals)
        result = svc.format_goals_context("agent_a", max_chars=20)
        assert len(result) <= 20
