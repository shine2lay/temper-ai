"""Tests for StudioService business logic layer."""
import pytest
import yaml

from src.dashboard.studio_service import StudioService, VALID_CONFIG_TYPES


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
        "implementation": "src.tools.calculator.CalculatorTool",
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
    # Create subdirectories
    for subdir in ("workflows", "stages", "agents", "tools"):
        (tmp_path / subdir).mkdir()

    # Write one sample config per type
    for config_type, data in _VALID_DATA.items():
        wrapper_key = list(data.keys())[0]  # e.g. "agent", "stage"
        name = data[wrapper_key]["name"]
        path = tmp_path / config_type / f"{name}.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    return tmp_path


@pytest.fixture()
def service(config_root):
    """Create a StudioService backed by the temporary config root."""
    return StudioService(config_root=str(config_root))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListConfigs:
    """Test listing configs for each type."""

    @pytest.mark.parametrize("config_type", sorted(VALID_CONFIG_TYPES))
    def test_list_configs(self, service, config_type):
        result = service.list_configs(config_type)
        assert "configs" in result
        assert "total" in result
        assert isinstance(result["configs"], list)
        assert result["total"] == len(result["configs"])
        # We seeded one config per type
        assert result["total"] >= 1


class TestGetConfig:
    """Test getting a single config."""

    def test_get_config(self, service):
        result = service.get_config("agents", "test_agent")
        assert isinstance(result, dict)
        assert "agent" in result
        assert result["agent"]["name"] == "test_agent"

    def test_get_config_not_found(self, service):
        with pytest.raises(FileNotFoundError):
            service.get_config("agents", "nonexistent_agent")


class TestGetConfigRaw:
    """Test getting raw YAML text."""

    def test_get_config_raw(self, service):
        raw = service.get_config_raw("agents", "test_agent")
        assert isinstance(raw, str)
        # Should be parseable YAML
        parsed = yaml.safe_load(raw)
        assert isinstance(parsed, dict)
        assert "agent" in parsed


class TestValidateConfig:
    """Test config validation."""

    def test_validate_config_valid(self, service):
        result = service.validate_config("agents", VALID_AGENT_DATA)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_validate_config_invalid(self, service):
        # Missing required fields
        invalid_data = {"agent": {"name": "bad"}}
        result = service.validate_config("agents", invalid_data)
        assert result["valid"] is False
        assert len(result["errors"]) > 0


class TestGetSchema:
    """Test JSON schema retrieval."""

    @pytest.mark.parametrize("config_type", sorted(VALID_CONFIG_TYPES))
    def test_get_schema(self, service, config_type):
        schema = service.get_schema(config_type)
        assert isinstance(schema, dict)
        assert "properties" in schema
        # Pydantic v2 uses $defs; some schemas may have definitions
        has_defs = "$defs" in schema or "definitions" in schema
        # Not all simple schemas will have $defs, but properties is required
        assert "properties" in schema


class TestCreateConfig:
    """Test creating new configs."""

    def test_create_config(self, service, config_root):
        new_data = {
            "agent": {
                "name": "new_agent",
                "description": "A brand new agent",
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
        result = service.create_config("agents", "new_agent", new_data)
        assert result == new_data

        # Verify the file was created
        file_path = config_root / "agents" / "new_agent.yaml"
        assert file_path.exists()

        # Cleanup
        service.delete_config("agents", "new_agent")
        assert not file_path.exists()

    def test_create_config_duplicate(self, service):
        with pytest.raises(FileExistsError):
            service.create_config("agents", "test_agent", VALID_AGENT_DATA)


class TestUpdateConfig:
    """Test updating existing configs."""

    def test_update_config(self, service, config_root):
        # Create first
        create_data = {
            "agent": {
                "name": "update_me",
                "description": "Original description",
                "version": "1.0",
                "type": "standard",
                "prompt": {"inline": "Original prompt."},
                "inference": {"provider": "ollama", "model": "qwen3"},
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "max_retries": 3,
                    "fallback": "GracefulDegradation",
                    "escalate_to_human_after": 3,
                },
            }
        }
        service.create_config("agents", "update_me", create_data)

        # Update
        updated_data = {
            "agent": {
                "name": "update_me",
                "description": "Updated description",
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
        result = service.update_config("agents", "update_me", updated_data)
        assert result["agent"]["description"] == "Updated description"

        # Verify file content changed
        raw = service.get_config_raw("agents", "update_me")
        parsed = yaml.safe_load(raw)
        assert parsed["agent"]["version"] == "2.0"

        # Cleanup
        service.delete_config("agents", "update_me")


class TestDeleteConfig:
    """Test deleting configs."""

    def test_delete_config(self, service, config_root):
        # Create a config to delete
        data = {
            "agent": {
                "name": "delete_me",
                "description": "To be deleted",
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
        service.create_config("agents", "delete_me", data)
        file_path = config_root / "agents" / "delete_me.yaml"
        assert file_path.exists()

        result = service.delete_config("agents", "delete_me")
        assert result["deleted"] == "agents/delete_me"
        assert not file_path.exists()


class TestValidateName:
    """Test name validation for invalid characters."""

    def test_validate_name_invalid(self, service):
        with pytest.raises(ValueError, match="Invalid config name"):
            service.get_config("agents", "../foo")

    def test_validate_name_with_slash(self, service):
        with pytest.raises(ValueError, match="Invalid config name"):
            service.get_config("agents", "../../etc")

    def test_validate_name_empty(self, service):
        with pytest.raises(ValueError, match="Invalid config name"):
            service.get_config("agents", "")


class TestInvalidConfigType:
    """Test invalid config type validation."""

    def test_invalid_config_type(self, service):
        with pytest.raises(ValueError, match="Invalid config type"):
            service.list_configs("invalid")

    def test_invalid_config_type_get(self, service):
        with pytest.raises(ValueError, match="Invalid config type"):
            service.get_config("invalid", "test")

    def test_invalid_config_type_validate(self, service):
        with pytest.raises(ValueError, match="Invalid config type"):
            service.validate_config("invalid", {})

    def test_invalid_config_type_schema(self, service):
        with pytest.raises(ValueError, match="Invalid config type"):
            service.get_schema("invalid")
