"""YAML importer — parse YAML files and store in DB."""

import logging
from pathlib import Path
from typing import Any

from temper_ai.config.helpers import (
    ConfigValidationError,
    detect_config_type,
    load_yaml_file,
)
from temper_ai.config.store import ConfigStore

logger = logging.getLogger(__name__)


def import_yaml(file_path: str | Path, store: ConfigStore | None = None) -> dict[str, Any]:
    """Import a single YAML config file into the DB.

    Flow: read file → security checks → parse → detect type → validate → store.

    Args:
        file_path: Path to YAML file.
        store: ConfigStore instance. Creates one if not provided.

    Returns:
        Dict with id, type, name of the imported config.
    """
    store = store or ConfigStore()
    path = Path(file_path)

    # Parse YAML with security checks
    raw_config = load_yaml_file(path)

    # Detect type from top-level key
    config_type = detect_config_type(raw_config)

    # Extract name from inner config
    inner = raw_config.get(config_type, {})
    name = inner.get("name")
    if not name:
        raise ConfigValidationError(
            f"Config must have a 'name' field inside '{config_type}' block"
        )

    schema_version = raw_config.get("schema_version", "1.0")

    # Store in DB (with ${VAR} still in place — resolved at read time)
    config_id = store.put(
        name=name,
        config_type=config_type,
        config=raw_config,
        schema_version=schema_version,
    )

    logger.info("Imported %s config '%s' from %s", config_type, name, path)
    return {"id": config_id, "type": config_type, "name": name}


def import_directory(dir_path: str | Path, store: ConfigStore | None = None) -> list[dict[str, Any]]:
    """Import all YAML files from a directory (non-recursive).

    Args:
        dir_path: Directory containing YAML files.
        store: ConfigStore instance.

    Returns:
        List of import results.
    """
    store = store or ConfigStore()
    directory = Path(dir_path)

    if not directory.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    results = []
    errors = []

    for file_path in sorted(directory.iterdir()):
        if file_path.suffix not in (".yaml", ".yml", ".json"):
            continue
        try:
            result = import_yaml(file_path, store)
            results.append(result)
        except Exception as e:
            errors.append({"file": str(file_path), "error": str(e)})
            logger.warning("Failed to import %s: %s", file_path, e)

    if errors:
        logger.warning("%d files failed to import", len(errors))

    return results
