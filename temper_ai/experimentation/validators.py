"""
Input validation and security for experimentation.

This module provides security-critical validation functions for experiment
and variant names, including Unicode normalization to prevent homograph attacks.
"""

import re
import unicodedata
from typing import Any, Dict, List

from temper_ai.shared.utils.logging import get_logger

logger = get_logger(__name__)

# Validation length limits
MAX_EXPERIMENT_NAME_LENGTH = 50
MAX_VARIANT_NAME_LENGTH = 30
MAX_NAME_DISPLAY_LENGTH = 30  # Maximum characters to display in security logs


def validate_experiment_name(name: str) -> str:
    """
    Validate and sanitize experiment name.

    Security requirements:
    - Alphanumeric, underscore, hyphen only
    - 1-50 characters
    - No Unicode tricks (homograph attacks)
    - Normalized form (NFKC)

    Args:
        name: Raw experiment name

    Returns:
        Validated and normalized name

    Raises:
        ValueError: If name violates security policy

    Example:
        >>> validate_experiment_name("test_experiment_v2")
        'test_experiment_v2'
        >>> validate_experiment_name("test'; DROP TABLE--")
        Traceback (most recent call last):
        ValueError: Experiment name must contain only alphanumeric...
    """
    # 1. Length check (before expensive operations)
    # Strip whitespace for length validation to catch " " as empty
    if not name or not name.strip() or len(name) > MAX_EXPERIMENT_NAME_LENGTH:
        raise ValueError(f"Experiment name must be 1-{MAX_EXPERIMENT_NAME_LENGTH} characters")

    # 2. Normalize Unicode (prevent homograph attacks)
    # NFKC = Compatibility Decomposition + Canonical Composition
    normalized = unicodedata.normalize('NFKC', name)

    # 3. Character set validation
    if not re.match(r'^[a-zA-Z0-9_-]+$', normalized):
        raise ValueError(
            "Experiment name must contain only alphanumeric characters, "
            "underscores, and hyphens (a-zA-Z0-9_-)"
        )

    # 4. Must start with letter (prevent issues with tooling)
    if not normalized[0].isalpha():
        raise ValueError("Experiment name must start with a letter")

    # 5. No consecutive special characters (aesthetic + prevents parsing issues)
    if re.search(r'[-_]{2,}', normalized):
        raise ValueError("Experiment name cannot contain consecutive hyphens or underscores")

    return normalized


def validate_variant_name(name: str) -> str:
    """
    Validate variant name (same rules as experiment name but shorter).

    Args:
        name: Raw variant name

    Returns:
        Validated and normalized name

    Raises:
        ValueError: If name violates security policy
    """
    if not name or len(name) > MAX_VARIANT_NAME_LENGTH:
        raise ValueError(f"Variant name must be 1-{MAX_VARIANT_NAME_LENGTH} characters")

    normalized = unicodedata.normalize('NFKC', name)

    if not re.match(r'^[a-zA-Z0-9_-]+$', normalized):
        raise ValueError(
            "Variant name must contain only alphanumeric characters, "
            "underscores, and hyphens"
        )

    return normalized


def validate_variant_list(
    variants: List[Dict[str, Any]],
    experiment_name: str
) -> List[Dict[str, Any]]:
    """
    Validate all variant names in a list atomically.

    This ensures we don't partially mutate the variants list on error.

    Args:
        variants: List of variant configurations
        experiment_name: Name of parent experiment (for logging)

    Returns:
        List of variant configurations with validated names

    Raises:
        ValueError: If any variant name is invalid
    """
    validated_variants = []
    for variant_config in variants:
        try:
            validated_name = validate_variant_name(variant_config["name"])
            validated_variants.append({**variant_config, "name": validated_name})
        except ValueError as e:
            logger.warning(
                f"Invalid variant name rejected: {variant_config.get('name', '')[:MAX_NAME_DISPLAY_LENGTH]}",
                extra={
                    "security_event": "INPUT_VALIDATION_FAILED",
                    "variant_name": variant_config.get("name", "")[:MAX_NAME_DISPLAY_LENGTH],
                    "experiment_name": experiment_name,
                    "error": str(e)
                }
            )
            raise

    return validated_variants


__all__ = [
    "validate_experiment_name",
    "validate_variant_name",
    "validate_variant_list",
]
