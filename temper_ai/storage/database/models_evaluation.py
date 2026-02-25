"""Database model for per-agent evaluation results.

Stores evaluation outcomes produced by the EvaluationDispatcher
after each agent completes execution.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, ForeignKey, Index, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from temper_ai.storage.database.constants import FK_AGENT_EXECUTIONS_ID, FK_CASCADE
from temper_ai.storage.database.datetime_utils import utcnow


class AgentEvaluationResult(SQLModel, table=True):
    """Per-agent evaluation result persisted by the EvaluationDispatcher."""

    __tablename__ = "agent_evaluation_results"
    __table_args__ = (
        UniqueConstraint(
            "agent_execution_id",
            "evaluation_name",
            name="uq_eval_agent_exec_name",
        ),
    )

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    tenant_id: str = Field(index=True)
    agent_execution_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey(FK_AGENT_EXECUTIONS_ID, ondelete=FK_CASCADE),
            index=True,
            nullable=False,
        ),
    )
    evaluation_name: str = Field(index=True)
    evaluator_type: str  # "criteria" | "scored" | "composite"
    score: float  # 0.0 - 1.0
    passed: bool | None = None
    details: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON),
    )
    created_at: datetime = Field(default_factory=utcnow)


# Composite index for optimizer queries: filter by evaluation + score threshold
Index(
    "idx_eval_name_score",
    AgentEvaluationResult.evaluation_name,  # type: ignore[arg-type]
    AgentEvaluationResult.score,  # type: ignore[arg-type]
)
