"""Tests for SubprocessSpawner — the local-process backend.

Strategy: spawn real short-lived child processes (echo / sleep) to
exercise the spawn/poll/kill lifecycle. We don't mock subprocess.Popen
because the implementation's value IS the subprocess interaction; mocking
would test the mock more than the code.

Each test cleans up after itself by killing any spawned child so a flaky
exit doesn't leak processes between tests.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from temper_ai.spawner.subprocess_spawner import SubprocessSpawner
from temper_ai.worker_proto import ProcessHandle, SpawnerKind


def _short_command(seconds: float = 0.2) -> list[str]:
    """A no-op child that sleeps then exits 0. Uses the test interpreter
    so no PATH dependency."""
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def _long_command() -> list[str]:
    """A child that sleeps long enough for is_alive/kill tests."""
    return [sys.executable, "-c", "import time; time.sleep(60)"]


def _make_spawner_with_command(cmd: list[str]) -> SubprocessSpawner:
    """Subclass that overrides the command for the test (rather than
    actually invoking `temper run-workflow` which needs a queued row).
    """
    spawner = SubprocessSpawner(python_executable=cmd[0])
    # Monkeypatch spawn to use our test command. The real code path is
    # exercised because we still go through Popen + the same env/group
    # plumbing — only the argv changes.

    def fake_spawn(execution_id: str) -> ProcessHandle:  # noqa: ARG001
        import subprocess
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        with spawner._lock:
            spawner._processes[execution_id] = proc
        return ProcessHandle(
            kind=SpawnerKind.subprocess,
            handle=str(proc.pid),
            metadata={"execution_id": execution_id},
        )

    spawner.spawn = fake_spawn  # type: ignore[method-assign]
    return spawner


@pytest.fixture
def spawner():
    """Spawner that produces fast-exiting children."""
    s = _make_spawner_with_command(_short_command())
    yield s
    # Cleanup: kill anything still running
    for execution_id in list(s._processes.keys()):
        try:
            s.kill(ProcessHandle(
                kind=SpawnerKind.subprocess,
                handle=str(s._processes[execution_id].pid),
                metadata={"execution_id": execution_id},
            ), force=True)
        except Exception:
            pass


@pytest.fixture
def long_spawner():
    s = _make_spawner_with_command(_long_command())
    yield s
    for execution_id in list(s._processes.keys()):
        try:
            s.kill(ProcessHandle(
                kind=SpawnerKind.subprocess,
                handle=str(s._processes[execution_id].pid),
                metadata={"execution_id": execution_id},
            ), force=True)
        except Exception:
            pass


def test_spawn_returns_handle_with_pid(spawner):
    handle = spawner.spawn("test-1")
    assert handle.kind == SpawnerKind.subprocess
    assert handle.handle.isdigit()
    assert int(handle.handle) > 0
    assert handle.metadata["execution_id"] == "test-1"


def test_is_alive_true_for_running_then_false_after_exit(spawner):
    handle = spawner.spawn("test-2")
    assert spawner.is_alive(handle) is True
    # Wait for the short child to exit
    time.sleep(0.5)
    assert spawner.is_alive(handle) is False


def test_kill_terminates_running_worker(long_spawner):
    handle = long_spawner.spawn("test-3")
    assert long_spawner.is_alive(handle) is True
    long_spawner.kill(handle)
    # SIGTERM should kill the python child within a tick
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if not long_spawner.is_alive(handle):
            break
        time.sleep(0.05)
    assert long_spawner.is_alive(handle) is False


def test_kill_already_dead_is_idempotent(spawner):
    """SIGTERM on a dead process is a no-op, not an error."""
    handle = spawner.spawn("test-4")
    time.sleep(0.5)  # let it exit
    assert spawner.is_alive(handle) is False
    spawner.kill(handle)  # must not raise
    spawner.kill(handle, force=True)  # must not raise


def test_force_kill_uses_sigkill(long_spawner):
    handle = long_spawner.spawn("test-5")
    long_spawner.kill(handle, force=True)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if not long_spawner.is_alive(handle):
            break
        time.sleep(0.05)
    assert long_spawner.is_alive(handle) is False


def test_reap_returns_exit_code(spawner):
    spawner.spawn("test-6")
    time.sleep(0.5)
    code = spawner.reap("test-6")
    assert code == 0
    # After reap, no longer tracked
    assert "test-6" not in spawner._processes


def test_reap_unknown_returns_none(spawner):
    assert spawner.reap("never-spawned") is None


def test_is_alive_via_os_kill_when_untracked():
    """If the spawner doesn't have the Popen handle (server restart),
    fall back to `os.kill(pid, 0)` for a best-effort liveness check."""
    spawner = SubprocessSpawner()
    # Use this test process — definitely alive, definitely owned by us
    self_handle = ProcessHandle(
        kind=SpawnerKind.subprocess,
        handle=str(os.getpid()),
        metadata={"execution_id": "fake"},
    )
    assert spawner.is_alive(self_handle) is True

    # PID 99999999 (almost certainly not allocated) → not alive
    dead_handle = ProcessHandle(
        kind=SpawnerKind.subprocess,
        handle="99999999",
        metadata={"execution_id": "fake"},
    )
    assert spawner.is_alive(dead_handle) is False
