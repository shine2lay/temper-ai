"""Extracted validation and I/O helpers for StudioService.

These are stateless helpers that were originally methods on StudioService.
Moving them here keeps the main class under the 500-line / 20-method thresholds.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from temper_ai.interfaces.dashboard.constants import (
    DEFAULT_ENCODING,
    ERROR_CONFIG_NOT_FOUND,
)

logger = logging.getLogger(__name__)


def load_raw_config(
    config_type: str,
    name: str,
    config_root: Path,
    dir_map: dict[str, str],
) -> dict[str, Any]:
    """Load config data from YAML file as a dict.

    Args:
        config_type: Config type string.
        name: Config name.
        config_root: Root configuration directory.
        dir_map: Mapping from config type to subdirectory name.

    Returns:
        Parsed YAML as dict.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file is not a valid YAML mapping.
    """
    file_path = config_root / dir_map[config_type] / f"{name}.yaml"
    if not file_path.exists():
        raise FileNotFoundError(f"{ERROR_CONFIG_NOT_FOUND}{config_type}/{name}")

    text = file_path.read_text(encoding=DEFAULT_ENCODING)
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Config file is not a valid YAML mapping: {config_type}/{name}"
        )
    return parsed


def write_config(file_path: Path, data: dict) -> None:
    """Write config data to a YAML file.

    Args:
        file_path: Target file path.
        data: Config data to serialize.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_text = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    file_path.write_text(yaml_text, encoding=DEFAULT_ENCODING)


def get_db_model(config_type: str):
    """Return the SQLModel class for the given config_type.

    Uses a lazy import to avoid circular import at module load time.

    Args:
        config_type: One of 'workflows', 'stages', 'agents'.

    Returns:
        SQLModel table class for the config type.

    Raises:
        ValueError: If config_type has no DB model (e.g. 'tools').
    """
    from temper_ai.storage.database.models_tenancy import (
        AgentConfigDB,
        StageConfigDB,
        WorkflowConfigDB,
    )

    _db_map = {
        "workflows": WorkflowConfigDB,
        "stages": StageConfigDB,
        "agents": AgentConfigDB,
    }
    if config_type not in _db_map:
        raise ValueError(
            f"Config type '{config_type}' does not have a DB-backed model."
        )
    return _db_map[config_type]
