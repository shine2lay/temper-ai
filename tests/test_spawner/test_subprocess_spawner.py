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


def _zombie(pid: int) -> bool:
    """Is ``pid`` a finished child of this process that nobody has collected?"""
    try:
        stat = open(f"/proc/{pid}/stat").read()  # noqa: PTH123, SIM115
    except OSError:
        return False  # collected: the process is gone
    fields = stat.rsplit(")", 1)[-1].split()
    return fields[0] == "Z" and fields[1] == str(os.getpid())


def _box_that_ends_its_run_itself(tmp_path) -> str:
    """A stand-in for ``python -m temper_ai.cli.main run-workflow ...``: takes the same
    arguments and exits 0 straight away, the way a box that finished its run does."""
    script = tmp_path / "box.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    return str(script)


def test_a_box_that_ends_its_run_itself_leaves_no_zombie(tmp_path):
    """#39's finding 4: a box that ends its run itself is never looked at again (the reaper
    only polls running rows), so nothing collected it and it stayed a zombie, its Popen kept
    for good. Every finished child is now collected as it ends, and its exit code is kept so
    the spawner still answers about it."""
    spawner = SubprocessSpawner(python_executable=_box_that_ends_its_run_itself(tmp_path))
    handle = spawner.spawn("self-ending")
    pid = int(handle.handle)
    deadline = time.time() + 5.0
    while time.time() < deadline and (os.path.exists(f"/proc/{pid}") and not _zombie(pid)):
        time.sleep(0.02)  # still running
    while time.time() < deadline and (_zombie(pid) or spawner._processes):
        time.sleep(0.02)  # ended: give the spawner its moment to collect it
    assert not _zombie(pid), "the box that ended its run is still a zombie child"
    assert spawner._processes == {}, "the finished box's Popen is still held"
    assert spawner.is_alive(handle) is False
    spawner.kill(handle)  # ended: nothing to signal, and no error
    assert spawner.reap("self-ending") == 0
    assert spawner.reap("self-ending") is None


def test_a_box_spawned_again_for_the_same_run_is_tracked_afresh(tmp_path):
    """A parked run's next box has the same execution id: the old box's ending must not
    stand in for the new one."""
    spawner = SubprocessSpawner(python_executable=_box_that_ends_its_run_itself(tmp_path))
    first = spawner.spawn("again")
    deadline = time.time() + 5.0
    while time.time() < deadline and spawner.is_alive(first):
        time.sleep(0.02)
    assert spawner.is_alive(first) is False
    long_script = tmp_path / "long.sh"
    long_script.write_text("#!/bin/sh\nexec sleep 60\n")
    long_script.chmod(0o755)
    spawner._python = str(long_script)
    second = spawner.spawn("again")
    try:
        assert spawner.is_alive(second) is True
    finally:
        spawner.kill(second, force=True)
    while time.time() < deadline and spawner.is_alive(second):
        time.sleep(0.02)
    assert spawner.is_alive(second) is False
    assert not _zombie(int(second.handle))


def test_a_run_never_gets_the_github_app_s_key(monkeypatch):
    """The server holds the app's key; a run asks it for short-lived tokens."""
    from temper_ai.spawner import subprocess_spawner

    seen = {}

    class FakePopen:
        pid = 4242

        def __init__(self, cmd, env=None, **kwargs):
            seen["env"] = env

    monkeypatch.setattr(subprocess_spawner.subprocess, "Popen", FakePopen)
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "-----BEGIN leak")
    monkeypatch.setenv("GITHUB_APP_WEBHOOK_SECRET", "whsec")
    monkeypatch.setenv("GITHUB_APP_ID", "1234")
    SubprocessSpawner(extra_env={"GITHUB_APP_PRIVATE_KEY": "-----BEGIN again"}).spawn("exec-1")
    env = seen["env"]
    assert "GITHUB_APP_PRIVATE_KEY" not in env and "GITHUB_APP_WEBHOOK_SECRET" not in env
    assert env["GITHUB_APP_ID"] == "1234"
