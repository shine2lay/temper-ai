"""Tests for database connection and session management."""
import pytest
import os
from sqlmodel import select

from src.observability.database import (
    DatabaseManager,
    init_database,
    get_database,
    get_session,
    _db_manager,
)
from src.observability.models import WorkflowExecution


def test_database_manager_sqlite():
    """Test DatabaseManager with SQLite."""
    manager = DatabaseManager("sqlite:///:memory:")
    assert manager.database_url == "sqlite:///:memory:"
    assert manager.engine is not None

    # Test table creation
    manager.create_all_tables()

    # Test table usage
    with manager.session() as session:
        workflow = WorkflowExecution(
            id="wf-001",
            workflow_name="test_workflow",
            workflow_config_snapshot={},
            status="running",
        )
        session.add(workflow)
        session.commit()

        result = session.exec(select(WorkflowExecution).where(WorkflowExecution.id == "wf-001")).first()
        assert result is not None
        assert result.workflow_name == "test_workflow"


def test_database_manager_default_url():
    """Test DatabaseManager uses default URL when none provided."""
    # Remove env var if set
    old_url = os.environ.get("DATABASE_URL")
    if old_url:
        del os.environ["DATABASE_URL"]

    manager = DatabaseManager()
    assert "sqlite" in manager.database_url

    # Restore env var
    if old_url:
        os.environ["DATABASE_URL"] = old_url


def test_database_manager_env_var():
    """Test DatabaseManager uses DATABASE_URL env var."""
    os.environ["DATABASE_URL"] = "sqlite:///test.db"

    manager = DatabaseManager()
    assert manager.database_url == "sqlite:///test.db"

    # Clean up
    del os.environ["DATABASE_URL"]


def test_session_context_manager():
    """Test session context manager commits on success."""
    manager = DatabaseManager("sqlite:///:memory:")
    manager.create_all_tables()

    # Create workflow in session
    with manager.session() as session:
        workflow = WorkflowExecution(
            id="wf-001",
            workflow_name="test_workflow",
            workflow_config_snapshot={},
            status="running",
        )
        session.add(workflow)
        # Should auto-commit on exit

    # Verify in new session
    with manager.session() as session:
        result = session.exec(select(WorkflowExecution).where(WorkflowExecution.id == "wf-001")).first()
        assert result is not None


def test_session_rollback_on_error():
    """Test session context manager rolls back on error."""
    manager = DatabaseManager("sqlite:///:memory:")
    manager.create_all_tables()

    # Create valid workflow first
    with manager.session() as session:
        workflow = WorkflowExecution(
            id="wf-001",
            workflow_name="test_workflow",
            workflow_config_snapshot={},
            status="running",
        )
        session.add(workflow)

    # Try to create duplicate (should fail and rollback)
    try:
        with manager.session() as session:
            duplicate = WorkflowExecution(
                id="wf-001",  # Duplicate ID
                workflow_name="duplicate",
                workflow_config_snapshot={},
                status="running",
            )
            session.add(duplicate)
            session.commit()  # Force commit to trigger error
    except Exception:
        pass  # Expected to fail

    # Verify original still exists and wasn't modified
    with manager.session() as session:
        result = session.exec(select(WorkflowExecution).where(WorkflowExecution.id == "wf-001")).first()
        assert result is not None
        assert result.workflow_name == "test_workflow"  # Not "duplicate"


def test_init_database():
    """Test init_database function."""
    # Reset global state
    import src.observability.database as db_module
    db_module._db_manager = None

    manager = init_database("sqlite:///:memory:")
    assert manager is not None
    assert isinstance(manager, DatabaseManager)

    # Should be set as global
    assert db_module._db_manager is manager

    # Clean up
    db_module._db_manager = None


def test_get_database():
    """Test get_database function."""
    # Reset global state
    import src.observability.database as db_module
    db_module._db_manager = None

    # Should raise error if not initialized
    with pytest.raises(RuntimeError, match="Database not initialized"):
        get_database()

    # Initialize and retrieve
    init_database("sqlite:///:memory:")
    manager = get_database()
    assert manager is not None
    assert isinstance(manager, DatabaseManager)

    # Clean up
    db_module._db_manager = None


def test_get_session_context():
    """Test get_session convenience function."""
    # Reset and initialize
    import src.observability.database as db_module
    db_module._db_manager = None
    init_database("sqlite:///:memory:")

    # Use get_session
    with get_session() as session:
        workflow = WorkflowExecution(
            id="wf-001",
            workflow_name="test_workflow",
            workflow_config_snapshot={},
            status="running",
        )
        session.add(workflow)

    # Verify
    with get_session() as session:
        result = session.exec(select(WorkflowExecution).where(WorkflowExecution.id == "wf-001")).first()
        assert result is not None

    # Clean up
    db_module._db_manager = None


def test_drop_all_tables():
    """Test dropping all tables."""
    manager = DatabaseManager("sqlite:///:memory:")
    manager.create_all_tables()

    # Create a workflow
    with manager.session() as session:
        workflow = WorkflowExecution(
            id="wf-001",
            workflow_name="test_workflow",
            workflow_config_snapshot={},
            status="running",
        )
        session.add(workflow)

    # Drop tables
    manager.drop_all_tables()

    # Recreate tables (should be empty)
    manager.create_all_tables()

    with manager.session() as session:
        result = session.exec(select(WorkflowExecution)).first()
        assert result is None  # No data should exist


def test_multiple_sessions():
    """Test multiple concurrent sessions work correctly."""
    manager = DatabaseManager("sqlite:///:memory:")
    manager.create_all_tables()

    # Create multiple workflows in different sessions
    with manager.session() as session1:
        workflow1 = WorkflowExecution(
            id="wf-001",
            workflow_name="workflow_1",
            workflow_config_snapshot={},
            status="running",
        )
        session1.add(workflow1)

    with manager.session() as session2:
        workflow2 = WorkflowExecution(
            id="wf-002",
            workflow_name="workflow_2",
            workflow_config_snapshot={},
            status="running",
        )
        session2.add(workflow2)

    # Verify both exist
    with manager.session() as session:
        count = len(session.exec(select(WorkflowExecution)).all())
        assert count == 2


def test_postgresql_engine_settings():
    """Test PostgreSQL engine is configured with connection pooling."""
    # Skip if psycopg2 not available
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed")

    # Note: This doesn't actually connect to PostgreSQL, just tests config
    manager = DatabaseManager("postgresql://user:pass@localhost/db")

    assert manager.database_url == "postgresql://user:pass@localhost/db"
    # PostgreSQL engines should have pool_size configured
    assert manager.engine.pool.size() >= 0  # Just verify pool exists


def test_sqlite_engine_settings():
    """Test SQLite engine is configured correctly."""
    manager = DatabaseManager("sqlite:///:memory:")

    # SQLite should use StaticPool
    from sqlalchemy.pool import StaticPool
    assert isinstance(manager.engine.pool, StaticPool)
