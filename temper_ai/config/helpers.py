"""Config helpers — YAML parsing, env var substitution, security checks."""

import json
import logging
import os
import re
from pathlib import Path
from re import Match
from typing import Any, cast

import yaml

logger = logging.getLogger(__name__)

# Security limits
MAX_CONFIG_SIZE = 1_048_576  # 1MB
MAX_YAML_NESTING_DEPTH = 20
MAX_YAML_NODES = 10_000
MAX_ENV_VAR_SIZE = 10_000

SUPPORTED_SCHEMA_VERSION = "1.0"


class ConfigError(Exception):
    """Base error for config operations."""


class ConfigNotFoundError(ConfigError):
    """Config not found."""


class ConfigValidationError(ConfigError):
    """Config failed validation."""


class SchemaVersionError(ConfigError):
    """Config schema version not supported."""


# -- YAML parsing with security checks --


def load_yaml_file(file_path: Path) -> dict[str, Any]:
    """Load a YAML/JSON file with security checks.

    Args:
        file_path: Path to the config file.

    Returns:
        Parsed config dict.
    """
    if not file_path.exists():
        raise ConfigNotFoundError(f"Config file not found: {file_path}")

    file_size = file_path.stat().st_size
    if file_size > MAX_CONFIG_SIZE:
        raise ConfigValidationError(
            f"Config file too large: {file_size} bytes (max: {MAX_CONFIG_SIZE})"
        )

    try:
        with open(file_path, encoding="utf-8") as f:
            if file_path.suffix == ".json":
                config = json.load(f)
            else:
                config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigValidationError(f"YAML parsing failed for {file_path}: {e}") from e
    except json.JSONDecodeError as e:
        raise ConfigValidationError(f"JSON parsing failed for {file_path}: {e}") from e

    if not isinstance(config, dict):
        raise ConfigValidationError(f"Config must be a mapping, got {type(config).__name__}")

    _validate_structure(config, file_path)
    return cast(dict[str, Any], config)


def _validate_structure(
    config: Any,
    file_path: Path,
    depth: int = 0,
    visited: set[int] | None = None,
    node_count: list[int] | None = None,
) -> None:
    """Check for excessive nesting, node count, and circular refs."""
    if visited is None:
        visited = set()
    if node_count is None:
        node_count = [0]

    if depth > MAX_YAML_NESTING_DEPTH:
        raise ConfigValidationError(
            f"{file_path}: exceeds max nesting depth of {MAX_YAML_NESTING_DEPTH}"
        )
    node_count[0] += 1
    if node_count[0] > MAX_YAML_NODES:
        raise ConfigValidationError(
            f"{file_path}: exceeds max node count of {MAX_YAML_NODES}"
        )

    if not isinstance(config, (dict, list)):
        return

    obj_id = id(config)
    if obj_id in visited:
        raise ConfigValidationError(f"{file_path}: circular reference detected")
    visited.add(obj_id)

    children = config.values() if isinstance(config, dict) else config
    try:
        for child in children:
            _validate_structure(child, file_path, depth + 1, visited, node_count)
    finally:
        visited.discard(obj_id)


# -- Environment variable substitution --


def substitute_env_vars(config: Any) -> Any:
    """Recursively substitute ${VAR} and ${VAR:default} in config values."""
    if isinstance(config, dict):
        return {k: substitute_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [substitute_env_vars(item) for item in config]
    elif isinstance(config, str):
        return _substitute_env_var_string(config)
    return config


def _substitute_env_var_string(value: str) -> str:
    """Replace ${VAR} and ${VAR:default} in a single string."""
    pattern = r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}"

    def replacer(match: Match[str]) -> str:
        var_name = match.group(1)
        default_value = match.group(2)

        if var_name in os.environ:
            env_value = os.environ[var_name]
            if len(env_value) > MAX_ENV_VAR_SIZE:
                raise ConfigValidationError(
                    f"Env var '{var_name}' too large: {len(env_value)} chars"
                )
            return env_value
        elif default_value is not None:
            return default_value
        else:
            raise ConfigValidationError(
                f"Environment variable '{var_name}' is required but not set"
            )

    return re.sub(pattern, replacer, value)


# -- Type detection --


def detect_config_type(config: dict[str, Any]) -> str:
    """Detect config type from top-level keys.

    Returns:
        "workflow", "stage", or "agent"
    """
    if "workflow" in config:
        return "workflow"
    elif "stage" in config:
        return "stage"
    elif "agent" in config:
        return "agent"
    else:
        raise ConfigValidationError(
            f"Cannot detect config type. Expected top-level key: workflow, stage, or agent. "
            f"Got: {list(config.keys())}"
        )


def check_schema_version(config: dict[str, Any]) -> None:
    """Check that schema_version is supported."""
    version = config.get("schema_version", "1.0")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Config schema version '{version}' is not supported. "
            f"Supported: {SUPPORTED_SCHEMA_VERSION}"
        )
