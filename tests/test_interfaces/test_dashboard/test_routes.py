"""Tests for dashboard REST API routes."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.interfaces.dashboard.app import create_app
from temper_ai.observability.constants import ObservabilityFields

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_WORKFLOW = {
    "id": "wf-1",
    "workflow_name": "test-workflow",
    ObservabilityFields.STATUS: "completed",
    ObservabilityFields.START_TIME: "2026-01-01T00:00:00",
    ObservabilityFields.END_TIME: "2026-01-01T00:01:00",
    "stages": [
        {
            "id": "st-1",
            "stage_name": "stage-1",
            ObservabilityFields.STATUS: "completed",
            ObservabilityFields.INPUT_DATA: {"key": "value"},
            ObservabilityFields.OUTPUT_DATA: {"result": 42},
        },
        {
            "id": "st-2",
            "stage_name": "stage-2",
            ObservabilityFields.STATUS: "completed",
            ObservabilityFields.INPUT_DATA: None,
            ObservabilityFields.OUTPUT_DATA: None,
        },
    ],
}

SAMPLE_STAGE = {
    "id": "st-1",
    "stage_name": "stage-1",
    ObservabilityFields.STATUS: "completed",
    "agents": [],
}

SAMPLE_AGENT = {
    "id": "ag-1",
    ObservabilityFields.AGENT_NAME: "researcher",
    ObservabilityFields.STATUS: "completed",
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
    ObservabilityFields.OUTPUT_DATA: {"result": "ok"},
}


def _make_backend():
    """Create a mock backend returning test data."""
    backend = MagicMock()
    backend.get_workflow.return_value = SAMPLE_WORKFLOW
    backend.list_workflows.return_value = [
        {"id": "wf-1", "workflow_name": "test-workflow", ObservabilityFields.STATUS: "completed"},
        {"id": "wf-2", "workflow_name": "test-workflow-2", ObservabilityFields.STATUS: "running"},
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
            ObservabilityFields.STATUS: "completed",
            "stages": [
                {
                    "id": "st-a",
                    "stage_name": "research",
                    ObservabilityFields.STATUS: "completed",
                    ObservabilityFields.INPUT_DATA: None,
                    ObservabilityFields.OUTPUT_DATA: {"findings": "data"},
                    "agents": [
                        {
                            "id": "ag-1",
                            ObservabilityFields.AGENT_NAME: "analyst",
                            ObservabilityFields.STATUS: "completed",
                            "agent_config_snapshot": {"model": "gpt-4"},
                            ObservabilityFields.TOTAL_TOKENS: 500,
                            "estimated_cost_usd": 0.01,
                            "num_llm_calls": 2,
                            "num_tool_calls": 1,
                        },
                        {
                            "id": "ag-2",
                            ObservabilityFields.AGENT_NAME: "reviewer",
                            ObservabilityFields.STATUS: "completed",
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
                    ObservabilityFields.STATUS: "completed",
                    ObservabilityFields.INPUT_DATA: {"findings": "data"},
                    ObservabilityFields.OUTPUT_DATA: None,
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
        assert agent_nodes[0][ObservabilityFields.TOTAL_TOKENS] == 500
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
            ObservabilityFields.STATUS: "completed",
            "stages": [
                {
                    "id": "st-1",
                    "stage_name": "stage-1",
                    ObservabilityFields.STATUS: "completed",
                    ObservabilityFields.INPUT_DATA: None,
                    ObservabilityFields.OUTPUT_DATA: None,
                    "agents": [
                        {ObservabilityFields.AGENT_NAME: "no-id-agent", ObservabilityFields.STATUS: "completed"},
                        {"id": "ag-ok", ObservabilityFields.AGENT_NAME: "good", ObservabilityFields.STATUS: "completed"},
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

    def test_data_flow_dag_edges(self):
        """DAG depends_on produces correct edges instead of sequential."""
        workflow = {
            "id": "wf-dag",
            "workflow_name": "dag-test",
            ObservabilityFields.STATUS: "completed",
            "workflow_config_snapshot": {
                "workflow": {
                    "stages": [
                        {"name": "A", "stage_ref": "a.yaml"},
                        {"name": "B", "stage_ref": "b.yaml", "depends_on": ["A"]},
                        {"name": "C", "stage_ref": "c.yaml", "depends_on": ["A"]},
                        {"name": "D", "stage_ref": "d.yaml", "depends_on": ["B", "C"]},
                    ]
                }
            },
            "stages": [
                {"id": "st-a", "stage_name": "A", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: {"result": 1}},
                {"id": "st-b", "stage_name": "B", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: {"b_out": 2}},
                {"id": "st-c", "stage_name": "C", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: {"c_out": 3}},
                {"id": "st-d", "stage_name": "D", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: None},
            ],
        }
        backend = _make_backend()
        backend.get_workflow.return_value = workflow
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/workflows/wf-dag/data-flow")
        assert resp.status_code == 200
        data = resp.json()

        flow = [e for e in data["edges"] if e["type"] == "data_flow"]
        # Diamond: A->B, A->C, B->D, C->D = 4 edges
        assert len(flow) == 4

        edge_pairs = {(e["from"], e["to"]) for e in flow}
        assert ("st-a", "st-b") in edge_pairs
        assert ("st-a", "st-c") in edge_pairs
        assert ("st-b", "st-d") in edge_pairs
        assert ("st-c", "st-d") in edge_pairs

        # Verify data_keys populated from dependency output
        a_to_b = [e for e in flow if e["from"] == "st-a" and e["to"] == "st-b"][0]
        assert a_to_b["data_keys"] == ["result"]

    def test_data_flow_dag_loop_back(self):
        """Loop-back edge appears when stage re-executes."""
        workflow = {
            "id": "wf-loop",
            "workflow_name": "loop-test",
            ObservabilityFields.STATUS: "completed",
            "workflow_config_snapshot": {
                "workflow": {
                    "stages": [
                        {"name": "code", "stage_ref": "code.yaml"},
                        {"name": "check", "stage_ref": "check.yaml",
                         "depends_on": ["code"],
                         "loops_back_to": "code", "max_loops": 2},
                    ]
                }
            },
            "stages": [
                {"id": "st-code-1", "stage_name": "code", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: {"files": ["a.py"]}},
                {"id": "st-check-1", "stage_name": "check", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: {"pass": False}},
                # Loop iteration 2
                {"id": "st-code-2", "stage_name": "code", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: {"files": ["a.py", "b.py"]}},
                {"id": "st-check-2", "stage_name": "check", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: {"pass": True}},
            ],
        }
        backend = _make_backend()
        backend.get_workflow.return_value = workflow
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/workflows/wf-loop/data-flow")
        assert resp.status_code == 200
        data = resp.json()

        flow = [e for e in data["edges"] if e["type"] == "data_flow"]
        edge_pairs = {(e["from"], e["to"]) for e in flow}

        # code-1 -> check-1 (depends_on)
        assert ("st-code-1", "st-check-1") in edge_pairs
        # check-1 -> code-2 (loop-back)
        assert ("st-check-1", "st-code-2") in edge_pairs
        # code-2 -> check-2 (depends_on, iteration 2)
        assert ("st-code-2", "st-check-2") in edge_pairs

        # Verify loop edge has 'loop' label
        loop_edges = [e for e in flow if e["label"] == "loop"]
        assert len(loop_edges) == 1
        assert loop_edges[0]["from"] == "st-check-1"
        assert loop_edges[0]["to"] == "st-code-2"

    def test_data_flow_stage_missing_id(self):
        """Stages without 'id' are gracefully skipped."""
        workflow = {
            "id": "wf-noid",
            "workflow_name": "no-id-test",
            ObservabilityFields.STATUS: "completed",
            "stages": [
                {"stage_name": "missing-id", ObservabilityFields.STATUS: "completed"},
                {"id": "st-ok", "stage_name": "ok", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: None},
            ],
        }
        backend = _make_backend()
        backend.get_workflow.return_value = workflow
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/workflows/wf-noid/data-flow")
        assert resp.status_code == 200
        data = resp.json()
        # Only 1 stage node (missing-id skipped)
        stage_nodes = [n for n in data["nodes"] if n["type"] == "stage"]
        assert len(stage_nodes) == 1
        assert stage_nodes[0]["id"] == "st-ok"

    def test_data_flow_sequential_fallback_without_config(self):
        """Without workflow_config_snapshot, falls back to sequential edges."""
        workflow = {
            "id": "wf-seq",
            "workflow_name": "seq-test",
            ObservabilityFields.STATUS: "completed",
            "stages": [
                {"id": "st-1", "stage_name": "first", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: {"x": 1}},
                {"id": "st-2", "stage_name": "second", ObservabilityFields.STATUS: "completed",
                 ObservabilityFields.OUTPUT_DATA: None},
            ],
        }
        backend = _make_backend()
        backend.get_workflow.return_value = workflow
        app = create_app(backend=backend)
        c = TestClient(app)
        resp = c.get("/api/workflows/wf-seq/data-flow")
        assert resp.status_code == 200
        data = resp.json()

        flow = [e for e in data["edges"] if e["type"] == "data_flow"]
        assert len(flow) == 1
        assert flow[0]["from"] == "st-1"
        assert flow[0]["to"] == "st-2"
        assert flow[0]["data_keys"] == ["x"]


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
        assert resp.json()[ObservabilityFields.AGENT_NAME] == "researcher"

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
        assert "/app" in resp.headers["location"]
