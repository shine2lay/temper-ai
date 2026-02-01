"""
Tests for defensive checks against database corruption.

Ensures that even if corruption occurs (tasks with completed_at but status='pending'),
agents won't work on already-completed tasks.
"""

import pytest
from coord_service.database import Database


@pytest.mark.skip_invariants
class TestCorruptionDefense:
    """Test defensive measures against task corruption."""

    def test_get_available_tasks_excludes_completed_at_pending(self, db):
        """get_available_tasks should exclude pending tasks with completed_at set.

        Defensive measure: Even if corruption occurs (status='pending' but
        completed_at is set), don't show these tasks to agents.
        """
        # Create a normal pending task
        db.create_task('normal-task', 'Normal pending task', 'Description')

        # Create a corrupted task (simulate corruption by direct SQL)
        # This should NEVER happen with our fixes, but defense in depth
        db.create_task('corrupted-task', 'Corrupted task', 'Description')
        db.execute(
            "UPDATE tasks SET completed_at = CURRENT_TIMESTAMP WHERE id = 'corrupted-task'"
        )

        # Get available tasks
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]

        # Should only see normal task, not corrupted one
        assert 'normal-task' in task_ids
        assert 'corrupted-task' not in task_ids, "Corrupted task should be excluded"

    def test_claim_task_rejects_completed_at_pending(self, db):
        """claim_task should reject pending tasks with completed_at set."""
        db.register_agent('test-agent', 12345)

        # Create corrupted task
        db.create_task('corrupted-task', 'Corrupted task', 'Description')
        db.execute(
            "UPDATE tasks SET completed_at = CURRENT_TIMESTAMP WHERE id = 'corrupted-task'"
        )

        # Try to claim corrupted task
        with pytest.raises(ValueError, match="Cannot claim task"):
            db.claim_task('corrupted-task', 'test-agent')

        # Task should remain pending (not claimed)
        task = db.get_task('corrupted-task')
        assert task['status'] == 'pending'
        assert task['owner'] is None

    def test_unregister_preserves_completed_tasks(self, db):
        """unregister_agent should not reset completed tasks to pending.

        Regression test for the unregister_agent corruption bug.
        """
        db.register_agent('test-agent', 12345)

        # Complete a task
        db.create_task('completed-task', 'Completed task', 'Description')
        db.claim_task('completed-task', 'test-agent')
        db.complete_task('completed-task', 'test-agent')

        # Verify completed
        task_before = db.get_task('completed-task')
        assert task_before['status'] == 'completed'
        assert task_before['completed_at'] is not None

        # Unregister agent
        db.unregister_agent('test-agent')

        # Task should still be completed (NOT reset to pending)
        task_after = db.get_task('completed-task')
        assert task_after['status'] == 'completed', "Completed task was corrupted by unregister!"
        assert task_after['completed_at'] is not None
        # Note: owner is cleared by FK constraint (ON DELETE SET NULL), but status stays 'completed'

    def test_unregister_releases_in_progress_tasks(self, db):
        """unregister_agent should release in_progress tasks."""
        db.register_agent('test-agent', 12345)

        # Claim but don't complete
        db.create_task('in-progress-task', 'In progress task', 'Description')
        db.claim_task('in-progress-task', 'test-agent')

        # Unregister agent
        db.unregister_agent('test-agent')

        # Task should be released to pending
        task = db.get_task('in-progress-task')
        assert task['status'] == 'pending'
        assert task['owner'] is None
        assert task['completed_at'] is None

    def test_corruption_invariant_detection(self, db):
        """Verify that corruption can be detected via query."""
        # Create corrupted task
        db.create_task('corrupted-task', 'Corrupted task', 'Description')
        db.execute(
            "UPDATE tasks SET completed_at = CURRENT_TIMESTAMP WHERE id = 'corrupted-task'"
        )

        # Query for corruption
        corrupted = db.query(
            """
            SELECT id, status, completed_at
            FROM tasks
            WHERE status != 'completed' AND completed_at IS NOT NULL
            """
        )

        assert len(corrupted) == 1
        assert corrupted[0]['id'] == 'corrupted-task'
        assert corrupted[0]['status'] == 'pending'
        assert corrupted[0]['completed_at'] is not None

    def test_status_reports_corruption(self, db):
        """Status operation should report corrupted tasks as warnings."""
        from coord_service.operations import OperationHandler

        # Create corrupted task
        db.create_task('corrupted-task', 'Corrupted task', 'Description')
        db.execute(
            "UPDATE tasks SET completed_at = CURRENT_TIMESTAMP WHERE id = 'corrupted-task'"
        )

        handler = OperationHandler(db)
        status = handler.execute('status', {})

        # Should have warnings
        assert 'warnings' in status
        assert status['warnings']['corrupted_tasks'] == 1
        assert 'corrupted-task' in status['warnings']['sample_ids']
        assert 'completed_at set but status' in status['warnings']['message']

    def test_status_no_warnings_when_clean(self, db):
        """Status operation should not show warnings when no corruption."""
        from coord_service.operations import OperationHandler

        # Create normal task
        db.create_task('normal-task', 'Normal task', 'Description')

        handler = OperationHandler(db)
        status = handler.execute('status', {})

        # Should NOT have warnings
        assert 'warnings' not in status
