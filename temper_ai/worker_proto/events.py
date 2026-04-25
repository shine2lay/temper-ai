"""Event wire types. Two shapes — durable milestones and ephemeral chunks.

Milestones go to Postgres `events` table; persisted forever (~5/min).
Chunks go to Redis Streams; ephemeral, MAXLEN-bounded (~50-100/sec per LLM call).

The two are NEVER mixed in storage but ARE merged on the WebSocket fan-out
to the dashboard. See worker_protocol_v1.md for the full storage tier model.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MilestoneEventType(str, Enum):
    """Coarse-grained workflow events persisted to Postgres `events` table.

    Matches the type values temper has been using historically (workflow.started,
    agent.completed, etc.) — preserved for backward compatibility with existing
    analytics scripts and the dashboard event timeline.
    """

    workflow_started = "workflow.started"
    workflow_completed = "workflow.completed"
    workflow_failed = "workflow.failed"
    workflow_cancelled = "workflow.cancelled"

    stage_started = "stage.started"
    stage_completed = "stage.completed"

    agent_started = "agent.started"
    agent_completed = "agent.completed"
    agent_failed = "agent.failed"

    llm_call_started = "llm.call.started"
    llm_call_completed = "llm.call.completed"
    llm_iteration = "llm.iteration"

    dispatch_applied = "dispatch.applied"
    checkpoint_saved = "checkpoint.saved"
    cancel_honored = "cancel.honored"


class EventEnvelope(BaseModel):
    """Shape of a milestone event before insertion into the events table.

    Matches the SQLModel `Event` columns exactly so a simple .model_dump()
    can be used for INSERT. Kept here as a wire-protocol type so the runner
    can construct events without importing the full SQLModel layer.
    """

    type: MilestoneEventType | str
    execution_id: str
    parent_id: str | None = None
    status: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChunkEvent(BaseModel):
    """Single LLM token / tool-call chunk for live streaming.

    Published to Redis Stream `chunks:{execution_id}` via XADD with MAXLEN.
    Server consumes via XREAD and fans out to dashboard WebSocket clients.

    Stream entries are auto-trimmed; do NOT use this type for anything that
    needs durability — milestones are the source of truth.
    """

    llm_call_id: str
    chunk_text: str = ""
    chunk_kind: str = "text"  # text | tool_use | tool_result | done
    token_count: int | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
