"""SQLite persistence for lifecycle adaptation data."""

import logging
from typing import Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from temper_ai.lifecycle.constants import DEFAULT_LIFECYCLE_DB_URL, DEFAULT_LIST_LIMIT
from temper_ai.lifecycle.models import LifecycleAdaptation, LifecycleProfileRecord
from temper_ai.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)


class LifecycleStore:
    """SQLite persistence for lifecycle adaptation and profile data."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url or DEFAULT_LIFECYCLE_DB_URL
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
            LifecycleAdaptation.__table__,  # type: ignore[attr-defined]
            LifecycleProfileRecord.__table__,  # type: ignore[attr-defined]
        ]
        SQLModel.metadata.create_all(self.engine, tables=_tables)
        logger.info("LifecycleStore initialized: %s", self.database_url)

    # ── Adaptations ──────────────────────────────────────────────────

    def save_adaptation(self, adaptation: LifecycleAdaptation) -> None:
        """Insert or update a lifecycle adaptation record."""
        with Session(self.engine) as session:
            session.merge(adaptation)
            session.commit()

    def list_adaptations(
        self,
        profile_name: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[LifecycleAdaptation]:
        """List adaptation records, newest first."""
        with Session(self.engine) as session:
            stmt = select(LifecycleAdaptation).order_by(
                LifecycleAdaptation.created_at.desc()  # type: ignore[attr-defined]
            )
            if profile_name is not None:
                stmt = stmt.where(
                    LifecycleAdaptation.profile_name == profile_name
                )
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    # ── Profiles ─────────────────────────────────────────────────────

    def save_profile(self, profile: LifecycleProfileRecord) -> None:
        """Insert or update a lifecycle profile record."""
        with Session(self.engine) as session:
            session.merge(profile)
            session.commit()

    def get_profile(self, name: str) -> Optional[LifecycleProfileRecord]:
        """Get a profile by name, or None."""
        with Session(self.engine) as session:
            stmt = select(LifecycleProfileRecord).where(
                LifecycleProfileRecord.name == name
            )
            return session.exec(stmt).first()

    def list_profiles(
        self,
        enabled_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[LifecycleProfileRecord]:
        """List profiles, optionally filtered by enabled status."""
        with Session(self.engine) as session:
            stmt = select(LifecycleProfileRecord).order_by(
                LifecycleProfileRecord.name
            )
            if enabled_only:
                stmt = stmt.where(LifecycleProfileRecord.enabled.is_(True))  # type: ignore[attr-defined]
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    def update_profile_status(
        self, name: str, enabled: bool
    ) -> bool:
        """Update a profile's enabled status. Returns True if found."""
        with Session(self.engine) as session:
            stmt = select(LifecycleProfileRecord).where(
                LifecycleProfileRecord.name == name
            )
            profile = session.exec(stmt).first()
            if profile is None:
                return False
            profile.enabled = enabled
            profile.updated_at = utcnow()
            session.add(profile)
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
