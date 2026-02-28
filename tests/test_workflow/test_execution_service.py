"""Tests for workflow/execution_service.py — sync methods and threading.Lock."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.workflow.execution_service import (
    WorkflowExecutionMetadata,
    WorkflowExecutionService,
    WorkflowExecutionStatus,
    _sanitize_workflow_result,
)


@pytest.fixture
def mock_backend():
    return MagicMock()


@pytest.fixture
def mock_event_bus():
    return MagicMock()


@pytest.fixture
def mock_run_store():
    store = MagicMock()
    store.get_run.return_value = None
    store.list_runs.return_value = []
    return store


@pytest.fixture
def service(mock_backend, mock_event_bus, mock_run_store, tmp_path):
    """Create a service with mocked dependencies."""
    return WorkflowExecutionService(
        backend=mock_backend,
        event_bus=mock_event_bus,
        config_root=str(tmp_path),
        max_workers=2,
        run_store=mock_run_store,
    )


class TestThreadingLock:
    def test_lock_is_threading_lock(self, service):
        """Lock should be threading.Lock, not asyncio.Lock."""
        assert isinstance(service._lock, type(threading.Lock()))

    def test_concurrent_get_status_sync(self, service):
        """get_status_sync should be safe for concurrent access."""
        results = []

        def read_status():
            result = service.get_status_sync("nonexistent")
            results.append(result)

        threads = [threading.Thread(target=read_status) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)

        assert len(results) == 10
        assert all(r is None for r in results)


class TestGetStatusSync:
    def test_returns_none_for_unknown_id(self, service):
        result = service.get_status_sync("unknown-id")
        assert result is None

    def test_returns_metadata_dict_for_known_id(self, service):
        metadata = WorkflowExecutionMetadata(
            execution_id="exec-abc",
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions["exec-abc"] = metadata

        result = service.get_status_sync("exec-abc")
        assert result is not None
        assert result["execution_id"] == "exec-abc"
        assert result["status"] == "running"

    def test_falls_back_to_run_store(self, service, mock_run_store):
        stored = MagicMock()
        stored.to_dict.return_value = {
            "execution_id": "exec-xyz",
            "status": "completed",
        }
        mock_run_store.get_run.return_value = stored

        result = service.get_status_sync("exec-xyz")
        assert result is not None
        assert result["status"] == "completed"


class TestSubmitWorkflow:
    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_returns_execution_id(self, mock_rt_cls, service, tmp_path):
        """submit_workflow should return an execution ID immediately."""
        mock_rt = MagicMock()
        mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
        mock_rt_cls.return_value = mock_rt

        # Create dummy workflow file
        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        with patch.object(service, "_execute_workflow_in_runner"):
            exec_id = service.submit_workflow("test.yaml", input_data={"a": 1})

        assert exec_id.startswith("exec-")
        assert exec_id in service._executions

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_tracks_future(self, mock_rt_cls, service, tmp_path):
        """submit_workflow should store a future for the execution."""
        mock_rt = MagicMock()
        mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
        mock_rt_cls.return_value = mock_rt

        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        with patch.object(service, "_execute_workflow_in_runner"):
            exec_id = service.submit_workflow("test.yaml")

        assert exec_id in service._futures

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_custom_run_id(self, mock_rt_cls, service, tmp_path):
        """submit_workflow with run_id should use it as prefix."""
        mock_rt = MagicMock()
        mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
        mock_rt_cls.return_value = mock_rt

        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        with patch.object(service, "_execute_workflow_in_runner"):
            exec_id = service.submit_workflow("test.yaml", run_id="my-run")

        assert exec_id == "exec-my-run"


class TestExecuteWorkflowSync:
    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_blocks_and_returns_result(self, mock_rt_cls, service, tmp_path):
        """execute_workflow_sync should block until completion."""
        mock_rt = MagicMock()
        mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
        mock_rt_cls.return_value = mock_rt

        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        mock_runner = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_result.result = {"output": "done"}
        mock_result.workflow_id = "wf-1"
        mock_runner.run.return_value = mock_result

        with patch(
            "temper_ai.interfaces.server.workflow_runner.WorkflowRunner",
            return_value=mock_runner,
        ):
            result = service.execute_workflow_sync("test.yaml", input_data={"x": 1})

        assert result["status"] == "completed"

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_failed_workflow_records_error(self, mock_rt_cls, service, tmp_path):
        """execute_workflow_sync should record failure status."""
        mock_rt = MagicMock()
        mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
        mock_rt_cls.return_value = mock_rt

        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        mock_runner = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "failed"
        mock_result.error_message = "Workflow boom"
        mock_result.workflow_id = None
        mock_runner.run.return_value = mock_result

        with patch(
            "temper_ai.interfaces.server.workflow_runner.WorkflowRunner",
            return_value=mock_runner,
        ):
            result = service.execute_workflow_sync("test.yaml")

        assert result["status"] == "failed"
        assert "boom" in (result.get("error_message") or "").lower()


class TestFuturesCleanup:
    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_futures_cleaned_after_sync_execute(self, mock_rt_cls, service, tmp_path):
        """execute_workflow_sync should not leave futures in _futures dict."""
        mock_rt = MagicMock()
        mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
        mock_rt_cls.return_value = mock_rt

        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        mock_runner = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_result.result = {"output": "done"}
        mock_result.workflow_id = "wf-1"
        mock_runner.run.return_value = mock_result

        with patch(
            "temper_ai.interfaces.server.workflow_runner.WorkflowRunner",
            return_value=mock_runner,
        ):
            service.execute_workflow_sync("test.yaml")

        assert len(service._futures) == 0


class TestSanitizeWorkflowResult:
    def test_strips_non_serializable_keys(self):
        result = _sanitize_workflow_result(
            {
                "output": "hello",
                "tracker": object(),
                "config_loader": object(),
            }
        )
        assert "output" in result
        assert "tracker" not in result
        assert "config_loader" not in result

    def test_non_dict_returns_none(self):
        assert _sanitize_workflow_result("string") is None

    def test_skips_non_json_values(self):
        result = _sanitize_workflow_result(
            {
                "good": "value",
                "bad": object(),
            }
        )
        assert "good" in result
        assert "bad" not in result


class TestCancelExecution:
    @pytest.mark.asyncio
    async def test_cancel_running_returns_true(self, service):
        metadata = WorkflowExecutionMetadata(
            execution_id="exec-run-1",
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions["exec-run-1"] = metadata

        result = await service.cancel_execution("exec-run-1")

        assert result is True
        assert metadata.status == WorkflowExecutionStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_returns_false(self, service):
        metadata = WorkflowExecutionMetadata(
            execution_id="exec-done-1",
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.COMPLETED,
        )
        service._executions["exec-done-1"] = metadata

        result = await service.cancel_execution("exec-done-1")

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_unknown_returns_false(self, service):
        result = await service.cancel_execution("nonexistent-id")
        assert result is False


class TestListExecutions:
    @pytest.mark.asyncio
    async def test_list_from_memory_no_store(self, service):
        service.run_store = None
        for i, status in enumerate(
            [WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.COMPLETED]
        ):
            metadata = WorkflowExecutionMetadata(
                execution_id=f"exec-mem-{i}",
                workflow_path="wf.yaml",
                workflow_name="test",
                status=status,
            )
            service._executions[f"exec-mem-{i}"] = metadata

        result = await service.list_executions()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, service):
        service.run_store = None
        for i, status in enumerate(
            [WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.COMPLETED]
        ):
            metadata = WorkflowExecutionMetadata(
                execution_id=f"exec-flt-{i}",
                workflow_path="wf.yaml",
                workflow_name="test",
                status=status,
            )
            service._executions[f"exec-flt-{i}"] = metadata

        result = await service.list_executions(status=WorkflowExecutionStatus.RUNNING)
        assert len(result) == 1
        assert result[0]["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_with_offset_limit(self, service):
        from datetime import UTC, datetime

        service.run_store = None
        for i in range(5):
            metadata = WorkflowExecutionMetadata(
                execution_id=f"exec-pg-{i}",
                workflow_path="wf.yaml",
                workflow_name="test",
                status=WorkflowExecutionStatus.RUNNING,
                started_at=datetime(2024, 1, i + 1, tzinfo=UTC),
            )
            service._executions[f"exec-pg-{i}"] = metadata

        result = await service.list_executions(offset=1, limit=2)
        assert len(result) == 2


class TestShutdown:
    def test_shutdown_calls_executor_shutdown(self, service):
        mock_executor = MagicMock()
        service._executor = mock_executor

        service.shutdown()

        mock_executor.shutdown.assert_called_once_with(wait=True)
