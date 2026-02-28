"""Tests for temper_ai.interfaces.server.agent_routes."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth, require_role
from temper_ai.interfaces.server.agent_routes import (
    _agent_not_found_detail,
    router,
)

_MOCK_AUTH_CTX = AuthContext(
    user_id="test-user",
    tenant_id="test-tenant",
    role="owner",
    api_key_id="key-test",
)


def _mock_auth():
    async def _dep():
        return _MOCK_AUTH_CTX

    return _dep


def _make_client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = _mock_auth()
    # Override require_role for all roles

    def _role_override(*roles):
        async def _dep():
            return _MOCK_AUTH_CTX

        return _dep

    app.dependency_overrides[require_role] = _mock_auth()
    # Patch at function level via overrides for the Depends
    return TestClient(app, raise_server_exceptions=False)


class TestAgentNotFoundDetail:
    def test_format(self):
        result = _agent_not_found_detail("my-agent")
        assert "my-agent" in result
        assert "not found" in result


class TestListAgents:
    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_list_all(self, mock_get_svc):
        mock_svc = MagicMock()
        agent_mock = MagicMock()
        agent_mock.model_dump.return_value = {"name": "agent1", "status": "active"}
        mock_svc.list_agents.return_value = [agent_mock]
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        assert len(resp.json()["agents"]) == 1

    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_list_with_status_filter(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.list_agents.return_value = []
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.get("/api/agents?status=active")
        assert resp.status_code == 200


class TestGetAgent:
    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_found(self, mock_get_svc):
        mock_svc = MagicMock()
        agent_mock = MagicMock()
        agent_mock.model_dump.return_value = {"name": "agent1"}
        mock_svc.get_agent.return_value = agent_mock
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.get("/api/agents/agent1")
        assert resp.status_code == 200

    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_not_found(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = None
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.get("/api/agents/missing")
        assert resp.status_code == 404


class TestRegisterAgent:
    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_success(self, mock_get_svc):
        mock_svc = MagicMock()
        entry_mock = MagicMock()
        entry_mock.model_dump.return_value = {"name": "new-agent"}
        mock_svc.register_agent.return_value = entry_mock
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.post(
            "/api/agents/register",
            json={"config_path": "/path/to/config.yaml"},
        )
        assert resp.status_code == 200

    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_value_error(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.register_agent.side_effect = ValueError("invalid config")
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.post(
            "/api/agents/register",
            json={"config_path": "/path/to/config.yaml"},
        )
        assert resp.status_code == 400

    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_file_not_found(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.register_agent.side_effect = FileNotFoundError("not found")
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.post(
            "/api/agents/register",
            json={"config_path": "/missing/config.yaml"},
        )
        assert resp.status_code == 400


class TestUnregisterAgent:
    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_success(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.unregister_agent.return_value = True
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.delete("/api/agents/agent1")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_not_found(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.unregister_agent.return_value = False
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.delete("/api/agents/missing")
        assert resp.status_code == 404


class TestSendMessage:
    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_success(self, mock_get_svc):
        mock_svc = MagicMock()
        agent_mock = MagicMock()
        mock_svc.get_agent.return_value = agent_mock
        response_mock = MagicMock()
        response_mock.model_dump.return_value = {
            "content": "hello",
            "agent_name": "a1",
            "execution_id": "e1",
        }
        mock_svc.invoke.return_value = response_mock
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.post("/api/agents/a1/message", json={"content": "hi"})
        assert resp.status_code == 200

    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_agent_not_found(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = None
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.post("/api/agents/missing/message", json={"content": "hi"})
        assert resp.status_code == 404

    @patch("temper_ai.interfaces.server.agent_routes._get_service")
    def test_invocation_error(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = MagicMock()
        mock_svc.invoke.side_effect = RuntimeError("invoke failed")
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.post("/api/agents/a1/message", json={"content": "hi"})
        assert resp.status_code == 500
