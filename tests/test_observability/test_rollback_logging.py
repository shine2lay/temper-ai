"""Tests for rollback observability logging.

Tests the database logging of rollback snapshots and events for audit trail.
"""
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.observability.models import RollbackEvent, RollbackSnapshotDB
from src.observability.rollback_logger import (
    get_rollback_events,
    get_rollback_snapshots,
    log_rollback_event,
    log_rollback_snapshot,
)
from src.safety.rollback import RollbackResult, RollbackSnapshot, RollbackStatus


class TestRollbackLogging:
    """Test suite for rollback observability logging."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager."""
        mock_manager = Mock()
        mock_session = MagicMock()
        mock_manager.session.return_value.__enter__.return_value = mock_session
        mock_manager.session.return_value.__exit__.return_value = None
        return mock_manager, mock_session

    @pytest.fixture
    def sample_snapshot(self):
        """Create sample rollback snapshot."""
        return RollbackSnapshot(
            id="snap-123",
            action={"tool": "write_file", "path": "/tmp/test.txt"},
            context={"workflow_id": "wf-1", "agent_id": "agent-1"},
            file_snapshots={"/tmp/test.txt": "original content"},
            state_snapshots={},
            metadata={},
            created_at=datetime.now(UTC)
        )

    @pytest.fixture
    def sample_result(self):
        """Create sample rollback result."""
        return RollbackResult(
            success=True,
            snapshot_id="snap-123",
            status=RollbackStatus.COMPLETED,
            reverted_items=["/tmp/test.txt"],
            failed_items=[],
            errors=[],
            metadata={"operator": "test-user", "reason": "Test rollback"},
            completed_at=datetime.now(UTC)
        )

    def test_log_rollback_snapshot(self, mock_db_manager, sample_snapshot):
        """Test logging rollback snapshot to database."""
        db_manager, mock_session = mock_db_manager

        log_rollback_snapshot(
            snapshot=sample_snapshot,
            workflow_execution_id="wf-exec-1",
            checkpoint_id="checkpoint-1",
            db_manager=db_manager
        )

        # Verify session.add was called
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]

        assert isinstance(added_obj, RollbackSnapshotDB)
        assert added_obj.id == sample_snapshot.id
        assert added_obj.workflow_execution_id == "wf-exec-1"
        assert added_obj.checkpoint_id == "checkpoint-1"
        assert added_obj.action == sample_snapshot.action
        assert added_obj.context == sample_snapshot.context

        # Verify commit was called
        mock_session.commit.assert_called_once()

    def test_log_rollback_event(self, mock_db_manager, sample_result):
        """Test logging rollback event to database."""
        db_manager, mock_session = mock_db_manager

        log_rollback_event(
            result=sample_result,
            trigger="manual",
            operator="test-user",
            reason="Manual recovery",
            db_manager=db_manager
        )

        # Verify session.add was called
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]

        assert isinstance(added_obj, RollbackEvent)
        assert added_obj.snapshot_id == sample_result.snapshot_id
        assert added_obj.status == sample_result.status.value
        assert added_obj.trigger == "manual"
        assert added_obj.operator == "test-user"
        assert added_obj.reason == "Manual recovery"
        assert added_obj.reverted_items == sample_result.reverted_items
        assert added_obj.failed_items == sample_result.failed_items
        assert added_obj.errors == sample_result.errors

        # Verify commit was called
        mock_session.commit.assert_called_once()

    def test_log_rollback_event_auto_trigger(self, mock_db_manager, sample_result):
        """Test logging auto-triggered rollback event."""
        db_manager, mock_session = mock_db_manager

        log_rollback_event(
            result=sample_result,
            trigger="auto",
            operator="agent-1",
            db_manager=db_manager
        )

        added_obj = mock_session.add.call_args[0][0]

        assert added_obj.trigger == "auto"
        assert added_obj.operator == "agent-1"

    def test_log_rollback_event_approval_rejection(self, mock_db_manager, sample_result):
        """Test logging approval rejection rollback."""
        db_manager, mock_session = mock_db_manager

        log_rollback_event(
            result=sample_result,
            trigger="approval_rejection",
            reason="Approval denied by user",
            db_manager=db_manager
        )

        added_obj = mock_session.add.call_args[0][0]

        assert added_obj.trigger == "approval_rejection"
        assert added_obj.reason == "Approval denied by user"

    def test_log_rollback_event_with_failures(self, mock_db_manager):
        """Test logging rollback event with failed items."""
        db_manager, mock_session = mock_db_manager

        result = RollbackResult(
            success=False,
            snapshot_id="snap-456",
            status=RollbackStatus.PARTIAL,
            reverted_items=["/tmp/file1.txt"],
            failed_items=["/tmp/file2.txt", "/tmp/file3.txt"],
            errors=["Error 1", "Error 2"],
            metadata={},
            completed_at=datetime.now(UTC)
        )

        log_rollback_event(
            result=result,
            trigger="auto",
            db_manager=db_manager
        )

        added_obj = mock_session.add.call_args[0][0]

        assert added_obj.status == RollbackStatus.PARTIAL.value
        assert len(added_obj.failed_items) == 2
        assert len(added_obj.errors) == 2

    @patch('src.observability.rollback_logger.DatabaseManager')
    def test_log_rollback_snapshot_creates_db_manager(self, mock_db_class, sample_snapshot):
        """Test that DatabaseManager is created if not provided."""
        mock_db_instance = Mock()
        mock_session = MagicMock()
        mock_db_instance.session.return_value.__enter__.return_value = mock_session
        mock_db_instance.session.return_value.__exit__.return_value = None
        mock_db_class.return_value = mock_db_instance

        log_rollback_snapshot(
            snapshot=sample_snapshot,
            db_manager=None  # Should create new instance
        )

        # Verify DatabaseManager was instantiated
        mock_db_class.assert_called_once()

        # Verify add and commit were called
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @patch('src.observability.rollback_logger.DatabaseManager')
    def test_log_rollback_event_error_handling(self, mock_db_class, sample_result):
        """Test error handling in log_rollback_event."""
        # Setup mock to raise exception
        mock_db_instance = Mock()
        mock_session = MagicMock()
        mock_session.add.side_effect = Exception("Database error")
        mock_db_instance.session.return_value.__enter__.return_value = mock_session
        mock_db_instance.session.return_value.__exit__.return_value = None
        mock_db_class.return_value = mock_db_instance

        # Should not raise exception (error is logged)
        log_rollback_event(
            result=sample_result,
            trigger="auto",
            db_manager=None
        )

        # Verify add was attempted
        mock_session.add.assert_called_once()

    def test_get_rollback_events_no_filter(self, mock_db_manager):
        """Test querying rollback events without filters."""
        db_manager, mock_session = mock_db_manager

        # Mock query results
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_session.query.return_value = mock_query

        events = get_rollback_events(db_manager=db_manager)

        # Verify query was executed
        mock_session.query.assert_called_once_with(RollbackEvent)
        mock_query.order_by.assert_called_once()
        mock_query.limit.assert_called_once_with(100)

    def test_get_rollback_events_filter_by_snapshot(self, mock_db_manager):
        """Test querying rollback events filtered by snapshot ID."""
        db_manager, mock_session = mock_db_manager

        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_session.query.return_value = mock_query

        events = get_rollback_events(
            snapshot_id="snap-123",
            db_manager=db_manager
        )

        # Verify filter was applied
        mock_query.filter.assert_called_once()

    def test_get_rollback_events_filter_by_trigger(self, mock_db_manager):
        """Test querying rollback events filtered by trigger type."""
        db_manager, mock_session = mock_db_manager

        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_session.query.return_value = mock_query

        events = get_rollback_events(
            trigger="manual",
            db_manager=db_manager
        )

        # Verify filter was applied
        mock_query.filter.assert_called_once()

    def test_get_rollback_snapshots_no_filter(self, mock_db_manager):
        """Test querying rollback snapshots without filters."""
        db_manager, mock_session = mock_db_manager

        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_session.query.return_value = mock_query

        snapshots = get_rollback_snapshots(db_manager=db_manager)

        # Verify query was executed
        mock_session.query.assert_called_once_with(RollbackSnapshotDB)
        mock_query.order_by.assert_called_once()
        mock_query.limit.assert_called_once_with(100)

    def test_get_rollback_snapshots_filter_by_workflow(self, mock_db_manager):
        """Test querying snapshots filtered by workflow execution ID."""
        db_manager, mock_session = mock_db_manager

        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_session.query.return_value = mock_query

        snapshots = get_rollback_snapshots(
            workflow_execution_id="wf-exec-1",
            db_manager=db_manager
        )

        # Verify filter was applied
        mock_query.filter.assert_called_once()
