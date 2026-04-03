"""Checkpoint database model — append-only execution state history."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel


class Checkpoint(SQLModel, table=True):
    """A single checkpoint entry in the execution history.

    Checkpoints form an append-only log per execution. Each entry records
    a state change: node completed, agent completed, or loop rewind.

    State at any point is reconstructed by replaying entries 0..N in order.

    Branching: a forked execution points to a parent checkpoint via parent_id.
    Reconstruction follows the parent chain to build the full history.
    """

    __tablename__ = "checkpoints"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    execution_id: str = Field(index=True)
    sequence: int = Field()  # monotonic within an execution: 0, 1, 2, ...

    # What happened
    event_type: str = Field()  # node_completed, agent_completed, loop_rewind, workflow_started
    node_name: str | None = Field(default=None)
    agent_name: str | None = Field(default=None)

    # Result data
    status: str = Field()
    output: str | None = Field(default=None)
    structured_output: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON),
    )
    cost_usd: float = Field(default=0.0)
    total_tokens: int = Field(default=0)
    duration_seconds: float = Field(default=0.0)
    error: str | None = Field(default=None)

    # Branching — points to a checkpoint row in any execution
    parent_id: str | None = Field(default=None, index=True)

    # Extra context (loop_counts, cleared_nodes, etc.)
    metadata_: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON),
    )

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )


Index("idx_checkpoints_exec_seq", Checkpoint.execution_id, Checkpoint.sequence)
