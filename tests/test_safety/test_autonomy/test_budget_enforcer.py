"""Tests for BudgetEnforcer."""

import pytest

from temper_ai.safety.autonomy.budget_enforcer import (
    BudgetEnforcer,
    BudgetStatus,
)
from temper_ai.safety.autonomy.constants import (
    STATUS_ACTIVE,
    STATUS_EXHAUSTED,
    STATUS_WARNING,
)
from temper_ai.safety.autonomy.store import AutonomyStore


@pytest.fixture
def store() -> AutonomyStore:
    return AutonomyStore(database_url="sqlite:///:memory:")


@pytest.fixture
def enforcer(store: AutonomyStore) -> BudgetEnforcer:
    return BudgetEnforcer(store=store, pricing_path=None, default_budget=100.0)


class TestCheckBudget:
    """Tests for check_budget."""

    def test_allowed_fresh_scope(self, enforcer: BudgetEnforcer) -> None:
        """Fresh scope has full budget remaining."""
        result = enforcer.check_budget("agent-a")
        assert result.allowed
        assert result.remaining_usd == 100.0
        assert result.status == STATUS_ACTIVE

    def test_allowed_with_estimated_cost(self, enforcer: BudgetEnforcer) -> None:
        """Allowed when estimated cost within budget."""
        result = enforcer.check_budget("agent-a", estimated_cost=50.0)
        assert result.allowed

    def test_blocked_estimated_exceeds(self, enforcer: BudgetEnforcer) -> None:
        """Blocked when estimated cost exceeds remaining."""
        enforcer.record_spend("agent-a", 80.0)
        result = enforcer.check_budget("agent-a", estimated_cost=25.0)
        assert not result.allowed
        assert result.status == STATUS_WARNING

    def test_exhausted_budget(self, enforcer: BudgetEnforcer) -> None:
        """Blocked when budget fully exhausted."""
        enforcer.record_spend("agent-a", 100.0)
        result = enforcer.check_budget("agent-a")
        assert not result.allowed
        assert result.remaining_usd == 0.0
        assert result.status == STATUS_EXHAUSTED

    def test_warning_threshold(self, enforcer: BudgetEnforcer) -> None:
        """Status becomes WARNING at 80% utilization."""
        enforcer.record_spend("agent-a", 85.0)
        result = enforcer.check_budget("agent-a")
        assert result.allowed
        assert result.status == STATUS_WARNING


class TestRecordSpend:
    """Tests for record_spend."""

    def test_accumulates_spending(self, enforcer: BudgetEnforcer) -> None:
        """Spending accumulates across calls."""
        enforcer.record_spend("agent-a", 10.0)
        enforcer.record_spend("agent-a", 20.0)
        status = enforcer.get_budget_status("agent-a")
        assert status.spent_usd == 30.0
        assert status.action_count == 2

    def test_status_transitions(self, enforcer: BudgetEnforcer) -> None:
        """Status transitions through active -> warning -> exhausted."""
        # Active
        enforcer.record_spend("agent-a", 50.0)
        assert enforcer.get_budget_status("agent-a").status == STATUS_ACTIVE

        # Warning (80%+)
        enforcer.record_spend("agent-a", 35.0)
        assert enforcer.get_budget_status("agent-a").status == STATUS_WARNING

        # Exhausted (100%+)
        enforcer.record_spend("agent-a", 20.0)
        assert enforcer.get_budget_status("agent-a").status == STATUS_EXHAUSTED


class TestEstimateActionCost:
    """Tests for estimate_action_cost."""

    def test_unknown_model_returns_zero(self, enforcer: BudgetEnforcer) -> None:
        """Unknown model returns 0 cost."""
        cost = enforcer.estimate_action_cost("unknown-model-xyz", 1000)
        assert cost == 0.0

    def test_no_pricing_returns_zero(self) -> None:
        """No pricing file returns 0 for all models."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        enforcer = BudgetEnforcer(store=store, pricing_path="/nonexistent/path.yaml")
        assert enforcer.estimate_action_cost("any-model", 1000) == 0.0


class TestGetBudgetStatus:
    """Tests for get_budget_status."""

    def test_fresh_scope(self, enforcer: BudgetEnforcer) -> None:
        """Fresh scope returns default budget."""
        status = enforcer.get_budget_status("new-scope")
        assert isinstance(status, BudgetStatus)
        assert status.budget_usd == 100.0
        assert status.spent_usd == 0.0
        assert status.remaining_usd == 100.0
        assert status.utilization == 0.0
        assert status.action_count == 0

    def test_reflects_spending(self, enforcer: BudgetEnforcer) -> None:
        """Status reflects recorded spending."""
        enforcer.record_spend("agent-a", 40.0)
        status = enforcer.get_budget_status("agent-a")
        assert status.spent_usd == 40.0
        assert status.remaining_usd == 60.0
        assert abs(status.utilization - 0.4) < 0.01
