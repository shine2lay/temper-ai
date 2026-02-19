"""SQLite persistence for continuous learning data."""

import logging
from typing import Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from temper_ai.learning.models import LearnedPattern, MiningRun, TuneRecommendation

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "sqlite:///./learning.db"
DEFAULT_LIST_LIMIT = 100
DEFAULT_MINING_LIST_LIMIT = 20


class LearningStore:
    """SQLite persistence for learning data."""

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

    def get_pattern(self, pattern_id: str) -> Optional[LearnedPattern]:
        """Get a pattern by ID, or None."""
        with Session(self.engine) as session:
            return session.get(LearnedPattern, pattern_id)

    def list_patterns(
        self,
        pattern_type: Optional[str] = None,
        status: Optional[str] = "active",
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

    def list_recommendations(
        self, status: str = "pending"
    ) -> list[TuneRecommendation]:
        """List recommendations filtered by status."""
        with Session(self.engine) as session:
            stmt = select(TuneRecommendation).where(
                TuneRecommendation.status == status
            )
            return list(session.exec(stmt).all())

    def update_recommendation_status(
        self, rec_id: str, status: str
    ) -> bool:
        """Update a recommendation's status. Returns True if found."""
        with Session(self.engine) as session:
            rec = session.get(TuneRecommendation, rec_id)
            if rec is None:
                return False
            rec.status = status
            session.add(rec)
            session.commit()
            return True


def _register_sqlite_pragmas(engine: Engine) -> None:
    """Enable WAL mode and foreign keys for SQLite."""

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
