"""`temper watch-queue` — long-running daemon that picks up queued runs.

Runs in the temper-worker container (or anywhere with DB + spawn ability).
Each tick:
  1. Query Postgres for WorkflowRun rows where status='queued' and
     spawner_handle is NULL (not already picked up by another watcher)
  2. For each, claim the row by setting spawner_kind='subprocess' and
     spawner_handle='claiming' (race-safe via UPDATE ... WHERE handle IS NULL)
  3. Call SubprocessSpawner.spawn() — launches `temper run-workflow
     --execution-id <id>` as a child process in this container
  4. Stamp the resulting handle (PID) onto the row

Reaper from Phase 3 piggybacks: runs in the same process, polls the same
rows for liveness + cancel_requested. One container = one watcher process
= owns spawn + reap + cancel for every run it claimed.

Multi-watcher safety: claim is a single UPDATE with a NULL guard, so two
watchers racing on the same row → only one wins, the other sees zero
rows updated and moves on. No lock table needed.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time

from sqlmodel import select

from temper_ai.database import get_session, init_database
from temper_ai.runner.models import WorkflowRun
from temper_ai.spawner import SpawnerError, get_spawner
from temper_ai.spawner.reaper import Reaper

logger = logging.getLogger(__name__)


# How often to scan for newly-queued rows. Cheap query (indexed on status),
# so 2s feels live without hammering the DB.
DEFAULT_POLL_INTERVAL = 2.0


def cmd_watch_queue(args: argparse.Namespace) -> int:
    """Long-lived daemon. Returns when SIGTERM/SIGINT arrives."""
    # Bootstrap DB connection — same env-driven path the worker uses.
    import os
    db_url = os.environ.get(
        "TEMPER_DATABASE_URL",
        os.environ.get("DATABASE_URL", "sqlite:///./data/temper.db"),
    )
    init_database(db_url)
    logger.info("Watcher DB connected: %s",
                db_url.split("@")[-1] if "@" in db_url else db_url)

    spawner = get_spawner()
    reaper = Reaper(spawner, interval_seconds=args.reaper_interval)
    reaper.start()
    logger.info(
        "Watcher started (poll=%.1fs, reaper=%.1fs)",
        args.poll_interval, args.reaper_interval,
    )

    stop = threading.Event()

    def _handle_signal(signum: int, _frame) -> None:
        logger.warning("Watcher received signal %d — shutting down", signum)
        stop.set()
        # Restore default so a second signal hard-kills
        signal.signal(signum, signal.SIG_DFL)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        while not stop.is_set():
            try:
                claimed = _scan_and_dispatch(spawner)
                if claimed:
                    logger.info("Dispatched %d new run(s)", claimed)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Watcher tick failed (continuing): %s", exc)
            stop.wait(args.poll_interval)
    finally:
        reaper.stop()
        logger.info("Watcher stopped")

    return 0


def _scan_and_dispatch(spawner) -> int:
    """Find queued rows, claim each, spawn a worker. Returns dispatched count.

    Claim semantics: a row is "ours" once we've UPDATEd spawner_kind from
    NULL to 'subprocess' atomically. Two watchers racing — only one's
    UPDATE matches the WHERE clause, the other gets zero rows changed.
    """
    queued = _load_queued()
    if not queued:
        return 0

    dispatched = 0
    for row_dict in queued:
        execution_id = row_dict["execution_id"]
        if not _claim_row(execution_id):
            # Another watcher beat us to it
            continue
        try:
            handle = spawner.spawn(execution_id)
        except SpawnerError as exc:
            logger.error(
                "Spawn failed for %s (%s) — marking failed", execution_id, exc,
            )
            _mark_spawn_failed(execution_id, str(exc))
            continue

        _stamp_handle(execution_id, handle)
        dispatched += 1
        logger.info(
            "Dispatched %s → spawner_handle=%s", execution_id, handle.handle,
        )
    return dispatched


def _load_queued() -> list[dict]:
    """Snapshot queued rows as plain dicts, release the session before
    spawn calls (which can take 10-100ms each)."""
    with get_session() as session:
        rows = session.exec(
            select(WorkflowRun).where(
                WorkflowRun.status == "queued",
                WorkflowRun.spawner_kind.is_(None),  # type: ignore[union-attr]
            ),
        ).all()
        return [{"execution_id": r.execution_id} for r in rows]


def _claim_row(execution_id: str) -> bool:
    """Try to atomically claim a queued row. Returns True if we got it.

    Uses a single UPDATE...WHERE statement so the claim is atomic at the
    database level — two watchers racing on the same row will both submit
    the UPDATE; only one's WHERE clause matches the still-NULL state, the
    other gets rowcount=0 and loses. No explicit locks needed.

    SELECT-then-UPDATE in two statements would be race-prone even under
    serializable isolation because the SELECT releases the row before the
    UPDATE acquires it.
    """
    from sqlalchemy import update

    with get_session() as session:
        stmt = (
            update(WorkflowRun)
            .where(
                WorkflowRun.execution_id == execution_id,  # type: ignore[arg-type]
                WorkflowRun.spawner_kind.is_(None),  # type: ignore[union-attr]
            )
            .values(spawner_kind="subprocess", spawner_handle="claiming")
        )
        result = session.exec(stmt)  # type: ignore[arg-type]
        return result.rowcount > 0


def _stamp_handle(execution_id: str, handle) -> None:
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is None:
            logger.warning("Row vanished after spawn: %s", execution_id)
            return
        row.spawner_handle = handle.handle
        row.spawner_metadata = handle.metadata
        session.add(row)


def _mark_spawn_failed(execution_id: str, message: str) -> None:
    from datetime import UTC, datetime
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is None:
            return
        row.status = "failed"
        row.completed_at = datetime.now(UTC)
        row.error = {"message": message, "kind": "spawn"}
        session.add(row)


def _now() -> float:
    """Test seam — monkey-patchable wall clock."""
    return time.time()
