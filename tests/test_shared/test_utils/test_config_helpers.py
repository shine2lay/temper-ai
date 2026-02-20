"""Tests for config_helpers module."""

import pytest

from temper_ai.shared.utils.config_helpers import (
    extract_required_fields,
    get_nested_value,
    merge_configs,
    resolve_config_path,
    sanitize_config_for_display,
    set_nested_value,
    validate_config_structure,
)


class TestMergeConfigs:
    """Test config merging functionality."""

    def test_merge_simple_configs(self):
        """Test merging simple flat configs."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        result = merge_configs(base, override)

        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_nested_configs(self):
        """Test merging nested configs."""
        base = {
            "llm": {"temperature": 0.7, "model": "gpt-4"},
            "tools": ["calculator"]
        }
        override = {
            "llm": {"temperature": 0.9},
            "safety": {"mode": "strict"}
        }

        result = merge_configs(base, override)

        assert result["llm"]["temperature"] == 0.9
        assert result["llm"]["model"] == "gpt-4"
        assert result["tools"] == ["calculator"]
        assert result["safety"]["mode"] == "strict"

    def test_merge_deep_nesting(self):
        """Test merging deeply nested configs."""
        base = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "old"
                    }
                }
            }
        }
        override = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "new"
                    }
                }
            }
        }

        result = merge_configs(base, override)

        assert result["level1"]["level2"]["level3"]["value"] == "new"

    def test_merge_doesnt_modify_original(self):
        """Test that merge doesn't modify original configs."""
        base = {"a": 1}
        override = {"b": 2}

        merge_configs(base, override)

        assert base == {"a": 1}
        assert override == {"b": 2}


class TestExtractRequiredFields:
    """Test required field extraction."""

    def test_extract_simple_fields(self):
        """Test extracting simple top-level fields."""
        config = {"name": "test", "version": "1.0", "type": "agent"}

        result = extract_required_fields(config, ["name", "version"])

        assert result == {"name": "test", "version": "1.0"}

    def test_extract_nested_fields(self):
        """Test extracting nested fields with dot notation."""
        config = {
            "agent": {
                "name": "researcher",
                "inference": {
                    "model": "gpt-4"
                }
            }
        }

        result = extract_required_fields(
            config,
            ["agent.name", "agent.inference.model"]
        )

        assert result["agent.name"] == "researcher"
        assert result["agent.inference.model"] == "gpt-4"

    def test_extract_missing_field_raises_error(self):
        """Test that missing required field raises ValueError."""
        config = {"name": "test"}

        with pytest.raises(ValueError, match="Required field.*missing"):
            extract_required_fields(config, ["name", "missing_field"])


class TestGetNestedValue:
    """Test nested value retrieval."""

    def test_get_simple_value(self):
        """Test getting top-level value."""
        config = {"name": "test"}

        result = get_nested_value(config, "name")

        assert result == "test"

    def test_get_nested_value(self):
        """Test getting nested value with dot notation."""
        config = {
            "agent": {
                "inference": {
                    "model": "gpt-4"
                }
            }
        }

        result = get_nested_value(config, "agent.inference.model")

        assert result == "gpt-4"

    def test_get_missing_value_returns_default(self):
        """Test that missing value returns default."""
        config = {"name": "test"}

        result = get_nested_value(config, "missing.path", default="default_value")

        assert result == "default_value"

    def test_get_missing_value_returns_none(self):
        """Test that missing value returns None by default."""
        config = {"name": "test"}

        result = get_nested_value(config, "missing.path")

        assert result is None

    def test_get_value_from_list(self):
        """Test getting value when path goes through non-dict."""
        config = {
            "items": ["a", "b", "c"]
        }

        # Can't get nested value from list
        result = get_nested_value(config, "items.0")

        assert result is None


class TestSetNestedValue:
    """Test nested value setting."""

    def test_set_simple_value(self):
        """Test setting top-level value."""
        config = {}

        set_nested_value(config, "name", "test")

        assert config["name"] == "test"

    def test_set_nested_value(self):
        """Test setting nested value with auto-creation."""
        config = {}

        set_nested_value(config, "agent.inference.model", "gpt-4")

        assert config["agent"]["inference"]["model"] == "gpt-4"

    def test_set_value_in_existing_path(self):
        """Test setting value in existing path."""
        config = {
            "agent": {
                "name": "researcher"
            }
        }

        set_nested_value(config, "agent.inference.model", "gpt-4")

        assert config["agent"]["name"] == "researcher"
        assert config["agent"]["inference"]["model"] == "gpt-4"

    def test_set_value_overwrites_existing(self):
        """Test that setting value overwrites existing value."""
        config = {
            "agent": {
                "name": "old_name"
            }
        }

        set_nested_value(config, "agent.name", "new_name")

        assert config["agent"]["name"] == "new_name"


class TestValidateConfigStructure:
    """Test config structure validation."""

    def test_validate_valid_structure(self):
        """Test validation passes for valid structure."""
        config = {
            "workflow": {"name": "test"},
            "version": "1.0"
        }

        # Should not raise for valid structure
        validate_config_structure(config, ["workflow", "version"])

    def test_validate_missing_key_raises_error(self):
        """Test validation fails for missing required key."""
        config = {
            "workflow": {"name": "test"}
        }

        with pytest.raises(ValueError, match="missing required key"):
            validate_config_structure(config, ["workflow", "missing_key"])


class TestSanitizeConfigForDisplay:
    """Test secret sanitization in configs."""

    def test_sanitize_api_key(self):
        """Test that API keys are redacted."""
        config = {
            "api_key": "sk-secret123",
            "model": "gpt-4"
        }

        result = sanitize_config_for_display(config)

        assert result["api_key"] == "***REDACTED***"
        assert result["model"] == "gpt-4"

    def test_sanitize_password(self):
        """Test that passwords are redacted."""
        config = {
            "username": "admin",
            "password": "secret123"
        }

        result = sanitize_config_for_display(config)

        assert result["username"] == "admin"
        assert result["password"] == "***REDACTED***"

    def test_sanitize_nested_secrets(self):
        """Test sanitization of nested secrets."""
        config = {
            "database": {
                "host": "localhost",
                "password": "db_secret",
                "credentials": {
                    "api_key": "api_secret"
                }
            }
        }

        result = sanitize_config_for_display(config)

        assert result["database"]["host"] == "localhost"
        assert result["database"]["password"] == "***REDACTED***"
        assert result["database"]["credentials"]["api_key"] == "***REDACTED***"

    def test_sanitize_various_secret_patterns(self):
        """Test various secret key patterns are caught."""
        config = {
            "api_key": "secret1",
            "apikey": "secret2",
            "api-key": "secret3",
            "secret": "secret4",
            "token": "secret5",
            "password": "secret6",
            "passwd": "secret7",
            "private_key": "secret8",
            "access_key": "secret9"
        }

        result = sanitize_config_for_display(config)

        for key in config.keys():
            assert result[key] == "***REDACTED***"

    def test_sanitize_case_insensitive(self):
        """Test sanitization is case-insensitive."""
        config = {
            "API_KEY": "secret1",
            "Password": "secret2",
            "SECRET": "secret3"
        }

        result = sanitize_config_for_display(config)

        for key in config.keys():
            assert result[key] == "***REDACTED***"

    def test_sanitize_custom_secret_keys(self):
        """Test adding custom secret keys."""
        config = {
            "custom_secret": "value1",
            "api_key": "value2"
        }

        result = sanitize_config_for_display(
            config,
            secret_keys=["custom_secret"]
        )

        assert result["custom_secret"] == "***REDACTED***"
        assert result["api_key"] == "***REDACTED***"

    def test_sanitize_secrets_in_lists(self):
        """Test sanitization in list items."""
        config = {
            "credentials": [
                {"api_key": "secret1"},
                {"api_key": "secret2"}
            ]
        }

        result = sanitize_config_for_display(config)

        assert result["credentials"][0]["api_key"] == "***REDACTED***"
        assert result["credentials"][1]["api_key"] == "***REDACTED***"

    def test_sanitize_doesnt_modify_original(self):
        """Test that sanitization doesn't modify original config."""
        config = {
            "api_key": "sk-secret123",
            "model": "gpt-4"
        }

        result = sanitize_config_for_display(config)

        assert config["api_key"] == "sk-secret123"  # Original unchanged
        assert result["api_key"] == "***REDACTED***"  # Copy redacted

    def test_sanitize_partial_match(self):
        """Test that partial matches in key names are caught."""
        config = {
            "openai_api_key": "secret1",
            "database_password": "secret2",
            "auth_token": "secret3"
        }

        result = sanitize_config_for_display(config)

        for key in config.keys():
            assert result[key] == "***REDACTED***"

    def test_sanitize_preserves_non_secrets(self):
        """Test that non-secret values are preserved."""
        config = {
            "name": "MyApp",
            "version": "1.0",
            "api_key": "secret",
            "timeout": 30,
            "enabled": True,
            "tags": ["prod", "api"]
        }

        result = sanitize_config_for_display(config)

        assert result["name"] == "MyApp"
        assert result["version"] == "1.0"
        assert result["api_key"] == "***REDACTED***"
        assert result["timeout"] == 30
        assert result["enabled"] is True
        assert result["tags"] == ["prod", "api"]


class TestResolveConfigPath:
    """Test config path resolution."""

    def test_resolve_relative_path(self, tmp_path):
        """Test resolving relative path."""
        config_root = tmp_path / "configs"
        config_root.mkdir()
        config_file = config_root / "test.yaml"
        config_file.write_text("test")

        result = resolve_config_path("test.yaml", config_root=config_root)

        assert result == config_file.resolve()

    def test_resolve_nested_relative_path(self, tmp_path):
        """Test resolving nested relative path within config_root."""
        config_root = tmp_path / "configs"
        subdir = config_root / "agents"
        subdir.mkdir(parents=True)
        config_file = subdir / "test.yaml"
        config_file.write_text("test")

        result = resolve_config_path("agents/test.yaml", config_root=config_root)

        assert result == config_file.resolve()

    def test_resolve_nonexistent_path_raises_error(self, tmp_path):
        """Test that non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            resolve_config_path("nonexistent.yaml", config_root=tmp_path)

    def test_resolve_default_config_root(self, tmp_path, monkeypatch):
        """Test using default config root (cwd/configs)."""
        monkeypatch.chdir(tmp_path)

        config_root = tmp_path / "configs"
        config_root.mkdir()
        config_file = config_root / "test.yaml"
        config_file.write_text("test")

        result = resolve_config_path("test.yaml")

        assert result == config_file.resolve()

    def test_reject_absolute_path(self, tmp_path):
        """Absolute paths must be rejected."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("test")

        with pytest.raises(ValueError, match="absolute"):
            resolve_config_path(str(config_file), config_root=tmp_path)

    def test_reject_traversal_with_dotdot(self, tmp_path):
        """Directory traversal with .. must be rejected."""
        config_root = tmp_path / "configs"
        config_root.mkdir()

        with pytest.raises(ValueError, match="\\.\\."):
            resolve_config_path("../../etc/passwd", config_root=config_root)

    def test_reject_traversal_single_dotdot(self, tmp_path):
        """Even a single .. component must be rejected."""
        config_root = tmp_path / "configs"
        config_root.mkdir()

        with pytest.raises(ValueError, match="\\.\\."):
            resolve_config_path("../secret.yaml", config_root=config_root)

    def test_reject_null_bytes(self, tmp_path):
        """Null bytes in paths must be rejected."""
        with pytest.raises(ValueError, match="null"):
            resolve_config_path("config\x00.yaml", config_root=tmp_path)

    def test_reject_symlink_escape(self, tmp_path):
        """Symlinks pointing outside config_root must be rejected."""
        config_root = tmp_path / "configs"
        config_root.mkdir()

        # Create target outside config_root
        outside = tmp_path / "outside.yaml"
        outside.write_text("secret config")

        # Create symlink inside config_root pointing outside
        symlink = config_root / "evil.yaml"
        symlink.symlink_to(outside)

        with pytest.raises(ValueError, match="escapes"):
            resolve_config_path("evil.yaml", config_root=config_root)

    def test_reject_absolute_etc_passwd(self):
        """Classic /etc/passwd path must be rejected."""
        with pytest.raises(ValueError, match="absolute"):
            resolve_config_path("/etc/passwd")


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_config_merge(self):
        """Test merging with empty configs."""
        result = merge_configs({}, {"a": 1})
        assert result == {"a": 1}

        result = merge_configs({"a": 1}, {})
        assert result == {"a": 1}

    def test_none_values_in_config(self):
        """Test handling None values."""
        config = {
            "name": "test",
            "optional": None
        }

        result = sanitize_config_for_display(config)
        assert result["optional"] is None

    def test_numeric_keys_in_get_nested(self):
        """Test that numeric string keys work."""
        config = {
            "items": {
                "0": "first",
                "1": "second"
            }
        }

        result = get_nested_value(config, "items.0")
        assert result == "first"

    def test_deep_nesting_sanitization(self):
        """Test sanitization with very deep nesting."""
        config = {
            "l1": {
                "l2": {
                    "l3": {
                        "l4": {
                            "l5": {
                                "api_key": "secret"
                            }
                        }
                    }
                }
            }
        }

        result = sanitize_config_for_display(config)
        assert result["l1"]["l2"]["l3"]["l4"]["l5"]["api_key"] == "***REDACTED***"
