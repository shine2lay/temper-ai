"""
Configuration helper utilities.

Shared utilities for configuration parsing, merging, and validation.
"""
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

# Import secrets management for detection
SecretReference: Optional[Any] = None
detect_secret_patterns: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None

try:
    from temper_ai.shared.utils.secrets import SecretReference, detect_secret_patterns
except ImportError:
    # Graceful fallback if secrets module not available
    pass


def merge_configs(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two configuration dictionaries.

    Args:
        base: Base configuration
        override: Override configuration (takes precedence)

    Returns:
        Merged configuration

    Example:
        >>> base = {"llm": {"temperature": 0.7, "model": "gpt-4"}}
        >>> override = {"llm": {"temperature": 0.9}}
        >>> merge_configs(base, override)
        {"llm": {"temperature": 0.9, "model": "gpt-4"}}
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursively merge nested dicts
            result[key] = merge_configs(result[key], value)
        else:
            # Override value
            result[key] = value

    return result


def extract_required_fields(
    config: Dict[str, Any],
    fields: List[str],
    config_name: str = "config"
) -> Dict[str, Any]:
    """
    Extract required fields from configuration.

    Args:
        config: Configuration dictionary
        fields: List of required field names (supports dot notation)
        config_name: Name for error messages

    Returns:
        Dict with extracted fields

    Raises:
        ValueError: If required field is missing

    Example:
        >>> config = {"agent": {"name": "foo", "model": "gpt-4"}}
        >>> extract_required_fields(config, ["agent.name", "agent.model"])
        {"agent.name": "foo", "agent.model": "gpt-4"}
    """
    result = {}

    for field in fields:
        value = get_nested_value(config, field)
        if value is None:
            raise ValueError(f"Required field '{field}' missing from {config_name}")
        result[field] = value

    return result


def get_nested_value(
    config: Dict[str, Any],
    path: str,
    default: Any = None
) -> Any:
    """
    Get value from nested dict using dot notation.

    Args:
        config: Configuration dictionary
        path: Dot-separated path (e.g., "agent.inference.model")
        default: Default value if path not found

    Returns:
        Value at path or default

    Example:
        >>> config = {"agent": {"inference": {"model": "gpt-4"}}}
        >>> get_nested_value(config, "agent.inference.model")
        "gpt-4"
        >>> get_nested_value(config, "agent.missing.field", "default")
        "default"
    """
    keys = path.split('.')
    value = config

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value


def set_nested_value(
    config: Dict[str, Any],
    path: str,
    value: Any
) -> None:
    """
    Set value in nested dict using dot notation.

    Args:
        config: Configuration dictionary (modified in place)
        path: Dot-separated path (e.g., "agent.inference.model")
        value: Value to set

    Example:
        >>> config = {"agent": {}}
        >>> set_nested_value(config, "agent.inference.model", "gpt-4")
        >>> config
        {"agent": {"inference": {"model": "gpt-4"}}}
    """
    keys = path.split('.')
    current = config

    # Navigate/create nested dicts
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    # Set value
    current[keys[-1]] = value


def validate_config_structure(
    config: Dict[str, Any],
    required_keys: List[str],
    config_name: str = "config"
) -> None:
    """
    Validate that config has required top-level keys.

    Args:
        config: Configuration dictionary
        required_keys: List of required top-level keys
        config_name: Name for error messages

    Raises:
        ValueError: If required key is missing
    """
    for key in required_keys:
        if key not in config:
            raise ValueError(
                f"Invalid {config_name}: missing required key '{key}'"
            )


def _redact_secret_reference(value: str) -> str:
    """Redact secret reference based on type."""
    if value.startswith("${env:"):
        return "${env:***REDACTED***}"
    elif value.startswith("${vault:"):
        return "${vault:***REDACTED***}"
    elif value.startswith("${aws:"):
        return "${aws:***REDACTED***}"
    else:
        return "***REDACTED***"


def _sanitize_dict(obj: Dict[str, Any], secret_patterns: List[str]) -> Dict[str, Any]:
    """Sanitize dictionary recursively."""
    result = {}
    for key, value in obj.items():
        # Check if key matches secret pattern
        if not any(pattern in key.lower() for pattern in secret_patterns):
            # Key is safe, recurse normally
            result[key] = _sanitize_value(value, secret_patterns)
            continue

        # Key looks like a secret - check value type
        if isinstance(value, (dict, list)):
            # Recurse even if key looks like a secret
            result[key] = _sanitize_value(value, secret_patterns)
        elif isinstance(value, str) and SecretReference is not None and SecretReference.is_reference(value):
            # Redact secret reference
            result[key] = _redact_secret_reference(value)
        else:
            # Redact primitive values
            result[key] = "***REDACTED***"
    return result


def _sanitize_string(obj: str) -> str:
    """Sanitize string value."""
    # Check if value contains secret patterns
    if detect_secret_patterns is not None:
        try:
            is_secret, confidence = detect_secret_patterns(obj)
            if is_secret and confidence == "high":
                return "***REDACTED***"
        except ValueError:
            pass  # Skip detection for oversized inputs
    # Check if value is a secret reference
    if SecretReference is not None and SecretReference.is_reference(obj):
        return "***SECRET_REF***"
    return obj


def _sanitize_value(obj: Any, secret_patterns: List[str]) -> Any:
    """Recursively sanitize any value."""
    if isinstance(obj, dict):
        return _sanitize_dict(obj, secret_patterns)
    elif isinstance(obj, list):
        return [_sanitize_value(item, secret_patterns) for item in obj]
    elif isinstance(obj, str):
        return _sanitize_string(obj)
    else:
        return obj


def sanitize_config_for_display(
    config: Dict[str, Any],
    secret_keys: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Sanitize configuration for safe display/logging.

    Redacts:
    - Secret references (${env:API_KEY})
    - Known secret key names (api_key, password, token, etc.)
    - Values that look like secrets (based on pattern detection)

    Args:
        config: Configuration dictionary
        secret_keys: Additional keys to redact (case-insensitive)

    Returns:
        Sanitized copy of configuration

    Example:
        >>> config = {"api_key": "secret123", "model": "gpt-4"}
        >>> sanitize_config_for_display(config)
        {"api_key": "***REDACTED***", "model": "gpt-4"}

        >>> config = {"api_key_ref": "${env:OPENAI_API_KEY}"}
        >>> sanitize_config_for_display(config)
        {"api_key_ref": "${env:***REDACTED***}"}
    """
    if secret_keys is None:
        secret_keys = []

    # Import key names from centralized registry
    from temper_ai.shared.utils.secret_patterns import SECRET_KEY_NAMES

    secret_patterns = [p.lower() for p in SECRET_KEY_NAMES + secret_keys]

    return cast(Dict[str, Any], _sanitize_value(config, secret_patterns))


def resolve_config_path(
    path: str,
    config_root: Optional[Path] = None
) -> Path:
    """
    Resolve configuration file path with security validation.

    Args:
        path: Config file path (must be relative to config_root)
        config_root: Root directory for relative paths

    Returns:
        Resolved absolute Path (guaranteed within config_root)

    Raises:
        ValueError: If path is absolute or attempts directory traversal
        FileNotFoundError: If path does not exist
    """
    if config_root is None:
        config_root = Path.cwd() / "configs"

    config_root_resolved = config_root.resolve()

    # Reject null bytes (path injection)
    if '\x00' in path:
        raise ValueError("Config path contains null bytes")

    path_obj = Path(path)

    # Reject absolute paths — config paths must be relative to config_root
    if path_obj.is_absolute():
        raise ValueError(
            f"Config path must be relative to config_root, "
            f"got absolute path: {path}"
        )

    # Reject explicit traversal components
    if ".." in path_obj.parts:
        raise ValueError(
            f"Config path must not contain '..': {path}"
        )

    # Resolve relative to config_root
    resolved = (config_root_resolved / path_obj).resolve()

    # Verify resolved path stays within config_root (catches symlink escapes)
    try:
        resolved.relative_to(config_root_resolved)
    except ValueError:
        raise ValueError(
            f"Config path escapes config_root: {path}"
        )

    if not resolved.exists():
        raise FileNotFoundError(f"Config file not found: {resolved}")

    return resolved
