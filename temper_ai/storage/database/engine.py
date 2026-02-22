"""Centralized database engine factory.

All database engines in the application should be created through this module
to ensure consistent configuration (pooling, timeouts, pragmas).

Production default: PostgreSQL via TEMPER_DATABASE_URL.
Tests can pass explicit SQLite URLs for isolation.
"""

import logging
import os
import sys
from typing import Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, QueuePool, StaticPool
from sqlmodel import create_engine

from temper_ai.shared.constants.limits import SMALL_POOL_SIZE

logger = logging.getLogger(__name__)

# Environment variable and default
TEMPER_DATABASE_URL_ENV = "TEMPER_DATABASE_URL"
DEFAULT_DATABASE_URL = "postgresql://temper:temper@localhost:5432/temper"

# PostgreSQL pool settings
PG_POOL_OVERFLOW_MULTIPLIER = 2


def get_database_url() -> str:
    """Return the configured database URL.

    Reads from the ``TEMPER_DATABASE_URL`` environment variable.
    Falls back to a local PostgreSQL default suitable for development.
    """
    return os.getenv(TEMPER_DATABASE_URL_ENV, DEFAULT_DATABASE_URL)


def create_app_engine(
    database_url: Optional[str] = None,
    pool_size: int = SMALL_POOL_SIZE,
) -> Engine:
    """Create a SQLAlchemy engine with dialect-appropriate settings.

    Args:
        database_url: Explicit database URL. If ``None``, uses
            :func:`get_database_url`.
        pool_size: Connection pool size (PostgreSQL only).

    Returns:
        Configured SQLAlchemy :class:`Engine`.

    Raises:
        ValueError: If a SQLite URL is provided (not supported in production).
    """
    url = database_url or get_database_url()

    if url.startswith("sqlite"):
        if "pytest" not in sys.modules:
            raise ValueError(
                "SQLite is not supported for production use. "
                "Set TEMPER_DATABASE_URL to a PostgreSQL connection string."
            )
        return _create_sqlite_engine(url)

    return _create_pg_engine(url, pool_size)


def create_test_engine(database_url: str = "sqlite:///:memory:") -> Engine:
    """Create a SQLite engine for tests only."""
    return _create_sqlite_engine(database_url)


# -- Private helpers --------------------------------------------------------


def _create_pg_engine(url: str, pool_size: int) -> Engine:
    """Create a PostgreSQL engine with QueuePool and pre-ping."""
    engine: Engine = create_engine(
        url,
        pool_size=pool_size,
        max_overflow=pool_size * PG_POOL_OVERFLOW_MULTIPLIER,
        pool_pre_ping=True,
        poolclass=QueuePool,
        echo=False,
    )
    return engine


def _create_sqlite_engine(url: str) -> Engine:
    """Create a SQLite engine with WAL mode and foreign keys.

    Used primarily by tests (``sqlite:///:memory:``).
    """
    is_memory = ":memory:" in url
    engine: Engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool if is_memory else NullPool,
        echo=False,
    )
    _register_sqlite_pragmas(engine)
    return engine


def _register_sqlite_pragmas(engine: Engine) -> None:
    """Enable WAL mode and foreign keys for every SQLite connection."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
