"""Tests for GoalStore persistence."""

import pytest

from temper_ai.goals.models import AnalysisRun, GoalProposalRecord
from temper_ai.goals.store import GoalStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def store():
    return GoalStore(database_url=MEMORY_DB)


@pytest.fixture
def sample_proposal():
    return GoalProposalRecord(
        id="gp-test001",
        goal_type="cost_reduction",
        title="Reduce LLM costs",
        description="Switch expensive model",
        status="proposed",
        risk_assessment={"level": "low"},
        effort_estimate="small",
        expected_impacts=[
            {"metric_name": "cost", "current_value": 10, "expected_value": 5}
        ],
        evidence={"analysis_summary": "High cost detected"},
        priority_score=0.75,
    )


class TestProposalCRUD:
    def test_save_and_get(self, store, sample_proposal):
        store.save_proposal(sample_proposal)
        result = store.get_proposal("gp-test001")
        assert result is not None
        assert result.title == "Reduce LLM costs"
        assert result.priority_score == 0.75

    def test_get_nonexistent(self, store):
        assert store.get_proposal("nonexistent") is None

    def test_list_proposals(self, store, sample_proposal):
        store.save_proposal(sample_proposal)
        results = store.list_proposals()
        assert len(results) == 1

    def test_list_filter_by_status(self, store, sample_proposal):
        store.save_proposal(sample_proposal)
        proposed = store.list_proposals(status="proposed")
        assert len(proposed) == 1
        approved = store.list_proposals(status="approved")
        assert len(approved) == 0

    def test_list_filter_by_goal_type(self, store, sample_proposal):
        store.save_proposal(sample_proposal)
        results = store.list_proposals(goal_type="cost_reduction")
        assert len(results) == 1
        results = store.list_proposals(goal_type="performance_optimization")
        assert len(results) == 0

    def test_list_filter_by_product_type(self, store):
        p1 = GoalProposalRecord(
            id="gp-prod1",
            goal_type="cost_reduction",
            title="T1",
            description="D1",
            source_product_type="api",
        )
        p2 = GoalProposalRecord(
            id="gp-prod2",
            goal_type="cost_reduction",
            title="T2",
            description="D2",
            source_product_type="web_app",
        )
        store.save_proposal(p1)
        store.save_proposal(p2)
        results = store.list_proposals(product_type="api")
        assert len(results) == 1
        assert results[0].id == "gp-prod1"

    def test_update_status(self, store, sample_proposal):
        store.save_proposal(sample_proposal)
        ok = store.update_proposal_status(
            "gp-test001", "approved", reviewer="admin", reason="LGTM"
        )
        assert ok is True
        updated = store.get_proposal("gp-test001")
        assert updated.status == "approved"
        assert updated.reviewer == "admin"

    def test_update_nonexistent(self, store):
        ok = store.update_proposal_status("nope", "approved")
        assert ok is False

    def test_count_by_status(self, store, sample_proposal):
        store.save_proposal(sample_proposal)
        p2 = GoalProposalRecord(
            id="gp-test002",
            goal_type="reliability_improvement",
            title="Fix errors",
            description="Reduce failures",
            status="approved",
        )
        store.save_proposal(p2)
        counts = store.count_by_status()
        assert counts.get("proposed") == 1
        assert counts.get("approved") == 1

    def test_count_proposals_today(self, store, sample_proposal):
        store.save_proposal(sample_proposal)
        count = store.count_proposals_today()
        assert count == 1

    def test_list_ordered_by_priority(self, store):
        p1 = GoalProposalRecord(
            id="gp-low",
            goal_type="cost_reduction",
            title="Low",
            description="D",
            priority_score=0.3,
        )
        p2 = GoalProposalRecord(
            id="gp-high",
            goal_type="cost_reduction",
            title="High",
            description="D",
            priority_score=0.9,
        )
        store.save_proposal(p1)
        store.save_proposal(p2)
        results = store.list_proposals()
        assert results[0].id == "gp-high"


class TestAnalysisRuns:
    def test_save_and_list(self, store):
        run = AnalysisRun(
            id="ar-test001",
            status="completed",
            proposals_generated=5,
            analyzer_stats={"total": 5},
        )
        store.save_analysis_run(run)
        runs = store.list_analysis_runs()
        assert len(runs) == 1
        assert runs[0].proposals_generated == 5
