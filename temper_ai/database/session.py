"""Database connection and session management."""

import logging
import threading
import urllib.parse
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from temper_ai.database.engine import create_app_engine, get_database_url

logger = logging.getLogger(__name__)


def _mask_url(url: str | None) -> str:
    """Mask password in a database URL for safe logging."""
    if not url:
        return "<no url>"
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.password:
            masked_netloc = parsed.netloc.replace(f":{parsed.password}@", ":****@")
            return urllib.parse.urlunparse(parsed._replace(netloc=masked_netloc))
        return url
    except Exception:
        return "<unparseable url>"


class DatabaseManager:
    """Manages database connections and sessions."""

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or get_database_url()
        self.engine: Engine = create_app_engine(self.database_url)

    def create_all_tables(self) -> None:
        """Create all SQLModel tables. For dev/test only — use Alembic in production."""
        SQLModel.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context manager for database sessions with auto commit/rollback."""
        session = Session(self.engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        """Dispose engine connections."""
        self.engine.dispose()


# -- Global instance (thread-safe singleton) --

_db_manager: DatabaseManager | None = None
_db_lock = threading.Lock()


def init_database(database_url: str | None = None) -> DatabaseManager:
    """Initialize global database manager. Verifies connection and creates tables."""
    global _db_manager

    with _db_lock:
        if _db_manager is not None:
            return _db_manager

        _db_manager = DatabaseManager(database_url)

        # Verify connection
        try:
            with _db_manager.session() as session:
                session.execute(text("SELECT 1"))
        except Exception as e:
            _db_manager = None
            raise ConnectionError(
                f"Failed to connect to database: {_mask_url(database_url)}"
            ) from e

        _db_manager.create_all_tables()
        logger.info("Database initialized: %s", _mask_url(database_url))
        return _db_manager


def get_database() -> DatabaseManager:
    """Get global database manager. Raises RuntimeError if not initialized."""
    if _db_manager is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db_manager


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get database session from global manager."""
    db = get_database()
    with db.session() as session:
        yield session


def reset_database() -> None:
    """Reset global database manager. For testing only."""
    global _db_manager

    with _db_lock:
        if _db_manager is not None:
            _db_manager.dispose()
            _db_manager = None
