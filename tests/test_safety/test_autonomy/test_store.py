"""Tests for AutonomyStore."""

import pytest

from temper_ai.safety.autonomy.models import (
    AutonomyState,
    AutonomyTransition,
    BudgetRecord,
    EmergencyStopEvent,
)
from temper_ai.safety.autonomy.store import AutonomyStore


@pytest.fixture
def store() -> AutonomyStore:
    """In-memory store for testing."""
    return AutonomyStore(database_url="sqlite:///:memory:")


class TestAutonomyStateOps:
    """Tests for AutonomyState CRUD."""

    def test_save_and_get(self, store: AutonomyStore) -> None:
        """Can save and retrieve state."""
        state = AutonomyState(
            id="as-1", agent_name="agent-a", domain="code", current_level=1,
        )
        store.save_state(state)
        result = store.get_state("agent-a", "code")
        assert result is not None
        assert result.current_level == 1

    def test_get_nonexistent(self, store: AutonomyStore) -> None:
        """Returns None for nonexistent state."""
        assert store.get_state("nope", "nope") is None

    def test_update_state(self, store: AutonomyStore) -> None:
        """Can update existing state."""
        state = AutonomyState(
            id="as-2", agent_name="agent-b", domain="d", current_level=0,
        )
        store.save_state(state)
        state.current_level = 2
        store.save_state(state)
        result = store.get_state("agent-b", "d")
        assert result is not None
        assert result.current_level == 2

    def test_list_states(self, store: AutonomyStore) -> None:
        """Can list all states."""
        store.save_state(AutonomyState(id="as-3", agent_name="a", domain="d1"))
        store.save_state(AutonomyState(id="as-4", agent_name="b", domain="d2"))
        states = store.list_states()
        assert len(states) == 2


class TestTransitionOps:
    """Tests for AutonomyTransition CRUD."""

    def test_save_and_list(self, store: AutonomyStore) -> None:
        """Can save and list transitions."""
        t = AutonomyTransition(
            id="at-1", agent_name="a", domain="d",
            from_level=0, to_level=1, reason="test", trigger="manual",
        )
        store.save_transition(t)
        result = store.list_transitions()
        assert len(result) == 1
        assert result[0].from_level == 0

    def test_filter_by_agent(self, store: AutonomyStore) -> None:
        """Can filter transitions by agent."""
        store.save_transition(AutonomyTransition(
            id="at-2", agent_name="a", domain="d",
            from_level=0, to_level=1, reason="r", trigger="t",
        ))
        store.save_transition(AutonomyTransition(
            id="at-3", agent_name="b", domain="d",
            from_level=0, to_level=1, reason="r", trigger="t",
        ))
        result = store.list_transitions(agent_name="a")
        assert len(result) == 1
        assert result[0].agent_name == "a"


class TestBudgetOps:
    """Tests for BudgetRecord CRUD."""

    def test_save_and_get(self, store: AutonomyStore) -> None:
        """Can save and retrieve budget."""
        b = BudgetRecord(
            id="bg-1", scope="agent-x", period="monthly", budget_usd=100.0,
        )
        store.save_budget(b)
        result = store.get_budget("agent-x")
        assert result is not None
        assert result.budget_usd == 100.0

    def test_get_nonexistent(self, store: AutonomyStore) -> None:
        """Returns None for nonexistent budget."""
        assert store.get_budget("nope") is None

    def test_update_budget(self, store: AutonomyStore) -> None:
        """Can update budget spent amount."""
        b = BudgetRecord(
            id="bg-2", scope="s", period="p", budget_usd=50.0,
        )
        store.save_budget(b)
        b.spent_usd = 25.0
        store.save_budget(b)
        result = store.get_budget("s")
        assert result is not None
        assert result.spent_usd == 25.0


class TestEmergencyOps:
    """Tests for EmergencyStopEvent CRUD."""

    def test_save_and_list(self, store: AutonomyStore) -> None:
        """Can save and list emergency events."""
        e = EmergencyStopEvent(
            id="es-1", triggered_by="admin", reason="test",
        )
        store.save_emergency_event(e)
        result = store.list_emergency_events()
        assert len(result) == 1
        assert result[0].triggered_by == "admin"

    def test_list_ordering(self, store: AutonomyStore) -> None:
        """Events listed newest first."""
        store.save_emergency_event(EmergencyStopEvent(
            id="es-2", triggered_by="a", reason="first",
        ))
        store.save_emergency_event(EmergencyStopEvent(
            id="es-3", triggered_by="b", reason="second",
        ))
        result = store.list_emergency_events()
        assert len(result) == 2
