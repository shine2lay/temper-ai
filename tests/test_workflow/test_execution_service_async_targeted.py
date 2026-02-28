"""Targeted tests for workflow/execution_service.py async paths.

Covers missing lines: 204-221 (execute_workflow_async), 234-271 (_run_workflow_background),
375-386 (get_execution_status), 419-432 (_list_from_store), 522, 613->621, 630->exit.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.workflow.execution_service import (
    WorkflowExecutionMetadata,
    WorkflowExecutionService,
    WorkflowExecutionStatus,
    _save_run_to_store,
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
    return WorkflowExecutionService(
        backend=mock_backend,
        event_bus=mock_event_bus,
        config_root=str(tmp_path),
        max_workers=2,
        run_store=mock_run_store,
    )


@pytest.fixture
def service_no_store(mock_backend, mock_event_bus, tmp_path):
    return WorkflowExecutionService(
        backend=mock_backend,
        event_bus=mock_event_bus,
        config_root=str(tmp_path),
        max_workers=2,
        run_store=None,
    )


# ---------------------------------------------------------------------------
# _save_run_to_store
# ---------------------------------------------------------------------------


class TestSaveRunToStore:
    def test_none_run_store_does_nothing(self):
        # Should not raise
        _save_run_to_store(
            None, "exec-1", "wf.yaml", "test", (None, None, None), "pending"
        )

    def test_calls_save_run_with_correct_args(self):
        run_store = MagicMock()
        _save_run_to_store(
            run_store,
            "exec-1",
            "wf.yaml",
            "My Workflow",
            ({"key": "val"}, "/workspace", "tenant-1"),
            "pending",
        )
        run_store.save_run.assert_called_once()
        call_args = run_store.save_run.call_args[0][0]
        assert call_args.execution_id == "exec-1"
        assert call_args.workflow_path == "wf.yaml"
        assert call_args.workspace == "/workspace"
        assert call_args.tenant_id == "tenant-1"


# ---------------------------------------------------------------------------
# execute_workflow_async
# ---------------------------------------------------------------------------


class TestExecuteWorkflowAsync:
    @pytest.mark.asyncio
    async def test_returns_execution_id(self, service, tmp_path):
        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        with patch("temper_ai.workflow.runtime.WorkflowRuntime") as mock_rt_cls:
            mock_rt = MagicMock()
            mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
            mock_rt_cls.return_value = mock_rt

            with patch.object(
                service, "_run_workflow_background", new_callable=AsyncMock
            ):
                exec_id = await service.execute_workflow_async(
                    "test.yaml", input_data={}
                )

        assert exec_id.startswith("exec-")

    @pytest.mark.asyncio
    async def test_uses_custom_run_id(self, service, tmp_path):
        wf = tmp_path / "test.yaml"
        wf.write_text("workflow:\n  name: test\n")

        with patch("temper_ai.workflow.runtime.WorkflowRuntime") as mock_rt_cls:
            mock_rt = MagicMock()
            mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
            mock_rt_cls.return_value = mock_rt

            with patch.object(
                service, "_run_workflow_background", new_callable=AsyncMock
            ):
                exec_id = await service.execute_workflow_async(
                    "test.yaml", run_id="custom-run"
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
    async def test_updates_run_store_on_success(self, service, mock_run_store):
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

        mock_run_store.update_status.assert_called()


# ---------------------------------------------------------------------------
# get_execution_status (async)
# ---------------------------------------------------------------------------


class TestGetExecutionStatus:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, service):
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
    async def test_falls_back_to_run_store(self, service, mock_run_store):
        stored = MagicMock()
        stored.to_dict.return_value = {
            "execution_id": "exec-123",
            "status": "completed",
        }
        mock_run_store.get_run.return_value = stored

        result = await service.get_execution_status("exec-123")
        assert result is not None
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_no_run_store_returns_none(self, service_no_store):
        result = await service_no_store.get_execution_status("unknown")
        assert result is None


# ---------------------------------------------------------------------------
# _list_from_store
# ---------------------------------------------------------------------------


class TestListFromStore:
    @pytest.mark.asyncio
    async def test_merges_store_and_memory(self, service, mock_run_store):
        # Add a stored run
        stored_run = MagicMock()
        stored_run.execution_id = "exec-stored-1"
        stored_run.to_dict.return_value = {
            "execution_id": "exec-stored-1",
            "status": "completed",
        }
        mock_run_store.list_runs.return_value = [stored_run]

        # Add an in-memory run that's NOT in the store
        in_mem_meta = WorkflowExecutionMetadata(
            execution_id="exec-mem-1",
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions["exec-mem-1"] = in_mem_meta

        result = await service.list_executions()

        # Both should appear
        ids = [r["execution_id"] for r in result]
        assert "exec-stored-1" in ids
        assert "exec-mem-1" in ids

    @pytest.mark.asyncio
    async def test_does_not_duplicate_stored_run_in_memory(
        self, service, mock_run_store
    ):
        stored_run = MagicMock()
        stored_run.execution_id = "exec-dup"
        stored_run.to_dict.return_value = {
            "execution_id": "exec-dup",
            "status": "completed",
        }
        mock_run_store.list_runs.return_value = [stored_run]

        # Same execution_id in memory too
        in_mem_meta = WorkflowExecutionMetadata(
            execution_id="exec-dup",
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.COMPLETED,
        )
        service._executions["exec-dup"] = in_mem_meta

        result = await service.list_executions()

        # Should not duplicate
        ids = [r["execution_id"] for r in result]
        assert ids.count("exec-dup") == 1

    @pytest.mark.asyncio
    async def test_status_filter_from_store(self, service, mock_run_store):
        mock_run_store.list_runs.return_value = []

        # Only running in memory
        meta = WorkflowExecutionMetadata(
            execution_id="exec-running",
            workflow_path="wf.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.RUNNING,
        )
        service._executions["exec-running"] = meta

        result = await service.list_executions(status=WorkflowExecutionStatus.COMPLETED)
        # Running should be filtered out
        ids = [r["execution_id"] for r in result]
        assert "exec-running" not in ids


# ---------------------------------------------------------------------------
# _record_success and _record_failure with run_store
# ---------------------------------------------------------------------------


class TestRecordSuccessWithStore:
    def test_record_success_updates_store(self, service, mock_run_store):
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
        mock_run_store.update_status.assert_called()

    def test_record_failure_updates_store(self, service, mock_run_store):
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
        mock_run_store.update_status.assert_called()


# ---------------------------------------------------------------------------
# _prepare_execution — duplicate ID check
# ---------------------------------------------------------------------------


class TestPrepareExecution:
    @patch("temper_ai.workflow.runtime.WorkflowRuntime")
    def test_duplicate_execution_id_raises(self, mock_rt_cls, service, tmp_path):
        mock_rt = MagicMock()
        mock_rt.load_config.return_value = ({"workflow": {"name": "test"}}, None)
        mock_rt_cls.return_value = mock_rt

        wf = tmp_path / "dup.yaml"
        wf.write_text("workflow:\n  name: test\n")

        # Insert a pre-existing execution with the same run_id prefix
        existing_meta = WorkflowExecutionMetadata(
            execution_id="exec-dup-id",
            workflow_path="dup.yaml",
            workflow_name="test",
            status=WorkflowExecutionStatus.PENDING,
        )
        service._executions["exec-dup-id"] = existing_meta

        with pytest.raises(ValueError, match="already exists"):
            service._prepare_execution("dup.yaml", None, None, "dup-id", None)
