"""Tests for goal proposal schemas."""

from temper_ai.goals._schemas import (
    EffortLevel,
    GoalEvidence,
    GoalProposal,
    GoalReview,
    GoalReviewAction,
    GoalRiskLevel,
    GoalStatus,
    GoalType,
    ImpactEstimate,
    RiskAssessment,
)


class TestGoalType:
    def test_all_values(self):
        assert len(GoalType) == 5
        assert GoalType.PERFORMANCE_OPTIMIZATION.value == "performance_optimization"
        assert GoalType.COST_REDUCTION.value == "cost_reduction"
        assert GoalType.RELIABILITY_IMPROVEMENT.value == "reliability_improvement"
        assert GoalType.CROSS_PRODUCT_OPPORTUNITY.value == "cross_product_opportunity"

    def test_string_enum(self):
        assert isinstance(GoalType.COST_REDUCTION, str)
        assert GoalType("cost_reduction") == GoalType.COST_REDUCTION


class TestGoalStatus:
    def test_all_statuses(self):
        assert len(GoalStatus) == 9
        assert GoalStatus.PROPOSED.value == "proposed"
        assert GoalStatus.APPROVED.value == "approved"
        assert GoalStatus.REJECTED.value == "rejected"
        assert GoalStatus.DEFERRED.value == "deferred"


class TestRiskAssessment:
    def test_defaults(self):
        ra = RiskAssessment()
        assert ra.level == GoalRiskLevel.LOW
        assert ra.reversible is True
        assert ra.safety_concerns == []

    def test_full(self):
        ra = RiskAssessment(
            level=GoalRiskLevel.HIGH,
            blast_radius="workflow:main",
            reversible=False,
            safety_concerns=["data loss"],
            mitigation_steps=["backup first"],
        )
        assert ra.level == GoalRiskLevel.HIGH
        assert ra.blast_radius == "workflow:main"
        assert len(ra.mitigation_steps) == 1


class TestImpactEstimate:
    def test_basic(self):
        ie = ImpactEstimate(
            metric_name="latency_ms",
            current_value=500.0,
            expected_value=250.0,
            improvement_pct=50.0,
            confidence=0.8,
        )
        assert ie.metric_name == "latency_ms"
        assert ie.improvement_pct == 50.0


class TestGoalProposal:
    def test_minimal(self):
        gp = GoalProposal(
            goal_type=GoalType.COST_REDUCTION,
            title="Reduce costs",
            description="Switch to cheaper model",
        )
        assert gp.goal_type == GoalType.COST_REDUCTION
        assert gp.priority_score == 0.0
        assert gp.proposed_actions == []

    def test_full(self):
        gp = GoalProposal(
            goal_type=GoalType.PERFORMANCE_OPTIMIZATION,
            title="Speed up stage X",
            description="Optimize slow stage",
            effort_estimate=EffortLevel.SMALL,
            expected_impacts=[
                ImpactEstimate(
                    metric_name="duration_s",
                    current_value=300,
                    expected_value=150,
                    improvement_pct=50,
                )
            ],
            evidence=GoalEvidence(
                workflow_ids=["wf-1"],
                metrics={"avg_duration": 300},
                analysis_summary="Slow stage",
            ),
            proposed_actions=["Profile it"],
            priority_score=0.75,
        )
        assert len(gp.expected_impacts) == 1
        assert gp.evidence.workflow_ids == ["wf-1"]


class TestGoalReview:
    def test_approve(self):
        r = GoalReview(
            action=GoalReviewAction.APPROVE,
            reviewer="admin",
            reason="Looks good",
        )
        assert r.action == GoalReviewAction.APPROVE

    def test_defer_with_date(self):
        r = GoalReview(
            action=GoalReviewAction.DEFER,
            reviewer="admin",
            defer_until="2026-03-01",
        )
        assert r.defer_until == "2026-03-01"
