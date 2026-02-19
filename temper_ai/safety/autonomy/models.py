"""SQLModel tables for progressive autonomy persistence."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from temper_ai.storage.database.datetime_utils import utcnow

# ============================================================================
# Status constants
# ============================================================================

STATUS_ACTIVE = "active"
STATUS_WARNING = "warning"
STATUS_EXHAUSTED = "exhausted"


class AutonomyState(SQLModel, table=True):
    """Current autonomy state for an agent in a domain."""

    __tablename__ = "autonomy_states"

    id: str = Field(primary_key=True)
    agent_name: str = Field(index=True)
    domain: str = Field(index=True)
    current_level: int = Field(default=0)
    shadow_level: Optional[int] = None
    shadow_runs: int = Field(default=0)
    shadow_agreements: int = Field(default=0)
    last_escalation: Optional[datetime] = None
    last_de_escalation: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AutonomyTransition(SQLModel, table=True):
    """Record of an autonomy level transition."""

    __tablename__ = "autonomy_transitions"

    id: str = Field(primary_key=True)
    agent_name: str = Field(index=True)
    domain: str
    from_level: int
    to_level: int
    reason: str
    trigger: str
    merit_snapshot: Dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=utcnow)


class BudgetRecord(SQLModel, table=True):
    """Budget tracking for cost-controlled autonomy."""

    __tablename__ = "budget_records"

    id: str = Field(primary_key=True)
    scope: str = Field(index=True)
    period: str
    budget_usd: float
    spent_usd: float = Field(default=0.0)
    action_count: int = Field(default=0)
    status: str = Field(default=STATUS_ACTIVE)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class EmergencyStopEvent(SQLModel, table=True):
    """Record of an emergency stop activation."""

    __tablename__ = "emergency_stop_events"

    id: str = Field(primary_key=True)
    triggered_by: str
    reason: str
    agents_halted: List[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    halt_duration_ms: Optional[float] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
