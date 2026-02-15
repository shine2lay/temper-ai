"""
Path safety validation utilities.

Public API for path safety validation.
"""
from pathlib import Path
from typing import Any, Union

from src.shared.utils.path_safety.exceptions import PathSafetyError
from src.shared.utils.path_safety.validator import PathSafetyValidator

# Global validator instance (uses cwd as root)
_default_validator = PathSafetyValidator()


def validate_path(path: Union[str, Path], **kwargs: Any) -> Path:
    """
    Validate a path using the default validator.

    Args:
        path: Path to validate
        **kwargs: Additional arguments passed to validator

    Returns:
        Resolved absolute path

    Raises:
        PathSafetyError: If validation fails
    """
    return _default_validator.validate_path(path, **kwargs)


def validate_read(path: Path) -> Path:
    """
    Validate a path for reading using the default validator.

    Args:
        path: Path to validate

    Returns:
        Resolved absolute path
    """
    return _default_validator.validate_read(path)


def validate_write(path: Path, allow_overwrite: bool = True, allow_create_parents: bool = False) -> Path:
    """
    Validate a path for writing using the default validator.

    Args:
        path: Path to validate
        allow_overwrite: If False, reject existing files
        allow_create_parents: If False, reject paths with non-existent parent directories

    Returns:
        Resolved absolute path
    """
    return _default_validator.validate_write(path, allow_overwrite, allow_create_parents)


__all__ = [
    "PathSafetyError",
    "PathSafetyValidator",
    "validate_path",
    "validate_read",
    "validate_write",
]
