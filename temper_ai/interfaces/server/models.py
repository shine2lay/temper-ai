"""Database models for MAF Server persistent run history."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from temper_ai.storage.database.datetime_utils import utcnow


class ServerRun(SQLModel, table=True):
    """Persistent record of a server-triggered workflow execution."""

    __tablename__ = "server_runs"

    execution_id: str = Field(primary_key=True)
    workflow_id: str | None = Field(default=None, index=True)
    workflow_path: str
    workflow_name: str = Field(index=True)
    status: str = Field(index=True)  # pending|running|completed|failed|cancelled
    created_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    workspace: str | None = None
    result_summary: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error_message: str | None = None
    tenant_id: str | None = Field(default=None, index=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "workflow_path": self.workflow_path,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "input_data": self.input_data,
            "workspace": self.workspace,
            "result_summary": self.result_summary,
            "error_message": self.error_message,
            "tenant_id": self.tenant_id,
        }
