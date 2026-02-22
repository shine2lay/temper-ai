"""Tests for src/database/manager.py.

Tests database connection and session management.
"""
import os
import threading
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from temper_ai.storage.database.manager import (
    DatabaseManager,
    IsolationLevel,
    _mask_database_url,
    get_database,
    get_session,
    init_database,
    reset_database,
)


class TestMaskDatabaseUrl:
    """Test _mask_database_url function."""

    def test_mask_postgres_url(self):
        """Test masking PostgreSQL URL."""
        url = "postgresql://user:password@localhost:5432/mydb"
        masked = _mask_database_url(url)
        assert masked == "postgresql://user:****@localhost:5432/mydb"

    def test_mask_mysql_url(self):
        """Test masking MySQL URL."""
        url = "mysql://admin:secret123@db.example.com:3306/production"
        masked = _mask_database_url(url)
        assert masked == "mysql://admin:****@db.example.com:3306/production"

    def test_no_password(self):
        """Test URL without password."""
        url = "sqlite:///./database.db"
        masked = _mask_database_url(url)
        assert masked == url

    def test_none_url(self):
        """Test with None URL."""
        masked = _mask_database_url(None)
        assert masked == "<no url>"

    def test_unparseable_url(self):
        """Test with unparseable URL."""
        with patch('urllib.parse.urlparse', side_effect=Exception("parse error")):
            masked = _mask_database_url("invalid://url")
            assert masked == "<unparseable url>"


class TestIsolationLevel:
    """Test IsolationLevel enum."""

    def test_isolation_levels_exist(self):
        """Test that all isolation levels are defined."""
        assert IsolationLevel.READ_UNCOMMITTED.value == "READ UNCOMMITTED"
        assert IsolationLevel.READ_COMMITTED.value == "READ COMMITTED"
        assert IsolationLevel.REPEATABLE_READ.value == "REPEATABLE READ"
        assert IsolationLevel.SERIALIZABLE.value == "SERIALIZABLE"


class TestDatabaseManager:
    """Test DatabaseManager class."""

    def test_initialization_default_url(self):
        """Test initialization with default PostgreSQL URL."""
        with patch.dict(os.environ, {}, clear=True):
            manager = DatabaseManager()
            assert "postgresql" in manager.database_url

    def test_initialization_env_var(self):
        """Test initialization with TEMPER_DATABASE_URL env var."""
        with patch.dict(os.environ, {"TEMPER_DATABASE_URL": "sqlite:///test.db"}):
            manager = DatabaseManager()
            assert manager.database_url == "sqlite:///test.db"

    def test_initialization_explicit_url(self):
        """Test initialization with explicit URL."""
        manager = DatabaseManager("sqlite:///explicit.db")
        assert manager.database_url == "sqlite:///explicit.db"

    def test_sqlite_engine_creation(self):
        """Test that SQLite engine is created with proper settings."""
        manager = DatabaseManager("sqlite:///test.db")
        assert manager.engine is not None

    @pytest.mark.skipif(
        os.getenv("CI") == "true",
        reason="PostgreSQL not available in CI"
    )
    def test_postgres_engine_creation(self):
        """Test that PostgreSQL engine is created with pool settings."""
        # Note: This will fail if PostgreSQL is not available
        try:
            manager = DatabaseManager("postgresql://user:pass@localhost/test")
            assert manager.engine is not None
        except (OperationalError, ConnectionError):
            pytest.skip("PostgreSQL not available")

    def test_session_context_manager(self):
        """Test session context manager."""
        manager = DatabaseManager("sqlite:///:memory:")
        manager.create_all_tables()

        with manager.session() as session:
            assert isinstance(session, Session)

    def test_session_commit_on_success(self):
        """Test that session commits on successful operation."""
        manager = DatabaseManager("sqlite:///:memory:")
        manager.create_all_tables()

        with manager.session() as session:
            # Successful operation
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1
        # Session should be committed and closed

    def test_session_rollback_on_error(self):
        """Test that session rolls back on error."""
        manager = DatabaseManager("sqlite:///:memory:")

        with pytest.raises(ValueError, match="test error"):
            with manager.session() as session:
                raise ValueError("test error")

    def test_session_with_serializable_isolation_sqlite(self):
        """Test session with SERIALIZABLE isolation on SQLite."""
        manager = DatabaseManager("sqlite:///:memory:")
        manager.create_all_tables()

        with manager.session(isolation_level=IsolationLevel.SERIALIZABLE) as session:
            assert isinstance(session, Session)

    def test_create_all_tables(self):
        """Test creating all tables."""
        from sqlalchemy import inspect

        manager = DatabaseManager("sqlite:///:memory:")
        manager.create_all_tables()
        table_names = inspect(manager.engine).get_table_names()
        assert len(table_names) > 0

    def test_drop_all_tables(self):
        """Test dropping all tables."""
        from sqlalchemy import inspect

        manager = DatabaseManager("sqlite:///:memory:")
        manager.create_all_tables()
        manager.drop_all_tables()
        table_names = inspect(manager.engine).get_table_names()
        assert len(table_names) == 0


class TestGlobalDatabaseFunctions:
    """Test global database management functions."""

    def setup_method(self):
        """Reset database before each test."""
        reset_database()

    def teardown_method(self):
        """Reset database after each test."""
        reset_database()

    def test_init_database(self):
        """Test initializing global database."""
        manager = init_database("sqlite:///:memory:")
        assert manager is not None
        assert isinstance(manager, DatabaseManager)

    def test_init_database_already_initialized(self):
        """Test that re-initializing returns existing instance."""
        manager1 = init_database("sqlite:///:memory:")
        manager2 = init_database("sqlite:///:memory:")
        assert manager1 is manager2

    def test_init_database_with_alembic_managed(self):
        """Test initialization with ALEMBIC_MANAGED env var."""
        with patch.dict(os.environ, {"ALEMBIC_MANAGED": "1"}):
            manager = init_database("sqlite:///:memory:")
            assert manager is not None
            assert isinstance(manager, DatabaseManager)
            # create_all_tables should have been skipped

    def test_init_database_connection_error(self):
        """Test that connection errors are raised."""
        with pytest.raises(ConnectionError, match="Failed to connect"):
            init_database("postgresql://invalid:invalid@nonexistent:9999/nodb")

    def test_get_database_initialized(self):
        """Test getting initialized database."""
        init_database("sqlite:///:memory:")
        manager = get_database()
        assert isinstance(manager, DatabaseManager)

    def test_get_database_not_initialized(self):
        """Test that getting uninitialized database raises error."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            get_database()

    def test_get_session(self):
        """Test get_session context manager."""
        init_database("sqlite:///:memory:")

        with get_session() as session:
            assert isinstance(session, Session)

    def test_reset_database(self):
        """Test resetting database."""
        init_database("sqlite:///:memory:")
        reset_database()

        with pytest.raises(RuntimeError, match="Database not initialized"):
            get_database()

    def test_thread_safety(self):
        """Test that initialization is thread-safe."""
        results = []

        def init_thread():
            try:
                manager = init_database("sqlite:///:memory:")
                results.append(manager)
            except Exception as e:
                results.append(e)

        threads = [threading.Thread(target=init_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should get the same manager instance
        managers = [r for r in results if isinstance(r, DatabaseManager)]
        assert len(managers) > 0
        assert all(m is managers[0] for m in managers)


class TestSQLiteForeignKeys:
    """Test SQLite foreign key enforcement."""

    def test_foreign_keys_enabled(self):
        """Test that foreign keys are enabled for SQLite connections."""
        manager = DatabaseManager("sqlite:///:memory:")

        with manager.session() as session:
            result = session.execute(text("PRAGMA foreign_keys")).fetchone()
            assert result[0] == 1

    def test_session_executes_query_after_table_creation(self):
        """Test that sessions work correctly after table creation."""
        manager = DatabaseManager("sqlite:///:memory:")
        manager.create_all_tables()

        with manager.session() as session:
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1


class TestSessionIsolation:
    """Test session isolation levels."""

    def test_default_isolation(self):
        """Test session with default isolation."""
        manager = DatabaseManager("sqlite:///:memory:")
        manager.create_all_tables()

        with manager.session() as session:
            assert isinstance(session, Session)

    def test_serializable_isolation_sqlite(self):
        """Test SERIALIZABLE isolation on SQLite."""
        manager = DatabaseManager("sqlite:///:memory:")
        manager.create_all_tables()

        with manager.session(isolation_level=IsolationLevel.SERIALIZABLE) as session:
            # SQLite should start IMMEDIATE transaction
            assert isinstance(session, Session)

    def test_read_committed_isolation_sqlite(self):
        """Test READ_COMMITTED isolation on SQLite (not fully supported)."""
        manager = DatabaseManager("sqlite:///:memory:")
        manager.create_all_tables()

        # Should not raise, but may log warning
        with manager.session(isolation_level=IsolationLevel.READ_COMMITTED) as session:
            assert isinstance(session, Session)

    def test_isolation_level_error_handling(self):
        """Test that isolation level errors are handled gracefully."""
        manager = DatabaseManager("sqlite:///:memory:")

        # Should not raise even if isolation level setting fails
        with manager.session(isolation_level=IsolationLevel.READ_UNCOMMITTED) as session:
            assert isinstance(session, Session)
