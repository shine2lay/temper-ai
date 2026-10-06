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


class CleanupHold(SQLModel, table=True):
    """Clean-ups a failed run is keeping back, and until when.

    A clean-up is a step that says what it undoes -- tearing down a dev stack, removing a
    worktree. When a run fails, temper holds them instead of running them, so the step that
    failed can be tried again in the setup it needs. This row is the memory of that: it
    survives a temper restart, and it is what the deadline is measured against.

    It ends in one of four ways: the run is picked up again and finishes (``done``), someone
    presses Give up (``released``), the deadline passes (``released``), or a later attempt --
    a resume, or a fork -- takes it over (``taken_over``), so an old deadline cannot tear down
    a setup a newer attempt is using.
    """

    __tablename__ = "cleanup_holds"

    execution_id: str = Field(primary_key=True)
    workflow_name: str = Field()
    workspace_path: str = Field(default="")
    inputs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # The clean-ups being held, by node path, with what each of them undoes.
    node_paths: list[Any] = Field(default_factory=list, sa_column=Column(JSON))
    # Where the run stopped, so the page can say what is being held open and why.
    stopped_at: str | None = Field(default=None)
    stop_reason: str | None = Field(default=None)

    status: str = Field(default="waiting", index=True)  # waiting / released / done / taken_over
    deadline: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = Field(default=None)
    ended_by: str | None = Field(default=None)  # "deadline", "give_up", "resume", or a run id


class ResumeClaim(SQLModel, table=True):
    """Who is carrying a cut-off Pi run on: one row per run, so only one asker starts it.

    Resume, the API and temper's own pick-up at start-up may all ask at the same moment to
    carry on a Pi run that was cut off while it ran. Before starting, each asker claims the run
    with one write that exactly one of them wins (runner/resume_claim.py): the first to insert
    the row, or, once the claim it holds has ended, the one whose update still finds the token
    it replaces. A run parked on an answer is claimed on its parked attempt instead
    (runner/parked.py).
    """

    __tablename__ = "resume_claims"

    execution_id: str = Field(primary_key=True)
    # The run's newest attempt when the claim was taken: the one the claimed start carries on.
    from_attempt: str = Field()
    # Changes with every claim, so a take-over or a give-back touches only the claim it read.
    token: str = Field()
    claimed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    claimed_by: str = Field(default="")


# Common query patterns:
#   "what's currently running" → WHERE status = 'running'
#   "anything to reap" → WHERE status = 'running' ORDER BY started_at
#   "this user's recent runs" → WHERE workflow_name = ? ORDER BY created_at DESC
Index("idx_workflow_runs_status_created", WorkflowRun.status, WorkflowRun.created_at)  # type: ignore[arg-type]
