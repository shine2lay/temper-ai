"""Centralized application settings using pydantic-settings.

All runtime configuration flows through ``TemperSettings``. Fields map to
``TEMPER_<FIELD>`` environment variables automatically thanks to
``env_prefix="TEMPER_"``.

Hierarchy (highest → lowest priority):
    CLI flags  >  env vars (TEMPER_*)  >  ~/.temper/config.yaml  >  defaults
"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class TemperSettings(BaseSettings):
    """Application-wide settings loaded from environment variables.

    Every field ``foo`` is read from the ``TEMPER_FOO`` env var.
    """

    model_config = SettingsConfigDict(
        env_prefix="TEMPER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Database --
    database_url: str = "postgresql://temper:temper@localhost:5432/temper"

    # -- Server --
    host: str = "127.0.0.1"
    port: int = 8420  # noqa  # scanner: skip-magic
    cors_origins: str = ""
    api_key: Optional[str] = None
    server_url: Optional[str] = None

    # -- Paths --
    config_root: str = "configs"
    workspace: Optional[str] = None
    db_path: Optional[str] = None

    # -- Workers --
    max_workers: int = 4  # noqa  # scanner: skip-magic

    # -- Logging & Observability --
    log_level: str = "INFO"
    log_format: str = "console"
    debug: bool = False

    # -- OpenTelemetry (custom TEMPER_* flags; standard OTEL_* vars unchanged) --
    otel_enabled: bool = False
    otel_instrument_httpx: bool = True
    otel_instrument_sqlalchemy: bool = False

    # -- Safety --
    safety_env: str = "development"

    # -- LLM (roadmap env vars) --
    llm_provider: str = "ollama"
    openai_api_key: Optional[str] = None
    secret_key: Optional[str] = None
