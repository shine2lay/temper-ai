"""Helper functions extracted from SecretDetectionPolicy to reduce class size."""

from typing import Any

from temper_ai.safety.constants import (
    MAX_EXCLUDED_PATH_LENGTH,
    MAX_EXCLUDED_PATHS,
)


def validate_enabled_patterns(
    config: dict[str, Any],
    valid_patterns: dict[str, Any],
) -> list[str]:
    """Validate and return enabled pattern names from config.

    Args:
        config: Policy configuration dict.
        valid_patterns: Full dict of known SECRET_PATTERNS.

    Returns:
        List of validated enabled pattern names.

    Raises:
        ValueError: If any pattern name is invalid or list is empty.
    """
    enabled_patterns_raw = config.get("enabled_patterns", list(valid_patterns.keys()))
    if not isinstance(enabled_patterns_raw, list):
        if isinstance(enabled_patterns_raw, str):
            enabled_patterns_raw = [enabled_patterns_raw]
        else:
            raise ValueError(
                f"enabled_patterns must be a list of strings, got {type(enabled_patterns_raw).__name__}"
            )

    valid_names = set(valid_patterns.keys())
    enabled_patterns: list[str] = []
    for pattern in enabled_patterns_raw:
        if not isinstance(pattern, str):
            raise ValueError(
                f"enabled_patterns items must be strings, got {type(pattern).__name__}"
            )
        if pattern not in valid_names:
            raise ValueError(
                f"Unknown pattern '{pattern}'. Valid patterns: {', '.join(sorted(valid_names))}"
            )
        enabled_patterns.append(pattern)

    if not enabled_patterns:
        raise ValueError(
            "enabled_patterns cannot be empty. At least one pattern must be enabled."
        )

    return enabled_patterns


def validate_excluded_paths(config: dict[str, Any]) -> list[str]:
    """Validate and return excluded paths from config.

    Args:
        config: Policy configuration dict.

    Returns:
        List of validated excluded path strings.

    Raises:
        ValueError: If paths are invalid or exceed limits.
    """
    excluded_paths_raw = config.get("excluded_paths", [])
    if not isinstance(excluded_paths_raw, list):
        raise ValueError(
            f"excluded_paths must be a list of strings, got {type(excluded_paths_raw).__name__}"
        )

    excluded_paths: list[str] = []
    for path in excluded_paths_raw:
        if not isinstance(path, str):
            raise ValueError(
                f"excluded_paths items must be strings, got {type(path).__name__}"
            )
        if len(path) > MAX_EXCLUDED_PATH_LENGTH:
            raise ValueError(
                f"excluded_paths items must be <= {MAX_EXCLUDED_PATH_LENGTH} characters, got {len(path)}"
            )
        excluded_paths.append(path)

    if len(excluded_paths) > MAX_EXCLUDED_PATHS:
        raise ValueError(
            f"excluded_paths must have <= {MAX_EXCLUDED_PATHS} items, got {len(excluded_paths)}"
        )

    return excluded_paths
