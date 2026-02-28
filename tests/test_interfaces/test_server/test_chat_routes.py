"""Tests for temper_ai.interfaces.server.chat_routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.chat_routes import (
    _SESSIONS,
    CreateSessionRequest,
    SendMessageRequest,
    _handle_create_session,
    _handle_delete_session,
    _handle_send_message,
    create_chat_router,
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


def _make_client(auth_enabled=False):
    app = FastAPI()
    app.include_router(create_chat_router(auth_enabled=auth_enabled))
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestHandleCreateSession:
    @patch("temper_ai.registry.service.AgentRegistryService")
    def test_success(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        body = CreateSessionRequest(agent_name="test-agent")
        result = _handle_create_session(body)
        assert result.agent_name == "test-agent"
        assert result.status == "active"
        # Clean up
        _SESSIONS.pop(result.session_id, None)

    @patch("temper_ai.registry.service.AgentRegistryService")
    def test_agent_not_found(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = None
        mock_svc_cls.return_value = mock_svc

        body = CreateSessionRequest(agent_name="missing")
        with pytest.raises(HTTPException) as exc_info:
            _handle_create_session(body)
        assert exc_info.value.status_code == 404

    @patch("temper_ai.registry.service.AgentRegistryService")
    def test_service_error(self, mock_svc_cls):
        mock_svc_cls.side_effect = RuntimeError("fail")

        body = CreateSessionRequest(agent_name="test")
        with pytest.raises(HTTPException) as exc_info:
            _handle_create_session(body)
        assert exc_info.value.status_code == 500


class TestHandleSendMessage:
    def test_session_not_found(self):
        body = SendMessageRequest(content="hello")
        with pytest.raises(HTTPException) as exc_info:
            _handle_send_message("nonexistent", body)
        assert exc_info.value.status_code == 404

    def test_session_not_active(self):
        _SESSIONS["inactive-session"] = {
            "session_id": "inactive-session",
            "agent_name": "test",
            "status": "closed",
        }
        body = SendMessageRequest(content="hello")
        with pytest.raises(HTTPException) as exc_info:
            _handle_send_message("inactive-session", body)
        assert exc_info.value.status_code == 400
        _SESSIONS.pop("inactive-session", None)

    @patch("temper_ai.registry.service.AgentRegistryService")
    def test_success(self, mock_svc_cls):
        mock_svc = MagicMock()
        response_mock = MagicMock()
        response_mock.content = "reply"
        response_mock.agent_name = "agent1"
        response_mock.execution_id = "exec1"
        mock_svc.invoke.return_value = response_mock
        mock_svc_cls.return_value = mock_svc

        _SESSIONS["test-session"] = {
            "session_id": "test-session",
            "agent_name": "agent1",
            "status": "active",
        }
        body = SendMessageRequest(content="hello")
        result = _handle_send_message("test-session", body)
        assert result.content == "reply"
        _SESSIONS.pop("test-session", None)

    @patch("temper_ai.registry.service.AgentRegistryService")
    def test_key_error(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.invoke.side_effect = KeyError("agent not found")
        mock_svc_cls.return_value = mock_svc

        _SESSIONS["key-err-session"] = {
            "session_id": "key-err-session",
            "agent_name": "agent1",
            "status": "active",
        }
        body = SendMessageRequest(content="hello")
        with pytest.raises(HTTPException) as exc_info:
            _handle_send_message("key-err-session", body)
        assert exc_info.value.status_code == 404
        _SESSIONS.pop("key-err-session", None)

    @patch("temper_ai.registry.service.AgentRegistryService")
    def test_generic_error(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.invoke.side_effect = RuntimeError("boom")
        mock_svc_cls.return_value = mock_svc

        _SESSIONS["err-session"] = {
            "session_id": "err-session",
            "agent_name": "agent1",
            "status": "active",
        }
        body = SendMessageRequest(content="hello")
        with pytest.raises(HTTPException) as exc_info:
            _handle_send_message("err-session", body)
        assert exc_info.value.status_code == 500
        _SESSIONS.pop("err-session", None)


class TestHandleDeleteSession:
    def test_success(self):
        _SESSIONS["del-session"] = {
            "session_id": "del-session",
            "agent_name": "test",
            "status": "active",
        }
        result = _handle_delete_session("del-session")
        assert result["status"] == "deleted"
        assert "del-session" not in _SESSIONS

    def test_not_found(self):
        with pytest.raises(HTTPException) as exc_info:
            _handle_delete_session("nonexistent")
        assert exc_info.value.status_code == 404


class TestChatRouterIntegration:
    @patch("temper_ai.registry.service.AgentRegistryService")
    def test_create_session(self, mock_svc_cls):
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        client = _make_client()
        resp = client.post("/api/chat/sessions", json={"agent_name": "test"})
        assert resp.status_code == 200
        # Clean up
        sid = resp.json().get("session_id")
        if sid:
            _SESSIONS.pop(sid, None)

    def test_delete_session_not_found(self):
        client = _make_client()
        resp = client.delete("/api/chat/sessions/nonexistent")
        assert resp.status_code == 404
