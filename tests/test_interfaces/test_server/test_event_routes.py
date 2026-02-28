"""Tests for temper_ai.interfaces.server.event_routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.event_routes import (
    ReplayRequest,
    SubscribeRequest,
    _handle_list_events,
    _handle_replay,
    _handle_subscribe,
    create_event_router,
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
    app.include_router(create_event_router(auth_enabled=auth_enabled))
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestHandleListEvents:
    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_success(self, mock_bus_cls):
        mock_bus = MagicMock()
        mock_bus.replay_events.return_value = [{"type": "test"}]
        mock_bus_cls.return_value = mock_bus

        result = _handle_list_events(None, 100, 0)
        assert result["total"] == 1

    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_with_offset(self, mock_bus_cls):
        mock_bus = MagicMock()
        mock_bus.replay_events.return_value = [{"type": "a"}, {"type": "b"}]
        mock_bus_cls.return_value = mock_bus

        result = _handle_list_events(None, 100, 1)
        assert result["total"] == 1

    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_error_returns_empty(self, mock_bus_cls):
        mock_bus_cls.side_effect = RuntimeError("no bus")

        result = _handle_list_events(None, 100, 0)
        assert result == {"events": [], "total": 0}


class TestHandleSubscribe:
    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_success(self, mock_bus_cls):
        mock_bus = MagicMock()
        mock_bus.subscribe_persistent.return_value = "sub-123"
        mock_bus_cls.return_value = mock_bus

        body = SubscribeRequest(event_type="workflow_completed")
        result = _handle_subscribe(body)
        assert result["subscription_id"] == "sub-123"
        assert result["status"] == "subscribed"

    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_error_raises_500(self, mock_bus_cls):
        mock_bus = MagicMock()
        mock_bus.subscribe_persistent.side_effect = RuntimeError("fail")
        mock_bus_cls.return_value = mock_bus

        body = SubscribeRequest(event_type="test")
        with pytest.raises(HTTPException) as exc_info:
            _handle_subscribe(body)
        assert exc_info.value.status_code == 500


class TestHandleReplay:
    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_success_with_model_dump(self, mock_bus_cls):
        mock_bus = MagicMock()
        event = MagicMock()
        event.model_dump.return_value = {"type": "test", "data": "x"}
        mock_bus.replay_events.return_value = [event]
        mock_bus_cls.return_value = mock_bus

        body = ReplayRequest(workflow_id="wf1")
        result = _handle_replay(body)
        assert result["total"] == 1
        assert result["workflow_id"] == "wf1"

    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_success_with_dict(self, mock_bus_cls):
        mock_bus = MagicMock()
        event = {"type": "test"}  # dict, no model_dump
        mock_bus.replay_events.return_value = [event]
        mock_bus_cls.return_value = mock_bus

        body = ReplayRequest(workflow_id="wf1")
        result = _handle_replay(body)
        assert result["total"] == 1

    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_error_raises_500(self, mock_bus_cls):
        mock_bus = MagicMock()
        mock_bus.replay_events.side_effect = RuntimeError("fail")
        mock_bus_cls.return_value = mock_bus

        body = ReplayRequest(workflow_id="wf1")
        with pytest.raises(HTTPException) as exc_info:
            _handle_replay(body)
        assert exc_info.value.status_code == 500


class TestEventRouterIntegration:
    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_list_events(self, mock_bus_cls):
        mock_bus = MagicMock()
        mock_bus.replay_events.return_value = []
        mock_bus_cls.return_value = mock_bus

        client = _make_client()
        resp = client.get("/api/events")
        assert resp.status_code == 200

    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_subscribe(self, mock_bus_cls):
        mock_bus = MagicMock()
        mock_bus.subscribe_persistent.return_value = "sub-1"
        mock_bus_cls.return_value = mock_bus

        client = _make_client()
        resp = client.post(
            "/api/events/subscribe",
            json={"event_type": "workflow_completed"},
        )
        assert resp.status_code == 200

    @patch("temper_ai.events.event_bus.TemperEventBus")
    def test_replay(self, mock_bus_cls):
        mock_bus = MagicMock()
        mock_bus.replay_events.return_value = []
        mock_bus_cls.return_value = mock_bus

        client = _make_client()
        resp = client.post(
            "/api/events/replay",
            json={"workflow_id": "wf1"},
        )
        assert resp.status_code == 200
