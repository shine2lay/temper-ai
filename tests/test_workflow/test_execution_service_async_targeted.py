"""Targeted tests for workflow/execution_service.py async paths.

Covers missing lines: execute_workflow_async, _run_workflow_background,
get_execution_status, list_executions, _record_success/_record_failure.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.workflow.execution_service import (
    WorkflowExecutionMetadata,
    WorkflowExecutionService,
    WorkflowExecutionStatus,
)


@pytest.fixture
def mock_backend():
    return MagicMock()


@pytest.fixture
def mock_event_bus():
    return MagicMock()


@pytest.fixture
def service(mock_backend, mock_event_bus, tmp_path):
    return WorkflowExecutionService(
        backend=mock_backend,
        event_bus=mock_event_bus,
        config_root=str(tmp_path),
        max_workers=2,
    )


@pytest.fixture
def service_no_backend(mock_event_bus, tmp_path):
    return WorkflowExecutionService(
        backend=None,
        event_bus=mock_event_bus,
        config_root=str(tmp_path),
        max_workers=2,
    )


# ---------------------------------------------------------------------------
# execute_workflow_async
# ---------------------------------------------------------------------------


class TestExecuteWorkflowAsync:
    @pytest.mark.asyncio
    async def test_returns_execution_id(self, service, tmp_path):
        with patch("temper_ai.workflow.config_loader.ConfigLoader") as mock_loader_cls:
            mock_loader = MagicMock()
            mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
            mock_loader_cls.return_value = mock_loader

            with patch.object(
                service, "_run_workflow_background", new_callable=AsyncMock
            ):
                exec_id = await service.execute_workflow_async("test", input_data={})

        assert exec_id.startswith("exec-")

    @pytest.mark.asyncio
    async def test_uses_custom_run_id(self, service, tmp_path):
        with patch("temper_ai.workflow.config_loader.ConfigLoader") as mock_loader_cls:
            mock_loader = MagicMock()
            mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
            mock_loader_cls.return_value = mock_loader

            with patch.object(
                service, "_run_workflow_background", new_callable=AsyncMock
            ):
                exec_id = await service.execute_workflow_async(
                    "test", run_id="custom-run"
                )

        assert exec_id == "exec-custom-run"


# ---------------------------------------------------------------------------
# _run_workflow_background
# ---------------------------------------------------------------------------


class TestRunWorkflowBackground:
    @pytest.mark.asyncio
    async def test_missing_metadata_logs_and_returns(self, service):
        # If metadata is not in _executions, should just return
        await service._run_workflow_background(
            "nonexistent-exec-id",
            "wf.yaml",
            {},
            None,
        )

    @pytest.mark.asyncio
    async def test_successful_run_updates_status(self, service, tmp_path):
        exec_id = "exec-bg-1"
        metadata = WorkflowExecutionMetadata(
            execution_id=exec_id,
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.PENDING,
        )
        service._executions[exec_id] = metadata

        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_result.result = {"output": "done"}
        mock_result.workflow_id = "wf-1"
        mock_result.error_message = None

        with patch.object(
            service,
            "_execute_workflow_in_runner",
            return_value={"output": "done"},
        ):
            await service._run_workflow_background(exec_id, "wf.yaml", {}, None)

        assert metadata.status == WorkflowExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failed_run_records_failure(self, service):
        exec_id = "exec-bg-fail"
        metadata = WorkflowExecutionMetadata(
            execution_id=exec_id,
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.PENDING,
        )
        service._executions[exec_id] = metadata

        with patch.object(
            service,
            "_execute_workflow_in_runner",
            side_effect=RuntimeError("execution exploded"),
        ):
            await service._run_workflow_background(exec_id, "wf.yaml", {}, None)

        assert metadata.status == WorkflowExecutionStatus.FAILED
        assert "exploded" in (metadata.error_message or "")

    @pytest.mark.asyncio
    async def test_updates_status_on_success(self, service):
        exec_id = "exec-store-success"
        metadata = WorkflowExecutionMetadata(
            execution_id=exec_id,
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.PENDING,
        )
        service._executions[exec_id] = metadata

        with patch.object(
            service,
            "_execute_workflow_in_runner",
            return_value={"key": "val"},
        ):
            await service._run_workflow_background(exec_id, "wf.yaml", {}, None)

        assert metadata.status == WorkflowExecutionStatus.COMPLETED


# ---------------------------------------------------------------------------
# get_execution_status (async)
# ---------------------------------------------------------------------------


class TestGetExecutionStatus:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, service, mock_backend):
        mock_backend.get_workflow.return_value = None
        result = await service.get_execution_status("unknown-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_metadata_from_memory(self, service):
        exec_id = "exec-mem-status"
        metadata = WorkflowExecutionMetadata(
            execution_id=exec_id,
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions[exec_id] = metadata

        result = await service.get_execution_status(exec_id)
        assert result is not None
        assert result["execution_id"] == exec_id
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_falls_back_to_backend(self, service, mock_backend):
        mock_backend.get_workflow.return_value = {
            "execution_id": "exec-123",
            "status": "completed",
        }

        result = await service.get_execution_status("exec-123")
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_backend_returns_none(self, service_no_backend):
        result = await service_no_backend.get_execution_status("unknown")
        assert result is None


# ---------------------------------------------------------------------------
# _list_from_backend
# ---------------------------------------------------------------------------


class TestListFromBackend:
    @pytest.mark.asyncio
    async def test_merges_backend_and_memory(self, service, mock_backend):
        # Backend returns one stored run
        mock_backend.list_workflows.return_value = [
            {
                "id": "exec-stored-1",
                "execution_id": "exec-stored-1",
                "status": "completed",
            }
        ]

        # Add an in-memory run that's NOT in the backend
        in_mem_meta = WorkflowExecutionMetadata(
            execution_id="exec-mem-1",
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions["exec-mem-1"] = in_mem_meta

        result = await service.list_executions()

        ids = [r.get("id") or r.get("execution_id") for r in result]
        assert any("exec-stored-1" in str(i) for i in ids)
        assert "exec-mem-1" in [r.get("execution_id") for r in result]

    @pytest.mark.asyncio
    async def test_status_filter_excludes_non_matching(self, service, mock_backend):
        mock_backend.list_workflows.return_value = []

        # Only running in memory
        meta = WorkflowExecutionMetadata(
            execution_id="exec-running",
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions["exec-running"] = meta

        result = await service.list_executions(status=WorkflowExecutionStatus.COMPLETED)
        ids = [r.get("execution_id") for r in result]
        assert "exec-running" not in ids


# ---------------------------------------------------------------------------
# _record_success and _record_failure
# ---------------------------------------------------------------------------


class TestRecordSuccess:
    def test_record_success_updates_status(self, service):
        exec_id = "exec-rec-success"
        metadata = WorkflowExecutionMetadata(
            execution_id=exec_id,
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions[exec_id] = metadata

        service._record_success(exec_id, {"output": "done"})

        assert metadata.status == WorkflowExecutionStatus.COMPLETED

    def test_record_failure_updates_status(self, service):
        exec_id = "exec-rec-failure"
        metadata = WorkflowExecutionMetadata(
            execution_id=exec_id,
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions[exec_id] = metadata

        service._record_failure(exec_id, "Something went wrong")

        assert metadata.status == WorkflowExecutionStatus.FAILED
        assert "Something went wrong" in (metadata.error_message or "")


# ---------------------------------------------------------------------------
# _prepare_execution — duplicate ID check
# ---------------------------------------------------------------------------


class TestPrepareExecution:
    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_duplicate_execution_id_raises(self, mock_loader_cls, service, tmp_path):
        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {"workflow": {"name": "test"}}
        mock_loader_cls.return_value = mock_loader

        # Insert a pre-existing execution with the same run_id prefix
        existing_meta = WorkflowExecutionMetadata(
            execution_id="exec-dup-id",
            workflow_path="dup",
            workflow_name="test",
            status=WorkflowExecutionStatus.PENDING,
        )
        service._executions["exec-dup-id"] = existing_meta

        with pytest.raises(ValueError, match="already exists"):
            service._prepare_execution("dup", None, None, "dup-id", None)
