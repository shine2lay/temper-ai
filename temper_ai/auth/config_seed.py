"""One-time CLI helper to seed all YAML configs from configs/ directory into the DB."""

import logging
from pathlib import Path
from typing import Any

from temper_ai.auth.config_sync import ConfigSyncService

logger = logging.getLogger(__name__)

_SUBDIR_TO_CONFIG_TYPE: dict[str, str] = {
    "workflows": "workflow",
    "stages": "stage",
    "agents": "agent",
}


def _read_yaml_file(file_path: Path) -> str:
    """Read YAML file contents as a string."""
    return file_path.read_text(encoding="utf-8")


def _seed_directory(
    sync_service: ConfigSyncService,
    directory: Path,
    config_type: str,
    tenant_id: str,
    user_id: str,
    errors: list[str],
) -> int:
    """Import all YAML files in a directory. Returns count of successes."""
    count = 0
    if not directory.is_dir():
        logger.debug("Directory not found, skipping: %s", directory)
        return count

    for file_path in sorted(directory.glob("*.yaml")):
        name = file_path.stem
        try:
            yaml_content = _read_yaml_file(file_path)
            sync_service.import_config(
                tenant_id=tenant_id,
                config_type=config_type,
                name=name,
                yaml_content=yaml_content,
                user_id=user_id,
            )
            count += 1
            logger.info("Seeded %s config: %s", config_type, name)
        except (ValueError, OSError) as exc:
            msg = f"{config_type}/{name}: {exc}"
            errors.append(msg)
            logger.warning("Failed to seed config %s: %s", name, exc)

    return count


def seed_configs(
    config_root: str,
    tenant_id: str,
    user_id: str,
) -> dict:
    """Read all YAML files from configs/{workflows,stages,agents}/ and import to DB.

    Returns dict with counts: { "workflows": int, "stages": int, "agents": int, "errors": list }
    """
    root = Path(config_root)
    sync_service = ConfigSyncService()
    errors: list[str] = []
    counts: dict[str, Any] = {
        "workflows": 0,
        "stages": 0,
        "agents": 0,
        "errors": errors,
    }

    for subdir, config_type in _SUBDIR_TO_CONFIG_TYPE.items():
        directory = root / subdir
        count_key = subdir  # "workflows", "stages", "agents"
        counts[count_key] = _seed_directory(
            sync_service=sync_service,
            directory=directory,
            config_type=config_type,
            tenant_id=tenant_id,
            user_id=user_id,
            errors=errors,
        )

    logger.info(
        "Seed complete — workflows=%d stages=%d agents=%d errors=%d",
        counts["workflows"],
        counts["stages"],
        counts["agents"],
        len(errors),
    )
    return counts
