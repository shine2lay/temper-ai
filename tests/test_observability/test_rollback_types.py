"""Tests for src/observability/rollback_types.py."""

from datetime import UTC, datetime, timedelta

import pytest

from temper_ai.observability.rollback_types import (
    RollbackResult,
    RollbackSnapshot,
    RollbackStatus,
)


class TestRollbackStatus:
    """Tests for RollbackStatus enum."""

    def test_rollback_status_values(self):
        """Test that RollbackStatus has the expected values."""
        assert RollbackStatus.PENDING.value == "pending"
        assert RollbackStatus.IN_PROGRESS.value == "in_progress"
        assert RollbackStatus.COMPLETED.value == "completed"
        assert RollbackStatus.FAILED.value == "failed"
        assert RollbackStatus.PARTIAL.value == "partial"

    def test_rollback_status_is_enum(self):
        """Test that RollbackStatus is an enum."""
        from enum import Enum

        assert issubclass(RollbackStatus, Enum)

    def test_rollback_status_all_members(self):
        """Test that RollbackStatus has exactly 5 members."""
        members = list(RollbackStatus)
        assert len(members) == 5
        assert RollbackStatus.PENDING in members
        assert RollbackStatus.IN_PROGRESS in members
        assert RollbackStatus.COMPLETED in members
        assert RollbackStatus.FAILED in members
        assert RollbackStatus.PARTIAL in members

    def test_rollback_status_from_string(self):
        """Test that RollbackStatus can be created from string."""
        assert RollbackStatus("pending") == RollbackStatus.PENDING
        assert RollbackStatus("in_progress") == RollbackStatus.IN_PROGRESS
        assert RollbackStatus("completed") == RollbackStatus.COMPLETED
        assert RollbackStatus("failed") == RollbackStatus.FAILED
        assert RollbackStatus("partial") == RollbackStatus.PARTIAL

    def test_rollback_status_invalid_value(self):
        """Test that invalid values raise ValueError."""
        with pytest.raises(ValueError):
            RollbackStatus("invalid")


class TestRollbackSnapshot:
    """Tests for RollbackSnapshot dataclass."""

    def test_rollback_snapshot_default_creation(self):
        """Test that RollbackSnapshot can be created with defaults."""
        snapshot = RollbackSnapshot()

        # Check that defaults are set
        assert snapshot.id is not None
        assert isinstance(snapshot.id, str)
        assert snapshot.action == {}
        assert snapshot.context == {}
        assert snapshot.file_snapshots == {}
        assert snapshot.state_snapshots == {}
        assert snapshot.metadata == {}
        assert snapshot.expires_at is None
        assert isinstance(snapshot.created_at, datetime)

    def test_rollback_snapshot_with_data(self):
        """Test creating RollbackSnapshot with data."""
        action = {"type": "file_write", "path": "/tmp/test.txt"}
        context = {"user": "test_user", "workflow": "test_workflow"}
        file_snapshots = {"/tmp/test.txt": "original content"}
        state_snapshots = {"counter": 42}
        metadata = {"note": "test snapshot"}

        snapshot = RollbackSnapshot(
            action=action,
            context=context,
            file_snapshots=file_snapshots,
            state_snapshots=state_snapshots,
            metadata=metadata,
        )

        assert snapshot.action == action
        assert snapshot.context == context
        assert snapshot.file_snapshots == file_snapshots
        assert snapshot.state_snapshots == state_snapshots
        assert snapshot.metadata == metadata

    def test_rollback_snapshot_unique_ids(self):
        """Test that each snapshot gets a unique ID."""
        snapshot1 = RollbackSnapshot()
        snapshot2 = RollbackSnapshot()

        assert snapshot1.id != snapshot2.id

    def test_rollback_snapshot_created_at_is_utc(self):
        """Test that created_at uses UTC timezone."""
        snapshot = RollbackSnapshot()

        assert snapshot.created_at.tzinfo == UTC

    def test_rollback_snapshot_expires_at_optional(self):
        """Test that expires_at is optional."""
        snapshot = RollbackSnapshot()
        assert snapshot.expires_at is None

        expires = datetime.now(UTC) + timedelta(hours=1)
        snapshot_with_expiry = RollbackSnapshot(expires_at=expires)
        assert snapshot_with_expiry.expires_at == expires

    def test_rollback_snapshot_to_dict(self):
        """Test converting RollbackSnapshot to dictionary."""
        action = {"type": "file_write"}
        context = {"user": "test"}
        file_snapshots = {"/tmp/test.txt": "content"}
        state_snapshots = {"key": "value"}
        metadata = {"note": "test"}

        snapshot = RollbackSnapshot(
            action=action,
            context=context,
            file_snapshots=file_snapshots,
            state_snapshots=state_snapshots,
            metadata=metadata,
        )

        result = snapshot.to_dict()

        assert isinstance(result, dict)
        assert result["id"] == snapshot.id
        assert result["action"] == action
        assert result["context"] == context
        assert result["file_snapshots"] == file_snapshots
        assert result["state_snapshots"] == state_snapshots
        assert result["metadata"] == metadata
        assert result["created_at"] == snapshot.created_at.isoformat()
        assert result["expires_at"] is None

    def test_rollback_snapshot_to_dict_with_expires_at(self):
        """Test to_dict with expires_at set."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        snapshot = RollbackSnapshot(expires_at=expires)

        result = snapshot.to_dict()

        assert result["expires_at"] == expires.isoformat()

    def test_rollback_snapshot_mutable_defaults_not_shared(self):
        """Test that mutable default fields are not shared between instances."""
        snapshot1 = RollbackSnapshot()
        snapshot2 = RollbackSnapshot()

        # Modify snapshot1's action
        snapshot1.action["key"] = "value"

        # snapshot2's action should not be affected
        assert "key" not in snapshot2.action
        assert snapshot1.action is not snapshot2.action


class TestRollbackResult:
    """Tests for RollbackResult dataclass."""

    def test_rollback_result_creation(self):
        """Test creating RollbackResult with required fields."""
        result = RollbackResult(
            success=True,
            snapshot_id="test-snapshot-123",
            status=RollbackStatus.COMPLETED,
        )

        assert result.success is True
        assert result.snapshot_id == "test-snapshot-123"
        assert result.status == RollbackStatus.COMPLETED
        assert result.reverted_items == []
        assert result.failed_items == []
        assert result.errors == []
        assert result.metadata == {}
        assert isinstance(result.completed_at, datetime)

    def test_rollback_result_with_all_fields(self):
        """Test creating RollbackResult with all fields."""
        reverted = ["/tmp/file1.txt", "/tmp/file2.txt"]
        failed = ["/tmp/file3.txt"]
        errors = ["Permission denied"]
        metadata = {"duration_ms": 123.45}

        result = RollbackResult(
            success=False,
            snapshot_id="test-snapshot-456",
            status=RollbackStatus.PARTIAL,
            reverted_items=reverted,
            failed_items=failed,
            errors=errors,
            metadata=metadata,
        )

        assert result.success is False
        assert result.snapshot_id == "test-snapshot-456"
        assert result.status == RollbackStatus.PARTIAL
        assert result.reverted_items == reverted
        assert result.failed_items == failed
        assert result.errors == errors
        assert result.metadata == metadata

    def test_rollback_result_completed_at_is_utc(self):
        """Test that completed_at uses UTC timezone."""
        result = RollbackResult(
            success=True, snapshot_id="test-123", status=RollbackStatus.COMPLETED
        )

        assert result.completed_at.tzinfo == UTC

    def test_rollback_result_to_dict(self):
        """Test converting RollbackResult to dictionary."""
        reverted = ["/tmp/file1.txt"]
        failed = ["/tmp/file2.txt"]
        errors = ["Error message"]
        metadata = {"note": "test"}

        result = RollbackResult(
            success=False,
            snapshot_id="test-789",
            status=RollbackStatus.FAILED,
            reverted_items=reverted,
            failed_items=failed,
            errors=errors,
            metadata=metadata,
        )

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["success"] is False
        assert result_dict["snapshot_id"] == "test-789"
        assert result_dict["status"] == "failed"  # Enum value
        assert result_dict["reverted_items"] == reverted
        assert result_dict["failed_items"] == failed
        assert result_dict["errors"] == errors
        assert result_dict["metadata"] == metadata
        assert result_dict["completed_at"] == result.completed_at.isoformat()

    def test_rollback_result_status_serialization(self):
        """Test that status enum is serialized as string."""
        result = RollbackResult(
            success=True, snapshot_id="test-123", status=RollbackStatus.COMPLETED
        )

        result_dict = result.to_dict()

        assert result_dict["status"] == "completed"
        assert isinstance(result_dict["status"], str)

    def test_rollback_result_mutable_defaults_not_shared(self):
        """Test that mutable default fields are not shared between instances."""
        result1 = RollbackResult(
            success=True, snapshot_id="test-1", status=RollbackStatus.COMPLETED
        )
        result2 = RollbackResult(
            success=True, snapshot_id="test-2", status=RollbackStatus.COMPLETED
        )

        # Modify result1's lists
        result1.reverted_items.append("/tmp/file.txt")
        result1.failed_items.append("/tmp/failed.txt")
        result1.errors.append("error")
        result1.metadata["key"] = "value"

        # result2's lists should not be affected
        assert "/tmp/file.txt" not in result2.reverted_items
        assert "/tmp/failed.txt" not in result2.failed_items
        assert "error" not in result2.errors
        assert "key" not in result2.metadata

    def test_rollback_result_success_matches_status(self):
        """Test creating results with matching success and status."""
        # Success case
        success_result = RollbackResult(
            success=True, snapshot_id="test-123", status=RollbackStatus.COMPLETED
        )
        assert success_result.success is True
        assert success_result.status == RollbackStatus.COMPLETED

        # Failure case
        failure_result = RollbackResult(
            success=False, snapshot_id="test-456", status=RollbackStatus.FAILED
        )
        assert failure_result.success is False
        assert failure_result.status == RollbackStatus.FAILED

        # Partial case
        partial_result = RollbackResult(
            success=False, snapshot_id="test-789", status=RollbackStatus.PARTIAL
        )
        assert partial_result.success is False
        assert partial_result.status == RollbackStatus.PARTIAL


class TestRollbackTypesIntegration:
    """Integration tests for rollback types."""

    def test_snapshot_and_result_workflow(self):
        """Test typical workflow of creating snapshot and result."""
        # Create a snapshot before an action
        snapshot = RollbackSnapshot(
            action={"type": "file_write", "path": "/tmp/test.txt"},
            context={"workflow": "test"},
            file_snapshots={"/tmp/test.txt": "original"},
        )

        # Perform rollback and create result
        result = RollbackResult(
            success=True,
            snapshot_id=snapshot.id,
            status=RollbackStatus.COMPLETED,
            reverted_items=["/tmp/test.txt"],
        )

        # Verify they are linked
        assert result.snapshot_id == snapshot.id
        assert result.success is True

    def test_serialization_round_trip(self):
        """Test that serialization preserves data."""
        snapshot = RollbackSnapshot(
            action={"type": "test"},
            context={"key": "value"},
            file_snapshots={"file": "content"},
        )

        snapshot_dict = snapshot.to_dict()

        # Verify essential data is preserved
        assert snapshot_dict["id"] == snapshot.id
        assert snapshot_dict["action"] == snapshot.action
        assert snapshot_dict["context"] == snapshot.context

    def test_result_serialization_round_trip(self):
        """Test that result serialization preserves data."""
        result = RollbackResult(
            success=True,
            snapshot_id="test-123",
            status=RollbackStatus.COMPLETED,
            reverted_items=["file1", "file2"],
            metadata={"duration": 123},
        )

        result_dict = result.to_dict()

        # Verify data is preserved
        assert result_dict["success"] == result.success
        assert result_dict["snapshot_id"] == result.snapshot_id
        assert result_dict["status"] == result.status.value
        assert result_dict["reverted_items"] == result.reverted_items
