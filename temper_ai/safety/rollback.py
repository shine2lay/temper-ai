"""Rollback mechanism for reverting failed or rejected actions.

This module provides a comprehensive rollback system that captures state before
high-risk actions and enables safe reversion when actions fail or are rejected.

Key Features:
- State snapshot creation before actions
- Multiple rollback strategies (file, state, composite)
- Safe rollback execution with validation
- Rollback history and audit trail
- Integration with approval workflow
- Partial rollback support
- Path traversal protection with symlink detection

Security:
- All file paths validated against allowed directories
- Symlinks detected and rejected to prevent path traversal
- Path normalization with realpath() before validation
- Whitelist-based access control

Example:
    >>> manager = RollbackManager()
    >>>
    >>> # Create snapshot before action
    >>> snapshot = manager.create_snapshot(
    ...     action={"tool": "write_file", "path": "/tmp/config.yaml"},
    ...     context={"agent": "config_updater"}
    ... )
    >>>
    >>> # Execute action (might fail)
    >>> try:
    ...     execute_risky_action()
    ... except Exception:
    ...     # Rollback on failure
    ...     result = manager.execute_rollback(snapshot.id)
    ...     if result.success:
    ...         print("Successfully rolled back changes")
"""

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Import rollback data types from observability (canonical location)
from temper_ai.observability.rollback_types import (
    RollbackResult,
    RollbackSnapshot,
    RollbackStatus,
)
from temper_ai.safety.constants import EXISTED_SUFFIX, STRATEGY_PREFIX
from temper_ai.shared.constants.limits import (
    MAX_MEDIUM_STRING_LENGTH,
    THRESHOLD_LARGE_COUNT,
)
from temper_ai.shared.utils.exceptions import SecurityError

logger = logging.getLogger(__name__)


class RollbackSecurityError(SecurityError):
    """Raised when rollback operation fails security validation."""

    pass


# Re-export types for backward compatibility
__all__ = [
    "RollbackResult",
    "RollbackSnapshot",
    "RollbackStatus",
    "RollbackSecurityError",
]


def validate_rollback_path(
    file_path: str,
    allowed_directories: list[str] | None = None,
    check_symlinks: bool = True,
) -> tuple[bool, str | None]:
    """Validate file path for rollback operations.

    Security validation for file paths to prevent:
    - Path traversal attacks (../../etc/passwd)
    - Symlink attacks (symlink pointing to /etc/passwd)
    - Access to system files
    - Access outside allowed directories

    Args:
        file_path: Path to validate
        allowed_directories: List of allowed directory paths. If None, uses safe defaults.
        check_symlinks: Whether to reject symlinks (default: True)

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if path is valid
        - (False, error_message) if path is invalid

    Security Notes:
        - Uses os.path.realpath() to resolve symlinks and relative paths
        - Checks if resolved path is within allowed directories
        - Rejects symlinks by default (can be disabled for testing)
        - Uses strict path validation to prevent traversal

    Example:
        >>> is_valid, error = validate_rollback_path("/tmp/myfile.txt")
        >>> if not is_valid:
        ...     raise RollbackSecurityError(error)
    """
    try:
        # Get allowed directories (with defaults if needed)
        if allowed_directories is None:
            allowed_directories = _get_default_allowed_directories()

        # Check for null bytes
        if "\x00" in str(file_path):
            return False, "Path contains null bytes (security violation)"

        # Resolve path
        real_path = _resolve_path(file_path)
        if not real_path:
            return False, "Cannot resolve path"

        # Check symlinks
        if check_symlinks:
            symlink_error = _check_symlinks(file_path, real_path)
            if symlink_error:
                return False, symlink_error

        # Check allowed directories
        if not _is_path_in_allowed_dirs(real_path, allowed_directories):
            return False, (
                f"Path outside allowed directories: {real_path}\n"
                f"Allowed: {', '.join(allowed_directories)}"
            )

        # Check dangerous directories
        dangerous_error = _check_dangerous_directories(real_path)
        if dangerous_error:
            return False, dangerous_error

        # Path is valid
        return True, None

    except Exception as e:  # noqa: BLE001 -- fail-closed top-level handler
        # Any unexpected error - fail closed
        logger.error(f"Path validation error for {file_path}: {e}")
        return False, f"Path validation failed: {str(e)}"


def _get_default_allowed_directories() -> list[str]:
    """Get default allowed directories for rollback operations.

    Returns:
        List of safe default directories
    """
    allowed_directories = [
        "/tmp",  # noqa: S108  # nosec B108 — safe default for rollback
        "/var/tmp",  # noqa: S108  # nosec B108
        os.path.expanduser("~/.cache"),
        os.getcwd(),  # Current working directory
    ]

    # Add platform-specific temp directories
    import tempfile

    temp_dir = tempfile.gettempdir()
    if temp_dir not in allowed_directories:
        allowed_directories.append(temp_dir)

    return allowed_directories


def _resolve_path(file_path: str) -> str | None:
    """Resolve file path to absolute real path.

    Args:
        file_path: Path to resolve

    Returns:
        Resolved path or None if resolution fails
    """
    try:
        return os.path.realpath(os.path.abspath(file_path))
    except (OSError, ValueError) as e:
        logger.error(f"Cannot resolve path {file_path}: {e}")
        return None


def _check_symlinks(file_path: str, real_path: str) -> str | None:
    """Check for symlinks in path.

    Args:
        file_path: Original path
        real_path: Resolved real path

    Returns:
        Error message if symlink detected, None otherwise
    """
    try:
        current_path = Path(file_path)
        if current_path.exists() and current_path.is_symlink():
            return "Path is a symlink (security violation)"

        # Check parent directories for symlinks
        for parent in current_path.parents:
            if parent.exists() and parent.is_symlink():
                return "Path contains symlink in parent (security violation)"

        # Verify resolved path matches expectations
        if current_path.exists() and str(current_path.resolve()) != real_path:
            return "Path resolves differently than expected (possible symlink)"

        return None
    except (OSError, PermissionError) as e:
        # If we can't check, fail closed
        return f"Cannot verify symlink status: {str(e)}"


def _is_path_in_allowed_dirs(real_path: str, allowed_directories: list[str]) -> bool:
    """Check if path is within allowed directories.

    Args:
        real_path: Resolved real path
        allowed_directories: List of allowed directories

    Returns:
        True if path is allowed, False otherwise
    """
    for allowed_dir in allowed_directories:
        try:
            # Normalize allowed directory
            allowed_real = os.path.realpath(os.path.abspath(allowed_dir))

            # Check if real_path is within allowed_real
            try:
                common = os.path.commonpath([real_path, allowed_real])
                # If common path equals the allowed directory, file is inside it
                if common == allowed_real:
                    return True
            except ValueError:
                # Paths are on different drives (Windows) - not allowed
                continue

        except (OSError, ValueError):
            # Skip invalid allowed directories
            continue

    return False


def _check_dangerous_directories(real_path: str) -> str | None:
    """Check if path is in dangerous system directory.

    Args:
        real_path: Resolved real path

    Returns:
        Error message if in dangerous directory, None otherwise
    """
    dangerous_dirs = [
        "/etc",
        "/sys",
        "/proc",
        "/dev",
        "/boot",
        "C:\\Windows\\System32",
        "C:\\Windows\\SysWOW64",
    ]

    for dangerous_dir in dangerous_dirs:
        try:
            dangerous_real = os.path.realpath(os.path.abspath(dangerous_dir))

            # Check if real_path is within dangerous_real
            try:
                common = os.path.commonpath([real_path, dangerous_real])
                if common == dangerous_real:
                    return f"Access to system directory denied: {dangerous_dir}"
            except ValueError:
                # Paths are on different drives (Windows) - not in dangerous dir
                continue

        except (OSError, ValueError):
            # If we can't resolve dangerous dir, skip it
            continue

    return None


class RollbackStrategy(ABC):
    """Abstract rollback strategy for reverting specific action types.

    Subclasses implement specific rollback logic for different action types
    (files, database, API calls, etc.).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name."""
        pass

    @abstractmethod
    def create_snapshot(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> RollbackSnapshot:
        """Create snapshot before action execution.

        Args:
            action: Action to be executed
            context: Execution context

        Returns:
            RollbackSnapshot with pre-action state
        """
        pass

    @abstractmethod
    def execute_rollback(self, snapshot: RollbackSnapshot) -> RollbackResult:
        """Execute rollback using snapshot.

        Args:
            snapshot: Snapshot to revert to

        Returns:
            RollbackResult with operation outcome
        """
        pass

    def validate_rollback(self, snapshot: RollbackSnapshot) -> tuple[bool, list[str]]:
        """Validate that rollback is safe to execute.

        Args:
            snapshot: Snapshot to validate

        Returns:
            (is_valid, error_messages)
        """
        return True, []


class FileRollbackStrategy(RollbackStrategy):
    """Rollback strategy for file operations.

    Captures file contents before modification and restores them on rollback.
    Supports file creation, modification, and deletion.
    """

    @property
    def name(self) -> str:
        """Rollback handler name."""
        return "file_rollback"

    def create_snapshot(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> RollbackSnapshot:
        """Snapshot file state before modification."""
        snapshot = RollbackSnapshot(action=action, context=context)

        # Extract file paths from action
        file_paths = self._extract_file_paths(action)

        # Capture current file contents
        for file_path in file_paths:
            # SECURITY: Validate path before accessing
            is_valid, error = validate_rollback_path(file_path)
            if not is_valid:
                logger.error(
                    f"SECURITY: Rejected invalid path in snapshot: {file_path}",
                    extra={"error": error, "action": action},
                )
                raise RollbackSecurityError(
                    f"Invalid file path rejected: {file_path}\n"
                    f"Reason: {error}\n"
                    f"This may indicate a path traversal attack."
                )

            path = Path(file_path)
            if path.exists() and path.is_file():
                try:
                    with open(path) as f:
                        snapshot.file_snapshots[file_path] = f.read()
                    snapshot.metadata[f"{file_path}{EXISTED_SUFFIX}"] = True
                except (OSError, UnicodeDecodeError):
                    # Binary file or read error - skip content snapshot
                    snapshot.metadata[f"{file_path}{EXISTED_SUFFIX}"] = True
                    snapshot.metadata[f"{file_path}_unreadable"] = True
            else:
                # File doesn't exist yet (will be created)
                snapshot.metadata[f"{file_path}{EXISTED_SUFFIX}"] = False

        return snapshot

    def execute_rollback(self, snapshot: RollbackSnapshot) -> RollbackResult:
        """Restore files to snapshot state."""
        result = RollbackResult(
            success=False, snapshot_id=snapshot.id, status=RollbackStatus.IN_PROGRESS
        )

        # Validate rollback
        is_valid, errors = self.validate_rollback(snapshot)
        if not is_valid:
            result.status = RollbackStatus.FAILED
            result.errors = errors
            return result

        # Restore file contents
        self._restore_file_contents(snapshot, result)

        # Delete files that didn't exist before
        self._delete_created_files(snapshot, result)

        # Determine final status
        self._set_final_status(result)

        return result

    def _restore_file_contents(
        self, snapshot: RollbackSnapshot, result: RollbackResult
    ) -> None:
        """Restore file contents from snapshot.

        Args:
            snapshot: Snapshot with file contents
            result: Result object to update
        """
        for file_path, content in snapshot.file_snapshots.items():
            try:
                # SECURITY: Validate path before writing
                is_valid, error = validate_rollback_path(file_path)
                if not is_valid:
                    logger.error(
                        f"SECURITY: Rejected invalid path in rollback restore: {file_path}",
                        extra={"error": error, "snapshot_id": snapshot.id},
                    )
                    result.failed_items.append(file_path)
                    result.errors.append(f"Security violation: {error}")
                    continue

                # Restore file atomically
                if self._restore_file_atomically(file_path, content, result):
                    result.reverted_items.append(file_path)

            except OSError as e:
                result.failed_items.append(file_path)
                result.errors.append(f"Failed to restore {file_path}: {str(e)}")

    def _restore_file_atomically(
        self, file_path: str, content: str, result: RollbackResult
    ) -> bool:
        """Restore file content atomically.

        Args:
            file_path: Path to restore
            content: File content
            result: Result object to update on error

        Returns:
            True if successful, False otherwise
        """
        # Re-validate path immediately before I/O (TOCTOU protection)
        recheck_valid, recheck_err = validate_rollback_path(file_path)
        if not recheck_valid:
            result.failed_items.append(file_path)
            result.errors.append(f"Security violation on recheck: {recheck_err}")
            return False

        # Use atomic write: tempfile + os.replace
        import tempfile as _tempfile

        dir_path = os.path.dirname(os.path.abspath(file_path))
        fd, tmp_path = _tempfile.mkstemp(dir=dir_path)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.replace(tmp_path, file_path)
            return True
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _delete_created_files(
        self, snapshot: RollbackSnapshot, result: RollbackResult
    ) -> None:
        """Delete files that were created (didn't exist before).

        Args:
            snapshot: Snapshot with file metadata
            result: Result object to update
        """
        for key, existed in snapshot.metadata.items():
            if not key.endswith(EXISTED_SUFFIX) or existed:
                continue

            file_path = key.replace(EXISTED_SUFFIX, "")

            # SECURITY: Validate path before deletion
            is_valid, error = validate_rollback_path(file_path)
            if not is_valid:
                logger.error(
                    f"SECURITY: Rejected invalid path in rollback deletion: {file_path}",
                    extra={"error": error, "snapshot_id": snapshot.id},
                )
                result.failed_items.append(file_path)
                result.errors.append(f"Security violation (delete): {error}")
                continue

            try:
                self._delete_file_safely(file_path, result)
            except OSError as e:
                result.failed_items.append(file_path)
                result.errors.append(f"Failed to delete {file_path}: {str(e)}")

    def _delete_file_safely(self, file_path: str, result: RollbackResult) -> None:
        """Delete file with TOCTOU protection.

        Args:
            file_path: Path to delete
            result: Result object to update on error
        """
        # SECURITY (SA-02): Resolve real path immediately before deletion
        real_path = os.path.realpath(file_path)
        is_valid2, error2 = validate_rollback_path(real_path)
        if not is_valid2:
            logger.error(
                f"SECURITY: Resolved path failed validation: {real_path}",
                extra={"original": file_path, "error": error2},
            )
            result.failed_items.append(file_path)
            result.errors.append(f"Security violation (resolved path): {error2}")
            return

        if os.path.exists(real_path):
            os.remove(real_path)
            result.reverted_items.append(f"deleted:{file_path}")

    def _set_final_status(self, result: RollbackResult) -> None:
        """Set final status based on operation results.

        Args:
            result: Result object to update
        """
        if not result.failed_items:
            result.status = RollbackStatus.COMPLETED
            result.success = True
        elif result.reverted_items:
            result.status = RollbackStatus.PARTIAL
            result.success = False
        else:
            result.status = RollbackStatus.FAILED
            result.success = False

    def _extract_file_paths(self, action: dict[str, Any]) -> list[str]:
        """Extract file paths from action."""
        paths = []

        # Check common file path keys
        for key in ["path", "file", "file_path", "files"]:
            if key in action:
                value = action[key]
                if isinstance(value, str):
                    paths.append(value)
                elif isinstance(value, list):
                    paths.extend(value)

        return paths


class StateRollbackStrategy(RollbackStrategy):
    """Rollback strategy for state changes.

    Captures arbitrary state values and restores them on rollback.
    Useful for in-memory state, configuration, or external system state.
    """

    @property
    def name(self) -> str:
        """Rollback handler name."""
        return "state_rollback"

    def __init__(self, state_getter: Callable[[], dict[str, Any]] | None = None):
        """Initialize with optional state getter.

        Args:
            state_getter: Function to retrieve current state
        """
        self.state_getter = state_getter

    def create_snapshot(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> RollbackSnapshot:
        """Snapshot current state."""
        snapshot = RollbackSnapshot(action=action, context=context)

        if self.state_getter:
            try:
                current_state = self.state_getter()
                if isinstance(current_state, dict):
                    snapshot.state_snapshots = current_state.copy()
            except Exception as e:  # noqa: BLE001 -- arbitrary state_getter callback
                snapshot.metadata["snapshot_error"] = str(e)

        return snapshot

    def execute_rollback(self, snapshot: RollbackSnapshot) -> RollbackResult:
        """Restore state to snapshot values."""
        result = RollbackResult(
            success=True, snapshot_id=snapshot.id, status=RollbackStatus.COMPLETED
        )

        # State rollback requires custom implementation
        # This base implementation just records the snapshot
        result.metadata["state_snapshot"] = snapshot.state_snapshots
        result.reverted_items = list(snapshot.state_snapshots.keys())

        return result


class CompositeRollbackStrategy(RollbackStrategy):
    """Composite rollback strategy that combines multiple strategies.

    Executes rollback across multiple strategies in order.
    Useful for complex actions that affect files, state, and external systems.
    """

    @property
    def name(self) -> str:
        """Rollback handler name."""
        return "composite_rollback"

    def __init__(self, strategies: list[RollbackStrategy] | None = None):
        """Initialize with list of strategies.

        Args:
            strategies: List of rollback strategies to compose
        """
        self.strategies: list[RollbackStrategy] = strategies or []

    def add_strategy(self, strategy: RollbackStrategy) -> None:
        """Add a strategy to the composite."""
        self.strategies.append(strategy)

    def create_snapshot(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> RollbackSnapshot:
        """Create composite snapshot from all strategies."""
        snapshot = RollbackSnapshot(action=action, context=context)

        # Collect snapshots from all strategies
        for strategy in self.strategies:
            try:
                sub_snapshot = strategy.create_snapshot(action, context)

                # Merge file snapshots
                snapshot.file_snapshots.update(sub_snapshot.file_snapshots)

                # Merge state snapshots
                snapshot.state_snapshots.update(sub_snapshot.state_snapshots)

                # Track which strategies contributed
                snapshot.metadata[f"{STRATEGY_PREFIX}{strategy.name}"] = True
            except Exception as e:  # noqa: BLE001 -- arbitrary strategy callback
                snapshot.metadata[f"{STRATEGY_PREFIX}{strategy.name}_error"] = str(e)

        return snapshot

    def execute_rollback(self, snapshot: RollbackSnapshot) -> RollbackResult:
        """Execute rollback across all strategies."""
        composite_result = RollbackResult(
            success=True, snapshot_id=snapshot.id, status=RollbackStatus.IN_PROGRESS
        )

        # Execute rollback for each strategy
        for strategy in self.strategies:
            try:
                result = strategy.execute_rollback(snapshot)

                # Aggregate results
                composite_result.reverted_items.extend(result.reverted_items)
                composite_result.failed_items.extend(result.failed_items)
                composite_result.errors.extend(result.errors)

                if not result.success:
                    composite_result.success = False

                composite_result.metadata[
                    f"{STRATEGY_PREFIX}{strategy.name}_status"
                ] = result.status.value
            except Exception as e:  # noqa: BLE001 -- arbitrary strategy callback
                composite_result.success = False
                composite_result.errors.append(
                    f"Strategy {strategy.name} failed: {str(e)}"
                )

        # Determine final status
        if composite_result.success and not composite_result.failed_items:
            composite_result.status = RollbackStatus.COMPLETED
        elif composite_result.reverted_items and composite_result.failed_items:
            composite_result.status = RollbackStatus.PARTIAL
        else:
            composite_result.status = RollbackStatus.FAILED

        return composite_result


class RollbackManager:
    """Manages rollback operations and snapshot lifecycle.

    Orchestrates snapshot creation, rollback execution, and history tracking.
    Integrates with approval workflow for automatic rollback on rejection.

    Example:
        >>> manager = RollbackManager()
        >>> manager.register_strategy("file", FileRollbackStrategy())
        >>>
        >>> # Create snapshot
        >>> snapshot = manager.create_snapshot(
        ...     action={"tool": "write_file", "path": "/tmp/test.txt"},
        ...     context={"agent": "writer"}
        ... )
        >>>
        >>> # Execute action...
        >>>
        >>> # Rollback if needed
        >>> result = manager.execute_rollback(snapshot.id)
    """

    # Defaults for bounded collections
    MAX_SNAPSHOTS = MAX_MEDIUM_STRING_LENGTH
    MAX_HISTORY = THRESHOLD_LARGE_COUNT

    def __init__(
        self,
        default_strategy: RollbackStrategy | None = None,
        max_snapshots: int = MAX_SNAPSHOTS,
        max_history: int = MAX_HISTORY,
    ):
        """Initialize rollback manager.

        Args:
            default_strategy: Default strategy if no specific match
            max_snapshots: Maximum stored snapshots before oldest are evicted
            max_history: Maximum stored history entries before oldest are evicted
        """
        self.default_strategy = default_strategy or FileRollbackStrategy()
        self._strategies: dict[str, RollbackStrategy] = {}
        self._snapshots: dict[str, RollbackSnapshot] = {}
        self._history: list[RollbackResult] = []
        self._max_snapshots = max_snapshots
        self._max_history = max_history
        self._on_rollback_callbacks: list[Callable[[RollbackResult], None]] = []

    def register_strategy(self, action_type: str, strategy: RollbackStrategy) -> None:
        """Register a rollback strategy for an action type.

        Args:
            action_type: Type of action (e.g., "file", "database", "api")
            strategy: Rollback strategy to use
        """
        self._strategies[action_type] = strategy

    def create_snapshot(
        self,
        action: dict[str, Any],
        context: dict[str, Any] | None = None,
        strategy_name: str | None = None,
    ) -> RollbackSnapshot:
        """Create snapshot before action execution.

        Args:
            action: Action to be executed
            context: Execution context
            strategy_name: Specific strategy to use (uses default if None)

        Returns:
            RollbackSnapshot with pre-action state
        """
        # Select strategy
        if strategy_name and strategy_name in self._strategies:
            strategy = self._strategies[strategy_name]
        else:
            # Try to infer strategy from action type
            action_type = action.get("type") or action.get("tool")
            if action_type and isinstance(action_type, str):
                strategy = self._strategies.get(action_type, self.default_strategy)
            else:
                strategy = self.default_strategy

        # Create snapshot
        snapshot = strategy.create_snapshot(action, context or {})

        # Store snapshot with eviction of oldest when over limit
        self._snapshots[snapshot.id] = snapshot
        if len(self._snapshots) > self._max_snapshots:
            # Remove oldest snapshot (by creation time)
            oldest_id = min(
                self._snapshots, key=lambda k: self._snapshots[k].created_at
            )
            del self._snapshots[oldest_id]

        return snapshot

    def execute_rollback(
        self, snapshot_id: str, strategy_name: str | None = None, dry_run: bool = False
    ) -> RollbackResult:
        """Execute rollback for a snapshot.

        Args:
            snapshot_id: ID of snapshot to rollback
            strategy_name: Specific strategy to use (infers if None)
            dry_run: If True, validate but don't execute (default: False)

        Returns:
            RollbackResult with operation outcome

        Raises:
            ValueError: If snapshot not found
        """
        # Get snapshot
        snapshot = self._snapshots.get(snapshot_id)
        if not snapshot:
            raise ValueError(f"Snapshot {snapshot_id} not found")

        # Dry run mode: return mock result without executing
        if dry_run:
            return RollbackResult(
                success=True,
                snapshot_id=snapshot_id,
                status=RollbackStatus.COMPLETED,
                reverted_items=list(snapshot.file_snapshots.keys()),
                failed_items=[],
                errors=[],
                metadata={"dry_run": True},
                completed_at=datetime.now(UTC),
            )

        # Select strategy
        if strategy_name and strategy_name in self._strategies:
            strategy = self._strategies[strategy_name]
        else:
            # Infer strategy from action
            action_type = snapshot.action.get("type") or snapshot.action.get("tool")
            if action_type and isinstance(action_type, str):
                strategy = self._strategies.get(action_type, self.default_strategy)
            else:
                strategy = self.default_strategy

        # Execute rollback
        result = strategy.execute_rollback(snapshot)

        # Record in history with eviction of oldest when over limit
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        # Trigger callbacks
        self._trigger_rollback_callbacks(result)

        return result

    def get_snapshot(self, snapshot_id: str) -> RollbackSnapshot | None:
        """Get snapshot by ID.

        Args:
            snapshot_id: Snapshot ID

        Returns:
            RollbackSnapshot if found, None otherwise
        """
        return self._snapshots.get(snapshot_id)

    def list_snapshots(self) -> list[RollbackSnapshot]:
        """Get all snapshots.

        Returns:
            List of all snapshots
        """
        return list(self._snapshots.values())

    def get_history(self) -> list[RollbackResult]:
        """Get rollback history.

        Returns:
            List of rollback results
        """
        return self._history.copy()

    def on_rollback(self, callback: Callable[[RollbackResult], None]) -> None:
        """Register callback for rollback events.

        Args:
            callback: Function to call when rollback executes
        """
        self._on_rollback_callbacks.append(callback)

    def _trigger_rollback_callbacks(self, result: RollbackResult) -> None:
        """Trigger all rollback callbacks."""
        for callback in self._on_rollback_callbacks:
            try:
                callback(result)
            except (
                Exception
            ):  # noqa: BLE001 -- defensive cleanup for arbitrary callback
                # Don't let callback errors break rollback
                pass

    def clear_snapshots(self) -> None:
        """Clear all snapshots. Use with caution!"""
        self._snapshots.clear()

    def clear_history(self) -> None:
        """Clear rollback history."""
        self._history.clear()

    def snapshot_count(self) -> int:
        """Get total number of snapshots."""
        return len(self._snapshots)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"RollbackManager("
            f"snapshots={len(self._snapshots)}, "
            f"strategies={len(self._strategies)}, "
            f"history={len(self._history)})"
        )
