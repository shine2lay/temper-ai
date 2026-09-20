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


def parse_yaml(file_path: str | Path) -> dict[str, Any]:
    """Read and validate a YAML config without touching the database.

    Flow: read file → security checks → parse → detect type → validate.
    Split out of ``import_yaml`` so a bulk load can parse every file first
    (where the per-file failures actually are) and then write them in one
    transaction instead of one per file.

    Returns:
        Dict with name, config_type, config, schema_version — the arguments
        ``ConfigStore.put``/``put_many`` expect.
    """
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

    return {
        "name": name,
        "config_type": config_type,
        "config": raw_config,
        "schema_version": raw_config.get("schema_version", "1.0"),
    }


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

    parsed = parse_yaml(path)
    config_type = parsed["config_type"]
    name = parsed["name"]

    # Store in DB (with ${VAR} still in place — resolved at read time)
    config_id = store.put(
        name=name,
        config_type=config_type,
        config=parsed["config"],
        schema_version=parsed["schema_version"],
    )

    logger.info("Imported %s config '%s' from %s", config_type, name, path)
    return {"id": config_id, "type": config_type, "name": name}


# Subdirectories holding YAMLs that are not workflow/stage/agent configs.
NON_CONFIG_DIRS = ("mcp_servers", "tools")


def import_config_tree(root: str | Path, store: ConfigStore | None = None) -> int:
    """Recursively import every config YAML under ``root``. Returns the count.

    Parses all files first, then writes them in a single transaction. Doing a
    ``put`` per file cost a disk sync each time — 6.5s for this repo's tree,
    paid on every server and worker startup.

    A file that fails to parse is skipped and logged at WARNING, not raised:
    one bad YAML must not leave the process with no configs at all, but it
    must also be visible. The CLI's default log level is WARNING, so a
    ``debug`` here (what this used to be) meant ``temper validate`` could
    swallow a YAML syntax error and report on whatever was left. A database
    failure is deliberately outside the per-file guard and propagates.
    """
    store = store or ConfigStore()
    parsed: list[dict[str, Any]] = []

    for yaml_file in sorted(Path(root).rglob("*.yaml")):
        if any(part in NON_CONFIG_DIRS for part in yaml_file.parts):
            continue
        try:
            parsed.append(parse_yaml(yaml_file))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipped config %s: %s", yaml_file, exc)

    if parsed:
        store.put_many(parsed)
    return len(parsed)


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
