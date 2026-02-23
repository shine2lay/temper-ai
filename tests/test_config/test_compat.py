"""Tests for backward-compatible MAF_* → TEMPER_* env var migration."""

import os
from unittest.mock import patch

import pytest

from temper_ai.config._compat import apply_compat_env_vars


@pytest.fixture(autouse=True)
def _clean_env():
    """Remove any TEMPER_*/MAF_* vars that tests may set."""
    keys_to_clean = [
        "MAF_CONFIG_ROOT",
        "TEMPER_CONFIG_ROOT",
        "MAF_SERVER_URL",
        "TEMPER_SERVER_URL",
        "MAF_API_KEY",
        "TEMPER_API_KEY",
        "LOG_LEVEL",
        "TEMPER_LOG_LEVEL",
        "SAFETY_ENV",
        "TEMPER_SAFETY_ENV",
        "MAF_HOST",
        "TEMPER_HOST",
        "MAF_PORT",
        "TEMPER_PORT",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys_to_clean}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


class TestApplyCompatEnvVars:
    """Test the MAF_* → TEMPER_* compat bridge."""

    def test_copies_old_to_new(self):
        with patch.dict(os.environ, {"MAF_CONFIG_ROOT": "/my/configs"}, clear=False):
            migrated = apply_compat_env_vars()
            assert "MAF_CONFIG_ROOT" in migrated
            assert os.environ["TEMPER_CONFIG_ROOT"] == "/my/configs"

    def test_does_not_overwrite_new(self):
        with patch.dict(
            os.environ,
            {"MAF_CONFIG_ROOT": "/old", "TEMPER_CONFIG_ROOT": "/new"},
            clear=False,
        ):
            migrated = apply_compat_env_vars()
            assert "MAF_CONFIG_ROOT" not in migrated
            assert os.environ["TEMPER_CONFIG_ROOT"] == "/new"

    def test_bare_log_level_migrated(self):
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}, clear=False):
            migrated = apply_compat_env_vars()
            assert "LOG_LEVEL" in migrated
            assert os.environ["TEMPER_LOG_LEVEL"] == "DEBUG"

    def test_safety_env_migrated(self):
        with patch.dict(os.environ, {"SAFETY_ENV": "production"}, clear=False):
            migrated = apply_compat_env_vars()
            assert "SAFETY_ENV" in migrated
            assert os.environ["TEMPER_SAFETY_ENV"] == "production"

    def test_no_vars_set_returns_empty(self):
        migrated = apply_compat_env_vars()
        assert migrated == []

    def test_multiple_vars_migrated(self):
        env = {
            "MAF_HOST": "0.0.0.0",
            "MAF_PORT": "9000",
            "LOG_LEVEL": "WARNING",
        }
        with patch.dict(os.environ, env, clear=False):
            migrated = apply_compat_env_vars()
            assert len(migrated) == 3  # noqa: PLR2004
            assert os.environ["TEMPER_HOST"] == "0.0.0.0"
            assert os.environ["TEMPER_PORT"] == "9000"
            assert os.environ["TEMPER_LOG_LEVEL"] == "WARNING"


class TestCompatIntegration:
    """Verify compat vars flow through to TemperSettings via load_settings."""

    def test_maf_config_root_reaches_settings(self):
        from temper_ai.config import load_settings, reset_settings

        reset_settings()
        with patch.dict(os.environ, {"MAF_CONFIG_ROOT": "/compat/root"}, clear=False):
            s = load_settings()
            assert s.config_root == "/compat/root"
        reset_settings()

    def test_safety_env_reaches_settings(self):
        from temper_ai.config import load_settings, reset_settings

        reset_settings()
        with patch.dict(os.environ, {"SAFETY_ENV": "staging"}, clear=False):
            s = load_settings()
            assert s.safety_env == "staging"
        reset_settings()
