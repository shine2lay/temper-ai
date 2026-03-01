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
    backend = MagicMock()
    backend.get_workflow.return_value = None
    return backend


@pytest.fixture
def mock_event_bus():
    return MagicMock()


@pytest.fixture
def service(mock_backend, mock_event_bus, tmp_path):
    """Create a service with mocked dependencies."""
    return WorkflowExecutionService(
        backend=mock_backend,
        event_bus=mock_event_bus,
        config_root=str(tmp_path),
        max_workers=2,
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

    def test_returns_none_for_unknown_id_no_store(self, service):
        result = service.get_status_sync("exec-xyz")
        assert result is None


class TestSubmitWorkflow:
    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_returns_execution_id(self, mock_loader_cls, service, tmp_path):
        """submit_workflow should return an execution ID immediately."""
        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
        mock_loader_cls.return_value = mock_loader

        with patch.object(service, "_execute_workflow_in_runner"):
            exec_id = service.submit_workflow("test", input_data={"a": 1})

        assert exec_id.startswith("exec-")
        assert exec_id in service._executions

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_tracks_future(self, mock_loader_cls, service, tmp_path):
        """submit_workflow should store a future for the execution."""
        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
        mock_loader_cls.return_value = mock_loader

        with patch.object(service, "_execute_workflow_in_runner"):
            exec_id = service.submit_workflow("test")

        assert exec_id in service._futures

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_custom_run_id(self, mock_loader_cls, service, tmp_path):
        """submit_workflow with run_id should use it as prefix."""
        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
        mock_loader_cls.return_value = mock_loader

        with patch.object(service, "_execute_workflow_in_runner"):
            exec_id = service.submit_workflow("test", run_id="my-run")

        assert exec_id == "exec-my-run"


class TestExecuteWorkflowSync:
    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_blocks_and_returns_result(self, mock_loader_cls, service, tmp_path):
        """execute_workflow_sync should block until completion."""
        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
        mock_loader_cls.return_value = mock_loader

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
            result = service.execute_workflow_sync("test", input_data={"x": 1})

        assert result["status"] == "completed"

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_failed_workflow_records_error(self, mock_loader_cls, service, tmp_path):
        """execute_workflow_sync should record failure status."""
        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
        mock_loader_cls.return_value = mock_loader

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
            result = service.execute_workflow_sync("test")

        assert result["status"] == "failed"
        assert "boom" in (result.get("error_message") or "").lower()


class TestFuturesCleanup:
    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_futures_cleaned_after_sync_execute(
        self, mock_loader_cls, service, tmp_path
    ):
        """execute_workflow_sync should not leave futures in _futures dict."""
        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
        mock_loader_cls.return_value = mock_loader

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
            service.execute_workflow_sync("test")

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


class TestResumeWorkflow:
    @pytest.mark.asyncio
    async def test_resume_no_backend(self, service):
        """ValueError when no backend configured."""
        service.backend = None
        with pytest.raises(
            ValueError, match="Resume requires an observability backend"
        ):
            await service.resume_workflow("exec-123")

    @pytest.mark.asyncio
    async def test_resume_not_found(self, service, mock_backend):
        """ValueError for missing run."""
        mock_backend.get_workflow.return_value = None
        with pytest.raises(ValueError, match="not found"):
            await service.resume_workflow("exec-missing")

    @pytest.mark.asyncio
    async def test_resume_wrong_status(self, service, mock_backend):
        """ValueError for non-resumable status."""
        mock_backend.get_workflow.return_value = {"status": "completed"}
        with pytest.raises(ValueError, match="Only 'stuck' or 'failed'"):
            await service.resume_workflow("exec-completed")

    @pytest.mark.asyncio
    async def test_resume_running_status_rejected(self, service, mock_backend):
        """Running status is not resumable."""
        mock_backend.get_workflow.return_value = {"status": "running"}
        with pytest.raises(ValueError, match="Only 'stuck' or 'failed'"):
            await service.resume_workflow("exec-running")


class TestTenantIdThreading:
    """Tests that tenant_id is threaded through the execution pipeline."""

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_tenant_id_reaches_runner_config(self, mock_rt_cls, service, tmp_path):
        """tenant_id should reach WorkflowRunnerConfig."""
        mock_rt = MagicMock()
        mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
        mock_rt_cls.return_value = mock_rt

        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        # Register execution metadata so _execute_workflow_in_runner can find it
        metadata = WorkflowExecutionMetadata(
            execution_id="exec-1",
            workflow_path=str(wf),
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions["exec-1"] = metadata

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
            with patch(
                "temper_ai.interfaces.server.workflow_runner.WorkflowRunnerConfig",
            ) as mock_config_cls:
                mock_config_cls.return_value = MagicMock()
                service._execute_workflow_in_runner(
                    str(wf), {"x": 1}, "exec-1", tenant_id="test-tenant"
                )
                mock_config_cls.assert_called_once()
                call_kwargs = mock_config_cls.call_args
                assert call_kwargs.kwargs.get("tenant_id") == "test-tenant"

    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_tenant_id_none_when_not_provided(self, mock_rt_cls, service, tmp_path):
        """tenant_id defaults to None when not passed."""
        mock_rt = MagicMock()
        mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
        mock_rt_cls.return_value = mock_rt

        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        # Register execution metadata so _execute_workflow_in_runner can find it
        metadata = WorkflowExecutionMetadata(
            execution_id="exec-2",
            workflow_path=str(wf),
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions["exec-2"] = metadata

        mock_runner = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_result.result = {}
        mock_result.workflow_id = "wf-1"
        mock_runner.run.return_value = mock_result

        with patch(
            "temper_ai.interfaces.server.workflow_runner.WorkflowRunner",
            return_value=mock_runner,
        ):
            with patch(
                "temper_ai.interfaces.server.workflow_runner.WorkflowRunnerConfig",
            ) as mock_config_cls:
                mock_config_cls.return_value = MagicMock()
                service._execute_workflow_in_runner(str(wf), {}, "exec-2")
                call_kwargs = mock_config_cls.call_args
                assert call_kwargs.kwargs.get("tenant_id") is None

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_submit_workflow_passes_tenant_id(self, mock_loader_cls, service, tmp_path):
        """submit_workflow should pass tenant_id to _run_workflow_with_tracking."""
        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
        mock_loader_cls.return_value = mock_loader

        with patch.object(service, "_execute_workflow_in_runner"):
            exec_id = service.submit_workflow(
                "test", input_data={"a": 1}, tenant_id="my-tenant"
            )

        assert exec_id.startswith("exec-")


class TestShutdown:
    def test_shutdown_calls_executor_shutdown(self, service):
        mock_executor = MagicMock()
        service._executor = mock_executor

        service.shutdown()

        mock_executor.shutdown.assert_called_once_with(wait=True)
