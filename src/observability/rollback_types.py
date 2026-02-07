"""Rollback data types for observability logging.

This module contains pure data structures for rollback operations.
These types are shared between safety (which performs rollbacks) and
observability (which logs rollback events).
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


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
