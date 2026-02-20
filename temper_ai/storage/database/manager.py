"""Database connection and session management."""

import logging
import os
import threading
import urllib.parse
from contextlib import contextmanager
from enum import Enum
from typing import Generator, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from temper_ai.storage.database.engine import create_app_engine, get_database_url

logger = logging.getLogger(__name__)


def _mask_database_url(url: Optional[str]) -> str:
    """Mask password in a database URL for safe logging.

    Replaces the password component with '****' so credentials
    are not exposed in log output.

    Args:
        url: Database URL (e.g., postgresql://user:pass@host/db)

    Returns:
        Masked URL string (e.g., postgresql://user:****@host/db)
    """
    if not url:
        return "<no url>"
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.password:
            # Replace password in netloc
            masked_netloc = parsed.netloc.replace(
                f":{parsed.password}@", ":****@"
            )
            return urllib.parse.urlunparse(parsed._replace(netloc=masked_netloc))
        return url
    except Exception:
        return "<unparseable url>"


class IsolationLevel(str, Enum):
    """Database transaction isolation levels.

    Isolation levels control how transactions handle concurrent access:
    - READ_UNCOMMITTED: Lowest isolation, allows dirty reads
    - READ_COMMITTED: Prevents dirty reads (default for most databases)
    - REPEATABLE_READ: Prevents non-repeatable reads
    - SERIALIZABLE: Highest isolation, prevents all anomalies

    Reference: https://www.postgresql.org/docs/current/transaction-iso.html
    """
    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


class DatabaseManager:
    """Manages database connections and sessions."""

    def __init__(self, database_url: Optional[str] = None):
        """Initialize database manager.

        Args:
            database_url: Database URL. If None, reads from
                ``TEMPER_DATABASE_URL`` env var (default: PostgreSQL).
        """
        self.database_url = database_url or get_database_url()
        self.engine: Engine = create_app_engine(self.database_url)

    def create_all_tables(self) -> None:
        """Create all tables in the database.

        WARNING: For production use, schema changes MUST go through Alembic
        migrations (see alembic/versions/). This method is retained for
        test fixtures that need a quick in-memory schema setup.
        Do NOT call this in production startup paths.
        """
        SQLModel.metadata.create_all(self.engine)

    def drop_all_tables(self) -> None:
        """Drop all tables. Use with caution!"""
        SQLModel.metadata.drop_all(self.engine)

    @contextmanager
    def session(
        self,
        isolation_level: Optional[IsolationLevel] = None
    ) -> Generator[Session, None, None]:
        """Context manager for database sessions with configurable isolation.

        Args:
            isolation_level: Transaction isolation level. If None, uses database default
                           (typically READ COMMITTED). Use SERIALIZABLE for operations
                           requiring strict consistency under concurrent access.

        Note:
            SERIALIZABLE isolation may result in serialization failures under high
            contention. Application code should implement retry logic for such failures.
        """
        session = Session(self.engine)

        # Set isolation level if specified
        if isolation_level:
            try:
                if self.database_url.startswith("sqlite"):
                    # SQLite supports SERIALIZABLE via IMMEDIATE transactions
                    if isolation_level == IsolationLevel.SERIALIZABLE:
                        session.execute(text("BEGIN IMMEDIATE"))
                else:
                    session.connection().execution_options(
                        isolation_level=isolation_level.value
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to set isolation level {isolation_level.value}: {e}",
                    extra={"database_url": _mask_database_url(self.database_url)}
                )

        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(
                f"Database session error: {e.__class__.__name__}: {str(e)}",
                exc_info=True,
                extra={
                    "database_url": _mask_database_url(self.database_url),
                    "isolation_level": isolation_level.value if isolation_level else "default"
                }
            )
            raise
        finally:
            session.close()


# Global instance (can be configured)
_db_manager: Optional[DatabaseManager] = None
_db_lock = threading.Lock()


def init_database(database_url: Optional[str] = None) -> DatabaseManager:
    """Initialize global database manager (thread-safe).

    Args:
        database_url: Database URL. If None, uses ``TEMPER_DATABASE_URL``
            env var (default: PostgreSQL).

    Returns:
        Initialized DatabaseManager instance.

    Raises:
        ConnectionError: If database connection fails.
    """
    global _db_manager

    with _db_lock:
        if _db_manager is not None:
            logger.warning("Database already initialized, returning existing instance")
            return _db_manager

        _db_manager = DatabaseManager(database_url)

        # Verify connection before creating tables
        try:
            with _db_manager.session() as session:
                session.execute(text("SELECT 1"))
        except Exception as e:
            _db_manager = None
            raise ConnectionError(
                f"Failed to connect to database: {_mask_database_url(database_url)}"
            ) from e

        # Alembic is the sole DDL strategy for production deployments.
        # In production, set ALEMBIC_MANAGED=1 so that init_database() skips
        # create_all_tables() and relies on `alembic upgrade head` instead.
        # For dev/test (the default), tables are auto-created for convenience.
        if not os.getenv("ALEMBIC_MANAGED"):
            _db_manager.create_all_tables()
        else:
            logger.info(
                "ALEMBIC_MANAGED is set -- skipping create_all_tables(). "
                "Run 'alembic upgrade head' to apply schema."
            )
        logger.info(f"Database initialized successfully: {_mask_database_url(database_url)}")
        return _db_manager


def get_database() -> DatabaseManager:
    """Get global database manager instance.

    Raises:
        RuntimeError: If database not initialized.
    """
    if _db_manager is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db_manager


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get database session from global manager.

    Usage:
        with get_session() as session:
            workflow = session.query(WorkflowExecution).first()
    """
    db = get_database()
    with db.session() as session:
        yield session


def reset_database() -> None:
    """Reset the global database manager.

    This allows re-initialization with a different database URL.
    Useful for testing when you need to switch between test databases.

    WARNING: This closes the existing database connection. Only use
    in testing or during application shutdown.
    """
    global _db_manager

    with _db_lock:
        if _db_manager is not None:
            # Close existing connections
            _db_manager.engine.dispose()
            _db_manager = None
            logger.info("Database manager reset")
