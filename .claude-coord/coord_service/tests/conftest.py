"""
Pytest configuration and shared fixtures.
"""

import os
import tempfile
import threading
import time
from pathlib import Path

import pytest
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from coord_service.database import Database
from coord_service.daemon import CoordinationDaemon
from coord_service.client import CoordinationClient
from coord_service.validator import StateValidator


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def coord_dir(temp_dir):
    """Create .claude-coord directory structure."""
    coord = Path(temp_dir) / '.claude-coord'
    coord.mkdir()
    (coord / 'task-specs').mkdir()
    (coord / 'backups').mkdir()
    return coord


@pytest.fixture
def db_path(coord_dir):
    """Database file path."""
    return str(coord_dir / 'coordination.db')


@pytest.fixture
def db(db_path):
    """Initialize database for testing."""
    database = Database(db_path)
    database.initialize()
    yield database
    # Cleanup connections
    try:
        # Import thread_local from database module
        from coord_service.database import _thread_local

        # Close connection if it exists
        if hasattr(_thread_local, 'conn'):
            try:
                _thread_local.conn.close()
            except:
                pass
            # CRITICAL: Delete the thread-local reference so next test gets fresh connection
            delattr(_thread_local, 'conn')
    except:
        pass


@pytest.fixture
def validator(db):
    """Create validator instance."""
    return StateValidator(db)


@pytest.fixture
def daemon(temp_dir):
    """Create daemon instance (not started)."""
    return CoordinationDaemon(temp_dir)


@pytest.fixture
def running_daemon(temp_dir):
    """Create and start daemon in background."""
    daemon = CoordinationDaemon(temp_dir)

    # Start daemon in thread
    thread = threading.Thread(
        target=daemon.start,
        kwargs={'daemonize': False},
        daemon=True
    )
    thread.start()

    # Wait for daemon to be ready
    time.sleep(1)

    yield daemon

    # Cleanup
    daemon.cleanup()


@pytest.fixture
def client(temp_dir):
    """Create client for running daemon."""
    return CoordinationClient(temp_dir)


@pytest.fixture
def sample_task_spec(coord_dir):
    """Create sample task spec file."""
    spec_path = coord_dir / 'task-specs' / 'test-high-example-01.md'
    spec_path.write_text("""# Task Specification: test-high-example-01

## Problem Statement
Example task for testing.

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Test Strategy
Test the implementation thoroughly.
""")
    return spec_path


@pytest.fixture(autouse=True)
def verify_database_invariants(request, db):
    """
    Automatically verify database invariants after each test.

    This fixture runs after every test to ensure no corruption was introduced.
    Critical for preventing regression of the completed_at corruption bug.
    """
    # Skip for tests that don't use the db fixture
    if 'db' not in request.fixturenames:
        yield
        return

    # Skip for tests that intentionally create corruption (marked with @pytest.mark.skip_invariants)
    if request.node.get_closest_marker('skip_invariants'):
        yield
        return

    yield  # Run the test

    # After test completes, verify invariants
    try:
        # Invariant 1: No task should have completed_at without status='completed'
        corrupted = db.query(
            "SELECT id, status, completed_at FROM tasks "
            "WHERE completed_at IS NOT NULL AND status != 'completed'"
        )
        assert len(corrupted) == 0, (
            f"Found {len(corrupted)} tasks with completed_at but wrong status: "
            f"{[r['id'] for r in corrupted]}"
        )

        # Invariant 2: No task should have status='in_progress' without owner
        orphaned = db.query(
            "SELECT id, status, owner FROM tasks "
            "WHERE status = 'in_progress' AND owner IS NULL"
        )
        assert len(orphaned) == 0, (
            f"Found {len(orphaned)} in_progress tasks without owner: "
            f"{[r['id'] for r in orphaned]}"
        )

        # Invariant 3: Completed tasks must have completed_at
        incomplete_completed = db.query(
            "SELECT id, status, completed_at FROM tasks "
            "WHERE status = 'completed' AND completed_at IS NULL"
        )
        assert len(incomplete_completed) == 0, (
            f"Found {len(incomplete_completed)} completed tasks without completed_at: "
            f"{[r['id'] for r in incomplete_completed]}"
        )

        # Invariant 4: In-progress tasks must have started_at
        unstartedprogress = db.query(
            "SELECT id, status, started_at FROM tasks "
            "WHERE status = 'in_progress' AND started_at IS NULL"
        )
        assert len(unstartedprogress) == 0, (
            f"Found {len(unstartedprogress)} in_progress tasks without started_at: "
            f"{[r['id'] for r in unstartedprogress]}"
        )

    except Exception as e:
        # Make invariant violations very visible
        pytest.fail(f"DATABASE INVARIANT VIOLATION: {e}")
