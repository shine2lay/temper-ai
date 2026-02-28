"""Extended tests for temper_ai.interfaces.cli.server_client — cover edge cases."""

from unittest.mock import MagicMock, patch

from temper_ai.interfaces.cli.server_client import MAFServerClient


class TestIsServerRunning:
    @patch("httpx.Client")
    def test_server_not_running(self, mock_client_cls):
        import httpx

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")
        mock_client_cls.return_value = mock_client

        client = MAFServerClient()
        assert client.is_server_running() is False

    @patch("httpx.Client")
    def test_server_timeout(self, mock_client_cls):
        import httpx

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_cls.return_value = mock_client

        client = MAFServerClient()
        assert client.is_server_running() is False


class TestTriggerRunEdgeCases:
    @patch("httpx.Client")
    def test_with_all_params(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"execution_id": "e1"}
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        client = MAFServerClient(api_key="test-key")
        result = client.trigger_run(
            workflow="test.yaml",
            inputs={"key": "val"},
            workspace="/tmp",
            run_id="custom-id",
        )
        assert result["execution_id"] == "e1"

    @patch("httpx.Client")
    def test_with_no_optional_params(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"execution_id": "e2"}
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        client = MAFServerClient()
        result = client.trigger_run(workflow="test.yaml")
        assert result["execution_id"] == "e2"


class TestListRunsEdgeCases:
    @patch("httpx.Client")
    def test_list_with_status_filter(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"runs": [], "total": 0}
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        client = MAFServerClient()
        result = client.list_runs(status="completed")
        assert result["total"] == 0
