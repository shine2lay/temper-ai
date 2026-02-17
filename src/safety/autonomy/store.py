"""SQLite persistence for progressive autonomy data."""

import logging
from typing import Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.safety.autonomy.models import (
    AutonomyState,
    AutonomyTransition,
    BudgetRecord,
    EmergencyStopEvent,
)

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "sqlite:///./autonomy.db"
DEFAULT_LIST_LIMIT = 100


class AutonomyStore:
    """SQLite persistence for autonomy data."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url or DEFAULT_DATABASE_URL
        is_memory = ":memory:" in self.database_url
        self.engine: Engine = create_engine(
            self.database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if is_memory else NullPool,
            echo=False,
        )
        if self.database_url.startswith("sqlite"):
            _register_sqlite_pragmas(self.engine)

        _tables = [
            AutonomyState.__table__,  # type: ignore[attr-defined]
            AutonomyTransition.__table__,  # type: ignore[attr-defined]
            BudgetRecord.__table__,  # type: ignore[attr-defined]
            EmergencyStopEvent.__table__,  # type: ignore[attr-defined]
        ]
        SQLModel.metadata.create_all(self.engine, tables=_tables)
        logger.info("AutonomyStore initialized: %s", self.database_url)

    # -- AutonomyState -------------------------------------------------

    def get_state(
        self, agent_name: str, domain: str
    ) -> Optional[AutonomyState]:
        """Get autonomy state for agent+domain, or None."""
        with Session(self.engine) as session:
            stmt = select(AutonomyState).where(
                AutonomyState.agent_name == agent_name,
                AutonomyState.domain == domain,
            )
            return session.exec(stmt).first()

    def save_state(self, state: AutonomyState) -> None:
        """Insert or update an autonomy state."""
        with Session(self.engine) as session:
            session.merge(state)
            session.commit()

    def list_states(
        self, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[AutonomyState]:
        """List all autonomy states."""
        with Session(self.engine) as session:
            stmt = select(AutonomyState).limit(limit)
            return list(session.exec(stmt).all())

    # -- AutonomyTransition --------------------------------------------

    def save_transition(self, transition: AutonomyTransition) -> None:
        """Insert a transition record."""
        with Session(self.engine) as session:
            session.merge(transition)
            session.commit()

    def list_transitions(
        self,
        agent_name: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[AutonomyTransition]:
        """List transitions, optionally filtered by agent."""
        with Session(self.engine) as session:
            stmt = select(AutonomyTransition).order_by(
                AutonomyTransition.created_at.desc()  # type: ignore[attr-defined]
            )
            if agent_name is not None:
                stmt = stmt.where(
                    AutonomyTransition.agent_name == agent_name
                )
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    # -- BudgetRecord --------------------------------------------------

    def get_budget(self, scope: str) -> Optional[BudgetRecord]:
        """Get active budget for scope."""
        with Session(self.engine) as session:
            stmt = select(BudgetRecord).where(
                BudgetRecord.scope == scope,
            )
            return session.exec(stmt).first()

    def save_budget(self, budget: BudgetRecord) -> None:
        """Insert or update a budget record."""
        with Session(self.engine) as session:
            session.merge(budget)
            session.commit()

    # -- EmergencyStopEvent -------------------------------------------

    def save_emergency_event(self, event_record: EmergencyStopEvent) -> None:
        """Insert an emergency stop event."""
        with Session(self.engine) as session:
            session.merge(event_record)
            session.commit()

    def list_emergency_events(
        self, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[EmergencyStopEvent]:
        """List emergency stop events, newest first."""
        with Session(self.engine) as session:
            stmt = (
                select(EmergencyStopEvent)
                .order_by(
                    EmergencyStopEvent.created_at.desc()  # type: ignore[attr-defined]
                )
                .limit(limit)
            )
            return list(session.exec(stmt).all())


def _register_sqlite_pragmas(engine: Engine) -> None:
    """Enable WAL mode and foreign keys for SQLite."""

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
