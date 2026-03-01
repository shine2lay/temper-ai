"""
Tests for database migration utilities.

Tests schema management and version tracking.
Deprecated raw SQL migration functions (apply_migration, _validate_migration_sql)
have been removed; use Alembic for schema evolution.
"""

from unittest.mock import Mock, patch

import pytest
from sqlalchemy import text

from temper_ai.observability.migrations import (
    create_schema,
    drop_schema,
    reset_schema,
)
from temper_ai.storage.database.manager import DatabaseManager


@pytest.fixture
def test_db():
    """Create an in-memory test database."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    assert db is not None
    yield db


class TestCreateSchema:
    """Test create_schema function."""

    def test_create_schema_with_url(self):
        """Test creating schema with explicit database URL."""
        db_url = "sqlite:///:memory:"

        with patch("temper_ai.observability.migrations.DatabaseManager") as mock_cls:
            create_schema(db_url)
            mock_cls.assert_called_once_with(db_url)
            mock_cls.return_value.create_all_tables.assert_called_once()

    def test_create_schema_without_url(self):
        """Test creating schema without URL uses existing database."""
        with patch("temper_ai.observability.migrations.get_database") as mock_get_db:
            mock_db = Mock(spec=DatabaseManager)
            mock_get_db.return_value = mock_db

            create_schema()

            mock_get_db.assert_called_once()
            mock_db.create_all_tables.assert_called_once()
            assert mock_get_db.call_count == 1

    def test_create_schema_creates_tables(self):
        """Test that create_all_tables actually creates database tables."""
        db = DatabaseManager("sqlite:///:memory:")

        # Before creation, check initial table count
        with db.session() as session:
            result = session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            initial_tables = {row[0] for row in result}

        # Create tables
        db.create_all_tables()

        # Verify new tables were created
        with db.session() as session:
            result = session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            created_tables = {row[0] for row in result}

        new_tables = created_tables - initial_tables
        assert len(new_tables) > 0, "create_all_tables should create at least one table"


class TestDropSchema:
    """Test drop_schema function."""

    def test_drop_schema_with_url(self):
        """Test dropping schema with explicit database URL."""
        db_url = "sqlite:///:memory:"

        with patch("temper_ai.observability.migrations.DatabaseManager") as mock_cls:
            drop_schema(db_url)
            mock_cls.assert_called_once_with(db_url)
            mock_cls.return_value.drop_all_tables.assert_called_once()

    def test_drop_schema_without_url(self):
        """Test dropping schema without URL uses existing database."""
        with patch("temper_ai.observability.migrations.get_database") as mock_get_db:
            mock_db = Mock(spec=DatabaseManager)
            mock_get_db.return_value = mock_db

            drop_schema()

            mock_get_db.assert_called_once()
            mock_db.drop_all_tables.assert_called_once()
            assert mock_get_db.call_count == 1


class TestResetSchema:
    """Test reset_schema function."""

    def test_reset_schema_drops_and_creates(self):
        """Test that reset_schema drops then creates tables."""
        with (
            patch("temper_ai.observability.migrations.drop_schema") as mock_drop,
            patch("temper_ai.observability.migrations.create_schema") as mock_create,
        ):

            reset_schema("sqlite:///:memory:")

            mock_drop.assert_called_once_with("sqlite:///:memory:")
            mock_create.assert_called_once_with("sqlite:///:memory:")

    def test_reset_schema_without_url(self):
        """Test reset_schema without URL."""
        with (
            patch("temper_ai.observability.migrations.drop_schema") as mock_drop,
            patch("temper_ai.observability.migrations.create_schema") as mock_create,
        ):

            reset_schema()

            mock_drop.assert_called_once_with(None)
            mock_create.assert_called_once_with(None)


class TestDataPreservation:
    """Test that migrations preserve existing data."""

    def test_reset_schema_destroys_data(self, test_db):
        """Test that reset_schema drops tables, destroying existing data."""
        from sqlmodel import select

        from temper_ai.storage.database.models import WorkflowExecution

        # Insert data into a model table
        with test_db.session() as session:
            wf = WorkflowExecution(
                id="wf-destroy-test",
                workflow_name="destroy_test",
                workflow_config_snapshot={},
                status="completed",
            )
            session.add(wf)
            session.commit()

        # Verify data exists
        with test_db.session() as session:
            result = session.exec(
                select(WorkflowExecution).where(
                    WorkflowExecution.id == "wf-destroy-test"
                )
            ).first()
            assert result is not None

        # Drop and recreate tables
        test_db.drop_all_tables()
        test_db.create_all_tables()

        # Data should be gone after reset
        with test_db.session() as session:
            result = session.exec(
                select(WorkflowExecution).where(
                    WorkflowExecution.id == "wf-destroy-test"
                )
            ).first()
            assert result is None, "Data should be destroyed after reset"


class TestDeprecatedFunctionsRemoved:
    """Verify deprecated migration functions were removed (M-18)."""

    def test_apply_migration_removed(self):
        """apply_migration should no longer exist."""
        import temper_ai.observability.migrations as mig

        assert not hasattr(
            mig, "apply_migration"
        ), "apply_migration was removed; use Alembic instead"

    def test_validate_migration_sql_removed(self):
        """_validate_migration_sql should no longer exist."""
        import temper_ai.observability.migrations as mig

        assert not hasattr(
            mig, "_validate_migration_sql"
        ), "_validate_migration_sql was removed; use Alembic instead"

    def test_normalize_sql_removed(self):
        """_normalize_sql should no longer exist."""
        import temper_ai.observability.migrations as mig

        assert not hasattr(
            mig, "_normalize_sql"
        ), "_normalize_sql was removed; use Alembic instead"

    def test_migration_security_error_removed(self):
        """MigrationSecurityError was removed (dead code)."""
        import temper_ai.observability.migrations as mig

        assert not hasattr(
            mig, "MigrationSecurityError"
        ), "MigrationSecurityError was removed"
