"""ConfigStore — DB-backed config storage.

All config reads at runtime go through this store.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlmodel import select

from temper_ai.config.helpers import (
    ConfigNotFoundError,
    check_schema_version,
    substitute_env_vars,
)
from temper_ai.config.models import Config
from temper_ai.database import get_session

logger = logging.getLogger(__name__)

VALID_TYPES = {"workflow", "stage", "agent"}


class ConfigStore:
    """Read and write configs from the database."""

    def get(self, name: str, config_type: str) -> dict[str, Any]:
        """Read a config from DB, check version, resolve env vars.

        Args:
            name: Config name (e.g. "vcs_suggestion").
            config_type: One of "workflow", "stage", "agent".

        Returns:
            The config dict with env vars resolved.
        """
        self._validate_type(config_type)

        with get_session() as session:
            row = session.exec(
                select(Config)
                .where(Config.type == config_type)
                .where(Config.name == name)
            ).first()

            if row is None:
                raise ConfigNotFoundError(
                    f"{config_type} config '{name}' not found"
                )

            # Extract inside session to avoid DetachedInstanceError
            config = row.config
            schema_version = row.schema_version

        check_schema_version({"schema_version": schema_version})
        return substitute_env_vars(config)

    def put(
        self,
        name: str,
        config_type: str,
        config: dict[str, Any],
        schema_version: str = "1.0",
    ) -> str:
        """Store a config in the DB. Upserts by (type, name).

        Args:
            name: Config name.
            config_type: One of "workflow", "stage", "agent".
            config: The validated config dict (with ${VAR} still in place).
            schema_version: Schema version string.

        Returns:
            The config ID.
        """
        self._validate_type(config_type)

        with get_session() as session:
            # Use select-for-update to prevent race condition between concurrent put() calls.
            # SQLite does not support SELECT FOR UPDATE, so skip the lock on SQLite.
            query = (
                select(Config)
                .where(Config.type == config_type)
                .where(Config.name == name)
            )
            if session.bind.dialect.name != "sqlite":
                query = query.with_for_update()
            existing = session.exec(query).first()

            if existing is not None:
                existing.config = config
                existing.schema_version = schema_version
                existing.updated_at = datetime.now(UTC)
                session.add(existing)
                return existing.id

            row = Config(
                type=config_type,
                name=name,
                schema_version=schema_version,
                config=config,
            )
            session.add(row)
            session.flush()
            return row.id

    def list(self, config_type: str | None = None) -> list[dict[str, Any]]:
        """List configs, optionally filtered by type.

        Returns:
            List of config summaries (id, type, name, schema_version, timestamps).
        """
        with get_session() as session:
            stmt = select(Config)
            if config_type is not None:
                self._validate_type(config_type)
                stmt = stmt.where(Config.type == config_type)
            stmt = stmt.order_by(Config.type, Config.name)

            rows = session.exec(stmt).all()
            # Extract inside session to avoid DetachedInstanceError
            return [
                {
                    "id": r.id,
                    "type": r.type,
                    "name": r.name,
                    "schema_version": r.schema_version,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]

    def delete(self, name: str, config_type: str) -> bool:
        """Delete a config by (type, name).

        Returns:
            True if deleted, False if not found.
        """
        self._validate_type(config_type)

        with get_session() as session:
            row = session.exec(
                select(Config)
                .where(Config.type == config_type)
                .where(Config.name == name)
            ).first()

            if row is None:
                return False

            session.delete(row)
            return True

    @staticmethod
    def _validate_type(config_type: str) -> None:
        if config_type not in VALID_TYPES:
            raise ValueError(
                f"Invalid config type '{config_type}'. Must be one of: {VALID_TYPES}"
            )
