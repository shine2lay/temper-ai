"""Tests for CLI rollback commands (src/cli/rollback.py).

Tests cover:
- rollback command group and subcommands
- list command: snapshot filtering, output formatting
- info command: snapshot details, safety validation
- execute command: dry-run, confirmation, safety checks
- history command: rollback execution history
- Error handling and exit codes
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from src.cli.rollback import execute, history, info, list, rollback
from src.safety.rollback import RollbackSnapshot, RollbackStatus


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_snapshot():
    """Create a mock rollback snapshot."""
    return RollbackSnapshot(
        id="snap-123",
        action={"tool": "write_file", "path": "/tmp/test.txt"},
        context={"workflow_id": "wf-456", "agent_id": "agent-789"},
        created_at=datetime.now(UTC) - timedelta(hours=2),
        file_snapshots={"/tmp/test.txt": "old content"},
        state_snapshots={"key1": "value1"},
        metadata={"operator": "test_user"},
    )


@pytest.fixture
def mock_rollback_result():
    """Create a mock rollback result."""
    result = Mock()
    result.success = True
    result.status = RollbackStatus.COMPLETED
    result.reverted_items = ["file:/tmp/test.txt"]
    result.failed_items = []
    result.errors = []
    result.completed_at = datetime.now(UTC)
    result.metadata = {"operator": "test_user", "reason": "Test rollback"}
    return result


class TestRollbackGroup:
    """Test the rollback command group."""

    def test_rollback_help(self, runner):
        """Test rollback group help message."""
        result = runner.invoke(rollback, ["--help"])
        assert result.exit_code == 0
        assert "Rollback operations" in result.output

    def test_rollback_no_command(self, runner):
        """Test rollback without subcommand shows usage."""
        result = runner.invoke(rollback, [])
        # Click returns 0 for group help, or 2 for missing command
        assert result.exit_code in [0, 2]
        assert "Usage:" in result.output or "Commands:" in result.output


class TestListCommand:
    """Test the list subcommand."""

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_list_snapshots_success(self, mock_api_cls, mock_manager_cls, runner, mock_snapshot):
        """Test successful snapshot listing."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["list_snapshots"])
        mock_api.list_snapshots.return_value = [mock_snapshot]
        mock_api_cls.return_value = mock_api

        result = runner.invoke(list, [])
        assert result.exit_code == 0
        assert "snap-123" in result.output
        assert "write_file" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_list_snapshots_empty(self, mock_api_cls, mock_manager_cls, runner):
        """Test listing when no snapshots found."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["list_snapshots"])
        mock_api.list_snapshots.return_value = []
        mock_api_cls.return_value = mock_api

        result = runner.invoke(list, [])
        assert result.exit_code == 0
        assert "No snapshots found" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_list_snapshots_with_workflow_filter(self, mock_api_cls, mock_manager_cls, runner, mock_snapshot):
        """Test snapshot listing with workflow_id filter."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["list_snapshots"])
        mock_api.list_snapshots.return_value = [mock_snapshot]
        mock_api_cls.return_value = mock_api

        result = runner.invoke(list, ["--workflow-id", "wf-456"])
        assert result.exit_code == 0
        mock_api.list_snapshots.assert_called_once()
        call_kwargs = mock_api.list_snapshots.call_args[1]
        assert call_kwargs["workflow_id"] == "wf-456"

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_list_snapshots_with_since_hours(self, mock_api_cls, mock_manager_cls, runner, mock_snapshot):
        """Test snapshot listing with since_hours filter."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["list_snapshots"])
        mock_api.list_snapshots.return_value = [mock_snapshot]
        mock_api_cls.return_value = mock_api

        result = runner.invoke(list, ["--since-hours", "24"])
        assert result.exit_code == 0
        call_kwargs = mock_api.list_snapshots.call_args[1]
        assert call_kwargs["since"] is not None

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_list_snapshots_with_limit(self, mock_api_cls, mock_manager_cls, runner, mock_snapshot):
        """Test snapshot listing with custom limit."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["list_snapshots"])
        mock_api.list_snapshots.return_value = [mock_snapshot]
        mock_api_cls.return_value = mock_api

        result = runner.invoke(list, ["--limit", "5"])
        assert result.exit_code == 0
        call_kwargs = mock_api.list_snapshots.call_args[1]
        assert call_kwargs["limit"] == 5

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_list_snapshots_error(self, mock_api_cls, mock_manager_cls, runner):
        """Test error handling in list command."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["list_snapshots"])
        mock_api.list_snapshots.side_effect = Exception("Database error")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(list, [])
        assert result.exit_code != 0
        assert "Error listing snapshots" in result.output


class TestInfoCommand:
    """Test the info subcommand."""

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_info_success(self, mock_api_cls, mock_manager_cls, runner):
        """Test successful snapshot info retrieval."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["get_snapshot_details", "validate_rollback_safety"])
        mock_api.get_snapshot_details.return_value = {
            "id": "snap-123",
            "created_at": datetime.now(UTC).isoformat(),
            "age_hours": 2.5,
            "file_count": 1,
            "files": ["/tmp/test.txt"],
            "state_keys": ["key1"],
        }
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api_cls.return_value = mock_api

        result = runner.invoke(info, ["snap-123"])
        assert result.exit_code == 0
        assert "snap-123" in result.output
        assert "No safety warnings" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_info_not_found(self, mock_api_cls, mock_manager_cls, runner):
        """Test info command with nonexistent snapshot."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["get_snapshot_details", "validate_rollback_safety"])
        mock_api.get_snapshot_details.return_value = None
        mock_api_cls.return_value = mock_api

        result = runner.invoke(info, ["snap-nonexistent"])
        assert result.exit_code != 0
        assert "Snapshot not found" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_info_with_warnings(self, mock_api_cls, mock_manager_cls, runner):
        """Test info command with safety warnings."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["get_snapshot_details", "validate_rollback_safety"])
        mock_api.get_snapshot_details.return_value = {
            "id": "snap-123",
            "created_at": datetime.now(UTC).isoformat(),
            "age_hours": 2.5,
            "file_count": 1,
            "files": ["/tmp/test.txt"],
        }
        mock_api.validate_rollback_safety.return_value = (True, ["Warning: Old snapshot"])
        mock_api_cls.return_value = mock_api

        result = runner.invoke(info, ["snap-123"])
        assert result.exit_code == 0
        assert "Warnings:" in result.output
        assert "Old snapshot" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_info_error(self, mock_api_cls, mock_manager_cls, runner):
        """Test error handling in info command."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["get_snapshot_details"])
        mock_api.get_snapshot_details.side_effect = Exception("Database error")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(info, ["snap-123"])
        assert result.exit_code != 0
        assert "Error getting snapshot info" in result.output


class TestExecuteCommand:
    """Test the execute subcommand."""

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_dry_run(self, mock_api_cls, mock_manager_cls, runner, mock_rollback_result):
        """Test execute command with dry-run flag."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "execute_manual_rollback"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.execute_manual_rollback.return_value = mock_rollback_result
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
            "--dry-run",
        ])
        assert result.exit_code == 0
        assert "Dry run mode" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_safety_check_failed(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with failed safety check."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety"])
        mock_api.validate_rollback_safety.return_value = (False, ["Critical error"])
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ])
        assert result.exit_code != 0
        assert "Safety check failed" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_with_force(self, mock_api_cls, mock_manager_cls, runner, mock_rollback_result):
        """Test execute command with --force flag to bypass safety checks."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details", "execute_manual_rollback"])
        mock_api.validate_rollback_safety.return_value = (False, ["Critical error"])
        mock_api.get_snapshot_details.return_value = {"file_count": 1}
        mock_api.execute_manual_rollback.return_value = mock_rollback_result
        mock_api_cls.return_value = mock_api

        # With force flag, should not prompt for confirmation
        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
            "--force",
        ])
        assert result.exit_code == 0
        assert "Rollback completed" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_user_cancels(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command when user cancels confirmation."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.get_snapshot_details.return_value = {"file_count": 1}
        mock_api_cls.return_value = mock_api

        # Simulate user declining confirmation
        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ], input="n\n")
        assert result.exit_code == 0
        assert "Rollback cancelled" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_success(self, mock_api_cls, mock_manager_cls, runner, mock_rollback_result):
        """Test successful rollback execution."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details", "execute_manual_rollback"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.get_snapshot_details.return_value = {"file_count": 1}
        mock_api.execute_manual_rollback.return_value = mock_rollback_result
        mock_api_cls.return_value = mock_api

        # Simulate user confirming
        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ], input="y\n")
        assert result.exit_code == 0
        assert "Rollback completed" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_failure(self, mock_api_cls, mock_manager_cls, runner):
        """Test rollback execution failure."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_result = Mock()
        mock_result.success = False
        mock_result.status = RollbackStatus.FAILED
        mock_result.errors = ["File not found"]
        mock_result.reverted_items = []
        mock_result.failed_items = ["/tmp/test.txt"]

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details", "execute_manual_rollback"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.get_snapshot_details.return_value = {"file_count": 1}
        mock_api.execute_manual_rollback.return_value = mock_result
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ], input="y\n")
        assert result.exit_code != 0
        assert "Rollback failed" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_value_error(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with ValueError."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety"])
        mock_api.validate_rollback_safety.side_effect = ValueError("Invalid snapshot ID")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
            "--dry-run",
        ])
        assert result.exit_code != 0

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_manager_initialization_error(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with manager initialization error."""
        mock_manager_cls.side_effect = RuntimeError("Failed to initialize manager")

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ])
        assert result.exit_code != 0
        assert "Failed to initialize" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_io_error_on_safety_check(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with IO error during safety check."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety"])
        mock_api.validate_rollback_safety.side_effect = IOError("Cannot read snapshot file")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ])
        assert result.exit_code != 0
        assert "Error reading snapshot" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_value_error_on_snapshot_details(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with ValueError when getting snapshot details."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.get_snapshot_details.side_effect = ValueError("Invalid snapshot")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ])
        assert result.exit_code != 0
        assert "Invalid snapshot" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_io_error_on_snapshot_details(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with IOError when getting snapshot details."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.get_snapshot_details.side_effect = IOError("Cannot read snapshot")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ])
        assert result.exit_code != 0

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_value_error_on_execution(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with ValueError during execution."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details", "execute_manual_rollback"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.get_snapshot_details.return_value = {"file_count": 1}
        mock_api.execute_manual_rollback.side_effect = ValueError("Invalid parameters")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ], input="y\n")
        assert result.exit_code != 0
        assert "Invalid rollback parameters" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_io_error_on_execution(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with IOError during execution."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details", "execute_manual_rollback"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.get_snapshot_details.return_value = {"file_count": 1}
        mock_api.execute_manual_rollback.side_effect = IOError("File system error")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ], input="y\n")
        assert result.exit_code != 0
        assert "File system error" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_permission_error_on_execution(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with PermissionError during execution."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details", "execute_manual_rollback"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.get_snapshot_details.return_value = {"file_count": 1}
        mock_api.execute_manual_rollback.side_effect = PermissionError("Permission denied")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ], input="y\n")
        assert result.exit_code != 0
        assert "File system error" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_execute_runtime_error_on_execution(self, mock_api_cls, mock_manager_cls, runner):
        """Test execute command with RuntimeError during execution."""
        mock_manager = Mock(spec=["execute_rollback"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["validate_rollback_safety", "get_snapshot_details", "execute_manual_rollback"])
        mock_api.validate_rollback_safety.return_value = (True, [])
        mock_api.get_snapshot_details.return_value = {"file_count": 1}
        mock_api.execute_manual_rollback.side_effect = RuntimeError("Execution failed")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(execute, [
            "snap-123",
            "--reason", "Test",
            "--operator", "alice",
        ], input="y\n")
        assert result.exit_code != 0
        assert "Rollback execution error" in result.output


class TestHistoryCommand:
    """Test the history subcommand."""

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_history_success(self, mock_api_cls, mock_manager_cls, runner, mock_rollback_result):
        """Test successful rollback history retrieval."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["get_rollback_history"])
        mock_api.get_rollback_history.return_value = [mock_rollback_result]
        mock_api_cls.return_value = mock_api

        result = runner.invoke(history, [])
        assert result.exit_code == 0
        assert "Rollback history" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_history_empty(self, mock_api_cls, mock_manager_cls, runner):
        """Test history command with no results."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["get_rollback_history"])
        mock_api.get_rollback_history.return_value = []
        mock_api_cls.return_value = mock_api

        result = runner.invoke(history, [])
        assert result.exit_code == 0
        assert "No rollback history found" in result.output

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_history_with_snapshot_filter(self, mock_api_cls, mock_manager_cls, runner, mock_rollback_result):
        """Test history command with snapshot_id filter."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["get_rollback_history"])
        mock_api.get_rollback_history.return_value = [mock_rollback_result]
        mock_api_cls.return_value = mock_api

        result = runner.invoke(history, ["--snapshot-id", "snap-123"])
        assert result.exit_code == 0
        call_kwargs = mock_api.get_rollback_history.call_args[1]
        assert call_kwargs["snapshot_id"] == "snap-123"

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_history_with_limit(self, mock_api_cls, mock_manager_cls, runner, mock_rollback_result):
        """Test history command with custom limit."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["get_rollback_history"])
        mock_api.get_rollback_history.return_value = [mock_rollback_result]
        mock_api_cls.return_value = mock_api

        result = runner.invoke(history, ["--limit", "5"])
        assert result.exit_code == 0
        call_kwargs = mock_api.get_rollback_history.call_args[1]
        assert call_kwargs["limit"] == 5

    @patch("src.cli.rollback.RollbackManager")
    @patch("src.cli.rollback.RollbackAPI")
    def test_history_error(self, mock_api_cls, mock_manager_cls, runner):
        """Test error handling in history command."""
        mock_manager = Mock(spec=["list_snapshots"])
        mock_manager_cls.return_value = mock_manager

        mock_api = Mock(spec=["get_rollback_history"])
        mock_api.get_rollback_history.side_effect = Exception("Database error")
        mock_api_cls.return_value = mock_api

        result = runner.invoke(history, [])
        assert result.exit_code != 0
        assert "Error getting rollback history" in result.output
