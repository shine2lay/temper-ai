"""Tests for temper_ai.interfaces.server.rollback_routes."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.rollback_routes import (
    RollbackExecuteRequest,
    _handle_execute_rollback,
    _handle_get_rollback,
    _handle_list_rollbacks,
    create_rollback_router,
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
    app.include_router(create_rollback_router(auth_enabled=auth_enabled))
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestHandleListRollbacks:
    @patch("temper_ai.safety.rollback_api.RollbackAPI")
    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_success(self, mock_mgr_cls, mock_api_cls):
        snapshot = MagicMock()
        snapshot.id = "rb1"
        snapshot.action = "revert"
        snapshot.context = {}
        snapshot.created_at = datetime.now(UTC)
        snapshot.expires_at = None
        snapshot.file_snapshots = []

        mock_api = MagicMock()
        mock_api.list_snapshots.return_value = [snapshot]
        mock_api_cls.return_value = mock_api

        result = _handle_list_rollbacks(None, None, 100)
        assert result["total"] == 1

    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_error_raises_500(self, mock_mgr_cls):
        mock_mgr_cls.side_effect = RuntimeError("fail")

        with pytest.raises(HTTPException) as exc_info:
            _handle_list_rollbacks(None, None, 100)
        assert exc_info.value.status_code == 500


class TestHandleGetRollback:
    @patch("temper_ai.safety.rollback_api.RollbackAPI")
    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_found(self, mock_mgr_cls, mock_api_cls):
        mock_api = MagicMock()
        mock_api.get_snapshot_details.return_value = {"id": "rb1", "files": []}
        mock_api_cls.return_value = mock_api

        result = _handle_get_rollback("rb1")
        assert result["id"] == "rb1"

    @patch("temper_ai.safety.rollback_api.RollbackAPI")
    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_not_found(self, mock_mgr_cls, mock_api_cls):
        mock_api = MagicMock()
        mock_api.get_snapshot_details.return_value = None
        mock_api_cls.return_value = mock_api

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_rollback("missing")
        assert exc_info.value.status_code == 404

    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_error_raises_500(self, mock_mgr_cls):
        mock_mgr_cls.side_effect = RuntimeError("db error")

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_rollback("rb1")
        assert exc_info.value.status_code == 500


class TestHandleExecuteRollback:
    @patch("temper_ai.safety.rollback_api.RollbackAPI")
    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_success(self, mock_mgr_cls, mock_api_cls):
        mock_api = MagicMock()
        result_mock = MagicMock()
        result_mock.snapshot_id = "rb1"
        result_mock.success = True
        result_mock.reverted_items = 3
        result_mock.metadata = {}
        mock_api.execute_manual_rollback.return_value = result_mock
        mock_api_cls.return_value = mock_api

        body = RollbackExecuteRequest(operator="admin", reason="fix")
        result = _handle_execute_rollback("rb1", body)
        assert result["success"] is True
        assert result["files_restored"] == 3

    @patch("temper_ai.safety.rollback_api.RollbackAPI")
    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_value_error(self, mock_mgr_cls, mock_api_cls):
        mock_api = MagicMock()
        mock_api.execute_manual_rollback.side_effect = ValueError("bad snapshot")
        mock_api_cls.return_value = mock_api

        body = RollbackExecuteRequest(operator="admin", reason="fix")
        with pytest.raises(HTTPException) as exc_info:
            _handle_execute_rollback("rb1", body)
        assert exc_info.value.status_code == 400

    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_generic_error(self, mock_mgr_cls):
        mock_mgr_cls.side_effect = RuntimeError("fail")

        body = RollbackExecuteRequest(operator="admin", reason="fix")
        with pytest.raises(HTTPException) as exc_info:
            _handle_execute_rollback("rb1", body)
        assert exc_info.value.status_code == 500


class TestRollbackRouterIntegration:
    @patch("temper_ai.safety.rollback_api.RollbackAPI")
    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_list_rollbacks(self, mock_mgr_cls, mock_api_cls):
        mock_api = MagicMock()
        mock_api.list_snapshots.return_value = []
        mock_api_cls.return_value = mock_api

        client = _make_client()
        resp = client.get("/api/rollbacks")
        assert resp.status_code == 200

    @patch("temper_ai.safety.rollback_api.RollbackAPI")
    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_get_rollback(self, mock_mgr_cls, mock_api_cls):
        mock_api = MagicMock()
        mock_api.get_snapshot_details.return_value = {"id": "rb1"}
        mock_api_cls.return_value = mock_api

        client = _make_client()
        resp = client.get("/api/rollbacks/rb1")
        assert resp.status_code == 200

    @patch("temper_ai.safety.rollback_api.RollbackAPI")
    @patch("temper_ai.safety.rollback.RollbackManager")
    def test_execute_rollback(self, mock_mgr_cls, mock_api_cls):
        mock_api = MagicMock()
        result_mock = MagicMock()
        result_mock.snapshot_id = "rb1"
        result_mock.success = True
        result_mock.reverted_items = 0
        result_mock.metadata = {}
        mock_api.execute_manual_rollback.return_value = result_mock
        mock_api_cls.return_value = mock_api

        client = _make_client()
        resp = client.post(
            "/api/rollbacks/rb1/execute",
            json={"operator": "admin", "reason": "fix"},
        )
        assert resp.status_code == 200
