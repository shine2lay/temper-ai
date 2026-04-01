"""YAML exporter — read from DB and serialize to YAML."""

import logging

import yaml
from sqlmodel import select

from temper_ai.config.helpers import ConfigNotFoundError
from temper_ai.config.models import Config
from temper_ai.config.store import ConfigStore
from temper_ai.database import get_session

logger = logging.getLogger(__name__)


def export_yaml(name: str, config_type: str, store: ConfigStore | None = None) -> str:
    """Export a config from DB as a YAML string.

    Note: env vars will be in their ${VAR} form (not resolved),
    since we store the raw config in DB.

    Args:
        name: Config name.
        config_type: One of "workflow", "stage", "agent".
        store: ConfigStore instance.

    Returns:
        YAML string.
    """
    with get_session() as session:
        row = session.exec(
            select(Config)
            .where(Config.type == config_type)
            .where(Config.name == name)
        ).first()

        if row is None:
            raise ConfigNotFoundError(f"{config_type} config '{name}' not found")

        # Extract inside session
        config = row.config

    return yaml.dump(config, default_flow_style=False, sort_keys=False)
