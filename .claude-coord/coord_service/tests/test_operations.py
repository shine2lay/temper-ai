"""
Comprehensive tests for operation handlers.

Tests all RPC operations with validation, error handling, and audit logging.
Critical for preventing bugs like the database corruption issue.
"""

import pytest
import time

from coord_service.operations import OperationHandler
from coord_service.validator import ValidationErrors, InvariantViolations


class TestOperationExecution:
    """Test operation execution framework."""

    def test_execute_dispatches_to_handler(self, db):
        """Execute dispatches to correct op_* method."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)

        result = handler.execute('heartbeat', {'agent_id': 'test-agent'})

        assert result['status'] == 'ok'

    def test_execute_logs_success(self, db):
        """Successful operations are audit logged."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)

        handler.execute('heartbeat', {'agent_id': 'test-agent'})

        # Check audit log
        logs = db.query("SELECT * FROM audit_log WHERE operation = 'heartbeat'")
        assert len(logs) == 1
        assert logs[0]['success'] == 1
        assert logs[0]['agent_id'] == 'test-agent'

    def test_execute_logs_failure(self, db):
        """Failed operations are audit logged with error details."""
        handler = OperationHandler(db)

        with pytest.raises(ValueError):
            handler.execute('invalid_operation', {})

        # Check audit log
        logs = db.query("SELECT * FROM audit_log WHERE success = 0")
        assert len(logs) == 1
        assert 'Unknown operation' in logs[0]['error_message']

    def test_execute_unknown_operation_raises(self, db):
        """Unknown operation raises ValueError."""
        handler = OperationHandler(db)

        with pytest.raises(ValueError, match="Unknown operation"):
            handler.execute('does_not_exist', {})

    def test_execute_validates_invariants_post_operation(self, db):
        """Post-operation invariant validation runs."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')

        # This should validate that no corruption occurred
        result = handler.execute('task_claim', {
            'agent_id': 'test-agent',
            'task_id': 'test-task'
        })

        assert result['status'] == 'claimed'
        # If invariants were violated, an exception would have been raised


class TestAgentOperations:
    """Test agent lifecycle operations."""

    def test_op_register_success(self, db):
        """Agent registration succeeds with valid params."""
        handler = OperationHandler(db)

        result = handler.execute('register', {
            'agent_id': 'test-agent',
            'pid': 12345
        })

        assert result['status'] == 'registered'
        assert result['agent_id'] == 'test-agent'
        assert db.agent_exists('test-agent')

    def test_op_register_with_metadata(self, db):
        """Agent registration preserves metadata."""
        handler = OperationHandler(db)

        handler.execute('register', {
            'agent_id': 'test-agent',
            'pid': 12345,
            'metadata': {'version': '1.0', 'env': 'test'}
        })

        agent = db.query_one("SELECT * FROM agents WHERE id = 'test-agent'")
        import json
        metadata = json.loads(agent['metadata'])
        assert metadata['version'] == '1.0'
        assert metadata['env'] == 'test'

    def test_op_register_duplicate_raises(self, db):
        """Registering duplicate agent raises error."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)

        with pytest.raises(Exception):  # sqlite3.IntegrityError or similar
            handler.execute('register', {
                'agent_id': 'test-agent',
                'pid': 67890
            })

    def test_op_unregister_success(self, db):
        """Agent unregistration succeeds."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)

        result = handler.execute('unregister', {
            'agent_id': 'test-agent'
        })

        assert result['status'] == 'unregistered'
        assert not db.agent_exists('test-agent')

    def test_op_unregister_releases_tasks(self, db):
        """Unregistering agent releases its claimed tasks."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'test-agent')

        handler.execute('unregister', {'agent_id': 'test-agent'})

        # Task should be released back to pending
        task = db.get_task('test-task')
        assert task['status'] == 'pending'
        assert task['owner'] is None

    def test_op_unregister_nonexistent_agent_succeeds(self, db):
        """Unregistering nonexistent agent doesn't raise error."""
        handler = OperationHandler(db)

        # Should succeed silently (idempotent)
        result = handler.execute('unregister', {
            'agent_id': 'nonexistent'
        })

        assert result['status'] == 'unregistered'

    def test_op_heartbeat_updates_timestamp(self, db):
        """Heartbeat updates agent's last_heartbeat."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)

        # Get initial heartbeat
        agent1 = db.query_one("SELECT last_heartbeat FROM agents WHERE id = 'test-agent'")

        time.sleep(0.1)  # Ensure time passes

        handler.execute('heartbeat', {'agent_id': 'test-agent'})

        # Get updated heartbeat
        agent2 = db.query_one("SELECT last_heartbeat FROM agents WHERE id = 'test-agent'")

        assert agent2['last_heartbeat'] > agent1['last_heartbeat']

    def test_op_heartbeat_nonexistent_agent_raises(self, db):
        """Heartbeat for nonexistent agent raises error."""
        handler = OperationHandler(db)

        with pytest.raises(Exception):
            handler.execute('heartbeat', {'agent_id': 'nonexistent'})


class TestTaskOperations:
    """Test task lifecycle operations."""

    def test_op_task_create_success(self, db):
        """Task creation succeeds with valid params."""
        handler = OperationHandler(db)

        result = handler.execute('task_create', {
            'task_id': 'test-task',
            'subject': 'Test Subject',
            'description': 'Test Description',
            'priority': 2
        })

        assert result['status'] == 'created'
        assert result['task_id'] == 'test-task'

        task = db.get_task('test-task')
        assert task['subject'] == 'Test Subject'
        assert task['priority'] == 2

    def test_op_task_create_with_metadata(self, db):
        """Task creation preserves metadata."""
        handler = OperationHandler(db)

        handler.execute('task_create', {
            'task_id': 'test-task',
            'subject': 'Subject',
            'description': 'Description',
            'metadata': {'category': 'test', 'owner': 'alice'}
        })

        task = db.get_task('test-task')
        import json
        metadata = json.loads(task['metadata'])
        assert metadata['category'] == 'test'
        assert metadata['owner'] == 'alice'

    def test_op_task_create_validation_error(self, db):
        """Task creation with invalid params raises ValidationErrors."""
        handler = OperationHandler(db)

        # Invalid task ID format
        with pytest.raises(ValidationErrors):
            handler.execute('task_create', {
                'task_id': 'invalid task id',  # Spaces not allowed
                'subject': 'Subject',
                'description': 'Description'
            })

    def test_op_task_create_duplicate_raises(self, db):
        """Creating duplicate task raises error."""
        handler = OperationHandler(db)
        db.create_task('test-task', 'Subject', 'Description')

        with pytest.raises(Exception):
            handler.execute('task_create', {
                'task_id': 'test-task',
                'subject': 'Subject',
                'description': 'Description'
            })

    def test_op_task_claim_success(self, db):
        """Task claim succeeds for pending task."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')

        result = handler.execute('task_claim', {
            'agent_id': 'test-agent',
            'task_id': 'test-task'
        })

        assert result['status'] == 'claimed'
        assert result['task_id'] == 'test-task'
        assert result['agent_id'] == 'test-agent'

        task = db.get_task('test-task')
        assert task['status'] == 'in_progress'
        assert task['owner'] == 'test-agent'

    def test_op_task_claim_already_claimed_raises(self, db):
        """Claiming already claimed task raises ValueError."""
        handler = OperationHandler(db)
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'agent1')

        with pytest.raises(ValueError, match="Cannot claim task"):
            handler.execute('task_claim', {
                'agent_id': 'agent2',
                'task_id': 'test-task'
            })

    def test_op_task_claim_nonexistent_raises(self, db):
        """Claiming nonexistent task raises error."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)

        with pytest.raises(ValueError, match="Cannot claim task"):
            handler.execute('task_claim', {
                'agent_id': 'test-agent',
                'task_id': 'nonexistent'
            })

    def test_op_task_complete_success(self, db):
        """Task completion succeeds for claimed task."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'test-agent')

        result = handler.execute('task_complete', {
            'agent_id': 'test-agent',
            'task_id': 'test-task'
        })

        assert result['status'] == 'completed'
        assert result['task_id'] == 'test-task'

        task = db.get_task('test-task')
        assert task['status'] == 'completed'
        assert task['completed_at'] is not None

    def test_op_task_complete_wrong_owner_raises(self, db):
        """Completing task with wrong owner raises ValueError.

        CRITICAL: Regression test for database corruption bug.
        Before fix, this would silently fail and corrupt completed_at.
        """
        handler = OperationHandler(db)
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'agent1')

        # Attempt to complete with wrong owner
        with pytest.raises(ValueError, match="Cannot complete task"):
            handler.execute('task_complete', {
                'agent_id': 'agent2',  # Wrong owner!
                'task_id': 'test-task'
            })

        # CRITICAL: Verify no corruption
        task = db.get_task('test-task')
        assert task['status'] == 'in_progress'  # Still in progress
        assert task['owner'] == 'agent1'  # Still owned by agent1
        assert task['completed_at'] is None  # No timestamp corruption!

    def test_op_task_complete_null_owner_raises(self, db):
        """Completing task with NULL owner raises ValueError.

        CRITICAL: Another corruption scenario - completing pending task.
        """
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        # Task is pending (no owner)

        with pytest.raises(ValueError, match="Cannot complete task"):
            handler.execute('task_complete', {
                'agent_id': 'test-agent',
                'task_id': 'test-task'
            })

        # Verify no corruption
        task = db.get_task('test-task')
        assert task['status'] == 'pending'
        assert task['owner'] is None
        assert task['completed_at'] is None

    def test_op_task_complete_nonexistent_raises(self, db):
        """Completing nonexistent task raises ValueError."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)

        with pytest.raises(ValueError, match="Cannot complete task"):
            handler.execute('task_complete', {
                'agent_id': 'test-agent',
                'task_id': 'nonexistent'
            })

    def test_op_task_get_success(self, db):
        """Get task returns task details."""
        handler = OperationHandler(db)
        db.create_task('test-task', 'Subject', 'Description', priority=1)

        result = handler.execute('task_get', {'task_id': 'test-task'})

        assert 'task' in result
        assert result['task']['id'] == 'test-task'
        assert result['task']['subject'] == 'Subject'
        assert result['task']['priority'] == 1

    def test_op_task_get_nonexistent_raises(self, db):
        """Get nonexistent task raises ValueError."""
        handler = OperationHandler(db)

        with pytest.raises(ValueError, match="not found"):
            handler.execute('task_get', {'task_id': 'nonexistent'})

    def test_op_task_list_returns_pending(self, db):
        """List tasks returns only pending tasks."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)

        db.create_task('pending1', 'S1', 'D1')
        db.create_task('pending2', 'S2', 'D2')
        db.create_task('claimed', 'S3', 'D3')
        db.claim_task('claimed', 'test-agent')

        result = handler.execute('task_list', {'limit': 10})

        task_ids = [t['id'] for t in result['tasks']]
        assert 'pending1' in task_ids
        assert 'pending2' in task_ids
        assert 'claimed' not in task_ids  # Not pending

    def test_op_task_list_respects_limit(self, db):
        """List tasks respects limit parameter."""
        handler = OperationHandler(db)

        for i in range(10):
            db.create_task(f'task-{i}', 'Subject', 'Description')

        result = handler.execute('task_list', {'limit': 5})

        assert len(result['tasks']) == 5

    def test_op_task_list_default_limit(self, db):
        """List tasks uses default limit if not specified."""
        handler = OperationHandler(db)

        for i in range(20):
            db.create_task(f'task-{i}', 'Subject', 'Description')

        result = handler.execute('task_list', {})

        # Default limit is 10
        assert len(result['tasks']) == 10


class TestLockOperations:
    """Test file lock operations."""

    def test_op_lock_acquire_success(self, db):
        """Lock acquisition succeeds."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)

        result = handler.execute('lock_acquire', {
            'agent_id': 'test-agent',
            'file_path': 'test/file.py'
        })

        assert result['status'] == 'acquired'

        locks = db.get_file_locks('test/file.py')
        assert len(locks) == 1
        assert locks[0]['owner'] == 'test-agent'

    def test_op_lock_acquire_already_locked_raises(self, db):
        """Acquiring already locked file raises error."""
        handler = OperationHandler(db)
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.acquire_lock('test/file.py', 'agent1')

        from coord_service.database import LockConflictError
        with pytest.raises(LockConflictError):
            handler.execute('lock_acquire', {
                'agent_id': 'agent2',
                'file_path': 'test/file.py'
            })

    def test_op_lock_release_success(self, db):
        """Lock release succeeds."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)
        db.acquire_lock('test/file.py', 'test-agent')

        result = handler.execute('lock_release', {
            'agent_id': 'test-agent',
            'file_path': 'test/file.py'
        })

        assert result['status'] == 'released'

        locks = db.get_file_locks('test/file.py')
        assert len(locks) == 0

    def test_op_lock_release_not_owned_succeeds(self, db):
        """Releasing lock not owned doesn't raise error (idempotent)."""
        handler = OperationHandler(db)
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.acquire_lock('test/file.py', 'agent1')

        # agent2 releasing agent1's lock should succeed (cleanup)
        result = handler.execute('lock_release', {
            'agent_id': 'agent2',
            'file_path': 'test/file.py'
        })

        assert result['status'] == 'released'

    def test_op_lock_list_by_agent(self, db):
        """List locks by agent returns agent's locks."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)
        db.acquire_lock('file1.py', 'test-agent')
        db.acquire_lock('file2.py', 'test-agent')

        result = handler.execute('lock_list', {
            'agent_id': 'test-agent'
        })

        assert len(result['locks']) == 2
        file_paths = [l['file_path'] for l in result['locks']]
        assert 'file1.py' in file_paths
        assert 'file2.py' in file_paths

    def test_op_lock_list_by_file(self, db):
        """List locks by file returns file's locks."""
        handler = OperationHandler(db)
        db.register_agent('test-agent', 12345)
        db.acquire_lock('test/file.py', 'test-agent')

        result = handler.execute('lock_list', {
            'file_path': 'test/file.py'
        })

        assert len(result['locks']) == 1
        assert result['locks'][0]['owner'] == 'test-agent'


class TestStatusOperations:
    """Test status and metrics operations."""

    def test_op_status_returns_all_stats(self, db):
        """Status returns agent count, task counts, lock count."""
        handler = OperationHandler(db)
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('pending', 'S', 'D')
        db.create_task('claimed', 'S', 'D')
        db.claim_task('claimed', 'agent1')
        db.acquire_lock('file.py', 'agent1')

        result = handler.execute('status', {})

        assert result['agent_count'] == 2
        assert result['task_pending'] == 1
        assert result['task_in_progress'] == 1
        assert result['task_completed'] == 0
        assert result['lock_count'] == 1

    def test_op_velocity_returns_metrics(self, db):
        """Velocity operation returns completion metrics."""
        handler = OperationHandler(db)

        result = handler.execute('velocity', {'period': '1 hour'})

        # Should return velocity data (even if empty)
        assert 'completed_count' in result or 'velocity' in result

    def test_op_file_hotspots_returns_files(self, db):
        """File hotspots returns most locked files."""
        handler = OperationHandler(db)

        result = handler.execute('file_hotspots', {'limit': 10})

        assert 'hotspots' in result or 'files' in result


class TestErrorHandling:
    """Test error handling and logging."""

    def test_validation_error_logged(self, db):
        """ValidationErrors are logged in audit log."""
        handler = OperationHandler(db)

        with pytest.raises(ValidationErrors):
            handler.execute('task_create', {
                'task_id': 'invalid id',  # Invalid format
                'subject': 'Subject',
                'description': 'Description'
            })

        logs = db.query(
            "SELECT * FROM audit_log WHERE error_code = 'VALIDATION_ERROR'"
        )
        assert len(logs) >= 1

    def test_operation_error_includes_stacktrace(self, db):
        """Operation errors include stack trace in audit log."""
        handler = OperationHandler(db)

        with pytest.raises(ValueError):
            handler.execute('unknown_op', {})

        logs = db.query("SELECT * FROM audit_log WHERE success = 0")
        assert len(logs) >= 1
        # Stack trace should be present for debugging
        assert logs[0]['stack_trace'] is not None


class TestConcurrentOperations:
    """Test concurrent operation handling."""

    def test_concurrent_task_claims_only_one_succeeds(self, db):
        """Multiple concurrent claims for same task - only one succeeds."""
        import threading

        handler = OperationHandler(db)
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('test-task', 'Subject', 'Description')

        results = []

        def claim_task(agent_id):
            try:
                result = handler.execute('task_claim', {
                    'agent_id': agent_id,
                    'task_id': 'test-task'
                })
                results.append(('success', agent_id, result))
            except Exception as e:
                results.append(('error', agent_id, str(e)))

        t1 = threading.Thread(target=claim_task, args=('agent1',))
        t2 = threading.Thread(target=claim_task, args=('agent2',))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one should succeed
        successes = [r for r in results if r[0] == 'success']
        errors = [r for r in results if r[0] == 'error']

        assert len(successes) == 1
        assert len(errors) == 1
        assert 'Cannot claim task' in errors[0][2]
