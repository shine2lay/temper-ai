"""Tests for temper_ai.interfaces.cli.main — CLI entry points."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from temper_ai.interfaces.cli.main import (
    DEFAULT_CONFIG_ROOT,
    DEFAULT_DASHBOARD_PORT,
    DEFAULT_HOST,
    DEFAULT_MAX_WORKERS,
    DEFAULT_SERVER_HOST,
    main,
)


class TestDunderMain:
    def test_module_importable(self):
        """Test that __main__.py can be imported."""
        from temper_ai.interfaces.cli.__main__ import main as main_func

        assert callable(main_func)


class TestConstants:
    def test_default_config_root(self):
        assert DEFAULT_CONFIG_ROOT == "configs"

    def test_default_host(self):
        assert DEFAULT_HOST == "127.0.0.1"

    def test_default_server_host(self):
        assert DEFAULT_SERVER_HOST == "0.0.0.0"

    def test_default_port(self):
        assert DEFAULT_DASHBOARD_PORT == 8420

    def test_default_max_workers(self):
        assert DEFAULT_MAX_WORKERS == 4


class TestMainGroup:
    def test_main_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Temper AI CLI" in result.output

    def test_serve_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "Start Temper AI" in result.output


class TestInitServerApp:
    @patch("temper_ai.interfaces.dashboard.app.create_app")
    @patch("temper_ai.storage.database.engine.get_database_url")
    @patch("temper_ai.observability.tracker.ExecutionTracker.ensure_database")
    def test_success(self, mock_ensure_db, mock_db_url, mock_create_app):
        from temper_ai.interfaces.cli.main import _init_server_app

        mock_db_url.return_value = "sqlite:///test.db"
        mock_create_app.return_value = MagicMock()

        result = _init_server_app("configs", None, 4, True)
        assert result is not None


class TestRunUvicorn:
    @patch("uvicorn.run")
    def test_normal(self, mock_run):
        from temper_ai.interfaces.cli.main import _run_uvicorn

        _run_uvicorn(MagicMock(), "127.0.0.1", 8420, False)
        mock_run.assert_called_once()

    @patch("uvicorn.run", side_effect=KeyboardInterrupt())
    def test_keyboard_interrupt(self, mock_run):
        from temper_ai.interfaces.cli.main import _run_uvicorn

        _run_uvicorn(MagicMock(), "127.0.0.1", 8420, False)


class TestInitServerAppErrors:
    def test_import_error_exits(self):
        """When temper_ai.interfaces.dashboard.app can't be imported, _init_server_app exits."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "temper_ai.interfaces.dashboard.app":
                raise ImportError("no dashboard")
            return original_import(name, *args, **kwargs)

        from temper_ai.interfaces.cli.main import _init_server_app

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(SystemExit) as exc_info:
                _init_server_app("configs", None, 4, True)
            assert exc_info.value.code == 1

    @patch("temper_ai.interfaces.dashboard.app.create_app")
    @patch(
        "temper_ai.storage.database.engine.get_database_url",
        return_value="sqlite:///test.db",
    )
    @patch(
        "temper_ai.observability.tracker.ExecutionTracker.ensure_database",
        side_effect=RuntimeError("db down"),
    )
    def test_db_error_exits(self, mock_ensure_db, mock_db_url, mock_create_app):
        from temper_ai.interfaces.cli.main import _init_server_app

        with pytest.raises(SystemExit) as exc_info:
            _init_server_app("configs", None, 4, True)
        assert exc_info.value.code == 1

    @patch("temper_ai.interfaces.dashboard.app.create_app")
    @patch(
        "temper_ai.storage.database.engine.get_database_url",
        return_value="sqlite:///test.db",
    )
    @patch("temper_ai.observability.tracker.ExecutionTracker.ensure_database")
    def test_with_explicit_db(self, mock_ensure_db, mock_db_url, mock_create_app):
        from temper_ai.interfaces.cli.main import _init_server_app

        mock_create_app.return_value = MagicMock()

        result = _init_server_app("configs", "sqlite:///explicit.db", 4, False)
        assert result is not None
        # When explicit db is given, get_database_url is NOT used as the fallback
        mock_ensure_db.assert_called_once_with("sqlite:///explicit.db")


class TestServeCommand:
    @patch("temper_ai.interfaces.cli.main._run_uvicorn")
    @patch("temper_ai.interfaces.cli.main._init_server_app")
    def test_serve_default(self, mock_init, mock_run_uvicorn):
        mock_init.return_value = MagicMock()

        runner = CliRunner()
        result = runner.invoke(main, ["serve"])
        assert result.exit_code == 0
        mock_init.assert_called_once()
        mock_run_uvicorn.assert_called_once()

    @patch("temper_ai.interfaces.cli.main._run_uvicorn")
    @patch("temper_ai.interfaces.cli.main._init_server_app")
    def test_serve_with_dev(self, mock_init, mock_run_uvicorn):
        mock_init.return_value = MagicMock()

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--dev"])
        assert result.exit_code == 0
        # dev=True is passed to _init_server_app
        call_kwargs = mock_init.call_args
        assert call_kwargs[0][3] is True  # dev arg

    @patch("temper_ai.interfaces.cli.main._run_uvicorn")
    @patch("temper_ai.interfaces.cli.main._init_server_app")
    @patch("temper_ai.interfaces.cli.main._start_mcp_thread")
    def test_serve_with_mcp(self, mock_mcp, mock_init, mock_run_uvicorn):
        mock_init.return_value = MagicMock()

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--mcp"])
        assert result.exit_code == 0
        mock_mcp.assert_called_once()

    @patch("temper_ai.interfaces.cli.main._run_uvicorn")
    @patch("temper_ai.interfaces.cli.main._init_server_app")
    def test_serve_with_host_0000(self, mock_init, mock_run_uvicorn):
        mock_init.return_value = MagicMock()

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--host", "0.0.0.0"])
        assert result.exit_code == 0
        assert "0.0.0.0" in result.output or "Warning" in result.output

    @patch("temper_ai.interfaces.cli.main._run_uvicorn")
    @patch("temper_ai.interfaces.cli.main._init_server_app")
    def test_serve_custom_port(self, mock_init, mock_run_uvicorn):
        mock_init.return_value = MagicMock()

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--port", "9999"])
        assert result.exit_code == 0
        # _run_uvicorn called with port=9999
        call_args = mock_run_uvicorn.call_args
        assert call_args[0][2] == 9999

    @patch("temper_ai.interfaces.cli.main._run_uvicorn")
    @patch("temper_ai.interfaces.cli.main._init_server_app")
    def test_serve_custom_config_root(self, mock_init, mock_run_uvicorn):
        mock_init.return_value = MagicMock()

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--config-root", "/tmp/my-configs"])
        assert result.exit_code == 0
        call_args = mock_init.call_args
        assert call_args[0][0] == "/tmp/my-configs"


class TestStartMcpThread:
    @patch("temper_ai.mcp.server.create_mcp_server")
    def test_starts_thread(self, mock_create_mcp):
        from temper_ai.interfaces.cli.main import _start_mcp_thread

        mock_mcp = MagicMock()
        mock_create_mcp.return_value = mock_mcp

        app = MagicMock()
        app.state.execution_service = MagicMock()

        _start_mcp_thread("configs", app)
        mock_create_mcp.assert_called_once()
