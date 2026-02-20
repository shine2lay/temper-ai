"""SQLModel table definitions for event persistence."""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel

from temper_ai.storage.database.datetime_utils import utcnow


class EventLog(SQLModel, table=True):
    """Persistent log of emitted events."""

    __tablename__ = "event_log"

    id: str = Field(primary_key=True)
    event_type: str = Field(index=True)
    timestamp: datetime = Field(default_factory=utcnow, index=True)
    source_workflow_id: Optional[str] = Field(default=None, index=True)
    source_stage_name: Optional[str] = None
    agent_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    consumed: bool = False
    consumed_at: Optional[datetime] = None
    consumed_by: Optional[str] = None


class EventSubscription(SQLModel, table=True):
    """Persistent event subscriptions."""

    __tablename__ = "event_subscriptions"

    id: str = Field(primary_key=True)
    agent_id: Optional[str] = Field(default=None, index=True)
    event_type: str = Field(index=True)
    source_workflow_filter: Optional[str] = None
    payload_filter: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    handler_ref: Optional[str] = None
    workflow_to_trigger: Optional[str] = None
    active: bool = Field(default=True, index=True)
    last_event_id: Optional[str] = None
    last_triggered_at: Optional[datetime] = None


def _new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())
