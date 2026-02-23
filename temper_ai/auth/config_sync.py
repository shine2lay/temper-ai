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
    WorkflowConfigDB,
)

logger = logging.getLogger(__name__)

_CONFIG_TYPE_DB_MODEL: dict[str, Any] = {
    "workflow": WorkflowConfigDB,
    "stage": StageConfigDB,
    "agent": AgentConfigDB,
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
    ) -> dict:
        """List all configs of the given type for the tenant.

        Returns dict with 'configs' list and 'total' count.
        Raises ValueError on invalid config_type.
        """
        _validate_config_type(config_type)
        db_model_cls = _CONFIG_TYPE_DB_MODEL[config_type]

        with get_session() as session:
            records = session.query(db_model_cls).filter_by(tenant_id=tenant_id).all()

        configs: list[dict[str, Any]] = [
            {
                "name": r.name,
                "version": r.version,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in records
        ]
        return {"configs": configs, "total": len(configs)}
