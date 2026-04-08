"""Integration tests for API routes.

Uses FastAPI TestClient to test endpoints without starting a real server.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.stage.loader import GraphLoader


@pytest.fixture
def app_state(tmp_path):
    """Create a test AppState with real ConfigStore and mock providers."""
    store = ConfigStore()
    loader = GraphLoader(store)
    state = AppState(
        config_store=store,
        graph_loader=loader,
        llm_providers={"mock": MagicMock()},
        memory_service=MemoryService(InMemoryStore()),
    )
    init_app_state(state)
    return state


@pytest.fixture
def client(app_state):
    """Create a FastAPI test client."""
    from temper_ai.server import app
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert "version" in body
        assert "timestamp" in body


class TestWorkflowListEndpoint:
    def test_list_workflows_returns_200(self, client):
        r = client.get("/api/workflows")
        assert r.status_code == 200
        body = r.json()
        # Response may be a list or {"runs": [], "total": 0}
        assert isinstance(body, (list, dict))


class TestRuntimeConfigEndpoint:
    def test_runtime_config_returns_200(self, client):
        r = client.get("/api/runtime-config")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)


class TestDocsEndpoints:
    def test_schema_agent(self, client):
        r = client.get("/api/docs/schemas/agent")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "agent"
        assert len(body["sections"]) > 0
        assert body["sections"][0]["class_name"] == "AgentConfig"

    def test_schema_workflow(self, client):
        r = client.get("/api/docs/schemas/workflow")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "workflow"

    def test_schema_invalid_tier(self, client):
        r = client.get("/api/docs/schemas/invalid")
        assert r.status_code == 404

    def test_examples_agent(self, client):
        r = client.get("/api/docs/examples/agent")
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "agent"
        assert isinstance(body["examples"], list)

    def test_registries(self, client):
        r = client.get("/api/docs/registries")
        assert r.status_code == 200
        body = r.json()
        assert "agent_types" in body
        assert "strategies" in body
        assert "tools" in body
        # Should have real entries
        assert len(body["agent_types"]) >= 2  # llm, script
        assert len(body["strategies"]) >= 3  # parallel, sequential, leader


class TestStudioEndpoints:
    def test_list_configs(self, client):
        r = client.get("/api/studio/configs/workflow")
        assert r.status_code == 200
        body = r.json()
        assert "configs" in body
        assert isinstance(body["configs"], list)

    def test_list_configs_agents(self, client):
        r = client.get("/api/studio/configs/agent")
        assert r.status_code == 200

    def test_get_config_not_found(self, client):
        r = client.get("/api/studio/configs/workflow/nonexistent_workflow_xyz")
        assert r.status_code == 404

    def test_registry(self, client):
        r = client.get("/api/studio/registry")
        assert r.status_code == 200
        body = r.json()
        assert "strategies" in body
        assert "agent_types" in body
        assert "tools" in body
        assert "providers" in body


class TestStartRunValidation:
    def test_invalid_workflow_returns_400(self, client):
        r = client.post("/api/runs", json={
            "workflow": "nonexistent_workflow_xyz",
            "inputs": {},
        })
        assert r.status_code == 400

    def test_missing_workflow_field(self, client):
        r = client.post("/api/runs", json={"inputs": {}})
        assert r.status_code == 422  # Pydantic validation error
