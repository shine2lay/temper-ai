"""Spawner abstraction — how the server starts a workflow runner process.

The server imports `get_spawner()` and calls `spawn(execution_id)`. The
returned ProcessHandle is opaque; the spawner that produced it knows how
to `kill()` and `is_alive()` against it.

SubprocessSpawner runs each run as a child process of the watcher;
DockerSpawner gives each run a container of its own (TEMPER_SPAWNER=docker).
The ABC is here so adding new backends doesn't change the server's call site.
"""

from temper_ai.spawner.base import Spawner, SpawnerError
from temper_ai.spawner.docker_spawner import DockerSpawner
from temper_ai.spawner.factory import get_spawner
from temper_ai.spawner.subprocess_spawner import SubprocessSpawner

__all__ = [
    "DockerSpawner",
    "Spawner",
    "SpawnerError",
    "SubprocessSpawner",
    "get_spawner",
]
