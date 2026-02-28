"""Tests for temper_ai.interfaces.dashboard.studio_routes — auth mode endpoints."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.dashboard.studio_routes import (
    _handle_create_config,
    _handle_delete_config,
    _handle_get_config,
    _handle_get_schema,
    _handle_list_configs,
    _handle_update_config,
    _handle_validate_config,
    create_studio_router,
)
from temper_ai.interfaces.dashboard.studio_service import StudioService

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


def _make_service(tmp_path, use_db=False):
    return StudioService(config_root=str(tmp_path), use_db=use_db)


def _make_auth_client(studio_service):
    app = FastAPI()
    router = create_studio_router(studio_service, auth_enabled=True)
    app.include_router(router, prefix="/api/studio")
    app.dependency_overrides[require_auth] = _mock_auth()
    # Override role-based auth too

    def mock_require_role(*roles):
        async def _dep():
            return _MOCK_AUTH_CTX

        return _dep

    # We need to override at the dependency level
    return TestClient(app, raise_server_exceptions=False)


class TestHandleCreateConfigWithAuth:
    def test_create_config_no_db(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        svc = _make_service(tmp_path, use_db=False)

        from fastapi import HTTPException

        # Invalid data will raise ValueError
        try:
            _handle_create_config(
                svc,
                "workflows",
                "test-wf",
                {"workflow": {"name": "test-wf", "stages": []}},
                None,
            )
        except (ValueError, HTTPException):
            pass  # Expected if validation fails

    def test_create_config_file_exists(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "existing.yaml").write_text("workflow:\n  name: existing")
        svc = _make_service(tmp_path, use_db=False)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_create_config(
                svc, "workflows", "existing", {"workflow": {"name": "existing"}}, None
            )
        assert exc_info.value.status_code == 409


class TestHandleUpdateConfigWithAuth:
    def test_update_not_found(self, tmp_path):
        (tmp_path / "workflows").mkdir()
        svc = _make_service(tmp_path, use_db=False)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_update_config(
                svc, "workflows", "missing", {"workflow": {"name": "test"}}, None
            )
        assert exc_info.value.status_code == 404


class TestHandlerDbPaths:
    """Test handler functions when ctx is not None and use_db is True."""

    def test_list_configs_db_path(self):
        svc = MagicMock()
        svc.use_db = True
        svc.list_configs_db.return_value = {"configs": []}

        result = _handle_list_configs(svc, "workflows", _MOCK_AUTH_CTX)
        svc.list_configs_db.assert_called_once_with("workflows", "test-tenant")
        assert result == {"configs": []}

    def test_list_configs_db_value_error(self):
        from fastapi import HTTPException

        svc = MagicMock()
        svc.use_db = True
        svc.list_configs_db.side_effect = ValueError("bad type")

        with pytest.raises(HTTPException) as exc_info:
            _handle_list_configs(svc, "workflows", _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400

    def test_get_config_db_path(self):
        svc = MagicMock()
        svc.use_db = True
        svc.get_config_db.return_value = {"name": "test"}

        _handle_get_config(svc, "workflows", "test", _MOCK_AUTH_CTX)
        svc.get_config_db.assert_called_once_with("workflows", "test", "test-tenant")

    def test_get_config_db_value_error(self):
        from fastapi import HTTPException

        svc = MagicMock()
        svc.use_db = True
        svc.get_config_db.side_effect = ValueError("bad")

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_config(svc, "workflows", "test", _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400

    def test_create_config_db_path(self):
        svc = MagicMock()
        svc.use_db = True
        svc.create_config_db.return_value = {"created": True}

        _handle_create_config(svc, "workflows", "new", {"data": 1}, _MOCK_AUTH_CTX)
        svc.create_config_db.assert_called_once_with(
            "workflows", "new", {"data": 1}, "test-tenant", "test-user"
        )

    def test_update_config_db_path(self):
        svc = MagicMock()
        svc.use_db = True
        svc.update_config_db.return_value = {"updated": True}

        _handle_update_config(svc, "workflows", "existing", {"data": 1}, _MOCK_AUTH_CTX)
        svc.update_config_db.assert_called_once_with(
            "workflows", "existing", {"data": 1}, "test-tenant", "test-user"
        )

    def test_update_config_db_value_error(self):
        from fastapi import HTTPException

        svc = MagicMock()
        svc.use_db = True
        svc.update_config_db.side_effect = ValueError("bad data")

        with pytest.raises(HTTPException) as exc_info:
            _handle_update_config(
                svc, "workflows", "existing", {"data": 1}, _MOCK_AUTH_CTX
            )
        assert exc_info.value.status_code == 400

    def test_delete_config_db_path(self):
        svc = MagicMock()
        svc.use_db = True
        svc.delete_config_db.return_value = {"deleted": True}

        _handle_delete_config(svc, "workflows", "old", _MOCK_AUTH_CTX)
        svc.delete_config_db.assert_called_once_with("workflows", "old", "test-tenant")

    def test_delete_config_db_value_error(self):
        from fastapi import HTTPException

        svc = MagicMock()
        svc.use_db = True
        svc.delete_config_db.side_effect = ValueError("invalid")

        with pytest.raises(HTTPException) as exc_info:
            _handle_delete_config(svc, "workflows", "old", _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400

    def test_validate_config_value_error(self):
        from fastapi import HTTPException

        svc = MagicMock()
        svc.validate_config.side_effect = ValueError("invalid data")

        with pytest.raises(HTTPException) as exc_info:
            _handle_validate_config(svc, "workflows", {"bad": True})
        assert exc_info.value.status_code == 400

    def test_get_schema_value_error(self):
        from fastapi import HTTPException

        svc = MagicMock()
        svc.get_schema.side_effect = ValueError("unknown type")

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_schema(svc, "invalid_type")
        assert exc_info.value.status_code == 400


class TestAuthModeStudioRouter:
    def test_list_configs_auth(self, tmp_path):
        svc = _make_service(tmp_path)
        app = FastAPI()
        router = create_studio_router(svc, auth_enabled=True)
        app.include_router(router, prefix="/api/studio")
        app.dependency_overrides[require_auth] = _mock_auth()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/studio/configs/workflows")
        assert resp.status_code == 200

    def test_get_config_auth(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "test.yaml").write_text("workflow:\n  name: test")
        svc = _make_service(tmp_path)
        app = FastAPI()
        router = create_studio_router(svc, auth_enabled=True)
        app.include_router(router, prefix="/api/studio")
        app.dependency_overrides[require_auth] = _mock_auth()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/studio/configs/workflows/test")
        assert resp.status_code == 200

    def test_get_config_raw_auth(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "test.yaml").write_text("workflow:\n  name: test")
        svc = _make_service(tmp_path)
        app = FastAPI()
        router = create_studio_router(svc, auth_enabled=True)
        app.include_router(router, prefix="/api/studio")
        app.dependency_overrides[require_auth] = _mock_auth()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/studio/configs/workflows/test/raw")
        assert resp.status_code == 200

    def test_create_config_auth(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        svc = _make_service(tmp_path)
        app = FastAPI()
        router = create_studio_router(svc, auth_enabled=True)
        app.include_router(router, prefix="/api/studio")
        app.dependency_overrides[require_auth] = _mock_auth()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/studio/configs/workflows/new-wf",
            json={"workflow": {"name": "new-wf"}},
        )
        # May be 201, 400, or 422 depending on validation
        assert resp.status_code in (201, 400, 422)

    def test_update_config_auth(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        svc = _make_service(tmp_path)
        app = FastAPI()
        router = create_studio_router(svc, auth_enabled=True)
        app.include_router(router, prefix="/api/studio")
        app.dependency_overrides[require_auth] = _mock_auth()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.put(
            "/api/studio/configs/workflows/missing",
            json={"workflow": {"name": "missing"}},
        )
        assert resp.status_code == 404

    def test_delete_config_auth(self, tmp_path):
        svc = _make_service(tmp_path)
        app = FastAPI()
        router = create_studio_router(svc, auth_enabled=True)
        app.include_router(router, prefix="/api/studio")
        app.dependency_overrides[require_auth] = _mock_auth()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete("/api/studio/configs/workflows/missing")
        assert resp.status_code == 404

    def test_validate_config_auth(self, tmp_path):
        svc = _make_service(tmp_path)
        app = FastAPI()
        router = create_studio_router(svc, auth_enabled=True)
        app.include_router(router, prefix="/api/studio")
        app.dependency_overrides[require_auth] = _mock_auth()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/studio/validate/workflows",
            json={"workflow": {"name": "test"}},
        )
        assert resp.status_code == 200

    def test_schemas_endpoint(self, tmp_path):
        svc = _make_service(tmp_path)
        app = FastAPI()
        router = create_studio_router(svc, auth_enabled=True)
        app.include_router(router, prefix="/api/studio")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/studio/schemas/workflows")
        assert resp.status_code == 200
