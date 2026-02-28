"""Tests for temper_ai.interfaces.server.config_routes — config import/export endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.config_routes import (
    EDITOR_ROLES,
    VIEWER_ROLES,
    ImportConfigRequest,
    _handle_export_config,
    _handle_import_config,
    _handle_list_configs,
    _invalid_config_type_detail,
    _validate_and_normalize_config_type,
    create_config_router,
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
    app.include_router(create_config_router())
    app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestConstants:
    def test_editor_roles(self):
        assert "editor" in EDITOR_ROLES
        assert "owner" in EDITOR_ROLES

    def test_viewer_roles(self):
        assert "viewer" in VIEWER_ROLES
        assert "editor" in VIEWER_ROLES
        assert "owner" in VIEWER_ROLES


class TestInvalidConfigTypeDetail:
    def test_message_format(self):
        result = _invalid_config_type_detail("bad", frozenset({"a", "b"}))
        assert "bad" in result
        assert "Must be one of" in result


class TestValidateAndNormalizeConfigType:
    def test_valid_type(self):
        result = _validate_and_normalize_config_type("  Workflow  ")
        assert result == "workflow"

    def test_invalid_type(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_and_normalize_config_type("invalid_type")
        assert exc_info.value.status_code == 400


class TestHandleImportConfig:
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_success(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.import_config.return_value = {"name": "test", "version": 1}
        mock_get_svc.return_value = mock_svc

        body = ImportConfigRequest(
            config_type="workflow", name="test", yaml_content="workflow:\n  name: test"
        )
        result = _handle_import_config(body, _MOCK_AUTH_CTX)
        assert result["name"] == "test"
        assert result["config_type"] == "workflow"

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_empty_name_raises_400(self, mock_get_svc):
        body = ImportConfigRequest(
            config_type="workflow", name="  ", yaml_content="data"
        )
        with pytest.raises(HTTPException) as exc_info:
            _handle_import_config(body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_invalid_config_type_raises_400(self, mock_get_svc):
        body = ImportConfigRequest(
            config_type="bad_type", name="test", yaml_content="data"
        )
        with pytest.raises(HTTPException) as exc_info:
            _handle_import_config(body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_value_error_raises_422(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.import_config.side_effect = ValueError("parse error")
        mock_get_svc.return_value = mock_svc

        body = ImportConfigRequest(
            config_type="workflow", name="test", yaml_content="bad"
        )
        with pytest.raises(HTTPException) as exc_info:
            _handle_import_config(body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 422


class TestHandleExportConfig:
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_success(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.export_config.return_value = "workflow:\n  name: test"
        mock_get_svc.return_value = mock_svc

        result = _handle_export_config("workflow", "test", _MOCK_AUTH_CTX)
        assert result.media_type == "text/yaml"

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_not_found_raises_404(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.export_config.side_effect = KeyError("not found")
        mock_get_svc.return_value = mock_svc

        with pytest.raises(HTTPException) as exc_info:
            _handle_export_config("workflow", "missing", _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 404


class TestHandleListConfigs:
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_success(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.list_configs.return_value = [{"name": "a"}, {"name": "b"}]
        mock_get_svc.return_value = mock_svc

        result = _handle_list_configs("workflow", _MOCK_AUTH_CTX)
        assert result["total"] == 2


class TestConfigRouterIntegration:
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_import_endpoint(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.import_config.return_value = {"name": "test", "version": 1}
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.post(
            "/api/configs/import",
            json={
                "config_type": "workflow",
                "name": "test",
                "yaml_content": "workflow:\n  name: test",
            },
        )
        assert resp.status_code == 200

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_export_endpoint(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.export_config.return_value = "yaml content"
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.get("/api/configs/workflow/test/export")
        assert resp.status_code == 200

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_list_endpoint(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.list_configs.return_value = []
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.get("/api/configs/workflow")
        assert resp.status_code == 200
