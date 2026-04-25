"""Spawner ABC + shared exception type.

Each backend (subprocess, docker, k8s) implements this contract. The server
imports only `Spawner` and calls `get_spawner()` to pick the implementation
at runtime; the backend is invisible above this line.

Lifecycle:
  spawn(execution_id) → ProcessHandle    # creates the worker
  is_alive(handle) → bool                # poll for liveness
  kill(handle, signal=SIGTERM) → None    # send a signal; cooperative cancel first
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from temper_ai.worker_proto import ProcessHandle


class SpawnerError(Exception):
    """Raised when spawn / kill / poll fails for backend-specific reasons.

    Routes catch this and convert to HTTP 503 — a spawn failure usually
    means infra is down (subprocess can't fork, docker daemon missing,
    k8s API unreachable). Distinct from workflow-level failures.
    """


class Spawner(ABC):
    """Backend-agnostic interface for starting workflow runner processes.

    Implementations must be reusable across many spawns; the server calls
    `get_spawner()` once and reuses the instance for every POST /api/runs.
    """

    @abstractmethod
    def spawn(self, execution_id: str) -> ProcessHandle:
        """Start a worker for the given execution_id.

        Precondition: a WorkflowRun row with execution_id=<id> already
        exists in the DB (status="queued"). The worker reads the row at
        startup, so the spawner only needs to launch the process.

        Returns: ProcessHandle the server stores for liveness/kill.
        Raises: SpawnerError if the backend can't start the process.
        """

    @abstractmethod
    def is_alive(self, handle: ProcessHandle) -> bool:
        """Whether the worker referenced by `handle` is still running.

        Used by the reaper to detect zombie/dead workers and update
        WorkflowRun.status from running → orphaned.
        """

    @abstractmethod
    def kill(self, handle: ProcessHandle, *, force: bool = False) -> None:
        """Request the worker stop.

        force=False sends SIGTERM (cooperative — worker writes a final
        cancelled milestone, exits cleanly). force=True sends SIGKILL
        (use only as escalation when the worker ignores SIGTERM).

        Raises SpawnerError if the kill itself fails (handle gone, etc.);
        a worker that's already dead is NOT an error — kill() is idempotent.
        """
