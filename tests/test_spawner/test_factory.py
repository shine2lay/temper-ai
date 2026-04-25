"""Tests for the spawner factory — env-driven backend selection."""

from __future__ import annotations

import pytest

from temper_ai.spawner import SubprocessSpawner, get_spawner
from temper_ai.spawner.factory import reset_spawner
from temper_ai.worker_proto import SpawnerKind


@pytest.fixture(autouse=True)
def _reset():
    """Each test gets a fresh factory cache."""
    reset_spawner()
    yield
    reset_spawner()


def test_default_returns_subprocess_spawner(monkeypatch):
    monkeypatch.delenv("TEMPER_SPAWNER", raising=False)
    spawner = get_spawner()
    assert isinstance(spawner, SubprocessSpawner)


def test_explicit_subprocess_kind():
    spawner = get_spawner(SpawnerKind.subprocess)
    assert isinstance(spawner, SubprocessSpawner)


def test_string_kind_resolves():
    spawner = get_spawner("subprocess")
    assert isinstance(spawner, SubprocessSpawner)


def test_inprocess_raises_value_error():
    """inprocess is not a Spawner — it's the legacy thread path."""
    with pytest.raises(ValueError, match="legacy in-thread"):
        get_spawner(SpawnerKind.inprocess)


def test_docker_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="phase 6"):
        get_spawner(SpawnerKind.docker)


def test_k8s_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="v2"):
        get_spawner(SpawnerKind.k8s_job)


def test_singleton_caches_within_kind():
    a = get_spawner(SpawnerKind.subprocess)
    b = get_spawner(SpawnerKind.subprocess)
    assert a is b
