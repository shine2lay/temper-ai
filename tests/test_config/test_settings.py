"""Tests for TemperSettings and config module."""

import os
from unittest.mock import patch

import pytest

from temper_ai.config import get_settings, load_settings, reset_settings
from temper_ai.config.settings import TemperSettings


@pytest.fixture(autouse=True)
def _clean_singleton(monkeypatch):
    """Reset the settings singleton and clean TEMPER_* env vars."""
    reset_settings()
    # Remove any TEMPER_* env vars that might leak between tests
    for key in list(os.environ):
        if key.startswith("TEMPER_"):
            monkeypatch.delenv(key, raising=False)
    # Prevent pydantic-settings from reading .env file during tests
    monkeypatch.setattr(
        TemperSettings,
        "model_config",
        {**TemperSettings.model_config, "env_file": None},
    )
    yield
    reset_settings()


class TestTemperSettingsDefaults:
    """Verify default values are sane."""

    def test_database_url_default(self):
        s = TemperSettings()
        assert s.database_url == "postgresql://temper:temper@localhost:5432/temper"

    def test_host_default(self):
        s = TemperSettings()
        assert s.host == "127.0.0.1"

    def test_port_default(self):
        s = TemperSettings()
        assert s.port == 8420

    def test_log_level_default(self):
        s = TemperSettings()
        assert s.log_level == "INFO"

    def test_safety_env_default(self):
        s = TemperSettings()
        assert s.safety_env == "development"

    def test_config_root_default(self):
        s = TemperSettings()
        assert s.config_root == "configs"

    def test_max_workers_default(self):
        s = TemperSettings()
        assert s.max_workers == 4

    def test_otel_disabled_by_default(self):
        s = TemperSettings()
        assert s.otel_enabled is False

    def test_optional_fields_none(self):
        s = TemperSettings()
        assert s.api_key is None
        assert s.server_url is None
        assert s.workspace is None
        assert s.db_path is None
        assert s.openai_api_key is None
        assert s.secret_key is None


class TestTemperSettingsEnvOverride:
    """Verify TEMPER_* env vars override defaults."""

    def test_database_url_from_env(self):
        with patch.dict(os.environ, {"TEMPER_DATABASE_URL": "sqlite:///test.db"}):
            s = TemperSettings()
            assert s.database_url == "sqlite:///test.db"

    def test_log_level_from_env(self):
        with patch.dict(os.environ, {"TEMPER_LOG_LEVEL": "DEBUG"}):
            s = TemperSettings()
            assert s.log_level == "DEBUG"

    def test_safety_env_from_env(self):
        with patch.dict(os.environ, {"TEMPER_SAFETY_ENV": "production"}):
            s = TemperSettings()
            assert s.safety_env == "production"

    def test_port_from_env(self):
        with patch.dict(os.environ, {"TEMPER_PORT": "9999"}):
            s = TemperSettings()
            assert s.port == 9999

    def test_otel_enabled_from_env(self):
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "true"}):
            s = TemperSettings()
            assert s.otel_enabled is True

    def test_max_workers_from_env(self):
        with patch.dict(os.environ, {"TEMPER_MAX_WORKERS": "8"}):
            s = TemperSettings()
            assert s.max_workers == 8


class TestTemperSettingsOverrideKwargs:
    """Verify constructor kwargs override env vars."""

    def test_kwargs_override(self):
        s = TemperSettings(database_url="sqlite:///override.db", log_level="WARNING")
        assert s.database_url == "sqlite:///override.db"
        assert s.log_level == "WARNING"


class TestLoadSettings:
    """Test the full load_settings() pipeline."""

    def test_load_settings_returns_instance(self):
        s = load_settings()
        assert isinstance(s, TemperSettings)

    def test_load_settings_with_overrides(self):
        s = load_settings(database_url="sqlite:///custom.db")
        assert s.database_url == "sqlite:///custom.db"


class TestGetSettingsSingleton:
    """Test singleton behavior of get_settings()."""

    def test_returns_same_instance(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reset_clears_singleton(self):
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2

    def test_singleton_is_temper_settings(self):
        s = get_settings()
        assert isinstance(s, TemperSettings)
