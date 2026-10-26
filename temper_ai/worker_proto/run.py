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
    """Legacy run parameters, not a closed configuration snapshot.

    Legacy workers resolve mutable workflow/agent names at startup. Candidate
    admission instead restores the protected run JSON through AdmissionTransport;
    this object cannot install or authenticate that reserved record.
    """

    execution_id: str
    workflow_name: str
    workspace_path: str
    inputs: dict[str, Any] = Field(default_factory=dict)

    # Runtime knobs
    max_attempts: int = 1
    deadline_seconds: int | None = None  # hard timeout; None = no deadline


class RunRequest(BaseModel):
    """Legacy internal request, NOT api/routes.py's actual HTTP RunRequest.

    Does not opt in to admission. Use the server's authenticated candidate route,
    whose request has the optional descriptor data and separate trust binding.
    """

    workflow: str  # workflow name registered with the engine
    workspace_path: str | None = None  # else default per workflow
    inputs: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = 1
