"""Schema migration utilities.

For production schema evolution, use Alembic-based migrations.
See docs/database/MIGRATION_SYSTEM.md for details.

The deprecated raw SQL migration functions (apply_migration, _validate_migration_sql,
_normalize_sql) have been removed. Use Alembic instead.
"""
import logging
from typing import Optional

from sqlalchemy import text

from src.constants.limits import DEFAULT_MIN_ITEMS
from src.utils.exceptions import SecurityError

from .database import DatabaseManager, get_database

logger = logging.getLogger(__name__)


class MigrationSecurityError(SecurityError):
    """Raised when migration validation fails security checks."""
    pass


def create_schema(database_url: Optional[str] = None) -> None:
    """Create all tables in the database.

    Args:
        database_url: Database URL. If None, uses existing database manager.
    """
    if database_url:
        db_manager = DatabaseManager(database_url)
    else:
        db_manager = get_database()

    db_manager.create_all_tables()


def drop_schema(database_url: Optional[str] = None) -> None:
    """Drop all tables in the database. Use with caution!

    Args:
        database_url: Database URL. If None, uses existing database manager.
    """
    if database_url:
        db_manager = DatabaseManager(database_url)
    else:
        db_manager = get_database()

    db_manager.drop_all_tables()


def reset_schema(database_url: Optional[str] = None) -> None:
    """Drop and recreate all tables. Use with caution!

    Args:
        database_url: Database URL. If None, uses existing database manager.
    """
    drop_schema(database_url)
    create_schema(database_url)


def check_schema_version(db_manager: DatabaseManager) -> Optional[str]:
    """Check the current schema version.

    Args:
        db_manager: Database manager instance.

    Returns:
        Schema version string or None if not tracked.
    """
    try:
        with db_manager.session() as session:
            result = session.execute(
                text(f"SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT {DEFAULT_MIN_ITEMS}")
            )
            row = result.fetchone()
            return row[0] if row else None
    except Exception:
        # Table doesn't exist yet
        return None
