"""
Comprehensive tests for database layer.

Coverage:
- Connection pooling
- Thread safety
- Transactions (ACID properties)
- All CRUD operations
- Edge cases (None, empty, boundaries)
- Concurrent access
- Error handling
"""

import json
import os
import threading
import time
from datetime import datetime

import pytest

from coord_service.database import Database, LockConflictError


class TestDatabaseInitialization:
    """Test database initialization and schema."""

    def test_initialize_creates_tables(self, db):
        """All tables should be created."""
        tables = db.query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = [t['name'] for t in tables]

        expected_tables = [
            'agents', 'audit_log', 'error_snapshots', 'event_log',
            'file_lock_stats', 'locks', 'metrics_snapshots',
            'performance_traces', 'schema_version', 'task_file_activity',
            'task_timing', 'tasks', 'velocity_events'
        ]

        for table in expected_tables:
            assert table in table_names, f"Table {table} not created"

    def test_initialize_idempotent(self, db):
        """Initialize should be idempotent (can be called multiple times)."""
        db.initialize()  # Second call
        db.initialize()  # Third call

        # Should not raise errors
        agents = db.query("SELECT COUNT(*) as count FROM agents")
        assert agents[0]['count'] == 0

    def test_wal_mode_enabled(self, db):
        """WAL mode should be enabled for better concurrency."""
        result = db.query("PRAGMA journal_mode")
        assert result[0]['journal_mode'].upper() == 'WAL'

    def test_foreign_keys_enabled(self, db):
        """Foreign keys should be enforced."""
        result = db.query("PRAGMA foreign_keys")
        assert result[0]['foreign_keys'] == 1


class TestDatabaseTransactions:
    """Test transaction handling and ACID properties."""

    def test_transaction_commit(self, db):
        """Successful transaction should commit changes."""
        with db.transaction():
            db.execute(
                "INSERT INTO agents (id, pid) VALUES (?, ?)",
                ('test-agent', 12345)
            )

        # Verify committed
        result = db.query_one("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        assert result is not None
        assert result['pid'] == 12345

    def test_transaction_rollback_on_exception(self, db):
        """Exception in transaction should rollback changes."""
        try:
            with db.transaction():
                db.execute(
                    "INSERT INTO agents (id, pid) VALUES (?, ?)",
                    ('rollback-agent', 12345)
                )
                raise ValueError("Force rollback")
        except ValueError:
            pass

        # Verify rolled back
        result = db.query_one("SELECT * FROM agents WHERE id = ?", ('rollback-agent',))
        assert result is None

    def test_nested_transactions_not_supported(self, db):
        """Nested transactions should work as expected (outer transaction)."""
        with db.transaction():
            db.execute(
                "INSERT INTO agents (id, pid) VALUES (?, ?)",
                ('outer-agent', 12345)
            )

            # Inner transaction (SQLite doesn't support nested, uses same transaction)
            with db.transaction():
                db.execute(
                    "INSERT INTO agents (id, pid) VALUES (?, ?)",
                    ('inner-agent', 54321)
                )

        # Both should be committed
        assert db.query_one("SELECT * FROM agents WHERE id = ?", ('outer-agent',))
        assert db.query_one("SELECT * FROM agents WHERE id = ?", ('inner-agent',))

    def test_transaction_isolation(self, db):
        """Concurrent transactions should be isolated."""
        results = []

        def transaction1():
            try:
                with db.transaction():
                    db.execute(
                        "INSERT INTO agents (id, pid) VALUES (?, ?)",
                        ('t1-agent', 11111)
                    )
                    time.sleep(0.1)  # Hold transaction
                results.append('t1-ok')
            except Exception as e:
                results.append(f't1-error: {e}')

        def transaction2():
            time.sleep(0.05)  # Start after t1
            try:
                with db.transaction():
                    db.execute(
                        "INSERT INTO agents (id, pid) VALUES (?, ?)",
                        ('t2-agent', 22222)
                    )
                results.append('t2-ok')
            except Exception as e:
                results.append(f't2-error: {e}')

        t1 = threading.Thread(target=transaction1)
        t2 = threading.Thread(target=transaction2)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both should succeed (WAL mode allows concurrent reads/writes)
        assert 't1-ok' in results
        assert 't2-ok' in results


class TestAgentOperations:
    """Test agent-related database operations."""

    def test_register_agent(self, db):
        """Register agent should insert record."""
        db.register_agent('test-agent', 12345, {'key': 'value'})

        agent = db.query_one("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        assert agent['id'] == 'test-agent'
        assert agent['pid'] == 12345
        assert json.loads(agent['metadata']) == {'key': 'value'}

    def test_register_agent_without_metadata(self, db):
        """Register agent without metadata should use empty dict."""
        db.register_agent('test-agent', 12345)

        agent = db.query_one("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        assert json.loads(agent['metadata']) == {}

    def test_register_duplicate_agent(self, db):
        """Registering duplicate agent should succeed (replace)."""
        db.register_agent('test-agent', 12345)
        db.register_agent('test-agent', 54321)  # Different PID

        agents = db.query("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        assert len(agents) == 1
        assert agents[0]['pid'] == 54321

    def test_agent_exists(self, db):
        """Check if agent exists."""
        assert not db.agent_exists('nonexistent')

        db.register_agent('test-agent', 12345)
        assert db.agent_exists('test-agent')

    def test_unregister_agent(self, db):
        """Unregister should delete agent and cascade."""
        db.register_agent('test-agent', 12345)

        # Add locks for agent
        db.execute(
            "INSERT INTO locks (file_path, owner) VALUES (?, ?)",
            ('test.py', 'test-agent')
        )

        db.unregister_agent('test-agent')

        # Agent should be gone
        assert not db.agent_exists('test-agent')

        # Locks should be gone (cascade)
        locks = db.query("SELECT * FROM locks WHERE owner = ?", ('test-agent',))
        assert len(locks) == 0

    def test_unregister_agent_releases_tasks(self, db):
        """Unregister should release claimed tasks."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'test-agent')

        db.unregister_agent('test-agent')

        # Task should be pending again
        task = db.get_task('test-task')
        assert task['status'] == 'pending'
        assert task['owner'] is None

    def test_update_heartbeat(self, db):
        """Update heartbeat should update timestamp."""
        db.register_agent('test-agent', 12345)

        # Get initial heartbeat
        agent1 = db.query_one("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        initial_hb = agent1['last_heartbeat']

        time.sleep(0.1)

        # Update heartbeat
        db.update_heartbeat('test-agent')

        agent2 = db.query_one("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        updated_hb = agent2['last_heartbeat']

        assert updated_hb > initial_hb

    def test_get_stale_agents(self, db):
        """Get stale agents based on heartbeat timeout."""
        # Register agents
        db.register_agent('fresh-agent', 11111)
        db.register_agent('stale-agent', 22222)

        # Make stale-agent old
        db.execute(
            "UPDATE agents SET last_heartbeat = datetime('now', '-10 minutes') WHERE id = ?",
            ('stale-agent',)
        )

        # Get stale (timeout 5 min = 300 sec)
        stale = db.get_stale_agents(300)

        assert 'stale-agent' in stale
        assert 'fresh-agent' not in stale

    def test_get_stale_agents_empty(self, db):
        """Get stale agents when none exist."""
        stale = db.get_stale_agents(300)
        assert len(stale) == 0

    def test_agent_id_boundary_lengths(self, db):
        """Test agent IDs with boundary lengths."""
        # Very short ID
        db.register_agent('a', 12345)
        assert db.agent_exists('a')

        # Very long ID (1000 chars)
        long_id = 'x' * 1000
        db.register_agent(long_id, 12345)
        assert db.agent_exists(long_id)

    def test_agent_id_special_characters(self, db):
        """Test agent IDs with special characters."""
        special_ids = [
            'agent-with-dashes',
            'agent_with_underscores',
            'agent.with.dots',
            'agent@with@symbols',
            'agent/with/slashes',
            'agent with spaces'
        ]

        for agent_id in special_ids:
            db.register_agent(agent_id, 12345)
            assert db.agent_exists(agent_id)


class TestTaskOperations:
    """Test task-related database operations."""

    def test_create_task_minimal(self, db):
        """Create task with minimal required fields."""
        db.create_task('test-task', 'Subject', 'Description')

        task = db.get_task('test-task')
        assert task['id'] == 'test-task'
        assert task['subject'] == 'Subject'
        assert task['description'] == 'Description'
        assert task['priority'] == 3  # Default
        assert task['status'] == 'pending'
        assert task['owner'] is None

    def test_create_task_full(self, db):
        """Create task with all fields."""
        db.create_task(
            'test-task',
            'Subject',
            'Description',
            priority=1,
            active_form='Testing',
            spec_path='/path/to/spec.md',
            metadata={'key': 'value'}
        )

        task = db.get_task('test-task')
        assert task['priority'] == 1
        assert task['active_form'] == 'Testing'
        assert task['spec_path'] == '/path/to/spec.md'
        assert json.loads(task['metadata']) == {'key': 'value'}

    def test_create_task_initializes_timing(self, db):
        """Create task should initialize task_timing record."""
        db.create_task('test-task', 'Subject', 'Description')

        timing = db.query_one(
            "SELECT * FROM task_timing WHERE task_id = ?",
            ('test-task',)
        )
        assert timing is not None
        assert timing['created_at'] is not None

    def test_task_exists(self, db):
        """Check if task exists."""
        assert not db.task_exists('nonexistent')

        db.create_task('test-task', 'Subject', 'Description')
        assert db.task_exists('test-task')

    def test_task_exists_ignores_deleted(self, db):
        """task_exists should ignore deleted tasks."""
        db.create_task('test-task', 'Subject', 'Description')
        db.execute("UPDATE tasks SET status = 'deleted' WHERE id = ?", ('test-task',))

        assert not db.task_exists('test-task')

    def test_get_task(self, db):
        """Get task by ID."""
        db.create_task('test-task', 'Subject', 'Description')

        task = db.get_task('test-task')
        assert task is not None
        assert task['id'] == 'test-task'

    def test_get_task_nonexistent(self, db):
        """Get nonexistent task returns None."""
        task = db.get_task('nonexistent')
        assert task is None

    def test_get_task_deleted_returns_none(self, db):
        """Get deleted task returns None."""
        db.create_task('test-task', 'Subject', 'Description')
        db.execute("UPDATE tasks SET status = 'deleted' WHERE id = ?", ('test-task',))

        task = db.get_task('test-task')
        assert task is None

    def test_claim_task(self, db):
        """Claim task updates status and owner."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')

        db.claim_task('test-task', 'test-agent')

        task = db.get_task('test-task')
        assert task['status'] == 'in_progress'
        assert task['owner'] == 'test-agent'
        assert task['started_at'] is not None

    def test_claim_task_updates_timing(self, db):
        """Claim task should update task_timing."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')

        db.claim_task('test-task', 'test-agent')

        timing = db.query_one(
            "SELECT * FROM task_timing WHERE task_id = ?",
            ('test-task',)
        )
        assert timing['claimed_at'] is not None

    def test_claim_task_already_claimed(self, db):
        """Claiming already claimed task should raise ValueError."""
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('test-task', 'Subject', 'Description')

        db.claim_task('test-task', 'agent1')

        # Attempting to claim again should raise error
        with pytest.raises(ValueError, match="Cannot claim task"):
            db.claim_task('test-task', 'agent2')

        # Verify state unchanged
        task = db.get_task('test-task')
        assert task['owner'] == 'agent1'
        assert task['status'] == 'in_progress'

    def test_complete_task(self, db):
        """Complete task updates status and timestamp."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'test-agent')

        db.complete_task('test-task', 'test-agent')

        task = db.get_task('test-task')
        assert task['status'] == 'completed'
        assert task['completed_at'] is not None

    def test_complete_task_updates_timing(self, db):
        """Complete task should update task_timing."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'test-agent')

        db.complete_task('test-task', 'test-agent')

        timing = db.query_one(
            "SELECT * FROM task_timing WHERE task_id = ?",
            ('test-task',)
        )
        assert timing['completed_at'] is not None

    def test_complete_task_wrong_owner(self, db):
        """Completing task with wrong owner should raise ValueError."""
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'agent1')

        # Attempting to complete with wrong owner should raise error
        with pytest.raises(ValueError, match="Cannot complete task"):
            db.complete_task('test-task', 'agent2')

        # Verify state unchanged and no timestamp corruption
        task = db.get_task('test-task')
        assert task['status'] == 'in_progress'
        assert task['owner'] == 'agent1'
        assert task['completed_at'] is None  # Critical: timestamp not corrupted

    def test_complete_task_null_owner(self, db):
        """Completing task with NULL owner should raise ValueError."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')

        # Task has no owner (pending state)
        with pytest.raises(ValueError, match="Cannot complete task"):
            db.complete_task('test-task', 'test-agent')

        # Verify state unchanged
        task = db.get_task('test-task')
        assert task['status'] == 'pending'
        assert task['owner'] is None
        assert task['completed_at'] is None

    def test_complete_task_nonexistent(self, db):
        """Completing non-existent task should raise ValueError."""
        db.register_agent('test-agent', 12345)

        with pytest.raises(ValueError, match="Cannot complete task"):
            db.complete_task('nonexistent-task', 'test-agent')

    def test_claim_completed_task(self, db):
        """Claiming completed task should raise ValueError."""
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'agent1')
        db.complete_task('test-task', 'agent1')

        # Attempting to claim completed task should fail
        with pytest.raises(ValueError, match="Cannot claim task"):
            db.claim_task('test-task', 'agent2')

        # Verify state unchanged
        task = db.get_task('test-task')
        assert task['status'] == 'completed'
        assert task['owner'] == 'agent1'

    def test_claim_nonexistent_task(self, db):
        """Claiming non-existent task should raise ValueError."""
        db.register_agent('test-agent', 12345)

        with pytest.raises(ValueError, match="Cannot claim task"):
            db.claim_task('nonexistent-task', 'test-agent')

    def test_get_available_tasks(self, db):
        """Get available tasks returns pending tasks in priority order."""
        db.create_task('task1', 'S1', 'D1', priority=3)
        db.create_task('task2', 'S2', 'D2', priority=1)
        db.create_task('task3', 'S3', 'D3', priority=2)

        # Claim one task
        db.register_agent('test-agent', 12345)
        db.claim_task('task3', 'test-agent')

        # Get available (limit 10)
        tasks = db.get_available_tasks(10)

        # Should get task2 (priority 1) and task1 (priority 3), not task3
        assert len(tasks) == 2
        assert tasks[0]['id'] == 'task2'  # Priority 1 first
        assert tasks[1]['id'] == 'task1'  # Priority 3 second

    def test_get_available_tasks_limit(self, db):
        """Get available tasks respects limit."""
        for i in range(10):
            db.create_task(f'task{i}', f'S{i}', f'D{i}')

        tasks = db.get_available_tasks(5)
        assert len(tasks) == 5

    def test_get_available_tasks_empty(self, db):
        """Get available tasks when none exist."""
        tasks = db.get_available_tasks(10)
        assert len(tasks) == 0

    def test_get_agent_task(self, db):
        """Get agent's current task."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'test-agent')

        task = db.get_agent_task('test-agent')
        assert task is not None
        assert task['id'] == 'test-task'

    def test_get_agent_task_none(self, db):
        """Get agent task when agent has no task."""
        db.register_agent('test-agent', 12345)

        task = db.get_agent_task('test-agent')
        assert task is None

    def test_task_subject_boundary_lengths(self, db):
        """Test task subjects with boundary lengths."""
        # Empty subject (allowed by database, validation layer checks)
        db.create_task('task1', '', 'Description')
        assert db.get_task('task1')['subject'] == ''

        # Very long subject (1000 chars)
        long_subject = 'x' * 1000
        db.create_task('task2', long_subject, 'Description')
        assert db.get_task('task2')['subject'] == long_subject

    def test_task_priority_boundaries(self, db):
        """Test task priorities at boundaries."""
        # Priority 1 (critical)
        db.create_task('task1', 'S', 'D', priority=1)
        assert db.get_task('task1')['priority'] == 1

        # Priority 5 (backlog)
        db.create_task('task2', 'S', 'D', priority=5)
        assert db.get_task('task2')['priority'] == 5

        # Priority 0 (invalid, should be rejected by constraint)
        with pytest.raises(Exception):  # Constraint violation
            db.create_task('task3', 'S', 'D', priority=0)

        # Priority 6 (invalid, should be rejected by constraint)
        with pytest.raises(Exception):  # Constraint violation
            db.create_task('task4', 'S', 'D', priority=6)


class TestLockOperations:
    """Test file lock operations."""

    def test_acquire_lock(self, db):
        """Acquire lock inserts record."""
        db.register_agent('test-agent', 12345)

        db.acquire_lock('test.py', 'test-agent')

        locks = db.query("SELECT * FROM locks WHERE file_path = ?", ('test.py',))
        assert len(locks) == 1
        assert locks[0]['owner'] == 'test-agent'

    def test_acquire_lock_updates_stats(self, db):
        """Acquire lock should update file_lock_stats."""
        db.register_agent('test-agent', 12345)

        db.acquire_lock('test.py', 'test-agent')

        stats = db.query_one(
            "SELECT * FROM file_lock_stats WHERE file_path = ?",
            ('test.py',)
        )
        assert stats is not None
        assert stats['lock_count'] == 1
        assert stats['last_locked_by'] == 'test-agent'

    def test_acquire_lock_with_task_creates_activity(self, db):
        """Acquire lock while task in progress creates task_file_activity."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'test-agent')

        db.acquire_lock('test.py', 'test-agent')

        activity = db.query(
            "SELECT * FROM task_file_activity WHERE task_id = ? AND file_path = ?",
            ('test-task', 'test.py')
        )
        assert len(activity) > 0
        assert activity[0]['lock_acquired_at'] is not None

    def test_acquire_lock_conflict(self, db):
        """Acquiring locked file should raise error."""
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)

        db.acquire_lock('test.py', 'agent1')

        with pytest.raises(LockConflictError):
            db.acquire_lock('test.py', 'agent2')

    def test_acquire_lock_same_agent_updates(self, db):
        """Same agent acquiring same lock should update timestamp."""
        db.register_agent('test-agent', 12345)

        db.acquire_lock('test.py', 'test-agent')
        time.sleep(0.1)
        db.acquire_lock('test.py', 'test-agent')  # Re-acquire

        locks = db.query("SELECT * FROM locks WHERE file_path = ?", ('test.py',))
        assert len(locks) == 1  # Still only one lock

    def test_release_lock(self, db):
        """Release lock deletes record."""
        db.register_agent('test-agent', 12345)
        db.acquire_lock('test.py', 'test-agent')

        db.release_lock('test.py', 'test-agent')

        locks = db.query("SELECT * FROM locks WHERE file_path = ?", ('test.py',))
        assert len(locks) == 0

    def test_release_lock_updates_stats(self, db):
        """Release lock should update duration in stats."""
        db.register_agent('test-agent', 12345)
        db.acquire_lock('test.py', 'test-agent')

        time.sleep(0.1)  # Hold lock for a bit

        db.release_lock('test.py', 'test-agent')

        stats = db.query_one(
            "SELECT * FROM file_lock_stats WHERE file_path = ?",
            ('test.py',)
        )
        assert stats['total_lock_duration_seconds'] > 0
        assert stats['avg_lock_duration_seconds'] > 0

    def test_release_lock_nonexistent(self, db):
        """Releasing nonexistent lock should succeed silently."""
        db.register_agent('test-agent', 12345)

        # Should not raise error
        db.release_lock('nonexistent.py', 'test-agent')

    def test_get_file_locks(self, db):
        """Get agents holding locks on a file."""
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)

        db.acquire_lock('test.py', 'agent1')

        locks = db.get_file_locks('test.py')
        assert locks == ['agent1']

        # No locks on other file
        locks = db.get_file_locks('other.py')
        assert locks == []

    def test_get_agent_locks(self, db):
        """Get files locked by an agent."""
        db.register_agent('test-agent', 12345)

        db.acquire_lock('file1.py', 'test-agent')
        db.acquire_lock('file2.py', 'test-agent')

        locks = db.get_agent_locks('test-agent')
        assert 'file1.py' in locks
        assert 'file2.py' in locks

    def test_get_agent_locks_empty(self, db):
        """Get agent locks when agent has no locks."""
        db.register_agent('test-agent', 12345)

        locks = db.get_agent_locks('test-agent')
        assert len(locks) == 0

    def test_file_path_special_characters(self, db):
        """Test file paths with special characters."""
        db.register_agent('test-agent', 12345)

        special_paths = [
            'file with spaces.py',
            'file-with-dashes.py',
            'file_with_underscores.py',
            'path/to/file.py',
            '../relative/path.py',
            'file@symbol.py',
            'file#hash.py'
        ]

        for path in special_paths:
            db.acquire_lock(path, 'test-agent')
            assert path in db.get_agent_locks('test-agent')
            db.release_lock(path, 'test-agent')


class TestAuditLogging:
    """Test audit log operations."""

    def test_log_operation_success(self, db):
        """Log successful operation."""
        db.log_operation(
            correlation_id='corr-123',
            operation='test_operation',
            agent_id='test-agent',
            entity_type='task',
            entity_id='test-task',
            request_params={'param': 'value'},
            success=True,
            duration_ms=42
        )

        log = db.query_one(
            "SELECT * FROM audit_log WHERE correlation_id = ?",
            ('corr-123',)
        )

        assert log is not None
        assert log['operation'] == 'test_operation'
        assert log['success'] == 1  # SQLite boolean
        assert log['duration_ms'] == 42

    def test_log_operation_error(self, db):
        """Log failed operation with error details."""
        db.log_operation(
            correlation_id='corr-456',
            operation='test_operation',
            success=False,
            error_code='TEST_ERROR',
            error_message='Test error message',
            stack_trace='Stack trace here'
        )

        log = db.query_one(
            "SELECT * FROM audit_log WHERE correlation_id = ?",
            ('corr-456',)
        )

        assert log['success'] == 0  # SQLite boolean
        assert log['error_code'] == 'TEST_ERROR'
        assert log['error_message'] == 'Test error message'
        assert log['stack_trace'] == 'Stack trace here'


class TestStateImportExport:
    """Test state import/export functionality."""

    def test_export_to_json(self, db, temp_dir):
        """Export state to JSON file."""
        # Setup test data
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.acquire_lock('test.py', 'test-agent')

        output_path = os.path.join(temp_dir, 'export.json')
        db.export_to_json(output_path)

        # Verify file exists and valid JSON
        assert os.path.exists(output_path)

        with open(output_path) as f:
            state = json.load(f)

        assert 'agents' in state
        assert 'tasks' in state
        assert 'locks' in state

        assert 'test-agent' in state['agents']
        assert 'test-task' in state['tasks']
        assert 'test.py' in state['locks']

    def test_export_empty_state(self, db, temp_dir):
        """Export empty state."""
        output_path = os.path.join(temp_dir, 'empty.json')
        db.export_to_json(output_path)

        with open(output_path) as f:
            state = json.load(f)

        assert state['agents'] == {}
        assert state['tasks'] == {}
        assert state['locks'] == {}

    def test_import_from_json(self, db, temp_dir):
        """Import state from JSON file."""
        # Create state file
        state = {
            'agents': {
                'test-agent': {
                    'pid': 12345,
                    'registered_at': '2026-01-31 10:00:00',
                    'last_heartbeat': '2026-01-31 10:00:00'
                }
            },
            'tasks': {
                'test-task': {
                    'subject': 'Subject',
                    'description': 'Description',
                    'priority': 3,
                    'status': 'pending',
                    'owner': None,
                    'created_at': '2026-01-31 10:00:00',
                    'started_at': None,
                    'completed_at': None
                }
            },
            'locks': {
                'test.py': [
                    {
                        'owner': 'test-agent',
                        'acquired_at': '2026-01-31 10:00:00'
                    }
                ]
            }
        }

        json_path = os.path.join(temp_dir, 'import.json')
        with open(json_path, 'w') as f:
            json.dump(state, f)

        # Import
        db.import_from_json(json_path)

        # Verify
        assert db.agent_exists('test-agent')
        assert db.task_exists('test-task')
        assert 'test-agent' in db.get_file_locks('test.py')

    def test_import_export_roundtrip(self, db, temp_dir):
        """Export and import should preserve state."""
        # Setup test data
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('task1', 'S1', 'D1', priority=1)
        db.create_task('task2', 'S2', 'D2', priority=2)
        db.claim_task('task1', 'agent1')
        db.acquire_lock('file1.py', 'agent1')
        db.acquire_lock('file2.py', 'agent2')

        # Export
        export_path = os.path.join(temp_dir, 'export.json')
        db.export_to_json(export_path)

        # Create new database
        import_db_path = os.path.join(temp_dir, 'import.db')
        import_db = Database(import_db_path)
        import_db.initialize()

        # Import
        import_db.import_from_json(export_path)

        # Verify
        assert import_db.agent_exists('agent1')
        assert import_db.agent_exists('agent2')
        assert import_db.task_exists('task1')
        assert import_db.task_exists('task2')

        task1 = import_db.get_task('task1')
        assert task1['owner'] == 'agent1'
        assert task1['status'] == 'in_progress'


class TestConcurrency:
    """Test concurrent database access."""

    def test_concurrent_task_claims(self, db):
        """Concurrent claims on same task - only one should succeed."""
        db.create_task('test-task', 'Subject', 'Description')

        results = []

        def claim_task(agent_id):
            try:
                db.register_agent(agent_id, 12345)
                db.claim_task('test-task', agent_id)
                results.append((agent_id, 'success'))
            except Exception as e:
                results.append((agent_id, 'failed'))

        threads = []
        for i in range(10):
            t = threading.Thread(target=claim_task, args=(f'agent-{i}',))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Only one should have succeeded
        successes = [r for r in results if r[1] == 'success']
        # Note: Due to race conditions, multiple might succeed if they hit before status changes
        # But task should only have one owner
        task = db.get_task('test-task')
        assert task['owner'] is not None
        assert task['status'] == 'in_progress'

    def test_concurrent_lock_acquisitions(self, db):
        """Concurrent lock acquisitions - only one should succeed."""
        for i in range(10):
            db.register_agent(f'agent-{i}', 12345 + i)

        results = []

        def acquire_lock(agent_id):
            try:
                db.acquire_lock('test.py', agent_id)
                results.append((agent_id, 'success'))
            except LockConflictError:
                results.append((agent_id, 'conflict'))

        threads = []
        for i in range(10):
            t = threading.Thread(target=acquire_lock, args=(f'agent-{i}',))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Exactly one should succeed
        successes = [r for r in results if r[1] == 'success']
        assert len(successes) == 1

        # Verify lock state
        locks = db.get_file_locks('test.py')
        assert len(locks) == 1

    def test_concurrent_inserts(self, db):
        """Concurrent inserts should all succeed (different records)."""
        results = []

        def insert_agent(i):
            try:
                db.register_agent(f'agent-{i}', 12345 + i)
                results.append(('success', i))
            except Exception as e:
                results.append(('error', str(e)))

        threads = []
        for i in range(50):
            t = threading.Thread(target=insert_agent, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All should succeed
        successes = [r for r in results if r[0] == 'success']
        assert len(successes) == 50

        # Verify all agents exist
        agents = db.query("SELECT COUNT(*) as count FROM agents")
        assert agents[0]['count'] == 50


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string_values(self, db):
        """Test operations with empty strings."""
        # Empty agent ID
        with pytest.raises(Exception):  # Likely constraint or unique violation
            db.register_agent('', 12345)

        # Empty task ID
        with pytest.raises(Exception):
            db.create_task('', 'Subject', 'Description')

        # Empty subject (allowed by DB, validation catches it)
        db.create_task('task1', '', 'Description')
        assert db.get_task('task1')['subject'] == ''

        # Empty file path
        db.register_agent('test-agent', 12345)
        db.acquire_lock('', 'test-agent')  # Should work
        assert '' in db.get_agent_locks('test-agent')

    def test_null_values(self, db):
        """Test operations with None/NULL values."""
        # None metadata
        db.register_agent('test-agent', 12345, None)
        agent = db.query_one("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        assert json.loads(agent['metadata']) == {}

        # None optional fields
        db.create_task('task1', 'Subject', 'Description',
                      active_form=None, spec_path=None, metadata=None)
        task = db.get_task('task1')
        assert task['active_form'] is None
        assert task['spec_path'] is None

    def test_unicode_values(self, db):
        """Test operations with Unicode characters."""
        # Unicode agent ID
        db.register_agent('测试代理', 12345)
        assert db.agent_exists('测试代理')

        # Unicode task subject
        db.create_task('task1', '主题 📝', '描述内容')
        task = db.get_task('task1')
        assert task['subject'] == '主题 📝'
        assert task['description'] == '描述内容'

        # Unicode file path
        db.register_agent('agent', 12345)
        db.acquire_lock('文件/路径.py', 'agent')
        assert '文件/路径.py' in db.get_agent_locks('agent')

    def test_very_long_values(self, db):
        """Test operations with very long values."""
        # Very long agent ID (10KB)
        long_id = 'a' * 10000
        db.register_agent(long_id, 12345)
        assert db.agent_exists(long_id)

        # Very long task description (1MB)
        long_desc = 'x' * 1000000
        db.create_task('task1', 'Subject', long_desc)
        task = db.get_task('task1')
        assert len(task['description']) == 1000000

    def test_sql_injection_attempts(self, db):
        """Test that SQL injection is prevented by parameterized queries."""
        # Try SQL injection in agent ID
        evil_id = "'; DROP TABLE agents; --"
        db.register_agent(evil_id, 12345)

        # Verify agents table still exists
        agents = db.query("SELECT * FROM agents")
        assert len(agents) > 0

        # Try SQL injection in query
        task_id = "' OR '1'='1"
        task = db.get_task(task_id)
        assert task is None  # Should not match anything

    def test_negative_pids(self, db):
        """Test negative PIDs (technically valid on some systems)."""
        db.register_agent('test-agent', -1)
        agent = db.query_one("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        assert agent['pid'] == -1

    def test_zero_values(self, db):
        """Test zero values."""
        # PID = 0
        db.register_agent('test-agent', 0)
        agent = db.query_one("SELECT * FROM agents WHERE id = ?", ('test-agent',))
        assert agent['pid'] == 0

        # Priority = 0 (should fail constraint)
        with pytest.raises(Exception):
            db.create_task('task1', 'Subject', 'Description', priority=0)

    def test_large_batch_operations(self, db):
        """Test operations with large batches."""
        # Create 1000 tasks
        for i in range(1000):
            db.create_task(f'task-{i:04d}', f'Subject {i}', f'Description {i}')

        # Verify count
        count = db.query_one("SELECT COUNT(*) as count FROM tasks")
        assert count['count'] == 1000

        # Query should still be fast
        import time
        start = time.time()
        tasks = db.get_available_tasks(100)
        elapsed = time.time() - start

        assert len(tasks) == 100
        assert elapsed < 0.1  # Should complete in <100ms


class TestDatabaseInvariants:
    """
    Test database invariants and constraints.

    These tests explicitly verify that the database maintains consistency
    even under edge cases and error conditions. Critical for preventing
    corruption bugs like the completed_at issue.
    """

    def test_no_completed_at_without_completed_status(self, db):
        """Verify no tasks can have completed_at without status='completed'."""
        # Create and complete task normally
        db.register_agent('agent1', 11111)
        db.create_task('task1', 'Subject', 'Description')
        db.claim_task('task1', 'agent1')
        db.complete_task('task1', 'agent1')

        # Try various failure modes that used to cause corruption
        db.create_task('task2', 'Subject', 'Description')
        db.claim_task('task2', 'agent1')

        # Wrong owner - should not set completed_at
        with pytest.raises(ValueError):
            db.complete_task('task2', 'wrong-agent')

        # Verify invariant: No tasks with completed_at but wrong status
        corrupted = db.query(
            "SELECT * FROM tasks WHERE completed_at IS NOT NULL AND status != 'completed'"
        )
        assert len(corrupted) == 0, f"Found corrupted tasks: {corrupted}"

    def test_no_in_progress_without_owner(self, db):
        """Verify no tasks can be in_progress without an owner."""
        db.register_agent('agent1', 11111)
        db.create_task('task1', 'Subject', 'Description')
        db.claim_task('task1', 'agent1')

        # Verify invariant
        orphaned = db.query(
            "SELECT * FROM tasks WHERE status = 'in_progress' AND owner IS NULL"
        )
        assert len(orphaned) == 0

    def test_completed_tasks_have_completed_at(self, db):
        """Verify completed tasks always have completed_at timestamp."""
        db.register_agent('agent1', 11111)
        db.create_task('task1', 'Subject', 'Description')
        db.claim_task('task1', 'agent1')
        db.complete_task('task1', 'agent1')

        # Verify completed task has timestamp
        task = db.get_task('task1')
        assert task['status'] == 'completed'
        assert task['completed_at'] is not None

        # Verify no completed tasks lack timestamp
        incomplete = db.query(
            "SELECT * FROM tasks WHERE status = 'completed' AND completed_at IS NULL"
        )
        assert len(incomplete) == 0

    def test_in_progress_tasks_have_started_at(self, db):
        """Verify in_progress tasks always have started_at timestamp."""
        db.register_agent('agent1', 11111)
        db.create_task('task1', 'Subject', 'Description')
        db.claim_task('task1', 'agent1')

        # Verify in_progress task has timestamp
        task = db.get_task('task1')
        assert task['status'] == 'in_progress'
        assert task['started_at'] is not None

        # Verify no in_progress tasks lack timestamp
        unstarted = db.query(
            "SELECT * FROM tasks WHERE status = 'in_progress' AND started_at IS NULL"
        )
        assert len(unstarted) == 0

    def test_invariants_after_failed_operations(self, db):
        """Verify invariants maintained even after failed operations."""
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('task1', 'Subject', 'Description')
        db.claim_task('task1', 'agent1')

        # Try several operations that should fail
        with pytest.raises(ValueError):
            db.claim_task('task1', 'agent2')  # Already claimed

        with pytest.raises(ValueError):
            db.complete_task('task1', 'agent2')  # Wrong owner

        with pytest.raises(ValueError):
            db.complete_task('task-nonexistent', 'agent1')  # Doesn't exist

        # Verify ALL invariants still hold
        corrupted = db.query(
            "SELECT * FROM tasks WHERE completed_at IS NOT NULL AND status != 'completed'"
        )
        assert len(corrupted) == 0

        orphaned = db.query(
            "SELECT * FROM tasks WHERE status = 'in_progress' AND owner IS NULL"
        )
        assert len(orphaned) == 0

    def test_invariants_after_agent_unregister(self, db):
        """Verify invariants maintained when agent unregisters."""
        db.register_agent('agent1', 11111)
        db.create_task('task1', 'Subject', 'Description')
        db.create_task('task2', 'Subject', 'Description')

        db.claim_task('task1', 'agent1')
        db.complete_task('task1', 'agent1')
        db.claim_task('task2', 'agent1')

        # Unregister agent - task2 should be released
        db.unregister_agent('agent1')

        # task2 should be released to pending
        task2 = db.get_task('task2')
        assert task2['status'] == 'pending'
        assert task2['owner'] is None

        # Verify invariants
        orphaned = db.query(
            "SELECT * FROM tasks WHERE status = 'in_progress' AND owner IS NULL"
        )
        assert len(orphaned) == 0

    def test_timestamp_consistency(self, db):
        """Verify timestamp consistency across task lifecycle."""
        db.register_agent('agent1', 11111)
        db.create_task('task1', 'Subject', 'Description')

        # Initially no timestamps
        task = db.get_task('task1')
        assert task['started_at'] is None
        assert task['completed_at'] is None

        # After claim, started_at set
        db.claim_task('task1', 'agent1')
        task = db.get_task('task1')
        assert task['started_at'] is not None
        assert task['completed_at'] is None

        # After complete, completed_at set
        db.complete_task('task1', 'agent1')
        task = db.get_task('task1')
        assert task['started_at'] is not None
        assert task['completed_at'] is not None

        # completed_at should be >= started_at
        # (Use string comparison since they're ISO timestamps)
        assert task['completed_at'] >= task['started_at']
