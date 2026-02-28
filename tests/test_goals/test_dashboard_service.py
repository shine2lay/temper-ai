"""Tests for GoalDataService."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.goals.dashboard_service import (
    DEFAULT_PROPOSAL_LIMIT,
    DEFAULT_RUN_LIMIT,
    GoalDataService,
)


def _make_proposal(**kwargs):
    defaults = {
        "id": "gp-001",
        "goal_type": "cost_reduction",
        "title": "Reduce costs",
        "status": "proposed",
        "priority_score": 0.75,
        "effort_estimate": "small",
        "risk_assessment": {"level": "low"},
        "created_at": datetime(2026, 1, 10, 8, 0, 0),
        "description": "desc",
        "expected_impacts": [],
        "evidence": {},
        "source_product_type": None,
        "applicable_product_types": [],
        "proposed_actions": [],
        "reviewer": None,
        "review_reason": None,
        "reviewed_at": None,
    }
    defaults.update(kwargs)
    p = MagicMock()
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


def _make_run(**kwargs):
    defaults = {
        "id": "run-001",
        "started_at": datetime(2026, 1, 10, 6, 0, 0),
        "completed_at": datetime(2026, 1, 10, 7, 0, 0),
        "status": "completed",
        "proposals_generated": 3,
        "analyzer_stats": {"perf": {"count": 3}},
    }
    defaults.update(kwargs)
    r = MagicMock()
    for k, v in defaults.items():
        setattr(r, k, v)
    return r


@pytest.fixture
def mock_store():
    return MagicMock()


@pytest.fixture
def service(mock_store):
    with patch("temper_ai.goals.dashboard_service.GoalReviewWorkflow"):
        svc = GoalDataService(store=mock_store)
    return svc


class TestGetProposals:
    def test_returns_list(self, service, mock_store):
        mock_store.list_proposals.return_value = [_make_proposal()]
        result = service.get_proposals()
        assert isinstance(result, list)
        assert len(result) == 1

    def test_proposal_dict_shape(self, service, mock_store):
        mock_store.list_proposals.return_value = [_make_proposal()]
        result = service.get_proposals()
        item = result[0]
        assert "id" in item
        assert "goal_type" in item
        assert "title" in item
        assert "status" in item
        assert "priority_score" in item
        assert "effort_estimate" in item
        assert "risk_assessment" in item
        assert "created_at" in item

    def test_created_at_is_isoformat(self, service, mock_store):
        mock_store.list_proposals.return_value = [_make_proposal()]
        result = service.get_proposals()
        assert result[0]["created_at"] == "2026-01-10T08:00:00"

    def test_created_at_none(self, service, mock_store):
        mock_store.list_proposals.return_value = [_make_proposal(created_at=None)]
        result = service.get_proposals()
        assert result[0]["created_at"] is None

    def test_passes_status_filter(self, service, mock_store):
        mock_store.list_proposals.return_value = []
        service.get_proposals(status="approved")
        mock_store.list_proposals.assert_called_once_with(
            status="approved", goal_type=None, limit=DEFAULT_PROPOSAL_LIMIT
        )

    def test_passes_goal_type_filter(self, service, mock_store):
        mock_store.list_proposals.return_value = []
        service.get_proposals(goal_type="cost_reduction")
        mock_store.list_proposals.assert_called_once_with(
            status=None, goal_type="cost_reduction", limit=DEFAULT_PROPOSAL_LIMIT
        )

    def test_passes_custom_limit(self, service, mock_store):
        mock_store.list_proposals.return_value = []
        service.get_proposals(limit=10)
        mock_store.list_proposals.assert_called_once_with(
            status=None, goal_type=None, limit=10
        )

    def test_empty_list(self, service, mock_store):
        mock_store.list_proposals.return_value = []
        result = service.get_proposals()
        assert result == []

    def test_multiple_proposals(self, service, mock_store):
        p1 = _make_proposal(id="gp-001")
        p2 = _make_proposal(id="gp-002", status="approved")
        mock_store.list_proposals.return_value = [p1, p2]
        result = service.get_proposals()
        assert len(result) == 2
        assert result[0]["id"] == "gp-001"
        assert result[1]["id"] == "gp-002"


class TestGetProposalDetail:
    def test_returns_none_for_missing(self, service, mock_store):
        mock_store.get_proposal.return_value = None
        result = service.get_proposal_detail("nonexistent")
        assert result is None

    def test_returns_full_dict(self, service, mock_store):
        mock_store.get_proposal.return_value = _make_proposal()
        result = service.get_proposal_detail("gp-001")
        assert result is not None
        expected_keys = {
            "id",
            "goal_type",
            "title",
            "description",
            "status",
            "priority_score",
            "effort_estimate",
            "risk_assessment",
            "expected_impacts",
            "evidence",
            "source_product_type",
            "applicable_product_types",
            "proposed_actions",
            "reviewer",
            "review_reason",
            "reviewed_at",
            "created_at",
        }
        assert expected_keys.issubset(result.keys())

    def test_created_at_isoformat(self, service, mock_store):
        mock_store.get_proposal.return_value = _make_proposal(
            created_at=datetime(2026, 2, 1, 9, 30, 0)
        )
        result = service.get_proposal_detail("gp-001")
        assert result["created_at"] == "2026-02-01T09:30:00"

    def test_reviewed_at_isoformat(self, service, mock_store):
        ts = datetime(2026, 2, 5, 12, 0, 0)
        mock_store.get_proposal.return_value = _make_proposal(reviewed_at=ts)
        result = service.get_proposal_detail("gp-001")
        assert result["reviewed_at"] == "2026-02-05T12:00:00"

    def test_reviewed_at_none(self, service, mock_store):
        mock_store.get_proposal.return_value = _make_proposal(reviewed_at=None)
        result = service.get_proposal_detail("gp-001")
        assert result["reviewed_at"] is None

    def test_calls_store_get_proposal(self, service, mock_store):
        mock_store.get_proposal.return_value = None
        service.get_proposal_detail("gp-xyz")
        mock_store.get_proposal.assert_called_once_with("gp-xyz")


class TestGetStats:
    def test_returns_stats_dict(self, service, mock_store):
        mock_store.count_by_status.return_value = {"proposed": 3, "approved": 1}
        with patch("temper_ai.goals.dashboard_service.GoalReviewWorkflow"):
            svc = GoalDataService(store=mock_store)
            svc._review.get_acceptance_rate.return_value = 0.25
        mock_store.count_by_status.return_value = {"proposed": 3, "approved": 1}
        svc._review.get_acceptance_rate.return_value = 0.25
        result = svc.get_stats()
        assert "counts_by_status" in result
        assert "total" in result
        assert "acceptance_rate" in result

    def test_total_is_sum(self, service, mock_store):
        service._review.get_acceptance_rate.return_value = 0.5
        mock_store.count_by_status.return_value = {
            "proposed": 5,
            "approved": 2,
            "rejected": 1,
        }
        result = service.get_stats()
        assert result["total"] == 8

    def test_empty_counts(self, service, mock_store):
        service._review.get_acceptance_rate.return_value = 0.0
        mock_store.count_by_status.return_value = {}
        result = service.get_stats()
        assert result["total"] == 0


class TestGetAnalysisRuns:
    def test_returns_list(self, service, mock_store):
        mock_store.list_analysis_runs.return_value = [_make_run()]
        result = service.get_analysis_runs()
        assert isinstance(result, list)
        assert len(result) == 1

    def test_run_dict_shape(self, service, mock_store):
        mock_store.list_analysis_runs.return_value = [_make_run()]
        result = service.get_analysis_runs()
        item = result[0]
        expected_keys = {
            "id",
            "started_at",
            "completed_at",
            "status",
            "proposals_generated",
            "analyzer_stats",
        }
        assert expected_keys.issubset(item.keys())

    def test_started_at_isoformat(self, service, mock_store):
        run = _make_run(started_at=datetime(2026, 1, 10, 6, 0, 0))
        mock_store.list_analysis_runs.return_value = [run]
        result = service.get_analysis_runs()
        assert result[0]["started_at"] == "2026-01-10T06:00:00"

    def test_completed_at_none(self, service, mock_store):
        run = _make_run(completed_at=None)
        mock_store.list_analysis_runs.return_value = [run]
        result = service.get_analysis_runs()
        assert result[0]["completed_at"] is None

    def test_passes_default_limit(self, service, mock_store):
        mock_store.list_analysis_runs.return_value = []
        service.get_analysis_runs()
        mock_store.list_analysis_runs.assert_called_once_with(limit=DEFAULT_RUN_LIMIT)

    def test_passes_custom_limit(self, service, mock_store):
        mock_store.list_analysis_runs.return_value = []
        service.get_analysis_runs(limit=5)
        mock_store.list_analysis_runs.assert_called_once_with(limit=5)

    def test_empty_runs(self, service, mock_store):
        mock_store.list_analysis_runs.return_value = []
        result = service.get_analysis_runs()
        assert result == []


class TestModuleConstants:
    def test_default_proposal_limit(self):
        assert DEFAULT_PROPOSAL_LIMIT == 50

    def test_default_run_limit(self):
        assert DEFAULT_RUN_LIMIT == 20
