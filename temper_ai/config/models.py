"""Config table — single table for all config types."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel


class Config(SQLModel, table=True):
    """Stores workflow, stage, and agent configurations as JSONB.

    Configs are imported from YAML or created via API.
    The DB is the source of truth at runtime.
    """

    __tablename__ = "configs"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    type: str = Field(index=True)  # "workflow" | "stage" | "agent"
    name: str = Field(index=True)
    schema_version: str = Field(default="1.0")
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


Index("idx_configs_type_name", Config.type, Config.name, unique=True)
