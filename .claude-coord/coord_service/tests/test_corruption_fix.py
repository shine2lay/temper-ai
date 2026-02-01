"""
Tests for database corruption fixes.

Regression tests for the bug where tasks with NULL owners
could have completed_at set without status being updated.
"""

import pytest
from coord_service.database import Database


class TestCorruptionFix:
    """Test that database operations properly validate state changes."""

    def test_cannot_complete_task_without_owner(self, db):
        """Test that completing a task with NULL owner raises an error."""
        # Create a task without an owner
        task_id = "test-orphan-task"
        db.create_task(
            task_id=task_id,
            subject="Test orphan task",
            description="Task without owner",
            active_form="Testing"
        )

        # Try to complete it - should fail
        with pytest.raises(ValueError, match="Cannot complete task"):
            db.complete_task(task_id, "any-agent")

        # Verify task is still pending and has no completed_at
        task = db.get_task(task_id)
        assert task['status'] == 'pending'
        assert task['completed_at'] is None

    def test_cannot_complete_task_with_wrong_owner(self, db):
        """Test that completing a task with wrong agent raises an error."""
        task_id = "test-owned-task"

        # Create and claim task
        db.create_task(
            task_id=task_id,
            subject="Test owned task",
            description="Task with specific owner",
            active_form="Testing"
        )
        db.claim_task(task_id, "agent-1")

        # Try to complete with different agent - should fail
        with pytest.raises(ValueError, match="Cannot complete task"):
            db.complete_task(task_id, "agent-2")

        # Verify task is still in_progress
        task = db.get_task(task_id)
        assert task['status'] == 'in_progress'
        assert task['owner'] == 'agent-1'
        assert task['completed_at'] is None

    def test_cannot_claim_already_claimed_task(self, db):
        """Test that claiming an already claimed task raises an error."""
        task_id = "test-claim-race"

        # Create and claim task
        db.create_task(
            task_id=task_id,
            subject="Test claim race",
            description="Task to test claim race condition",
            active_form="Testing"
        )
        db.claim_task(task_id, "agent-1")

        # Try to claim again with different agent - should fail
        with pytest.raises(ValueError, match="Cannot claim task"):
            db.claim_task(task_id, "agent-2")

        # Verify task is still owned by agent-1
        task = db.get_task(task_id)
        assert task['status'] == 'in_progress'
        assert task['owner'] == 'agent-1'

    def test_successful_claim_and_complete_flow(self, db):
        """Test the happy path of claim and complete."""
        task_id = "test-happy-path"
        agent_id = "agent-happy"

        # Register agent
        db.register_agent(agent_id, 12345)

        # Create task
        db.create_task(
            task_id=task_id,
            subject="Test happy path",
            description="Normal task flow",
            active_form="Testing"
        )

        # Claim task
        db.claim_task(task_id, agent_id)
        task = db.get_task(task_id)
        assert task['status'] == 'in_progress'
        assert task['owner'] == agent_id
        assert task['started_at'] is not None

        # Complete task
        db.complete_task(task_id, agent_id)
        task = db.get_task(task_id)
        assert task['status'] == 'completed'
        assert task['owner'] == agent_id
        assert task['completed_at'] is not None

    def test_no_corruption_on_failed_complete(self, db, tmp_path):
        """Test that failed complete doesn't leave partial state."""
        task_id = "test-corruption-check"

        # Create task without owner
        db.create_task(
            task_id=task_id,
            subject="Test corruption",
            description="Check no partial updates",
            active_form="Testing"
        )

        # Try to complete - should fail
        with pytest.raises(ValueError):
            db.complete_task(task_id, "fake-agent")

        # Query raw database to verify NO corruption
        rows = db.query(
            """
            SELECT status, completed_at
            FROM tasks
            WHERE id = ? AND completed_at IS NOT NULL AND status != 'completed'
            """,
            (task_id,)
        )

        # Should be empty - no corrupted records
        assert len(rows) == 0, "Found corrupted task with completed_at but wrong status"
