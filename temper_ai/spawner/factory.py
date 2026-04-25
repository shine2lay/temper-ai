"""Spawner factory — pick the right backend at server startup.

Single source of truth for "which spawner does the server use." Routes
ask for a Spawner; the factory hands back the implementation matching
$TEMPER_SPAWNER (default: inprocess for backward compatibility).
"""

from __future__ import annotations

import logging
import os

from temper_ai.spawner.base import Spawner
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
        NotImplementedError if the requested kind isn't implemented yet
        (docker / k8s_job land in phases 6+).

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
        _singleton = SubprocessSpawner()
    elif kind == SpawnerKind.docker:
        raise NotImplementedError("DockerSpawner lands in phase 6")
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


def reset_spawner() -> None:
    """For tests — clear the cached spawner so the next get_spawner() rebuilds."""
    global _singleton, _singleton_kind
    _singleton = None
    _singleton_kind = None
