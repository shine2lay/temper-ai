"""Persistent storage for server run metadata.

Uses SQLModel/SQLAlchemy with a dedicated engine so the server's run
history is independent of the main observability database.
"""

import logging

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from temper_ai.interfaces.server.models import ServerRun
from temper_ai.storage.database.engine import create_app_engine, get_database_url

logger = logging.getLogger(__name__)


class RunStore:
    """Persistent storage for server run metadata."""

    def __init__(self, database_url: str | None = None) -> None:
        """Initialize the store and create tables if needed.

        Args:
            database_url: SQLAlchemy database URL.
                Defaults to the centralized database URL.
        """
        self.database_url = database_url or get_database_url()
        self.engine: Engine = create_app_engine(self.database_url)

        SQLModel.metadata.create_all(self.engine, tables=[ServerRun.__table__])  # type: ignore[attr-defined]
        logger.info("RunStore initialized: %s", self.database_url)

    def save_run(self, run: ServerRun) -> None:
        """Insert or update a run record."""
        with Session(self.engine) as session:
            session.merge(run)
            session.commit()

    def get_run(self, execution_id: str) -> ServerRun | None:
        """Get a run by execution_id, or None."""
        with Session(self.engine) as session:
            return session.get(ServerRun, execution_id)

    def list_runs(
        self,
        status: str | None = None,
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
