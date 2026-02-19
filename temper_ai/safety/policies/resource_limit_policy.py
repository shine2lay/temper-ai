"""Resource Consumption Limits Policy.

Enforces resource consumption limits to prevent:
- Excessive file sizes that could fill disk or cause memory issues
- Memory exhaustion from loading large files
- CPU-intensive operations that could hang the system
- Disk space exhaustion

Default Limits (per operation):
- Max file size: 100MB for reads, 10MB for writes
- Max memory per operation: 500MB
- Max CPU time per operation: 30 seconds
- Min free disk space: 1GB

This policy integrates with system resource monitoring to track:
- File sizes before read/write operations
- Memory usage during operations
- CPU time consumed by operations
- Available disk space
"""
import os
import time
from typing import Any, Dict, List, Optional

import psutil

from temper_ai.shared.constants.durations import SECONDS_PER_HOUR, SLEEP_VERY_SHORT, TIMEOUT_MEDIUM
from temper_ai.shared.constants.limits import (
    DEFAULT_MAX_WORKERS,
    MAX_WORKERS,
    MIN_POSITIVE_VALUE,
    MIN_WORKERS,
    MULTIPLIER_LARGE,
    MULTIPLIER_MEDIUM,
    PERCENT_20,
    PERCENT_80,
)
from temper_ai.shared.constants.probabilities import FRACTION_QUARTER, PROB_MINIMAL
from temper_ai.shared.constants.sizes import (
    BYTES_PER_GB,
    BYTES_PER_KB,
    BYTES_PER_MB,
    BYTES_PER_TB,
    SIZE_1GB,
    SIZE_10MB,
    SIZE_100MB,
)
from temper_ai.safety.base import BaseSafetyPolicy
from temper_ai.safety.interfaces import SafetyViolation, ValidationResult
from temper_ai.safety.policies._resource_limit_helpers import (
    FileSizeCheckParams,
    check_disk_space,
    check_file_size,
    check_memory_usage,
    format_bytes,
    validate_bool,
    validate_size,
    validate_time,
)
from temper_ai.safety.policies._resource_limit_helpers import (
    get_current_usage as _get_current_usage_helper,
)

# File size validation limits
MIN_FILE_SIZE = MIN_WORKERS  # Minimum file size in bytes (prevents negative/zero)
MAX_FILE_SIZE_READ = 10 * BYTES_PER_GB  # 10GB maximum for read operations
MAX_FILE_SIZE_WRITE = SIZE_1GB  # 1GB maximum for write operations

# Memory validation limits
MIN_MEMORY_SIZE = MIN_WORKERS  # Minimum memory size in bytes (prevents negative/zero)
MAX_MEMORY_SIZE = 8 * BYTES_PER_GB  # 8GB maximum memory per operation  # noqa: Multiplier in constant expression

# Disk space limits
MIN_FREE_DISK_SPACE = SIZE_1GB  # 1GB minimum free disk space required
MAX_FREE_DISK_SPACE = BYTES_PER_TB  # 1TB maximum disk space limit

# Worker process limits
MIN_WORKER_PROCESSES = MIN_WORKERS  # Minimum number of worker processes
MAX_WORKER_PROCESSES = MAX_WORKERS  # Maximum number of worker processes

# CPU time limits
MIN_CPU_TIME = MIN_POSITIVE_VALUE  # 1ms minimum (prevents zero/negative, allows testing)
MAX_CPU_TIME = float(SECONDS_PER_HOUR)  # 1 hour maximum CPU time

# Disk space safety margin
DISK_SPACE_SAFETY_MARGIN = 1.0 + FRACTION_QUARTER - PROB_MINIMAL  # 1.2 = 20% safety margin to prevent TOCTOU race conditions
DISK_SPACE_SAFETY_MARGIN_PERCENT = PERCENT_20  # 20% safety margin percentage for metadata

# HTTP connection pool limits (8 CPU cores, 5 workers per core = 8 * 5 = 40 connections)
DEFAULT_MAX_HTTP_CONNECTIONS = DEFAULT_MAX_WORKERS
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = PERCENT_20
MULTIPLIER_CPU_CORES = MULTIPLIER_MEDIUM - 2  # 8 CPU cores
WORKERS_PER_CPU_CORE = MULTIPLIER_MEDIUM // 2  # 5 workers per core
DEFAULT_KEEPALIVE_EXPIRY_SECONDS = float(TIMEOUT_MEDIUM)

# Byte size formatting (converted to float for division operations)
BYTES_PER_KB_FLOAT = float(BYTES_PER_KB)
BYTES_PER_MB_FLOAT = float(BYTES_PER_MB)
BYTES_PER_GB_FLOAT = float(BYTES_PER_GB)
BYTES_PER_TB_FLOAT = float(BYTES_PER_TB)

# CPU sampling
CPU_SAMPLE_INTERVAL_SECONDS = SLEEP_VERY_SHORT  # Interval for CPU usage sampling


class ResourceLimitPolicy(BaseSafetyPolicy):
    """Resource consumption limit enforcement policy.

    Configuration options:
        max_file_size_read: Maximum file size for read operations (bytes)
        max_file_size_write: Maximum file size for write operations (bytes)
        max_memory_per_operation: Maximum memory per operation (bytes)
        max_cpu_time: Maximum CPU time per operation (seconds)
        min_free_disk_space: Minimum free disk space required (bytes)
        track_memory: Enable memory tracking (default: True)
        track_cpu: Enable CPU time tracking (default: True)
        track_disk: Enable disk space tracking (default: True)

    Example:
        >>> config = {
        ...     "max_file_size_read": 100 * 1024 * 1024,  # 100MB
        ...     "max_file_size_write": 10 * 1024 * 1024,  # 10MB
        ...     "max_memory_per_operation": 500 * 1024 * 1024,  # 500MB
        ...     "max_cpu_time": 30.0,  # 30 seconds
        ...     "min_free_disk_space": 1024 * 1024 * 1024  # 1GB
        ... }
        >>> policy = ResourceLimitPolicy(config)
        >>> result = policy.validate(
        ...     action={"operation": "file_read", "path": "/data/large.csv"},
        ...     context={"agent_id": "agent-123"}
        ... )
    """

    # Default limits (conservative defaults for safety)
    DEFAULT_MAX_FILE_SIZE_READ = SIZE_100MB  # 100MB
    DEFAULT_MAX_FILE_SIZE_WRITE = SIZE_10MB  # 10MB
    DEFAULT_MAX_MEMORY_PER_OPERATION = (MULTIPLIER_LARGE * 5) * BYTES_PER_MB  # 500MB  # noqa: Multiplier
    DEFAULT_MAX_CPU_TIME = float(TIMEOUT_MEDIUM)  # 30 seconds
    DEFAULT_MIN_FREE_DISK_SPACE = SIZE_1GB  # 1GB

    # Map action types to resource checks
    FILE_READ_OPERATIONS = {
        "file_read", "read", "read_file", "load", "open"
    }

    FILE_WRITE_OPERATIONS = {
        "file_write", "write", "write_file", "save", "create"
    }

    # Instance attributes set dynamically in __init__ via setattr
    max_file_size_read: int
    max_file_size_write: int
    max_memory_per_operation: int
    min_free_disk_space: int
    track_memory: bool
    track_cpu: bool
    track_disk: bool

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize resource limit policy.

        Args:
            config: Policy configuration (optional)

        Raises:
            ValueError: If configuration values are invalid
        """
        super().__init__(config or {})

        # Size limits (validated using helper)
        size_configs = [
            ("max_file_size_read", MIN_FILE_SIZE, MAX_FILE_SIZE_READ, self.DEFAULT_MAX_FILE_SIZE_READ),
            ("max_file_size_write", MIN_FILE_SIZE, MAX_FILE_SIZE_WRITE, self.DEFAULT_MAX_FILE_SIZE_WRITE),
            ("max_memory_per_operation", MIN_MEMORY_SIZE, MAX_MEMORY_SIZE, self.DEFAULT_MAX_MEMORY_PER_OPERATION),
            ("min_free_disk_space", MIN_MEMORY_SIZE, MAX_FREE_DISK_SPACE, self.DEFAULT_MIN_FREE_DISK_SPACE),
        ]

        for name, min_val, max_val, default in size_configs:
            setattr(
                self, name,
                validate_size(name, self.config.get(name, default), min_val, max_val, default)
            )

        # Time limits
        self.max_cpu_time = validate_time(
            "max_cpu_time",
            self.config.get("max_cpu_time", self.DEFAULT_MAX_CPU_TIME),
            min_value=MIN_CPU_TIME,
            max_value=MAX_CPU_TIME,
            default=self.DEFAULT_MAX_CPU_TIME
        )

        # Tracking flags (validated using helper)
        tracking_flags = ["track_memory", "track_cpu", "track_disk"]
        for flag_name in tracking_flags:
            setattr(
                self, flag_name,
                validate_bool(flag_name, self.config.get(flag_name, True))
            )

        # Operation tracking for memory/CPU monitoring
        self._operation_start_times: Dict[str, float] = {}
        self._operation_start_memory: Dict[str, int] = {}

    @property
    def name(self) -> str:
        """Return policy name."""
        return "resource_limit"

    @property
    def version(self) -> str:
        """Return policy version."""
        return "1.0.0"

    @property
    def priority(self) -> int:
        """Return policy priority.

        Resource limiting has high priority to prevent system exhaustion.
        """
        return PERCENT_80

    def _check_file_violations(
        self,
        operation: str,
        file_path: str,
        context: Dict[str, Any],
    ) -> List[SafetyViolation]:
        """Check file size and disk space violations for file operations."""
        violations: List[SafetyViolation] = []
        if os.path.exists(file_path):
            params = FileSizeCheckParams(
                operation=operation,
                file_path=file_path,
                context=context,
                max_file_size_read=self.max_file_size_read,
                max_file_size_write=self.max_file_size_write,
                file_read_operations=self.FILE_READ_OPERATIONS,
                file_write_operations=self.FILE_WRITE_OPERATIONS,
                policy_name=self.name
            )
            file_violation = check_file_size(params=params)
            if file_violation:
                violations.append(file_violation)

        if operation in self.FILE_WRITE_OPERATIONS:
            disk_violation = check_disk_space(
                file_path, context, self.track_disk,
                self.min_free_disk_space, self.name,
            )
            if disk_violation:
                violations.append(disk_violation)

        return violations

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against resource limits.

        Args:
            action: Action to validate, should contain:
                - operation: Type of operation
                - path: File path (for file operations)
                - size: Expected size (optional, for validation)
            context: Execution context

        Returns:
            ValidationResult with violations if limits exceeded
        """
        violations: List[SafetyViolation] = []
        operation = action.get("operation") or action.get("type", "unknown")
        file_path = action.get("path") or action.get("file_path")

        if file_path:
            violations.extend(self._check_file_violations(operation, file_path, context))

        if self.track_memory:
            memory_violation = check_memory_usage(
                context, self.track_memory,
                self.max_memory_per_operation, self.name,
            )
            if memory_violation:
                violations.append(memory_violation)

        valid = len(violations) == 0

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata={
                "operation": operation,
                "file_path": file_path,
                "limits_checked": {
                    "file_size": file_path is not None,
                    "disk_space": operation in self.FILE_WRITE_OPERATIONS and file_path is not None,
                    "memory": self.track_memory
                }
            },
            policy_name=self.name
        )

    def start_operation(self, operation_id: str) -> None:
        """Mark the start of an operation for CPU/memory tracking."""
        if self.track_cpu:
            self._operation_start_times[operation_id] = time.time()

        if self.track_memory:
            try:
                process = psutil.Process()
                self._operation_start_memory[operation_id] = process.memory_info().rss
            except (psutil.Error, OSError):
                pass

    def end_operation(self, operation_id: str) -> Dict[str, Any]:
        """Mark the end of an operation and check resource usage."""
        stats: Dict[str, Any] = {
            "operation_id": operation_id,
            "cpu_time": None,
            "memory_delta": None,
            "cpu_exceeded": False,
            "memory_exceeded": False
        }

        # Calculate CPU time
        if operation_id in self._operation_start_times:
            start_time = self._operation_start_times.pop(operation_id)
            cpu_time = time.time() - start_time
            stats["cpu_time"] = cpu_time
            stats["cpu_exceeded"] = cpu_time > self.max_cpu_time

        # Calculate memory delta
        if operation_id in self._operation_start_memory:
            start_memory = self._operation_start_memory.pop(operation_id)
            try:
                process = psutil.Process()
                current_memory = process.memory_info().rss
                memory_delta = current_memory - start_memory
                stats["memory_delta"] = memory_delta
                stats["memory_exceeded"] = memory_delta > self.max_memory_per_operation
            except (psutil.Error, OSError):
                pass

        return stats

    def get_current_usage(self) -> Dict[str, Any]:
        """Get current system resource usage."""
        return _get_current_usage_helper()

    def _format_bytes(self, size_bytes: int) -> str:
        """Format bytes for human readability."""
        return format_bytes(size_bytes)
