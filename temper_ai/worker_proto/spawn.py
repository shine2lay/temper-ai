"""Spawner abstraction: how the server starts a workflow runner.

Three backends planned:
  subprocess — local Python subprocess; default for dev. Inherits server env.
  docker     — runs `temper/worker:latest` container per run; isolated env.
  k8s_job    — kubectl create job per run; cloud-native (deferred to v2).
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SpawnerKind(str, Enum):
    """Which spawn backend the server uses to start runner subprocesses.

    Pick via TEMPER_SPAWNER env var.
    """

    inprocess = "inprocess"  # legacy; runs workflow in server process (backward compat)
    subprocess = "subprocess"
    docker = "docker"
    k8s_job = "k8s_job"  # v2


class ProcessHandle(BaseModel):
    """Opaque handle the spawner returns after starting a runner.

    Server stores this on the WorkflowRun row so it can:
      - poll for liveness
      - send SIGTERM on cancel
      - re-discover after server restart (best-effort)

    Shape varies per spawner (PID for subprocess, container ID for docker,
    namespaced job name for k8s) but all spawners produce the same envelope.
    """

    kind: SpawnerKind
    handle: str  # PID / container_id / k8s job name
    spawned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
