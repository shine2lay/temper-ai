"""Schema migration utilities."""
from typing import Optional
import logging
from sqlmodel import SQLModel
from sqlalchemy import text
from .database import DatabaseManager, get_database

logger = logging.getLogger(__name__)


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
                text("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1")
            )
            row = result.fetchone()
            return row[0] if row else None
    except Exception:
        # Table doesn't exist yet
        return None


def _validate_migration_sql(sql: str) -> None:
    """Validate migration SQL for basic safety checks.

    Args:
        sql: SQL migration script to validate.

    Raises:
        ValueError: If migration contains suspicious patterns.
    """
    if not sql or not sql.strip():
        raise ValueError("Migration SQL cannot be empty")

    # Check for dangerous patterns
    dangerous_patterns = [
        "DROP DATABASE",
        "CREATE USER",
        "GRANT ALL",
        "REVOKE ALL",
        "XP_",  # SQL Server extended procedures
        "SP_",  # Stored procedures
    ]

    sql_upper = sql.upper()
    for pattern in dangerous_patterns:
        if pattern in sql_upper:
            logger.warning(f"Migration contains suspicious pattern: {pattern}")
            raise ValueError(f"Migration contains potentially dangerous pattern: {pattern}")


def apply_migration(db_manager: DatabaseManager, migration_sql: str, version: str) -> None:
    """Apply a migration script.

    Args:
        db_manager: Database manager instance.
        migration_sql: SQL migration script (MUST be from trusted source).
        version: Version identifier for this migration.

    Raises:
        ValueError: If migration_sql contains suspicious patterns.
    """
    # Validate migration script
    _validate_migration_sql(migration_sql)

    with db_manager.session() as session:
        # Execute migration
        logger.info(f"Applying migration: {version}")
        session.execute(text(migration_sql))

        # Record migration with parameterized query
        session.execute(
            text(
                "INSERT INTO schema_version (version, applied_at) "
                "VALUES (:version, CURRENT_TIMESTAMP)"
            ),
            {"version": version}
        )
        logger.info(f"Migration {version} applied successfully")
