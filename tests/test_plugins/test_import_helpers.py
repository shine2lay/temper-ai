"""Tests for plugin import helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from temper_ai.plugins._import_helpers import (
    _sanitize_name,
    build_agent_config_dict,
    load_yaml_safe,
    write_agent_yaml,
)


class TestLoadYamlSafe:
    def test_valid_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "test.yaml"
        f.write_text("key: value\n")
        result = load_yaml_safe(f)
        assert result == {"key": "value"}

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_yaml_safe(tmp_path / "missing.yaml")

    def test_invalid_yaml_not_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "test.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="Expected YAML dict"):
            load_yaml_safe(f)

    def test_nested_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "test.yaml"
        f.write_text("agents:\n  - role: Researcher\n    goal: Research\n")
        result = load_yaml_safe(f)
        assert "agents" in result
        assert result["agents"][0]["role"] == "Researcher"

    def test_empty_dict_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "test.yaml"
        f.write_text("{}\n")
        result = load_yaml_safe(f)
        assert result == {}


class TestSanitizeName:
    def test_basic_name(self) -> None:
        assert _sanitize_name("my_agent") == "my_agent"

    def test_special_chars(self) -> None:
        result = _sanitize_name("my agent!@#")
        assert " " not in result
        assert "!" not in result

    def test_empty_name(self) -> None:
        assert _sanitize_name("") == "unnamed_agent"

    def test_long_name_truncated(self) -> None:
        name = "a" * 100
        result = _sanitize_name(name)
        assert len(result) <= 64  # scanner: skip-magic

    def test_lowercase(self) -> None:
        result = _sanitize_name("MyAgent")
        assert result == result.lower()

    def test_hyphen_preserved(self) -> None:
        result = _sanitize_name("my-agent")
        assert "-" in result


class TestBuildAgentConfigDict:
    def test_basic_config(self) -> None:
        result = build_agent_config_dict(
            name="test",
            description="A test agent",
            agent_type="crewai",
            plugin_config={"framework": "crewai"},
        )
        assert result["agent"]["name"] == "test"
        assert result["agent"]["type"] == "crewai"
        assert result["agent"]["plugin_config"]["framework"] == "crewai"
        assert "error_handling" in result["agent"]

    def test_custom_version(self) -> None:
        result = build_agent_config_dict(
            name="test",
            description="d",
            agent_type="t",
            plugin_config={},
            version="2.0",
        )
        assert result["agent"]["version"] == "2.0"

    def test_default_version(self) -> None:
        result = build_agent_config_dict(
            name="test",
            description="d",
            agent_type="t",
            plugin_config={},
        )
        assert result["agent"]["version"] == "1.0"

    def test_description_preserved(self) -> None:
        result = build_agent_config_dict(
            name="test",
            description="My agent description",
            agent_type="crewai",
            plugin_config={},
        )
        assert result["agent"]["description"] == "My agent description"

    def test_error_handling_has_retry(self) -> None:
        result = build_agent_config_dict(
            name="test",
            description="d",
            agent_type="t",
            plugin_config={},
        )
        assert "max_retries" in result["agent"]["error_handling"]

    def test_name_is_sanitized(self) -> None:
        result = build_agent_config_dict(
            name="My Agent!",
            description="d",
            agent_type="t",
            plugin_config={},
        )
        assert " " not in result["agent"]["name"]
        assert "!" not in result["agent"]["name"]


class TestWriteAgentYaml:
    def test_writes_files(self, tmp_path: Path) -> None:
        configs = [
            {"agent": {"name": "agent_one", "type": "crewai"}},
            {"agent": {"name": "agent_two", "type": "crewai"}},
        ]
        written = write_agent_yaml(configs, tmp_path)
        assert len(written) == 2
        for p in written:
            assert p.exists()
            data = yaml.safe_load(p.read_text())
            assert "agent" in data

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "dir"
        configs = [{"agent": {"name": "a", "type": "crewai"}}]
        written = write_agent_yaml(configs, out)
        assert len(written) == 1
        assert out.exists()

    def test_empty_configs_returns_empty(self, tmp_path: Path) -> None:
        written = write_agent_yaml([], tmp_path)
        assert written == []

    def test_file_named_after_agent(self, tmp_path: Path) -> None:
        configs = [{"agent": {"name": "my_agent", "type": "crewai"}}]
        written = write_agent_yaml(configs, tmp_path)
        assert written[0].name == "my_agent.yaml"

    def test_yaml_content_valid(self, tmp_path: Path) -> None:
        configs = [
            {"agent": {"name": "test", "type": "crewai", "data": {"key": "val"}}}
        ]
        written = write_agent_yaml(configs, tmp_path)
        data = yaml.safe_load(written[0].read_text())
        assert data["agent"]["data"]["key"] == "val"
