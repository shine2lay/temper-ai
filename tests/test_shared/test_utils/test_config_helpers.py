"""Tests for config_helpers module."""

from temper_ai.shared.utils.config_helpers import (
    get_nested_value,
    sanitize_config_for_display,
)


class TestGetNestedValue:
    """Test nested value retrieval."""

    def test_get_simple_value(self):
        """Test getting top-level value."""
        config = {"name": "test"}

        result = get_nested_value(config, "name")

        assert result == "test"

    def test_get_nested_value(self):
        """Test getting nested value with dot notation."""
        config = {"agent": {"inference": {"model": "gpt-4"}}}

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
        config = {"items": ["a", "b", "c"]}

        # Can't get nested value from list
        result = get_nested_value(config, "items.0")

        assert result is None


class TestSanitizeConfigForDisplay:
    """Test secret sanitization in configs."""

    def test_sanitize_api_key(self):
        """Test that API keys are redacted."""
        config = {"api_key": "sk-secret123", "model": "gpt-4"}

        result = sanitize_config_for_display(config)

        assert result["api_key"] == "***REDACTED***"
        assert result["model"] == "gpt-4"

    def test_sanitize_password(self):
        """Test that passwords are redacted."""
        config = {"username": "admin", "password": "secret123"}

        result = sanitize_config_for_display(config)

        assert result["username"] == "admin"
        assert result["password"] == "***REDACTED***"

    def test_sanitize_nested_secrets(self):
        """Test sanitization of nested secrets."""
        config = {
            "database": {
                "host": "localhost",
                "password": "db_secret",
                "credentials": {"api_key": "api_secret"},
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
            "access_key": "secret9",
        }

        result = sanitize_config_for_display(config)

        for key in config.keys():
            assert result[key] == "***REDACTED***"

    def test_sanitize_case_insensitive(self):
        """Test sanitization is case-insensitive."""
        config = {"API_KEY": "secret1", "Password": "secret2", "SECRET": "secret3"}

        result = sanitize_config_for_display(config)

        for key in config.keys():
            assert result[key] == "***REDACTED***"

    def test_sanitize_custom_secret_keys(self):
        """Test adding custom secret keys."""
        config = {"custom_secret": "value1", "api_key": "value2"}

        result = sanitize_config_for_display(config, secret_keys=["custom_secret"])

        assert result["custom_secret"] == "***REDACTED***"
        assert result["api_key"] == "***REDACTED***"

    def test_sanitize_secrets_in_lists(self):
        """Test sanitization in list items."""
        config = {"credentials": [{"api_key": "secret1"}, {"api_key": "secret2"}]}

        result = sanitize_config_for_display(config)

        assert result["credentials"][0]["api_key"] == "***REDACTED***"
        assert result["credentials"][1]["api_key"] == "***REDACTED***"

    def test_sanitize_doesnt_modify_original(self):
        """Test that sanitization doesn't modify original config."""
        config = {"api_key": "sk-secret123", "model": "gpt-4"}

        result = sanitize_config_for_display(config)

        assert config["api_key"] == "sk-secret123"  # Original unchanged
        assert result["api_key"] == "***REDACTED***"  # Copy redacted

    def test_sanitize_partial_match(self):
        """Test that partial matches in key names are caught."""
        config = {
            "openai_api_key": "secret1",
            "database_password": "secret2",
            "auth_token": "secret3",
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
            "tags": ["prod", "api"],
        }

        result = sanitize_config_for_display(config)

        assert result["name"] == "MyApp"
        assert result["version"] == "1.0"
        assert result["api_key"] == "***REDACTED***"
        assert result["timeout"] == 30
        assert result["enabled"] is True
        assert result["tags"] == ["prod", "api"]


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_none_values_in_config(self):
        """Test handling None values."""
        config = {"name": "test", "optional": None}

        result = sanitize_config_for_display(config)
        assert result["optional"] is None

    def test_numeric_keys_in_get_nested(self):
        """Test that numeric string keys work."""
        config = {"items": {"0": "first", "1": "second"}}

        result = get_nested_value(config, "items.0")
        assert result == "first"

    def test_deep_nesting_sanitization(self):
        """Test sanitization with very deep nesting."""
        config = {"l1": {"l2": {"l3": {"l4": {"l5": {"api_key": "secret"}}}}}}

        result = sanitize_config_for_display(config)
        assert result["l1"]["l2"]["l3"]["l4"]["l5"]["api_key"] == "***REDACTED***"
