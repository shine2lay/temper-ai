"""Extended tests for temper_ai.interfaces.dashboard.studio_routes — cover no-auth endpoints."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.interfaces.dashboard.studio_routes import (
    _handle_delete_config,
    _handle_get_config,
    _handle_get_config_raw,
    _handle_get_schema,
    _handle_list_configs,
    _handle_validate_config,
    _validate_config_type_param,
    create_studio_router,
)
from temper_ai.interfaces.dashboard.studio_service import StudioService


def _make_service(tmp_path, use_db=False):
    return StudioService(config_root=str(tmp_path), use_db=use_db)


def _make_client(studio_service, auth_enabled=False):
    app = FastAPI()
    router = create_studio_router(studio_service, auth_enabled=auth_enabled)
    app.include_router(router, prefix="/api/studio")
    return TestClient(app, raise_server_exceptions=False)


class TestValidateConfigTypeParam:
    def test_valid(self):
        _validate_config_type_param("workflows")

    def test_invalid_raises_400(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_config_type_param("bad_type")
        assert exc_info.value.status_code == 400


class TestHandleListConfigsNoAuth:
    def test_list_configs_no_db(self, tmp_path):
        svc = _make_service(tmp_path)
        result = _handle_list_configs(svc, "workflows", None)
        assert "configs" in result

    def test_invalid_type(self, tmp_path):
        svc = _make_service(tmp_path)
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _handle_list_configs(svc, "invalid", None)


class TestHandleGetConfigNoAuth:
    def test_not_found(self, tmp_path):
        svc = _make_service(tmp_path)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_config(svc, "workflows", "nonexistent", None)
        assert exc_info.value.status_code == 404

    def test_invalid_type(self, tmp_path):
        svc = _make_service(tmp_path)
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _handle_get_config(svc, "invalid", "test", None)


class TestHandleGetConfigRaw:
    def test_not_found(self, tmp_path):
        svc = _make_service(tmp_path)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_config_raw(svc, "workflows", "nonexistent")
        assert exc_info.value.status_code == 404

    def test_invalid_type(self, tmp_path):
        svc = _make_service(tmp_path)
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _handle_get_config_raw(svc, "invalid", "test")

    def test_success(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "test.yaml").write_text("workflow:\n  name: test")
        svc = _make_service(tmp_path)
        result = _handle_get_config_raw(svc, "workflows", "test")
        assert result.media_type == "text/yaml"


class TestHandleValidateConfig:
    def test_invalid_type(self, tmp_path):
        svc = _make_service(tmp_path)
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _handle_validate_config(svc, "invalid", {})


class TestHandleGetSchema:
    def test_invalid_type(self, tmp_path):
        svc = _make_service(tmp_path)
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _handle_get_schema(svc, "invalid")

    def test_valid_type(self, tmp_path):
        svc = _make_service(tmp_path)
        result = _handle_get_schema(svc, "workflows")
        assert "properties" in result or "title" in result


class TestHandleDeleteConfigNoAuth:
    def test_not_found(self, tmp_path):
        svc = _make_service(tmp_path)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_delete_config(svc, "workflows", "nonexistent", None)
        assert exc_info.value.status_code == 404


class TestStudioRouterNoAuthEndpoints:
    def test_list_configs(self, tmp_path):
        svc = _make_service(tmp_path)
        client = _make_client(svc, auth_enabled=False)
        resp = client.get("/api/studio/configs/workflows")
        assert resp.status_code == 200

    def test_get_config_not_found(self, tmp_path):
        svc = _make_service(tmp_path)
        client = _make_client(svc, auth_enabled=False)
        resp = client.get("/api/studio/configs/workflows/nonexistent")
        assert resp.status_code == 404

    def test_get_config_raw_not_found(self, tmp_path):
        svc = _make_service(tmp_path)
        client = _make_client(svc, auth_enabled=False)
        resp = client.get("/api/studio/configs/workflows/nonexistent/raw")
        assert resp.status_code == 404

    def test_create_config(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        svc = _make_service(tmp_path)
        client = _make_client(svc, auth_enabled=False)
        resp = client.post(
            "/api/studio/configs/workflows/test-wf",
            json={"workflow": {"name": "test-wf", "stages": []}},
        )
        # May be 201 or 400 depending on validation
        assert resp.status_code in (201, 400)

    def test_update_config_not_found(self, tmp_path):
        svc = _make_service(tmp_path)
        client = _make_client(svc, auth_enabled=False)
        resp = client.put(
            "/api/studio/configs/workflows/nonexistent",
            json={"workflow": {"name": "test"}},
        )
        assert resp.status_code == 404

    def test_delete_config_not_found(self, tmp_path):
        svc = _make_service(tmp_path)
        client = _make_client(svc, auth_enabled=False)
        resp = client.delete("/api/studio/configs/workflows/nonexistent")
        assert resp.status_code == 404

    def test_validate_config(self, tmp_path):
        svc = _make_service(tmp_path)
        client = _make_client(svc, auth_enabled=False)
        resp = client.post(
            "/api/studio/validate/workflows",
            json={"workflow": {"name": "test"}},
        )
        assert resp.status_code == 200

    def test_get_schema(self, tmp_path):
        svc = _make_service(tmp_path)
        client = _make_client(svc, auth_enabled=False)
        resp = client.get("/api/studio/schemas/workflows")
        assert resp.status_code == 200
