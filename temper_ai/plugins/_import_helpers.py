"""Helpers for importing and translating external agent configurations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")
DEFAULT_VERSION = "1.0"


def load_yaml_safe(path: Path) -> dict[str, Any]:
    """Load a YAML file safely.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If file is not valid YAML or not a dict.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML dict, got {type(data).__name__}")
    return data


def _sanitize_name(name: str) -> str:
    """Sanitize a name for use in agent config."""
    sanitized = _SAFE_NAME_RE.sub("_", name.strip())
    return sanitized.lower()[:64] or "unnamed_agent"  # scanner: skip-magic


def build_agent_config_dict(
    name: str,
    description: str,
    agent_type: str,
    plugin_config: dict[str, Any],
    version: str = DEFAULT_VERSION,
) -> dict[str, Any]:
    """Build a valid Temper AI agent config dict."""
    return {
        "agent": {
            "name": _sanitize_name(name),
            "description": description,
            "version": version,
            "type": agent_type,
            "plugin_config": plugin_config,
            "error_handling": {
                "retry_strategy": "ExponentialBackoff",
                "max_retries": 2,
                "fallback": "GracefulDegradation",
                "escalate_to_human_after": 2,
            },
        },
    }


def write_agent_yaml(
    config_dicts: list[dict[str, Any]],
    output_dir: Path,
) -> list[Path]:
    """Write agent config dicts to individual YAML files.

    Returns list of paths written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for config_dict in config_dicts:
        agent_name = config_dict["agent"]["name"]
        out_path = output_dir / f"{agent_name}.yaml"
        with open(out_path, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
        written.append(out_path)
    return written
