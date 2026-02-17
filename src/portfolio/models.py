"""SQLModel tables for portfolio management data."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from src.storage.database.datetime_utils import utcnow


class PortfolioRecord(SQLModel, table=True):
    """A persisted portfolio definition."""

    __tablename__ = "portfolios"

    id: str = Field(primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str = ""
    config: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    enabled: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: Optional[datetime] = None


class ProductRunRecord(SQLModel, table=True):
    """Per-product execution log entry."""

    __tablename__ = "product_runs"

    id: str = Field(primary_key=True)
    portfolio_id: str = Field(index=True)
    product_type: str = Field(index=True)
    workflow_id: str = Field(index=True)
    status: str = Field(default="running", index=True)
    cost_usd: float = 0.0
    duration_s: float = 0.0
    success: bool = False
    metadata_json: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None


class SharedComponentRecord(SQLModel, table=True):
    """Detected shared component between products."""

    __tablename__ = "shared_components"

    id: str = Field(primary_key=True)
    source_stage: str = Field(index=True)
    target_stage: str = Field(index=True)
    similarity: float = 0.0
    shared_keys: List[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    differing_keys: List[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    status: str = Field(default="detected")
    created_at: datetime = Field(default_factory=utcnow)


class KGConceptRecord(SQLModel, table=True):
    """Knowledge graph node."""

    __tablename__ = "kg_concepts"

    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    concept_type: str = Field(index=True)
    properties: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=utcnow)


class KGEdgeRecord(SQLModel, table=True):
    """Knowledge graph edge."""

    __tablename__ = "kg_edges"

    id: str = Field(primary_key=True)
    source_id: str = Field(index=True)
    target_id: str = Field(index=True)
    relation: str = Field(index=True)
    weight: float = 1.0
    properties: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=utcnow)


class TechCompatibilityRecord(SQLModel, table=True):
    """Technology compatibility assessment."""

    __tablename__ = "tech_compatibility"

    id: str = Field(primary_key=True)
    tech_a: str = Field(index=True)
    tech_b: str = Field(index=True)
    compatibility_score: float = 0.0
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class PortfolioSnapshotRecord(SQLModel, table=True):
    """Periodic scorecard snapshot for trend analysis."""

    __tablename__ = "portfolio_snapshots"

    id: str = Field(primary_key=True)
    portfolio_id: str = Field(index=True)
    product_type: str = Field(index=True)
    success_rate: float = 0.0
    cost_efficiency: float = 0.0
    trend: float = 0.0
    utilization: float = 0.0
    composite_score: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)
