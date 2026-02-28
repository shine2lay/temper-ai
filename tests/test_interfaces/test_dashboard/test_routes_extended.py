"""Extended tests for temper_ai.interfaces.dashboard.routes — cover dev mode endpoints."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.dashboard.routes import (
    _handle_get_agent,
    _handle_get_llm_call,
    _handle_get_stage,
    _handle_get_tool_call,
    _handle_get_workflow,
    _handle_get_workflow_trace,
    _handle_list_workflows,
    create_router,
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


class TestHandlerFunctions:
    def test_list_workflows(self):
        ds = MagicMock()
        ds.list_workflows.return_value = [{"id": "wf1"}]
        result = _handle_list_workflows(ds, 50, 0, None)
        assert len(result) == 1

    def test_get_workflow_found(self):
        ds = MagicMock()
        ds.get_workflow_snapshot.return_value = {"id": "wf1"}
        result = _handle_get_workflow(ds, "wf1")
        assert result["id"] == "wf1"

    def test_get_workflow_not_found(self):
        ds = MagicMock()
        ds.get_workflow_snapshot.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _handle_get_workflow(ds, "missing")
        assert exc_info.value.status_code == 404

    def test_get_workflow_trace_found(self):
        ds = MagicMock()
        ds.get_workflow_trace.return_value = {"trace": "data"}
        result = _handle_get_workflow_trace(ds, "wf1")
        assert result["trace"] == "data"

    def test_get_workflow_trace_not_found(self):
        ds = MagicMock()
        ds.get_workflow_trace.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _handle_get_workflow_trace(ds, "missing")
        assert exc_info.value.status_code == 404

    def test_get_stage_found(self):
        ds = MagicMock()
        ds.get_stage.return_value = {"id": "s1"}
        result = _handle_get_stage(ds, "s1")
        assert result["id"] == "s1"

    def test_get_stage_not_found(self):
        ds = MagicMock()
        ds.get_stage.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _handle_get_stage(ds, "missing")
        assert exc_info.value.status_code == 404

    def test_get_agent_found(self):
        ds = MagicMock()
        ds.get_agent.return_value = {"id": "a1"}
        result = _handle_get_agent(ds, "a1")
        assert result["id"] == "a1"

    def test_get_agent_not_found(self):
        ds = MagicMock()
        ds.get_agent.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _handle_get_agent(ds, "missing")
        assert exc_info.value.status_code == 404

    def test_get_llm_call_found(self):
        ds = MagicMock()
        ds.get_llm_call.return_value = {"id": "lc1"}
        result = _handle_get_llm_call(ds, "lc1")
        assert result["id"] == "lc1"

    def test_get_llm_call_not_found(self):
        ds = MagicMock()
        ds.get_llm_call.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _handle_get_llm_call(ds, "missing")
        assert exc_info.value.status_code == 404

    def test_get_tool_call_found(self):
        ds = MagicMock()
        ds.get_tool_call.return_value = {"id": "tc1"}
        result = _handle_get_tool_call(ds, "tc1")
        assert result["id"] == "tc1"

    def test_get_tool_call_not_found(self):
        ds = MagicMock()
        ds.get_tool_call.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            _handle_get_tool_call(ds, "missing")
        assert exc_info.value.status_code == 404

    def test_with_tenant_id(self):
        ds = MagicMock()
        ds.get_workflow_snapshot.return_value = {"id": "wf1"}
        result = _handle_get_workflow(ds, "wf1", tenant_id="t1")
        assert result["id"] == "wf1"


class TestDevModeRouter:
    def _make_dev_client(self):
        ds = MagicMock()
        ds.list_workflows.return_value = [{"id": "wf1"}]
        ds.get_workflow_snapshot.return_value = {"id": "wf1"}
        ds.get_workflow_trace.return_value = {"trace": "data"}
        ds.get_data_flow.return_value = {"nodes": [], "edges": []}
        ds.get_stage.return_value = {"id": "s1"}
        ds.get_agent.return_value = {"id": "a1"}
        ds.get_llm_call.return_value = {"id": "lc1"}
        ds.get_tool_call.return_value = {"id": "tc1"}

        app = FastAPI()
        router = create_router(ds, auth_enabled=False)
        app.include_router(router, prefix="/api")
        return TestClient(app, raise_server_exceptions=False)

    def test_list_workflows(self):
        client = self._make_dev_client()
        resp = client.get("/api/workflows")
        assert resp.status_code == 200

    def test_get_workflow(self):
        client = self._make_dev_client()
        resp = client.get("/api/workflows/wf1")
        assert resp.status_code == 200

    def test_get_workflow_trace(self):
        client = self._make_dev_client()
        resp = client.get("/api/workflows/wf1/trace")
        assert resp.status_code == 200

    def test_get_data_flow(self):
        client = self._make_dev_client()
        resp = client.get("/api/workflows/wf1/data-flow")
        assert resp.status_code == 200

    def test_get_stage(self):
        client = self._make_dev_client()
        resp = client.get("/api/stages/s1")
        assert resp.status_code == 200

    def test_get_agent(self):
        client = self._make_dev_client()
        resp = client.get("/api/agents/a1")
        assert resp.status_code == 200

    def test_get_llm_call(self):
        client = self._make_dev_client()
        resp = client.get("/api/llm-calls/lc1")
        assert resp.status_code == 200

    def test_get_tool_call(self):
        client = self._make_dev_client()
        resp = client.get("/api/tool-calls/tc1")
        assert resp.status_code == 200


class TestAuthModeRouter:
    def _make_auth_client(self):
        ds = MagicMock()
        ds.list_workflows.return_value = [{"id": "wf1"}]
        ds.get_workflow_snapshot.return_value = {"id": "wf1"}
        ds.get_workflow_trace.return_value = {"trace": "data"}
        ds.get_data_flow.return_value = {"nodes": [], "edges": []}
        ds.get_stage.return_value = {"id": "s1"}
        ds.get_agent.return_value = {"id": "a1"}
        ds.get_llm_call.return_value = {"id": "lc1"}
        ds.get_tool_call.return_value = {"id": "tc1"}

        app = FastAPI()
        router = create_router(ds, auth_enabled=True)
        app.include_router(router, prefix="/api")
        app.dependency_overrides[require_auth] = _mock_auth()
        return TestClient(app, raise_server_exceptions=False)

    def test_list_workflows(self):
        client = self._make_auth_client()
        resp = client.get("/api/workflows")
        assert resp.status_code == 200

    def test_get_workflow(self):
        client = self._make_auth_client()
        resp = client.get("/api/workflows/wf1")
        assert resp.status_code == 200

    def test_get_workflow_trace(self):
        client = self._make_auth_client()
        resp = client.get("/api/workflows/wf1/trace")
        assert resp.status_code == 200

    def test_get_data_flow(self):
        client = self._make_auth_client()
        resp = client.get("/api/workflows/wf1/data-flow")
        assert resp.status_code == 200

    def test_get_stage(self):
        client = self._make_auth_client()
        resp = client.get("/api/stages/s1")
        assert resp.status_code == 200

    def test_get_agent(self):
        client = self._make_auth_client()
        resp = client.get("/api/agents/a1")
        assert resp.status_code == 200

    def test_get_llm_call(self):
        client = self._make_auth_client()
        resp = client.get("/api/llm-calls/lc1")
        assert resp.status_code == 200

    def test_get_tool_call(self):
        client = self._make_auth_client()
        resp = client.get("/api/tool-calls/tc1")
        assert resp.status_code == 200
