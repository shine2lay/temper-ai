"""Tests for server delegation (maf run → server auto-detection)."""
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.interfaces.cli.server_client import MAFServerClient
from src.interfaces.cli.server_delegation import (
    MAX_POLL_SECONDS,
    POLL_INTERVAL,
    _poll_with_progress,
    _save_output,
    delegate_to_server,
    detect_server,
)


# ── is_server_running ────────────────────────────────────────────────


class TestIsServerRunning:
    """Tests for MAFServerClient.is_server_running()."""

    def test_healthy_server_returns_true(self) -> None:
        client = MAFServerClient(base_url="http://localhost:8420")
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.Client") as mock_client_cls:
            mock_http = MagicMock()
            mock_http.__enter__ = MagicMock(return_value=mock_http)
            mock_http.__exit__ = MagicMock(return_value=False)
            mock_http.get.return_value = mock_resp
            mock_client_cls.return_value = mock_http

            assert client.is_server_running() is True
            mock_http.get.assert_called_once_with("/api/health")

    def test_connection_error_returns_false(self) -> None:
        client = MAFServerClient(base_url="http://localhost:8420")

        with patch("httpx.Client") as mock_client_cls:
            mock_http = MagicMock()
            mock_http.__enter__ = MagicMock(return_value=mock_http)
            mock_http.__exit__ = MagicMock(return_value=False)
            mock_http.get.side_effect = httpx.ConnectError("Connection refused")
            mock_client_cls.return_value = mock_http

            assert client.is_server_running() is False

    def test_timeout_returns_false(self) -> None:
        client = MAFServerClient(base_url="http://localhost:8420")

        with patch("httpx.Client") as mock_client_cls:
            mock_http = MagicMock()
            mock_http.__enter__ = MagicMock(return_value=mock_http)
            mock_http.__exit__ = MagicMock(return_value=False)
            mock_http.get.side_effect = httpx.TimeoutException("Timed out")
            mock_client_cls.return_value = mock_http

            assert client.is_server_running() is False


# ── detect_server ────────────────────────────────────────────────────


class TestDetectServer:
    """Tests for detect_server()."""

    def test_returns_client_when_server_found(self) -> None:
        with patch.object(MAFServerClient, "is_server_running", return_value=True):
            result = detect_server("http://localhost:8420")
            assert result is not None
            assert isinstance(result, MAFServerClient)

    def test_returns_none_when_server_not_found(self) -> None:
        with patch.object(MAFServerClient, "is_server_running", return_value=False):
            result = detect_server("http://localhost:8420")
            assert result is None


# ── delegate_to_server ───────────────────────────────────────────────


class TestDelegateToServer:
    """Tests for delegate_to_server()."""

    @patch("src.interfaces.cli.server_delegation._save_output")
    @patch("src.interfaces.cli.server_delegation._poll_with_progress")
    def test_success_flow(
        self, mock_poll: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_client = MagicMock(spec=MAFServerClient)
        mock_client.trigger_run.return_value = {"execution_id": "exec-123"}
        mock_poll.return_value = {"status": "completed"}

        delegate_to_server(
            mock_client, "configs/wf.yaml", {"key": "val"},
            workspace=None, run_id=None, output_file=None, show_details=False,
        )

        mock_client.trigger_run.assert_called_once()
        call_kwargs = mock_client.trigger_run.call_args
        # Verify absolute path was sent
        assert Path(call_kwargs.kwargs["workflow"]).is_absolute()
        mock_poll.assert_called_once_with(mock_client, "exec-123", False)
        mock_save.assert_not_called()

    @patch("src.interfaces.cli.server_delegation._save_output")
    @patch("src.interfaces.cli.server_delegation._poll_with_progress")
    def test_failure_raises_system_exit(
        self, mock_poll: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_client = MagicMock(spec=MAFServerClient)
        mock_client.trigger_run.return_value = {"execution_id": "exec-456"}
        mock_poll.return_value = {"status": "failed", "error_message": "boom"}

        with pytest.raises(SystemExit) as exc_info:
            delegate_to_server(
                mock_client, "configs/wf.yaml", {},
                workspace=None, run_id=None, output_file=None, show_details=False,
            )
        assert exc_info.value.code == 1

    @patch("src.interfaces.cli.server_delegation._save_output")
    @patch("src.interfaces.cli.server_delegation._poll_with_progress")
    def test_resolves_absolute_path(
        self, mock_poll: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_client = MagicMock(spec=MAFServerClient)
        mock_client.trigger_run.return_value = {"execution_id": "exec-789"}
        mock_poll.return_value = {"status": "completed"}

        delegate_to_server(
            mock_client, "relative/path.yaml", {},
            workspace=None, run_id=None, output_file=None, show_details=False,
        )

        call_kwargs = mock_client.trigger_run.call_args
        sent_path = call_kwargs.kwargs["workflow"]
        assert Path(sent_path).is_absolute()

    @patch("src.interfaces.cli.server_delegation._save_output")
    @patch("src.interfaces.cli.server_delegation._poll_with_progress")
    def test_saves_output_when_file_specified(
        self, mock_poll: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_client = MagicMock(spec=MAFServerClient)
        mock_client.trigger_run.return_value = {"execution_id": "exec-out"}
        mock_poll.return_value = {"status": "completed", "result": "data"}

        delegate_to_server(
            mock_client, "configs/wf.yaml", {},
            workspace=None, run_id=None, output_file="/tmp/out.json",
            show_details=False,
        )

        mock_save.assert_called_once_with(
            {"status": "completed", "result": "data"}, "/tmp/out.json"
        )

    @patch("src.interfaces.cli.server_delegation._save_output")
    @patch("src.interfaces.cli.server_delegation._poll_with_progress")
    def test_missing_execution_id_raises_system_exit(
        self, mock_poll: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_client = MagicMock(spec=MAFServerClient)
        mock_client.trigger_run.return_value = {"status": "ok"}  # No execution_id

        with pytest.raises(SystemExit) as exc_info:
            delegate_to_server(
                mock_client, "configs/wf.yaml", {},
                workspace=None, run_id=None, output_file=None, show_details=False,
            )
        assert exc_info.value.code == 1
        mock_poll.assert_not_called()


# ── _poll_with_progress ──────────────────────────────────────────────


class TestPollWithProgress:
    """Tests for _poll_with_progress()."""

    @patch("src.interfaces.cli.server_delegation.time.sleep")
    @patch("src.interfaces.cli.server_delegation.time.monotonic")
    def test_polls_until_complete(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        # Simulate time well within deadline
        mock_monotonic.side_effect = [0, 1, 2, 3, 4]

        mock_client = MagicMock(spec=MAFServerClient)
        mock_client.get_status.side_effect = [
            {"status": "running", "stages": []},
            {"status": "running", "stages": [{"name": "s1", "status": "completed"}]},
            {"status": "completed", "stages": [{"name": "s1", "status": "completed"}]},
        ]

        result = _poll_with_progress(mock_client, "exec-poll", show_details=True)

        assert result["status"] == "completed"
        assert mock_client.get_status.call_count == 3

    @patch("src.interfaces.cli.server_delegation.time.sleep")
    @patch("src.interfaces.cli.server_delegation.time.monotonic")
    def test_shows_stage_transitions_when_detailed(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        mock_monotonic.side_effect = [0, 1, 2, 3]

        mock_client = MagicMock(spec=MAFServerClient)
        mock_client.get_status.side_effect = [
            {
                "status": "running",
                "stages": [{"name": "design", "status": "running"}],
            },
            {
                "status": "completed",
                "stages": [{"name": "design", "status": "completed"}],
            },
        ]

        result = _poll_with_progress(mock_client, "exec-stages", show_details=True)

        assert result["status"] == "completed"

    @patch("src.interfaces.cli.server_delegation.time.sleep")
    @patch("src.interfaces.cli.server_delegation.time.monotonic")
    def test_times_out_after_deadline(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        # First call sets deadline, second call exceeds it
        mock_monotonic.side_effect = [0, MAX_POLL_SECONDS + 1]

        mock_client = MagicMock(spec=MAFServerClient)

        with pytest.raises(SystemExit) as exc_info:
            _poll_with_progress(mock_client, "exec-timeout", show_details=False)
        assert exc_info.value.code == 1
        mock_client.get_status.assert_not_called()


# ── _save_output ─────────────────────────────────────────────────────


class TestSaveOutput:
    """Tests for _save_output()."""

    def test_writes_json_file(self, tmp_path: Path) -> None:
        output_file = str(tmp_path / "subdir" / "result.json")
        status_data = {"status": "completed", "result": {"answer": 42}}

        _save_output(status_data, output_file)

        written = json.loads(Path(output_file).read_text())
        assert written["status"] == "completed"
        assert written["result"]["answer"] == 42

    def test_handles_permission_error(self, capsys: Any) -> None:
        # Writing to /proc should fail with permission error
        _save_output({"status": "ok"}, "/proc/fake/result.json")
        # Should not raise - error is printed to console
        assert not Path("/proc/fake/result.json").exists()
