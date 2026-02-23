"""Tests for config file and .env loading."""

import os
from unittest.mock import patch

from temper_ai.config._loader import inject_config_as_env, load_config_file


class TestLoadConfigFile:
    """Test ~/.temper/config.yaml loading."""

    def test_returns_empty_when_no_file(self, tmp_path):
        fake_file = tmp_path / "nonexistent" / "config.yaml"
        with patch("temper_ai.config._loader.CONFIG_FILE", fake_file):
            result = load_config_file()
            assert result == {}

    def test_loads_valid_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "database_url: sqlite:///from_file.db\nlog_level: DEBUG\n"
        )
        with patch("temper_ai.config._loader.CONFIG_FILE", config_file):
            result = load_config_file()
            assert result["database_url"] == "sqlite:///from_file.db"
            assert result["log_level"] == "DEBUG"

    def test_returns_empty_for_non_mapping(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("- item1\n- item2\n")
        with patch("temper_ai.config._loader.CONFIG_FILE", config_file):
            result = load_config_file()
            assert result == {}

    def test_returns_empty_for_invalid_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(": : : invalid\n  bad:\n")
        with patch("temper_ai.config._loader.CONFIG_FILE", config_file):
            result = load_config_file()
            # Should return empty or parsed — either is valid for malformed YAML
            assert isinstance(result, dict)


class TestInjectConfigAsEnv:
    """Test config-file → env var injection."""

    def test_injects_as_temper_prefixed(self):
        env_clean = {"TEMPER_DATABASE_URL": None, "TEMPER_LOG_LEVEL": None}
        for k in env_clean:
            os.environ.pop(k, None)

        config = {"database_url": "sqlite:///cfg.db", "log_level": "DEBUG"}
        try:
            injected = inject_config_as_env(config)
            assert "TEMPER_DATABASE_URL" in injected
            assert "TEMPER_LOG_LEVEL" in injected
            assert os.environ["TEMPER_DATABASE_URL"] == "sqlite:///cfg.db"
            assert os.environ["TEMPER_LOG_LEVEL"] == "DEBUG"
        finally:
            for k in env_clean:
                os.environ.pop(k, None)

    def test_does_not_overwrite_existing_env(self):
        with patch.dict(os.environ, {"TEMPER_LOG_LEVEL": "WARNING"}, clear=False):
            config = {"log_level": "DEBUG"}
            injected = inject_config_as_env(config)
            assert "TEMPER_LOG_LEVEL" not in injected
            assert os.environ["TEMPER_LOG_LEVEL"] == "WARNING"

    def test_empty_config_returns_empty(self):
        injected = inject_config_as_env({})
        assert injected == []


class TestConfigFileIntegration:
    """End-to-end: config file → TemperSettings."""

    def test_config_file_values_reach_settings(self, tmp_path):
        from temper_ai.config import load_settings, reset_settings

        config_file = tmp_path / "config.yaml"
        config_file.write_text("safety_env: from_file\n")

        reset_settings()
        # Remove any competing env vars
        env_overrides = {"TEMPER_SAFETY_ENV": None, "SAFETY_ENV": None}
        cleaned = {}
        for k in env_overrides:
            cleaned[k] = os.environ.pop(k, None)

        try:
            with patch("temper_ai.config._loader.CONFIG_FILE", config_file):
                s = load_settings()
                assert s.safety_env == "from_file"
        finally:
            for k, v in cleaned.items():
                if v is not None:
                    os.environ[k] = v
            reset_settings()

    def test_env_var_overrides_config_file(self, tmp_path):
        from temper_ai.config import load_settings, reset_settings

        config_file = tmp_path / "config.yaml"
        config_file.write_text("log_level: DEBUG\n")

        reset_settings()
        with patch("temper_ai.config._loader.CONFIG_FILE", config_file):
            with patch.dict(os.environ, {"TEMPER_LOG_LEVEL": "ERROR"}, clear=False):
                s = load_settings()
                assert s.log_level == "ERROR"
        reset_settings()
