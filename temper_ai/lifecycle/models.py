"""SQLModel tables for lifecycle adaptation data."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from temper_ai.storage.database.datetime_utils import utcnow

# Status constants
STATUS_ENABLED = "enabled"
STATUS_DISABLED = "disabled"


class LifecycleAdaptation(SQLModel, table=True):
    """Record of a lifecycle adaptation applied to a workflow."""

    __tablename__ = "lifecycle_adaptations"

    id: str = Field(primary_key=True)
    workflow_id: str = Field(index=True)
    profile_name: str = Field(index=True)
    characteristics: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    rules_applied: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    stages_original: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    stages_adapted: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    experiment_id: str | None = None
    experiment_variant: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class LifecycleProfileRecord(SQLModel, table=True):
    """A lifecycle profile stored in the database."""

    __tablename__ = "lifecycle_profiles"

    id: str = Field(primary_key=True)
    name: str = Field(unique=True)
    description: str = ""
    version: str = "1.0"
    product_types: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    rules: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    enabled: bool = True
    source: str = "manual"
    confidence: float = 1.0
    min_autonomy_level: int = 0
    requires_approval: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None
