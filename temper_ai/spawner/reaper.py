"""Reaper — background task that detects dead workers and updates rows.

Runs on the server side. Periodically:
  1. Loads WorkflowRun rows where status='running' AND spawner_kind set
  2. For each, asks the spawner if the process is alive
  3. If not alive AND row is still 'running', marks it 'orphaned' so the
     UI doesn't show a perpetual spinner on a worker that vanished
  4. Honors cancel_requested by sending SIGTERM (cooperative); escalates
     to SIGKILL after a grace period if the worker still hasn't exited

The reaper is the *only* server-side code that mutates WorkflowRun rows
for running workers — the worker itself owns the terminal write. This
keeps the contract clean: worker writes its own success/failure,
reaper writes orphaned/cancellation outcomes.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from temper_ai.database import get_session
from temper_ai.runner.models import WorkflowRun
from temper_ai.spawner.base import Spawner, SpawnerError
from temper_ai.worker_proto import ProcessHandle, SpawnerKind

logger = logging.getLogger(__name__)


# Grace period between SIGTERM and SIGKILL escalation. Worker has this
# long to finish the current node + write a clean cancelled milestone.
DEFAULT_KILL_GRACE_SECONDS = 30


class Reaper:
    """Background sweeper. Start once at server lifespan, stop at shutdown.

    Not a thread per worker — a single sweeper that polls all live rows
    each tick. Trades polling overhead for simpler shutdown semantics.
    """

    def __init__(
        self,
        spawner: Spawner,
        *,
        interval_seconds: float = 5.0,
        kill_grace_seconds: float = DEFAULT_KILL_GRACE_SECONDS,
    ) -> None:
        self._spawner = spawner
        self._interval = interval_seconds
        self._kill_grace = kill_grace_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # When we sent SIGTERM but the worker hasn't exited yet
        self._termed_at: dict[str, datetime] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="spawner-reaper", daemon=True,
        )
        self._thread.start()
        logger.info("Reaper started (interval=%.1fs)", self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        logger.info("Reaper stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Reaper tick failed (continuing): %s", exc)
            self._stop.wait(self._interval)

    def tick(self) -> None:
        """One reap pass. Public so tests can drive it deterministically."""
        rows = self._load_live_rows()
        for row in rows:
            self._process_row(row)

    # -- Internals ----------------------------------------------------------

    def _load_live_rows(self) -> list[dict]:
        """Read just the columns we need, snapshot to dicts, release the
        session before doing slow ops (signal calls, OS polls)."""
        with get_session() as session:
            rows = session.exec(
                select(WorkflowRun).where(
                    WorkflowRun.status == "running",
                    WorkflowRun.spawner_kind.is_not(None),  # type: ignore[union-attr]
                ),
            ).all()
            return [
                {
                    "execution_id": r.execution_id,
                    "spawner_kind": r.spawner_kind,
                    "spawner_handle": r.spawner_handle,
                    "cancel_requested": r.cancel_requested,
                    "started_at": r.started_at,
                }
                for r in rows
            ]

    def _process_row(self, row: dict) -> None:
        execution_id = row["execution_id"]
        spawner_kind_str = row["spawner_kind"]
        handle_str = row["spawner_handle"]
        if not handle_str:
            # Spawn was attempted but never returned a handle — server
            # restart between row insert and spawner.spawn(). Mark orphaned
            # so the UI moves on.
            self._mark_orphaned(execution_id, reason="no spawner handle")
            return

        try:
            handle = ProcessHandle(
                kind=SpawnerKind(spawner_kind_str),
                handle=handle_str,
                metadata={"execution_id": execution_id},
            )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Reaper: bad handle for %s (%s) — orphaning",
                execution_id, exc,
            )
            self._mark_orphaned(execution_id, reason=f"bad handle: {exc}")
            return

        alive = self._spawner.is_alive(handle)

        # Cancellation flow first — even if alive, we may need to signal
        if row["cancel_requested"] and alive:
            self._honor_cancel(execution_id, handle)
            return

        if not alive:
            self._mark_orphaned(execution_id, reason="worker process gone")
            self._termed_at.pop(execution_id, None)

    def _honor_cancel(
        self, execution_id: str, handle: ProcessHandle,
    ) -> None:
        """Send SIGTERM the first time we see cancel_requested, then escalate
        to SIGKILL after the grace period. Worker is responsible for the
        clean-exit DB write; the reaper only signals."""
        sent_at = self._termed_at.get(execution_id)
        now = datetime.now(UTC)
        if sent_at is None:
            try:
                self._spawner.kill(handle, force=False)
                self._termed_at[execution_id] = now
                logger.info(
                    "Cancel: SIGTERM sent to worker for %s", execution_id,
                )
            except SpawnerError as exc:
                logger.warning(
                    "Cancel: SIGTERM failed for %s (%s) — orphaning",
                    execution_id, exc,
                )
                self._mark_orphaned(execution_id, reason=f"signal failed: {exc}")
            return

        if now - sent_at > timedelta(seconds=self._kill_grace):
            try:
                self._spawner.kill(handle, force=True)
                logger.warning(
                    "Cancel: SIGKILL after %s grace expired for %s",
                    self._kill_grace, execution_id,
                )
            except SpawnerError as exc:
                logger.warning(
                    "Cancel: SIGKILL failed for %s (%s)", execution_id, exc,
                )
            # Whether the kill succeeded or not, mark cancelled so the
            # UI doesn't keep waiting on a process we've given up on.
            self._mark_status(execution_id, "cancelled")
            self._termed_at.pop(execution_id, None)

    def _mark_orphaned(self, execution_id: str, *, reason: str) -> None:
        """Best-effort terminal write. Idempotent — if the row is already
        terminal, the WHERE clause matches nothing."""
        self._mark_status(
            execution_id,
            "orphaned",
            error={"message": f"reaped: {reason}", "kind": "orphaned"},
        )
        logger.warning("Reaped %s as orphaned: %s", execution_id, reason)

    def _mark_status(
        self,
        execution_id: str,
        status: str,
        *,
        error: dict | None = None,
    ) -> None:
        with get_session() as session:
            row = session.exec(
                select(WorkflowRun).where(
                    WorkflowRun.execution_id == execution_id,
                ),
            ).first()
            if row is None or row.status != "running":
                # Race: worker beat us to the terminal write. Fine.
                return
            row.status = status
            row.completed_at = datetime.now(UTC)
            if error is not None:
                row.error = error
            session.add(row)


def _sleep(seconds: float) -> None:
    """Indirection for tests that monkeypatch sleep behavior."""
    time.sleep(seconds)
