"""Tests for Workflow Studio REST API routes."""
import pytest
import yaml
from fastapi import FastAPI
from starlette.testclient import TestClient

from temper_ai.interfaces.dashboard.studio_routes import create_studio_router
from temper_ai.interfaces.dashboard.studio_service import StudioService


# ---------------------------------------------------------------------------
# Sample valid config data for each type
# ---------------------------------------------------------------------------

VALID_AGENT_DATA = {
    "agent": {
        "name": "test_agent",
        "description": "A test agent",
        "version": "1.0",
        "type": "standard",
        "prompt": {"inline": "You are a helpful assistant."},
        "inference": {
            "provider": "ollama",
            "model": "qwen3",
        },
        "error_handling": {
            "retry_strategy": "ExponentialBackoff",
            "max_retries": 3,
            "fallback": "GracefulDegradation",
            "escalate_to_human_after": 3,
        },
    }
}

VALID_STAGE_DATA = {
    "stage": {
        "name": "test_stage",
        "description": "A test stage",
        "version": "1.0",
        "agents": ["test_agent"],
    }
}

VALID_WORKFLOW_DATA = {
    "workflow": {
        "name": "test_workflow",
        "description": "A test workflow",
        "version": "1.0",
        "stages": [
            {"name": "step1", "stage_ref": "configs/stages/test_stage.yaml"},
        ],
        "error_handling": {
            "on_stage_failure": "halt",
            "max_stage_retries": 2,
            "escalation_policy": "default",
            "enable_rollback": False,
        },
    }
}

VALID_TOOL_DATA = {
    "tool": {
        "name": "test_tool",
        "description": "A test tool",
        "version": "1.0",
        "implementation": "temper_ai.tools.calculator.CalculatorTool",
    }
}

# Map from config type to valid sample data
_VALID_DATA = {
    "agents": VALID_AGENT_DATA,
    "stages": VALID_STAGE_DATA,
    "workflows": VALID_WORKFLOW_DATA,
    "tools": VALID_TOOL_DATA,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config_root(tmp_path):
    """Create a temporary config directory pre-populated with sample configs."""
    for subdir in ("workflows", "stages", "agents", "tools"):
        (tmp_path / subdir).mkdir()

    for config_type, data in _VALID_DATA.items():
        wrapper_key = list(data.keys())[0]
        name = data[wrapper_key]["name"]
        path = tmp_path / config_type / f"{name}.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    return tmp_path


@pytest.fixture()
def client(config_root):
    """Create a TestClient with the studio router mounted at /api/studio."""
    service = StudioService(config_root=str(config_root))
    app = FastAPI()
    app.include_router(create_studio_router(service), prefix="/api/studio")
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/studio/configs/{config_type}
# ---------------------------------------------------------------------------


class TestListConfigsEndpoint:
    def test_list_configs_endpoint(self, client):
        resp = client.get("/api/studio/configs/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert "configs" in data
        assert "total" in data
        assert isinstance(data["configs"], list)
        assert data["total"] >= 1

    def test_list_configs_agents(self, client):
        resp = client.get("/api/studio/configs/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1


# ---------------------------------------------------------------------------
# GET /api/studio/configs/{config_type}/{name}
# ---------------------------------------------------------------------------


class TestGetConfigEndpoint:
    def test_get_config_endpoint(self, client):
        resp = client.get("/api/studio/configs/workflows/test_workflow")
        assert resp.status_code == 200
        data = resp.json()
        assert "workflow" in data
        assert data["workflow"]["name"] == "test_workflow"

    def test_get_config_not_found(self, client):
        resp = client.get("/api/studio/configs/workflows/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/studio/configs/{config_type}/{name}/raw
# ---------------------------------------------------------------------------


class TestGetConfigRaw:
    def test_get_config_raw(self, client):
        resp = client.get("/api/studio/configs/agents/test_agent/raw")
        assert resp.status_code == 200
        assert "text/yaml" in resp.headers["content-type"]
        # Should be valid YAML text
        parsed = yaml.safe_load(resp.text)
        assert isinstance(parsed, dict)
        assert "agent" in parsed

    def test_get_config_raw_not_found(self, client):
        resp = client.get("/api/studio/configs/agents/does_not_exist/raw")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/studio/configs/{config_type}/{name}
# ---------------------------------------------------------------------------


class TestCreateConfigEndpoint:
    def test_create_config_endpoint(self, client):
        new_data = {
            "agent": {
                "name": "created_agent",
                "description": "Created via API",
                "version": "1.0",
                "type": "standard",
                "prompt": {"inline": "Hello."},
                "inference": {"provider": "ollama", "model": "llama3"},
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "max_retries": 3,
                    "fallback": "GracefulDegradation",
                    "escalate_to_human_after": 3,
                },
            }
        }
        resp = client.post("/api/studio/configs/agents/created_agent", json=new_data)
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent"]["name"] == "created_agent"

    def test_create_config_conflict(self, client):
        # test_agent already exists
        resp = client.post("/api/studio/configs/agents/test_agent", json=VALID_AGENT_DATA)
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PUT /api/studio/configs/{config_type}/{name}
# ---------------------------------------------------------------------------


class TestUpdateConfigEndpoint:
    def test_update_config_endpoint(self, client):
        updated_data = {
            "agent": {
                "name": "test_agent",
                "description": "Updated via API",
                "version": "2.0",
                "type": "standard",
                "prompt": {"inline": "Updated prompt."},
                "inference": {"provider": "ollama", "model": "llama3"},
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "max_retries": 3,
                    "fallback": "GracefulDegradation",
                    "escalate_to_human_after": 3,
                },
            }
        }
        resp = client.put("/api/studio/configs/agents/test_agent", json=updated_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"]["description"] == "Updated via API"

    def test_update_config_not_found(self, client):
        resp = client.put("/api/studio/configs/agents/no_such_agent", json=VALID_AGENT_DATA)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/studio/configs/{config_type}/{name}
# ---------------------------------------------------------------------------


class TestDeleteConfigEndpoint:
    def test_delete_config_endpoint(self, client, config_root):
        # Create a config to delete
        create_data = {
            "agent": {
                "name": "to_delete",
                "description": "Will be deleted",
                "version": "1.0",
                "type": "standard",
                "prompt": {"inline": "Bye."},
                "inference": {"provider": "ollama", "model": "qwen3"},
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "max_retries": 3,
                    "fallback": "GracefulDegradation",
                    "escalate_to_human_after": 3,
                },
            }
        }
        resp = client.post("/api/studio/configs/agents/to_delete", json=create_data)
        assert resp.status_code == 201

        # Delete it
        resp = client.delete("/api/studio/configs/agents/to_delete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == "agents/to_delete"

        # Confirm it's gone
        resp = client.get("/api/studio/configs/agents/to_delete")
        assert resp.status_code == 404

    def test_delete_config_not_found(self, client):
        resp = client.delete("/api/studio/configs/agents/ghost")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/studio/validate/{config_type}
# ---------------------------------------------------------------------------


class TestValidateEndpoint:
    def test_validate_valid(self, client):
        resp = client.post("/api/studio/validate/workflows", json=VALID_WORKFLOW_DATA)
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["errors"] == []

    def test_validate_invalid(self, client):
        invalid_data = {"workflow": {"name": "bad"}}
        resp = client.post("/api/studio/validate/workflows", json=invalid_data)
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0


# ---------------------------------------------------------------------------
# GET /api/studio/schemas/{config_type}
# ---------------------------------------------------------------------------


class TestGetSchemaEndpoint:
    def test_get_schema_endpoint(self, client):
        resp = client.get("/api/studio/schemas/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert "properties" in data


# ---------------------------------------------------------------------------
# Invalid config type / invalid name
# ---------------------------------------------------------------------------


class TestInvalidConfigType:
    def test_invalid_config_type(self, client):
        resp = client.get("/api/studio/configs/invalid_type")
        assert resp.status_code == 400

    def test_invalid_config_type_validate(self, client):
        resp = client.post("/api/studio/validate/invalid_type", json={})
        assert resp.status_code == 400

    def test_invalid_config_type_schema(self, client):
        resp = client.get("/api/studio/schemas/invalid_type")
        assert resp.status_code == 400


class TestInvalidName:
    def test_invalid_name_path_traversal(self, client):
        resp = client.get("/api/studio/configs/workflows/../../etc")
        # FastAPI may not route this, but the service should reject it
        # The double-dot path segment may be handled by the router differently
        assert resp.status_code in (400, 404, 422)

    def test_invalid_name_with_dots(self, client):
        resp = client.get("/api/studio/configs/workflows/..%2F..%2Fetc")
        # URL-encoded traversal attempt
        assert resp.status_code in (400, 404)
