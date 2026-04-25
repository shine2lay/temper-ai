"""WorkflowRun model — server-side tracking of spawned runner subprocesses.

Distinct from `events` (which records what happened) and `checkpoints`
(which records resumable state). This row is the spawner's bookkeeping:
which subprocess is running, what handle do we use to kill / poll it,
has cancellation been requested.

Phase 0: model defined; not yet wired to anything. Phase 3 wires it in
when SubprocessSpawner lands.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel


class WorkflowRun(SQLModel, table=True):
    """One row per workflow execution that the spawner has dispatched.

    Lifecycle:
      1. created       — POST /api/runs inserts row (status=queued)
      2. spawned       — spawner returns a ProcessHandle (status=running, spawner_handle set)
      3. heartbeat     — runner writes checkpoints to the checkpoints table; server's
                         reaper considers a run dead if no checkpoint for >5min AND
                         spawner says the process is no longer alive
      4. terminal      — runner exits; spawner detects; server updates status to
                         completed / failed / cancelled / orphaned

    Cancellation flow:
      User → POST /api/runs/{id}/cancel → UPDATE cancel_requested=true
        → spawner sends SIGTERM to handle
          → runner catches signal between agent invocations
            → runner writes cancel.honored milestone + exits cleanly
              → spawner reaps; server updates status=cancelled
    """

    __tablename__ = "workflow_runs"

    execution_id: str = Field(primary_key=True)
    workflow_name: str = Field()
    workspace_path: str = Field()
    inputs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # Lifecycle status — see RunStatus enum in worker_proto.run
    status: str = Field(default="queued", index=True)

    # Spawner bookkeeping — see ProcessHandle in worker_proto.spawn
    spawner_kind: str | None = Field(default=None)  # subprocess / docker / k8s_job / inprocess
    spawner_handle: str | None = Field(default=None)  # PID / container_id / job name
    spawner_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON),
    )

    # Cancellation — runner polls this between agent invocations
    cancel_requested: bool = Field(default=False, index=True)

    # Retry accounting — server reaper consults if a run dies
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=1)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    # Terminal payload (cleared on retry)
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


# Common query patterns:
#   "what's currently running" → WHERE status = 'running'
#   "anything to reap" → WHERE status = 'running' ORDER BY started_at
#   "this user's recent runs" → WHERE workflow_name = ? ORDER BY created_at DESC
Index("idx_workflow_runs_status_created", WorkflowRun.status, WorkflowRun.created_at)  # type: ignore[arg-type]
