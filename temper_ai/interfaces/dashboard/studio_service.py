"""Business logic layer for Workflow Studio config CRUD operations.

Provides listing, reading, creating, updating, deleting, and validating
YAML-based configuration files for the Temper AI dashboard.
"""
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Type

import yaml
from pydantic import BaseModel, ValidationError

from temper_ai.workflow.config_loader import ConfigLoader
from temper_ai.stage._schemas import StageConfig
from temper_ai.tools._schemas import ToolConfig
from temper_ai.workflow._schemas import WorkflowConfig
from temper_ai.interfaces.dashboard.constants import DEFAULT_ENCODING, ERROR_CONFIG_NOT_FOUND
from temper_ai.storage.schemas.agent_config import AgentConfig

logger = logging.getLogger(__name__)

# Name validation: alphanumeric, hyphens, underscores only
_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Maximum config data size in bytes (1 MB)
MAX_CONFIG_SIZE_BYTES = 1_048_576

# Valid config types exposed by the API
VALID_CONFIG_TYPES = frozenset({"workflows", "stages", "agents", "tools"})

# Mapping from API config type to ConfigLoader type string
_LOADER_TYPE_MAP: Dict[str, str] = {
    "workflows": "workflow",
    "stages": "stage",
    "agents": "agent",
    "tools": "tool",
}

# Mapping from API config type to Pydantic model class
_MODEL_MAP: Dict[str, Type[BaseModel]] = {
    "workflows": WorkflowConfig,
    "stages": StageConfig,
    "agents": AgentConfig,
    "tools": ToolConfig,
}

# Mapping from API config type to config subdirectory name
_DIR_MAP: Dict[str, str] = {
    "workflows": "workflows",
    "stages": "stages",
    "agents": "agents",
    "tools": "tools",
}

# Mapping from API config type to the top-level wrapper key in YAML
_WRAPPER_KEY_MAP: Dict[str, str] = {
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


def _extract_config_summary(config_data: Dict[str, Any], wrapper_key: str) -> Dict[str, Any]:
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

    def __init__(self, config_root: str = "configs") -> None:
        """Initialize the studio service.

        Args:
            config_root: Root directory for configuration files.
        """
        self._config_root = Path(config_root)
        self._loader = ConfigLoader(config_root=config_root)

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

        configs: List[Dict[str, Any]] = []
        for name in names:
            try:
                data = self._load_raw_config(config_type, name)
                summary = _extract_config_summary(data, wrapper_key)
                summary["name"] = summary["name"] or name
                configs.append(summary)
            except (FileNotFoundError, yaml.YAMLError) as exc:
                logger.warning("Failed to read config %s/%s: %s", config_type, name, exc)
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

        return self._load_raw_config(config_type, name)

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
                f"Config validation failed: {'; '.join(validation['errors'])}"
            )

        self._write_config(file_path, data)
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
                f"Config validation failed: {'; '.join(validation['errors'])}"
            )

        self._write_config(file_path, data)
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
        errors: List[str] = []

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

    def _load_raw_config(self, config_type: str, name: str) -> Dict[str, Any]:
        """Load config data from YAML file as a dict.

        Args:
            config_type: Config type string.
            name: Config name.

        Returns:
            Parsed YAML as dict.

        Raises:
            FileNotFoundError: If file does not exist.
        """
        file_path = self._get_config_path(config_type, name)
        if not file_path.exists():
            raise FileNotFoundError(f"{ERROR_CONFIG_NOT_FOUND}{config_type}/{name}")

        text = file_path.read_text(encoding=DEFAULT_ENCODING)
        parsed = yaml.safe_load(text)
        if not isinstance(parsed, dict):
            raise ValueError(f"Config file is not a valid YAML mapping: {config_type}/{name}")
        return parsed

    @staticmethod
    def _write_config(file_path: Path, data: dict) -> None:
        """Write config data to a YAML file.

        Args:
            file_path: Target file path.
            data: Config data to serialize.
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_text = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
        file_path.write_text(yaml_text, encoding=DEFAULT_ENCODING)
