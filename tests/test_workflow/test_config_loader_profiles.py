"""Tests for ConfigLoader profile resolution."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from temper_ai.workflow.config_loader import ConfigLoader, ConfigValidationError


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory structure for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_root = Path(tmpdir)
        for sub in ("agents", "stages", "workflows", "tools", "triggers", "prompts"):
            (config_root / sub).mkdir()
        yield config_root


class TestResolveProfiles:
    """Tests for _resolve_profiles() method."""

    def test_no_tenant_skips_resolution(self, temp_config_dir):
        """No tenant_id means no profile resolution."""
        loader = ConfigLoader(config_root=temp_config_dir)
        config = {"agent": {"llm_profile": "fast-llm", "name": "test"}}
        result = loader._resolve_profiles(config, "agent")
        # Profile reference should remain untouched
        assert result["agent"]["llm_profile"] == "fast-llm"

    def test_resolve_llm_profile(self, temp_config_dir):
        """LLM profile replaces inference + context_management fields."""
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        config = {"agent": {"llm_profile": "fast-llm", "name": "test"}}
        profile_data = {
            "inference": {"provider": "openai", "model": "gpt-4"},
            "context_management": {"strategy": "sliding_window"},
        }

        with patch.object(loader, "_load_profile_from_db", return_value=profile_data):
            result = loader._resolve_profiles(config, "agent")

        assert result["agent"]["inference"] == {"provider": "openai", "model": "gpt-4"}
        assert result["agent"]["context_management"] == {"strategy": "sliding_window"}
        assert "llm_profile" not in result["agent"]

    def test_resolve_safety_profile(self, temp_config_dir):
        """Safety profile resolves on agent config."""
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        config = {"agent": {"safety_profile": "strict", "name": "test"}}
        profile_data = {
            "safety": {"max_tokens": 1000},
            "autonomy": {"level": "supervised"},
        }

        with patch.object(loader, "_load_profile_from_db", return_value=profile_data):
            result = loader._resolve_profiles(config, "agent")

        assert result["agent"]["safety"] == {"max_tokens": 1000}
        assert result["agent"]["autonomy"] == {"level": "supervised"}
        assert "safety_profile" not in result["agent"]

    def test_resolve_error_handling_profile_on_stage(self, temp_config_dir):
        """Error handling profile resolves on stage config."""
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        config = {"stage": {"error_handling_profile": "retry-3x", "name": "test"}}
        profile_data = {"max_retries": 3, "backoff": "exponential"}

        with patch.object(loader, "_load_profile_from_db", return_value=profile_data):
            result = loader._resolve_profiles(config, "stage")

        assert result["stage"]["error_handling"] == profile_data
        assert "error_handling_profile" not in result["stage"]

    def test_resolve_observability_profile(self, temp_config_dir):
        """Observability profile resolves correctly."""
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        config = {"workflow": {"observability_profile": "verbose", "name": "test"}}
        profile_data = {"log_level": "DEBUG", "trace_enabled": True}

        with patch.object(loader, "_load_profile_from_db", return_value=profile_data):
            result = loader._resolve_profiles(config, "workflow")

        assert result["workflow"]["observability"] == profile_data

    def test_resolve_memory_profile(self, temp_config_dir):
        """Memory profile resolves correctly."""
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        config = {"agent": {"memory_profile": "rag-default", "name": "test"}}
        profile_data = {"provider": "chromadb", "embedding_model": "ada-002"}

        with patch.object(loader, "_load_profile_from_db", return_value=profile_data):
            result = loader._resolve_profiles(config, "agent")

        assert result["agent"]["memory"] == profile_data

    def test_resolve_budget_profile(self, temp_config_dir):
        """Budget profile resolves nested config.budget + config.rate_limit."""
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        config = {"workflow": {"budget_profile": "enterprise", "name": "test"}}
        profile_data = {
            "config.budget": {"max_cost": 100.0},
            "config.rate_limit": {"requests_per_minute": 60},
        }

        with patch.object(loader, "_load_profile_from_db", return_value=profile_data):
            result = loader._resolve_profiles(config, "workflow")

        assert result["workflow"]["config"]["budget"] == {"max_cost": 100.0}
        assert result["workflow"]["config"]["rate_limit"] == {"requests_per_minute": 60}
        assert "budget_profile" not in result["workflow"]

    def test_profile_not_found_raises(self, temp_config_dir):
        """Missing profile raises ConfigValidationError."""
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        config = {"agent": {"llm_profile": "nonexistent", "name": "test"}}

        with patch.object(loader, "_load_profile_from_db", return_value=None):
            with pytest.raises(ConfigValidationError, match="not found"):
                loader._resolve_profiles(config, "agent")

    def test_inline_config_unaffected(self, temp_config_dir):
        """Config without profile refs is unchanged."""
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        config = {
            "agent": {
                "name": "test",
                "inference": {"provider": "ollama"},
            }
        }
        original = config.copy()

        result = loader._resolve_profiles(config, "agent")
        assert result["agent"]["inference"] == {"provider": "ollama"}
        assert "llm_profile" not in result["agent"]

    def test_multiple_profiles_resolved(self, temp_config_dir):
        """Multiple profile references resolved in same config."""
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        config = {
            "agent": {
                "name": "test",
                "llm_profile": "fast",
                "safety_profile": "strict",
            }
        }

        def mock_load(profile_type, name, tenant_id):
            if profile_type == "llm":
                return {"inference": {"provider": "openai", "model": "gpt-4"}}
            if profile_type == "safety":
                return {"safety": {"max_tokens": 500}}
            return None

        with patch.object(loader, "_load_profile_from_db", side_effect=mock_load):
            result = loader._resolve_profiles(config, "agent")

        assert result["agent"]["inference"] == {"provider": "openai", "model": "gpt-4"}
        assert result["agent"]["safety"] == {"max_tokens": 500}
        assert "llm_profile" not in result["agent"]
        assert "safety_profile" not in result["agent"]


class TestApplyProfileData:
    """Tests for _apply_profile_data() static method."""

    def test_single_field(self):
        inner = {}
        ConfigLoader._apply_profile_data(inner, ["inference"], {"provider": "openai"})
        assert inner["inference"] == {"provider": "openai"}

    def test_nested_field(self):
        inner = {}
        ConfigLoader._apply_profile_data(inner, ["config.budget"], {"max_cost": 100})
        assert inner["config"]["budget"] == {"max_cost": 100}

    def test_multi_target(self):
        inner = {}
        profile_data = {
            "inference": {"provider": "openai"},
            "context_management": {"strategy": "sliding_window"},
        }
        ConfigLoader._apply_profile_data(
            inner, ["inference", "context_management"], profile_data
        )
        assert inner["inference"] == {"provider": "openai"}
        assert inner["context_management"] == {"strategy": "sliding_window"}

    def test_multi_target_partial(self):
        """Multi-target with only some keys present."""
        inner = {}
        profile_data = {"inference": {"provider": "openai"}}
        ConfigLoader._apply_profile_data(
            inner, ["inference", "context_management"], profile_data
        )
        assert inner["inference"] == {"provider": "openai"}
        assert "context_management" not in inner


class TestLoadProfileFromDb:
    """Tests for _load_profile_from_db() method."""

    def test_returns_none_for_unknown_profile_type(self, temp_config_dir):
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        result = loader._load_profile_from_db("unknown", "test", "t1")
        assert result is None

    def test_returns_none_on_db_error(self, temp_config_dir):
        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")
        with patch(
            "temper_ai.storage.database.manager.get_session",
            side_effect=RuntimeError("DB down"),
        ):
            result = loader._load_profile_from_db("llm", "test", "t1")
        assert result is None


class TestProfileIntegrationWithLoadConfig:
    """Test that profiles are resolved during config loading."""

    def test_filesystem_config_with_profile(self, temp_config_dir):
        """Profile resolved when loading from filesystem."""
        agent_config = {
            "agent": {
                "name": "test",
                "llm_profile": "fast",
            }
        }
        agent_path = temp_config_dir / "agents" / "test.yaml"
        with open(agent_path, "w") as f:
            yaml.dump(agent_config, f)

        loader = ConfigLoader(config_root=temp_config_dir, tenant_id="t1")

        profile_data = {
            "inference": {"provider": "openai", "model": "gpt-4"},
        }

        with patch.object(loader, "_load_profile_from_db", return_value=profile_data):
            result = loader.load_agent("test", validate=False)

        assert result["agent"]["inference"] == {"provider": "openai", "model": "gpt-4"}
        assert "llm_profile" not in result["agent"]
