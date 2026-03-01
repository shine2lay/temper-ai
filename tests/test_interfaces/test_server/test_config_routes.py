"""Tests for temper_ai.interfaces.server.config_routes — config CRUD, import/export."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.config_routes import (
    EDITOR_ROLES,
    VIEWER_ROLES,
    ConfigCreateRequest,
    ConfigUpdateRequest,
    ForkRequest,
    ImportConfigRequest,
    _handle_create_config,
    _handle_delete_config,
    _handle_export_config,
    _handle_fork_config,
    _handle_get_config,
    _handle_import_config,
    _handle_list_configs,
    _handle_update_config,
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


class TestHandleCreateConfig:
    @patch("temper_ai.interfaces.server.config_routes._validate_config_data")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_success(self, mock_get_svc, mock_validate):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = None
        mock_svc.create_config.return_value = {
            "id": "cfg-1",
            "name": "my-wf",
            "version": 1,
        }
        mock_get_svc.return_value = mock_svc

        body = ConfigCreateRequest(
            name="my-wf", config_data={"workflow": {"name": "my-wf"}}
        )
        result = _handle_create_config("workflow", body, _MOCK_AUTH_CTX)
        assert result["id"] == "cfg-1"
        assert result["name"] == "my-wf"

    @patch("temper_ai.interfaces.server.config_routes._validate_config_data")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_duplicate_raises_400(self, mock_get_svc, mock_validate):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = {"id": "existing"}
        mock_get_svc.return_value = mock_svc

        body = ConfigCreateRequest(
            name="dup", config_data={"workflow": {"name": "dup"}}
        )
        with pytest.raises(HTTPException) as exc_info:
            _handle_create_config("workflow", body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_empty_name_raises_400(self, mock_get_svc):
        body = ConfigCreateRequest(name="  ", config_data={})
        with pytest.raises(HTTPException) as exc_info:
            _handle_create_config("workflow", body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400

    def test_invalid_type_raises_400(self):
        body = ConfigCreateRequest(name="test", config_data={})
        with pytest.raises(HTTPException) as exc_info:
            _handle_create_config("bad_type", body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400


class TestHandleGetConfig:
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_found(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = {"id": "cfg-1", "name": "my-wf"}
        mock_get_svc.return_value = mock_svc

        result = _handle_get_config("workflow", "my-wf", _MOCK_AUTH_CTX)
        assert result["name"] == "my-wf"

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_not_found_raises_404(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = None
        mock_get_svc.return_value = mock_svc

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_config("workflow", "missing", _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 404


class TestHandleUpdateConfig:
    @patch("temper_ai.interfaces.server.config_routes._validate_config_data")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_success(self, mock_get_svc, mock_validate):
        mock_svc = MagicMock()
        mock_svc.update_config.return_value = {
            "id": "cfg-1",
            "name": "wf",
            "version": 2,
        }
        mock_get_svc.return_value = mock_svc

        body = ConfigUpdateRequest(config_data={"workflow": {"name": "wf"}})
        result = _handle_update_config("workflow", "wf", body, _MOCK_AUTH_CTX)
        assert result["version"] == 2

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_not_found_raises_404(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.update_config.side_effect = KeyError("not found")
        mock_get_svc.return_value = mock_svc

        body = ConfigUpdateRequest(description="updated")
        with pytest.raises(HTTPException) as exc_info:
            _handle_update_config("workflow", "missing", body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 404


class TestHandleDeleteConfig:
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_success(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_get_svc.return_value = mock_svc

        result = _handle_delete_config("workflow", "wf", _MOCK_AUTH_CTX)
        assert result["status"] == "deleted"

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_not_found_raises_404(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.delete_config.side_effect = KeyError("not found")
        mock_get_svc.return_value = mock_svc

        with pytest.raises(HTTPException) as exc_info:
            _handle_delete_config("workflow", "missing", _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 404


class TestHandleForkConfig:
    @patch("temper_ai.interfaces.server.config_routes._validate_config_data")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_fork_from_db(self, mock_get_svc, mock_validate):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = {
            "config_data": {"workflow": {"name": "original"}},
        }
        mock_svc.create_config.return_value = {"id": "fork-1", "name": "forked"}
        mock_get_svc.return_value = mock_svc

        body = ForkRequest(new_name="forked")
        result = _handle_fork_config("workflow", "original", body, _MOCK_AUTH_CTX)
        assert result["forked_from"] == "original"
        assert result["name"] == "forked"

    @patch("temper_ai.interfaces.server.config_routes._validate_config_data")
    @patch("temper_ai.interfaces.server.config_routes._load_filesystem_template")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_fork_from_template(self, mock_get_svc, mock_load_tpl, mock_validate):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = None
        mock_svc.create_config.return_value = {"id": "fork-2", "name": "my-fork"}
        mock_get_svc.return_value = mock_svc
        mock_load_tpl.return_value = {"workflow": {"name": "template"}}

        body = ForkRequest(new_name="my-fork")
        result = _handle_fork_config("workflow", "template", body, _MOCK_AUTH_CTX)
        assert result["forked_from"] == "template"

    @patch("temper_ai.interfaces.server.config_routes._load_filesystem_template")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_fork_not_found_raises_404(self, mock_get_svc, mock_load_tpl):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = None
        mock_get_svc.return_value = mock_svc
        mock_load_tpl.return_value = None

        body = ForkRequest(new_name="forked")
        with pytest.raises(HTTPException) as exc_info:
            _handle_fork_config("workflow", "missing", body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 404

    @patch("temper_ai.interfaces.server.config_routes._validate_config_data")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_fork_with_overrides(self, mock_get_svc, mock_validate):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = {
            "config_data": {"workflow": {"name": "original", "timeout": 30}},
        }
        mock_svc.create_config.return_value = {"id": "fork-3", "name": "custom"}
        mock_get_svc.return_value = mock_svc

        body = ForkRequest(new_name="custom", overrides={"timeout": 60})
        result = _handle_fork_config("workflow", "original", body, _MOCK_AUTH_CTX)
        assert result["name"] == "custom"

        # Verify overrides were applied to config_data
        call_kwargs = mock_svc.create_config.call_args
        config_data = call_kwargs.kwargs.get(
            "config_data", call_kwargs[1].get("config_data")
        )
        assert config_data["timeout"] == 60


class TestHandleListTemplates:
    def test_returns_templates(self, tmp_path):
        from temper_ai.interfaces.server.config_routes import _handle_list_templates

        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "research.yaml").write_text(
            "workflow:\n  name: research\n  description: Research workflow"
        )

        result = _handle_list_templates("workflow", str(tmp_path))
        assert result["total"] == 1
        assert result["templates"][0]["name"] == "research"

    def test_empty_directory(self, tmp_path):
        from temper_ai.interfaces.server.config_routes import _handle_list_templates

        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()

        result = _handle_list_templates("workflow", str(tmp_path))
        assert result["total"] == 0

    def test_nonexistent_directory(self, tmp_path):
        from temper_ai.interfaces.server.config_routes import _handle_list_templates

        result = _handle_list_templates("workflow", str(tmp_path))
        assert result["total"] == 0


class TestCRUDRouterIntegration:
    @patch("temper_ai.interfaces.server.config_routes._validate_config_data")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_create_endpoint(self, mock_get_svc, mock_validate):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = None
        mock_svc.create_config.return_value = {
            "id": "cfg-1",
            "name": "wf",
            "version": 1,
        }
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.post(
            "/api/configs/workflow",
            json={"name": "wf", "config_data": {"workflow": {"name": "wf"}}},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "cfg-1"

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_get_endpoint(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = {"id": "cfg-1", "name": "my-wf"}
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.get("/api/configs/workflow/my-wf")
        assert resp.status_code == 200
        assert resp.json()["name"] == "my-wf"

    @patch("temper_ai.interfaces.server.config_routes._validate_config_data")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_update_endpoint(self, mock_get_svc, mock_validate):
        mock_svc = MagicMock()
        mock_svc.update_config.return_value = {
            "id": "cfg-1",
            "name": "wf",
            "version": 2,
        }
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.put(
            "/api/configs/workflow/wf",
            json={"config_data": {"workflow": {"name": "wf"}}},
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 2

    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_delete_endpoint(self, mock_get_svc):
        mock_svc = MagicMock()
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.delete("/api/configs/workflow/wf")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    @patch("temper_ai.interfaces.server.config_routes._validate_config_data")
    @patch("temper_ai.interfaces.server.config_routes._get_sync_service")
    def test_fork_endpoint(self, mock_get_svc, mock_validate):
        mock_svc = MagicMock()
        mock_svc.get_config.return_value = {
            "config_data": {"workflow": {"name": "src"}},
        }
        mock_svc.create_config.return_value = {"id": "f-1", "name": "forked"}
        mock_get_svc.return_value = mock_svc

        client = _make_client()
        resp = client.post(
            "/api/configs/workflow/src/fork",
            json={"new_name": "forked"},
        )
        assert resp.status_code == 200
        assert resp.json()["forked_from"] == "src"
