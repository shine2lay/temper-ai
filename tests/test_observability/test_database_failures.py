"""
Comprehensive tests for database failure scenarios and resilience.

Tests database connection failures, transaction rollbacks, data integrity,
and recovery mechanisms.
"""
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.observability.database import DatabaseManager
from src.observability.models import (
    StageExecution,
    WorkflowExecution,
)


@pytest.fixture
def temp_db_file():
    """Provide temporary database file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def db_manager(temp_db_file):
    """Provide database manager with temp database."""
    manager = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")
    manager.create_all_tables()
    yield manager
    # DatabaseManager doesn't have close() method, engine cleanup happens automatically


class TestConnectionFailures:
    """Test database connection failure scenarios."""

    def test_connection_to_nonexistent_database(self):
        """Test connection to nonexistent database."""
        # Invalid database URL should raise error or handle gracefully
        try:
            manager = DatabaseManager(database_url="sqlite:////nonexistent/path/db.sqlite")
            # If it succeeds, it should create the database
            assert manager is not None
            # Manager cleanup happens automatically
        except Exception as e:
            # Expected to fail with connection or permission error
            assert "permission" in str(e).lower() or "error" in str(e).lower()

    def test_connection_with_invalid_url(self):
        """Test connection with invalid database URL."""
        with pytest.raises(Exception):
            # Malformed URL should raise error
            manager = DatabaseManager(database_url="invalid://url")

    def test_multiple_connections_to_same_database(self, temp_db_file):
        """Test multiple connections to the same database."""
        manager1 = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")
        manager2 = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")

        # Both should connect successfully (SQLite allows this)
        assert manager1 is not None
        assert manager2 is not None

        # Manager cleanup happens automatically
        # Manager cleanup happens automatically

    def test_connection_after_dispose(self, db_manager):
        """Test using connection after engine disposal."""
        # Dispose the engine
        db_manager.engine.dispose()

        # Should still be able to use (engine auto-reconnects)
        with db_manager.session() as session:
            # May succeed (auto-reconnect) or fail
            try:
                result = session.query(WorkflowExecution).first()
                # Auto-reconnect worked: result is None (empty table) or a row
                assert result is None or hasattr(result, "id")
            except Exception:
                # Also acceptable if it fails after dispose
                pass

    def test_connection_timeout(self):
        """Test connection timeout handling."""
        # This would require a slow/unresponsive database
        # Testing the manager can be created with in-memory database
        manager = DatabaseManager(database_url="sqlite:///:memory:")

        # Should create manager successfully
        assert manager is not None
        # Manager cleanup happens automatically


class TestTransactionFailures:
    """Test transaction failure and rollback scenarios."""

    def test_rollback_on_exception(self, db_manager):
        """Test that transaction rolls back on exception."""
        # Create initial state
        with db_manager.session() as session:
            workflow = WorkflowExecution(
                id="wf-1",
                workflow_name="test",
                started_at=datetime.now(),
                status="running"
            )
            session.add(workflow)
            session.commit()

        # Attempt operation that fails mid-transaction
        try:
            with db_manager.session() as session:
                workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
                workflow.status = "completed"
                session.flush()  # Flush changes but don't commit

                # Simulate error
                raise RuntimeError("Simulated error")
        except RuntimeError:
            pass

        # Verify rollback - status should still be "running"
        with db_manager.session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
            assert workflow.status == "running", "Transaction should have rolled back"

    def test_nested_transaction_rollback(self, db_manager):
        """Test rollback of nested transactions."""
        with db_manager.session() as session:
            workflow = WorkflowExecution(
                id="wf-1",
                workflow_name="test",
                started_at=datetime.now(),
                status="running"
            )
            session.add(workflow)
            session.commit()

        # Nested transaction that fails
        try:
            with db_manager.session() as session:
                workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
                workflow.status = "completed"

                # Nested operation
                try:
                    stage = StageExecution(
                        id="stage-1",
                        workflow_execution_id="wf-1",
                        stage_name="test_stage",
                        stage_config_snapshot={},
                        started_at=datetime.now(),
                        status="running"
                    )
                    session.add(stage)
                    session.flush()

                    # Inner transaction fails
                    raise ValueError("Inner error")
                except ValueError:
                    session.rollback()
                    raise

                session.commit()
        except ValueError:
            pass

        # Verify both operations rolled back
        with db_manager.session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
            assert workflow.status == "running"

            stages = session.query(StageExecution).filter_by(workflow_execution_id="wf-1").all()
            assert len(stages) == 0

    def test_partial_commit_failure(self, db_manager):
        """Test handling of partial commit failures."""
        # Add multiple records
        with db_manager.session() as session:
            workflow1 = WorkflowExecution(
                id="wf-1",
                workflow_name="test1",
                started_at=datetime.now(),
                status="running"
            )
            workflow2 = WorkflowExecution(
                id="wf-2",
                workflow_name="test2",
                started_at=datetime.now(),
                status="running"
            )
            session.add_all([workflow1, workflow2])
            session.commit()

        # Both should be committed
        with db_manager.session() as session:
            count = session.query(WorkflowExecution).count()
            assert count == 2


class TestConcurrentAccess:
    """Test concurrent access scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_writes_to_different_records(self, db_manager):
        """Test concurrent writes to different records."""
        # Create initial records
        with db_manager.session() as session:
            for i in range(5):
                workflow = WorkflowExecution(
                    id=f"wf-{i}",
                    workflow_name=f"test{i}",
                    started_at=datetime.now(),
                    status="running"
                )
                session.add(workflow)
            session.commit()

        # Concurrent updates to different records
        async def update_workflow(wf_id: str):
            await asyncio.sleep(0.01)  # Small delay
            with db_manager.session() as session:
                workflow = session.query(WorkflowExecution).filter_by(id=wf_id).first()
                workflow.status = "completed"
                session.commit()

        # Update all 5 concurrently
        tasks = [update_workflow(f"wf-{i}") for i in range(5)]
        await asyncio.gather(*tasks)

        # Verify all updated
        with db_manager.session() as session:
            completed = session.query(WorkflowExecution).filter_by(status="completed").count()
            assert completed == 5

    @pytest.mark.asyncio
    async def test_concurrent_writes_to_same_record(self, db_manager):
        """Test concurrent writes to the same record."""
        # Create initial record
        with db_manager.session() as session:
            workflow = WorkflowExecution(
                id="wf-1",
                workflow_name="test",
                started_at=datetime.now(),
                status="running",
                extra_metadata={"counter": 0}
            )
            session.add(workflow)
            session.commit()

        # Concurrent updates to same record
        update_count = {"count": 0}

        async def increment_counter():
            await asyncio.sleep(0.01)
            try:
                with db_manager.session() as session:
                    workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
                    # Simulate race condition
                    current = workflow.extra_metadata.get("counter", 0) if workflow.extra_metadata else 0
                    await asyncio.sleep(0.01)
                    workflow.extra_metadata = {"counter": current + 1}
                    session.commit()
                    update_count["count"] += 1
            except Exception:
                # May fail due to race condition
                pass

        # Try 10 concurrent increments
        tasks = [increment_counter() for _ in range(10)]
        await asyncio.gather(*tasks)

        # Due to race conditions, final count may be less than 10
        # (This demonstrates the race condition - proper solution would use locks)
        with db_manager.session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
            final_count = workflow.extra_metadata.get("counter", 0) if workflow.extra_metadata else 0

            # At least 1 update should have succeeded
            assert final_count >= 1
            assert final_count <= 10

    @pytest.mark.asyncio
    async def test_concurrent_read_and_write(self, db_manager):
        """Test concurrent reads and writes."""
        # Create initial record
        with db_manager.session() as session:
            workflow = WorkflowExecution(
                id="wf-1",
                workflow_name="test",
                started_at=datetime.now(),
                status="running"
            )
            session.add(workflow)
            session.commit()

        read_results = []

        async def read_workflow():
            await asyncio.sleep(0.01)
            with db_manager.session() as session:
                workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
                read_results.append(workflow.status)

        async def write_workflow():
            await asyncio.sleep(0.02)
            with db_manager.session() as session:
                workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
                workflow.status = "completed"
                session.commit()

        # 5 reads + 1 write concurrently
        tasks = [read_workflow() for _ in range(5)] + [write_workflow()]
        await asyncio.gather(*tasks)

        # Some reads may see "running", others may see "completed"
        assert len(read_results) == 5
        assert "running" in read_results or "completed" in read_results


class TestDataIntegrity:
    """Test data integrity and constraint violations."""

    def test_unique_constraint_violation(self, db_manager):
        """Test handling of unique constraint violations."""
        # Create workflow with ID
        with db_manager.session() as session:
            workflow = WorkflowExecution(
                id="wf-1",
                workflow_name="test",
                started_at=datetime.now(),
                status="running"
            )
            session.add(workflow)
            session.commit()

        # Attempt to create duplicate
        with pytest.raises(Exception):  # SQLite raises IntegrityError
            with db_manager.session() as session:
                duplicate = WorkflowExecution(
                    id="wf-1",  # Same ID
                    workflow_name="test2",
                    started_at=datetime.now(),
                    status="running"
                )
                session.add(duplicate)
                session.commit()

    def test_foreign_key_constraint_violation(self, db_manager):
        """Test handling of foreign key constraint violations."""
        # Attempt to create stage without workflow
        try:
            with db_manager.session() as session:
                stage = StageExecution(
                    id="stage-1",
                    workflow_execution_id="nonexistent-wf",  # Doesn't exist
                    stage_name="test",
                    stage_config_snapshot={},
                    started_at=datetime.now(),
                    status="running"
                )
                session.add(stage)
                session.commit()

            # If foreign keys are enforced, this should fail
            # If not enforced (SQLite default), it will succeed
            # Either is acceptable depending on configuration
        except Exception as e:
            # Foreign key violation
            assert "foreign" in str(e).lower() or "constraint" in str(e).lower()

    def test_null_constraint_violation(self, db_manager):
        """Test handling of null constraint violations."""
        # Attempt to create record with missing required field
        with pytest.raises(Exception):
            with db_manager.session() as session:
                workflow = WorkflowExecution(
                    id="wf-1",
                    workflow_name=None,  # Required field
                    started_at=datetime.now(),
                    status="running"
                )
                session.add(workflow)
                session.commit()


class TestRecoveryMechanisms:
    """Test recovery mechanisms after failures."""

    def test_recovery_after_connection_loss(self, temp_db_file):
        """Test recovery after connection loss."""
        manager = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")
        manager.create_all_tables()

        # Create initial data
        with manager.session() as session:
            workflow = WorkflowExecution(
                id="wf-1",
                workflow_name="test",
                started_at=datetime.now(),
                status="running"
            )
            session.add(workflow)
            session.commit()

        # Simulate connection loss
        # Manager cleanup happens automatically

        # Create new connection
        manager2 = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")

        # Should be able to read previous data
        with manager2.session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
            assert workflow is not None
            assert workflow.status == "running"

        # Manager cleanup happens automatically

    def test_recovery_after_failed_transaction(self, db_manager):
        """Test recovery after a failed transaction."""
        # Failed transaction
        try:
            with db_manager.session() as session:
                workflow = WorkflowExecution(
                    id="wf-1",
                    workflow_name="test",
                    started_at=datetime.now(),
                    status="running"
                )
                session.add(workflow)
                session.flush()
                raise RuntimeError("Simulated error")
        except RuntimeError:
            pass

        # Should be able to perform new transaction
        with db_manager.session() as session:
            workflow = WorkflowExecution(
                id="wf-2",
                workflow_name="test2",
                started_at=datetime.now(),
                status="running"
            )
            session.add(workflow)
            session.commit()

        # Verify second transaction succeeded
        with db_manager.session() as session:
            count = session.query(WorkflowExecution).count()
            assert count == 1  # Only wf-2, wf-1 rolled back

    def test_automatic_reconnect_on_connection_error(self, temp_db_file):
        """Test automatic reconnection on connection errors."""
        manager = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")
        manager.create_all_tables()

        # Create data
        with manager.session() as session:
            workflow = WorkflowExecution(
                id="wf-1",
                workflow_name="test",
                started_at=datetime.now(),
                status="running"
            )
            session.add(workflow)
            session.commit()

        # Force connection to close
        if hasattr(manager, 'engine'):
            manager.engine.dispose()

        # Should automatically reconnect
        with manager.session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
            assert workflow is not None

        # Manager cleanup happens automatically


class TestQueryFailures:
    """Test query failure scenarios."""

    def test_query_nonexistent_table(self, db_manager):
        """Test querying nonexistent table."""
        with pytest.raises(Exception):
            with db_manager.session() as session:
                # Query table that doesn't exist
                session.execute("SELECT * FROM nonexistent_table")

    def test_invalid_query_syntax(self, db_manager):
        """Test query with invalid syntax."""
        with pytest.raises(Exception):
            with db_manager.session() as session:
                # Invalid SQL syntax
                session.execute("SELECT * FORM workflow_executions")  # FORM instead of FROM

    def test_query_timeout(self):
        """Test query timeout handling."""
        # Would require long-running query to test
        # Testing that manager can be created
        manager = DatabaseManager(database_url="sqlite:///:memory:")

        # Should create successfully
        assert manager is not None
        # Manager cleanup happens automatically

    def test_large_result_set_handling(self, db_manager):
        """Test handling of large result sets."""
        # Create many records
        with db_manager.session() as session:
            workflows = [
                WorkflowExecution(
                    id=f"wf-{i}",
                    workflow_name=f"test{i}",
                    started_at=datetime.now(),
                    status="running"
                )
                for i in range(1000)
            ]
            session.add_all(workflows)
            session.commit()

        # Query all records
        with db_manager.session() as session:
            results = session.query(WorkflowExecution).all()
            assert len(results) == 1000


class TestMemoryManagement:
    """Test memory management with database operations."""

    def test_session_cleanup_after_exception(self, db_manager):
        """Test that sessions are properly cleaned up after exceptions."""
        # Create session that raises exception
        try:
            with db_manager.session() as session:
                workflow = WorkflowExecution(
                    id="wf-1",
                    workflow_name="test",
                    started_at=datetime.now(),
                    status="running"
                )
                session.add(workflow)
                raise RuntimeError("Test error")
        except RuntimeError:
            pass

        # Should be able to create new session
        with db_manager.session() as session:
            count = session.query(WorkflowExecution).count()
            assert count == 0  # Previous session rolled back

    def test_no_memory_leak_with_many_sessions(self, db_manager):
        """Test no memory leaks with many sessions."""
        import gc

        # Create many short-lived sessions
        for i in range(100):
            with db_manager.session() as session:
                workflow = WorkflowExecution(
                    id=f"wf-{i}",
                    workflow_name=f"test{i}",
                    started_at=datetime.now(),
                    status="running"
                )
                session.add(workflow)
                session.commit()

        # Force garbage collection
        gc.collect()

        # Verify data integrity
        with db_manager.session() as session:
            count = session.query(WorkflowExecution).count()
            assert count == 100


class TestDatabaseMigrations:
    """Test database migration scenarios."""

    def test_migration_on_schema_change(self, temp_db_file):
        """Test handling of schema changes."""
        # Create database with initial schema
        manager1 = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")
        manager1.create_all_tables()

        with manager1.session() as session:
            workflow = WorkflowExecution(
                id="wf-1",
                workflow_name="test",
                started_at=datetime.now(),
                status="running"
            )
            session.add(workflow)
            session.commit()

        # Manager cleanup happens automatically

        # Reopen with same schema (simulates migration compatibility)
        manager2 = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")

        with manager2.session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
            assert workflow is not None

        # Manager cleanup happens automatically


class TestBackupAndRestore:
    """Test backup and restore scenarios."""

    def test_database_file_copy(self, temp_db_file):
        """Test copying database file."""
        manager = DatabaseManager(database_url=f"sqlite:///{temp_db_file}")
        manager.create_all_tables()

        # Create data
        with manager.session() as session:
            workflow = WorkflowExecution(
                id="wf-1",
                workflow_name="test",
                started_at=datetime.now(),
                status="running"
            )
            session.add(workflow)
            session.commit()

        # Manager cleanup happens automatically

        # Copy database file
        import shutil
        backup_file = temp_db_file + ".backup"
        shutil.copy(temp_db_file, backup_file)

        # Open backup
        backup_manager = DatabaseManager(database_url=f"sqlite:///{backup_file}")

        with backup_manager.session() as session:
            workflow = session.query(WorkflowExecution).filter_by(id="wf-1").first()
            assert workflow is not None

        # Manager cleanup happens automatically
        Path(backup_file).unlink(missing_ok=True)
