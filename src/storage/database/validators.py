"""Database field validators for data integrity and safety."""
import json
import logging
from typing import Any, Dict

from src.shared.constants.sizes import BYTES_PER_MB

logger = logging.getLogger(__name__)


class JSONSizeError(ValueError):
    """Raised when JSON blob exceeds maximum allowed size."""
    pass


def validate_json_size(
    data: Dict[str, Any],
    max_bytes: int = BYTES_PER_MB,
    field_name: str = "JSON field"
) -> None:
    """
    Validate that JSON-serializable data doesn't exceed size limit.

    Args:
        data: Dictionary to validate
        max_bytes: Maximum size in bytes (default: 1MB)
        field_name: Name of field for error messages

    Raises:
        JSONSizeError: If serialized size exceeds max_bytes
        TypeError: If data is not JSON-serializable

    Example:
        >>> validate_json_size({"key": "value"}, max_bytes=BYTES_PER_MB)
        >>> validate_json_size(huge_dict, max_bytes=BYTES_PER_MB // 2, field_name="workflow_config_snapshot")
        JSONSizeError: workflow_config_snapshot too large: 0.75MB exceeds 0.50MB limit
    """
    try:
        serialized = json.dumps(data, separators=(',', ':'))
        size_bytes = len(serialized.encode('utf-8'))
        size_mb = size_bytes / BYTES_PER_MB
        max_mb = max_bytes / BYTES_PER_MB

        if size_bytes > max_bytes:
            raise JSONSizeError(
                f"{field_name} too large: {size_mb:.2f}MB exceeds {max_mb:.2f}MB limit"
            )

        logger.debug(
            f"JSON size validation passed for {field_name}: {size_mb:.2f}MB"
        )

    except (TypeError, ValueError) as e:
        raise TypeError(
            f"Failed to serialize {field_name} to JSON: {e}"
        ) from e


def validate_optional_json_size(
    data: Dict[str, Any] | None,
    max_bytes: int = BYTES_PER_MB,
    field_name: str = "JSON field"
) -> None:
    """Validate optional JSON field size (allows None)."""
    if data is not None:
        validate_json_size(data, max_bytes, field_name)
