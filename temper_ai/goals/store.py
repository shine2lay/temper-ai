"""SQLite persistence for goal proposal data."""

import logging
from typing import Dict, Optional

from sqlalchemy import event, func
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from temper_ai.goals.constants import DEFAULT_DATABASE_URL, DEFAULT_LIST_LIMIT, DEFAULT_RUN_LIMIT
from temper_ai.goals.models import AnalysisRun, GoalProposalRecord

logger = logging.getLogger(__name__)


class GoalStore:
    """SQLite persistence for goal proposals and analysis runs."""

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
            GoalProposalRecord.__table__,  # type: ignore[attr-defined]
            AnalysisRun.__table__,  # type: ignore[attr-defined]
        ]
        SQLModel.metadata.create_all(self.engine, tables=_tables)
        logger.info("GoalStore initialized: %s", self.database_url)

    # -- Proposals ---------------------------------------------------------

    def save_proposal(self, record: GoalProposalRecord) -> None:
        """Insert or update a goal proposal."""
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()

    def get_proposal(self, proposal_id: str) -> Optional[GoalProposalRecord]:
        """Get a proposal by ID, or None."""
        with Session(self.engine) as session:
            return session.get(GoalProposalRecord, proposal_id)

    def list_proposals(
        self,
        status: Optional[str] = None,
        goal_type: Optional[str] = None,
        product_type: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[GoalProposalRecord]:
        """List proposals with optional filters."""
        with Session(self.engine) as session:
            stmt = select(GoalProposalRecord).order_by(
                GoalProposalRecord.priority_score.desc()  # type: ignore[attr-defined]
            )
            if status is not None:
                stmt = stmt.where(GoalProposalRecord.status == status)
            if goal_type is not None:
                stmt = stmt.where(GoalProposalRecord.goal_type == goal_type)
            if product_type is not None:
                stmt = stmt.where(
                    GoalProposalRecord.source_product_type == product_type
                )
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        reviewer: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """Update a proposal's status. Returns True if found."""
        from temper_ai.storage.database.datetime_utils import utcnow as _utcnow

        with Session(self.engine) as session:
            record = session.get(GoalProposalRecord, proposal_id)
            if record is None:
                return False
            record.status = status
            record.updated_at = _utcnow()
            if reviewer is not None:
                record.reviewer = reviewer
                record.reviewed_at = _utcnow()
            if reason is not None:
                record.review_reason = reason
            session.add(record)
            session.commit()
            return True

    def count_by_status(self) -> Dict[str, int]:
        """Count proposals grouped by status."""
        with Session(self.engine) as session:
            rows = session.exec(
                select(
                    GoalProposalRecord.status,
                    func.count(GoalProposalRecord.id),  # type: ignore[arg-type]
                ).group_by(GoalProposalRecord.status)
            ).all()
            return {str(row[0]): int(row[1]) for row in rows}

    # -- Analysis Runs -----------------------------------------------------

    def save_analysis_run(self, run: AnalysisRun) -> None:
        """Insert or update an analysis run record."""
        with Session(self.engine) as session:
            session.merge(run)
            session.commit()

    def list_analysis_runs(
        self, limit: int = DEFAULT_RUN_LIMIT
    ) -> list[AnalysisRun]:
        """List recent analysis runs, newest first."""
        with Session(self.engine) as session:
            stmt = (
                select(AnalysisRun)
                .order_by(AnalysisRun.started_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )
            return list(session.exec(stmt).all())

    def count_proposals_today(self) -> int:
        """Count proposals created in the last 24 hours."""
        from datetime import timedelta

        from temper_ai.storage.database.datetime_utils import utcnow as _utcnow

        cutoff = _utcnow() - timedelta(hours=24)  # noqa: scanner: skip-magic
        with Session(self.engine) as session:
            stmt = select(func.count(GoalProposalRecord.id)).where(  # type: ignore[arg-type]
                GoalProposalRecord.created_at >= cutoff
            )
            result = session.exec(stmt).one()
            return int(result)


def _register_sqlite_pragmas(engine: Engine) -> None:
    """Enable WAL mode and foreign keys for SQLite."""

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
