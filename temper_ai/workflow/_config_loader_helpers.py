"""Helper functions extracted from ConfigLoader to reduce class size.

Contains:
- File parsing and validation
- Config structure security validation
- Environment variable substitution
- Secret resolution
- Template variable substitution
- Schema validation
"""

import json
import logging
import os
import re
from pathlib import Path
from re import Match
from typing import Any, cast

import yaml
from pydantic import ValidationError

from temper_ai.shared.utils.exceptions import ConfigNotFoundError, ConfigValidationError
from temper_ai.shared.utils.secrets import SecretReference, resolve_secret
from temper_ai.stage._schemas import StageConfig
from temper_ai.storage.schemas.agent_config import AgentConfig
from temper_ai.tools._schemas import ToolConfig
from temper_ai.workflow._schemas import WorkflowConfig
from temper_ai.workflow._triggers import CronTrigger, EventTrigger, ThresholdTrigger
from temper_ai.workflow.env_var_validator import EnvVarValidator
from temper_ai.workflow.security_limits import CONFIG_SECURITY

logger = logging.getLogger(__name__)

MAX_CONFIG_SIZE = CONFIG_SECURITY.MAX_CONFIG_SIZE
MAX_ENV_VAR_SIZE = CONFIG_SECURITY.MAX_ENV_VAR_SIZE
MAX_YAML_NESTING_DEPTH = CONFIG_SECURITY.MAX_YAML_NESTING_DEPTH
MAX_YAML_NODES = CONFIG_SECURITY.MAX_YAML_NODES


def load_config_file(directory: Path, name: str) -> dict[str, Any]:
    """Load a configuration file (YAML or JSON).

    Tries both .yaml, .yml, and .json extensions.
    """
    for ext in [".yaml", ".yml", ".json"]:
        file_path = directory / f"{name}{ext}"
        if file_path.exists():
            return load_and_validate_config_file(file_path)

    raise ConfigNotFoundError(
        message=f"Config file not found: {name} in {directory}\nTried extensions: .yaml, .yml, .json",
        config_path=str(directory / name),
    )


def load_and_validate_config_file(file_path: Path) -> dict[str, Any]:
    """Load and validate a YAML or JSON configuration file with security protections.

    Args:
        file_path: Path to config file

    Returns:
        Parsed configuration dictionary

    Raises:
        ConfigValidationError: If file too large, parsing fails, or security limits exceeded
    """
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

        validate_config_structure(config, file_path)

        return cast(dict[str, Any], config)

    except yaml.YAMLError as e:
        raise ConfigValidationError(f"YAML parsing failed for {file_path}: {e}") from e
    except json.JSONDecodeError as e:
        raise ConfigValidationError(f"JSON parsing failed for {file_path}: {e}") from e
    except Exception as e:
        raise ConfigValidationError(
            f"Failed to parse config file {file_path}: {e}"
        ) from e


def _check_config_limits(
    file_path: Path,
    current_depth: int,
    node_count: list[int],
) -> None:
    """Raise if config exceeds depth or node count limits."""
    if current_depth > MAX_YAML_NESTING_DEPTH:
        raise ConfigValidationError(
            f"Config file {file_path} exceeds maximum nesting depth of "
            f"{MAX_YAML_NESTING_DEPTH} levels. This may indicate a YAML bomb attack or malformed config."
        )
    node_count[0] += 1
    if node_count[0] > MAX_YAML_NODES:
        raise ConfigValidationError(
            f"Config file {file_path} exceeds maximum node count of "
            f"{MAX_YAML_NODES}. This may indicate a YAML bomb (billion laughs) attack."
        )


def validate_config_structure(
    config: Any,
    file_path: Path,
    current_depth: int = 0,
    visited: set[int] | None = None,
    node_count: list[int] | None = None,
) -> None:
    """Validate config structure for security (depth, node count, circular refs)."""
    if visited is None:
        visited = set()
    if node_count is None:
        node_count = [0]

    _check_config_limits(file_path, current_depth, node_count)

    if not isinstance(config, (dict, list)):
        return

    obj_id = id(config)
    if obj_id in visited:
        raise ConfigValidationError(
            f"Circular reference detected in config file {file_path}. "
            f"This may cause infinite loops during processing."
        )
    visited.add(obj_id)

    children = config.values() if isinstance(config, dict) else config
    try:
        for child in children:
            validate_config_structure(
                child, file_path, current_depth + 1, visited, node_count
            )
    finally:
        visited.discard(obj_id)


def substitute_env_vars(config: Any) -> Any:
    """Recursively substitute environment variables in config.

    Replaces ${VAR_NAME} with os.environ['VAR_NAME']
    Replaces ${VAR_NAME:default_value} with os.environ.get('VAR_NAME', 'default_value')
    """
    if isinstance(config, dict):
        return {k: substitute_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [substitute_env_vars(item) for item in config]
    elif isinstance(config, str):
        return substitute_env_var_string(config)
    else:
        return config


def substitute_env_var_string(value: str) -> str:
    """Substitute environment variables in a string with security validation."""
    if SecretReference.is_reference(value):
        return value

    pattern = r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}"

    def replacer(match: Match[str]) -> str:
        """Replace config placeholders with environment variables."""
        var_name = match.group(1)
        default_value = match.group(2)

        if var_name in os.environ:
            env_value = os.environ[var_name]
            validate_env_var_value(var_name, env_value)
            return env_value
        elif default_value is not None:
            validate_env_var_value(var_name, default_value)
            return default_value
        else:
            raise ConfigValidationError(
                f"Environment variable '{var_name}' is required but not set"
            )

    return re.sub(pattern, replacer, value)


def validate_env_var_value(var_name: str, value: str) -> None:
    """Validate environment variable value for security issues using context-aware validation."""
    validator = EnvVarValidator()
    is_valid, error_message = validator.validate(
        var_name=var_name, value=value, max_length=MAX_ENV_VAR_SIZE
    )

    if not is_valid:
        raise ConfigValidationError(error_message or "Validation failed")


def resolve_secrets(config: Any) -> Any:
    """Recursively resolve secret references in configuration."""
    try:
        return resolve_secret(config)
    except (ValueError, NotImplementedError) as e:
        raise ConfigValidationError(f"Secret resolution failed: {e}") from e


def substitute_template_vars(template: str, variables: dict[str, str]) -> str:
    """Substitute variables in a prompt template.

    Replaces {{var_name}} with variables['var_name']
    """
    pattern = r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}"

    def replacer(match: Match[str]) -> str:
        """Replace config placeholders with template variables."""
        var_name = match.group(1)
        if var_name not in variables:
            raise ConfigValidationError(
                f"Template variable '{var_name}' is required but not provided"
            )
        return variables[var_name]

    return re.sub(pattern, replacer, template)


def validate_config(config_type: str, config: dict[str, Any]) -> None:
    """Validate configuration against Pydantic schemas.

    Args:
        config_type: Type of config (agent, stage, workflow, tool, trigger)
        config: Configuration dictionary to validate

    Raises:
        ConfigValidationError: If validation fails
    """
    schema_map = {
        "agent": AgentConfig,
        "stage": StageConfig,
        "workflow": WorkflowConfig,
        "tool": ToolConfig,
    }

    try:
        if config_type == "trigger":
            trigger_type = config.get("trigger", {}).get("type")
            if trigger_type == "EventTrigger":
                EventTrigger(**config)
            elif trigger_type == "CronTrigger":
                CronTrigger(**config)
            elif trigger_type == "ThresholdTrigger":
                ThresholdTrigger(**config)
            else:
                raise ConfigValidationError(f"Unknown trigger type: {trigger_type}")
        elif config_type in schema_map:
            schema_map[config_type](**config)

    except ValidationError as e:
        raise ConfigValidationError(
            f"Config validation failed for {config_type}: {e}"
        ) from e
