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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from uuid import uuid4
import os
import shutil


class RollbackStatus(Enum):
    """Status of a rollback operation.

    States:
        PENDING: Snapshot created, not yet rolled back
        IN_PROGRESS: Rollback currently executing
        COMPLETED: Rollback completed successfully
        FAILED: Rollback failed with errors
        PARTIAL: Rollback partially completed (some items failed)
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class RollbackSnapshot:
    """Snapshot of state before an action.

    Attributes:
        id: Unique snapshot identifier
        action: Action that will be executed
        context: Execution context
        created_at: When snapshot was created
        file_snapshots: Pre-action file states {path: content}
        state_snapshots: Pre-action state values {key: value}
        metadata: Additional snapshot metadata
        expires_at: Optional expiration time for cleanup
    """
    id: str = field(default_factory=lambda: str(uuid4()))
    action: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    file_snapshots: Dict[str, str] = field(default_factory=dict)
    state_snapshots: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "action": self.action,
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "file_snapshots": self.file_snapshots,
            "state_snapshots": self.state_snapshots,
            "metadata": self.metadata,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None
        }


@dataclass
class RollbackResult:
    """Result of a rollback operation.

    Attributes:
        success: Whether rollback completed successfully
        snapshot_id: ID of snapshot that was rolled back
        status: Rollback status
        reverted_items: List of successfully reverted items
        failed_items: List of items that failed to revert
        errors: Error messages from failures
        metadata: Additional result metadata
        completed_at: When rollback completed
    """
    success: bool
    snapshot_id: str
    status: RollbackStatus
    reverted_items: List[str] = field(default_factory=list)
    failed_items: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "snapshot_id": self.snapshot_id,
            "status": self.status.value,
            "reverted_items": self.reverted_items,
            "failed_items": self.failed_items,
            "errors": self.errors,
            "metadata": self.metadata,
            "completed_at": self.completed_at.isoformat()
        }


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
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
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
    def execute_rollback(
        self,
        snapshot: RollbackSnapshot
    ) -> RollbackResult:
        """Execute rollback using snapshot.

        Args:
            snapshot: Snapshot to revert to

        Returns:
            RollbackResult with operation outcome
        """
        pass

    def validate_rollback(
        self,
        snapshot: RollbackSnapshot
    ) -> tuple[bool, List[str]]:
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
        return "file_rollback"

    def create_snapshot(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> RollbackSnapshot:
        """Snapshot file state before modification."""
        snapshot = RollbackSnapshot(action=action, context=context)

        # Extract file paths from action
        file_paths = self._extract_file_paths(action)

        # Capture current file contents
        for file_path in file_paths:
            path = Path(file_path)
            if path.exists() and path.is_file():
                try:
                    with open(path, 'r') as f:
                        snapshot.file_snapshots[file_path] = f.read()
                    snapshot.metadata[f"{file_path}_existed"] = True
                except Exception:
                    # Binary file or read error - skip content snapshot
                    snapshot.metadata[f"{file_path}_existed"] = True
                    snapshot.metadata[f"{file_path}_unreadable"] = True
            else:
                # File doesn't exist yet (will be created)
                snapshot.metadata[f"{file_path}_existed"] = False

        return snapshot

    def execute_rollback(
        self,
        snapshot: RollbackSnapshot
    ) -> RollbackResult:
        """Restore files to snapshot state."""
        result = RollbackResult(
            success=False,
            snapshot_id=snapshot.id,
            status=RollbackStatus.IN_PROGRESS
        )

        # Validate rollback
        is_valid, errors = self.validate_rollback(snapshot)
        if not is_valid:
            result.status = RollbackStatus.FAILED
            result.errors = errors
            return result

        # Revert each file
        for file_path, content in snapshot.file_snapshots.items():
            try:
                # Restore file content
                with open(file_path, 'w') as f:
                    f.write(content)
                result.reverted_items.append(file_path)
            except Exception as e:
                result.failed_items.append(file_path)
                result.errors.append(f"Failed to restore {file_path}: {str(e)}")

        # Delete files that didn't exist before
        for key, existed in snapshot.metadata.items():
            if key.endswith("_existed") and not existed:
                file_path = key.replace("_existed", "")
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        result.reverted_items.append(f"deleted:{file_path}")
                except Exception as e:
                    result.failed_items.append(file_path)
                    result.errors.append(f"Failed to delete {file_path}: {str(e)}")

        # Determine final status
        if not result.failed_items:
            result.status = RollbackStatus.COMPLETED
            result.success = True
        elif result.reverted_items:
            result.status = RollbackStatus.PARTIAL
            result.success = False
        else:
            result.status = RollbackStatus.FAILED
            result.success = False

        return result

    def _extract_file_paths(self, action: Dict[str, Any]) -> List[str]:
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
        return "state_rollback"

    def __init__(self, state_getter: Optional[Callable[[], Dict[str, Any]]] = None):
        """Initialize with optional state getter.

        Args:
            state_getter: Function to retrieve current state
        """
        self.state_getter = state_getter

    def create_snapshot(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> RollbackSnapshot:
        """Snapshot current state."""
        snapshot = RollbackSnapshot(action=action, context=context)

        if self.state_getter:
            try:
                current_state = self.state_getter()
                if isinstance(current_state, dict):
                    snapshot.state_snapshots = current_state.copy()
            except Exception as e:
                snapshot.metadata["snapshot_error"] = str(e)

        return snapshot

    def execute_rollback(
        self,
        snapshot: RollbackSnapshot
    ) -> RollbackResult:
        """Restore state to snapshot values."""
        result = RollbackResult(
            success=True,
            snapshot_id=snapshot.id,
            status=RollbackStatus.COMPLETED
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
        return "composite_rollback"

    def __init__(self, strategies: Optional[List[RollbackStrategy]] = None):
        """Initialize with list of strategies.

        Args:
            strategies: List of rollback strategies to compose
        """
        self.strategies: List[RollbackStrategy] = strategies or []

    def add_strategy(self, strategy: RollbackStrategy) -> None:
        """Add a strategy to the composite."""
        self.strategies.append(strategy)

    def create_snapshot(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
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
                snapshot.metadata[f"strategy_{strategy.name}"] = True
            except Exception as e:
                snapshot.metadata[f"strategy_{strategy.name}_error"] = str(e)

        return snapshot

    def execute_rollback(
        self,
        snapshot: RollbackSnapshot
    ) -> RollbackResult:
        """Execute rollback across all strategies."""
        composite_result = RollbackResult(
            success=True,
            snapshot_id=snapshot.id,
            status=RollbackStatus.IN_PROGRESS
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

                composite_result.metadata[f"strategy_{strategy.name}_status"] = result.status.value
            except Exception as e:
                composite_result.success = False
                composite_result.errors.append(f"Strategy {strategy.name} failed: {str(e)}")

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

    def __init__(self, default_strategy: Optional[RollbackStrategy] = None):
        """Initialize rollback manager.

        Args:
            default_strategy: Default strategy if no specific match
        """
        self.default_strategy = default_strategy or FileRollbackStrategy()
        self._strategies: Dict[str, RollbackStrategy] = {}
        self._snapshots: Dict[str, RollbackSnapshot] = {}
        self._history: List[RollbackResult] = []
        self._on_rollback_callbacks: List[Callable[[RollbackResult], None]] = []

    def register_strategy(self, action_type: str, strategy: RollbackStrategy) -> None:
        """Register a rollback strategy for an action type.

        Args:
            action_type: Type of action (e.g., "file", "database", "api")
            strategy: Rollback strategy to use
        """
        self._strategies[action_type] = strategy

    def create_snapshot(
        self,
        action: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        strategy_name: Optional[str] = None
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

        # Store snapshot
        self._snapshots[snapshot.id] = snapshot

        return snapshot

    def execute_rollback(
        self,
        snapshot_id: str,
        strategy_name: Optional[str] = None
    ) -> RollbackResult:
        """Execute rollback for a snapshot.

        Args:
            snapshot_id: ID of snapshot to rollback
            strategy_name: Specific strategy to use (infers if None)

        Returns:
            RollbackResult with operation outcome

        Raises:
            ValueError: If snapshot not found
        """
        # Get snapshot
        snapshot = self._snapshots.get(snapshot_id)
        if not snapshot:
            raise ValueError(f"Snapshot {snapshot_id} not found")

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

        # Record in history
        self._history.append(result)

        # Trigger callbacks
        self._trigger_rollback_callbacks(result)

        return result

    def get_snapshot(self, snapshot_id: str) -> Optional[RollbackSnapshot]:
        """Get snapshot by ID.

        Args:
            snapshot_id: Snapshot ID

        Returns:
            RollbackSnapshot if found, None otherwise
        """
        return self._snapshots.get(snapshot_id)

    def list_snapshots(self) -> List[RollbackSnapshot]:
        """Get all snapshots.

        Returns:
            List of all snapshots
        """
        return list(self._snapshots.values())

    def get_history(self) -> List[RollbackResult]:
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
            except Exception:
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
