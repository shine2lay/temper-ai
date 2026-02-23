"""Database persistence for progressive autonomy data."""

import logging

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from temper_ai.safety.autonomy.models import (
    AutonomyState,
    AutonomyTransition,
    BudgetRecord,
    EmergencyStopEvent,
)
from temper_ai.storage.database.engine import create_app_engine, get_database_url

logger = logging.getLogger(__name__)

DEFAULT_LIST_LIMIT = 100


class AutonomyStore:
    """Database persistence for autonomy data."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or get_database_url()
        self.engine: Engine = create_app_engine(self.database_url)

        _tables = [
            AutonomyState.__table__,  # type: ignore[attr-defined]
            AutonomyTransition.__table__,  # type: ignore[attr-defined]
            BudgetRecord.__table__,  # type: ignore[attr-defined]
            EmergencyStopEvent.__table__,  # type: ignore[attr-defined]
        ]
        SQLModel.metadata.create_all(self.engine, tables=_tables)
        logger.info("AutonomyStore initialized: %s", self.database_url)

    # -- AutonomyState -------------------------------------------------

    def get_state(self, agent_name: str, domain: str) -> AutonomyState | None:
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

    def list_states(self, limit: int = DEFAULT_LIST_LIMIT) -> list[AutonomyState]:
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
        agent_name: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[AutonomyTransition]:
        """List transitions, optionally filtered by agent."""
        with Session(self.engine) as session:
            stmt = select(AutonomyTransition).order_by(
                AutonomyTransition.created_at.desc()  # type: ignore[attr-defined]
            )
            if agent_name is not None:
                stmt = stmt.where(AutonomyTransition.agent_name == agent_name)
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    # -- BudgetRecord --------------------------------------------------

    def get_budget(self, scope: str) -> BudgetRecord | None:
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
