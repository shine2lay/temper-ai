"""ConfigSyncService: import YAML configs to DB and export DB configs to YAML."""

import logging
import uuid
from typing import Any

import yaml
from pydantic import BaseModel

from temper_ai.storage.database.datetime_utils import utcnow
from temper_ai.storage.database.manager import get_session
from temper_ai.storage.database.models_tenancy import (
    VALID_CONFIG_TYPES,
    AgentConfigDB,
    StageConfigDB,
    ToolConfigDB,
    WorkflowConfigDB,
)

logger = logging.getLogger(__name__)

_CONFIG_TYPE_DB_MODEL: dict[str, Any] = {
    "workflow": WorkflowConfigDB,
    "stage": StageConfigDB,
    "agent": AgentConfigDB,
    "tool": ToolConfigDB,
}


def _get_pydantic_model(config_type: str) -> type[BaseModel]:
    """Return the Pydantic model class for the given config_type."""
    from temper_ai.stage._schemas import StageConfig  # noqa: lazy import
    from temper_ai.storage.schemas.agent_config import AgentConfig  # noqa: lazy import
    from temper_ai.workflow._schemas import WorkflowConfig  # noqa: lazy import

    mapping: dict[str, type[BaseModel]] = {
        "workflow": WorkflowConfig,
        "stage": StageConfig,
        "agent": AgentConfig,
    }
    return mapping[config_type]


def _validate_config_type(config_type: str) -> None:
    """Raise ValueError if config_type is not valid."""
    if config_type not in VALID_CONFIG_TYPES:
        raise ValueError(
            f"Invalid config_type '{config_type}'. "
            f"Must be one of: {sorted(VALID_CONFIG_TYPES)}"
        )


def _parse_yaml(yaml_content: str) -> dict[str, Any]:
    """Parse YAML string and return dict. Raises ValueError on failure."""
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("YAML content must represent a mapping (dict).")
    return data


def _validate_with_pydantic(config_type: str, data: dict[str, Any]) -> None:
    """Validate data against the Pydantic model. Raises ValueError on failure."""
    if config_type not in ("workflow", "stage", "agent"):
        return  # No Pydantic model for tool configs; store as-is
    model_cls = _get_pydantic_model(config_type)
    try:
        model_cls.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Config validation failed: {exc}") from exc


class ConfigSyncService:
    """Import YAML to DB JSONB and export DB configs to YAML."""

    def import_config(
        self,
        tenant_id: str,
        config_type: str,
        name: str,
        yaml_content: str,
        user_id: str,
    ) -> dict:
        """Parse YAML, validate via Pydantic, and store as JSONB.

        Returns dict with name, config_type, version.
        Raises ValueError on invalid YAML or validation failure.
        """
        _validate_config_type(config_type)
        data = _parse_yaml(yaml_content)
        _validate_with_pydantic(config_type, data)

        db_model_cls = _CONFIG_TYPE_DB_MODEL[config_type]

        with get_session() as session:
            existing = (
                session.query(db_model_cls)
                .filter_by(tenant_id=tenant_id, name=name)
                .first()
            )
            if existing is not None:
                existing.config_data = data
                existing.version = existing.version + 1
                existing.updated_by = user_id
                existing.updated_at = utcnow()
                version = existing.version
            else:
                record = db_model_cls(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    name=name,
                    config_data=data,
                    created_by=user_id,
                    updated_by=user_id,
                )
                session.add(record)
                version = 1

        logger.info(
            "Config imported",
            extra={"config_type": config_type, "name": name, "version": version},
        )
        return {"name": name, "config_type": config_type, "version": version}

    def export_config(
        self,
        tenant_id: str,
        config_type: str,
        name: str,
    ) -> str:
        """Read config from DB and return as YAML string.

        Raises ValueError on invalid config_type.
        Raises FileNotFoundError if config not found.
        """
        _validate_config_type(config_type)
        db_model_cls = _CONFIG_TYPE_DB_MODEL[config_type]

        with get_session() as session:
            record = (
                session.query(db_model_cls)
                .filter_by(tenant_id=tenant_id, name=name)
                .first()
            )
            if record is None:
                raise FileNotFoundError(
                    f"{config_type} config '{name}' not found for tenant '{tenant_id}'."
                )
            return yaml.safe_dump(record.config_data, default_flow_style=False)

    def list_configs(
        self,
        tenant_id: str,
        config_type: str,
    ) -> list[dict[str, Any]]:
        """List all configs of the given type for the tenant.

        Returns list of config summary dicts.
        Raises ValueError on invalid config_type.
        """
        _validate_config_type(config_type)
        db_model_cls = _CONFIG_TYPE_DB_MODEL[config_type]

        with get_session() as session:
            records = session.query(db_model_cls).filter_by(tenant_id=tenant_id).all()
            return [
                {
                    "name": r.name,
                    "version": getattr(r, "version", None),
                    "description": getattr(r, "description", ""),
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in records
            ]

    def get_config(
        self,
        tenant_id: str,
        config_type: str,
        name: str,
    ) -> dict[str, Any] | None:
        """Get a single config by (tenant_id, config_type, name).

        Returns dict with id, name, version, description, config_data, timestamps,
        or None if not found.
        """
        _validate_config_type(config_type)
        db_model_cls = _CONFIG_TYPE_DB_MODEL[config_type]

        with get_session() as session:
            record = (
                session.query(db_model_cls)
                .filter_by(tenant_id=tenant_id, name=name)
                .first()
            )
            if record is None:
                return None
            return {
                "id": record.id,
                "name": record.name,
                "version": getattr(record, "version", None),
                "description": getattr(record, "description", ""),
                "config_data": record.config_data,
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
            }

    def create_config(
        self,
        tenant_id: str,
        user_id: str,
        config_type: str,
        name: str,
        config_data: dict[str, Any],
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new config in the database.

        Returns dict with id, name, version.
        Raises ValueError on invalid config_type.
        """
        _validate_config_type(config_type)
        db_model_cls = _CONFIG_TYPE_DB_MODEL[config_type]

        record_id = str(uuid.uuid4())
        record = db_model_cls(
            id=record_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            config_data=config_data,
            created_by=user_id,
            updated_by=user_id,
        )

        with get_session() as session:
            session.add(record)
            version = getattr(record, "version", 1)

        logger.info(
            "Config created",
            extra={"config_type": config_type, "name": name},
        )
        return {"id": record_id, "name": name, "version": version}

    def update_config(
        self,
        tenant_id: str,
        user_id: str,
        config_type: str,
        name: str,
        description: str | None = None,
        config_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update an existing config.

        Returns dict with id, name, version.
        Raises KeyError if not found, ValueError on invalid config_type.
        """
        _validate_config_type(config_type)
        db_model_cls = _CONFIG_TYPE_DB_MODEL[config_type]

        with get_session() as session:
            record = (
                session.query(db_model_cls)
                .filter_by(tenant_id=tenant_id, name=name)
                .first()
            )
            if record is None:
                raise KeyError(
                    f"{config_type} config '{name}' not found for tenant '{tenant_id}'."
                )

            if config_data is not None:
                record.config_data = config_data
            if description is not None:
                record.description = description
            if hasattr(record, "version"):
                record.version = record.version + 1
            record.updated_by = user_id
            record.updated_at = utcnow()
            # Capture values before session closes
            result = {
                "id": record.id,
                "name": record.name,
                "version": getattr(record, "version", None),
            }

        logger.info(
            "Config updated",
            extra={"config_type": config_type, "name": name},
        )
        return result

    def delete_config(
        self,
        tenant_id: str,
        config_type: str,
        name: str,
    ) -> None:
        """Delete a config by (tenant_id, config_type, name).

        Raises KeyError if not found, ValueError on invalid config_type.
        """
        _validate_config_type(config_type)
        db_model_cls = _CONFIG_TYPE_DB_MODEL[config_type]

        with get_session() as session:
            record = (
                session.query(db_model_cls)
                .filter_by(tenant_id=tenant_id, name=name)
                .first()
            )
            if record is None:
                raise KeyError(
                    f"{config_type} config '{name}' not found for tenant '{tenant_id}'."
                )
            session.delete(record)

        logger.info(
            "Config deleted",
            extra={"config_type": config_type, "name": name},
        )
