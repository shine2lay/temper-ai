"""Database persistence for continuous learning data."""

import logging

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, select

from temper_ai.learning.models import LearnedPattern, MiningRun, TuneRecommendation
from temper_ai.storage.database.engine import create_app_engine, get_database_url

logger = logging.getLogger(__name__)

DEFAULT_LIST_LIMIT = 100
DEFAULT_MINING_LIST_LIMIT = 20


class LearningStore:
    """Database persistence for learning data."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or get_database_url()
        self.engine: Engine = create_app_engine(self.database_url)

        _tables = [
            LearnedPattern.__table__,  # type: ignore[attr-defined]
            MiningRun.__table__,  # type: ignore[attr-defined]
            TuneRecommendation.__table__,  # type: ignore[attr-defined]
        ]
        SQLModel.metadata.create_all(self.engine, tables=_tables)
        logger.info("LearningStore initialized: %s", self.database_url)

    # ── Patterns ──────────────────────────────────────────────────────

    def save_pattern(self, pattern: LearnedPattern) -> None:
        """Insert or update a learned pattern."""
        with Session(self.engine) as session:
            session.merge(pattern)
            session.commit()

    def get_pattern(self, pattern_id: str) -> LearnedPattern | None:
        """Get a pattern by ID, or None."""
        with Session(self.engine) as session:
            return session.get(LearnedPattern, pattern_id)

    def list_patterns(
        self,
        pattern_type: str | None = None,
        status: str | None = "active",
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[LearnedPattern]:
        """List patterns with optional type and status filters."""
        with Session(self.engine) as session:
            stmt = select(LearnedPattern).order_by(
                LearnedPattern.confidence.desc()  # type: ignore[attr-defined]
            )
            if pattern_type is not None:
                stmt = stmt.where(LearnedPattern.pattern_type == pattern_type)
            if status is not None:
                stmt = stmt.where(LearnedPattern.status == status)
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    # ── Mining Runs ───────────────────────────────────────────────────

    def save_mining_run(self, run: MiningRun) -> None:
        """Insert or update a mining run record."""
        with Session(self.engine) as session:
            session.merge(run)
            session.commit()

    def list_mining_runs(
        self, limit: int = DEFAULT_MINING_LIST_LIMIT
    ) -> list[MiningRun]:
        """List recent mining runs, newest first."""
        with Session(self.engine) as session:
            stmt = (
                select(MiningRun)
                .order_by(MiningRun.started_at.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )
            return list(session.exec(stmt).all())

    # ── Recommendations ───────────────────────────────────────────────

    def save_recommendation(self, rec: TuneRecommendation) -> None:
        """Insert or update a recommendation."""
        with Session(self.engine) as session:
            session.merge(rec)
            session.commit()

    def list_recommendations(self, status: str = "pending") -> list[TuneRecommendation]:
        """List recommendations filtered by status."""
        with Session(self.engine) as session:
            stmt = select(TuneRecommendation).where(TuneRecommendation.status == status)
            return list(session.exec(stmt).all())

    def update_recommendation_status(self, rec_id: str, status: str) -> bool:
        """Update a recommendation's status. Returns True if found."""
        with Session(self.engine) as session:
            rec = session.get(TuneRecommendation, rec_id)
            if rec is None:
                return False
            rec.status = status
            session.add(rec)
            session.commit()
            return True
