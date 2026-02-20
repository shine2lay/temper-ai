"""Backward-compatible environment variable mapping.

Copies old ``MAF_*`` / bare env vars into their ``TEMPER_*`` equivalents so
that existing deployments continue to work. A deprecation warning is logged
for every old-style variable that is still in use.

Call :func:`apply_compat_env_vars` **once** before constructing
``TemperSettings``.
"""

import logging
import os

logger = logging.getLogger(__name__)

# (old_name, new_name) — order does not matter.
_COMPAT_MAP: list[tuple[str, str]] = [
    ("MAF_CONFIG_ROOT", "TEMPER_CONFIG_ROOT"),
    ("MAF_SERVER_URL", "TEMPER_SERVER_URL"),
    ("MAF_API_KEY", "TEMPER_API_KEY"),
    ("MAF_HOST", "TEMPER_HOST"),
    ("MAF_PORT", "TEMPER_PORT"),
    ("MAF_DB_PATH", "TEMPER_DB_PATH"),
    ("MAF_MAX_WORKERS", "TEMPER_MAX_WORKERS"),
    ("MAF_WORKSPACE", "TEMPER_WORKSPACE"),
    ("MAF_OTEL_ENABLED", "TEMPER_OTEL_ENABLED"),
    ("MAF_OTEL_INSTRUMENT_HTTPX", "TEMPER_OTEL_INSTRUMENT_HTTPX"),
    ("MAF_OTEL_INSTRUMENT_SQLALCHEMY", "TEMPER_OTEL_INSTRUMENT_SQLALCHEMY"),
    ("MAF_LOG_FORMAT", "TEMPER_LOG_FORMAT"),
    ("LOG_LEVEL", "TEMPER_LOG_LEVEL"),
    ("SAFETY_ENV", "TEMPER_SAFETY_ENV"),
]


def apply_compat_env_vars() -> list[str]:
    """Copy old-style env vars into ``TEMPER_*`` equivalents.

    Only copies when the new name is **not** already set so that explicit
    ``TEMPER_*`` values always win.

    Returns:
        List of old variable names that were migrated (useful for testing).
    """
    migrated: list[str] = []
    for old_name, new_name in _COMPAT_MAP:
        old_value = os.environ.get(old_name)
        if old_value is not None and os.environ.get(new_name) is None:
            os.environ[new_name] = old_value
            migrated.append(old_name)
            logger.warning(
                "Deprecated env var %s detected — use %s instead",
                old_name,
                new_name,
            )
    return migrated
