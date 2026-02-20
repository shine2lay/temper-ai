"""Agent registry database model."""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from temper_ai.storage.database.datetime_utils import utcnow


class AgentRegistryDB(SQLModel, table=True):
    """Persistent agent registration record."""

    __tablename__ = "agent_registry"
    __table_args__ = (
        UniqueConstraint("name", name="uq_agent_registry_name"),
    )

    id: str = Field(primary_key=True)
    name: str = Field(max_length=128, index=True)
    description: str = ""
    version: str = "1.0"
    agent_type: str = "standard"
    config_path: Optional[str] = None
    config_snapshot: Dict[str, Any] = Field(sa_column=Column(JSON))
    memory_namespace: str = ""
    status: str = Field(default="registered", index=True)
    total_invocations: int = 0
    registered_at: datetime = Field(default_factory=utcnow)
    last_active_at: Optional[datetime] = None
    metadata_json: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
