"""Single event table for all observability data."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel


class Event(SQLModel, table=True):
    """Generic observability event.

    Every trackable thing in the system is an event: workflow runs,
    stage executions, agent calls, LLM requests, tool invocations.

    Events form a tree via parent_id. execution_id is denormalized
    for fast "give me everything for this run" queries.
    """

    __tablename__ = "events"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    type: str = Field(index=True)
    parent_id: str | None = Field(default=None, index=True)
    execution_id: str | None = Field(default=None, index=True)
    status: str | None = Field(default=None, index=True)
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        index=True,
    )


Index("idx_events_execution_type", Event.execution_id, Event.type)  # type: ignore[arg-type]
Index("idx_events_execution_timestamp", Event.execution_id, Event.timestamp)  # type: ignore[arg-type]
