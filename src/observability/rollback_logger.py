"""Logging for rollback operations.

This module provides functions to log rollback events to the observability
database for audit trail and compliance purposes.

Example:
    >>> from src.safety.rollback import RollbackResult
    >>> from src.observability.rollback_logger import log_rollback_event
    >>>
    >>> # After rollback execution
    >>> log_rollback_event(
    ...     result=rollback_result,
    ...     trigger="auto",
    ...     operator="agent-123"
    ... )
"""
from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from src.shared.constants.limits import VERY_LARGE_ITEM_LIMIT
from src.storage.database import DatabaseManager, get_database
from src.storage.database.models import RollbackEvent, RollbackSnapshotDB
from src.observability.rollback_types import RollbackResult
from src.observability.rollback_types import RollbackSnapshot as SnapshotData
from src.shared.utils.logging import get_logger

logger = get_logger(__name__)


def log_rollback_snapshot(
    snapshot: SnapshotData,
    workflow_execution_id: Optional[str] = None,
    checkpoint_id: Optional[str] = None,
    db_manager: Optional[DatabaseManager] = None
) -> None:
    """Log rollback snapshot to database.

    Args:
        snapshot: RollbackSnapshot to log
        workflow_execution_id: Associated workflow execution ID (optional)
        checkpoint_id: Associated checkpoint ID (optional)
        db_manager: DatabaseManager instance (creates if None)
    """
    if db_manager is None:
        # OB-05: Use the initialized singleton instead of creating an
        # uninitialized DatabaseManager that may lack table setup.
        db_manager = get_database()

    try:
        snapshot_db = RollbackSnapshotDB(
            id=snapshot.id,
            workflow_execution_id=workflow_execution_id or snapshot.context.get("workflow_id"),
            checkpoint_id=checkpoint_id,
            action=snapshot.action,
            context=snapshot.context,
            file_snapshots=snapshot.file_snapshots,
            state_snapshots=snapshot.state_snapshots,
            created_at=snapshot.created_at,
            expires_at=snapshot.expires_at
        )

        with db_manager.session() as session:
            session.add(snapshot_db)
            # OB-04: Let context manager handle commit; explicit commit here
            # causes double-commit since session().__exit__ also commits.

        logger.debug(f"Logged rollback snapshot {snapshot.id} to database")
    except Exception as e:
        logger.error(f"Failed to log rollback snapshot: {e}")


def log_rollback_event(
    result: RollbackResult,
    trigger: str,
    operator: Optional[str] = None,
    reason: Optional[str] = None,
    db_manager: Optional[DatabaseManager] = None
) -> None:
    """Log rollback execution to database.

    Args:
        result: RollbackResult from execution
        trigger: "auto" | "manual" | "approval_rejection"
        operator: Name/ID of operator (for manual rollbacks)
        reason: Reason for rollback (for manual rollbacks)
        db_manager: DatabaseManager instance (creates if None)
    """
    if db_manager is None:
        # OB-05: Use the initialized singleton instead of creating an
        # uninitialized DatabaseManager that may lack table setup.
        db_manager = get_database()

    try:
        event = RollbackEvent(
            id=str(uuid4()),
            snapshot_id=result.snapshot_id,
            status=result.status.value,
            trigger=trigger,
            operator=operator or result.metadata.get("operator"),
            reverted_items=result.reverted_items,
            failed_items=result.failed_items,
            errors=result.errors,
            executed_at=result.completed_at or datetime.now(UTC),
            reason=reason or result.metadata.get("reason"),
            rollback_metadata=result.metadata
        )

        with db_manager.session() as session:
            session.add(event)
            session.commit()

        logger.info(
            f"Logged rollback event for snapshot {result.snapshot_id}: "
            f"trigger={trigger}, status={result.status.value}"
        )
    except Exception as e:
        logger.error(f"Failed to log rollback event: {e}")


def get_rollback_events(
    snapshot_id: Optional[str] = None,
    trigger: Optional[str] = None,
    limit: int = VERY_LARGE_ITEM_LIMIT,
    db_manager: Optional[DatabaseManager] = None
) -> list[RollbackEvent]:
    """Query rollback events from database.

    Args:
        snapshot_id: Filter by snapshot ID (optional)
        trigger: Filter by trigger type (optional)
        limit: Maximum number of results (default: 100)
        db_manager: DatabaseManager instance (creates if None)

    Returns:
        List of RollbackEvent records
    """
    if db_manager is None:
        # OB-05: Use the initialized singleton instead of creating an
        # uninitialized DatabaseManager that may lack table setup.
        db_manager = get_database()

    try:
        with db_manager.session() as session:
            query = session.query(RollbackEvent)

            if snapshot_id:
                query = query.filter(RollbackEvent.snapshot_id == snapshot_id)  # type: ignore[arg-type]

            if trigger:
                query = query.filter(RollbackEvent.trigger == trigger)  # type: ignore[arg-type]

            query = query.order_by(RollbackEvent.executed_at.desc())  # type: ignore[attr-defined]
            query = query.limit(limit)

            return query.all()
    except Exception as e:
        logger.error(f"Failed to query rollback events: {e}")
        return []


def get_rollback_snapshots(
    workflow_execution_id: Optional[str] = None,
    limit: int = VERY_LARGE_ITEM_LIMIT,
    db_manager: Optional[DatabaseManager] = None
) -> list[RollbackSnapshotDB]:
    """Query rollback snapshots from database.

    Args:
        workflow_execution_id: Filter by workflow execution ID (optional)
        limit: Maximum number of results (default: 100)
        db_manager: DatabaseManager instance (creates if None)

    Returns:
        List of RollbackSnapshotDB records
    """
    if db_manager is None:
        # OB-05: Use the initialized singleton instead of creating an
        # uninitialized DatabaseManager that may lack table setup.
        db_manager = get_database()

    try:
        with db_manager.session() as session:
            query = session.query(RollbackSnapshotDB)

            if workflow_execution_id:
                query = query.filter(
                    RollbackSnapshotDB.workflow_execution_id == workflow_execution_id  # type: ignore[arg-type]
                )

            query = query.order_by(RollbackSnapshotDB.created_at.desc())  # type: ignore[attr-defined]
            query = query.limit(limit)

            return query.all()
    except Exception as e:
        logger.error(f"Failed to query rollback snapshots: {e}")
        return []
