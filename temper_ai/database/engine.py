"""Database engine factory.

All database engines should be created through this module
to ensure consistent configuration (pooling, timeouts, pragmas).

Production default: PostgreSQL via TEMPER_DATABASE_URL.
Tests can pass explicit SQLite URLs for isolation.
"""

import logging
import os

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, QueuePool, StaticPool
from sqlmodel import create_engine

logger = logging.getLogger(__name__)

TEMPER_DATABASE_URL_ENV = "TEMPER_DATABASE_URL"
DEFAULT_DATABASE_URL = "postgresql://temper_ai:temper_dev@localhost:5432/temper_ai"

_DEFAULT_POOL_SIZE = 10
_PG_POOL_OVERFLOW_MULTIPLIER = 2


def get_database_url() -> str:
    """Return the configured database URL from env or default."""
    return os.getenv(TEMPER_DATABASE_URL_ENV, DEFAULT_DATABASE_URL)


def create_app_engine(
    database_url: str | None = None,
    pool_size: int = _DEFAULT_POOL_SIZE,
) -> Engine:
    """Create a SQLAlchemy engine with dialect-appropriate settings."""
    url = database_url or get_database_url()

    if url.startswith("sqlite"):
        logger.warning(
            "Using SQLite database (%s). SQLite is suitable for local development "
            "and testing only — use PostgreSQL for production.",
            url,
        )
        return _create_sqlite_engine(url)

    return _create_pg_engine(url, pool_size)


def create_test_engine(database_url: str = "sqlite:///:memory:") -> Engine:
    """Create a SQLite engine for tests only."""
    return _create_sqlite_engine(database_url)


def _create_pg_engine(url: str, pool_size: int) -> Engine:
    engine: Engine = create_engine(
        url,
        pool_size=pool_size,
        max_overflow=pool_size * _PG_POOL_OVERFLOW_MULTIPLIER,
        pool_pre_ping=True,
        poolclass=QueuePool,
        echo=False,
    )

    # Every time temper stores carries UTC (temper_ai/shared/clock.py), and
    # most of its columns are `timestamp without time zone`. Postgres drops
    # the offset using the *session's* zone, so a server whose database ran
    # on local time would shift every stored time by its offset. Saying UTC
    # on each connection makes the cast exact, wherever the database lives.
    #
    # Said here rather than in connect_args: connect_args would take over the
    # `options` a URL can carry, and the tests use that to give each xdist
    # worker a schema of its own.
    @event.listens_for(engine, "connect")
    def _utc_session(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.close()

    return engine


def _create_sqlite_engine(url: str) -> Engine:
    is_memory = ":memory:" in url
    engine: Engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool if is_memory else NullPool,
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine
