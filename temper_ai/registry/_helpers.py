"""Helper functions for the agent registry module."""
import uuid
from typing import Any, Dict

import yaml

from temper_ai.registry.constants import PERSISTENT_NAMESPACE_PREFIX


def build_memory_namespace(agent_name: str) -> str:
    """Return the memory namespace for a persistent agent."""
    return f"{PERSISTENT_NAMESPACE_PREFIX}{agent_name}"


def build_persistent_memory_config(agent_name: str) -> Dict[str, Any]:
    """Return a memory config dict for persistent agent storage."""
    return {
        "enabled": True,
        "namespace": build_memory_namespace(agent_name),
    }


def generate_agent_id() -> str:
    """Generate a unique agent ID."""
    return uuid.uuid4().hex


def load_config_from_path(config_path: str) -> Dict[str, Any]:
    """Load and return a YAML agent config from a file path.

    Args:
        config_path: Absolute path to the YAML configuration file.

    Returns:
        Parsed configuration as a dict.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the YAML content is not a mapping.
    """
    with open(config_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(
            f"Agent config at '{config_path}' must be a YAML mapping, "
            f"got {type(data).__name__}"
        )
    return data
