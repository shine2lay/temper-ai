"""Schema migration utilities.

WARNING: This migration system has known security vulnerabilities.
For production use, please migrate to Alembic-based migrations.
See docs/database/MIGRATION_SYSTEM.md for details.
"""
from typing import Optional
import logging
import os
import re
import warnings
from sqlmodel import SQLModel
from sqlalchemy import text
from .database import DatabaseManager, get_database

logger = logging.getLogger(__name__)


class MigrationSecurityError(Exception):
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
                text("SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1")
            )
            row = result.fetchone()
            return row[0] if row else None
    except Exception:
        # Table doesn't exist yet
        return None


def _normalize_sql(sql: str) -> str:
    """Normalize SQL by removing comments and extra whitespace.

    Args:
        sql: Raw SQL string

    Returns:
        Normalized SQL string

    Raises:
        ValueError: If SQL exceeds maximum allowed size
    """
    # Prevent ReDoS attacks with extremely long input
    MAX_MIGRATION_SIZE = 1_000_000  # 1MB limit
    if len(sql) > MAX_MIGRATION_SIZE:
        raise ValueError(
            f"Migration SQL exceeds maximum allowed size "
            f"({len(sql)} bytes > {MAX_MIGRATION_SIZE} bytes)"
        )

    # Remove SQL line comments
    sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)

    # Remove SQL block comments
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)

    # Normalize whitespace
    sql = ' '.join(sql.split())

    return sql


def _validate_migration_sql(sql: str) -> None:
    """Validate migration SQL for basic safety checks.

    SECURITY NOTE: This validation is NOT comprehensive and can be bypassed.
    For production deployments, use Alembic with cryptographic signing.
    See: docs/database/MIGRATION_SYSTEM.md

    Args:
        sql: SQL migration script to validate.

    Raises:
        MigrationSecurityError: If migration contains suspicious patterns.
        ValueError: If migration SQL is empty or malformed.
    """
    if not sql or not sql.strip():
        raise ValueError("Migration SQL cannot be empty")

    # Normalize SQL (remove comments, extra whitespace)
    normalized_sql = _normalize_sql(sql)

    # Comprehensive dangerous patterns (case-insensitive regex)
    # NOTE: This list is NOT exhaustive - pattern matching cannot catch all attacks
    dangerous_patterns = [
        # Database operations
        (r'\bDROP\s+DATABASE\b', "DROP DATABASE"),
        (r'\bALTER\s+DATABASE\b', "ALTER DATABASE"),

        # NOTE: DROP TABLE/VIEW are intentionally NOT blocked here as legitimate
        # migrations may need to drop tables. However, this should be carefully
        # reviewed in code review. For production, use Alembic migrations.
        # (r'\bDROP\s+TABLE\b', "DROP TABLE"),
        # (r'\bDROP\s+VIEW\b', "DROP VIEW"),

        # User/privilege operations
        (r'\bCREATE\s+USER\b', "CREATE USER"),
        (r'\bDROP\s+USER\b', "DROP USER"),
        (r'\bGRANT\s+ALL\b', "GRANT ALL"),
        (r'\bREVOKE\s+ALL\b', "REVOKE ALL"),
        (r'\bGRANT\s+\w+\s+TO\b', "GRANT TO"),
        (r'\bSET\s+ROLE\b', "SET ROLE"),

        # Data deletion (dangerous patterns)
        (r'\bTRUNCATE\s+TABLE\b', "TRUNCATE TABLE"),
        (r'\bDELETE\s+FROM\s+\w+\s+WHERE\s+1\s*=\s*1', "DELETE WHERE 1=1"),
        (r'\bDELETE\s+FROM\s+\w+\s+WHERE\s+true\b', "DELETE WHERE true"),
        (r'\bDELETE\s+FROM\s+\w+\s+WHERE\s+[\'\"]?\w+[\'\"]?\s*=\s*[\'\"]?\w+[\'\"]?', "DELETE WHERE constant=constant"),
        (r'\bDELETE\s+FROM\s+\w+\s*;?\s*$', "DELETE FROM (no WHERE)"),

        # Stored procedures and dynamic SQL
        (r'\bEXEC\b', "EXEC"),
        (r'\bEXECUTE\b', "EXECUTE"),
        (r'\bCALL\b', "CALL"),
        (r'\bPREPARE\b', "PREPARE"),
        (r'\bEXECUTE\s+IMMEDIATE\b', "EXECUTE IMMEDIATE"),

        # Extended/system procedures (SQL Server)
        (r'\bxp_\w+', "xp_ extended procedure"),
        (r'\bsp_\w+', "sp_ stored procedure"),

        # Dangerous schema operations
        (r'\bCREATE\s+TRIGGER\b', "CREATE TRIGGER"),
        (r'\bALTER\s+TRIGGER\b', "ALTER TRIGGER"),
        (r'\bCREATE\s+FUNCTION\b', "CREATE FUNCTION"),
        (r'\bALTER\s+FUNCTION\b', "ALTER FUNCTION"),

        # Shell execution (PostgreSQL)
        (r'\bCOPY\b.*\bPROGRAM\b', "COPY PROGRAM"),
        (r'\bCOPY\b.*\bFROM\s+PROGRAM\b', "COPY FROM PROGRAM"),

        # File operations (MySQL)
        (r'\bLOAD\s+DATA\b.*\bINFILE\b', "LOAD DATA INFILE"),
        (r'\bSELECT\b.*\bINTO\s+OUTFILE\b', "SELECT INTO OUTFILE"),
        (r'\bSELECT\b.*\bINTO\s+DUMPFILE\b', "SELECT INTO DUMPFILE"),

        # SQLite-specific dangerous operations
        (r'\bATTACH\s+DATABASE\b', "ATTACH DATABASE"),
        (r'\bPRAGMA\b', "PRAGMA"),
    ]

    for pattern_regex, pattern_name in dangerous_patterns:
        if re.search(pattern_regex, normalized_sql, re.IGNORECASE):
            logger.error(
                f"SECURITY: Migration blocked - contains dangerous pattern: {pattern_name}",
                extra={
                    "pattern": pattern_name,
                    "sql_preview": sql[:100]
                }
            )
            raise MigrationSecurityError(
                f"Migration contains potentially dangerous pattern: {pattern_name}. "
                f"If this is a legitimate operation, please use Alembic migrations instead."
            )

    # Additional validation: Check for stacked queries (multiple statements)
    # This is a weak check but better than nothing
    MAX_STATEMENTS = 50  # Hard limit for security review
    WARN_STATEMENTS = 10  # Warning threshold

    statements = [s.strip() for s in normalized_sql.split(';') if s.strip()]

    if len(statements) > MAX_STATEMENTS:
        raise MigrationSecurityError(
            f"Migration contains {len(statements)} statements (max: {MAX_STATEMENTS}). "
            "Break into smaller migrations for security review."
        )
    elif len(statements) > WARN_STATEMENTS:
        logger.warning(
            f"Migration contains {len(statements)} SQL statements. "
            "Consider breaking into multiple migrations."
        )

    # Log validation success
    logger.debug(f"Migration SQL validation passed ({len(statements)} statements)")


def apply_migration(db_manager: DatabaseManager, migration_sql: str, version: str) -> None:
    """Apply a migration script.

    DEPRECATED: This function has known security vulnerabilities (SQL injection).
    For production use, migrate to Alembic-based migrations.

    This function:
    - Uses pattern-based validation (incomplete protection)
    - Executes raw SQL without cryptographic verification
    - Cannot prevent all injection attacks

    Recommended Alternative:
        Use Alembic migrations for secure, versioned schema evolution.
        See: docs/database/MIGRATION_SYSTEM.md

    Args:
        db_manager: Database manager instance.
        migration_sql: SQL migration script (MUST be from trusted source).
        version: Version identifier for this migration.

    Raises:
        MigrationSecurityError: If migration contains suspicious patterns.
        ValueError: If migration SQL is empty or malformed.

    Security Notes:
        - SQL is validated but validation is NOT comprehensive
        - Pattern matching can be bypassed with obfuscation
        - No cryptographic signature verification
        - Migrations should only come from trusted version control
    """
    # OB-10: Require explicit opt-in via environment variable.
    # This prevents accidental use of the deprecated, insecure function.
    if not os.environ.get("ALLOW_RAW_SQL_MIGRATION"):
        raise RuntimeError(
            "apply_migration() is deprecated and disabled by default. "
            "Set ALLOW_RAW_SQL_MIGRATION=1 to enable (NOT recommended for production). "
            "Migrate to Alembic instead: docs/database/MIGRATION_SYSTEM.md"
        )

    # Emit deprecation warning
    warnings.warn(
        "apply_migration() is deprecated due to security vulnerabilities. "
        "Please migrate to Alembic-based migrations. "
        "See docs/database/MIGRATION_SYSTEM.md for migration guide.",
        DeprecationWarning,
        stacklevel=2
    )

    # Comprehensive validation (still not perfect)
    _validate_migration_sql(migration_sql)

    # Security audit log
    logger.warning(
        "SECURITY AUDIT: Raw SQL migration executed",
        extra={
            "version": version,
            "sql_length": len(migration_sql),
            "function": "apply_migration",
            "recommendation": "Migrate to Alembic"
        }
    )

    with db_manager.session() as session:
        try:
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

        except Exception as e:
            logger.error(
                f"Migration {version} failed: {str(e)}",
                extra={
                    "version": version,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )
            raise
