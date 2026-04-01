"""Tests for config/helpers.py — YAML loading, env var substitution, security checks."""

import json
import os
from pathlib import Path

import pytest

from temper_ai.config.helpers import (
    ConfigNotFoundError,
    ConfigValidationError,
    SchemaVersionError,
    check_schema_version,
    detect_config_type,
    load_yaml_file,
    substitute_env_vars,
)


class TestLoadYamlFile:
    def test_load_valid_yaml(self, tmp_path):
        f = tmp_path / "test.yaml"
        f.write_text("name: test\nversion: '1.0'\n")
        result = load_yaml_file(f)
        assert result == {"name": "test", "version": "1.0"}

    def test_load_valid_json(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"name": "test"}))
        result = load_yaml_file(f)
        assert result == {"name": "test"}

    def test_file_not_found(self, tmp_path):
        with pytest.raises(ConfigNotFoundError, match="not found"):
            load_yaml_file(tmp_path / "nonexistent.yaml")

    def test_file_too_large(self, tmp_path):
        f = tmp_path / "big.yaml"
        f.write_text("x: " + "a" * 1_100_000)
        with pytest.raises(ConfigValidationError, match="too large"):
            load_yaml_file(f)

    def test_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(":\n  - [\n  invalid")
        with pytest.raises(ConfigValidationError, match="YAML parsing failed"):
            load_yaml_file(f)

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json}")
        with pytest.raises(ConfigValidationError, match="JSON parsing failed"):
            load_yaml_file(f)

    def test_non_dict_raises(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(ConfigValidationError, match="must be a mapping"):
            load_yaml_file(f)


class TestValidateStructure:
    def test_excessive_nesting(self, tmp_path):
        """Deeply nested YAML should be rejected (YAML bomb prevention)."""
        # Build a 25-level deep dict
        nested = "a: " * 25 + "value"
        f = tmp_path / "deep.yaml"
        f.write_text(nested.replace("a:", "a:\n  a:").replace("  a: value", "  value: end"))
        # Manually create deeply nested YAML
        content = "root:\n"
        for i in range(22):
            content += "  " * (i + 1) + f"level{i}:\n"
        content += "  " * 23 + "value: end\n"
        f.write_text(content)

        with pytest.raises(ConfigValidationError, match="nesting depth"):
            load_yaml_file(f)

    def test_normal_nesting_ok(self, tmp_path):
        content = "a:\n  b:\n    c:\n      d: value\n"
        f = tmp_path / "ok.yaml"
        f.write_text(content)
        result = load_yaml_file(f)
        assert result["a"]["b"]["c"]["d"] == "value"


class TestSubstituteEnvVars:
    def test_simple_substitution(self, monkeypatch):
        monkeypatch.setenv("TEST_MODEL", "gpt-4o")
        result = substitute_env_vars({"model": "${TEST_MODEL}"})
        assert result == {"model": "gpt-4o"}

    def test_default_value(self):
        # Ensure var doesn't exist
        os.environ.pop("NONEXISTENT_VAR_12345", None)
        result = substitute_env_vars({"model": "${NONEXISTENT_VAR_12345:gpt-4o-mini}"})
        assert result == {"model": "gpt-4o-mini"}

    def test_missing_required_var(self):
        os.environ.pop("REQUIRED_MISSING_VAR", None)
        with pytest.raises(ConfigValidationError, match="required but not set"):
            substitute_env_vars({"key": "${REQUIRED_MISSING_VAR}"})

    def test_nested_dict_substitution(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "secret123")
        result = substitute_env_vars({
            "outer": {"inner": "${MY_KEY}"},
        })
        assert result["outer"]["inner"] == "secret123"

    def test_list_substitution(self, monkeypatch):
        monkeypatch.setenv("ITEM", "hello")
        result = substitute_env_vars(["${ITEM}", "static"])
        assert result == ["hello", "static"]

    def test_non_string_passthrough(self):
        result = substitute_env_vars({"count": 42, "flag": True, "ratio": 0.5})
        assert result == {"count": 42, "flag": True, "ratio": 0.5}

    def test_oversized_env_var(self, monkeypatch):
        monkeypatch.setenv("HUGE_VAR", "x" * 20_000)
        with pytest.raises(ConfigValidationError, match="too large"):
            substitute_env_vars({"val": "${HUGE_VAR}"})

    def test_multiple_vars_in_one_string(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "8080")
        result = substitute_env_vars({"url": "http://${HOST}:${PORT}/api"})
        assert result == {"url": "http://localhost:8080/api"}

    def test_empty_default(self):
        os.environ.pop("EMPTY_DEFAULT_VAR", None)
        result = substitute_env_vars({"val": "${EMPTY_DEFAULT_VAR:}"})
        assert result == {"val": ""}


class TestDetectConfigType:
    def test_workflow(self):
        assert detect_config_type({"workflow": {}}) == "workflow"

    def test_stage(self):
        assert detect_config_type({"stage": {}}) == "stage"

    def test_agent(self):
        assert detect_config_type({"agent": {}}) == "agent"

    def test_unknown(self):
        with pytest.raises(ConfigValidationError, match="Cannot detect config type"):
            detect_config_type({"unknown_key": {}})


class TestCheckSchemaVersion:
    def test_supported_version(self):
        check_schema_version({"schema_version": "1.0"})  # should not raise
        assert True

    def test_default_version(self):
        check_schema_version({})  # defaults to "1.0", should not raise
        assert True

    def test_unsupported_version(self):
        with pytest.raises(SchemaVersionError, match="not supported"):
            check_schema_version({"schema_version": "2.0"})
