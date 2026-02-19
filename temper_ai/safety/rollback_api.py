"""Public API for manual rollback operations.

This module provides a high-level API for querying and executing manual rollbacks
with comprehensive safety checks and validation.

Example:
    >>> from temper_ai.safety.rollback import RollbackManager
    >>> from temper_ai.safety.rollback_api import RollbackAPI
    >>>
    >>> manager = RollbackManager()
    >>> api = RollbackAPI(manager)
    >>>
    >>> # List recent snapshots
    >>> snapshots = api.list_snapshots(workflow_id="wf-123", limit=10)
    >>>
    >>> # Validate safety before rollback
    >>> is_safe, warnings = api.validate_rollback_safety(snapshot.id)
    >>>
    >>> # Execute manual rollback
    >>> result = api.execute_manual_rollback(
    ...     snapshot_id=snapshot.id,
    ...     operator="alice",
    ...     reason="Manual recovery from failed deployment"
    ... )
"""
import os
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple

from temper_ai.shared.constants.durations import SECONDS_PER_HOUR
from temper_ai.shared.constants.limits import THRESHOLD_LARGE_COUNT
from temper_ai.safety.rollback import RollbackManager, RollbackResult, RollbackSnapshot
from temper_ai.shared.utils.logging import get_logger

logger = get_logger(__name__)


class RollbackAPI:
    """Public API for querying and executing manual rollbacks.

    Provides a safe, high-level interface for rollback operations with
    comprehensive validation and safety checks.

    Example:
        >>> api = RollbackAPI(rollback_manager)
        >>> snapshots = api.list_snapshots(since=datetime.now() - timedelta(hours=24))
        >>> for snap in snapshots:
        ...     print(f"{snap.id}: {snap.action}")
    """

    def __init__(self, rollback_manager: RollbackManager):
        """Initialize rollback API.

        Args:
            rollback_manager: RollbackManager instance
        """
        self.manager = rollback_manager

    # Default snapshot limit
    DEFAULT_SNAPSHOT_LIMIT = THRESHOLD_LARGE_COUNT

    def list_snapshots(
        self,
        workflow_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = DEFAULT_SNAPSHOT_LIMIT
    ) -> List[RollbackSnapshot]:
        """List available snapshots with filtering.

        Args:
            workflow_id: Filter by workflow ID (optional)
            agent_id: Filter by agent ID (optional)
            since: Filter by creation time (optional)
            limit: Maximum number of snapshots to return (default: 100)

        Returns:
            List of snapshots matching filters, sorted by creation time (newest first)
        """
        snapshots = self.manager.list_snapshots()

        # Filter by workflow_id
        if workflow_id:
            snapshots = [
                s for s in snapshots
                if s.context.get("workflow_id") == workflow_id
            ]

        # Filter by agent_id
        if agent_id:
            snapshots = [
                s for s in snapshots
                if s.context.get("agent_id") == agent_id
            ]

        # Filter by time
        if since:
            snapshots = [s for s in snapshots if s.created_at >= since]

        # Sort by creation time (newest first) and limit
        snapshots.sort(key=lambda s: s.created_at, reverse=True)
        return snapshots[:limit]

    def get_snapshot_details(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed snapshot information.

        Args:
            snapshot_id: Snapshot ID

        Returns:
            Dict with snapshot details or None if not found
        """
        snapshot = self.manager.get_snapshot(snapshot_id)
        if not snapshot:
            return None

        return {
            "id": snapshot.id,
            "action": snapshot.action,
            "context": snapshot.context,
            "created_at": snapshot.created_at.isoformat(),
            "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
            "file_count": len(snapshot.file_snapshots),
            "files": list(snapshot.file_snapshots.keys()),
            "state_keys": list(snapshot.state_snapshots.keys()),
            "age_hours": (datetime.now(UTC) - snapshot.created_at).total_seconds() / SECONDS_PER_HOUR
        }

    def validate_rollback_safety(
        self,
        snapshot_id: str
    ) -> Tuple[bool, List[str]]:
        """Pre-flight safety checks before rollback.

        Checks for:
        - Snapshot expiration
        - File modifications since snapshot
        - Snapshot age warnings

        Args:
            snapshot_id: Snapshot ID to validate

        Returns:
            (is_safe, warnings) - True if safe to rollback, list of warnings
        """
        snapshot = self.manager.get_snapshot(snapshot_id)
        if not snapshot:
            return False, ["Snapshot not found"]

        warnings = []

        # Check expiration
        if snapshot.expires_at and datetime.now(UTC) > snapshot.expires_at:
            warnings.append(f"Snapshot expired at {snapshot.expires_at.isoformat()}")

        # Check file conflicts (files modified since snapshot)
        for file_path in snapshot.file_snapshots.keys():
            if os.path.exists(file_path):
                file_mtime = datetime.fromtimestamp(
                    os.path.getmtime(file_path),
                    tz=UTC
                )
                if file_mtime > snapshot.created_at:
                    warnings.append(
                        f"File modified since snapshot: {file_path} "
                        f"(modified at {file_mtime.isoformat()})"
                    )

        # Check age
        snapshot_warning_age_hours = 24
        age_hours = (datetime.now(UTC) - snapshot.created_at).total_seconds() / SECONDS_PER_HOUR
        if age_hours > snapshot_warning_age_hours:
            warnings.append(f"Snapshot is {age_hours:.1f} hours old")

        # Safe if no critical warnings
        critical_warnings = [w for w in warnings if "expired" in w.lower()]
        return len(critical_warnings) == 0, warnings

    def execute_manual_rollback(
        self,
        snapshot_id: str,
        operator: str,
        reason: str,
        dry_run: bool = False,
        force: bool = False
    ) -> RollbackResult:
        """Execute manual rollback with safety validation.

        Args:
            snapshot_id: ID of snapshot to rollback to
            operator: Name/ID of person executing rollback
            reason: Reason for manual rollback
            dry_run: If True, validate but don't execute (default: False)
            force: If True, skip safety checks - use with caution! (default: False)

        Returns:
            RollbackResult with outcome

        Raises:
            ValueError: If snapshot not found or safety check failed
        """
        # Get snapshot
        snapshot = self.manager.get_snapshot(snapshot_id)
        if not snapshot:
            raise ValueError(f"Snapshot not found: {snapshot_id}")

        # Safety validation (unless forced)
        if not force:
            is_safe, warnings = self.validate_rollback_safety(snapshot_id)
            if not is_safe:
                raise ValueError(
                    f"Rollback safety check failed: {'; '.join(warnings)}"
                )

            # Log warnings even if safe
            if warnings:
                logger.warning(
                    f"Rollback warnings for {snapshot_id}: {warnings}"
                )

        # Execute rollback (with dry_run support)
        if dry_run:
            logger.info(f"Dry-run manual rollback {snapshot_id} by {operator}: {reason}")
        else:
            logger.info(f"Executing manual rollback {snapshot_id} by {operator}: {reason}")

        result = self.manager.execute_rollback(snapshot_id, dry_run=dry_run)

        # Add operator/reason to metadata
        result.metadata.update({
            "operator": operator,
            "reason": reason,
            "manual": True
        })

        return result

    # Default history limit
    DEFAULT_HISTORY_LIMIT = THRESHOLD_LARGE_COUNT

    def get_rollback_history(
        self,
        snapshot_id: Optional[str] = None,
        limit: int = DEFAULT_HISTORY_LIMIT
    ) -> List[RollbackResult]:
        """Get rollback execution history.

        Args:
            snapshot_id: Filter by snapshot ID (optional)
            limit: Maximum number of results (default: 100)

        Returns:
            List of rollback results
        """
        history = self.manager.get_history()

        if snapshot_id:
            history = [r for r in history if r.snapshot_id == snapshot_id]

        # Sort by completion time (newest first) and limit
        history.sort(key=lambda r: r.completed_at, reverse=True)
        return history[:limit]
