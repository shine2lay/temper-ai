"""Persistent storage for server run metadata.

Uses SQLModel/SQLAlchemy with a dedicated engine so the server's run
history is independent of the main observability database.
"""
import logging
from typing import Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from temper_ai.interfaces.server.models import ServerRun

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "sqlite:///./server_runs.db"


class RunStore:
    """Persistent storage for server run metadata."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        """Initialize the store and create tables if needed.

        Args:
            database_url: SQLAlchemy database URL.
                Defaults to ``sqlite:///./server_runs.db``.
        """
        self.database_url = database_url or DEFAULT_DATABASE_URL
        is_memory = ":memory:" in self.database_url
        self.engine: Engine = create_engine(
            self.database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if is_memory else NullPool,
            echo=False,
        )

        # Enable WAL + foreign keys for SQLite
        if self.database_url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
                """Enable SQLite WAL mode and foreign keys."""
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        SQLModel.metadata.create_all(self.engine, tables=[ServerRun.__table__])  # type: ignore[attr-defined]
        logger.info("RunStore initialized: %s", self.database_url)

    def save_run(self, run: ServerRun) -> None:
        """Insert or update a run record."""
        with Session(self.engine) as session:
            session.merge(run)
            session.commit()

    def get_run(self, execution_id: str) -> Optional[ServerRun]:
        """Get a run by execution_id, or None."""
        with Session(self.engine) as session:
            return session.get(ServerRun, execution_id)

    def list_runs(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ServerRun]:
        """List runs, optionally filtered by status.

        Results are ordered by created_at descending (newest first).
        """
        with Session(self.engine) as session:
            stmt = select(ServerRun).order_by(ServerRun.created_at.desc())  # type: ignore[attr-defined]
            if status is not None:
                stmt = stmt.where(ServerRun.status == status)
            stmt = stmt.offset(offset).limit(limit)
            return list(session.exec(stmt).all())

    def update_status(
        self,
        execution_id: str,
        status: str,
        **kwargs: object,
    ) -> bool:
        """Update a run's status and optional fields.

        Returns True if the run was found and updated, False otherwise.
        """
        with Session(self.engine) as session:
            run = session.get(ServerRun, execution_id)
            if run is None:
                return False
            run.status = status
            for key, value in kwargs.items():
                if hasattr(run, key):
                    setattr(run, key, value)
            session.add(run)
            session.commit()
            return True
