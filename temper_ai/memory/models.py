"""Table backing the SQL memory store."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel


class Memory(SQLModel, table=True):
    """One stored memory for an (agent, scope) pair.

    `scope` partitions memories the same way the store interface defines it
    (for example `project:/path/to/repo`), so the same agent keeps separate
    memories per project.
    """

    __tablename__ = "memories"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    agent_name: str = Field(index=True)
    scope: str = Field(index=True)
    content: str
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)

    __table_args__ = (
        Index("ix_memories_agent_scope_created", "agent_name", "scope", "created_at"),
    )
