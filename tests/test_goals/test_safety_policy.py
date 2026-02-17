"""Tests for GoalSafetyPolicy."""

from unittest.mock import MagicMock

import pytest

from src.goals._schemas import (
    EffortLevel,
    GoalProposal,
    GoalType,
    ImpactEstimate,
    RiskAssessment,
    GoalRiskLevel,
)
from src.goals.safety_policy import GoalSafetyPolicy
from src.goals.store import GoalStore

MEMORY_DB = "sqlite:///:memory:"


def _make_proposal(risk=GoalRiskLevel.LOW, blast_radius="stage:x"):
    return GoalProposal(
        goal_type=GoalType.COST_REDUCTION,
        title="Test proposal",
        description="Test",
        risk_assessment=RiskAssessment(
            level=risk, blast_radius=blast_radius
        ),
        effort_estimate=EffortLevel.SMALL,
        expected_impacts=[
            ImpactEstimate(
                metric_name="cost_usd",
                current_value=10.0,
                expected_value=5.0,
                improvement_pct=50.0,
            )
        ],
    )


@pytest.fixture
def store():
    return GoalStore(database_url=MEMORY_DB)


class TestValidateProposal:
    def test_low_risk_allowed(self, store):
        policy = GoalSafetyPolicy(store=store)
        result = policy.validate_proposal(_make_proposal())
        assert result.allowed is True

    def test_critical_risk_requires_review(self, store):
        policy = GoalSafetyPolicy(store=store)
        result = policy.validate_proposal(
            _make_proposal(risk=GoalRiskLevel.CRITICAL)
        )
        assert result.allowed is True
        assert result.requires_approval is True
        assert any("critical" in r.lower() for r in result.reasons)

    def test_rate_limit_exceeded(self, store):
        policy = GoalSafetyPolicy(store=store, max_proposals_per_day=0)
        result = policy.validate_proposal(_make_proposal())
        assert result.allowed is False
        assert any("limit" in r.lower() for r in result.reasons)

    def test_large_blast_radius(self, store):
        policy = GoalSafetyPolicy(store=store)
        result = policy.validate_proposal(
            _make_proposal(blast_radius="a,b,c,d,e,f,g")
        )
        assert result.requires_approval is True
        assert any("blast radius" in r.lower() for r in result.reasons)

    def test_low_risk_no_approval_required(self, store):
        policy = GoalSafetyPolicy(store=store)
        result = policy.validate_proposal(
            _make_proposal(risk=GoalRiskLevel.LOW, blast_radius="")
        )
        assert result.requires_approval is False
        assert result.approval_level == "auto"


class TestCanAutoApprove:
    def test_supervised_never(self, store):
        policy = GoalSafetyPolicy(store=store)
        assert policy.can_auto_approve(_make_proposal(), 0) is False

    def test_spot_checked_never(self, store):
        policy = GoalSafetyPolicy(store=store)
        assert policy.can_auto_approve(_make_proposal(), 1) is False

    def test_risk_gated_low_ok(self, store):
        policy = GoalSafetyPolicy(store=store)
        assert policy.can_auto_approve(_make_proposal(risk=GoalRiskLevel.LOW), 2) is True

    def test_risk_gated_medium_blocked(self, store):
        policy = GoalSafetyPolicy(store=store)
        assert policy.can_auto_approve(
            _make_proposal(risk=GoalRiskLevel.MEDIUM), 2
        ) is False

    def test_autonomous_medium_ok(self, store):
        policy = GoalSafetyPolicy(store=store)
        assert policy.can_auto_approve(
            _make_proposal(risk=GoalRiskLevel.MEDIUM), 3
        ) is True

    def test_autonomous_high_blocked(self, store):
        policy = GoalSafetyPolicy(store=store)
        assert policy.can_auto_approve(
            _make_proposal(risk=GoalRiskLevel.HIGH), 3
        ) is False

    def test_strategic_high_ok(self, store):
        policy = GoalSafetyPolicy(store=store)
        assert policy.can_auto_approve(
            _make_proposal(risk=GoalRiskLevel.HIGH), 4
        ) is True

    def test_critical_never(self, store):
        policy = GoalSafetyPolicy(store=store)
        assert policy.can_auto_approve(
            _make_proposal(risk=GoalRiskLevel.CRITICAL), 4
        ) is False

    def test_budget_check_blocks(self, store):
        enforcer = MagicMock()
        policy = GoalSafetyPolicy(
            store=store, budget_enforcer=enforcer
        )
        proposal = _make_proposal(risk=GoalRiskLevel.LOW)
        proposal.expected_impacts[0].metric_name = "cost_usd"
        proposal.expected_impacts[0].current_value = 100.0
        proposal.expected_impacts[0].expected_value = 0.0
        # Cost impact > MAX_BUDGET_IMPACT_AUTO_USD (10.0)
        assert policy.can_auto_approve(proposal, 2) is False


class TestBudgetCheck:
    def test_no_enforcer(self, store):
        policy = GoalSafetyPolicy(store=store, budget_enforcer=None)
        assert policy._check_budget(_make_proposal()) is True

    def test_within_limit(self, store):
        enforcer = MagicMock()
        policy = GoalSafetyPolicy(store=store, budget_enforcer=enforcer)
        proposal = _make_proposal()
        proposal.expected_impacts[0].metric_name = "cost_usd"
        proposal.expected_impacts[0].current_value = 10.0
        proposal.expected_impacts[0].expected_value = 5.0
        assert policy._check_budget(proposal) is True

    def test_exceeds_limit(self, store):
        enforcer = MagicMock()
        policy = GoalSafetyPolicy(store=store, budget_enforcer=enforcer)
        proposal = _make_proposal()
        proposal.expected_impacts[0].metric_name = "cost_usd"
        proposal.expected_impacts[0].current_value = 50.0
        proposal.expected_impacts[0].expected_value = 0.0
        assert policy._check_budget(proposal) is False
