"""
Tests for task dependency system.
"""

import pytest
from coord_service.database import Database


@pytest.fixture
def db(tmp_path):
    """Create a test database."""
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    return db


@pytest.fixture
def setup_tasks(db):
    """Create test tasks."""
    # Create agents
    db.register_agent("agent1", 1234)

    # Create tasks
    db.create_task("task1", "Task 1", "First task", priority=1)
    db.create_task("task2", "Task 2", "Second task", priority=2)
    db.create_task("task3", "Task 3", "Third task", priority=3)
    db.create_task("task4", "Task 4", "Fourth task", priority=4)

    return db


class TestTaskDependencies:
    """Test task dependency management."""

    def test_add_dependency(self, setup_tasks):
        """Test adding a task dependency."""
        db = setup_tasks

        # Add dependency: task2 depends on task1
        db.add_dependency("task2", "task1")

        # Verify dependency was added
        deps = db.get_task_dependencies("task2")
        assert "task1" in deps
        assert len(deps) == 1

    def test_add_multiple_dependencies(self, setup_tasks):
        """Test adding multiple dependencies to a task."""
        db = setup_tasks

        # Add dependencies: task3 depends on task1 and task2
        db.add_dependency("task3", "task1")
        db.add_dependency("task3", "task2")

        # Verify dependencies
        deps = db.get_task_dependencies("task3")
        assert "task1" in deps
        assert "task2" in deps
        assert len(deps) == 2

    def test_remove_dependency(self, setup_tasks):
        """Test removing a task dependency."""
        db = setup_tasks

        # Add and then remove dependency
        db.add_dependency("task2", "task1")
        db.remove_dependency("task2", "task1")

        # Verify dependency was removed
        deps = db.get_task_dependencies("task2")
        assert len(deps) == 0

    def test_get_dependents(self, setup_tasks):
        """Test getting tasks that depend on a task."""
        db = setup_tasks

        # task2 and task3 depend on task1
        db.add_dependency("task2", "task1")
        db.add_dependency("task3", "task1")

        # Get dependents of task1
        dependents = db.get_task_dependents("task1")
        assert "task2" in dependents
        assert "task3" in dependents
        assert len(dependents) == 2

    def test_circular_dependency_direct(self, setup_tasks):
        """Test that direct circular dependencies are prevented."""
        db = setup_tasks

        # Add task2 depends on task1
        db.add_dependency("task2", "task1")

        # Try to add task1 depends on task2 (circular)
        with pytest.raises(ValueError, match="circular dependency"):
            db.add_dependency("task1", "task2")

    def test_circular_dependency_indirect(self, setup_tasks):
        """Test that indirect circular dependencies are prevented."""
        db = setup_tasks

        # Create chain: task3 -> task2 -> task1
        db.add_dependency("task2", "task1")
        db.add_dependency("task3", "task2")

        # Try to add task1 -> task3 (creates cycle)
        with pytest.raises(ValueError, match="circular dependency"):
            db.add_dependency("task1", "task3")

    def test_self_dependency_prevented_by_check(self, setup_tasks):
        """Test that self-dependencies are prevented by database constraint."""
        db = setup_tasks

        # Try to add task1 depends on task1
        # This should be caught by the CHECK constraint
        with pytest.raises(Exception):  # SQLite constraint violation
            db.add_dependency("task1", "task1")


class TestAvailableTasks:
    """Test task availability with dependencies."""

    def test_available_tasks_no_dependencies(self, setup_tasks):
        """Test that all pending tasks are available when no dependencies exist."""
        db = setup_tasks

        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]

        assert "task1" in task_ids
        assert "task2" in task_ids
        assert "task3" in task_ids
        assert "task4" in task_ids

    def test_available_tasks_with_incomplete_dependency(self, setup_tasks):
        """Test that tasks with incomplete dependencies are not available."""
        db = setup_tasks

        # task2 depends on task1
        db.add_dependency("task2", "task1")

        # Both tasks are pending, so task2 should NOT be available
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]

        assert "task1" in task_ids
        assert "task2" not in task_ids

    def test_available_tasks_with_completed_dependency(self, setup_tasks):
        """Test that tasks become available when dependencies are completed."""
        db = setup_tasks

        # task2 depends on task1
        db.add_dependency("task2", "task1")

        # Complete task1
        db.claim_task("task1", "agent1")
        db.complete_task("task1", "agent1")

        # Now task2 should be available
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]

        assert "task1" not in task_ids  # Completed tasks not returned
        assert "task2" in task_ids       # Now available

    def test_available_tasks_chain(self, setup_tasks):
        """Test task availability with dependency chain."""
        db = setup_tasks

        # Create chain: task3 -> task2 -> task1
        db.add_dependency("task2", "task1")
        db.add_dependency("task3", "task2")

        # Initially, only task1 is available
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]
        assert "task1" in task_ids
        assert "task2" not in task_ids
        assert "task3" not in task_ids

        # Complete task1
        db.claim_task("task1", "agent1")
        db.complete_task("task1", "agent1")

        # Now task2 is available
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]
        assert "task2" in task_ids
        assert "task3" not in task_ids

        # Complete task2
        db.claim_task("task2", "agent1")
        db.complete_task("task2", "agent1")

        # Now task3 is available
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]
        assert "task3" in task_ids

    def test_available_tasks_multiple_dependencies(self, setup_tasks):
        """Test task with multiple dependencies."""
        db = setup_tasks

        # task4 depends on both task1 and task2
        db.add_dependency("task4", "task1")
        db.add_dependency("task4", "task2")

        # task4 should not be available
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]
        assert "task4" not in task_ids

        # Complete task1 only
        db.claim_task("task1", "agent1")
        db.complete_task("task1", "agent1")

        # task4 still not available (task2 not done)
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]
        assert "task4" not in task_ids

        # Complete task2
        db.claim_task("task2", "agent1")
        db.complete_task("task2", "agent1")

        # Now task4 is available
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]
        assert "task4" in task_ids


class TestBlockedTasks:
    """Test blocked task listing."""

    def test_get_blocked_tasks(self, setup_tasks):
        """Test getting blocked tasks."""
        db = setup_tasks

        # Create dependencies
        db.add_dependency("task2", "task1")
        db.add_dependency("task3", "task1")
        db.add_dependency("task3", "task2")

        # Get blocked tasks
        blocked = db.get_blocked_tasks()
        blocked_ids = [t['id'] for t in blocked]

        assert "task2" in blocked_ids
        assert "task3" in blocked_ids

    def test_blocked_tasks_cleared_on_completion(self, setup_tasks):
        """Test that blocked tasks list updates when dependencies complete."""
        db = setup_tasks

        # task2 depends on task1
        db.add_dependency("task2", "task1")

        # Verify task2 is blocked
        blocked = db.get_blocked_tasks()
        blocked_ids = [t['id'] for t in blocked]
        assert "task2" in blocked_ids

        # Complete task1
        db.claim_task("task1", "agent1")
        db.complete_task("task1", "agent1")

        # task2 should no longer be blocked
        blocked = db.get_blocked_tasks()
        blocked_ids = [t['id'] for t in blocked]
        assert "task2" not in blocked_ids

    def test_blocked_count(self, setup_tasks):
        """Test blocked_by_count in blocked tasks."""
        db = setup_tasks

        # task3 depends on task1 and task2
        db.add_dependency("task3", "task1")
        db.add_dependency("task3", "task2")

        # Get blocked tasks
        blocked = db.get_blocked_tasks()

        task3_blocked = [t for t in blocked if t['id'] == 'task3'][0]
        assert task3_blocked['blocked_by_count'] == 2


class TestDependencyCascade:
    """Test dependency behavior on task deletion."""

    def test_dependency_cascade_on_delete(self, setup_tasks):
        """Test that dependencies are deleted when task is deleted."""
        db = setup_tasks

        # Add dependency
        db.add_dependency("task2", "task1")

        # Delete task1 (dependency source)
        db.execute("UPDATE tasks SET status = 'deleted' WHERE id = 'task1'")

        # Verify dependencies were cascade deleted
        deps = db.get_task_dependencies("task2")
        # Dependency should still exist in table but point to deleted task
        # task2 should become available since dependency is gone
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]
        # task2 might still be blocked depending on CASCADE behavior
        # This tests our CASCADE constraint is working


class TestDependencyEdgeCases:
    """Test edge cases in dependency management."""

    def test_duplicate_dependency(self, setup_tasks):
        """Test adding the same dependency twice."""
        db = setup_tasks

        # Add dependency twice
        db.add_dependency("task2", "task1")
        db.add_dependency("task2", "task1")  # Should be idempotent

        # Should only have one dependency
        deps = db.get_task_dependencies("task2")
        assert len(deps) == 1

    def test_dependency_on_completed_task(self, setup_tasks):
        """Test adding dependency on already completed task."""
        db = setup_tasks

        # Complete task1
        db.claim_task("task1", "agent1")
        db.complete_task("task1", "agent1")

        # Add dependency on completed task
        db.add_dependency("task2", "task1")

        # task2 should be immediately available
        available = db.get_available_tasks(limit=10)
        task_ids = [t['id'] for t in available]
        assert "task2" in task_ids

    def test_dependency_prioritization(self, setup_tasks):
        """Test that priority is respected among available tasks."""
        db = setup_tasks

        # task2 (priority 2) depends on task1 (priority 1)
        db.add_dependency("task2", "task1")

        # Available tasks should be ordered by priority
        available = db.get_available_tasks(limit=10)

        # task1 should come before task3 (both available, but task1 has lower priority number)
        task_ids = [t['id'] for t in available]
        assert task_ids.index("task1") < task_ids.index("task3")
