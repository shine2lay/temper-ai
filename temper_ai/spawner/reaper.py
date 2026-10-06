"""Reaper — background task that detects dead workers and updates rows.

Runs next to whatever spawns the runs (the server in subprocess mode, the
worker's watch-queue in external mode). Periodically:
  1. Loads WorkflowRun rows where status='running' AND spawner_kind set,
     plus 'queued' rows already handed to a process or box that has not
     started the run yet
  2. For each, asks the spawner if the process is alive
  3. If not alive AND row is still 'running', marks it 'orphaned' so the
     UI doesn't show a perpetual spinner on a worker that vanished (and
     ends the run's event the same way); a handed-over row whose box is
     gone before it started the run is marked 'failed' (or 'cancelled')
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
from temper_ai.observability.reconcile import INTERRUPTED, settle_run_event
from temper_ai.runner.models import WorkflowRun
from temper_ai.spawner.base import Spawner, SpawnerError
from temper_ai.worker_proto import ProcessHandle, SpawnerKind

logger = logging.getLogger(__name__)


# Grace period between SIGTERM and SIGKILL escalation. Worker has this
# long to finish the current node + write a clean cancelled milestone.
DEFAULT_KILL_GRACE_SECONDS = 30

# spawner_handle while a watcher is claiming a row, before its box exists.
CLAIMING = "claiming"


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
        lane: str | None = None,
    ) -> None:
        self._spawner = spawner
        # Only this lane's rows (runner/lanes.py): the main worker's reaper must never ask its
        # own spawner about a Pi run the Pi lane started, nor the Pi lane's about anything else.
        self._lane = lane
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
            try:
                self._process_row(row)
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the rest
                logger.exception("Reaper: %s failed (continuing): %s", row["execution_id"], exc)

    # -- Internals ----------------------------------------------------------

    def _load_live_rows(self) -> list[dict]:
        """Read just the columns we need, snapshot to dicts, release the
        session before doing slow ops (signal calls, OS polls)."""
        from sqlalchemy import and_, or_
        from sqlmodel import col

        from temper_ai.runner.lanes import lane_clause

        with get_session() as session:
            rows = session.exec(
                select(WorkflowRun).where(
                    col(WorkflowRun.spawner_kind).is_not(None),
                    lane_clause(col(WorkflowRun.spawner_metadata), self._lane),
                    or_(
                        col(WorkflowRun.status) == "running",
                        # Handed to a box that has not started the run yet.
                        and_(
                            col(WorkflowRun.status) == "queued",
                            col(WorkflowRun.spawner_handle).is_not(None),
                            col(WorkflowRun.spawner_handle) != CLAIMING,
                        ),
                    ),
                ),
            ).all()
            return [
                {
                    "execution_id": r.execution_id,
                    "status": r.status,
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

        try:
            alive = self._spawner.is_alive(handle)
        except SpawnerError as exc:
            # Can't tell (the docker daemon hiccupped, say): look again next tick
            # rather than bury a run that may be fine.
            logger.warning("Reaper: can't tell whether %s is alive: %s", execution_id, exc)
            return

        if row.get("status") == "queued":
            # Its box is still starting the run: the run marks its row
            # running within seconds. A box that is gone without doing that
            # died on the way up, and never will.
            if row["cancel_requested"] and alive:
                self._honor_cancel(execution_id, handle)
            elif not alive:
                self._end_unstarted(execution_id, cancelled=bool(row["cancel_requested"]))
            return

        # Cancellation flow first — even if alive, we may need to signal
        if row["cancel_requested"] and alive:
            self._honor_cancel(execution_id, handle)
            return

        if not alive and self._parked(execution_id):
            # A Pi run's box let go at a gate: not lost, waiting on the owner.
            self._let_go_parked(execution_id, handle, cancel=bool(row["cancel_requested"]))
            return

        if not alive:
            self._mark_orphaned(execution_id, reason="worker process gone")
            self._termed_at.pop(execution_id, None)

    @staticmethod
    def _parked(execution_id: str) -> bool:
        from temper_ai.runner.parked import parked_attempt

        try:
            return parked_attempt(execution_id) is not None
        except Exception as exc:  # noqa: BLE001 - cannot tell: treat as before
            logger.warning("Reaper: can't tell whether %s is parked: %s", execution_id, exc)
            return False

    def _let_go_parked(self, execution_id: str, handle: ProcessHandle, *, cancel: bool) -> None:
        """Free a parked Pi run whose box has gone, then cancel it or carry it on.

        Waits until the box is gone, not just stopped, so the box that carries the run on
        never meets the old one's name. Then the row says ``waiting`` (no box, nothing lost),
        and the run is cancelled if someone asked, or carried on if the owner has answered
        (runner/parked.py): an answer that came while the box was letting go, or while this
        worker was down, is applied here.
        """
        from temper_ai.runner import parked

        is_gone = getattr(self._spawner, "is_gone", None)
        try:
            if callable(is_gone) and not is_gone(handle):
                return  # stopped, not yet removed: look again next tick
        except SpawnerError as exc:
            logger.warning("Reaper: can't tell whether %s's box is gone: %s", execution_id, exc)
            return
        self._termed_at.pop(execution_id, None)
        if cancel:
            parked.cancel_parked(execution_id, by="reaper")
            return
        if self._mark_status(execution_id, parked.WAITING, keep_open=True):
            logger.info("Reaper: %s waits on you with no box", execution_id)
        parked.carry_on(execution_id, start=parked.queue_resume, by="reaper")

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
            if self._mark_status(execution_id, "cancelled"):
                settle_run_event(execution_id, "cancelled", "Cancelled: stopped by force.")
            self._termed_at.pop(execution_id, None)

    def _mark_orphaned(self, execution_id: str, *, reason: str) -> None:
        """Best-effort terminal write. Idempotent — if the row is already
        terminal, the WHERE clause matches nothing."""
        if self._mark_status(
            execution_id,
            "orphaned",
            error={"message": f"reaped: {reason}", "kind": "orphaned"},
        ):
            # The dashboard and the notify loop read the run's event, not its row.
            settle_run_event(
                execution_id, INTERRUPTED,
                f"Interrupted: the run's worker stopped before it finished ({reason}).",
            )
        logger.warning("Reaped %s as orphaned: %s", execution_id, reason)

    def _end_unstarted(self, execution_id: str, *, cancelled: bool) -> None:
        """A handed-over run whose box is gone before the run started."""
        if cancelled:
            ended = self._mark_status(execution_id, "cancelled", from_status="queued")
        else:
            ended = self._mark_status(
                execution_id, "failed", from_status="queued",
                error={"message": "The run's box stopped before the run started.", "kind": "spawn"},
            )
        self._termed_at.pop(execution_id, None)
        if ended:
            logger.warning("Reaper: %s's box stopped before the run started", execution_id)

    def _mark_status(
        self,
        execution_id: str,
        status: str,
        *,
        error: dict | None = None,
        from_status: str = "running",
        keep_open: bool = False,
    ) -> bool:
        """End a row still in ``from_status``; False when the worker already ended it.

        ``keep_open``: the run is not over (a parked Pi run), so no end time is written.
        """
        with get_session() as session:
            row = session.exec(
                select(WorkflowRun).where(
                    WorkflowRun.execution_id == execution_id,
                ),
            ).first()
            if row is None or row.status != from_status:
                # Race: worker beat us to the terminal write. Fine.
                return False
            row.status = status
            if not keep_open:
                row.completed_at = datetime.now(UTC)
            if error is not None:
                row.error = error
            session.add(row)
            return True


def _sleep(seconds: float) -> None:
    """Indirection for tests that monkeypatch sleep behavior."""
    time.sleep(seconds)
