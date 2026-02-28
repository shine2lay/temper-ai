"""SQLModel table definitions for event persistence."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel

from temper_ai.shared.utils.datetime_utils import utcnow


class EventLog(SQLModel, table=True):
    """Persistent log of emitted events."""

    __tablename__ = "event_log"

    id: str = Field(primary_key=True)
    event_type: str = Field(index=True)
    timestamp: datetime = Field(default_factory=utcnow, index=True)
    source_workflow_id: str | None = Field(default=None, index=True)
    source_stage_name: str | None = None
    agent_id: str | None = None
    payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    consumed: bool = False
    consumed_at: datetime | None = None
    consumed_by: str | None = None


class EventSubscription(SQLModel, table=True):
    """Persistent event subscriptions."""

    __tablename__ = "event_subscriptions"

    id: str = Field(primary_key=True)
    agent_id: str | None = Field(default=None, index=True)
    event_type: str = Field(index=True)
    source_workflow_filter: str | None = None
    payload_filter: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    handler_ref: str | None = None
    workflow_to_trigger: str | None = None
    active: bool = Field(default=True, index=True)
    last_event_id: str | None = None
    last_triggered_at: datetime | None = None
