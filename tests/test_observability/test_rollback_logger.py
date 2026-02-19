"""Comprehensive tests for rollback logger module."""
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from temper_ai.storage.database import DatabaseManager
from temper_ai.storage.database.models import RollbackEvent, RollbackSnapshotDB
from temper_ai.observability.rollback_logger import (
    get_rollback_events,
    get_rollback_snapshots,
    log_rollback_event,
    log_rollback_snapshot,
)
from temper_ai.observability.rollback_types import (
    RollbackResult,
    RollbackSnapshot,
    RollbackStatus,
)


@pytest.fixture
def db_manager():
    """Create in-memory database manager for tests."""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    from sqlmodel import SQLModel

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    @contextmanager
    def get_session():
        """Get session context manager."""
        session = Session(bind=engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    manager = Mock(spec=DatabaseManager)
    manager.session = get_session

    yield manager


@pytest.fixture
def rollback_snapshot():
    """Create sample rollback snapshot."""
    return RollbackSnapshot(
        id=str(uuid4()),
        action={"type": "file_write", "path": "/test/file.py"},
        context={"workflow_id": "wf-123", "agent_id": "agent-456"},
        created_at=datetime.now(UTC),
        file_snapshots={"/test/file.py": "original content"},
        state_snapshots={"counter": 42},
        metadata={"reason": "test"},
        expires_at=datetime.now(UTC) + timedelta(hours=24)
    )


@pytest.fixture
def rollback_result(rollback_snapshot):
    """Create sample rollback result."""
    return RollbackResult(
        success=True,
        snapshot_id=rollback_snapshot.id,
        status=RollbackStatus.COMPLETED,
        reverted_items=["/test/file.py"],
        failed_items=[],
        errors=[],
        metadata={"operator": "test-agent"},
        completed_at=datetime.now(UTC)
    )


class TestLogRollbackSnapshot:
    """Test logging rollback snapshots."""

    def test_log_basic_snapshot(self, db_manager, rollback_snapshot):
        """Test logging basic snapshot."""
        log_rollback_snapshot(rollback_snapshot, db_manager=db_manager)

        with db_manager.session() as session:
            snapshot = session.query(RollbackSnapshotDB).filter_by(
                id=rollback_snapshot.id
            ).first()

            assert snapshot is not None
            assert snapshot.id == rollback_snapshot.id
            assert snapshot.action == rollback_snapshot.action
            assert snapshot.context == rollback_snapshot.context

    def test_log_snapshot_with_workflow_id(self, db_manager, rollback_snapshot):
        """Test logging snapshot with workflow_execution_id."""
        workflow_id = "wf-999"

        log_rollback_snapshot(
            rollback_snapshot,
            workflow_execution_id=workflow_id,
            db_manager=db_manager
        )

        with db_manager.session() as session:
            snapshot = session.query(RollbackSnapshotDB).filter_by(
                id=rollback_snapshot.id
            ).first()

            assert snapshot.workflow_execution_id == workflow_id

    def test_log_snapshot_with_checkpoint_id(self, db_manager, rollback_snapshot):
        """Test logging snapshot with checkpoint_id."""
        checkpoint_id = "ckpt-123"

        log_rollback_snapshot(
            rollback_snapshot,
            checkpoint_id=checkpoint_id,
            db_manager=db_manager
        )

        with db_manager.session() as session:
            snapshot = session.query(RollbackSnapshotDB).filter_by(
                id=rollback_snapshot.id
            ).first()

            assert snapshot.checkpoint_id == checkpoint_id

    def test_log_snapshot_file_snapshots(self, db_manager, rollback_snapshot):
        """Test snapshot file_snapshots are stored."""
        log_rollback_snapshot(rollback_snapshot, db_manager=db_manager)

        with db_manager.session() as session:
            snapshot = session.query(RollbackSnapshotDB).filter_by(
                id=rollback_snapshot.id
            ).first()

            assert snapshot.file_snapshots == {"/test/file.py": "original content"}

    def test_log_snapshot_state_snapshots(self, db_manager, rollback_snapshot):
        """Test snapshot state_snapshots are stored."""
        log_rollback_snapshot(rollback_snapshot, db_manager=db_manager)

        with db_manager.session() as session:
            snapshot = session.query(RollbackSnapshotDB).filter_by(
                id=rollback_snapshot.id
            ).first()

            assert snapshot.state_snapshots == {"counter": 42}

    def test_log_snapshot_timestamps(self, db_manager, rollback_snapshot):
        """Test snapshot timestamps are preserved."""
        log_rollback_snapshot(rollback_snapshot, db_manager=db_manager)

        with db_manager.session() as session:
            snapshot = session.query(RollbackSnapshotDB).filter_by(
                id=rollback_snapshot.id
            ).first()

            assert snapshot.created_at is not None
            assert snapshot.expires_at is not None

    @patch('temper_ai.observability.rollback_logger.get_database')
    def test_log_snapshot_uses_singleton_db(self, mock_get_db, rollback_snapshot):
        """Test logging uses singleton database when db_manager is None."""
        mock_db = Mock(spec=DatabaseManager)
        mock_session = Mock()
        mock_db.session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db.session.return_value.__exit__ = Mock(return_value=None)
        mock_get_db.return_value = mock_db

        log_rollback_snapshot(rollback_snapshot)

        mock_get_db.assert_called_once()
        mock_db.session.assert_called_once()

    def test_log_snapshot_error_handling(self, db_manager, rollback_snapshot, caplog):
        """Test error handling when logging fails."""
        # Make session.add raise an error
        with patch.object(db_manager, 'session') as mock_session_ctx:
            mock_session = Mock()
            mock_session.add.side_effect = Exception("Database error")
            mock_session_ctx.return_value.__enter__ = Mock(return_value=mock_session)
            mock_session_ctx.return_value.__exit__ = Mock(return_value=None)

            log_rollback_snapshot(rollback_snapshot, db_manager=db_manager)

            assert any("Failed to log rollback snapshot" in rec.message for rec in caplog.records)


class TestLogRollbackEvent:
    """Test logging rollback events."""

    def test_log_basic_event(self, db_manager, rollback_result):
        """Test logging basic rollback event."""
        log_rollback_event(
            result=rollback_result,
            trigger="auto",
            db_manager=db_manager
        )

        with db_manager.session() as session:
            event = session.query(RollbackEvent).filter_by(
                snapshot_id=rollback_result.snapshot_id
            ).first()

            assert event is not None
            assert event.snapshot_id == rollback_result.snapshot_id
            assert event.status == rollback_result.status.value
            assert event.trigger == "auto"

    def test_log_event_with_operator(self, db_manager, rollback_result):
        """Test logging event with operator."""
        log_rollback_event(
            result=rollback_result,
            trigger="manual",
            operator="admin-user",
            db_manager=db_manager
        )

        with db_manager.session() as session:
            event = session.query(RollbackEvent).filter_by(
                snapshot_id=rollback_result.snapshot_id
            ).first()

            assert event.operator == "admin-user"
            assert event.trigger == "manual"

    def test_log_event_with_reason(self, db_manager, rollback_result):
        """Test logging event with reason."""
        log_rollback_event(
            result=rollback_result,
            trigger="manual",
            reason="User requested rollback due to error",
            db_manager=db_manager
        )

        with db_manager.session() as session:
            event = session.query(RollbackEvent).filter_by(
                snapshot_id=rollback_result.snapshot_id
            ).first()

            assert event.reason == "User requested rollback due to error"

    def test_log_event_reverted_items(self, db_manager, rollback_result):
        """Test event stores reverted items."""
        log_rollback_event(
            result=rollback_result,
            trigger="auto",
            db_manager=db_manager
        )

        with db_manager.session() as session:
            event = session.query(RollbackEvent).filter_by(
                snapshot_id=rollback_result.snapshot_id
            ).first()

            assert event.reverted_items == ["/test/file.py"]

    def test_log_event_failed_items(self, db_manager, rollback_result):
        """Test event stores failed items."""
        rollback_result.failed_items = ["/test/other.py"]
        rollback_result.errors = ["Permission denied"]

        log_rollback_event(
            result=rollback_result,
            trigger="auto",
            db_manager=db_manager
        )

        with db_manager.session() as session:
            event = session.query(RollbackEvent).filter_by(
                snapshot_id=rollback_result.snapshot_id
            ).first()

            assert event.failed_items == ["/test/other.py"]
            assert event.errors == ["Permission denied"]

    def test_log_event_metadata(self, db_manager, rollback_result):
        """Test event stores metadata."""
        log_rollback_event(
            result=rollback_result,
            trigger="auto",
            db_manager=db_manager
        )

        with db_manager.session() as session:
            event = session.query(RollbackEvent).filter_by(
                snapshot_id=rollback_result.snapshot_id
            ).first()

            assert event.rollback_metadata == {"operator": "test-agent"}

    def test_log_event_different_triggers(self, db_manager, rollback_result):
        """Test logging events with different triggers."""
        triggers = ["auto", "manual", "approval_rejection"]

        for trigger in triggers:
            result = RollbackResult(
                success=True,
                snapshot_id=str(uuid4()),
                status=RollbackStatus.COMPLETED
            )

            log_rollback_event(
                result=result,
                trigger=trigger,
                db_manager=db_manager
            )

            with db_manager.session() as session:
                event = session.query(RollbackEvent).filter_by(
                    snapshot_id=result.snapshot_id
                ).first()

                assert event.trigger == trigger

    @patch('temper_ai.observability.rollback_logger.get_database')
    def test_log_event_uses_singleton_db(self, mock_get_db, rollback_result):
        """Test logging uses singleton database when db_manager is None."""
        mock_db = Mock(spec=DatabaseManager)
        mock_session = Mock()
        mock_db.session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db.session.return_value.__exit__ = Mock(return_value=None)
        mock_get_db.return_value = mock_db

        log_rollback_event(result=rollback_result, trigger="auto")

        mock_get_db.assert_called_once()

    def test_log_event_error_handling(self, db_manager, rollback_result, caplog):
        """Test error handling when logging event fails."""
        with patch.object(db_manager, 'session') as mock_session_ctx:
            mock_session = Mock()
            mock_session.add.side_effect = Exception("Database error")
            mock_session_ctx.return_value.__enter__ = Mock(return_value=mock_session)
            mock_session_ctx.return_value.__exit__ = Mock(return_value=None)

            log_rollback_event(
                result=rollback_result,
                trigger="auto",
                db_manager=db_manager
            )

            assert any("Failed to log rollback event" in rec.message for rec in caplog.records)


class TestGetRollbackEvents:
    """Test querying rollback events."""

    def test_get_all_events(self, db_manager, rollback_result):
        """Test getting all rollback events."""
        # Log some events
        log_rollback_event(rollback_result, "auto", db_manager=db_manager)

        result2 = RollbackResult(
            success=True,
            snapshot_id=str(uuid4()),
            status=RollbackStatus.COMPLETED
        )
        log_rollback_event(result2, "manual", db_manager=db_manager)

        events = get_rollback_events(db_manager=db_manager)

        assert len(events) == 2

    def test_get_events_by_snapshot_id(self, db_manager, rollback_result):
        """Test filtering events by snapshot_id."""
        log_rollback_event(rollback_result, "auto", db_manager=db_manager)

        result2 = RollbackResult(
            success=True,
            snapshot_id=str(uuid4()),
            status=RollbackStatus.COMPLETED
        )
        log_rollback_event(result2, "manual", db_manager=db_manager)

        # Access within session context
        with db_manager.session() as session:
            from temper_ai.storage.database.models import RollbackEvent
            events_query = session.query(RollbackEvent).filter_by(
                snapshot_id=rollback_result.snapshot_id
            ).all()

            assert len(events_query) == 1
            assert events_query[0].snapshot_id == rollback_result.snapshot_id

    def test_get_events_by_trigger(self, db_manager, rollback_result):
        """Test filtering events by trigger."""
        log_rollback_event(rollback_result, "auto", db_manager=db_manager)

        result2 = RollbackResult(
            success=True,
            snapshot_id=str(uuid4()),
            status=RollbackStatus.COMPLETED
        )
        log_rollback_event(result2, "manual", db_manager=db_manager)

        # Access within session context
        with db_manager.session() as session:
            from temper_ai.storage.database.models import RollbackEvent
            events_query = session.query(RollbackEvent).filter_by(
                trigger="manual"
            ).all()

            assert len(events_query) == 1
            assert events_query[0].trigger == "manual"

    def test_get_events_with_limit(self, db_manager):
        """Test limiting number of results."""
        # Create multiple events
        for _ in range(5):
            result = RollbackResult(
                success=True,
                snapshot_id=str(uuid4()),
                status=RollbackStatus.COMPLETED
            )
            log_rollback_event(result, "auto", db_manager=db_manager)

        events = get_rollback_events(limit=3, db_manager=db_manager)

        assert len(events) == 3

    def test_get_events_ordered_by_execution_time(self, db_manager):
        """Test events are ordered by execution time (newest first)."""
        for i in range(3):
            result = RollbackResult(
                success=True,
                snapshot_id=str(uuid4()),
                status=RollbackStatus.COMPLETED,
                completed_at=datetime.now(UTC) + timedelta(seconds=i)
            )
            log_rollback_event(result, "auto", db_manager=db_manager)

        # Access within session context
        with db_manager.session() as session:
            from temper_ai.storage.database.models import RollbackEvent
            events_query = session.query(RollbackEvent).order_by(
                RollbackEvent.executed_at.desc()
            ).all()

            # Should be in descending order (newest first)
            assert len(events_query) == 3
            for i in range(len(events_query) - 1):
                assert events_query[i].executed_at >= events_query[i + 1].executed_at

    def test_get_events_error_handling(self, db_manager, caplog):
        """Test error handling when query fails."""
        with patch.object(db_manager, 'session') as mock_session_ctx:
            mock_session = Mock()
            mock_session.query.side_effect = Exception("Query error")
            mock_session_ctx.return_value.__enter__ = Mock(return_value=mock_session)
            mock_session_ctx.return_value.__exit__ = Mock(return_value=None)

            events = get_rollback_events(db_manager=db_manager)

            assert events == []
            assert any("Failed to query rollback events" in rec.message for rec in caplog.records)


class TestGetRollbackSnapshots:
    """Test querying rollback snapshots."""

    def test_get_all_snapshots(self, db_manager, rollback_snapshot):
        """Test getting all snapshots."""
        log_rollback_snapshot(rollback_snapshot, db_manager=db_manager)

        snapshot2 = RollbackSnapshot(
            id=str(uuid4()),
            action={"type": "state_change"},
            context={"workflow_id": "wf-999"}
        )
        log_rollback_snapshot(snapshot2, db_manager=db_manager)

        snapshots = get_rollback_snapshots(db_manager=db_manager)

        assert len(snapshots) == 2

    def test_get_snapshots_by_workflow_id(self, db_manager, rollback_snapshot):
        """Test filtering snapshots by workflow_execution_id."""
        workflow_id = "wf-specific"

        log_rollback_snapshot(
            rollback_snapshot,
            workflow_execution_id=workflow_id,
            db_manager=db_manager
        )

        snapshot2 = RollbackSnapshot()
        log_rollback_snapshot(
            snapshot2,
            workflow_execution_id="wf-other",
            db_manager=db_manager
        )

        # Access within session context
        with db_manager.session() as session:
            from temper_ai.storage.database.models import RollbackSnapshotDB
            snapshots_query = session.query(RollbackSnapshotDB).filter_by(
                workflow_execution_id=workflow_id
            ).all()

            assert len(snapshots_query) == 1
            assert snapshots_query[0].workflow_execution_id == workflow_id

    def test_get_snapshots_with_limit(self, db_manager):
        """Test limiting number of results."""
        for _ in range(5):
            snapshot = RollbackSnapshot()
            log_rollback_snapshot(snapshot, db_manager=db_manager)

        snapshots = get_rollback_snapshots(limit=3, db_manager=db_manager)

        assert len(snapshots) == 3

    def test_get_snapshots_ordered_by_creation_time(self, db_manager):
        """Test snapshots are ordered by creation time (newest first)."""
        for i in range(3):
            snapshot = RollbackSnapshot(
                created_at=datetime.now(UTC) + timedelta(seconds=i)
            )
            log_rollback_snapshot(snapshot, db_manager=db_manager)

        # Access within session context
        with db_manager.session() as session:
            from temper_ai.storage.database.models import RollbackSnapshotDB
            snapshots_query = session.query(RollbackSnapshotDB).order_by(
                RollbackSnapshotDB.created_at.desc()
            ).all()

            assert len(snapshots_query) == 3
            for i in range(len(snapshots_query) - 1):
                assert snapshots_query[i].created_at >= snapshots_query[i + 1].created_at

    def test_get_snapshots_error_handling(self, db_manager, caplog):
        """Test error handling when query fails."""
        with patch.object(db_manager, 'session') as mock_session_ctx:
            mock_session = Mock()
            mock_session.query.side_effect = Exception("Query error")
            mock_session_ctx.return_value.__enter__ = Mock(return_value=mock_session)
            mock_session_ctx.return_value.__exit__ = Mock(return_value=None)

            snapshots = get_rollback_snapshots(db_manager=db_manager)

            assert snapshots == []
            assert any("Failed to query rollback snapshots" in rec.message for rec in caplog.records)


class TestIntegration:
    """Integration tests combining snapshots and events."""

    def test_snapshot_and_event_lifecycle(self, db_manager, rollback_snapshot, rollback_result):
        """Test complete lifecycle: snapshot -> event -> query."""
        # Log snapshot
        log_rollback_snapshot(
            rollback_snapshot,
            workflow_execution_id="wf-123",
            db_manager=db_manager
        )

        # Log rollback event
        log_rollback_event(
            result=rollback_result,
            trigger="auto",
            operator="system",
            db_manager=db_manager
        )

        # Query both within session context
        with db_manager.session() as session:
            from temper_ai.storage.database.models import RollbackEvent, RollbackSnapshotDB

            snapshots_query = session.query(RollbackSnapshotDB).filter_by(
                workflow_execution_id="wf-123"
            ).all()

            events_query = session.query(RollbackEvent).filter_by(
                snapshot_id=rollback_snapshot.id
            ).all()

            assert len(snapshots_query) == 1
            assert len(events_query) == 1
            assert events_query[0].snapshot_id == snapshots_query[0].id
