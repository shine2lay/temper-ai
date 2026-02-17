"""Tests for autonomy SQLModel tables."""

from src.safety.autonomy.models import (
    AutonomyState,
    AutonomyTransition,
    BudgetRecord,
    EmergencyStopEvent,
)
from src.storage.database.datetime_utils import utcnow


class TestAutonomyState:
    """Tests for AutonomyState model."""

    def test_create(self) -> None:
        """Can create an AutonomyState."""
        state = AutonomyState(
            id="as-test1",
            agent_name="researcher",
            domain="analysis",
            current_level=0,
        )
        assert state.agent_name == "researcher"
        assert state.domain == "analysis"
        assert state.current_level == 0
        assert state.shadow_runs == 0

    def test_defaults(self) -> None:
        """Default values are set correctly."""
        state = AutonomyState(id="as-test2", agent_name="a", domain="d")
        assert state.shadow_level is None
        assert state.shadow_agreements == 0
        assert state.last_escalation is None
        assert state.created_at is not None


class TestAutonomyTransition:
    """Tests for AutonomyTransition model."""

    def test_create(self) -> None:
        """Can create a transition record."""
        t = AutonomyTransition(
            id="at-test1",
            agent_name="coder",
            domain="code",
            from_level=0,
            to_level=1,
            reason="test",
            trigger="manual",
        )
        assert t.from_level == 0
        assert t.to_level == 1
        assert t.trigger == "manual"
        assert t.merit_snapshot == {}

    def test_with_snapshot(self) -> None:
        """Can include merit snapshot JSON."""
        t = AutonomyTransition(
            id="at-test2",
            agent_name="a",
            domain="d",
            from_level=1,
            to_level=2,
            reason="r",
            trigger="auto_escalation",
            merit_snapshot={"success_rate": 0.95},
        )
        assert t.merit_snapshot["success_rate"] == 0.95


class TestBudgetRecord:
    """Tests for BudgetRecord model."""

    def test_create(self) -> None:
        """Can create a budget record."""
        b = BudgetRecord(
            id="bg-test1",
            scope="agent-a",
            period="monthly",
            budget_usd=100.0,
        )
        assert b.spent_usd == 0.0
        assert b.action_count == 0
        assert b.status == "active"

    def test_update_spent(self) -> None:
        """Can update spent amount."""
        b = BudgetRecord(
            id="bg-test2", scope="s", period="p", budget_usd=50.0
        )
        b.spent_usd = 25.0
        b.action_count = 10
        assert b.spent_usd == 25.0


class TestEmergencyStopEvent:
    """Tests for EmergencyStopEvent model."""

    def test_create(self) -> None:
        """Can create an emergency stop event."""
        e = EmergencyStopEvent(
            id="es-test1",
            triggered_by="admin",
            reason="safety concern",
        )
        assert e.triggered_by == "admin"
        assert e.agents_halted == []
        assert e.resolved_at is None

    def test_with_agents(self) -> None:
        """Can list halted agents."""
        e = EmergencyStopEvent(
            id="es-test2",
            triggered_by="system",
            reason="test",
            agents_halted=["agent-a", "agent-b"],
        )
        assert len(e.agents_halted) == 2
