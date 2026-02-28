"""
Configuration helper utilities.

Shared utilities for configuration parsing, merging, and validation.
"""

from collections.abc import Callable
from typing import Any, cast

# Import secrets management for detection
SecretReference: Any | None = None
detect_secret_patterns: Callable[[str], tuple[bool, str | None]] | None = None

try:
    from temper_ai.shared.utils.secrets import SecretReference, detect_secret_patterns
except ImportError:
    # Graceful fallback if secrets module not available
    pass


def get_nested_value(config: dict[str, Any], path: str, default: Any = None) -> Any:
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
    keys = path.split(".")
    value = config

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value


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


def _sanitize_dict(obj: dict[str, Any], secret_patterns: list[str]) -> dict[str, Any]:
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
        elif (
            isinstance(value, str)
            and SecretReference is not None
            and SecretReference.is_reference(value)
        ):
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


def _sanitize_value(obj: Any, secret_patterns: list[str]) -> Any:
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
    config: dict[str, Any], secret_keys: list[str] | None = None
) -> dict[str, Any]:
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

    return cast(dict[str, Any], _sanitize_value(config, secret_patterns))
