"""Tests for HTTP API routes in temper_ai.interfaces.server.agent_routes."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.interfaces.server.agent_routes import router
from temper_ai.registry._schemas import AgentRegistryEntry, MessageResponse

_MOCK_SERVICE_PATH = "temper_ai.interfaces.server.agent_routes._get_service"


def _make_entry(**kwargs) -> AgentRegistryEntry:
    """Build a minimal AgentRegistryEntry for testing."""
    defaults = dict(
        id="abc123",
        name="test-agent",
        agent_type="standard",
        version="1.0",
        status="registered",
        memory_namespace="agent__test-agent",
        total_invocations=0,
        registered_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_active_at=None,
    )
    defaults.update(kwargs)
    return AgentRegistryEntry(**defaults)


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


client = _make_client()


class TestListAgents:
    def test_list_empty(self):
        mock_svc = MagicMock()
        mock_svc.list_agents.return_value = []
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.get("/api/agents")
        assert resp.status_code == 200
        assert resp.json() == {"agents": []}

    def test_list_returns_agents(self):
        entry = _make_entry()
        mock_svc = MagicMock()
        mock_svc.list_agents.return_value = [entry]
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["name"] == "test-agent"

    def test_list_with_status_filter(self):
        mock_svc = MagicMock()
        mock_svc.list_agents.return_value = []
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.get("/api/agents?status=active")
        assert resp.status_code == 200
        mock_svc.list_agents.assert_called_once_with(status="active")


class TestGetAgent:
    def test_get_found(self):
        entry = _make_entry()
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = entry
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.get("/api/agents/test-agent")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-agent"

    def test_get_not_found(self):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = None
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.get("/api/agents/ghost")
        assert resp.status_code == 404


class TestRegisterAgent:
    def test_register_success(self):
        entry = _make_entry()
        mock_svc = MagicMock()
        mock_svc.register_agent.return_value = entry
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.post(
                "/api/agents/register",
                json={"config_path": "/tmp/agent.yaml"},
            )
        assert resp.status_code == 200
        assert resp.json()["agent"]["name"] == "test-agent"

    def test_register_value_error(self):
        mock_svc = MagicMock()
        mock_svc.register_agent.side_effect = ValueError("missing name")
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.post(
                "/api/agents/register",
                json={"config_path": "/tmp/bad.yaml"},
            )
        assert resp.status_code == 400

    def test_register_file_not_found(self):
        mock_svc = MagicMock()
        mock_svc.register_agent.side_effect = FileNotFoundError("not found")
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.post(
                "/api/agents/register",
                json={"config_path": "/nonexistent/agent.yaml"},
            )
        assert resp.status_code == 400


class TestUnregisterAgent:
    def test_delete_success(self):
        mock_svc = MagicMock()
        mock_svc.unregister_agent.return_value = True
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.delete("/api/agents/test-agent")
        assert resp.status_code == 200
        assert resp.json() == {"deleted": True}

    def test_delete_not_found(self):
        mock_svc = MagicMock()
        mock_svc.unregister_agent.return_value = False
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.delete("/api/agents/ghost")
        assert resp.status_code == 404


class TestSendMessage:
    def test_message_success(self):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = _make_entry()
        mock_response = MessageResponse(
            content="hello!", agent_name="test-agent", execution_id="exec-1"
        )
        mock_svc.invoke.return_value = mock_response
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.post(
                "/api/agents/test-agent/message",
                json={"content": "hi"},
            )
        assert resp.status_code == 200
        assert resp.json()["content"] == "hello!"

    def test_message_agent_not_found(self):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = None
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.post(
                "/api/agents/ghost/message",
                json={"content": "hello"},
            )
        assert resp.status_code == 404

    def test_message_invoke_error(self):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = _make_entry()
        mock_svc.invoke.side_effect = RuntimeError("agent failed")
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            resp = client.post(
                "/api/agents/test-agent/message",
                json={"content": "hi"},
            )
        assert resp.status_code == 500
