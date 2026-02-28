"""Tests for temper_ai.interfaces.server.plugin_routes."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.plugin_routes import (
    ImportPluginRequest,
    _handle_import_plugin,
    _handle_plugin_health,
    create_plugin_router,
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
    app.include_router(create_plugin_router(auth_enabled=auth_enabled))
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestHandleImportPlugin:
    @patch("temper_ai.plugins.registry.is_plugin_type")
    @patch("temper_ai.plugins.registry.ensure_plugin_registered")
    def test_success(self, mock_register, mock_is_plugin):
        mock_is_plugin.return_value = True
        mock_register.return_value = True

        body = ImportPluginRequest(framework="crewai")
        result = _handle_import_plugin(body)
        assert result["status"] == "registered"

    @patch("temper_ai.plugins.registry.is_plugin_type")
    def test_unknown_framework(self, mock_is_plugin):
        mock_is_plugin.return_value = False

        body = ImportPluginRequest(framework="unknown")
        with pytest.raises(HTTPException) as exc_info:
            _handle_import_plugin(body)
        assert exc_info.value.status_code == 404

    @patch("temper_ai.plugins.registry.is_plugin_type")
    @patch("temper_ai.plugins.registry.ensure_plugin_registered")
    def test_registration_failure(self, mock_register, mock_is_plugin):
        mock_is_plugin.return_value = True
        mock_register.return_value = False

        body = ImportPluginRequest(framework="crewai")
        with pytest.raises(HTTPException) as exc_info:
            _handle_import_plugin(body)
        assert exc_info.value.status_code == 500

    @patch("temper_ai.plugins.registry.is_plugin_type")
    @patch("temper_ai.plugins.registry.ensure_plugin_registered")
    def test_generic_error(self, mock_register, mock_is_plugin):
        mock_is_plugin.return_value = True
        mock_register.side_effect = RuntimeError("boom")

        body = ImportPluginRequest(framework="crewai")
        with pytest.raises(HTTPException) as exc_info:
            _handle_import_plugin(body)
        assert exc_info.value.status_code == 500


class TestHandlePluginHealth:
    @pytest.mark.asyncio
    @patch("temper_ai.plugins.registry.is_plugin_type")
    @patch("temper_ai.plugins.registry.get_health_checks")
    async def test_success(self, mock_health, mock_is_plugin):
        mock_is_plugin.return_value = True
        mock_health.return_value = {"crewai": {"status": "healthy"}}

        result = await _handle_plugin_health("crewai")
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    @patch("temper_ai.plugins.registry.is_plugin_type")
    async def test_unknown_framework(self, mock_is_plugin):
        mock_is_plugin.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await _handle_plugin_health("unknown")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("temper_ai.plugins.registry.is_plugin_type")
    @patch("temper_ai.plugins.registry.get_health_checks")
    async def test_no_health_data(self, mock_health, mock_is_plugin):
        mock_is_plugin.return_value = True
        mock_health.return_value = {}

        with pytest.raises(HTTPException) as exc_info:
            await _handle_plugin_health("crewai")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("temper_ai.plugins.registry.is_plugin_type")
    @patch("temper_ai.plugins.registry.get_health_checks")
    async def test_error_raises_500(self, mock_health, mock_is_plugin):
        mock_is_plugin.return_value = True
        mock_health.side_effect = RuntimeError("fail")

        with pytest.raises(HTTPException) as exc_info:
            await _handle_plugin_health("crewai")
        assert exc_info.value.status_code == 500


class TestPluginRouterIntegration:
    @patch("temper_ai.plugins.registry.list_plugins")
    def test_list_plugins(self, mock_list):
        mock_list.return_value = [{"name": "crewai"}]

        client = _make_client()
        resp = client.get("/api/plugins")
        assert resp.status_code == 200

    @patch("temper_ai.plugins.registry.is_plugin_type")
    @patch("temper_ai.plugins.registry.ensure_plugin_registered")
    def test_import_plugin(self, mock_register, mock_is_plugin):
        mock_is_plugin.return_value = True
        mock_register.return_value = True

        client = _make_client()
        resp = client.post("/api/plugins/import", json={"framework": "crewai"})
        assert resp.status_code == 200

    @patch("temper_ai.plugins.registry.is_plugin_type")
    @patch("temper_ai.plugins.registry.get_health_checks")
    def test_plugin_health(self, mock_health, mock_is_plugin):
        mock_is_plugin.return_value = True
        mock_health.return_value = {"crewai": {"status": "ok"}}

        client = _make_client()
        resp = client.get("/api/plugins/crewai/health")
        assert resp.status_code == 200
