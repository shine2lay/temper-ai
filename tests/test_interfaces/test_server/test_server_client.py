"""Tests for MAFServerClient and CLI trigger/status/logs commands."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from temper_ai.interfaces.cli.server_client import DEFAULT_SERVER_URL, MAFServerClient


class TestMAFServerClient:
    """Test HTTP client methods."""

    def test_default_url(self) -> None:
        client = MAFServerClient()
        assert client.base_url == DEFAULT_SERVER_URL

    def test_custom_url(self) -> None:
        client = MAFServerClient(base_url="http://localhost:9999")
        assert client.base_url == "http://localhost:9999"

    def test_api_key_header(self) -> None:
        client = MAFServerClient(api_key="secret-key")
        headers = client._headers()
        assert headers["X-API-Key"] == "secret-key"

    def test_no_api_key_header(self) -> None:
        client = MAFServerClient()
        headers = client._headers()
        assert "X-API-Key" not in headers

    @patch("temper_ai.interfaces.cli.server_client.httpx.Client")
    def test_health_check(self, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "healthy"}
        mock_client.get.return_value = mock_resp

        client = MAFServerClient()
        result = client.health_check()
        assert result["status"] == "healthy"
        mock_client.get.assert_called_once_with("/api/health")

    @patch("temper_ai.interfaces.cli.server_client.httpx.Client")
    def test_trigger_run(self, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"execution_id": "exec-123", "status": "pending"}
        mock_client.post.return_value = mock_resp

        client = MAFServerClient()
        result = client.trigger_run("workflows/test.yaml", inputs={"key": "val"})
        assert result["execution_id"] == "exec-123"

    @patch("temper_ai.interfaces.cli.server_client.httpx.Client")
    def test_get_status(self, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"execution_id": "exec-1", "status": "completed"}
        mock_client.get.return_value = mock_resp

        client = MAFServerClient()
        result = client.get_status("exec-1")
        assert result["status"] == "completed"

    @patch("temper_ai.interfaces.cli.server_client.httpx.Client")
    def test_list_runs(self, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"runs": [], "total": 0}
        mock_client.get.return_value = mock_resp

        client = MAFServerClient()
        result = client.list_runs(status="completed", limit=10)
        assert result["total"] == 0

    @patch("temper_ai.interfaces.cli.server_client.httpx.Client")
    def test_cancel_run(self, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "cancelled", "execution_id": "exec-1"}
        mock_client.post.return_value = mock_resp

        client = MAFServerClient()
        result = client.cancel_run("exec-1")
        assert result["status"] == "cancelled"


class TestCLICommands:
    """Test CLI help output for trigger/status/logs commands."""

    def test_trigger_help(self) -> None:
        from click.testing import CliRunner

        from temper_ai.interfaces.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["trigger", "--help"])
        assert result.exit_code == 0
        assert "--server" in result.output
        assert "--api-key" in result.output
        assert "--wait" in result.output
        assert "--workspace" in result.output

    def test_status_help(self) -> None:
        from click.testing import CliRunner

        from temper_ai.interfaces.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0
        assert "--server" in result.output
        assert "--api-key" in result.output
        assert "--all" in result.output

    def test_logs_help(self) -> None:
        from click.testing import CliRunner

        from temper_ai.interfaces.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["logs", "--help"])
        assert result.exit_code == 0
        assert "--server" in result.output
        assert "--api-key" in result.output
        assert "--follow" in result.output
