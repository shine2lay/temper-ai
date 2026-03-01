"""Tests for name-based run flow (Plan 4: Run Flow Migration).

Validates that workflows are referenced by name (not filesystem path),
ConfigLoader resolves names (DB first, filesystem fallback), and
path traversal is no longer possible.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from temper_ai.interfaces.server.routes import RunRequest, _handle_create_run


class TestRunByName:
    """Tests that runs are triggered by workflow name, not path."""

    @pytest.mark.asyncio
    async def test_simple_name_accepted(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.return_value = "exec-123"
        body = RunRequest(workflow="research", inputs={"topic": "AI"})
        result = await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert result.execution_id == "exec-123"
        # Verify the workflow name (not path) was passed through
        call_kwargs = exec_svc.execute_workflow_async.call_args
        assert call_kwargs.kwargs.get("workflow_path") == "research"

    @pytest.mark.asyncio
    async def test_hyphenated_name_accepted(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.return_value = "exec-456"
        body = RunRequest(workflow="my-research-workflow")
        result = await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert result.execution_id == "exec-456"

    @pytest.mark.asyncio
    async def test_name_with_underscores_accepted(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.return_value = "exec-789"
        body = RunRequest(workflow="data_pipeline_v2")
        result = await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert result.execution_id == "exec-789"


class TestNameValidation:
    """Tests for workflow name validation rules."""

    @pytest.mark.asyncio
    async def test_empty_name_rejected(self):
        exec_svc = AsyncMock()
        body = RunRequest(workflow="")
        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert exc_info.value.status_code == 400
        assert "empty" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_whitespace_only_rejected(self):
        exec_svc = AsyncMock()
        body = RunRequest(workflow="   ")
        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_forward_slash_rejected(self):
        exec_svc = AsyncMock()
        body = RunRequest(workflow="workflows/research")
        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert exc_info.value.status_code == 400
        assert "Invalid workflow name" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_backslash_rejected(self):
        exec_svc = AsyncMock()
        body = RunRequest(workflow="workflows\\research")
        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_dot_dot_rejected(self):
        exec_svc = AsyncMock()
        body = RunRequest(workflow="..research")
        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert exc_info.value.status_code == 400


class TestNoPathTraversal:
    """Verify path traversal patterns are rejected at the name level."""

    @pytest.mark.asyncio
    async def test_parent_dir_traversal(self):
        exec_svc = AsyncMock()
        body = RunRequest(workflow="../../etc/passwd")
        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_absolute_path_rejected(self):
        exec_svc = AsyncMock()
        body = RunRequest(workflow="/etc/passwd")
        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_relative_path_with_extension_rejected(self):
        exec_svc = AsyncMock()
        body = RunRequest(workflow="workflows/test.yaml")
        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/configs")
        assert exc_info.value.status_code == 400


class TestTenantScoping:
    """Tests that tenant_id is passed through the run flow."""

    @pytest.mark.asyncio
    async def test_tenant_id_forwarded(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.return_value = "exec-1"
        body = RunRequest(workflow="research")
        await _handle_create_run(exec_svc, body, "/tmp/configs", tenant_id="tenant-123")
        call_kwargs = exec_svc.execute_workflow_async.call_args
        assert call_kwargs.kwargs.get("tenant_id") == "tenant-123"

    @pytest.mark.asyncio
    async def test_none_tenant_id_forwarded(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.return_value = "exec-1"
        body = RunRequest(workflow="research")
        await _handle_create_run(exec_svc, body, "/tmp/configs", tenant_id=None)
        call_kwargs = exec_svc.execute_workflow_async.call_args
        assert call_kwargs.kwargs.get("tenant_id") is None


class TestPrepareExecutionWithConfigLoader:
    """Tests that _prepare_execution uses ConfigLoader for name-based lookup."""

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_configloader_created_with_tenant_id(self, mock_loader_cls):
        from temper_ai.workflow.execution_service import WorkflowExecutionService

        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {"workflow": {"name": "test-wf"}}
        mock_loader_cls.return_value = mock_loader

        svc = WorkflowExecutionService(
            backend=MagicMock(),
            event_bus=MagicMock(),
            config_root="/tmp/configs",
        )

        exec_id, wf_name = svc._prepare_execution(
            "research", None, None, None, tenant_id="t1"
        )

        mock_loader_cls.assert_called_once_with(
            config_root="/tmp/configs", tenant_id="t1"
        )
        mock_loader.load_workflow.assert_called_once_with("research", validate=True)
        assert wf_name == "research"

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    def test_workflow_display_name_extracted(self, mock_loader_cls):
        from temper_ai.workflow.execution_service import WorkflowExecutionService

        mock_loader = MagicMock()
        mock_loader.load_workflow.return_value = {
            "workflow": {"name": "My Research Workflow"}
        }
        mock_loader_cls.return_value = mock_loader

        svc = WorkflowExecutionService(
            backend=MagicMock(),
            event_bus=MagicMock(),
            config_root="/tmp/configs",
        )

        exec_id, wf_name = svc._prepare_execution(
            "research", None, None, None, tenant_id="t1"
        )

        # Metadata should store the display name
        meta = svc._executions[exec_id]
        assert meta.workflow_name == "My Research Workflow"
        assert meta.workflow_path == "research"
