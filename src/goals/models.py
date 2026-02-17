"""SQLModel tables for goal proposal data."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from src.storage.database.datetime_utils import utcnow


class GoalProposalRecord(SQLModel, table=True):
    """A persisted goal proposal."""

    __tablename__ = "goal_proposals"

    id: str = Field(primary_key=True)
    goal_type: str = Field(index=True)
    title: str
    description: str
    status: str = Field(default="proposed", index=True)
    risk_assessment: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    effort_estimate: str = Field(default="medium")
    expected_impacts: List[Dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    evidence: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    source_product_type: Optional[str] = Field(default=None, index=True)
    applicable_product_types: List[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    proposed_actions: List[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    priority_score: float = Field(default=0.0)
    reviewer: Optional[str] = None
    review_reason: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AnalysisRun(SQLModel, table=True):
    """Record of a goal analysis execution."""

    __tablename__ = "analysis_runs"

    id: str = Field(primary_key=True)
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None
    status: str = Field(default="running")
    proposals_generated: int = Field(default=0)
    analyzer_stats: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    error_message: Optional[str] = None
