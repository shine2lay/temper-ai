"""Database connection and session management."""
from contextlib import contextmanager
from typing import Generator, Optional
from enum import Enum
import logging
import threading
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
import os

logger = logging.getLogger(__name__)


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
            database_url: Database URL. If None, uses DATABASE_URL env var
                         or defaults to SQLite.
        """
        if database_url is None:
            database_url = os.getenv(
                "DATABASE_URL",
                "sqlite:///./meta_autonomous.db"
            )

        self.database_url = database_url
        self.engine = self._create_engine()

    def _create_engine(self) -> Engine:
        """Create SQLAlchemy engine with appropriate settings."""
        if self.database_url.startswith("sqlite"):
            # SQLite settings
            engine = create_engine(
                self.database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False
            )
        else:
            # PostgreSQL settings
            engine = create_engine(
                self.database_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                echo=False
            )

        return engine

    def create_all_tables(self) -> None:
        """Create all tables in the database."""
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

        Usage:
            # Default isolation (READ COMMITTED)
            with db_manager.session() as session:
                workflow = WorkflowExecution(...)
                session.add(workflow)
                session.commit()

            # SERIALIZABLE for critical operations
            with db_manager.session(isolation_level=IsolationLevel.SERIALIZABLE) as session:
                # Concurrent-safe operations
                result = session.execute(...)
                session.commit()

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
                    # Other isolation levels not fully supported in SQLite
                else:
                    # PostgreSQL/other databases support all isolation levels
                    session.execute(
                        text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level.value}")
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to set isolation level {isolation_level.value}: {e}",
                    extra={"database_url": self.database_url}
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
                    "database_url": self.database_url,
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
        database_url: Database URL. If None, uses default.

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
                f"Failed to connect to database: {database_url}"
            ) from e

        _db_manager.create_all_tables()
        logger.info(f"Database initialized successfully: {database_url}")
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
