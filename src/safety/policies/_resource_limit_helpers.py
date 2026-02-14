"""Helper functions for ResourceLimitPolicy.

Extracted from ResourceLimitPolicy to keep the class below 500 lines.
These are internal implementation details and should not be used directly.
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional

import psutil

from src.constants.durations import SLEEP_VERY_SHORT
from src.constants.limits import PERCENT_20
from src.constants.probabilities import FRACTION_QUARTER
from src.constants.sizes import BYTES_PER_KB
from src.safety.constants import PERCENT_KEY
from src.safety.interfaces import SafetyViolation, ViolationSeverity

# Constants (duplicated from resource_limit_policy to avoid circular import)
BYTES_PER_KB_FLOAT = float(BYTES_PER_KB)
DISK_SPACE_SAFETY_MARGIN = 1.0 + FRACTION_QUARTER - 0.05  # 1.2  # noqa: Calculation constant
DISK_SPACE_SAFETY_MARGIN_PERCENT = PERCENT_20
CPU_SAMPLE_INTERVAL_SECONDS = SLEEP_VERY_SHORT


def format_bytes(size_bytes: int) -> str:
    """Format bytes for human readability.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string (e.g., "10.5 MB", "1.2 GB")
    """
    size: float = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < BYTES_PER_KB_FLOAT:
            return f"{size:.1f} {unit}"
        size /= BYTES_PER_KB_FLOAT
    return f"{size:.1f} PB"


def validate_size(
    name: str,
    value: Any,
    min_value: int,
    max_value: int,
    default: int
) -> int:
    """Validate size parameter (bytes).

    Args:
        name: Parameter name
        value: Value to validate
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        default: Default value

    Returns:
        Validated value

    Raises:
        ValueError: If value is invalid
    """
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"{name} must be numeric, got {type(value).__name__}"
        )

    int_value = int(value)

    if int_value < min_value:
        raise ValueError(
            f"{name} must be >= {min_value} bytes ({format_bytes(min_value)}), "
            f"got {int_value} ({format_bytes(int_value)})"
        )

    if int_value > max_value:
        raise ValueError(
            f"{name} must be <= {max_value} bytes ({format_bytes(max_value)}), "
            f"got {int_value} ({format_bytes(int_value)})"
        )

    return int_value


def validate_time(
    name: str,
    value: Any,
    min_value: float,
    max_value: float,
    default: float
) -> float:
    """Validate time parameter (seconds).

    Args:
        name: Parameter name
        value: Value to validate
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        default: Default value

    Returns:
        Validated value

    Raises:
        ValueError: If value is invalid
    """
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"{name} must be numeric, got {type(value).__name__}"
        )

    float_value = float(value)

    if float_value < min_value:
        raise ValueError(
            f"{name} must be >= {min_value} seconds, got {float_value}"
        )

    if float_value > max_value:
        raise ValueError(
            f"{name} must be <= {max_value} seconds, got {float_value}"
        )

    return float_value


def validate_bool(name: str, value: Any) -> bool:
    """Validate boolean parameter.

    Args:
        name: Parameter name
        value: Value to validate

    Returns:
        Validated value

    Raises:
        ValueError: If value is invalid
    """
    if not isinstance(value, bool):
        raise ValueError(
            f"{name} must be boolean, got {type(value).__name__}"
        )

    return value


def check_file_size(
    operation: str,
    file_path: str,
    context: Dict[str, Any],
    max_file_size_read: int,
    max_file_size_write: int,
    file_read_operations: set,
    file_write_operations: set,
    policy_name: str,
) -> Optional[SafetyViolation]:
    """Check if file size is within limits.

    Args:
        operation: Operation type
        file_path: Path to file
        context: Execution context
        max_file_size_read: Maximum file size for read operations
        max_file_size_write: Maximum file size for write operations
        file_read_operations: Set of read operation names
        file_write_operations: Set of write operation names
        policy_name: Name of the policy

    Returns:
        SafetyViolation if file too large, None otherwise
    """
    try:
        file_size = os.path.getsize(file_path)

        if operation in file_read_operations:
            max_size = max_file_size_read
            operation_name = "read"
        elif operation in file_write_operations:
            max_size = max_file_size_write
            operation_name = "write"
        else:
            return None

        if file_size > max_size:
            return SafetyViolation(
                policy_name=policy_name,
                severity=ViolationSeverity.HIGH,
                message=f"File size exceeds {operation_name} limit: {format_bytes(file_size)} > {format_bytes(max_size)}",
                action=operation,
                context=context,
                remediation_hint=f"Use smaller files or increase max_file_size_{operation_name} limit",
                metadata={
                    "file_path": file_path,
                    "file_size": file_size,
                    "max_size": max_size,
                    "operation": operation_name,
                    "exceeded_by": file_size - max_size
                }
            )

        return None

    except (OSError, IOError):
        return None


def check_disk_space(
    file_path: str,
    context: Dict[str, Any],
    track_disk: bool,
    min_free_disk_space: int,
    policy_name: str,
) -> Optional[SafetyViolation]:
    """Check if sufficient disk space is available with safety margin.

    Args:
        file_path: Path where file will be written
        context: Execution context
        track_disk: Whether disk tracking is enabled
        min_free_disk_space: Minimum free disk space required
        policy_name: Name of the policy

    Returns:
        SafetyViolation if insufficient disk space, None otherwise
    """
    if not track_disk:
        return None

    try:
        path_obj = Path(file_path).parent
        if not path_obj.exists():
            path_obj = Path("/")

        disk_usage = psutil.disk_usage(str(path_obj))
        free_space = disk_usage.free

        required_space_with_margin = int(min_free_disk_space * DISK_SPACE_SAFETY_MARGIN)

        if free_space < required_space_with_margin:
            return SafetyViolation(
                policy_name=policy_name,
                severity=ViolationSeverity.CRITICAL,
                message=f"Insufficient disk space: {format_bytes(free_space)} < {format_bytes(required_space_with_margin)} required (includes {DISK_SPACE_SAFETY_MARGIN_PERCENT}% safety margin)",
                action="file_write",
                context=context,
                remediation_hint="Free up disk space or reduce min_free_disk_space requirement",
                metadata={
                    "file_path": file_path,
                    "free_space": free_space,
                    "required_space_base": min_free_disk_space,
                    "required_space_with_margin": required_space_with_margin,
                    "safety_margin_percent": DISK_SPACE_SAFETY_MARGIN_PERCENT,
                    "total_space": disk_usage.total,
                    "used_space": disk_usage.used,
                    "disk_usage_percent": disk_usage.percent
                }
            )

        return None

    except (psutil.Error, OSError):
        return None


def check_memory_usage(
    context: Dict[str, Any],
    track_memory: bool,
    max_memory_per_operation: int,
    policy_name: str,
) -> Optional[SafetyViolation]:
    """Check current memory usage.

    Args:
        context: Execution context
        track_memory: Whether memory tracking is enabled
        max_memory_per_operation: Maximum memory per operation
        policy_name: Name of the policy

    Returns:
        SafetyViolation if memory usage too high, None otherwise
    """
    if not track_memory:
        return None

    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        current_memory = memory_info.rss

        system_memory = psutil.virtual_memory()

        if current_memory > max_memory_per_operation:
            return SafetyViolation(
                policy_name=policy_name,
                severity=ViolationSeverity.HIGH,
                message=f"Memory usage exceeds limit: {format_bytes(current_memory)} > {format_bytes(max_memory_per_operation)}",
                action="memory_check",
                context=context,
                remediation_hint="Reduce memory usage or increase max_memory_per_operation limit",
                metadata={
                    "current_memory": current_memory,
                    "max_memory": max_memory_per_operation,
                    "system_memory_total": system_memory.total,
                    "system_memory_available": system_memory.available,
                    "system_memory_percent": system_memory.percent
                }
            )

        return None

    except (psutil.Error, OSError):
        return None


def get_current_usage() -> Dict[str, Any]:
    """Get current system resource usage.

    Returns:
        Dictionary with current resource usage
    """
    usage: Dict[str, Any] = {}

    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        system_memory = psutil.virtual_memory()

        usage["memory"] = {
            "process_rss": memory_info.rss,
            "process_vms": memory_info.vms,
            "system_total": system_memory.total,
            "system_available": system_memory.available,
            "system_used": system_memory.used,
            PERCENT_KEY: system_memory.percent
        }
    except (psutil.Error, OSError):
        usage["memory"] = None

    try:
        disk_usage = psutil.disk_usage("/")
        usage["disk"] = {
            "total": disk_usage.total,
            "used": disk_usage.used,
            "free": disk_usage.free,
            PERCENT_KEY: disk_usage.percent
        }
    except (psutil.Error, OSError):
        usage["disk"] = None

    try:
        cpu_percent = psutil.cpu_percent(interval=CPU_SAMPLE_INTERVAL_SECONDS)
        usage["cpu"] = {
            PERCENT_KEY: cpu_percent,
            "count": psutil.cpu_count()
        }
    except (psutil.Error, OSError):
        usage["cpu"] = None

    return usage
