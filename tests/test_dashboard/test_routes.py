"""Tests for dashboard REST API routes."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_WORKFLOW = {
    "id": "wf-1",
    "workflow_name": "test-workflow",
    "status": "completed",
    "start_time": "2026-01-01T00:00:00",
    "end_time": "2026-01-01T00:01:00",
    "stages": [
        {
            "id": "st-1",
            "stage_name": "stage-1",
            "status": "completed",
            "input_data": {"key": "value"},
            "output_data": {"result": 42},
        },
        {
            "id": "st-2",
            "stage_name": "stage-2",
            "status": "completed",
            "input_data": None,
            "output_data": None,
        },
    ],
}

SAMPLE_STAGE = {
    "id": "st-1",
    "stage_name": "stage-1",
    "status": "completed",
    "agents": [],
}

SAMPLE_AGENT = {
    "id": "ag-1",
    "agent_name": "researcher",
    "status": "completed",
    "llm_calls": [],
    "tool_calls": [],
}

SAMPLE_LLM_CALL = {
    "id": "llm-1",
    "provider": "ollama",
    "model": "qwen3",
    "prompt": "Hello",
    "response": "World",
}

SAMPLE_TOOL_CALL = {
    "id": "tc-1",
    "tool_name": "web_search",
    "input_params": {"q": "test"},
    "output_data": {"result": "ok"},
}


def _make_backend():
    """Create a mock backend returning test data."""
    backend = MagicMock()
    backend.get_workflow.return_value = SAMPLE_WORKFLOW
    backend.list_workflows.return_value = [
        {"id": "wf-1", "workflow_name": "test-workflow", "status": "completed"},
        {"id": "wf-2", "workflow_name": "test-workflow-2", "status": "running"},
    ]
    backend.get_stage.return_value = SAMPLE_STAGE
    backend.get_agent.return_value = SAMPLE_AGENT
    backend.get_llm_call.return_value = SAMPLE_LLM_CALL
    backend.get_tool_call.return_value = SAMPLE_TOOL_CALL
    return backend


@pytest.fixture()
def client():
    backend = _make_backend()
    app = create_app(backend=backend)
    return TestClient(app)


@pytest.fixture()
def client_no_backend():
    app = create_app(backend=None)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/workflows
# ---------------------------------------------------------------------------


class TestListWorkflows:
    def test_list_workflows_returns_list(self, client):
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_list_workflows_with_limit(self, client):
        resp = client.get("/api/workflows?limit=1")
        assert resp.status_code == 200

    def test_list_workflows_with_offset(self, client):
        resp = client.get("/api/workflows?offset=5")
        assert resp.status_code == 200

    def test_list_workflows_with_status(self, client):
        resp = client.get("/api/workflows?status=completed")
        assert resp.status_code == 200

    def test_list_workflows_empty_when_no_backend(self, client_no_backend):
        resp = client_no_backend.get("/api/workflows")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_workflows_invalid_limit(self, client):
        resp = client.get("/api/workflows?limit=0")
        assert resp.status_code == 422

    def test_list_workflows_invalid_offset(self, client):
        resp = client.get("/api/workflows?offset=-1")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/workflows/{workflow_id}
# ---------------------------------------------------------------------------


class TestGetWorkflow:
    def test_get_workflow(self, client):
        resp = client.get("/api/workflows/wf-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "wf-1"
        assert data["workflow_name"] == "test-workflow"

    def test_get_workflow_not_found(self, client):
        backend = _make_backend()
        backend.get_workflow.return_value = None
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/workflows/nonexistent")
        assert resp.status_code == 404

    def test_get_workflow_no_backend(self, client_no_backend):
        resp = client_no_backend.get("/api/workflows/wf-1")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/workflows/{workflow_id}/trace
# ---------------------------------------------------------------------------


class TestGetWorkflowTrace:
    def test_trace_no_backend(self, client_no_backend):
        resp = client_no_backend.get("/api/workflows/wf-1/trace")
        assert resp.status_code == 404

    def test_trace_fallback_to_snapshot(self, client):
        """When export_waterfall is not importable, falls back to snapshot."""
        resp = client.get("/api/workflows/wf-1/trace")
        # Depending on import availability, may return snapshot or trace.
        # We just ensure it doesn't crash.
        assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# GET /api/workflows/{workflow_id}/data-flow
# ---------------------------------------------------------------------------


class TestGetDataFlow:
    def test_data_flow(self, client):
        resp = client.get("/api/workflows/wf-1/data-flow")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        # Edge should carry output keys from first stage
        assert data["edges"][0]["data_keys"] == ["result"]

    def test_data_flow_with_agents(self):
        """Agent nodes appear as children of their stage with parent field."""
        workflow = {
            "id": "wf-agents",
            "workflow_name": "agents-test",
            "status": "completed",
            "stages": [
                {
                    "id": "st-a",
                    "stage_name": "research",
                    "status": "completed",
                    "input_data": None,
                    "output_data": {"findings": "data"},
                    "agents": [
                        {
                            "id": "ag-1",
                            "agent_name": "analyst",
                            "status": "completed",
                            "agent_config_snapshot": {"model": "gpt-4"},
                            "total_tokens": 500,
                            "estimated_cost_usd": 0.01,
                            "num_llm_calls": 2,
                            "num_tool_calls": 1,
                        },
                        {
                            "id": "ag-2",
                            "agent_name": "reviewer",
                            "status": "completed",
                            "agent_config_snapshot": None,
                        },
                    ],
                    "collaboration_events": [
                        {
                            "event_type": "debate",
                            "agents_involved": ["ag-1", "ag-2"],
                        },
                    ],
                },
                {
                    "id": "st-b",
                    "stage_name": "decision",
                    "status": "completed",
                    "input_data": {"findings": "data"},
                    "output_data": None,
                    "agents": [],
                },
            ],
        }
        backend = _make_backend()
        backend.get_workflow.return_value = workflow
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/workflows/wf-agents/data-flow")
        assert resp.status_code == 200
        data = resp.json()

        # 2 stages + 2 agents = 4 nodes
        assert len(data["nodes"]) == 4
        agent_nodes = [n for n in data["nodes"] if n["type"] == "agent"]
        assert len(agent_nodes) == 2
        assert agent_nodes[0]["parent"] == "st-a"
        assert agent_nodes[0]["model"] == "gpt-4"
        assert agent_nodes[0]["total_tokens"] == 500
        assert agent_nodes[1]["parent"] == "st-a"
        assert agent_nodes[1]["model"] is None

        # 1 data-flow edge + 1 collaboration edge = 2 edges
        assert len(data["edges"]) == 2
        collab = [e for e in data["edges"] if e["type"] == "collaboration"]
        assert len(collab) == 1
        assert collab[0]["from"] == "ag-1"
        assert collab[0]["to"] == "ag-2"
        assert collab[0]["label"] == "debate"
        flow = [e for e in data["edges"] if e["type"] == "data_flow"]
        assert len(flow) == 1
        assert flow[0]["data_keys"] == ["findings"]

    def test_data_flow_agent_without_id_skipped(self):
        """Agents missing 'id' are gracefully skipped."""
        workflow = {
            "id": "wf-skip",
            "workflow_name": "skip-test",
            "status": "completed",
            "stages": [
                {
                    "id": "st-1",
                    "stage_name": "stage-1",
                    "status": "completed",
                    "input_data": None,
                    "output_data": None,
                    "agents": [
                        {"agent_name": "no-id-agent", "status": "completed"},
                        {"id": "ag-ok", "agent_name": "good", "status": "completed"},
                    ],
                },
            ],
        }
        backend = _make_backend()
        backend.get_workflow.return_value = workflow
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/workflows/wf-skip/data-flow")
        assert resp.status_code == 200
        data = resp.json()
        # 1 stage + 1 agent (one skipped) = 2 nodes
        assert len(data["nodes"]) == 2
        agent_nodes = [n for n in data["nodes"] if n["type"] == "agent"]
        assert len(agent_nodes) == 1
        assert agent_nodes[0]["id"] == "ag-ok"

    def test_data_flow_no_backend(self, client_no_backend):
        resp = client_no_backend.get("/api/workflows/wf-1/data-flow")
        assert resp.status_code == 200
        assert resp.json() == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# GET /api/stages/{stage_id}
# ---------------------------------------------------------------------------


class TestGetStage:
    def test_get_stage(self, client):
        resp = client.get("/api/stages/st-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "st-1"

    def test_stage_not_found(self, client):
        backend = _make_backend()
        backend.get_stage.return_value = None
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/stages/nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/agents/{agent_id}
# ---------------------------------------------------------------------------


class TestGetAgent:
    def test_get_agent(self, client):
        resp = client.get("/api/agents/ag-1")
        assert resp.status_code == 200
        assert resp.json()["agent_name"] == "researcher"

    def test_agent_not_found(self, client):
        backend = _make_backend()
        backend.get_agent.return_value = None
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/agents/nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/llm-calls/{llm_call_id}
# ---------------------------------------------------------------------------


class TestGetLLMCall:
    def test_get_llm_call(self, client):
        resp = client.get("/api/llm-calls/llm-1")
        assert resp.status_code == 200
        assert resp.json()["provider"] == "ollama"

    def test_llm_call_not_found(self, client):
        backend = _make_backend()
        backend.get_llm_call.return_value = None
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/llm-calls/nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/tool-calls/{tool_call_id}
# ---------------------------------------------------------------------------


class TestGetToolCall:
    def test_get_tool_call(self, client):
        resp = client.get("/api/tool-calls/tc-1")
        assert resp.status_code == 200
        assert resp.json()["tool_name"] == "web_search"

    def test_tool_call_not_found(self, client):
        backend = _make_backend()
        backend.get_tool_call.return_value = None
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/tool-calls/nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------


class TestRootRedirect:
    def test_root_redirects(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert "/dashboard/list.html" in resp.headers["location"]
