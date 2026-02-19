"""Tests for autonomy dashboard routes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.safety.autonomy.dashboard_routes import create_autonomy_router
from temper_ai.safety.autonomy.dashboard_service import AutonomyDataService
from temper_ai.safety.autonomy.emergency_stop import reset_emergency_state
from temper_ai.safety.autonomy.models import AutonomyState, AutonomyTransition, BudgetRecord
from temper_ai.safety.autonomy.store import AutonomyStore


@pytest.fixture(autouse=True)
def _reset_stop() -> None:
    reset_emergency_state()


@pytest.fixture
def store() -> AutonomyStore:
    return AutonomyStore(database_url="sqlite:///:memory:")


@pytest.fixture
def client(store: AutonomyStore) -> TestClient:
    service = AutonomyDataService(store=store)
    router = create_autonomy_router(service)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestGetStatus:
    """Tests for GET /autonomy/status."""

    def test_empty_status(self, client: TestClient) -> None:
        """Returns empty when no agents."""
        resp = client.get("/autonomy/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_agents"] == 0

    def test_with_agents(self, store: AutonomyStore, client: TestClient) -> None:
        """Returns agent states."""
        store.save_state(AutonomyState(
            id="as-1", agent_name="agent-a", domain="code", current_level=1,
        ))
        resp = client.get("/autonomy/status")
        data = resp.json()
        assert data["total_agents"] == 1
        assert data["agents"][0]["agent_name"] == "agent-a"


class TestGetTransitions:
    """Tests for GET /autonomy/transitions."""

    def test_empty(self, client: TestClient) -> None:
        """Returns empty list when no transitions."""
        resp = client.get("/autonomy/transitions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_with_transitions(self, store: AutonomyStore, client: TestClient) -> None:
        """Returns transitions."""
        store.save_transition(AutonomyTransition(
            id="at-1", agent_name="a", domain="d",
            from_level=0, to_level=1, reason="test", trigger="manual",
        ))
        resp = client.get("/autonomy/transitions")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["trigger"] == "manual"


class TestGetBudget:
    """Tests for GET /autonomy/budget."""

    def test_empty(self, client: TestClient) -> None:
        """Returns empty list when no budgets."""
        resp = client.get("/autonomy/budget")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_with_budgets(self, store: AutonomyStore, client: TestClient) -> None:
        """Returns budget records."""
        store.save_budget(BudgetRecord(
            id="bg-1", scope="agent-a", period="monthly", budget_usd=100.0,
        ))
        resp = client.get("/autonomy/budget")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["scope"] == "agent-a"


class TestGetEmergency:
    """Tests for GET /autonomy/emergency."""

    def test_inactive(self, client: TestClient) -> None:
        """Returns inactive status when no emergency."""
        resp = client.get("/autonomy/emergency")
        data = resp.json()
        assert data["is_active"] is False
        assert data["recent_events"] == []


class TestPostEmergencyStop:
    """Tests for POST /autonomy/emergency-stop."""

    def test_activate(self, client: TestClient) -> None:
        """Activates emergency stop via API."""
        resp = client.post(
            "/autonomy/emergency-stop",
            json={"reason": "test stop", "triggered_by": "api"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "activated"

        # Verify it's active
        resp = client.get("/autonomy/emergency")
        assert resp.json()["is_active"] is True


class TestPostResume:
    """Tests for POST /autonomy/resume."""

    def test_deactivate(self, client: TestClient) -> None:
        """Deactivates emergency stop via API."""
        # First activate
        client.post(
            "/autonomy/emergency-stop",
            json={"reason": "test", "triggered_by": "api"},
        )
        # Then resume
        resp = client.post(
            "/autonomy/resume",
            json={"reason": "all clear"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"


class TestPostEscalate:
    """Tests for POST /autonomy/escalate."""

    def test_escalation(self, client: TestClient) -> None:
        """Escalates agent via API."""
        resp = client.post(
            "/autonomy/escalate",
            json={"agent_name": "agent-a", "domain": "code"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "escalated"
        assert data["from_level"] == 0
        assert data["to_level"] == 1


class TestPostDeescalate:
    """Tests for POST /autonomy/deescalate."""

    def test_no_change_at_supervised(self, client: TestClient) -> None:
        """No change when already at SUPERVISED."""
        resp = client.post(
            "/autonomy/deescalate",
            json={"agent_name": "agent-a", "domain": "code"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_change"
