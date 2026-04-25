"""Spawner abstraction — how the server starts a workflow runner process.

The server imports `get_spawner()` and calls `spawn(execution_id)`. The
returned ProcessHandle is opaque; the spawner that produced it knows how
to `kill()` and `is_alive()` against it.

Phase 3 ships SubprocessSpawner only. Phase 6 adds DockerSpawner. The
ABC is here so adding new backends doesn't change the server's call site.
"""

from temper_ai.spawner.base import Spawner, SpawnerError
from temper_ai.spawner.factory import get_spawner
from temper_ai.spawner.subprocess_spawner import SubprocessSpawner

__all__ = [
    "Spawner",
    "SpawnerError",
    "SubprocessSpawner",
    "get_spawner",
]
