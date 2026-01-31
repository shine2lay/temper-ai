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
    if hasattr(database, '_get_connection'):
        try:
            conn = database._get_connection()
            conn.close()
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
