"""SQLite persistence for portfolio management data."""

import logging
from typing import Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from temper_ai.portfolio.constants import (
    DEFAULT_LIST_LIMIT,
    DEFAULT_PORTFOLIO_DB_URL,
    DEFAULT_RUN_LIMIT,
    DEFAULT_SNAPSHOT_LIMIT,
)
from temper_ai.portfolio.models import (
    KGConceptRecord,
    KGEdgeRecord,
    PortfolioRecord,
    PortfolioSnapshotRecord,
    ProductRunRecord,
    SharedComponentRecord,
    TechCompatibilityRecord,
)
from temper_ai.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)


class PortfolioStore:
    """SQLite persistence for portfolio data."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url or DEFAULT_PORTFOLIO_DB_URL
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
            PortfolioRecord.__table__,  # type: ignore[attr-defined]
            ProductRunRecord.__table__,  # type: ignore[attr-defined]
            SharedComponentRecord.__table__,  # type: ignore[attr-defined]
            KGConceptRecord.__table__,  # type: ignore[attr-defined]
            KGEdgeRecord.__table__,  # type: ignore[attr-defined]
            TechCompatibilityRecord.__table__,  # type: ignore[attr-defined]
            PortfolioSnapshotRecord.__table__,  # type: ignore[attr-defined]
        ]
        SQLModel.metadata.create_all(self.engine, tables=_tables)
        logger.info("PortfolioStore initialized: %s", self.database_url)

    # ── Portfolios ─────────────────────────────────────────────────────

    def save_portfolio(self, record: PortfolioRecord) -> None:
        """Insert or update a portfolio record."""
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()

    def get_portfolio(self, name: str) -> Optional[PortfolioRecord]:
        """Get a portfolio by name, or None."""
        with Session(self.engine) as session:
            stmt = select(PortfolioRecord).where(
                PortfolioRecord.name == name
            )
            return session.exec(stmt).first()

    def list_portfolios(
        self, enabled_only: bool = False, limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[PortfolioRecord]:
        """List portfolios, optionally filtered by enabled status."""
        with Session(self.engine) as session:
            stmt = select(PortfolioRecord).order_by(PortfolioRecord.name)
            if enabled_only:
                stmt = stmt.where(PortfolioRecord.enabled.is_(True))  # type: ignore[attr-defined]
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    # ── Product Runs ───────────────────────────────────────────────────

    def save_product_run(self, record: ProductRunRecord) -> None:
        """Insert or update a product run record."""
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()

    def list_product_runs(
        self,
        product_type: Optional[str] = None,
        portfolio_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = DEFAULT_RUN_LIMIT,
    ) -> list[ProductRunRecord]:
        """List product runs with optional filters."""
        with Session(self.engine) as session:
            stmt = select(ProductRunRecord).order_by(
                ProductRunRecord.started_at.desc()  # type: ignore[attr-defined]
            )
            if product_type is not None:
                stmt = stmt.where(
                    ProductRunRecord.product_type == product_type
                )
            if portfolio_id is not None:
                stmt = stmt.where(
                    ProductRunRecord.portfolio_id == portfolio_id
                )
            if status is not None:
                stmt = stmt.where(ProductRunRecord.status == status)
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    def count_product_runs(
        self, product_type: str, portfolio_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """Count runs for a product type, optionally filtered by status."""
        from sqlalchemy import func

        with Session(self.engine) as session:
            stmt = select(func.count(ProductRunRecord.id)).where(  # type: ignore[arg-type]
                ProductRunRecord.product_type == product_type,
            )
            if portfolio_id is not None:
                stmt = stmt.where(
                    ProductRunRecord.portfolio_id == portfolio_id
                )
            if status is not None:
                stmt = stmt.where(ProductRunRecord.status == status)
            return int(session.exec(stmt).one())

    def get_total_cost(
        self, product_type: str, portfolio_id: Optional[str] = None,
    ) -> float:
        """Get total cost for a product type."""
        from sqlalchemy import func

        with Session(self.engine) as session:
            stmt = select(func.coalesce(func.sum(ProductRunRecord.cost_usd), 0.0)).where(
                ProductRunRecord.product_type == product_type,
            )
            if portfolio_id is not None:
                stmt = stmt.where(
                    ProductRunRecord.portfolio_id == portfolio_id
                )
            return float(session.exec(stmt).one())

    # ── Shared Components ──────────────────────────────────────────────

    def save_shared_component(self, record: SharedComponentRecord) -> None:
        """Insert or update a shared component record."""
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()

    def list_shared_components(
        self, min_similarity: float = 0.0, limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[SharedComponentRecord]:
        """List shared components above a similarity threshold."""
        with Session(self.engine) as session:
            stmt = (
                select(SharedComponentRecord)
                .where(SharedComponentRecord.similarity >= min_similarity)
                .order_by(SharedComponentRecord.similarity.desc())  # type: ignore[attr-defined]
                .limit(limit)
            )
            return list(session.exec(stmt).all())

    # ── Knowledge Graph ────────────────────────────────────────────────

    def save_concept(self, record: KGConceptRecord) -> None:
        """Insert or update a knowledge graph concept."""
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()

    def get_concept(
        self, name: Optional[str] = None, concept_id: Optional[str] = None,
    ) -> Optional[KGConceptRecord]:
        """Get a concept by name or ID, or None."""
        with Session(self.engine) as session:
            if concept_id is not None:
                return session.get(KGConceptRecord, concept_id)
            if name is not None:
                stmt = select(KGConceptRecord).where(
                    KGConceptRecord.name == name
                )
                return session.exec(stmt).first()
            return None

    def list_concepts(
        self,
        concept_type: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[KGConceptRecord]:
        """List concepts with optional type filter."""
        with Session(self.engine) as session:
            stmt = select(KGConceptRecord).order_by(KGConceptRecord.name)
            if concept_type is not None:
                stmt = stmt.where(
                    KGConceptRecord.concept_type == concept_type
                )
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    def save_edge(self, record: KGEdgeRecord) -> None:
        """Insert or update a knowledge graph edge."""
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()

    def query_edges(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relation: Optional[str] = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[KGEdgeRecord]:
        """Query edges with optional filters."""
        with Session(self.engine) as session:
            stmt = select(KGEdgeRecord)
            if source_id is not None:
                stmt = stmt.where(KGEdgeRecord.source_id == source_id)
            if target_id is not None:
                stmt = stmt.where(KGEdgeRecord.target_id == target_id)
            if relation is not None:
                stmt = stmt.where(KGEdgeRecord.relation == relation)
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())

    # ── Tech Compatibility ─────────────────────────────────────────────

    def save_compatibility(self, record: TechCompatibilityRecord) -> None:
        """Insert or update a tech compatibility record."""
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()

    def get_compatibility(
        self, tech_name: str, limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[TechCompatibilityRecord]:
        """Get all compatibility records for a technology."""
        with Session(self.engine) as session:
            stmt = (
                select(TechCompatibilityRecord)
                .where(
                    (TechCompatibilityRecord.tech_a == tech_name)
                    | (TechCompatibilityRecord.tech_b == tech_name)
                )
                .limit(limit)
            )
            return list(session.exec(stmt).all())

    # ── Snapshots ──────────────────────────────────────────────────────

    def save_snapshot(self, record: PortfolioSnapshotRecord) -> None:
        """Insert or update a portfolio snapshot."""
        with Session(self.engine) as session:
            session.merge(record)
            session.commit()

    def list_snapshots(
        self,
        product_type: Optional[str] = None,
        portfolio_id: Optional[str] = None,
        limit: int = DEFAULT_SNAPSHOT_LIMIT,
    ) -> list[PortfolioSnapshotRecord]:
        """List snapshots, newest first."""
        with Session(self.engine) as session:
            stmt = select(PortfolioSnapshotRecord).order_by(
                PortfolioSnapshotRecord.created_at.desc()  # type: ignore[attr-defined]
            )
            if product_type is not None:
                stmt = stmt.where(
                    PortfolioSnapshotRecord.product_type == product_type
                )
            if portfolio_id is not None:
                stmt = stmt.where(
                    PortfolioSnapshotRecord.portfolio_id == portfolio_id
                )
            stmt = stmt.limit(limit)
            return list(session.exec(stmt).all())


def update_portfolio_status(store: PortfolioStore, name: str, enabled: bool) -> bool:
    """Update a portfolio's enabled status. Returns True if found."""
    with Session(store.engine) as session:
        stmt = select(PortfolioRecord).where(
            PortfolioRecord.name == name
        )
        portfolio = session.exec(stmt).first()
        if portfolio is None:
            return False
        portfolio.enabled = enabled
        portfolio.updated_at = utcnow()
        session.add(portfolio)
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
