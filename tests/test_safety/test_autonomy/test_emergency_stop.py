"""Tests for EmergencyStopController."""

import pytest

from src.safety.autonomy.emergency_stop import (
    EmergencyStopController,
    EmergencyStopError,
    reset_emergency_state,
)
from src.safety.autonomy.store import AutonomyStore


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset module-level state before each test."""
    reset_emergency_state()


@pytest.fixture
def store() -> AutonomyStore:
    return AutonomyStore(database_url="sqlite:///:memory:")


@pytest.fixture
def controller(store: AutonomyStore) -> EmergencyStopController:
    return EmergencyStopController(store=store)


class TestActivateDeactivate:
    """Tests for activate and deactivate."""

    def test_activate_sets_active(self, controller: EmergencyStopController) -> None:
        """Activate sets emergency stop to active."""
        assert not controller.is_active()
        controller.activate(triggered_by="admin", reason="test")
        assert controller.is_active()

    def test_activate_returns_event(self, controller: EmergencyStopController) -> None:
        """Activate returns EmergencyStopEvent."""
        event = controller.activate(triggered_by="admin", reason="safety issue")
        assert event.id.startswith("es-")
        assert event.triggered_by == "admin"
        assert event.reason == "safety issue"

    def test_activate_persists_event(self, controller: EmergencyStopController, store: AutonomyStore) -> None:
        """Activate persists event to store."""
        controller.activate(triggered_by="admin", reason="test")
        events = store.list_emergency_events()
        assert len(events) == 1

    def test_activate_with_agents_halted(self, controller: EmergencyStopController) -> None:
        """Activate can list halted agents."""
        event = controller.activate(
            triggered_by="system", reason="test",
            agents_halted=["agent-a", "agent-b"],
        )
        assert event.agents_halted == ["agent-a", "agent-b"]

    def test_deactivate_clears_active(self, controller: EmergencyStopController) -> None:
        """Deactivate clears emergency stop."""
        controller.activate(triggered_by="admin", reason="test")
        assert controller.is_active()
        controller.deactivate(resolution_reason="resolved")
        assert not controller.is_active()

    def test_deactivate_without_store(self) -> None:
        """Deactivate works without store (no persistence)."""
        ctrl = EmergencyStopController(store=None)
        ctrl.activate(triggered_by="admin", reason="test")
        ctrl.deactivate(resolution_reason="ok")
        assert not ctrl.is_active()


class TestCheckOrRaise:
    """Tests for check_or_raise."""

    def test_no_raise_when_inactive(self, controller: EmergencyStopController) -> None:
        """No exception when stop is not active."""
        controller.check_or_raise()  # Should not raise
        assert not controller.is_active()

    def test_raises_when_active(self, controller: EmergencyStopController) -> None:
        """Raises EmergencyStopError when active."""
        controller.activate(triggered_by="admin", reason="test")
        with pytest.raises(EmergencyStopError):
            controller.check_or_raise()


class TestResetState:
    """Tests for reset_emergency_state."""

    def test_clears_state(self, controller: EmergencyStopController) -> None:
        """reset_emergency_state clears the module-level event."""
        controller.activate(triggered_by="admin", reason="test")
        assert controller.is_active()
        reset_emergency_state()
        assert not controller.is_active()


class TestTimeout:
    """Tests for get_timeout."""

    def test_returns_configured_timeout(self, controller: EmergencyStopController) -> None:
        """Returns the configured emergency stop timeout."""
        timeout = controller.get_timeout()
        assert timeout == 5
