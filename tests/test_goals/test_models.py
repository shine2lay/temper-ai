"""Tests for temper_ai.goals.models SQLModel tables."""

from datetime import datetime

from temper_ai.goals.models import AnalysisRun, GoalProposalRecord


class TestGoalProposalRecord:
    def _make_proposal(self, **kwargs):
        defaults = {
            "id": "gp-001",
            "goal_type": "cost_reduction",
            "title": "Reduce LLM costs",
            "description": "Switch to cheaper model",
        }
        defaults.update(kwargs)
        return GoalProposalRecord(**defaults)

    def test_required_fields(self):
        p = self._make_proposal()
        assert p.id == "gp-001"
        assert p.goal_type == "cost_reduction"
        assert p.title == "Reduce LLM costs"
        assert p.description == "Switch to cheaper model"

    def test_default_status(self):
        p = self._make_proposal()
        assert p.status == "proposed"

    def test_default_effort_estimate(self):
        p = self._make_proposal()
        assert p.effort_estimate == "medium"

    def test_default_priority_score(self):
        p = self._make_proposal()
        assert p.priority_score == 0.0

    def test_default_risk_assessment_empty_dict(self):
        p = self._make_proposal()
        assert p.risk_assessment == {}

    def test_default_expected_impacts_empty_list(self):
        p = self._make_proposal()
        assert p.expected_impacts == []

    def test_default_evidence_empty_dict(self):
        p = self._make_proposal()
        assert p.evidence == {}

    def test_default_applicable_product_types_empty(self):
        p = self._make_proposal()
        assert p.applicable_product_types == []

    def test_default_proposed_actions_empty(self):
        p = self._make_proposal()
        assert p.proposed_actions == []

    def test_default_source_fields_none(self):
        p = self._make_proposal()
        assert p.source_product_type is None
        assert p.source_agent_id is None

    def test_default_reviewer_fields_none(self):
        p = self._make_proposal()
        assert p.reviewer is None
        assert p.review_reason is None
        assert p.reviewed_at is None

    def test_created_at_auto_populated(self):
        p = self._make_proposal()
        assert isinstance(p.created_at, datetime)

    def test_updated_at_auto_populated(self):
        p = self._make_proposal()
        assert isinstance(p.updated_at, datetime)

    def test_custom_status(self):
        p = self._make_proposal(status="approved")
        assert p.status == "approved"

    def test_custom_risk_assessment(self):
        risk = {"level": "high", "reversible": False}
        p = self._make_proposal(risk_assessment=risk)
        assert p.risk_assessment["level"] == "high"

    def test_custom_expected_impacts(self):
        impacts = [{"metric_name": "latency_ms", "improvement_pct": 30}]
        p = self._make_proposal(expected_impacts=impacts)
        assert len(p.expected_impacts) == 1

    def test_custom_source_fields(self):
        p = self._make_proposal(source_product_type="api", source_agent_id="agent-42")
        assert p.source_product_type == "api"
        assert p.source_agent_id == "agent-42"

    def test_custom_applicable_product_types(self):
        p = self._make_proposal(applicable_product_types=["api", "batch"])
        assert "api" in p.applicable_product_types

    def test_custom_proposed_actions(self):
        p = self._make_proposal(proposed_actions=["Profile stage", "Cache results"])
        assert len(p.proposed_actions) == 2

    def test_reviewer_fields_set(self):
        ts = datetime(2026, 1, 15, 10, 0, 0)
        p = self._make_proposal(reviewer="alice", review_reason="LGTM", reviewed_at=ts)
        assert p.reviewer == "alice"
        assert p.review_reason == "LGTM"
        assert p.reviewed_at == ts

    def test_tablename(self):
        assert GoalProposalRecord.__tablename__ == "goal_proposals"

    def test_instances_are_independent(self):
        p1 = self._make_proposal(id="gp-001")
        p2 = self._make_proposal(id="gp-002")
        p2.proposed_actions.append("action")
        assert p1.proposed_actions == []


class TestAnalysisRun:
    def _make_run(self, **kwargs):
        defaults = {"id": "run-001"}
        defaults.update(kwargs)
        return AnalysisRun(**defaults)

    def test_required_id(self):
        r = self._make_run()
        assert r.id == "run-001"

    def test_default_status_running(self):
        r = self._make_run()
        assert r.status == "running"

    def test_default_proposals_generated(self):
        r = self._make_run()
        assert r.proposals_generated == 0

    def test_default_analyzer_stats_empty(self):
        r = self._make_run()
        assert r.analyzer_stats == {}

    def test_default_completed_at_none(self):
        r = self._make_run()
        assert r.completed_at is None

    def test_default_error_message_none(self):
        r = self._make_run()
        assert r.error_message is None

    def test_started_at_auto_populated(self):
        r = self._make_run()
        assert isinstance(r.started_at, datetime)

    def test_custom_status(self):
        r = self._make_run(status="completed")
        assert r.status == "completed"

    def test_custom_proposals_generated(self):
        r = self._make_run(proposals_generated=7)
        assert r.proposals_generated == 7

    def test_custom_analyzer_stats(self):
        stats = {"performance": {"proposals": 3}, "cost": {"proposals": 2}}
        r = self._make_run(analyzer_stats=stats)
        assert "performance" in r.analyzer_stats

    def test_completed_at_set(self):
        ts = datetime(2026, 2, 1, 12, 0, 0)
        r = self._make_run(completed_at=ts)
        assert r.completed_at == ts

    def test_error_message_set(self):
        r = self._make_run(status="failed", error_message="DB connection error")
        assert r.error_message == "DB connection error"

    def test_tablename(self):
        assert AnalysisRun.__tablename__ == "analysis_runs"
