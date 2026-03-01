"""Schema migration utilities.

For production schema evolution, use Alembic-based migrations.
See docs/database/MIGRATION_SYSTEM.md for details.

The deprecated raw SQL migration functions (apply_migration, _validate_migration_sql,
_normalize_sql) have been removed. Use Alembic instead.
"""

import logging

from temper_ai.storage.database.manager import DatabaseManager, get_database

logger = logging.getLogger(__name__)


def create_schema(database_url: str | None = None) -> None:
    """Create all tables in the database.

    Args:
        database_url: Database URL. If None, uses existing database manager.
    """
    if database_url:
        db_manager = DatabaseManager(database_url)
    else:
        db_manager = get_database()

    db_manager.create_all_tables()


def drop_schema(database_url: str | None = None) -> None:
    """Drop all tables in the database. Use with caution!

    Args:
        database_url: Database URL. If None, uses existing database manager.
    """
    if database_url:
        db_manager = DatabaseManager(database_url)
    else:
        db_manager = get_database()

    db_manager.drop_all_tables()


def reset_schema(database_url: str | None = None) -> None:
    """Drop and recreate all tables. Use with caution!

    Args:
        database_url: Database URL. If None, uses existing database manager.
    """
    drop_schema(database_url)
    create_schema(database_url)
