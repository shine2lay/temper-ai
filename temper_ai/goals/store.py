"""Database persistence for goal proposal data."""

import logging

from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from temper_ai.goals.constants import DEFAULT_LIST_LIMIT, DEFAULT_RUN_LIMIT
from temper_ai.goals.models import AnalysisRun, GoalProposalRecord
from temper_ai.storage.database.engine import create_app_engine, get_database_url

logger = logging.getLogger(__name__)


class GoalStore:
    """Database persistence for goal proposals and analysis runs."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or get_database_url()
        self.engine: Engine = create_app_engine(self.database_url)

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

    def get_proposal(self, proposal_id: str) -> GoalProposalRecord | None:
        """Get a proposal by ID, or None."""
        with Session(self.engine) as session:
            return session.get(GoalProposalRecord, proposal_id)

    def list_proposals(
        self,
        status: str | None = None,
        goal_type: str | None = None,
        product_type: str | None = None,
        agent_id: str | None = None,
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
            if agent_id is not None:
                stmt = stmt.where(GoalProposalRecord.source_agent_id == agent_id)
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        reviewer: str | None = None,
        reason: str | None = None,
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

    def count_by_status(self) -> dict[str, int]:
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

    def list_analysis_runs(self, limit: int = DEFAULT_RUN_LIMIT) -> list[AnalysisRun]:
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
