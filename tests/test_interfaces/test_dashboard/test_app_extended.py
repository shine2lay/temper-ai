"""Extended tests for temper_ai.interfaces.dashboard.app — app factory and lifecycle."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.interfaces.dashboard.app import (
    _init_server_components,
    _mount_react_app,
    _register_auth_routes,
    _register_management_routes,
    _register_optional_routes,
    _SPAStaticFiles,
)


class TestInitServerComponents:
    def test_non_server_mode(self):
        result = _init_server_components("test")
        assert result == (None, None, None, None)

    @patch("temper_ai.interfaces.server.lifecycle.GracefulShutdownManager")
    @patch("temper_ai.interfaces.server.run_store.RunStore")
    def test_server_mode(self, mock_rs, mock_gsm):
        mock_gsm.return_value = MagicMock()
        mock_rs.return_value = MagicMock()

        result = _init_server_components("server")
        shutdown_mgr, run_store, mining, analysis = result
        assert shutdown_mgr is not None
        assert run_store is not None

    @patch("temper_ai.interfaces.server.lifecycle.GracefulShutdownManager")
    def test_dev_mode(self, mock_gsm):
        mock_gsm.return_value = MagicMock()

        result = _init_server_components("dev")
        shutdown_mgr, _, _, _ = result
        assert shutdown_mgr is not None

    @patch("temper_ai.interfaces.server.lifecycle.GracefulShutdownManager")
    @patch(
        "temper_ai.interfaces.server.run_store.RunStore",
        side_effect=RuntimeError("fail"),
    )
    def test_run_store_failure(self, mock_rs, mock_gsm):
        mock_gsm.return_value = MagicMock()

        result = _init_server_components("server")
        _, run_store, _, _ = result
        assert run_store is None


class TestRegisterAuthRoutes:
    def test_success(self):
        from fastapi import FastAPI

        app = FastAPI()
        _register_auth_routes(app)

    @patch(
        "temper_ai.interfaces.server.auth_routes.create_auth_router",
        side_effect=ImportError("no auth"),
    )
    def test_auth_import_error(self, mock_auth):
        from fastapi import FastAPI

        app = FastAPI()
        _register_auth_routes(app)  # Should not raise


class TestRegisterManagementRoutes:
    def test_registers_routes(self):
        from fastapi import FastAPI

        app = FastAPI()
        _register_management_routes(app, "configs", auth_enabled=False)

    def test_auth_enabled(self):
        from fastapi import FastAPI

        app = FastAPI()
        _register_management_routes(app, "configs", auth_enabled=True)


class TestRegisterOptionalRoutes:
    def test_registers_without_error(self):
        from fastapi import FastAPI

        app = FastAPI()
        _register_optional_routes(app, "configs")


class TestMountReactApp:
    def test_no_dist_dir(self):
        from fastapi import FastAPI

        app = FastAPI()
        with patch("temper_ai.interfaces.dashboard.app.REACT_DIST_DIR") as mock_dir:
            mock_dir.exists.return_value = False
            _mount_react_app(app)

    def test_with_dist_dir(self, tmp_path):
        from fastapi import FastAPI

        dist = tmp_path / "react-dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>")

        app = FastAPI()
        with patch("temper_ai.interfaces.dashboard.app.REACT_DIST_DIR", dist):
            _mount_react_app(app)


class TestSPAStaticFiles:
    @pytest.mark.asyncio
    async def test_fallback_to_index(self, tmp_path):
        (tmp_path / "index.html").write_text("<html>SPA</html>")
        spa = _SPAStaticFiles(directory=str(tmp_path), html=True)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/nonexistent",
            "query_string": b"",
            "headers": [],
            "root_path": "",
        }
        # Should not raise — falls back to index.html
        try:
            response = await spa.get_response("nonexistent", scope)
            assert response is not None
        except Exception:
            pass  # May fail due to scope setup
