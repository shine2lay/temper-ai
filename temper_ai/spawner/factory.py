"""Spawner factory — pick the right backend at server startup.

Single source of truth for "which spawner does the server use." Routes
ask for a Spawner; the factory hands back the implementation matching
$TEMPER_SPAWNER (default: inprocess for backward compatibility).
"""

from __future__ import annotations

import logging
import os

from temper_ai.spawner.base import Spawner, SpawnerError
from temper_ai.spawner.docker_spawner import DockerSpawner
from temper_ai.spawner.subprocess_spawner import SubprocessSpawner
from temper_ai.worker_proto import SpawnerKind

logger = logging.getLogger(__name__)

_singleton: Spawner | None = None
_singleton_kind: SpawnerKind | None = None


def get_spawner(kind: SpawnerKind | str | None = None) -> Spawner:
    """Return a Spawner. Cached after first call.

    Args:
        kind: explicit override (mainly for tests). Default: read
            $TEMPER_SPAWNER, fall back to subprocess.

    Raises:
        NotImplementedError for k8s_job (v2).

    The function intentionally does NOT support `inprocess` here — that
    backend is the existing thread-based path inlined in routes.py and
    has no Spawner implementation. Phase 6 unifies them; until then,
    routes.py picks "inprocess vs spawner" via the env flag itself and
    only calls get_spawner() when it's not inprocess.
    """
    global _singleton, _singleton_kind

    if kind is None:
        kind = os.environ.get("TEMPER_SPAWNER", SpawnerKind.subprocess.value)
    if isinstance(kind, str):
        kind = SpawnerKind(kind)

    if _singleton is not None and _singleton_kind == kind:
        return _singleton

    if kind == SpawnerKind.subprocess:
        refuse_subprocess_beside_docker()
        _singleton = SubprocessSpawner()
    elif kind == SpawnerKind.docker:
        _singleton = DockerSpawner()
    elif kind == SpawnerKind.k8s_job:
        raise NotImplementedError("K8s spawner is v2 (out of phase scope)")
    elif kind == SpawnerKind.inprocess:
        raise ValueError(
            "inprocess is not a Spawner — it's the legacy in-thread path. "
            "Routes select it via TEMPER_EXECUTION_MODE before reaching here.",
        )
    else:
        raise ValueError(f"Unknown spawner kind: {kind!r}")

    _singleton_kind = kind
    logger.info("Spawner initialized: %s", kind.value)
    return _singleton


#: Where a Docker socket shows up in a container or on a host (HOME-REVIEW H1). A test points
#: this at a path that doesn't exist (tests/conftest.py), since CI and dev hosts have one.
DOCKER_SOCKETS: tuple[str, ...] = ("/var/run/docker.sock", "/run/docker.sock")
#: Settings that point Docker's client somewhere else (same test hook).
DOCKER_HOST_ENVS: tuple[str, ...] = ("DOCKER_HOST",)


class SubprocessBesideDocker(SpawnerError):  # noqa: N818 - a refusal, named for what it refuses
    """The subprocess spawner was asked for in a process that can reach Docker (H1)."""


def docker_reachable() -> str | None:
    """How this process could reach Docker: a socket path, ``DOCKER_HOST``, or None."""
    for name in DOCKER_HOST_ENVS:
        if os.environ.get(name, "").strip():
            return name
    for path in DOCKER_SOCKETS:
        if os.path.exists(path):
            return path
    return None


def refuse_subprocess_beside_docker() -> None:
    """H1 / SW-75: a run started as a child process here would share this process's Docker
    socket, which is the host. Only the Pi lane (``TEMPER_LANE=pi``: the pi-worker service)
    runs its runs that way beside a socket, because its runs are Pi runs that start their own
    member boxes and nothing else (runner/lanes.py, the Pi-only rule). Everywhere else --
    the main worker, the server's subprocess mode -- this refuses, so a worker given the
    socket without the Pi lane setting never starts."""
    from temper_ai.runner.lanes import PI_LANE, this_lane

    where = docker_reachable()
    if where is None:
        return
    if this_lane() == PI_LANE:  # a bad TEMPER_LANE raises LaneSettingError: no start either
        return
    raise SubprocessBesideDocker(
        f"TEMPER_SPAWNER=subprocess in a process that can reach Docker ({where}): its runs "
        f"would hold the host's Docker socket. Use TEMPER_SPAWNER=docker, or take the socket "
        f"away; only the Pi lane (TEMPER_LANE=pi) runs child processes beside it.")


def reset_spawner() -> None:
    """For tests — clear the cached spawner so the next get_spawner() rebuilds."""
    global _singleton, _singleton_kind
    _singleton = None
    _singleton_kind = None
