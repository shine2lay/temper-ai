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
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil  # type: ignore[import-untyped]

from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import SafetyViolation, ValidationResult, ViolationSeverity


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
    DEFAULT_MAX_FILE_SIZE_READ = 100 * 1024 * 1024  # 100MB
    DEFAULT_MAX_FILE_SIZE_WRITE = 10 * 1024 * 1024  # 10MB
    DEFAULT_MAX_MEMORY_PER_OPERATION = 500 * 1024 * 1024  # 500MB
    DEFAULT_MAX_CPU_TIME = 30.0  # 30 seconds
    DEFAULT_MIN_FREE_DISK_SPACE = 1024 * 1024 * 1024  # 1GB

    # Map action types to resource checks
    FILE_READ_OPERATIONS = {
        "file_read", "read", "read_file", "load", "open"
    }

    FILE_WRITE_OPERATIONS = {
        "file_write", "write", "write_file", "save", "create"
    }

    def _validate_size(
        self,
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

        value = int(value)

        if value < min_value:
            raise ValueError(
                f"{name} must be >= {min_value} bytes ({self._format_bytes(min_value)}), "
                f"got {value} ({self._format_bytes(value)})"
            )

        if value > max_value:
            raise ValueError(
                f"{name} must be <= {max_value} bytes ({self._format_bytes(max_value)}), "
                f"got {value} ({self._format_bytes(value)})"
            )

        return value

    def _validate_time(
        self,
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

        value = float(value)

        if value < min_value:
            raise ValueError(
                f"{name} must be >= {min_value} seconds, got {value}"
            )

        if value > max_value:
            raise ValueError(
                f"{name} must be <= {max_value} seconds, got {value}"
            )

        return value

    def _validate_bool(
        self,
        name: str,
        value: Any
    ) -> bool:
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

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize resource limit policy.

        Args:
            config: Policy configuration (optional)

        Raises:
            ValueError: If configuration values are invalid
        """
        super().__init__(config or {})

        # Validate and set file size limits
        self.max_file_size_read = self._validate_size(
            "max_file_size_read",
            self.config.get("max_file_size_read", self.DEFAULT_MAX_FILE_SIZE_READ),
            min_value=1,  # 1 byte minimum (prevents negative/zero)
            max_value=10 * 1024**3,  # 10GB maximum (safety limit)
            default=self.DEFAULT_MAX_FILE_SIZE_READ
        )

        self.max_file_size_write = self._validate_size(
            "max_file_size_write",
            self.config.get("max_file_size_write", self.DEFAULT_MAX_FILE_SIZE_WRITE),
            min_value=1,  # 1 byte minimum (prevents negative/zero)
            max_value=1024**3,  # 1GB maximum (safety limit)
            default=self.DEFAULT_MAX_FILE_SIZE_WRITE
        )

        self.max_memory_per_operation = self._validate_size(
            "max_memory_per_operation",
            self.config.get("max_memory_per_operation", self.DEFAULT_MAX_MEMORY_PER_OPERATION),
            min_value=1,  # 1 byte minimum (prevents negative/zero, allows testing)
            max_value=8 * 1024**3,  # 8GB maximum (safety limit)
            default=self.DEFAULT_MAX_MEMORY_PER_OPERATION
        )

        # Validate CPU time
        self.max_cpu_time = self._validate_time(
            "max_cpu_time",
            self.config.get("max_cpu_time", self.DEFAULT_MAX_CPU_TIME),
            min_value=0.001,  # 1ms minimum (prevents zero/negative, allows testing)
            max_value=3600.0,  # 1 hour maximum
            default=self.DEFAULT_MAX_CPU_TIME
        )

        # Validate disk space
        self.min_free_disk_space = self._validate_size(
            "min_free_disk_space",
            self.config.get("min_free_disk_space", self.DEFAULT_MIN_FREE_DISK_SPACE),
            min_value=1,  # 1 byte minimum (prevents negative/zero, allows testing)
            max_value=1024**4,  # 1TB maximum
            default=self.DEFAULT_MIN_FREE_DISK_SPACE
        )

        # Validate tracking flags
        self.track_memory = self._validate_bool(
            "track_memory",
            self.config.get("track_memory", True)
        )
        self.track_cpu = self._validate_bool(
            "track_cpu",
            self.config.get("track_cpu", True)
        )
        self.track_disk = self._validate_bool(
            "track_disk",
            self.config.get("track_disk", True)
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
        return 80

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

        # Extract operation details
        operation = action.get("operation") or action.get("type", "unknown")
        file_path = action.get("path") or action.get("file_path")

        # Check file size limits
        if file_path and os.path.exists(file_path):
            file_violation = self._check_file_size(operation, file_path, context)
            if file_violation:
                violations.append(file_violation)

        # Check disk space for write operations
        if operation in self.FILE_WRITE_OPERATIONS and file_path:
            disk_violation = self._check_disk_space(file_path, context)
            if disk_violation:
                violations.append(disk_violation)

        # Check current memory usage
        if self.track_memory:
            memory_violation = self._check_memory_usage(context)
            if memory_violation:
                violations.append(memory_violation)

        # Determine validity
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

    def _check_file_size(
        self,
        operation: str,
        file_path: str,
        context: Dict[str, Any]
    ) -> Optional[SafetyViolation]:
        """Check if file size is within limits.

        Args:
            operation: Operation type
            file_path: Path to file
            context: Execution context

        Returns:
            SafetyViolation if file too large, None otherwise
        """
        try:
            file_size = os.path.getsize(file_path)

            # Determine limit based on operation type
            if operation in self.FILE_READ_OPERATIONS:
                max_size = self.max_file_size_read
                operation_name = "read"
            elif operation in self.FILE_WRITE_OPERATIONS:
                max_size = self.max_file_size_write
                operation_name = "write"
            else:
                # Unknown operation, skip check
                return None

            # Check against limit
            if file_size > max_size:
                return SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.HIGH,
                    message=f"File size exceeds {operation_name} limit: {self._format_bytes(file_size)} > {self._format_bytes(max_size)}",
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
            # File doesn't exist or can't be accessed - not a resource limit issue
            return None

    def _check_disk_space(
        self,
        file_path: str,
        context: Dict[str, Any]
    ) -> Optional[SafetyViolation]:
        """Check if sufficient disk space is available with safety margin.

        Includes 20% safety margin to prevent TOCTOU race conditions where
        disk space is consumed between check and write operations.

        Args:
            file_path: Path where file will be written
            context: Execution context

        Returns:
            SafetyViolation if insufficient disk space, None otherwise
        """
        if not self.track_disk:
            return None

        try:
            # Get disk usage for the target path
            path_obj = Path(file_path).parent
            if not path_obj.exists():
                # Use root directory if path doesn't exist yet
                path_obj = Path("/")

            disk_usage = psutil.disk_usage(str(path_obj))
            free_space = disk_usage.free

            # Apply 20% safety margin to prevent TOCTOU race conditions
            # This accounts for:
            # - Other processes writing to disk between check and write
            # - File system metadata overhead
            # - Buffer space needed for atomic writes
            safety_margin = 1.2
            required_space_with_margin = int(self.min_free_disk_space * safety_margin)

            if free_space < required_space_with_margin:
                return SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Insufficient disk space: {self._format_bytes(free_space)} < {self._format_bytes(required_space_with_margin)} required (includes 20% safety margin)",
                    action="file_write",
                    context=context,
                    remediation_hint="Free up disk space or reduce min_free_disk_space requirement",
                    metadata={
                        "file_path": file_path,
                        "free_space": free_space,
                        "required_space_base": self.min_free_disk_space,
                        "required_space_with_margin": required_space_with_margin,
                        "safety_margin_percent": 20,
                        "total_space": disk_usage.total,
                        "used_space": disk_usage.used,
                        "disk_usage_percent": disk_usage.percent
                    }
                )

            return None

        except Exception:
            # Error checking disk space - don't block operation
            return None

    def _check_memory_usage(
        self,
        context: Dict[str, Any]
    ) -> Optional[SafetyViolation]:
        """Check current memory usage.

        Args:
            context: Execution context

        Returns:
            SafetyViolation if memory usage too high, None otherwise
        """
        if not self.track_memory:
            return None

        try:
            # Get current process memory usage
            process = psutil.Process()
            memory_info = process.memory_info()
            current_memory = memory_info.rss  # Resident Set Size

            # Get system memory
            system_memory = psutil.virtual_memory()

            # Check if current memory is approaching limit
            # We check process memory, not per-operation
            if current_memory > self.max_memory_per_operation:
                return SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.HIGH,
                    message=f"Memory usage exceeds limit: {self._format_bytes(current_memory)} > {self._format_bytes(self.max_memory_per_operation)}",
                    action="memory_check",
                    context=context,
                    remediation_hint="Reduce memory usage or increase max_memory_per_operation limit",
                    metadata={
                        "current_memory": current_memory,
                        "max_memory": self.max_memory_per_operation,
                        "system_memory_total": system_memory.total,
                        "system_memory_available": system_memory.available,
                        "system_memory_percent": system_memory.percent
                    }
                )

            return None

        except Exception:
            # Error checking memory - don't block operation
            return None

    def start_operation(self, operation_id: str) -> None:
        """Mark the start of an operation for CPU/memory tracking.

        Args:
            operation_id: Unique identifier for the operation

        Example:
            >>> policy = ResourceLimitPolicy()
            >>> policy.start_operation("task-123")
            >>> # ... perform operation ...
            >>> policy.end_operation("task-123")
        """
        if self.track_cpu:
            self._operation_start_times[operation_id] = time.time()

        if self.track_memory:
            try:
                process = psutil.Process()
                self._operation_start_memory[operation_id] = process.memory_info().rss
            except Exception:
                pass

    def end_operation(
        self,
        operation_id: str
    ) -> Dict[str, Any]:
        """Mark the end of an operation and check resource usage.

        Args:
            operation_id: Unique identifier for the operation

        Returns:
            Dictionary with operation resource usage stats

        Example:
            >>> policy = ResourceLimitPolicy()
            >>> policy.start_operation("task-123")
            >>> # ... perform operation ...
            >>> stats = policy.end_operation("task-123")
            >>> print(f"CPU time: {stats['cpu_time']}s")
        """
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
            except Exception:
                pass

        return stats

    def get_current_usage(self) -> Dict[str, Any]:
        """Get current system resource usage.

        Returns:
            Dictionary with current resource usage

        Example:
            >>> policy = ResourceLimitPolicy()
            >>> usage = policy.get_current_usage()
            >>> print(f"Memory: {usage['memory']['percent']}%")
            >>> print(f"Disk: {usage['disk']['percent']}%")
        """
        usage: Dict[str, Any] = {}

        # Memory usage
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
                "percent": system_memory.percent
            }
        except Exception:
            usage["memory"] = None

        # Disk usage
        try:
            disk_usage = psutil.disk_usage("/")
            usage["disk"] = {
                "total": disk_usage.total,
                "used": disk_usage.used,
                "free": disk_usage.free,
                "percent": disk_usage.percent
            }
        except Exception:
            usage["disk"] = None

        # CPU usage (requires time to sample)
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            usage["cpu"] = {
                "percent": cpu_percent,
                "count": psutil.cpu_count()
            }
        except Exception:
            usage["cpu"] = None

        return usage

    def _format_bytes(self, size_bytes: int) -> str:
        """Format bytes for human readability.

        Args:
            size_bytes: Size in bytes

        Returns:
            Formatted string (e.g., "10.5 MB", "1.2 GB")
        """
        size: float = float(size_bytes)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"
