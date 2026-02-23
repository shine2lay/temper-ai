"""Business logic layer for Workflow Studio config CRUD operations.

Provides listing, reading, creating, updating, deleting, and validating
YAML-based configuration files for the Temper AI dashboard.
"""

import json
import logging
import re
import sys
from datetime import UTC
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from temper_ai.interfaces.dashboard._studio_validation_helpers import (
    get_db_model,
    load_raw_config,
    write_config,
)
from temper_ai.interfaces.dashboard.constants import (
    DEFAULT_ENCODING,
    ERROR_CONFIG_NOT_FOUND,
)
from temper_ai.stage._schemas import StageConfig
from temper_ai.storage.schemas.agent_config import AgentConfig
from temper_ai.tools._schemas import ToolConfig
from temper_ai.workflow._schemas import WorkflowConfig
from temper_ai.workflow.config_loader import ConfigLoader

logger = logging.getLogger(__name__)

# Name validation: alphanumeric, hyphens, underscores only
_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Maximum config data size in bytes (1 MB)
MAX_CONFIG_SIZE_BYTES = 1_048_576
_CONFIG_VALIDATION_FAILED = "Config validation failed: "

# Valid config types exposed by the API
VALID_CONFIG_TYPES = frozenset({"workflows", "stages", "agents", "tools"})

# Mapping from API config type to ConfigLoader type string
_LOADER_TYPE_MAP: dict[str, str] = {
    "workflows": "workflow",
    "stages": "stage",
    "agents": "agent",
    "tools": "tool",
}

# Mapping from API config type to Pydantic model class
_MODEL_MAP: dict[str, type[BaseModel]] = {
    "workflows": WorkflowConfig,
    "stages": StageConfig,
    "agents": AgentConfig,
    "tools": ToolConfig,
}

# Mapping from API config type to config subdirectory name
_DIR_MAP: dict[str, str] = {
    "workflows": "workflows",
    "stages": "stages",
    "agents": "agents",
    "tools": "tools",
}

# Mapping from API config type to the top-level wrapper key in YAML
_WRAPPER_KEY_MAP: dict[str, str] = {
    "workflows": "workflow",
    "stages": "stage",
    "agents": "agent",
    "tools": "tool",
}


def _validate_name(name: str) -> None:
    """Validate config name against allowed pattern.

    Raises:
        ValueError: If name contains invalid characters or is empty.
    """
    if not name or not _NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid config name '{name}'. "
            "Only alphanumeric characters, hyphens, and underscores are allowed."
        )


def _validate_config_type(config_type: str) -> None:
    """Validate that config_type is one of the allowed types.

    Raises:
        ValueError: If config_type is not valid.
    """
    if config_type not in VALID_CONFIG_TYPES:
        raise ValueError(
            f"Invalid config type '{config_type}'. "
            f"Must be one of: {sorted(VALID_CONFIG_TYPES)}"
        )


def _check_data_size(data: dict) -> None:
    """Check that serialized config data does not exceed size limit.

    Raises:
        ValueError: If data exceeds MAX_CONFIG_SIZE_BYTES.
    """
    size = sys.getsizeof(json.dumps(data))
    if size > MAX_CONFIG_SIZE_BYTES:
        raise ValueError(
            f"Config data too large: {size} bytes (max: {MAX_CONFIG_SIZE_BYTES})"
        )


def _extract_config_summary(
    config_data: dict[str, Any], wrapper_key: str
) -> dict[str, Any]:
    """Extract name, description, version from a config's inner wrapper.

    Args:
        config_data: Full parsed config dict.
        wrapper_key: The top-level key (e.g., 'workflow', 'agent').

    Returns:
        Dict with name, description, version fields.
    """
    inner = config_data.get(wrapper_key, {})
    return {
        "name": inner.get("name", ""),
        "description": inner.get("description", ""),
        "version": inner.get("version", ""),
    }


class StudioService:
    """Service for CRUD operations on YAML configuration files."""

    def __init__(self, config_root: str = "configs", use_db: bool = False) -> None:
        """Initialize the studio service.

        Args:
            config_root: Root directory for configuration files.
            use_db: When True, DB-backed methods are available for multi-tenant storage.
        """
        self._config_root = Path(config_root)
        self._loader = ConfigLoader(config_root=config_root)
        self._use_db = use_db

    @property
    def use_db(self) -> bool:
        """True when DB-backed storage is active."""
        return self._use_db

    def _get_config_dir(self, config_type: str) -> Path:
        """Get the directory path for a given config type."""
        return self._config_root / _DIR_MAP[config_type]

    def _get_config_path(self, config_type: str, name: str) -> Path:
        """Get the full file path for a specific config."""
        return self._get_config_dir(config_type) / f"{name}.yaml"

    def list_configs(self, config_type: str) -> dict:
        """List all configs of a given type.

        Args:
            config_type: One of 'workflows', 'stages', 'agents', 'tools'.

        Returns:
            Dict with 'configs' list and 'total' count.

        Raises:
            ValueError: If config_type is invalid.
        """
        _validate_config_type(config_type)

        loader_type = _LOADER_TYPE_MAP[config_type]
        wrapper_key = _WRAPPER_KEY_MAP[config_type]
        names = self._loader.list_configs(loader_type)

        configs: list[dict[str, Any]] = []
        for name in names:
            try:
                data = load_raw_config(config_type, name, self._config_root, _DIR_MAP)
                summary = _extract_config_summary(data, wrapper_key)
                summary["name"] = summary["name"] or name
                configs.append(summary)
            except (FileNotFoundError, yaml.YAMLError) as exc:
                logger.warning(
                    "Failed to read config %s/%s: %s", config_type, name, exc
                )
                continue

        return {"configs": configs, "total": len(configs)}

    def get_config(self, config_type: str, name: str) -> dict:
        """Get a parsed config as a JSON-compatible dict.

        Args:
            config_type: Config type string.
            name: Config name (no extension).

        Returns:
            Parsed config dictionary.

        Raises:
            ValueError: If config_type or name is invalid.
            FileNotFoundError: If config file does not exist.
        """
        _validate_config_type(config_type)
        _validate_name(name)

        return load_raw_config(config_type, name, self._config_root, _DIR_MAP)

    def get_config_raw(self, config_type: str, name: str) -> str:
        """Get the raw YAML text of a config file.

        Args:
            config_type: Config type string.
            name: Config name (no extension).

        Returns:
            Raw YAML string.

        Raises:
            ValueError: If config_type or name is invalid.
            FileNotFoundError: If config file does not exist.
        """
        _validate_config_type(config_type)
        _validate_name(name)

        file_path = self._get_config_path(config_type, name)
        if not file_path.exists():
            raise FileNotFoundError(f"{ERROR_CONFIG_NOT_FOUND}{config_type}/{name}")

        return file_path.read_text(encoding=DEFAULT_ENCODING)

    def create_config(self, config_type: str, name: str, data: dict) -> dict:
        """Create a new config file.

        Args:
            config_type: Config type string.
            name: Config name (no extension).
            data: Config data dictionary.

        Returns:
            The saved config data.

        Raises:
            ValueError: If config_type, name, or data is invalid.
            FileExistsError: If a config with this name already exists.
        """
        _validate_config_type(config_type)
        _validate_name(name)
        _check_data_size(data)

        file_path = self._get_config_path(config_type, name)
        if file_path.exists():
            raise FileExistsError(f"Config already exists: {config_type}/{name}")

        # Validate before writing
        validation = self.validate_config(config_type, data)
        if not validation["valid"]:
            raise ValueError(
                f"{_CONFIG_VALIDATION_FAILED}{'; '.join(validation['errors'])}"
            )

        write_config(file_path, data)
        self._loader.clear_cache()

        logger.info("Created config: %s/%s", config_type, name)
        return data

    def update_config(self, config_type: str, name: str, data: dict) -> dict:
        """Update an existing config file.

        Args:
            config_type: Config type string.
            name: Config name (no extension).
            data: New config data dictionary.

        Returns:
            The updated config data.

        Raises:
            ValueError: If config_type, name, or data is invalid.
            FileNotFoundError: If config file does not exist.
        """
        _validate_config_type(config_type)
        _validate_name(name)
        _check_data_size(data)

        file_path = self._get_config_path(config_type, name)
        if not file_path.exists():
            raise FileNotFoundError(f"{ERROR_CONFIG_NOT_FOUND}{config_type}/{name}")

        # Validate before writing
        validation = self.validate_config(config_type, data)
        if not validation["valid"]:
            raise ValueError(
                f"{_CONFIG_VALIDATION_FAILED}{'; '.join(validation['errors'])}"
            )

        write_config(file_path, data)
        self._loader.clear_cache()

        logger.info("Updated config: %s/%s", config_type, name)
        return data

    def delete_config(self, config_type: str, name: str) -> dict:
        """Delete a config file.

        Args:
            config_type: Config type string.
            name: Config name (no extension).

        Returns:
            Dict confirming deletion with 'deleted' key.

        Raises:
            ValueError: If config_type or name is invalid.
            FileNotFoundError: If config file does not exist.
        """
        _validate_config_type(config_type)
        _validate_name(name)

        file_path = self._get_config_path(config_type, name)
        if not file_path.exists():
            raise FileNotFoundError(f"{ERROR_CONFIG_NOT_FOUND}{config_type}/{name}")

        file_path.unlink()
        self._loader.clear_cache()

        logger.info("Deleted config: %s/%s", config_type, name)
        return {"deleted": f"{config_type}/{name}"}

    def validate_config(self, config_type: str, data: dict) -> dict:
        """Validate config data without saving.

        Args:
            config_type: Config type string.
            data: Config data dictionary to validate.

        Returns:
            Dict with 'valid' bool and 'errors' list.

        Raises:
            ValueError: If config_type is invalid.
        """
        _validate_config_type(config_type)

        model_class = _MODEL_MAP[config_type]
        errors: list[str] = []

        try:
            model_class.model_validate(data)
        except ValidationError as exc:
            for error in exc.errors():
                loc = " -> ".join(str(part) for part in error["loc"])
                errors.append(f"{loc}: {error['msg']}")

        return {"valid": len(errors) == 0, "errors": errors}

    def get_schema(self, config_type: str) -> dict:
        """Get JSON Schema for a config type.

        Args:
            config_type: Config type string.

        Returns:
            JSON Schema dictionary from the Pydantic model.

        Raises:
            ValueError: If config_type is invalid.
        """
        _validate_config_type(config_type)

        model_class = _MODEL_MAP[config_type]
        return model_class.model_json_schema()

    def list_configs_db(self, config_type: str, tenant_id: str) -> dict:
        """List all configs of the given type for a tenant from the DB.

        Args:
            config_type: One of 'workflows', 'stages', 'agents'.
            tenant_id: Tenant identifier for row-level isolation.

        Returns:
            Dict with 'configs' list and 'total' count.

        Raises:
            ValueError: If config_type is invalid or has no DB model.
        """
        _validate_config_type(config_type)
        _validate_name(tenant_id)

        from sqlmodel import col, select

        from temper_ai.storage.database.manager import get_session

        model_class = get_db_model(config_type)

        with get_session() as session:
            stmt = (
                select(
                    model_class.name,
                    model_class.version,
                    model_class.description,
                )
                .where(col(model_class.tenant_id) == tenant_id)
                .order_by(model_class.name)
            )
            rows = session.exec(stmt).all()

        configs = [
            {"name": row[0], "version": row[1], "description": row[2]} for row in rows
        ]
        return {"configs": configs, "total": len(configs)}

    def get_config_db(self, config_type: str, name: str, tenant_id: str) -> dict:
        """Get a config from the DB by name and tenant.

        Args:
            config_type: One of 'workflows', 'stages', 'agents'.
            name: Config name.
            tenant_id: Tenant identifier.

        Returns:
            The config_data dict stored in the DB.

        Raises:
            ValueError: If config_type or name is invalid.
            FileNotFoundError: If no matching record exists.
        """
        _validate_config_type(config_type)
        _validate_name(name)
        _validate_name(tenant_id)

        from sqlmodel import col, select

        from temper_ai.storage.database.manager import get_session

        model_class = get_db_model(config_type)

        with get_session() as session:
            stmt = (
                select(model_class.config_data)
                .where(col(model_class.tenant_id) == tenant_id)
                .where(col(model_class.name) == name)
            )
            row = session.exec(stmt).first()

        if row is None:
            raise FileNotFoundError(f"{ERROR_CONFIG_NOT_FOUND}{config_type}/{name}")
        return row

    def create_config_db(
        self,
        config_type: str,
        name: str,
        data: dict,
        tenant_id: str,
        user_id: str,
    ) -> dict:
        """Create a new config record in the DB.

        Args:
            config_type: One of 'workflows', 'stages', 'agents'.
            name: Config name (must be unique per tenant).
            data: Config data dictionary.
            tenant_id: Tenant identifier.
            user_id: ID of the user creating the config (for audit trail).

        Returns:
            The saved config data dict.

        Raises:
            ValueError: If config_type, name, or data is invalid, or validation fails.
            FileExistsError: If a record with (tenant_id, name) already exists.
        """
        _validate_config_type(config_type)
        _validate_name(name)
        _validate_name(tenant_id)
        _check_data_size(data)

        from datetime import datetime as _datetime

        from sqlmodel import col, select

        from temper_ai.storage.database.manager import get_session

        model_class = get_db_model(config_type)

        validation = self.validate_config(config_type, data)
        if not validation["valid"]:
            raise ValueError(
                f"{_CONFIG_VALIDATION_FAILED}{'; '.join(validation['errors'])}"
            )

        with get_session() as session:
            existing = session.exec(
                select(model_class.id)
                .where(col(model_class.tenant_id) == tenant_id)
                .where(col(model_class.name) == name)
            ).first()
            if existing is not None:
                raise FileExistsError(f"Config already exists: {config_type}/{name}")

            now = _datetime.now(UTC)
            record = model_class(
                tenant_id=tenant_id,
                name=name,
                version=1,
                config_data=data,
                created_by=user_id,
                updated_by=user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.commit()

        logger.info(
            "DB created config: %s/%s (tenant=%s)", config_type, name, tenant_id
        )
        return data

    def update_config_db(
        self,
        config_type: str,
        name: str,
        data: dict,
        tenant_id: str,
        user_id: str,
    ) -> dict:
        """Update an existing config record in the DB.

        Args:
            config_type: One of 'workflows', 'stages', 'agents'.
            name: Config name.
            data: New config data dictionary.
            tenant_id: Tenant identifier.
            user_id: ID of the user updating the config (for audit trail).

        Returns:
            The updated config data dict.

        Raises:
            ValueError: If config_type, name, or data is invalid, or validation fails.
            FileNotFoundError: If no matching record exists.
        """
        _validate_config_type(config_type)
        _validate_name(name)
        _validate_name(tenant_id)
        _check_data_size(data)

        from datetime import datetime as _datetime

        from sqlmodel import col, select

        from temper_ai.storage.database.manager import get_session

        model_class = get_db_model(config_type)

        validation = self.validate_config(config_type, data)
        if not validation["valid"]:
            raise ValueError(
                f"{_CONFIG_VALIDATION_FAILED}{'; '.join(validation['errors'])}"
            )

        with get_session() as session:
            stmt = (
                select(model_class)
                .where(col(model_class.tenant_id) == tenant_id)
                .where(col(model_class.name) == name)
            )
            record = session.exec(stmt).first()
            if record is None:
                raise FileNotFoundError(f"{ERROR_CONFIG_NOT_FOUND}{config_type}/{name}")

            record.config_data = data
            record.version = record.version + 1
            record.updated_by = user_id
            record.updated_at = _datetime.now(UTC)
            session.add(record)
            session.commit()

        logger.info(
            "DB updated config: %s/%s (tenant=%s)", config_type, name, tenant_id
        )
        return data

    def delete_config_db(self, config_type: str, name: str, tenant_id: str) -> dict:
        """Delete a config record from the DB.

        Args:
            config_type: One of 'workflows', 'stages', 'agents'.
            name: Config name.
            tenant_id: Tenant identifier.

        Returns:
            Dict confirming deletion with 'deleted' key.

        Raises:
            ValueError: If config_type or name is invalid.
            FileNotFoundError: If no matching record exists.
        """
        _validate_config_type(config_type)
        _validate_name(name)
        _validate_name(tenant_id)

        from sqlmodel import col, select

        from temper_ai.storage.database.manager import get_session

        model_class = get_db_model(config_type)

        with get_session() as session:
            stmt = (
                select(model_class)
                .where(col(model_class.tenant_id) == tenant_id)
                .where(col(model_class.name) == name)
            )
            record = session.exec(stmt).first()
            if record is None:
                raise FileNotFoundError(f"{ERROR_CONFIG_NOT_FOUND}{config_type}/{name}")

            session.delete(record)
            session.commit()

        logger.info(
            "DB deleted config: %s/%s (tenant=%s)", config_type, name, tenant_id
        )
        return {"deleted": f"{config_type}/{name}"}
