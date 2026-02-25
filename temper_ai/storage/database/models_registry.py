"""Agent registry database model."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from temper_ai.storage.database.datetime_utils import utcnow

_MAX_NAME_LENGTH = 128


class AgentRegistryDB(SQLModel, table=True):
    """Persistent agent registration record."""

    __tablename__ = "agent_registry"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agent_registry_tenant_name"),
    )

    id: str = Field(primary_key=True)
    tenant_id: str = Field(index=True)
    name: str = Field(max_length=_MAX_NAME_LENGTH, index=True)
    description: str = ""
    version: str = "1.0"
    agent_type: str = "standard"
    config_path: str | None = None
    config_snapshot: dict[str, Any] = Field(sa_column=Column(JSON))
    memory_namespace: str = ""
    status: str = Field(default="registered", index=True)
    total_invocations: int = 0
    registered_at: datetime = Field(default_factory=utcnow)
    last_active_at: datetime | None = None
    metadata_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
