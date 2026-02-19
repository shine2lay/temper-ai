"""
Configuration management for experiment variants.

Handles deep merging of variant configuration overrides with base configurations,
validation against schemas, and security checks to prevent sensitive field overrides.
"""

import copy
from typing import Any, Dict, Optional, Set

from pydantic import ValidationError

# Protected fields that cannot be overridden by experiment variants
# for security and safety reasons
PROTECTED_CONFIG_FIELDS = {
    "api_key",
    "api_key_ref",
    "secret",
    "secret_ref",
    "password",
    "token",
    "credentials",
    "private_key",
    # Safety settings
    "safety_policy",
    "max_retries",  # Prevent infinite loops
    "timeout",  # Prevent resource exhaustion via long timeouts
}


class ExperimentConfigValidationError(Exception):
    """Raised when variant config validation fails."""
    pass


class SecurityViolationError(Exception):
    """Raised when variant config attempts to override protected fields."""
    pass


class ConfigManager:
    """
    Manages configuration merging and validation for experiment variants.

    Provides deep merge functionality to combine base configurations with
    variant-specific overrides, along with validation and security checks.

    Example:
        >>> manager = ConfigManager()
        >>> base_config = {
        ...     "agent": {"model": "gpt-4", "temperature": 0.7},
        ...     "timeout": 30
        ... }
        >>> variant_overrides = {
        ...     "agent": {"temperature": 0.9, "max_tokens": 4096}
        ... }
        >>> merged = manager.merge_config(base_config, variant_overrides)
        >>> # Result: {
        >>> #     "agent": {"model": "gpt-4", "temperature": 0.9, "max_tokens": 4096},
        >>> #     "timeout": 30
        >>> # }
    """

    def __init__(self, protected_fields: Optional[Set[str]] = None):
        """
        Initialize config manager.

        Args:
            protected_fields: Custom set of protected field names (overrides default)
        """
        self.protected_fields = protected_fields or PROTECTED_CONFIG_FIELDS

    def merge_config(
        self,
        base_config: Dict[str, Any],
        variant_overrides: Dict[str, Any],
        validate_protected: bool = True
    ) -> Dict[str, Any]:
        """
        Deep merge variant overrides into base configuration.

        Args:
            base_config: Base configuration dictionary
            variant_overrides: Variant-specific overrides
            validate_protected: Whether to check for protected field violations

        Returns:
            Merged configuration dictionary

        Raises:
            SecurityViolationError: If variant tries to override protected fields
        """
        # Security check: prevent overriding protected fields
        if validate_protected:
            self._check_protected_fields(variant_overrides)

        # Deep copy to avoid mutating original
        merged = copy.deepcopy(base_config)

        # Deep merge overrides
        self._deep_merge(merged, variant_overrides)

        return merged

    def _deep_merge(self, base: Dict[str, Any], overrides: Dict[str, Any]) -> None:
        """
        Recursively merge overrides into base dictionary.

        Modifies base dictionary in-place.

        Args:
            base: Base dictionary (modified in-place)
            overrides: Overrides to merge

        Behavior:
            - If both values are dicts: recursively merge
            - Otherwise: override base value with override value
        """
        for key, value in overrides.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                # Recursively merge nested dicts
                self._deep_merge(base[key], value)
            else:
                # Override value
                base[key] = value

    def _check_protected_fields(
        self,
        config: Dict[str, Any],
        path: str = ""
    ) -> None:
        """
        Recursively check for protected field violations.

        Args:
            config: Configuration dictionary to check
            path: Current path in config hierarchy (for error messages)

        Raises:
            SecurityViolationError: If protected field is found
        """
        for key, value in config.items():
            current_path = f"{path}.{key}" if path else key

            # Check if this field is protected
            if key in self.protected_fields:
                raise SecurityViolationError(
                    f"Variant config cannot override protected field: {current_path}"
                )

            # Recursively check nested dicts
            if isinstance(value, dict):
                self._check_protected_fields(value, current_path)

    def validate_merged_config(
        self,
        merged_config: Dict[str, Any],
        schema_class: Any
    ) -> None:
        """
        Validate merged config against Pydantic schema.

        Args:
            merged_config: Merged configuration to validate
            schema_class: Pydantic model class to validate against

        Raises:
            ExperimentConfigValidationError: If validation fails
        """
        try:
            schema_class(**merged_config)
        except ValidationError as e:
            raise ExperimentConfigValidationError(
                f"Merged config validation failed: {e}"
            ) from e

    def get_config_diff(
        self,
        base_config: Dict[str, Any],
        variant_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get diff showing what changed in variant config.

        Args:
            base_config: Base configuration
            variant_config: Merged/variant configuration

        Returns:
            Dictionary showing only changed/added keys
        """
        diff: Dict[str, Any] = {}

        for key, value in variant_config.items():
            if key not in base_config:
                # Added key
                diff[key] = {"added": value}
            elif base_config[key] != value:
                # Changed key
                if isinstance(value, dict) and isinstance(base_config[key], dict):
                    # Recursively diff nested dicts
                    nested_diff = self.get_config_diff(base_config[key], value)
                    if nested_diff:
                        diff[key] = nested_diff
                else:
                    diff[key] = {"old": base_config[key], "new": value}

        return diff

    def apply_overrides_safely(
        self,
        base_config: Dict[str, Any],
        variant_overrides: Dict[str, Any],
        schema_class: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Apply overrides with full validation and security checks.

        Convenience method combining merge, security check, and validation.

        Args:
            base_config: Base configuration
            variant_overrides: Variant overrides to apply
            schema_class: Optional Pydantic schema for validation

        Returns:
            Safely merged and validated configuration

        Raises:
            SecurityViolationError: If protected fields are overridden
            ExperimentConfigValidationError: If merged config is invalid
        """
        # Merge with security check
        merged = self.merge_config(
            base_config,
            variant_overrides,
            validate_protected=True
        )

        # Validate against schema if provided
        if schema_class:
            self.validate_merged_config(merged, schema_class)

        return merged


def extract_overrides_from_variant(
    variant_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Extract config overrides from variant dictionary.

    Handles different variant dictionary formats.

    Args:
        variant_dict: Variant dictionary (may have "config", "config_overrides", etc.)

    Returns:
        Configuration overrides dictionary
    """
    # Try common keys
    for key in ["config_overrides", "config", "overrides"]:
        if key in variant_dict:
            return variant_dict[key]  # type: ignore[no-any-return]

    # If no known key, assume entire dict is overrides
    return variant_dict


def merge_agent_config(
    base_agent_config: Dict[str, Any],
    variant_overrides: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merge variant overrides into agent configuration.

    Convenience function for agent config merging.

    Args:
        base_agent_config: Base agent configuration
        variant_overrides: Variant-specific agent overrides

    Returns:
        Merged agent configuration

    Example:
        >>> base = {
        ...     "name": "researcher",
        ...     "model": "gpt-4",
        ...     "inference": {"temperature": 0.7, "max_tokens": 2048}
        ... }
        >>> overrides = {
        ...     "inference": {"temperature": 0.9}
        ... }
        >>> merged = merge_agent_config(base, overrides)
        >>> # merged["inference"]["temperature"] == 0.9
        >>> # merged["inference"]["max_tokens"] == 2048 (preserved)
    """
    manager = ConfigManager()
    return manager.merge_config(base_agent_config, variant_overrides)


def merge_stage_config(
    base_stage_config: Dict[str, Any],
    variant_overrides: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merge variant overrides into stage configuration.

    Convenience function for stage config merging.

    Args:
        base_stage_config: Base stage configuration
        variant_overrides: Variant-specific stage overrides

    Returns:
        Merged stage configuration
    """
    manager = ConfigManager()
    return manager.merge_config(base_stage_config, variant_overrides)


def merge_workflow_config(
    base_workflow_config: Dict[str, Any],
    variant_overrides: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merge variant overrides into workflow configuration.

    Convenience function for workflow config merging.

    Args:
        base_workflow_config: Base workflow configuration
        variant_overrides: Variant-specific workflow overrides

    Returns:
        Merged workflow configuration
    """
    manager = ConfigManager()
    return manager.merge_config(base_workflow_config, variant_overrides)
