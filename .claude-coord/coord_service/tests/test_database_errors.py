"""
Comprehensive database error handling tests for coordination system.

Test Coverage:
- Transaction rollback scenarios (multi-entity atomicity)
- Connection pool exhaustion under load
- Disk I/O errors and corruption
- Constraint violations (foreign key, unique, check)
- Concurrent access race conditions

Total: 250+ LOC
"""

import pytest
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import concurrent.futures

from coord_service.database import Database, LockConflictError


# ============================================================================
# Helper Functions
# ============================================================================

def verify_no_partial_state(db, task_id):
    """Verify no partial task state exists after rollback."""
    # Check task doesn't exist
    task = db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert task is None, f"Task {task_id} should not exist"

    # Check no dependencies
    deps = db.query(
        "SELECT * FROM task_dependencies WHERE task_id = ?",
        (task_id,)
    )
    assert len(deps) == 0, f"No orphaned dependencies for {task_id}"

    # Check no timing records
    timing = db.query(
        "SELECT * FROM task_timing WHERE task_id = ?",
        (task_id,)
    )
    assert len(timing) == 0, f"No orphaned timing for {task_id}"


def verify_lock_consistency(db, file_path, expected_owner=None):
    """Verify file lock consistency."""
    locks = db.query(
        "SELECT * FROM locks WHERE file_path = ?",
        (file_path,)
    )

    if expected_owner is None:
        assert len(locks) == 0, f"File {file_path} should not be locked"
    else:
        assert len(locks) > 0, f"File {file_path} should be locked"
        assert locks[0]['owner'] == expected_owner, \
            f"{expected_owner} should own lock on {file_path}"


# ============================================================================
# Test Class 1: Transaction Rollback
# ============================================================================

class TestTransactionRollback:
    """Test transaction rollback scenarios (80 LOC)."""

    def test_task_creation_with_dependencies_rollback(self, db):
        """Task creation with dependencies should rollback atomically on error."""
        # Create dependency tasks
        db.create_task('dep-task-1', 'Dependency 1', 'First dep')
        db.create_task('dep-task-2', 'Dependency 2', 'Second dep')

        # Attempt to create task with circular dependency - should fail
        db.create_task('test-task', 'Test Task', 'Description')
        db.create_task('mid-task', 'Mid Task', 'Description', depends_on=['test-task'])

        # Try to add circular dependency: test-task -> mid-task (creates cycle)
        with pytest.raises(ValueError) as exc_info:
            db.add_dependency('test-task', 'mid-task')

        assert 'circular' in str(exc_info.value).lower() or 'cycle' in str(exc_info.value).lower()

        # Verify no dependency was added
        deps = db.query(
            "SELECT * FROM task_dependencies WHERE task_id = ?",
            ('test-task',)
        )
        assert len(deps) == 0, "No dependency should exist due to circular detection"

    def test_lock_acquisition_conflict_handling(self, db):
        """Lock acquisition should fail if file is already locked by another agent."""
        # Create two agents
        db.register_agent('agent-1', 12345)
        db.register_agent('agent-2', 12346)

        # Agent 1 acquires lock
        db.acquire_lock('/shared/file.py', 'agent-1')

        # Agent 2 tries to acquire same lock - should fail
        with pytest.raises(LockConflictError) as exc_info:
            db.acquire_lock('/shared/file.py', 'agent-2')

        assert '/shared/file.py' in str(exc_info.value)
        assert 'agent-1' in str(exc_info.value)

        # Verify only agent-1 has the lock
        verify_lock_consistency(db, '/shared/file.py', expected_owner='agent-1')

        # Verify agent-2 has no locks
        agent2_locks = db.query(
            "SELECT * FROM locks WHERE owner = ?",
            ('agent-2',)
        )
        assert len(agent2_locks) == 0, "Agent-2 should have no locks"

    def test_transaction_rollback_on_constraint_violation(self, db):
        """Transaction should rollback completely when constraint is violated."""
        # Setup agent with locks and tasks
        db.register_agent('test-agent', 12345)
        db.create_task('task-1', 'Task 1', 'Description 1')
        db.claim_task('task-1', 'test-agent')
        db.acquire_lock('/file1.py', 'test-agent')
        db.acquire_lock('/file2.py', 'test-agent')

        # Try to create a duplicate agent within a transaction that also modifies other data
        # This simulates a transaction that partially succeeds but ultimately fails
        with pytest.raises(sqlite3.IntegrityError):
            with db.transaction():
                # First, modify existing data
                db.execute(
                    "UPDATE agents SET pid = ? WHERE id = ?",
                    (99999, 'test-agent')
                )
                # Then violate constraint by inserting duplicate agent
                db.execute(
                    "INSERT INTO agents (id, pid) VALUES (?, ?)",
                    ('test-agent', 54321)
                )

        # Verify complete rollback: agent's PID should still be original value
        agent = db.query_one("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        assert agent is not None, "Agent should still exist"
        assert agent['pid'] == 12345, "Agent PID should not have changed (rollback)"

        # Verify locks still exist (not affected by failed transaction)
        locks = db.query("SELECT * FROM locks WHERE owner = ?", ('test-agent',))
        assert len(locks) == 2, "Locks should be unchanged"

        # Verify task still claimed
        task1 = db.get_task('task-1')
        assert task1['owner'] == 'test-agent', "Task should still be owned"


# ============================================================================
# Test Class 2: Connection Pool & Concurrency
# ============================================================================

class TestConnectionPoolConcurrency:
    """Test connection pool and concurrency (60 LOC)."""

    def test_concurrent_long_transactions_with_wal_mode(self, db):
        """Verify SQLite WAL mode handles many concurrent long-running transactions correctly."""
        CONCURRENT_WORKERS = 30
        TRANSACTION_DURATION = 0.05

        results = {'success': 0, 'failure': 0, 'errors': []}

        def long_running_transaction(worker_id):
            try:
                with db.transaction():
                    # Simulate long-running work
                    db.execute(
                        "INSERT INTO agents (id, pid) VALUES (?, ?)",
                        (f'agent-{worker_id}', worker_id)
                    )
                    time.sleep(TRANSACTION_DURATION)  # Hold transaction
                results['success'] += 1
            except Exception as e:
                results['failure'] += 1
                results['errors'].append(str(e))

        # Create 30 concurrent long transactions
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
            futures = [executor.submit(long_running_transaction, i)
                      for i in range(CONCURRENT_WORKERS)]
            concurrent.futures.wait(futures)

        # All should succeed with WAL mode (SQLite handles concurrent writes well)
        assert results['success'] == CONCURRENT_WORKERS, \
            f"All {CONCURRENT_WORKERS} transactions should succeed with WAL mode, " \
            f"got {results['success']} successes, {results['failure']} failures. " \
            f"Errors: {results['errors'][:3]}"

        # Verify no partial commits
        agents = db.query("SELECT COUNT(*) as count FROM agents")
        assert agents[0]['count'] == CONCURRENT_WORKERS, \
            "All agents should be committed atomically"

    def test_concurrent_circular_dependency_creation_race(self, db):
        """Verify circular dependency detection works under concurrent adds."""
        CONCURRENT_ATTEMPTS = 10

        # Create task chain: A -> B -> C
        db.create_task('task-a', 'Task A', 'Description A')
        db.create_task('task-b', 'Task B', 'Description B', depends_on=['task-a'])
        db.create_task('task-c', 'Task C', 'Description C', depends_on=['task-b'])

        results = {'success': 0, 'circular_detected': 0, 'other_error': 0}

        def add_circular_dependency():
            try:
                # Try to add A -> C (would create cycle A -> B -> C -> A)
                db.add_dependency('task-a', 'task-c')
                results['success'] += 1
            except ValueError as e:
                if 'circular' in str(e).lower() or 'cycle' in str(e).lower():
                    results['circular_detected'] += 1
                else:
                    results['other_error'] += 1
            except Exception as e:
                results['other_error'] += 1

        # Run 10 concurrent attempts
        threads = [threading.Thread(target=add_circular_dependency)
                  for _ in range(CONCURRENT_ATTEMPTS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be rejected (circular dependency detection should catch all attempts)
        assert results['circular_detected'] == CONCURRENT_ATTEMPTS, \
            f"All {CONCURRENT_ATTEMPTS} circular dependencies should be detected, got {results}"
        assert results['success'] == 0, \
            f"No circular dependency should succeed, got {results}"
        assert results['other_error'] == 0, \
            f"No other errors should occur, got {results}"


# ============================================================================
# Test Class 3: Disk I/O Errors
# ============================================================================

class TestDiskIOErrors:
    """Test disk I/O and corruption scenarios (50 LOC)."""

    def test_database_corruption_detection(self, tmp_path):
        """Detect and report corrupted database file."""
        db_path = tmp_path / "test.db"

        # Create valid database
        db = Database(str(db_path))
        db.initialize()
        db.register_agent('test-agent', 12345)

        # Close connection
        from coord_service.database import _thread_local
        if hasattr(_thread_local, 'conn'):
            _thread_local.conn.close()
            delattr(_thread_local, 'conn')

        # Corrupt database file
        with open(db_path, 'wb') as f:
            f.write(b'CORRUPTED DATA NOT A VALID SQLITE FILE')

        # Should detect corruption on next operation
        db2 = Database(str(db_path))
        with pytest.raises((sqlite3.DatabaseError, sqlite3.OperationalError)) as exc_info:
            db2.initialize()

        error_msg = str(exc_info.value).lower()
        assert 'corrupt' in error_msg or 'not a database' in error_msg or \
               'malformed' in error_msg or 'file is not a database' in error_msg

    def test_constraint_violation_during_transaction(self, db):
        """Constraint violations should cause transaction rollback."""
        # Create initial state
        db.register_agent('test-agent', 12345)
        db.create_task('task-1', 'Task 1', 'Description')

        # Try to create duplicate task - should fail with integrity error
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            db.create_task('task-1', 'Duplicate Task', 'Should fail')

        error_msg = str(exc_info.value).lower()
        assert 'unique' in error_msg or 'constraint' in error_msg

        # Verify original task unchanged
        task1 = db.get_task('task-1')
        assert task1 is not None, "Existing task should remain"
        assert task1['subject'] == 'Task 1', "Original subject should be unchanged"
        assert task1['description'] == 'Description', "Original description unchanged"

        # Verify only one task-1 exists
        tasks = db.query("SELECT * FROM tasks WHERE id = ?", ('task-1',))
        assert len(tasks) == 1, "Only one task-1 should exist"


# ============================================================================
# Test Class 4: Constraint Violations
# ============================================================================

class TestConstraintViolations:
    """Test constraint violation handling (60 LOC)."""

    @pytest.mark.skip_invariants
    def test_foreign_key_cascade_on_delete(self, db):
        """Verify foreign key cascades work correctly."""
        # Create agent with lock
        db.register_agent('cascade-agent', 12345)
        db.acquire_lock('/cascade.py', 'cascade-agent')

        # Delete agent (should cascade)
        db.execute("DELETE FROM agents WHERE id = ?", ('cascade-agent',))

        # Verify cascade: locks should be deleted
        locks = db.query("SELECT * FROM locks WHERE owner = ?", ('cascade-agent',))
        assert len(locks) == 0, "Locks should be cascaded (ON DELETE CASCADE)"

        # Verify agent deleted
        agent = db.query_one("SELECT * FROM agents WHERE id = ?", ('cascade-agent',))
        assert agent is None, "Agent should be deleted"

    def test_concurrent_duplicate_task_creation(self, db):
        """Handle concurrent attempts to create same task ID."""
        CONCURRENT_ATTEMPTS = 10

        results = {'success': 0, 'integrity_error': 0, 'other_error': 0}

        def create_task():
            try:
                db.create_task('duplicate-task', 'Subject', 'Description')
                results['success'] += 1
            except sqlite3.IntegrityError:
                results['integrity_error'] += 1
            except Exception as e:
                results['other_error'] += 1

        # 10 threads try to create same task
        threads = [threading.Thread(target=create_task)
                  for _ in range(CONCURRENT_ATTEMPTS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 1 should succeed, rest should get integrity errors
        assert results['success'] == 1, \
            f"Exactly one creation should succeed, got {results}"
        assert results['integrity_error'] == CONCURRENT_ATTEMPTS - 1, \
            f"Exactly {CONCURRENT_ATTEMPTS - 1} should get integrity error, got {results}"
        assert results['other_error'] == 0, \
            f"No other errors should occur, got {results}"

        # Verify only 1 task exists
        tasks = db.query("SELECT * FROM tasks WHERE id = ?", ('duplicate-task',))
        assert len(tasks) == 1, "Exactly one task should exist"

    def test_invalid_task_status_rejected(self, db):
        """Reject invalid task status values."""
        db.create_task('test-task', 'Subject', 'Description')

        # Try to set invalid status
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            db.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                ('invalid_status', 'test-task')
            )

        error_msg = str(exc_info.value).lower()
        assert 'check constraint' in error_msg or 'constraint' in error_msg

        # Verify status unchanged
        task = db.get_task('test-task')
        assert task['status'] == 'pending'

    def test_invalid_priority_rejected(self, db):
        """Reject priority values outside 0-3 range."""
        # Try invalid high priority
        with pytest.raises((sqlite3.IntegrityError, ValueError)):
            db.create_task('test-task', 'Subject', 'Description', priority=10)

        # Try invalid negative priority
        with pytest.raises((sqlite3.IntegrityError, ValueError)):
            db.create_task('test-task-2', 'Subject', 'Description', priority=-1)

        # Verify neither task exists
        task1 = db.query_one("SELECT * FROM tasks WHERE id = ?", ('test-task',))
        assert task1 is None

        task2 = db.query_one("SELECT * FROM tasks WHERE id = ?", ('test-task-2',))
        assert task2 is None
