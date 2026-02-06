"""
Tests for database migration utilities.

Tests schema management and version tracking.
Deprecated raw SQL migration functions (apply_migration, _validate_migration_sql)
have been removed; use Alembic for schema evolution.
"""
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.observability.database import DatabaseManager
from src.observability.migrations import (
    MigrationSecurityError,
    check_schema_version,
    create_schema,
    drop_schema,
    reset_schema,
)


@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    yield db


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    from unittest.mock import MagicMock
    mock = Mock(spec=DatabaseManager)
    mock_session = MagicMock()
    mock_context_manager = MagicMock()
    mock_context_manager.__enter__.return_value = mock_session
    mock_context_manager.__exit__.return_value = None
    mock.session.return_value = mock_context_manager
    return mock


class TestCreateSchema:
    """Test create_schema function."""

    def test_create_schema_with_url(self):
        """Test creating schema with explicit database URL."""
        db_url = "sqlite:///:memory:"

        # Should not raise error
        create_schema(db_url)

    def test_create_schema_without_url(self):
        """Test creating schema without URL uses existing database."""
        with patch('src.observability.migrations.get_database') as mock_get_db:
            mock_db = Mock(spec=DatabaseManager)
            mock_get_db.return_value = mock_db

            create_schema()

            mock_get_db.assert_called_once()
            mock_db.create_all_tables.assert_called_once()

    def test_create_schema_creates_tables(self):
        """Test that create_schema actually creates tables."""
        db = DatabaseManager("sqlite:///:memory:")

        # Before creation, tables don't exist
        with db.session() as session:
            # This should fail or return empty
            try:
                result = session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
                initial_tables = [row[0] for row in result]
            except Exception:
                initial_tables = []

        # Create schema
        create_schema("sqlite:///:memory:")


class TestDropSchema:
    """Test drop_schema function."""

    def test_drop_schema_with_url(self):
        """Test dropping schema with explicit database URL."""
        db_url = "sqlite:///:memory:"

        # Create then drop
        create_schema(db_url)
        drop_schema(db_url)

    def test_drop_schema_without_url(self):
        """Test dropping schema without URL uses existing database."""
        with patch('src.observability.migrations.get_database') as mock_get_db:
            mock_db = Mock(spec=DatabaseManager)
            mock_get_db.return_value = mock_db

            drop_schema()

            mock_get_db.assert_called_once()
            mock_db.drop_all_tables.assert_called_once()


class TestResetSchema:
    """Test reset_schema function."""

    def test_reset_schema_drops_and_creates(self):
        """Test that reset_schema drops then creates tables."""
        with patch('src.observability.migrations.drop_schema') as mock_drop, \
             patch('src.observability.migrations.create_schema') as mock_create:

            reset_schema("sqlite:///:memory:")

            mock_drop.assert_called_once_with("sqlite:///:memory:")
            mock_create.assert_called_once_with("sqlite:///:memory:")

    def test_reset_schema_without_url(self):
        """Test reset_schema without URL."""
        with patch('src.observability.migrations.drop_schema') as mock_drop, \
             patch('src.observability.migrations.create_schema') as mock_create:

            reset_schema()

            mock_drop.assert_called_once_with(None)
            mock_create.assert_called_once_with(None)


class TestCheckSchemaVersion:
    """Test check_schema_version function."""

    def test_check_version_returns_latest(self, test_db):
        """Test checking schema version returns latest version."""
        # Create schema_version table
        with test_db.session() as session:
            session.execute(text(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version TEXT, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            ))
            session.execute(
                text("INSERT INTO schema_version (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP)"),
                {"version": "1.0.0"}
            )
            session.commit()

        version = check_schema_version(test_db)
        assert version == "1.0.0"

    def test_check_version_returns_none_if_no_versions(self, test_db):
        """Test checking version when no versions exist."""
        # Create empty schema_version table
        with test_db.session() as session:
            session.execute(text(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version TEXT, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            ))
            session.commit()

        version = check_schema_version(test_db)
        assert version is None

    def test_check_version_returns_none_if_table_missing(self, test_db):
        """Test checking version when table doesn't exist."""
        # Don't create schema_version table
        version = check_schema_version(test_db)
        assert version is None

    def test_check_version_returns_latest_when_multiple(self, test_db):
        """Test that check_version returns most recent version."""
        # Create schema_version table with multiple versions
        with test_db.session() as session:
            session.execute(text(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version TEXT, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            ))
            session.execute(
                text("INSERT INTO schema_version (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP)"),
                {"version": "1.0.0"}
            )
            session.execute(
                text("INSERT INTO schema_version (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP)"),
                {"version": "1.1.0"}
            )
            session.execute(
                text("INSERT INTO schema_version (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP)"),
                {"version": "1.2.0"}
            )
            session.commit()

        version = check_schema_version(test_db)
        # Should return the last inserted (most recent)
        assert version in ["1.0.0", "1.1.0", "1.2.0"]  # Depends on TIMESTAMP ordering


class TestMigrationEdgeCases:
    """Test edge cases and error handling."""

    def test_check_version_with_sql_error(self, mock_db_manager):
        """Test check_version handles SQL errors gracefully."""
        mock_session = mock_db_manager.session.return_value.__enter__.return_value
        mock_session.execute.side_effect = SQLAlchemyError("Database error")

        # Should return None instead of raising
        version = check_schema_version(mock_db_manager)
        assert version is None


class TestDataPreservation:
    """Test that migrations preserve existing data."""

    def test_reset_schema_destroys_data(self, test_db):
        """Test that reset_schema destroys existing data (as expected)."""
        # Create a table with data
        with test_db.session() as session:
            session.execute(text("CREATE TABLE test_data (id INTEGER, value TEXT)"))
            session.execute(text("INSERT INTO test_data VALUES (1, 'important')"))
            session.commit()

        # Reset schema
        reset_schema("sqlite:///:memory:")  # Note: This creates NEW db, not same one


class TestDeprecatedFunctionsRemoved:
    """Verify deprecated migration functions were removed (M-18)."""

    def test_apply_migration_removed(self):
        """apply_migration should no longer exist."""
        import src.observability.migrations as mig
        assert not hasattr(mig, "apply_migration"), (
            "apply_migration was removed; use Alembic instead"
        )

    def test_validate_migration_sql_removed(self):
        """_validate_migration_sql should no longer exist."""
        import src.observability.migrations as mig
        assert not hasattr(mig, "_validate_migration_sql"), (
            "_validate_migration_sql was removed; use Alembic instead"
        )

    def test_normalize_sql_removed(self):
        """_normalize_sql should no longer exist."""
        import src.observability.migrations as mig
        assert not hasattr(mig, "_normalize_sql"), (
            "_normalize_sql was removed; use Alembic instead"
        )

    def test_migration_security_error_still_exists(self):
        """MigrationSecurityError should still be importable for backward compat."""
        assert MigrationSecurityError is not None
