"""Tests for WorkflowRunner library API."""
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.interfaces.server.workflow_runner import (
    WorkflowRunner,
    WorkflowRunnerConfig,
    WorkflowRunResult,
)


class TestWorkflowRunnerConfig:
    """Test WorkflowRunnerConfig defaults and customization."""

    def test_defaults(self) -> None:
        config = WorkflowRunnerConfig()
        assert config.config_root == "configs"
        assert config.workspace is None
        assert config.show_details is False
        assert config.trigger_type == "api"
        assert config.environment == "server"

    def test_custom_values(self) -> None:
        config = WorkflowRunnerConfig(
            config_root="/custom/root",
            workspace="/tmp/ws",
            show_details=True,
            trigger_type="cli",
            environment="test",
        )
        assert config.config_root == "/custom/root"
        assert config.workspace == "/tmp/ws"
        assert config.show_details is True


class TestWorkflowRunResult:
    """Test WorkflowRunResult model."""

    def test_completed_result(self) -> None:
        now = datetime.now(timezone.utc)
        result = WorkflowRunResult(
            workflow_id="wf-123",
            workflow_name="test",
            status="completed",
            result={"output": "hello"},
            started_at=now,
            completed_at=now,
            duration_seconds=1.5,
        )
        assert result.status == "completed"
        assert result.error_message is None
        assert result.result == {"output": "hello"}

    def test_failed_result(self) -> None:
        now = datetime.now(timezone.utc)
        result = WorkflowRunResult(
            workflow_id="",
            workflow_name="broken",
            status="failed",
            error_message="Something went wrong",
            started_at=now,
            completed_at=now,
            duration_seconds=0.1,
        )
        assert result.status == "failed"
        assert result.error_message == "Something went wrong"
        assert result.result is None


class TestWorkflowRunner:
    """Test WorkflowRunner execution."""

    def test_file_not_found_raises(self) -> None:
        runner = WorkflowRunner()
        with pytest.raises(FileNotFoundError):
            runner.run("nonexistent/workflow.yaml")

    @patch("src.interfaces.server.workflow_runner.WorkflowRunner._setup_infrastructure")
    @patch("src.interfaces.server.workflow_runner.WorkflowRunner._compile")
    def test_run_success(self, mock_compile, mock_setup, tmp_path) -> None:
        """Successful run returns completed WorkflowRunResult."""
        # Create a workflow YAML
        wf_file = tmp_path / "test.yaml"
        wf_file.write_text(yaml.dump({
            "workflow": {"name": "test-wf", "stages": []},
        }))

        # Mock infrastructure
        mock_tracker = MagicMock()
        mock_tracker.track_workflow.return_value.__enter__ = MagicMock(return_value="wf-abc")
        mock_tracker.track_workflow.return_value.__exit__ = MagicMock(return_value=False)
        mock_setup.return_value = (MagicMock(), MagicMock(), mock_tracker)

        # Mock compilation
        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {"status": "completed", "output": "ok"}
        mock_engine = MagicMock()
        mock_engine.tool_executor = None
        mock_compile.return_value = (mock_compiled, mock_engine)

        runner = WorkflowRunner(config=WorkflowRunnerConfig(config_root=str(tmp_path)))
        result = runner.run(str(wf_file), input_data={"key": "val"})

        assert result.status == "completed"
        assert result.workflow_name == "test-wf"
        assert result.duration_seconds >= 0

    @patch("src.interfaces.server.workflow_runner.WorkflowRunner._setup_infrastructure")
    @patch("src.interfaces.server.workflow_runner.WorkflowRunner._compile")
    def test_run_with_on_event(self, mock_compile, mock_setup, tmp_path) -> None:
        """on_event callback is subscribed and unsubscribed."""
        wf_file = tmp_path / "test.yaml"
        wf_file.write_text(yaml.dump({
            "workflow": {"name": "test-wf", "stages": []},
        }))

        mock_tracker = MagicMock()
        mock_tracker.track_workflow.return_value.__enter__ = MagicMock(return_value="wf-abc")
        mock_tracker.track_workflow.return_value.__exit__ = MagicMock(return_value=False)
        mock_setup.return_value = (MagicMock(), MagicMock(), mock_tracker)

        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {"status": "completed"}
        mock_engine = MagicMock()
        mock_engine.tool_executor = None
        mock_compile.return_value = (mock_compiled, mock_engine)

        event_bus = MagicMock()
        event_bus.subscribe.return_value = "sub-123"

        callback = MagicMock()
        runner = WorkflowRunner(
            config=WorkflowRunnerConfig(config_root=str(tmp_path)),
            event_bus=event_bus,
        )
        runner.run(str(wf_file), on_event=callback)

        event_bus.subscribe.assert_called_once_with(callback)
        event_bus.unsubscribe.assert_called_once_with("sub-123")

    @patch("src.interfaces.server.workflow_runner.WorkflowRunner._setup_infrastructure")
    def test_compilation_error_returns_failed(self, mock_setup, tmp_path) -> None:
        """Compilation failure returns a failed result (no exception)."""
        wf_file = tmp_path / "test.yaml"
        wf_file.write_text(yaml.dump({
            "workflow": {"name": "bad-wf", "stages": []},
        }))

        mock_setup.side_effect = ValueError("Bad config")

        runner = WorkflowRunner(config=WorkflowRunnerConfig(config_root=str(tmp_path)))
        result = runner.run(str(wf_file))

        assert result.status == "failed"
        assert "Bad config" in result.error_message

    @patch("src.interfaces.server.workflow_runner.WorkflowRunner._setup_infrastructure")
    @patch("src.interfaces.server.workflow_runner.WorkflowRunner._compile")
    def test_engine_cleanup_on_success(self, mock_compile, mock_setup, tmp_path) -> None:
        """Engine cleanup runs even on success."""
        wf_file = tmp_path / "test.yaml"
        wf_file.write_text(yaml.dump({
            "workflow": {"name": "test-wf", "stages": []},
        }))

        mock_tracker = MagicMock()
        mock_tracker.track_workflow.return_value.__enter__ = MagicMock(return_value="wf-1")
        mock_tracker.track_workflow.return_value.__exit__ = MagicMock(return_value=False)
        mock_setup.return_value = (MagicMock(), MagicMock(), mock_tracker)

        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {"status": "completed"}
        mock_engine = MagicMock()
        mock_engine.tool_executor = MagicMock()
        mock_compile.return_value = (mock_compiled, mock_engine)

        runner = WorkflowRunner(config=WorkflowRunnerConfig(config_root=str(tmp_path)))
        runner.run(str(wf_file))

        mock_engine.tool_executor.shutdown.assert_called_once()

    @patch("src.interfaces.server.workflow_runner.WorkflowRunner._setup_infrastructure")
    @patch("src.interfaces.server.workflow_runner.WorkflowRunner._compile")
    def test_workspace_in_state(self, mock_compile, mock_setup, tmp_path) -> None:
        """Workspace is passed through to workflow state."""
        wf_file = tmp_path / "test.yaml"
        wf_file.write_text(yaml.dump({
            "workflow": {"name": "test-wf", "stages": []},
        }))

        mock_tracker = MagicMock()
        mock_tracker.track_workflow.return_value.__enter__ = MagicMock(return_value="wf-1")
        mock_tracker.track_workflow.return_value.__exit__ = MagicMock(return_value=False)
        mock_setup.return_value = (MagicMock(), MagicMock(), mock_tracker)

        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {"status": "completed"}
        mock_engine = MagicMock()
        mock_engine.tool_executor = None
        mock_compile.return_value = (mock_compiled, mock_engine)

        runner = WorkflowRunner(config=WorkflowRunnerConfig(config_root=str(tmp_path)))
        runner.run(str(wf_file), workspace="/safe/dir")

        call_args = mock_compiled.invoke.call_args[0][0]
        assert call_args["workspace_root"] == "/safe/dir"
