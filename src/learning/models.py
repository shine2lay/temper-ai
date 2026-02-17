"""SQLModel tables for continuous learning data."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from src.storage.database.datetime_utils import utcnow

# Pattern type constants
PATTERN_AGENT_PERFORMANCE = "agent_performance"
PATTERN_MODEL_EFFECTIVENESS = "model_effectiveness"
PATTERN_FAILURE = "failure"
PATTERN_COST = "cost"
PATTERN_COLLABORATION = "collaboration"

ALL_PATTERN_TYPES = (
    PATTERN_AGENT_PERFORMANCE,
    PATTERN_MODEL_EFFECTIVENESS,
    PATTERN_FAILURE,
    PATTERN_COST,
    PATTERN_COLLABORATION,
)

# Status constants
STATUS_ACTIVE = "active"
STATUS_APPLIED = "applied"
STATUS_DISMISSED = "dismissed"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_PENDING = "pending"
STATUS_EXPERIMENT = "experiment"


class LearnedPattern(SQLModel, table=True):
    """A pattern discovered by mining execution history."""

    __tablename__ = "learned_patterns"

    id: str = Field(primary_key=True)
    pattern_type: str = Field(index=True)
    title: str
    description: str
    evidence: Dict[str, Any] = Field(sa_column=Column(JSON))
    confidence: float
    impact_score: float
    recommendation: Optional[str] = None
    status: str = Field(default=STATUS_ACTIVE, index=True)
    source_workflow_ids: List[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MiningRun(SQLModel, table=True):
    """Record of a pattern mining execution."""

    __tablename__ = "mining_runs"

    id: str = Field(primary_key=True)
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None
    status: str = Field(default=STATUS_RUNNING)
    patterns_found: int = Field(default=0)
    patterns_new: int = Field(default=0)
    novelty_score: float = Field(default=0.0)
    miner_stats: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    error_message: Optional[str] = None


class TuneRecommendation(SQLModel, table=True):
    """An actionable config-change recommendation from a learned pattern."""

    __tablename__ = "tune_recommendations"

    id: str = Field(primary_key=True)
    pattern_id: str = Field(index=True)
    config_path: str
    field_path: str
    current_value: str
    recommended_value: str
    rationale: str
    status: str = Field(default=STATUS_PENDING)
    created_at: datetime = Field(default_factory=utcnow)
