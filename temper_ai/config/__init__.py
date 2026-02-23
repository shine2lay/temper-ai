"""Centralized configuration for Temper AI.

Usage::

    from temper_ai.config import get_settings

    settings = get_settings()
    print(settings.database_url)

The singleton is created lazily on first access. Call :func:`load_settings`
explicitly if you need to pass overrides (e.g. from CLI flags).
"""

from typing import Any, Optional

from temper_ai.config.settings import TemperSettings

__all__ = ["TemperSettings", "get_settings", "load_settings", "reset_settings"]

_settings: TemperSettings | None = None


def load_settings(**overrides: Any) -> TemperSettings:
    """Full load: config.yaml → compat env vars → TemperSettings.

    Args:
        **overrides: Field overrides forwarded to the ``TemperSettings``
            constructor (e.g. ``database_url="sqlite:///test.db"``).

    Returns:
        A fresh :class:`TemperSettings` instance.
    """
    from temper_ai.config._compat import apply_compat_env_vars
    from temper_ai.config._loader import inject_config_as_env, load_config_file

    # 1. Lowest priority: inject config-file values as env vars
    config = load_config_file()
    inject_config_as_env(config)

    # 2. Copy deprecated MAF_* → TEMPER_* (only if TEMPER_* is absent)
    apply_compat_env_vars()

    # 3. Construct settings (reads TEMPER_* env vars + .env file)
    return TemperSettings(**overrides)


def get_settings() -> TemperSettings:
    """Return the application-wide settings singleton.

    Creates the singleton on first call via :func:`load_settings`.
    """
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """Clear the cached singleton (useful for tests)."""
    global _settings  # noqa: PLW0603
    _settings = None
