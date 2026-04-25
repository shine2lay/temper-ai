"""Run-level types: what the server hands to the runner subprocess at spawn."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    """Lifecycle of a single workflow run.

    Status transitions:
      queued    → server has accepted the run; spawner has not yet been called
      running   → subprocess is alive and processing
      completed → workflow engine exited 0 with all required nodes done
      failed    → subprocess exited non-zero or workflow engine reported terminal failure
      cancelled → cancellation was requested and honored
      orphaned  → server lost track of subprocess (e.g. server restart);
                  subprocess may still be alive but not under server control
    """

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    orphaned = "orphaned"


class WorkflowRunSpec(BaseModel):
    """Snapshot of everything the runner needs to execute one workflow.

    Frozen at spawn time so hot-reload of configs / workflow files does not
    affect in-flight runs (mirrors how Temporal snapshots activity inputs).
    Server resolves all references (workflow YAML, agent configs) before
    handing this to the subprocess.
    """

    execution_id: str
    workflow_name: str
    workspace_path: str
    inputs: dict[str, Any] = Field(default_factory=dict)

    # Runtime knobs
    max_attempts: int = 1
    deadline_seconds: int | None = None  # hard timeout; None = no deadline


class RunRequest(BaseModel):
    """User-facing request to start a workflow run. Server transforms this
    into a `WorkflowRunSpec` after resolving the workflow definition + inputs.
    """

    workflow: str  # workflow name registered with the engine
    workspace_path: str | None = None  # else default per workflow
    inputs: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = 1
