"""Tests for temper_ai/workflow/_config_loader_helpers.py.

Covers:
- load_config_file: YAML/YML/JSON probing, not found
- load_and_validate_config_file: oversize, valid YAML/JSON, parse errors
- validate_config_structure: depth limit, node count, circular refs
- substitute_env_vars: recursive, lists, defaults, unset vars
- substitute_env_var_string: secret refs, env vars, defaults, missing
- validate_env_var_value: valid/invalid via EnvVarValidator
- resolve_secrets: delegates to resolve_secret, error wrapping
- substitute_template_vars: happy path, missing vars
- validate_config: agent/stage/workflow/tool/trigger dispatch, unknown trigger
"""

import json
from unittest.mock import patch

import pytest

from temper_ai.shared.utils.exceptions import ConfigNotFoundError, ConfigValidationError
from temper_ai.workflow._config_loader_helpers import (
    MAX_CONFIG_SIZE,
    MAX_YAML_NESTING_DEPTH,
    MAX_YAML_NODES,
    load_and_validate_config_file,
    load_config_file,
    resolve_secrets,
    substitute_env_var_string,
    substitute_env_vars,
    substitute_template_vars,
    validate_config,
    validate_config_structure,
    validate_env_var_value,
)

# ============================================================================
# load_config_file
# ============================================================================


class TestLoadConfigFile:
    """Tests for load_config_file — probing .yaml, .yml, .json."""

    def test_loads_yaml(self, tmp_path):
        """Finds and loads a .yaml file."""
        (tmp_path / "wf.yaml").write_text("workflow:\n  name: test\n")
        result = load_config_file(tmp_path, "wf")
        assert result["workflow"]["name"] == "test"

    def test_loads_yml(self, tmp_path):
        """Falls back to .yml when .yaml doesn't exist."""
        (tmp_path / "wf.yml").write_text("workflow:\n  name: yml_test\n")
        result = load_config_file(tmp_path, "wf")
        assert result["workflow"]["name"] == "yml_test"

    def test_loads_json(self, tmp_path):
        """Falls back to .json when neither .yaml nor .yml exist."""
        (tmp_path / "wf.json").write_text(
            json.dumps({"workflow": {"name": "json_test"}})
        )
        result = load_config_file(tmp_path, "wf")
        assert result["workflow"]["name"] == "json_test"

    def test_prefers_yaml_over_yml(self, tmp_path):
        """When both .yaml and .yml exist, prefers .yaml."""
        (tmp_path / "wf.yaml").write_text("workflow:\n  name: yaml_first\n")
        (tmp_path / "wf.yml").write_text("workflow:\n  name: yml_second\n")
        result = load_config_file(tmp_path, "wf")
        assert result["workflow"]["name"] == "yaml_first"

    def test_not_found_raises(self, tmp_path):
        """Raises ConfigNotFoundError when no matching file exists."""
        with pytest.raises(ConfigNotFoundError, match="Config file not found"):
            load_config_file(tmp_path, "nonexistent")


# ============================================================================
# load_and_validate_config_file
# ============================================================================


class TestLoadAndValidateConfigFile:
    """Tests for load_and_validate_config_file — size, parse, validate."""

    def test_valid_yaml(self, tmp_path):
        """Parses valid YAML successfully."""
        f = tmp_path / "valid.yaml"
        f.write_text("key: value\nnested:\n  a: 1\n")
        result = load_and_validate_config_file(f)
        assert result["key"] == "value"
        assert result["nested"]["a"] == 1

    def test_valid_json(self, tmp_path):
        """Parses valid JSON successfully."""
        f = tmp_path / "valid.json"
        f.write_text(json.dumps({"key": "value"}))
        result = load_and_validate_config_file(f)
        assert result["key"] == "value"

    def test_oversize_file_raises(self, tmp_path):
        """Raises ConfigValidationError for files exceeding MAX_CONFIG_SIZE."""
        f = tmp_path / "big.yaml"
        f.write_text("x: " + "a" * (MAX_CONFIG_SIZE + 1))
        with pytest.raises(ConfigValidationError, match="Config file too large"):
            load_and_validate_config_file(f)

    def test_invalid_yaml_raises(self, tmp_path):
        """Raises ConfigValidationError for invalid YAML."""
        f = tmp_path / "bad.yaml"
        f.write_text(":\n  : :\n  {{invalid}}")
        with pytest.raises(ConfigValidationError, match="YAML parsing failed"):
            load_and_validate_config_file(f)

    def test_invalid_json_raises(self, tmp_path):
        """Raises ConfigValidationError for invalid JSON."""
        f = tmp_path / "bad.json"
        f.write_text("{not valid json}")
        with pytest.raises(ConfigValidationError, match="JSON parsing failed"):
            load_and_validate_config_file(f)


# ============================================================================
# validate_config_structure
# ============================================================================


class TestValidateConfigStructure:
    """Tests for validate_config_structure — depth, nodes, circular refs."""

    def test_flat_config_passes(self, tmp_path):
        """Simple flat dict passes validation."""
        validate_config_structure({"a": 1, "b": "x"}, tmp_path / "f.yaml")

    def test_list_config_passes(self, tmp_path):
        """Config with lists passes validation."""
        validate_config_structure({"items": [1, 2, 3]}, tmp_path / "f.yaml")

    def test_exceeds_depth_limit(self, tmp_path):
        """Deeply nested config exceeding MAX_YAML_NESTING_DEPTH raises."""
        nested: dict = {}
        current = nested
        for _ in range(MAX_YAML_NESTING_DEPTH + 2):
            current["child"] = {}
            current = current["child"]

        with pytest.raises(ConfigValidationError, match="maximum nesting depth"):
            validate_config_structure(nested, tmp_path / "deep.yaml")

    def test_exceeds_node_count(self, tmp_path):
        """Config with too many nodes raises."""
        # Create a flat dict with more than MAX_YAML_NODES keys
        big = {f"k{i}": i for i in range(MAX_YAML_NODES + 2)}
        with pytest.raises(ConfigValidationError, match="maximum node count"):
            validate_config_structure(big, tmp_path / "big.yaml")

    def test_circular_ref_detected(self, tmp_path):
        """Circular reference raises ConfigValidationError."""
        d: dict = {"a": {}}
        d["a"]["self"] = d  # circular
        with pytest.raises(ConfigValidationError, match="Circular reference"):
            validate_config_structure(d, tmp_path / "circ.yaml")

    def test_scalar_passes_without_recursion(self, tmp_path):
        """Scalar values (int, str, None) pass without recursion."""
        validate_config_structure("just a string", tmp_path / "f.yaml")
        validate_config_structure(42, tmp_path / "f.yaml")
        validate_config_structure(None, tmp_path / "f.yaml")


# ============================================================================
# substitute_env_vars
# ============================================================================


class TestSubstituteEnvVars:
    """Tests for substitute_env_vars — recursive substitution."""

    def test_string_substitution(self, monkeypatch):
        """Substitutes ${VAR} in string values."""
        monkeypatch.setenv("MY_VAR", "hello")
        result = substitute_env_vars("${MY_VAR}")
        assert result == "hello"

    def test_dict_recursive(self, monkeypatch):
        """Recursively substitutes env vars in dict values."""
        monkeypatch.setenv("A", "alpha")
        monkeypatch.setenv("B", "beta")
        result = substitute_env_vars({"x": "${A}", "y": "${B}"})
        assert result == {"x": "alpha", "y": "beta"}

    def test_list_recursive(self, monkeypatch):
        """Recursively substitutes env vars in list items."""
        monkeypatch.setenv("ITEM", "value")
        result = substitute_env_vars(["${ITEM}", "literal"])
        assert result == ["value", "literal"]

    def test_nested_dict_and_list(self, monkeypatch):
        """Works with deeply nested structures."""
        monkeypatch.setenv("DEEP", "found")
        result = substitute_env_vars({"outer": [{"inner": "${DEEP}"}]})
        assert result == {"outer": [{"inner": "found"}]}

    def test_non_string_passthrough(self):
        """Non-string, non-dict, non-list values pass through unchanged."""
        assert substitute_env_vars(42) == 42
        assert substitute_env_vars(True) is True
        assert substitute_env_vars(None) is None

    def test_default_value_used(self, monkeypatch):
        """Uses default when env var is not set."""
        monkeypatch.delenv("UNSET_VAR", raising=False)
        result = substitute_env_vars("${UNSET_VAR:fallback}")
        assert result == "fallback"

    def test_missing_var_no_default_raises(self, monkeypatch):
        """Raises ConfigValidationError when var is unset and no default given."""
        monkeypatch.delenv("REQUIRED_VAR", raising=False)
        with pytest.raises(ConfigValidationError, match="required but not set"):
            substitute_env_vars("${REQUIRED_VAR}")


# ============================================================================
# substitute_env_var_string
# ============================================================================


class TestSubstituteEnvVarString:
    """Tests for substitute_env_var_string — single string substitution."""

    def test_env_var_replaced(self, monkeypatch):
        """${VAR} is replaced with os.environ[VAR]."""
        monkeypatch.setenv("HOST", "localhost")
        assert (
            substitute_env_var_string("http://${HOST}:8080") == "http://localhost:8080"
        )

    def test_default_value(self, monkeypatch):
        """${VAR:default} uses default when VAR is not set."""
        monkeypatch.delenv("OPT", raising=False)
        assert substitute_env_var_string("${OPT:fallback_val}") == "fallback_val"

    def test_secret_reference_passthrough(self):
        """Secret references are returned unchanged."""
        ref = "secret://vault/my-secret"
        with patch(
            "temper_ai.workflow._config_loader_helpers.SecretReference.is_reference",
            return_value=True,
        ):
            assert substitute_env_var_string(ref) == ref

    def test_multiple_vars_in_one_string(self, monkeypatch):
        """Multiple ${VAR} patterns in one string are all replaced."""
        monkeypatch.setenv("PROTO", "https")
        monkeypatch.setenv("DOMAIN", "api.example.com")
        result = substitute_env_var_string("${PROTO}://${DOMAIN}/v1")
        assert result == "https://api.example.com/v1"

    def test_no_vars_passthrough(self):
        """String without ${} patterns is returned unchanged."""
        assert substitute_env_var_string("plain text") == "plain text"


# ============================================================================
# substitute_template_vars
# ============================================================================


class TestSubstituteTemplateVars:
    """Tests for substitute_template_vars — {{var}} substitution."""

    def test_single_var(self):
        """Substitutes a single {{var}} placeholder."""
        result = substitute_template_vars("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_multiple_vars(self):
        """Substitutes multiple {{var}} placeholders."""
        result = substitute_template_vars(
            "{{greeting}} {{target}}!",
            {"greeting": "Hi", "target": "there"},
        )
        assert result == "Hi there!"

    def test_missing_var_raises(self):
        """Raises ConfigValidationError for missing template variable."""
        with pytest.raises(ConfigValidationError, match="required but not provided"):
            substitute_template_vars("{{missing}}", {})

    def test_no_placeholders(self):
        """String without {{}} is returned unchanged."""
        result = substitute_template_vars("no vars here", {"extra": "ignored"})
        assert result == "no vars here"


# ============================================================================
# resolve_secrets
# ============================================================================


class TestResolveSecrets:
    """Tests for resolve_secrets — wraps resolve_secret with error conversion."""

    def test_delegates_to_resolve_secret(self):
        """Calls resolve_secret and returns its result."""
        with patch(
            "temper_ai.workflow._config_loader_helpers.resolve_secret",
            return_value="resolved_value",
        ) as mock_resolve:
            result = resolve_secrets("secret://test")
            mock_resolve.assert_called_once_with("secret://test")
            assert result == "resolved_value"

    def test_value_error_wrapped(self):
        """ValueError from resolve_secret is wrapped in ConfigValidationError."""
        with patch(
            "temper_ai.workflow._config_loader_helpers.resolve_secret",
            side_effect=ValueError("bad secret"),
        ):
            with pytest.raises(ConfigValidationError, match="Secret resolution failed"):
                resolve_secrets("secret://bad")

    def test_not_implemented_error_wrapped(self):
        """NotImplementedError from resolve_secret is wrapped in ConfigValidationError."""
        with patch(
            "temper_ai.workflow._config_loader_helpers.resolve_secret",
            side_effect=NotImplementedError("unsupported backend"),
        ):
            with pytest.raises(ConfigValidationError, match="Secret resolution failed"):
                resolve_secrets("secret://unsupported")


# ============================================================================
# validate_config
# ============================================================================


class TestValidateConfig:
    """Tests for validate_config — schema dispatch."""

    def test_unknown_trigger_type_raises(self):
        """Unknown trigger type raises ConfigValidationError."""
        with pytest.raises(ConfigValidationError, match="Unknown trigger type"):
            validate_config("trigger", {"trigger": {"type": "UnknownTrigger"}})

    def test_trigger_missing_type_raises(self):
        """Missing trigger type raises ConfigValidationError."""
        with pytest.raises(ConfigValidationError, match="Unknown trigger type"):
            validate_config("trigger", {"trigger": {}})

    def test_invalid_agent_config_raises(self):
        """Invalid agent config raises ConfigValidationError."""
        with pytest.raises(ConfigValidationError, match="Config validation failed"):
            validate_config("agent", {"invalid_field_only": True})

    def test_unregistered_config_type_no_error(self):
        """Unknown config type (not in schema_map) silently returns."""
        # Should not raise — falls through elif without action
        validate_config("unknown_type", {"anything": True})


# ============================================================================
# validate_env_var_value
# ============================================================================


class TestValidateEnvVarValue:
    """Tests for validate_env_var_value — delegates to EnvVarValidator."""

    def test_valid_value_passes(self):
        """Normal string value passes validation."""
        # Should not raise
        validate_env_var_value("MY_VAR", "normal_value")

    def test_oversized_value_raises(self):
        """Value exceeding MAX_ENV_VAR_SIZE raises ConfigValidationError."""
        from temper_ai.workflow._config_loader_helpers import MAX_ENV_VAR_SIZE

        huge = "x" * (MAX_ENV_VAR_SIZE + 1)
        with pytest.raises(ConfigValidationError):
            validate_env_var_value("BIG_VAR", huge)
