"""Worker protocol — wire types shared between server and workflow runner subprocesses.

These are pure data types. They're separate from database models (in
checkpoint/, observability/, runner/models.py) because they describe the
contract between server and worker, not the persistence shape.

The runner reads/writes the database via the same SQLModel classes the server
uses — no proxy schemas. This package is for things that cross the
process boundary (CLI args, event bus messages, spawn handles).

Reference: protocol shape modeled on GitLab CI runner protocol (incremental
trace chunks via Redis), Argo Workflows pod spec (separation of state vs
logs), and Temporal worker activities (typed work units).
"""

from temper_ai.worker_proto.events import (
    ChunkEvent,
    EventEnvelope,
    MilestoneEventType,
)
from temper_ai.worker_proto.run import (
    RunRequest,
    RunStatus,
    WorkflowRunSpec,
)
from temper_ai.worker_proto.spawn import ProcessHandle, SpawnerKind

__all__ = [
    # Spawn
    "ProcessHandle",
    "SpawnerKind",
    # Run
    "RunRequest",
    "RunStatus",
    "WorkflowRunSpec",
    # Events
    "ChunkEvent",
    "EventEnvelope",
    "MilestoneEventType",
]
