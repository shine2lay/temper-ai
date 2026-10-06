"""`temper watch-queue` — long-running daemon that picks up queued runs.

Runs in the temper-worker container (or anywhere with DB + spawn ability).
Each tick:
  1. Query Postgres for WorkflowRun rows where status='queued' and
     spawner_handle is NULL (not already picked up by another watcher)
  2. For each, claim the row by setting spawner_kind to the spawner's kind
     and spawner_handle='claiming' (race-safe via UPDATE ... WHERE handle IS NULL)
  3. Call spawner.spawn() — `temper run-workflow --execution-id <id>` as a
     child process in this container (subprocess, the default) or in a
     sibling container of its own (docker, TEMPER_SPAWNER=docker)
  4. Stamp the resulting handle (PID / container name) onto the row

Reaper from Phase 3 piggybacks: runs in the same process, polls the same
rows for liveness + cancel_requested. One container = one watcher process
= owns spawn + reap + cancel for every run it claimed.

Multi-watcher safety: claim is a single UPDATE with a NULL guard, so two
watchers racing on the same row → only one wins, the other sees zero
rows updated and moves on. No lock table needed.

A run stopped while it waits (cancel_requested) is marked cancelled and
never gets a box. At start, a watcher puts back in the queue the rows of
its kind that a restart caught between claiming and spawning (handle still
'claiming'), unless their box came up after all.

Lanes (runner/lanes.py, docs/pi-lane.md): a watcher claims, reaps and puts
back only its own lane's rows. The main watcher (no TEMPER_LANE) never
touches a Pi run; the Pi lane's watcher (TEMPER_LANE=pi, the pi-worker
service) touches nothing else, claims one Pi run at a time (counting a
parked one) in the order they came, and does its own start-up and drain
(runner/pi_lane.py).
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from typing import Any

from sqlmodel import col, select

from temper_ai.database import get_session, init_database
from temper_ai.runner.lanes import (
    PI_LANE,
    WAITING_FOR_PI_LANE,
    LaneSettingError,
    lane_clause,
    lane_of,
    mark_lane,
    this_lane,
)
from temper_ai.runner.models import WorkflowRun
from temper_ai.spawner import SpawnerBusy, SpawnerError, get_spawner
from temper_ai.spawner.reaper import CLAIMING, Reaper
from temper_ai.worker_proto import ProcessHandle, SpawnerKind

logger = logging.getLogger(__name__)


# How often to scan for newly-queued rows. Cheap query (indexed on status),
# so 2s feels live without hammering the DB.
DEFAULT_POLL_INTERVAL = 2.0

# The queued Pi runs already logged as waiting for the Pi lane (said once each).
_TOLD_WAITING: set[str] = set()
# Our launched resume handles whose DB acknowledgement was lost. No new spawn on retry.
_PENDING_RESUME_STAMPS: dict[str, tuple[ProcessHandle, str]] = {}


def cmd_watch_queue(args: argparse.Namespace) -> int:
    """Long-lived daemon. Returns when SIGTERM/SIGINT arrives."""
    # Bootstrap DB connection — same env-driven path the worker uses.
    import os
    db_url = os.environ.get(
        "TEMPER_DATABASE_URL",
        os.environ.get("DATABASE_URL", "sqlite:///./data/temper.db"),
    )
    try:
        lane = this_lane()
    except LaneSettingError as exc:
        logger.error("Watcher won't start: %s", exc)
        return 2
    try:
        spawner = get_spawner()
    except SpawnerError as exc:  # H1: the subprocess spawner beside a Docker socket
        logger.error("Watcher won't start: %s", exc)
        return 2
    if lane == PI_LANE:
        from temper_ai.runner import pi_lane

        problem = pi_lane.worker_problem(spawner)
        if problem:
            logger.error("The Pi lane won't start: %s", problem)
            return 2
        pi_lane.eager_import()
        pi_lane.arm_drain_mark()
    reaper = Reaper(spawner, interval_seconds=args.reaper_interval, lane=lane)
    ready = False
    logger.info(
        "Watcher started (lane=%s, poll=%.1fs, reaper=%.1fs)",
        lane or "main", args.poll_interval, args.reaper_interval,
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
            if not ready:
                ready = _try_watcher_startup(db_url, spawner, lane)
                if not ready:
                    stop.wait(args.poll_interval)
                    continue
                reaper.start()
            try:
                _flush_resume_stamps()
                claimed = _scan_and_dispatch(spawner, lane)
                if claimed:
                    logger.info("Dispatched %d new run(s)", claimed)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Watcher tick failed (continuing): %s", exc)
            stop.wait(args.poll_interval)
    finally:
        if lane == PI_LANE and ready:
            # Claims nothing more; its runs leave at their next turn boundary. The reaper
            # keeps going meanwhile, so a run that parks is let go as usual.
            pi_lane.drain(spawner)
        reaper.stop()
        logger.info("Watcher stopped")

    return 0


def _try_watcher_startup(db_url: str, spawner, lane: str | None) -> bool:
    """Retry only DB/startup bookkeeping, never a refused workflow or its producer."""
    from sqlalchemy.exc import SQLAlchemyError

    from temper_ai.runner.resume_authority import ResumeAttemptRefused

    try:
        init_database(db_url)
        if lane == PI_LANE:
            from temper_ai.runner import pi_lane
            state = pi_lane.start_up()
            if state.get("authority_unavailable"):
                return False
            logger.info("Pi lane start-up: %s", state)
        requeued = _requeue_stuck_claims(spawner, lane)
        if requeued:
            logger.warning("Put %d ordinary claims back in the queue", requeued)
        return True
    except (OSError, SQLAlchemyError, ResumeAttemptRefused) as exc:
        # Stay alive during a read outage, not an unrelated startup programming error.
        # No permission, false outcome or SQL/credential dump.
        logger.warning("Watcher authority unavailable (%s); no new work", type(exc).__name__)
        return False


def _flush_resume_stamps() -> None:
    """Persist only handles we already launched, fenced to their original reservation."""
    for execution_id, (handle, token) in list(_PENDING_RESUME_STAMPS.items()):
        try:
            _stamp_handle(execution_id, handle, resume_token=token)
        except Exception:  # noqa: BLE001
            continue
        _PENDING_RESUME_STAMPS.pop(execution_id, None)


def _scan_and_dispatch(spawner, lane: str | None = None) -> int:
    """Find queued rows, claim each, spawn a worker. Returns dispatched count.

    Claim semantics: a row is "ours" once we've UPDATEd spawner_kind from
    NULL to the spawner's kind atomically. Two watchers racing — only one's
    UPDATE matches the WHERE clause, the other gets zero rows changed.
    Only ``lane``'s rows (runner/lanes.py).
    """
    from temper_ai.runner.resume_authority import (
        ResumeAttemptRefused,
        automatic_resume_refused,
        bind_resume_launch,
        refuse_resume,
    )

    queued = _load_queued(lane)
    if not queued:
        return 0

    dispatched = 0
    for row_dict in queued:
        execution_id = row_dict["execution_id"]
        if row_dict.get("cancel_requested"):
            # Stopped before it started: no box for it.
            if _mark_cancelled_unclaimed(execution_id):
                logger.info("Cancelled %s before it started", execution_id)
            continue
        resume_token = row_dict.get("resume_token")
        if row_dict.get("start") == "resume" or resume_token is not None:
            try:
                if automatic_resume_refused(execution_id):
                    continue
                if resume_token is None:
                    raise ResumeAttemptRefused("resume_reservation_missing", execution_id=execution_id)
            except ResumeAttemptRefused as refused:
                if refused.token is None:
                    refused.token = resume_token
                refuse_resume(execution_id, refused)
                continue
        claimed = (_claim_row(execution_id, spawner.kind.value, lane, resume_token=resume_token)
                   if resume_token is not None else _claim_row(execution_id, spawner.kind.value, lane))
        if not claimed:
            # Another watcher beat us to it; in the Pi lane, another Pi run holds the lane.
            if lane == PI_LANE and execution_id not in _TOLD_WAITING:
                _TOLD_WAITING.add(execution_id)
                logger.info("%s is %s: another Pi run holds it", execution_id,
                            WAITING_FOR_PI_LANE)
            continue
        _TOLD_WAITING.discard(execution_id)
        try:
            with bind_resume_launch(execution_id, resume_token):
                handle = spawner.spawn(execution_id)
        except ResumeAttemptRefused as refused:
            if refused.token is None:
                refused.token = resume_token
            refuse_resume(execution_id, refused)
            logger.warning("Run %s: spawn attempt refused (%s)", execution_id, refused.code)
            continue
        except SpawnerBusy as exc:
            # Not now, but soon: back in the queue for the next scan.
            logger.warning("Can't start %s yet (%s); trying again shortly", execution_id, exc)
            if resume_token is not None:
                _unclaim(execution_id, resume_token=resume_token)
            else:
                _unclaim(execution_id)
            continue
        except SpawnerError as exc:
            if resume_token is not None:
                refuse_resume(execution_id, ResumeAttemptRefused(
                    "resume_spawn_unavailable", execution_id=execution_id, token=resume_token))
                logger.warning("Run %s: its unadmitted spawn was refused", execution_id)
                continue
            logger.error(
                "Spawn failed for %s (%s) — marking failed", execution_id, exc,
            )
            _mark_spawn_failed(execution_id, str(exc))
            continue
        except Exception:
            if resume_token is not None:
                refuse_resume(execution_id, ResumeAttemptRefused(
                    "resume_spawn_unconfirmed", execution_id=execution_id, token=resume_token))
                logger.warning("Run %s: spawn awaits token-fenced recovery", execution_id)
                continue
            raise

        if resume_token is not None:
            _PENDING_RESUME_STAMPS[execution_id] = (handle, resume_token)
            _flush_resume_stamps()
        else:
            _stamp_handle(execution_id, handle)
        dispatched += 1
        logger.info(
            "Dispatched %s → spawner_handle=%s", execution_id, handle.handle,
        )
    return dispatched


def _load_queued(lane: str | None = None) -> list[dict]:
    """Snapshot queued rows as plain dicts, release the session before
    spawn calls (which can take 10-100ms each). Only ``lane``'s rows; the Pi
    lane's in the order they came, since it runs one at a time."""
    from temper_ai.runner.resume_authority import RESERVATION_KEY

    with get_session() as session:
        query = select(WorkflowRun).where(
            WorkflowRun.status == "queued",
            WorkflowRun.spawner_kind.is_(None),  # type: ignore[union-attr]
            lane_clause(col(WorkflowRun.spawner_metadata), lane),
        )
        if lane == PI_LANE:
            query = query.order_by(col(WorkflowRun.created_at))
        rows = session.exec(query).all()
        queued = []
        for row in rows:
            item: dict[str, Any] = {"execution_id": row.execution_id,
                                    "cancel_requested": bool(row.cancel_requested)}
            metadata = row.spawner_metadata or {}
            if metadata.get("start") == "resume":
                item["start"] = "resume"
                capsule = metadata.get(RESERVATION_KEY)
                if isinstance(capsule, dict):
                    item["resume_token"] = capsule.get("token")
            queued.append(item)
        return queued


def _mark_cancelled_unclaimed(execution_id: str) -> bool:
    """End a queued run nobody has claimed yet; False if someone just did."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    with get_session() as session:
        stmt = (
            update(WorkflowRun)
            .where(
                WorkflowRun.execution_id == execution_id,  # type: ignore[arg-type]
                WorkflowRun.status == "queued",  # type: ignore[arg-type]
                WorkflowRun.spawner_kind.is_(None),  # type: ignore[union-attr]
            )
            .values(status="cancelled", completed_at=datetime.now(UTC))
        )
        return session.exec(stmt).rowcount > 0  # type: ignore[arg-type]


def _unclaim(execution_id: str, *, resume_token: str | None = None) -> bool:
    """Hand a claimed row that got no box back to the queue, not a later reservation."""
    from sqlalchemy import update

    from temper_ai.runner.resume_authority import RESERVATION_KEY
    own = ([col(WorkflowRun.spawner_metadata)[RESERVATION_KEY]["token"].as_string() == resume_token]
           if resume_token is not None else [])
    with get_session() as session:
        stmt = (
            update(WorkflowRun)
            .where(
                WorkflowRun.execution_id == execution_id,  # type: ignore[arg-type]
                WorkflowRun.status == "queued",  # type: ignore[arg-type]
                WorkflowRun.spawner_handle == CLAIMING,  # type: ignore[arg-type]
                *own,
            )
            .values(spawner_kind=None, spawner_handle=None)
        )
        return session.exec(stmt).rowcount > 0  # type: ignore[arg-type]


def _requeue_stuck_claims(spawner, lane: str | None = None) -> int:
    """Put back rows of this spawner's kind that were claimed but never
    given a box: the watcher stopped between the two. A box that did come
    up (docker only: it is named after the run) is left to mark itself
    running. Assumes one watcher per spawner kind and lane, as deployed here.
    """
    with get_session() as session:
        rows = session.exec(
            select(WorkflowRun).where(
                WorkflowRun.status == "queued",
                WorkflowRun.spawner_kind == spawner.kind.value,
                WorkflowRun.spawner_handle == CLAIMING,
                lane_clause(col(WorkflowRun.spawner_metadata), lane),
            ),
        ).all()
        stuck = [(r.execution_id, r.spawner_metadata, bool(r.cancel_requested)) for r in rows]

    from temper_ai.runner.resume_authority import (
        ResumeAttemptRefused,
        recover_resume_reservation,
        refuse_resume,
        reservation,
        reservation_never_admitted,
    )
    requeued = 0
    for execution_id, metadata, cancelled in stuck:
        capsule = reservation(metadata)
        if capsule is None and not cancelled and (metadata or {}).get("start") == "resume":
            refuse_resume(execution_id, ResumeAttemptRefused(
                "resume_reservation_missing", execution_id=execution_id), expected_handle=CLAIMING)
            continue
        if capsule is not None and not cancelled:
            try:
                unstarted = reservation_never_admitted(metadata, execution_id=execution_id)
            except ResumeAttemptRefused as refused:
                refuse_resume(execution_id, refused, expected_handle=CLAIMING)
                continue
            if unstarted:
                if capsule.get("phase") in ("recovered", "invalid"):
                    continue
                gone = False
                if spawner.kind == SpawnerKind.docker:
                    handle = ProcessHandle(kind=spawner.kind, handle=CLAIMING,
                                           metadata={"execution_id": execution_id})
                    try:
                        if spawner.is_alive(handle):
                            continue
                        is_gone = getattr(spawner, "is_gone", None)
                        if callable(is_gone) and not is_gone(handle):
                            continue
                        gone = True
                    except SpawnerError:
                        continue
                token = capsule.get("token")
                if isinstance(token, str) and token:
                    # With an unknown subprocess handle, only an ungranted
                    # reservation may roll back. An issued permission needs proof.
                    recover_resume_reservation(execution_id, expected_token=token,
                                               expected_handle=CLAIMING, box_proved_gone=gone)
                continue  # Never requeue a refused/unadmitted attempt automatically.
        if spawner.kind == SpawnerKind.docker:
            handle = ProcessHandle(
                kind=spawner.kind, handle=CLAIMING, metadata={"execution_id": execution_id},
            )
            try:
                if spawner.is_alive(handle):
                    continue
            except SpawnerError as exc:
                logger.warning("Can't tell whether %s's box is up (%s); leaving it", execution_id, exc)
                continue
        if _unclaim(execution_id):
            requeued += 1
    return requeued


def _claim_row(execution_id: str, spawner_kind: str = "subprocess",
               lane: str | None = None, *, resume_token: str | None = None) -> bool:
    """Try to atomically claim a queued row. Returns True if we got it.

    Uses a single UPDATE...WHERE statement so the claim is atomic at the
    database level — two watchers racing on the same row will both submit
    the UPDATE; only one's WHERE clause matches the still-NULL state, the
    other gets rowcount=0 and loses. No explicit locks needed.

    SELECT-then-UPDATE in two statements would be race-prone even under
    serializable isolation because the SELECT releases the row before the
    UPDATE acquires it.

    Only a row of ``lane``. The Pi lane claims one only while no other Pi run
    holds the lane (ADR-M4-11): running, parked (``waiting``) or claimed. That
    test sits in the same UPDATE; it is exact with the one Pi lane watcher
    there is.
    """
    from sqlalchemy import and_, exists, or_, update

    conditions = [
        WorkflowRun.execution_id == execution_id,  # type: ignore[arg-type]
        WorkflowRun.spawner_kind.is_(None),  # type: ignore[union-attr]
        lane_clause(col(WorkflowRun.spawner_metadata), lane),
    ]
    if resume_token is not None:
        from temper_ai.runner.resume_authority import RESERVATION_KEY
        conditions += [WorkflowRun.status == "queued",  # type: ignore[arg-type]
                       col(WorkflowRun.spawner_metadata)[RESERVATION_KEY]["token"].as_string() == resume_token]
    if lane == PI_LANE:
        # Still queued: the server ends an unclaimed Pi run itself on a cancel (api/routes.py
        # _cancel_unclaimed_pi_run), maybe between this watcher's scan and this claim.
        conditions.append(WorkflowRun.status == "queued")  # type: ignore[arg-type]
        other = WorkflowRun.__table__.alias("other_pi_run")  # type: ignore[attr-defined]
        conditions.append(~exists().where(
            other.c.execution_id != execution_id,
            lane_clause(other.c.spawner_metadata, PI_LANE),
            or_(other.c.status.in_(("running", "waiting")),
                and_(other.c.status == "queued", other.c.spawner_kind.is_not(None))),
        ))
    with get_session() as session:
        stmt = (
            update(WorkflowRun)
            .where(*conditions)
            .values(spawner_kind=spawner_kind, spawner_handle=CLAIMING)
        )
        result = session.exec(stmt)  # type: ignore[arg-type]
        return result.rowcount > 0


def _stamp_handle(execution_id: str, handle, *, resume_token: str | None = None) -> None:
    if resume_token is not None:
        # The box may already have refused/restored, or a later owner may have
        # queued another attempt. Merge atomically; never replace append-only audit.
        import json

        from sqlalchemy import JSON, cast, func, literal, update
        from sqlalchemy.dialects.postgresql import JSONB

        from temper_ai.runner.lanes import LANE_RECORD_KEY
        from temper_ai.runner.resume_authority import RESERVATION_KEY, RESERVED_KEYS
        extra = {k: v for k, v in handle.metadata.items()
                 if k not in (*RESERVED_KEYS, "box_profile", LANE_RECORD_KEY)}
        meta = col(WorkflowRun.spawner_metadata)
        with get_session() as session:
            merged: Any
            if session.get_bind().dialect.name == "postgresql":
                merged = cast(meta, JSONB).op("||")(cast(literal(extra, type_=JSON), JSONB))
            else:
                merged = func.json_patch(meta, json.dumps(extra))
            session.exec(update(WorkflowRun).where(  # type: ignore[call-overload]
                col(WorkflowRun.execution_id) == execution_id,
                col(WorkflowRun.status).in_(("queued", "running")),
                meta["start"].as_string() == "resume",
                meta[RESERVATION_KEY]["token"].as_string() == resume_token,
            ).values(spawner_handle=handle.handle, spawner_metadata=merged)
              .execution_options(synchronize_session=False))
        return
    with get_session() as session:
        row = session.exec(
            select(WorkflowRun).where(WorkflowRun.execution_id == execution_id),
        ).first()
        if row is None:
            logger.warning("Row vanished after spawn: %s", execution_id)
            return
        row.spawner_handle = handle.handle
        # Merge: the row may already say how the box starts ("start": resume
        # or fork), and the box reads that a moment from now. Its lane stays.
        old = row.spawner_metadata or {}
        row.spawner_metadata = mark_lane({**old, **handle.metadata}, lane_of(old))
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
