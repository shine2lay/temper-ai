"""SubprocessSpawner — launches `temper run-workflow` as a local subprocess.

The default backend for dev. Inherits the server's environment (DB URL,
LLM provider keys, config dir) so the worker bootstraps to the same state
the server is in.

Each spawn produces a process group (start_new_session=True) so SIGTERM
to the leader propagates to any tools the worker spawns. Without this,
shell-shaped tools (claude, bash) become orphans on cancel.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess  # noqa: S404 — intentional: this is the spawner
import sys
import threading

from temper_ai.integrations.github import secret as _github_secret
from temper_ai.spawner.base import Spawner, SpawnerError
from temper_ai.worker_proto import ProcessHandle, SpawnerKind

logger = logging.getLogger(__name__)

# How many finished boxes' exit codes are kept (oldest dropped first): enough for the reaper
# and reap() to ask about a box after it ended, without growing for every run ever started.
_KEEP_EXIT_CODES = 1000


class SubprocessSpawner(Spawner):
    """Launches the worker via `python -m temper_ai.cli.main run-workflow`.

    Why `python -m` and not the `temper` entry point: the entry point
    requires the package to be pip-installed. Using `python -m` works in
    both `pip install -e .` and bare-checkout layouts; matches how the
    server itself is started (`python -m uvicorn temper_ai.server:app`).

    Stdout/stderr are inherited so worker logs flow into whatever the
    server's logging is wired to (docker logs, journalctl, etc.). Phase 4
    will switch chunk streaming to Redis; logs stay on stdout for ops.
    """

    kind = SpawnerKind.subprocess

    def __init__(
        self,
        *,
        python_executable: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        # Default to the same interpreter the server is running. Critical:
        # if the server's venv has temper_ai installed, the subprocess must
        # too — sharing the interpreter guarantees that.
        self._python = python_executable or sys.executable
        self._extra_env = extra_env or {}
        # Track live processes so the reaper can poll without rediscovery
        # via the WorkflowRun.spawner_handle (PID) string. Each child is
        # collected the moment it ends (``_collect``): its entry moves to
        # ``_exit_codes``, so no finished box stays a zombie.
        self._processes: dict[str, subprocess.Popen] = {}
        self._exit_codes: dict[str, int] = {}
        self._lock = threading.Lock()

    def spawn(self, execution_id: str) -> ProcessHandle:
        """Fork a worker. Caller is responsible for inserting the queued
        WorkflowRun row before calling — we don't validate it here because
        the worker itself errors-out cleanly if the row is missing.

        Refused under TEMPER_BOX_RUNTIME_BOUNDARY=sealed: a child process shares the
        worker's files and keys, so it is no box (BoxProfileError, a SpawnerError).
        """
        from temper_ai.spawner.box_profile import refuse_unboxed_under_sealed

        refuse_unboxed_under_sealed("the subprocess spawner (TEMPER_SPAWNER=subprocess)")
        cmd = [
            self._python,
            "-m", "temper_ai.cli.main",
            "run-workflow",
            "--execution-id", execution_id,
        ]

        # Inherit server env + apply overrides. Children get the same
        # DB URL, LLM keys, config dir -- never the GitHub app's key: a run
        # asks the server for short-lived tokens (integrations.github.secret).
        env = _github_secret.without_server_only({**os.environ, **self._extra_env})
        from temper_ai.runner.resume_authority import (
            RESERVATION_ENV,
            launch_resume_token,
        )
        env.pop(RESERVATION_ENV, None)
        token = launch_resume_token(execution_id)
        if token is not None:
            env[RESERVATION_ENV] = token

        try:
            proc = subprocess.Popen(  # noqa: S603 — args are list, no shell
                cmd,
                env=env,
                stdout=None,  # inherit (server's stdout)
                stderr=None,  # inherit
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # new process group → SIGTERM propagates
            )
        except (OSError, ValueError) as exc:
            raise SpawnerError(
                f"Failed to spawn worker for {execution_id}: {exc}",
            ) from exc

        with self._lock:
            self._processes[execution_id] = proc
            self._exit_codes.pop(execution_id, None)  # a new box for the same run
        threading.Thread(
            target=self._collect, args=(execution_id, proc),
            name=f"spawner-collect-{execution_id}", daemon=True,
        ).start()

        logger.info(
            "Spawned worker pid=%d for execution_id=%s", proc.pid, execution_id,
        )
        return ProcessHandle(
            kind=SpawnerKind.subprocess,
            handle=str(proc.pid),
            metadata={"execution_id": execution_id},
        )

    def _collect(self, execution_id: str, proc: subprocess.Popen) -> None:
        """Wait for one child to end and collect it at once, so it never stays a zombie.

        A box that ends its run itself is never looked at again (the reaper polls only rows
        still running), so nothing else would collect it. Its exit code is kept, so
        ``is_alive``/``reap``/``kill`` still answer about it without asking the OS about a
        pid that may since belong to someone else.
        """
        try:
            code = proc.wait()
        except Exception:  # noqa: BLE001 - the child is unknown to us now; nothing to keep
            logger.warning("Could not collect worker pid=%d (%s)", proc.pid, execution_id,
                           exc_info=True)
            return
        with self._lock:
            if self._processes.get(execution_id) is not proc:
                return  # already reaped, or a newer box for the same run took its place
            del self._processes[execution_id]
            self._exit_codes[execution_id] = code
            while len(self._exit_codes) > _KEEP_EXIT_CODES:
                del self._exit_codes[next(iter(self._exit_codes))]

    def is_alive(self, handle: ProcessHandle) -> bool:
        """Poll the subprocess. Returns False once it exits OR if we have
        no record of it (server restarted between spawn and poll)."""
        execution_id = handle.metadata.get("execution_id", "")
        with self._lock:
            proc = self._processes.get(execution_id)
            ended = execution_id in self._exit_codes
        if proc is None and ended:
            return False
        if proc is None:
            # Best-effort: try the OS directly. signal 0 is a permissions
            # check that doesn't actually deliver — succeeds iff the PID
            # exists and we own it.
            try:
                pid = int(handle.handle)
                os.kill(pid, 0)
                return True
            except (ProcessLookupError, ValueError, PermissionError):
                return False
        return proc.poll() is None

    def kill(self, handle: ProcessHandle, *, force: bool = False) -> None:
        """Send SIGTERM (or SIGKILL if force) to the worker's process group.

        Targeting the process group catches any tools the worker forked
        (bash subshells, claude CLI). Without this, the worker exits but
        its descendants linger holding stdout — see CLAUDE memory note
        on orphan-daemon-stall for why this matters.
        """
        execution_id = handle.metadata.get("execution_id", "")
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            pid = int(handle.handle)
        except ValueError as exc:
            raise SpawnerError(f"Bad handle: {handle.handle!r}") from exc
        with self._lock:
            ended = execution_id in self._exit_codes and execution_id not in self._processes
        if ended:
            # Collected already: its pid may belong to another process by now.
            logger.debug("Worker pid=%d already gone for execution_id=%s", pid, execution_id)
            return

        try:
            # negative pid = kill the process group, not just the leader
            os.killpg(os.getpgid(pid), sig)
            logger.info(
                "Sent %s to worker pid=%d (execution_id=%s)",
                sig.name, pid, execution_id,
            )
        except ProcessLookupError:
            # Already dead. Idempotent — this is fine.
            logger.debug(
                "Worker pid=%d already gone for execution_id=%s",
                pid, execution_id,
            )
        except OSError as exc:
            raise SpawnerError(
                f"Failed to {sig.name} worker pid={pid}: {exc}",
            ) from exc

    def live_runs(self) -> list[str]:
        """The runs whose child process this spawner started and that hasn't ended yet (the
        Pi lane waits for them when it stops: runner/pi_lane.py)."""
        with self._lock:
            return [eid for eid, proc in self._processes.items() if proc.poll() is None]

    def reap(self, execution_id: str) -> int | None:
        """Pop the Popen handle for a completed worker and return its exit code.

        Every child is collected as it ends (``_collect``), so this only hands back the
        exit code and forgets the box. Returns None if we never tracked the process
        (server restart) or it was reaped already — caller falls back to "orphaned".
        """
        with self._lock:
            proc = self._processes.pop(execution_id, None)
            code = self._exit_codes.pop(execution_id, None)
        if proc is None:
            return code
        try:
            return proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            # The subprocess says it's done but wait() blocks → race;
            # leave it for the next reap pass instead of hanging here.
            with self._lock:
                self._processes[execution_id] = proc
            return None
