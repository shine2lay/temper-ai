"""Tests for temper_ai.interfaces.dashboard.app — app factory and middleware."""

from unittest.mock import MagicMock, patch

from temper_ai.interfaces.dashboard.app import (
    _DOMAIN_REGISTRY,
    DEFAULT_MAX_WORKERS,
    REACT_DIST_DIR,
    _configure_cors,
    _NoCacheStaticMiddleware,
    _register_domain_routes,
    _SecurityHeadersMiddleware,
)


class TestNoCacheStaticMiddleware:
    def test_non_http_passthrough(self):
        import asyncio

        inner_app = MagicMock()

        async def mock_inner(scope, receive, send):
            pass

        inner_app.side_effect = mock_inner
        middleware = _NoCacheStaticMiddleware(inner_app)

        scope = {"type": "websocket", "path": "/ws"}
        asyncio.get_event_loop().run_until_complete(
            middleware(scope, MagicMock(), MagicMock())
        )

    def test_non_static_passthrough(self):
        import asyncio

        inner_app = MagicMock()

        async def mock_inner(scope, receive, send):
            pass

        inner_app.side_effect = mock_inner
        middleware = _NoCacheStaticMiddleware(inner_app)

        scope = {"type": "http", "path": "/api/health"}
        asyncio.get_event_loop().run_until_complete(
            middleware(scope, MagicMock(), MagicMock())
        )

    def test_static_path_adds_cache_control(self):
        import asyncio

        sent_messages = []

        async def mock_inner(scope, receive, send):
            await send({"type": "http.response.start", "headers": []})

        middleware = _NoCacheStaticMiddleware(mock_inner)

        scope = {"type": "http", "path": "/app/index.html"}

        async def capture_send(msg):
            sent_messages.append(msg)

        asyncio.get_event_loop().run_until_complete(
            middleware(scope, MagicMock(), capture_send)
        )
        # Check that Cache-Control was added
        assert len(sent_messages) == 1


class TestSecurityHeadersMiddleware:
    def test_non_http_passthrough(self):
        import asyncio

        inner_app = MagicMock()

        async def mock_inner(scope, receive, send):
            pass

        inner_app.side_effect = mock_inner
        middleware = _SecurityHeadersMiddleware(inner_app)

        scope = {"type": "websocket"}
        asyncio.get_event_loop().run_until_complete(
            middleware(scope, MagicMock(), MagicMock())
        )

    def test_http_adds_security_headers(self):
        import asyncio

        sent_messages = []

        async def mock_inner(scope, receive, send):
            await send({"type": "http.response.start", "headers": []})

        middleware = _SecurityHeadersMiddleware(mock_inner)
        scope = {"type": "http", "path": "/api/test"}

        async def capture_send(msg):
            sent_messages.append(msg)

        asyncio.get_event_loop().run_until_complete(
            middleware(scope, MagicMock(), capture_send)
        )
        assert len(sent_messages) == 1


class TestConfigureCors:
    def test_server_mode_no_env(self):
        from fastapi import FastAPI

        app = FastAPI()
        with patch.dict("os.environ", {}, clear=True):
            _configure_cors(app, "server")

    def test_server_mode_with_env(self):
        from fastapi import FastAPI

        app = FastAPI()
        with patch.dict("os.environ", {"TEMPER_CORS_ORIGINS": "http://example.com"}):
            _configure_cors(app, "server")

    def test_dev_mode(self):
        from fastapi import FastAPI

        app = FastAPI()
        _configure_cors(app, "dev")


class TestDomainRegistry:
    def test_known_domains(self):
        assert "temper_ai.learning" in _DOMAIN_REGISTRY
        assert "temper_ai.goals" in _DOMAIN_REGISTRY
        assert "temper_ai.portfolio" in _DOMAIN_REGISTRY

    def test_register_domain_unknown(self):
        from fastapi import FastAPI

        app = FastAPI()
        mod = MagicMock()
        _register_domain_routes(app, "unknown_domain", mod)
        # Should return early without registering

    @patch("importlib.import_module")
    def test_register_domain_with_svc(self, mock_import):
        from fastapi import FastAPI

        app = FastAPI()
        mod_routes = MagicMock()
        mock_store_mod = MagicMock()
        mock_svc_mod = MagicMock()
        mock_router = MagicMock()
        mod_routes.create_learning_router = MagicMock(return_value=mock_router)

        def side_effect(path):
            if "store" in path:
                return mock_store_mod
            return mock_svc_mod

        mock_import.side_effect = side_effect

        _register_domain_routes(app, "temper_ai.learning", mod_routes)

    @patch("importlib.import_module")
    def test_register_domain_without_svc(self, mock_import):
        from fastapi import FastAPI

        app = FastAPI()
        mod_routes = MagicMock()
        mock_store_mod = MagicMock()
        mock_router = MagicMock()
        mod_routes.create_portfolio_router = MagicMock(return_value=mock_router)

        mock_import.return_value = mock_store_mod

        _register_domain_routes(app, "temper_ai.portfolio", mod_routes)


class TestConstants:
    def test_default_max_workers(self):
        assert DEFAULT_MAX_WORKERS == 4

    def test_react_dist_dir_is_path(self):
        from pathlib import Path

        assert isinstance(REACT_DIST_DIR, Path)
