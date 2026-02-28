"""Tests for temper_ai.interfaces.server.routes — server-mode API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.routes import (
    RunRequest,
    ValidateRequest,
    _handle_cancel_run,
    _handle_create_run,
    _handle_get_run,
    _handle_get_run_events,
    _handle_health,
    _handle_list_available_workflows,
    _handle_list_runs,
    _handle_readiness,
    _handle_validate_workflow,
    create_server_router,
)

_MOCK_AUTH_CTX = AuthContext(
    user_id="test-user",
    tenant_id="test-tenant",
    role="owner",
    api_key_id="key-test",
)


def _mock_auth():
    async def _dep():
        return _MOCK_AUTH_CTX

    return _dep


def _make_client(execution_service, data_service=None, auth_enabled=False):
    app = FastAPI()
    ds = data_service or MagicMock()
    router = create_server_router(
        execution_service,
        ds,
        config_root="/tmp/test-configs",
        auth_enabled=auth_enabled,
    )
    app.include_router(router, prefix="/api")
    if auth_enabled:
        app.dependency_overrides[require_auth] = _mock_auth()
    return TestClient(app, raise_server_exceptions=False)


class TestHandleHealth:
    def test_returns_health_dict(self):
        result = _handle_health()
        assert "status" in result


class TestHandleReadiness:
    @patch("temper_ai.storage.database.get_session")
    def test_ready_when_gate_true(self, mock_session):
        # Mock db session to make check_readiness return "ready"
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = mock_ctx

        exec_svc = MagicMock()
        exec_svc._executions = {}
        request = MagicMock()
        request.app.state = MagicMock(spec=[])
        result = _handle_readiness(exec_svc, request)
        assert result["status"] == "ready"

    def test_not_ready_raises_503(self):
        exec_svc = MagicMock()
        request = MagicMock()
        sm = MagicMock()
        sm.readiness_gate = False
        request.app.state.shutdown_manager = sm
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_readiness(exec_svc, request)
        assert exc_info.value.status_code == 503


class TestHandleCreateRun:
    @pytest.mark.asyncio
    async def test_success(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.return_value = "exec-123"
        body = RunRequest(workflow="workflows/test.yaml", inputs={"key": "val"})
        result = await _handle_create_run(exec_svc, body, "/tmp/test-configs")
        assert result.execution_id == "exec-123"

    @pytest.mark.asyncio
    async def test_path_traversal_raises_400(self):
        exec_svc = AsyncMock()
        body = RunRequest(workflow="../../etc/passwd")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/test-configs")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_file_not_found_raises_404(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.side_effect = FileNotFoundError("missing")
        body = RunRequest(workflow="workflows/test.yaml")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/test-configs")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_generic_error_raises_500(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.side_effect = RuntimeError("boom")
        body = RunRequest(workflow="workflows/test.yaml")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _handle_create_run(exec_svc, body, "/tmp/test-configs")
        assert exc_info.value.status_code == 500


class TestHandleListRuns:
    @pytest.mark.asyncio
    async def test_list_no_filter(self):
        exec_svc = AsyncMock()
        exec_svc.list_executions.return_value = [{"id": "r1"}]
        result = await _handle_list_runs(exec_svc, None, 100, 0)
        assert result == {"runs": [{"id": "r1"}], "total": 1}

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self):
        exec_svc = AsyncMock()
        exec_svc.list_executions.return_value = []
        result = await _handle_list_runs(exec_svc, "completed", 10, 0)
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_invalid_status(self):
        exec_svc = AsyncMock()
        result = await _handle_list_runs(exec_svc, "INVALID_STATUS_999", 10, 0)
        assert result == {"runs": [], "total": 0}

    @pytest.mark.asyncio
    async def test_list_with_tenant_id(self):
        exec_svc = AsyncMock()
        exec_svc.list_executions.return_value = []
        result = await _handle_list_runs(exec_svc, None, 10, 0, tenant_id="t1")
        assert result["total"] == 0


class TestHandleGetRun:
    @pytest.mark.asyncio
    async def test_found(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = {"id": "r1", "status": "running"}
        result = await _handle_get_run(exec_svc, "r1")
        assert result["id"] == "r1"

    @pytest.mark.asyncio
    async def test_not_found(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = None
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _handle_get_run(exec_svc, "missing")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_error_raises_500(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.side_effect = RuntimeError("db error")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _handle_get_run(exec_svc, "r1")
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_with_tenant_id_logging(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = {"id": "r1"}
        result = await _handle_get_run(exec_svc, "r1", tenant_id="t1")
        assert result["id"] == "r1"


class TestHandleCancelRun:
    @pytest.mark.asyncio
    async def test_cancel_success(self):
        exec_svc = AsyncMock()
        exec_svc.cancel_execution.return_value = True
        result = await _handle_cancel_run(exec_svc, "r1")
        assert result["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_not_found(self):
        exec_svc = AsyncMock()
        exec_svc.cancel_execution.return_value = False
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _handle_cancel_run(exec_svc, "r1")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_with_tenant_id(self):
        exec_svc = AsyncMock()
        exec_svc.cancel_execution.return_value = True
        result = await _handle_cancel_run(exec_svc, "r1", tenant_id="t1")
        assert result["execution_id"] == "r1"


class TestHandleGetRunEvents:
    @pytest.mark.asyncio
    async def test_run_not_found(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = None
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await _handle_get_run_events(exec_svc, "r1", 100, 0)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_workflow_id(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = {"id": "r1"}
        result = await _handle_get_run_events(exec_svc, "r1", 100, 0)
        assert result == {"events": [], "total": 0}

    @pytest.mark.asyncio
    async def test_events_found(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = {
            "id": "r1",
            "workflow_id": "wf1",
        }
        mock_backend = MagicMock()
        mock_backend.get_run_events.return_value = [{"event": "e1"}]
        with patch(
            "temper_ai.observability.backends.sql_backend.SQLObservabilityBackend",
            return_value=mock_backend,
        ):
            result = await _handle_get_run_events(exec_svc, "r1", 100, 0)
        assert "events" in result

    @pytest.mark.asyncio
    async def test_events_backend_failure_returns_empty(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = {
            "id": "r1",
            "workflow_id": "wf1",
        }
        with patch(
            "temper_ai.observability.backends.sql_backend.SQLObservabilityBackend",
            side_effect=Exception("boom"),
        ):
            result = await _handle_get_run_events(exec_svc, "r1", 100, 0)
        assert result["events"] == []


class TestHandleValidateWorkflow:
    def test_path_traversal(self):
        result = _handle_validate_workflow(
            "/tmp/test-configs", ValidateRequest(workflow="../../etc/passwd")
        )
        assert result["valid"] is False
        assert "Invalid workflow path" in result["errors"][0]

    def test_file_not_found(self):
        result = _handle_validate_workflow(
            "/tmp/test-configs", ValidateRequest(workflow="nonexistent.yaml")
        )
        assert result["valid"] is False
        assert "File not found" in result["errors"][0]


class TestHandleListAvailableWorkflows:
    def test_no_workflows_dir(self):
        result = _handle_list_available_workflows("/tmp/nonexistent-dir-xyz")
        assert result == {"workflows": [], "total": 0}

    def test_with_yaml_files(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "test.yaml").write_text(
            "workflow:\n  name: test\n  description: A test\n  version: '1.0'"
        )
        result = _handle_list_available_workflows(str(tmp_path))
        assert result["total"] == 1
        assert result["workflows"][0]["name"] == "test"

    def test_invalid_yaml_skipped(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "bad.yaml").write_text(": : invalid yaml }{}{")
        result = _handle_list_available_workflows(str(tmp_path))
        assert result["total"] == 0


class TestServerRouterNoAuth:
    def test_health(self):
        client = _make_client(MagicMock())
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_create_run(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.return_value = "exec-1"
        client = _make_client(exec_svc)
        resp = client.post("/api/runs", json={"workflow": "workflows/test.yaml"})
        assert resp.status_code == 200
        assert resp.json()["execution_id"] == "exec-1"

    def test_list_runs(self):
        exec_svc = AsyncMock()
        exec_svc.list_executions.return_value = []
        client = _make_client(exec_svc)
        resp = client.get("/api/runs")
        assert resp.status_code == 200

    def test_get_run(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = {"id": "r1", "status": "done"}
        client = _make_client(exec_svc)
        resp = client.get("/api/runs/r1")
        assert resp.status_code == 200

    def test_cancel_run(self):
        exec_svc = AsyncMock()
        exec_svc.cancel_execution.return_value = True
        client = _make_client(exec_svc)
        resp = client.post("/api/runs/r1/cancel")
        assert resp.status_code == 200

    def test_validate_workflow(self):
        exec_svc = MagicMock()
        client = _make_client(exec_svc)
        resp = client.post("/api/validate", json={"workflow": "nonexistent.yaml"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False

    def test_list_available_workflows(self):
        exec_svc = MagicMock()
        client = _make_client(exec_svc)
        resp = client.get("/api/workflows/available")
        assert resp.status_code == 200


class TestServerRouterWithAuth:
    def test_create_run_auth(self):
        exec_svc = AsyncMock()
        exec_svc.execute_workflow_async.return_value = "exec-1"
        client = _make_client(exec_svc, auth_enabled=True)
        resp = client.post("/api/runs", json={"workflow": "workflows/test.yaml"})
        assert resp.status_code == 200

    def test_list_runs_auth(self):
        exec_svc = AsyncMock()
        exec_svc.list_executions.return_value = []
        client = _make_client(exec_svc, auth_enabled=True)
        resp = client.get("/api/runs")
        assert resp.status_code == 200

    def test_get_run_auth(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = {"id": "r1"}
        client = _make_client(exec_svc, auth_enabled=True)
        resp = client.get("/api/runs/r1")
        assert resp.status_code == 200

    def test_cancel_run_auth(self):
        exec_svc = AsyncMock()
        exec_svc.cancel_execution.return_value = True
        client = _make_client(exec_svc, auth_enabled=True)
        resp = client.post("/api/runs/r1/cancel")
        assert resp.status_code == 200

    def test_get_run_events_auth(self):
        exec_svc = AsyncMock()
        exec_svc.get_execution_status.return_value = None
        client = _make_client(exec_svc, auth_enabled=True)
        resp = client.get("/api/runs/r1/events")
        assert resp.status_code == 404
