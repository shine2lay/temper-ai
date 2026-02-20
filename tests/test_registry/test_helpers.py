"""Tests for temper_ai.registry._helpers."""
import tempfile
import os

import pytest
import yaml

from temper_ai.registry._helpers import (
    build_memory_namespace,
    build_persistent_memory_config,
    generate_agent_id,
    load_config_from_path,
)
from temper_ai.registry.constants import PERSISTENT_NAMESPACE_PREFIX


class TestBuildMemoryNamespace:
    def test_prefix_is_applied(self):
        result = build_memory_namespace("my-agent")
        assert result == f"{PERSISTENT_NAMESPACE_PREFIX}my-agent"

    def test_different_agents(self):
        assert build_memory_namespace("agent-a") != build_memory_namespace("agent-b")

    def test_starts_with_prefix(self):
        ns = build_memory_namespace("test")
        assert ns.startswith(PERSISTENT_NAMESPACE_PREFIX)


class TestBuildPersistentMemoryConfig:
    def test_returns_dict(self):
        cfg = build_persistent_memory_config("my-agent")
        assert isinstance(cfg, dict)

    def test_enabled_true(self):
        cfg = build_persistent_memory_config("my-agent")
        assert cfg["enabled"] is True

    def test_namespace_matches_helper(self):
        cfg = build_persistent_memory_config("my-agent")
        assert cfg["namespace"] == build_memory_namespace("my-agent")


class TestGenerateAgentId:
    def test_returns_string(self):
        agent_id = generate_agent_id()
        assert isinstance(agent_id, str)

    def test_unique(self):
        ids = {generate_agent_id() for _ in range(10)}
        assert len(ids) == 10

    def test_non_empty(self):
        assert generate_agent_id() != ""

    def test_hex_format(self):
        agent_id = generate_agent_id()
        int(agent_id, 16)  # Raises if not valid hex


class TestLoadConfigFromPath:
    def test_loads_valid_yaml(self):
        data = {"name": "my-agent", "type": "standard"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as fh:
            yaml.dump(data, fh)
            path = fh.name
        try:
            result = load_config_from_path(path)
            assert result["name"] == "my-agent"
            assert result["type"] == "standard"
        finally:
            os.unlink(path)

    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config_from_path("/does/not/exist.yaml")

    def test_raises_value_error_for_non_mapping(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as fh:
            fh.write("- item1\n- item2\n")
            path = fh.name
        try:
            with pytest.raises(ValueError, match="must be a YAML mapping"):
                load_config_from_path(path)
        finally:
            os.unlink(path)
