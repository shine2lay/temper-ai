"""Tests for WorkflowRunner library API."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.interfaces.server.workflow_runner import (
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
        now = datetime.now(UTC)
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
        now = datetime.now(UTC)
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

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_run_success(self, mock_rt_class, tmp_path) -> None:
        """Successful run returns completed WorkflowRunResult."""
        mock_rt = MagicMock()
        mock_rt.run_pipeline.return_value = {
            "workflow_id": "wf-abc",
            "workflow_name": "test-wf",
            "status": "completed",
            "output": "ok",
        }
        mock_rt_class.return_value = mock_rt

        runner = WorkflowRunner(config=WorkflowRunnerConfig(config_root=str(tmp_path)))
        result = runner.run("test.yaml", input_data={"key": "val"})

        assert result.status == "completed"
        assert result.workflow_name == "test-wf"
        assert result.duration_seconds >= 0
        mock_rt.run_pipeline.assert_called_once()

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_run_with_on_event(self, mock_rt_class, tmp_path) -> None:
        """on_event callback is subscribed and unsubscribed."""
        mock_rt = MagicMock()
        mock_rt.run_pipeline.return_value = {
            "workflow_id": "wf-abc",
            "workflow_name": "test-wf",
            "status": "completed",
        }
        mock_rt_class.return_value = mock_rt

        event_bus = MagicMock()
        event_bus.subscribe.return_value = "sub-123"

        callback = MagicMock()
        runner = WorkflowRunner(
            config=WorkflowRunnerConfig(config_root=str(tmp_path)),
            event_bus=event_bus,
        )
        runner.run("test.yaml", on_event=callback)

        event_bus.subscribe.assert_called_once_with(callback)
        event_bus.unsubscribe.assert_called_once_with("sub-123")

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_pipeline_error_returns_failed(self, mock_rt_class, tmp_path) -> None:
        """Pipeline failure returns a failed result (no exception)."""
        mock_rt = MagicMock()
        mock_rt.run_pipeline.side_effect = ValueError("Bad config")
        mock_rt_class.return_value = mock_rt

        runner = WorkflowRunner(config=WorkflowRunnerConfig(config_root=str(tmp_path)))
        result = runner.run("test.yaml")

        assert result.status == "failed"
        assert "Bad config" in result.error_message

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_cleanup_handled_by_pipeline(self, mock_rt_class, tmp_path) -> None:
        """Engine cleanup is handled internally by run_pipeline."""
        mock_rt = MagicMock()
        mock_rt.run_pipeline.return_value = {
            "workflow_id": "wf-1",
            "workflow_name": "test-wf",
            "status": "completed",
        }
        mock_rt_class.return_value = mock_rt

        runner = WorkflowRunner(config=WorkflowRunnerConfig(config_root=str(tmp_path)))
        result = runner.run("test.yaml")

        assert result.status == "completed"
        # run_pipeline handles cleanup internally; no external cleanup call needed

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_workspace_passed_to_pipeline(self, mock_rt_class, tmp_path) -> None:
        """Workspace is passed through to run_pipeline."""
        mock_rt = MagicMock()
        mock_rt.run_pipeline.return_value = {
            "workflow_id": "wf-1",
            "workflow_name": "test-wf",
            "status": "completed",
        }
        mock_rt_class.return_value = mock_rt

        runner = WorkflowRunner(config=WorkflowRunnerConfig(config_root=str(tmp_path)))
        runner.run("test.yaml", workspace="/safe/dir")

        call_kwargs = mock_rt.run_pipeline.call_args[1]
        assert call_kwargs["workspace"] == "/safe/dir"

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_run_pipeline_called_with_correct_args(
        self, mock_rt_class, tmp_path
    ) -> None:
        """run_pipeline receives correct workflow_path and input_data."""
        mock_rt = MagicMock()
        mock_rt.run_pipeline.return_value = {
            "workflow_id": "wf-1",
            "workflow_name": "test-wf",
            "status": "completed",
        }
        mock_rt_class.return_value = mock_rt

        runner = WorkflowRunner(config=WorkflowRunnerConfig(config_root=str(tmp_path)))
        runner.run("my_workflow.yaml", input_data={"topic": "AI"}, run_id="run-1")

        mock_rt.run_pipeline.assert_called_once()
        call_kwargs = mock_rt.run_pipeline.call_args[1]
        assert call_kwargs["workflow_path"] == "my_workflow.yaml"
        assert call_kwargs["input_data"] == {"topic": "AI"}
        assert call_kwargs["run_id"] == "run-1"
