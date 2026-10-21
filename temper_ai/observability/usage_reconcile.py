"""Bounded numeric capture recovery; its internal cutover is NOT coverage.

Every row transaction ends immediately after the landed capture/drain helper.
No Event.data object, provider call, pricing, retention or reader is involved.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    and_,
    case,
    cast,
    exists,
    func,
    or_,
)
from sqlalchemy import select as sql_select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select
from sqlmodel import Column, Field, Session, SQLModel, col, select

from temper_ai.database import get_database
from temper_ai.observability import usage_rows as usage
from temper_ai.observability.models import Event
from temper_ai.runner.models import WorkflowRun
from temper_ai.shared.clock import as_utc

logger = logging.getLogger(__name__)
PACIFIC = ZoneInfo("America/Los_Angeles")
WRITER_KINDS = frozenset({"server", "worker", "pi-worker"})
TERMINAL = ("completed", "failed", "cancelled", "interrupted")
FAULT_CODES = frozenset({"post-cutover-missing-row", "drain-fault"})
EVERY_SECONDS = 60.0
MAX_BATCH = 200
DRAIN_BUDGET_SECONDS = 20.0
RECONCILE_BUDGET_SECONDS = 20.0
UNENDED_BUDGET_SECONDS = 5.0
WAKE_BUDGET_SECONDS = 50.0
BATCH_PAUSE_SECONDS = 0.025
FAULT_CAP = 10_000
LEAVES = ("model", "provider", *usage.TOKEN_FIELDS.values(), "cost_usd", "llm_call_id",
          "call_kind", "started_event_id", "executed_by", "restored_from_fork")
_thread: threading.Thread | None = None
_stop = threading.Event()


def _require_time(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("usage timestamp missing")
    return value


def _clock_column(*, nullable: bool = False):
    return Column(DateTime(timezone=True), nullable=nullable)


class UsageWriterReady(SQLModel, table=True):
    __tablename__ = "usage_writer_ready"
    __table_args__ = (
        CheckConstraint("kind IN ('server','worker','pi-worker')", name="usage_ready_kind"),
        CheckConstraint("writer_version = 1", name="usage_ready_version"),
    )
    kind: str = Field(primary_key=True, max_length=16)
    writer_version: int = Field(default=1)
    ready_at: datetime = Field(sa_column=_clock_column())


class UsageCoverage(SQLModel, table=True):
    """Internal progress only. There deliberately is no completeness status column."""
    __tablename__ = "usage_coverage"
    __table_args__ = (
        CheckConstraint("id = 1", name="usage_coverage_singleton"),
        CheckConstraint("phase IN ('backfill','cutover')", name="usage_coverage_phase"),
        CheckConstraint("fault_overflow >= 0", name="usage_fault_overflow_nonnegative"),
    )
    id: int = Field(default=1, primary_key=True)
    cutover_at: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    cutover_seq: int | None = Field(default=None, sa_type=BigInteger)
    backfilled_from: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    phase: str = Field(default="backfill", max_length=16)
    reconciled_count: int = Field(default=0, sa_type=BigInteger)
    fault_overflow: int = Field(default=0, sa_type=BigInteger)
    lap_generation: int = Field(default=0)
    lap_ready_at: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    lap_started_at: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    lap_upper_at: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    lap_from: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    lap_cursor_week: int | None = None
    lap_cursor_at: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    lap_cursor_event_id: str | None = Field(default=None, max_length=128)
    lap_clean: bool = True
    lap_complete: bool = False
    start_cursor_at: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    start_cursor_event_id: str | None = Field(default=None, max_length=128)


class UsageFault(SQLModel, table=True):
    __tablename__ = "usage_faults"
    __table_args__ = (
        UniqueConstraint("event_id", "code", name="usage_fault_event_code"),
        CheckConstraint("code IN ('post-cutover-missing-row','drain-fault')", name="usage_fault_code"),
    )
    id: int | None = Field(default=None, primary_key=True)
    event_id: str = Field(max_length=128)
    code: str = Field(max_length=32)
    detected_at: datetime = Field(sa_column=_clock_column())


class UsageDrainHeartbeat(SQLModel, table=True):
    __tablename__ = "usage_drain_heartbeat"
    __table_args__ = (
        CheckConstraint("id = 1", name="usage_drain_singleton"),
        CheckConstraint("outcome IN ('empty','drained','already-final','busy','deferred','fault','mixed','budget')",
                        name="usage_drain_outcome"),
        CheckConstraint("drained >= 0 AND remaining >= 0 AND attempted >= 0 AND busy >= 0 "
                        "AND deferred >= 0 AND already_final >= 0 AND missing >= 0 AND faulted >= 0",
                        name="usage_drain_counts"),
    )
    id: int = Field(default=1, primary_key=True)
    last_drain_at: datetime = Field(sa_column=_clock_column())
    outcome: str = Field(max_length=16)
    attempted: int = 0
    drained: int = 0
    remaining: int = 0
    already_final: int = 0
    busy: int = 0
    deferred: int = 0
    missing: int = 0
    faulted: int = 0
    cursor_pending_at: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    cursor_event_at: datetime | None = Field(default=None, sa_column=_clock_column(nullable=True))
    cursor_revision: int | None = None
    cursor_event_id: str | None = Field(default=None, max_length=128)


def enabled() -> bool:
    return os.environ.get("TEMPER_USAGE_RECONCILER", "1").strip().lower() not in ("0", "false", "off", "no")


def _insert(session: Session, model):
    return (pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert)(model)


def _db_now(session: Session) -> datetime:
    # PostgreSQL CURRENT_TIMESTAMP is transaction-start time, NOT completion time.
    if session.get_bind().dialect.name == "postgresql":
        return _require_time(as_utc(session.execute(sql_select(func.clock_timestamp())).scalar_one()))
    value = session.execute(sql_select(func.strftime("%Y-%m-%dT%H:%M:%f+00:00", "now"))).scalar_one()
    return datetime.fromisoformat(value)


def _bounded_statement(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(sql_select(func.set_config("statement_timeout", "5s", True)))
        session.execute(sql_select(func.set_config("lock_timeout", "2s", True)))


def pacific_week_start(dt: datetime) -> datetime:
    local = _require_time(as_utc(dt)).astimezone(PACIFIC)
    monday = local.date() - timedelta(days=local.weekday())
    return _require_time(as_utc(datetime.combine(monday, datetime.min.time(), PACIFIC)))


def _history_start(now: datetime) -> datetime:
    # Calendar subtraction BEFORE converting to UTC preserves Monday00:00 across DST.
    monday = pacific_week_start(now).astimezone(PACIFIC).date() - timedelta(days=7)
    return _require_time(as_utc(datetime.combine(monday, datetime.min.time(), PACIFIC)))


def mark_ready(kind: str) -> None:
    """Persist this startup's actual DB-clock readiness; kinds/versions are closed."""
    if kind not in WRITER_KINDS:
        raise ValueError("usage writer kind invalid")
    with usage.sqlite_transaction_lock(), get_database().session() as session:
        _bounded_statement(session)
        values = {"kind": kind, "writer_version": 1, "ready_at": _db_now(session)}
        session.execute(_insert(session, UsageWriterReady).values(**values).on_conflict_do_update(
            index_elements=["kind"], set_=values,
        ))


def _coverage(session: Session, *, lock: bool = False) -> UsageCoverage:
    session.execute(_insert(session, UsageCoverage).values(id=1, phase="backfill", reconciled_count=0,
                    fault_overflow=0).on_conflict_do_nothing(index_elements=["id"]))
    stmt = select(UsageCoverage).where(UsageCoverage.id == 1).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update()
    return session.exec(stmt).one()


def _fault(session: Session, event_id: str, code: str) -> None:
    if code not in FAULT_CODES:
        raise ValueError("usage reconcile fault invalid")
    coverage = _coverage(session, lock=True)
    if session.exec(select(UsageFault.id).where(UsageFault.event_id == event_id, UsageFault.code == code)).first():
        return
    count = session.exec(select(func.count()).select_from(UsageFault)).one()
    if count >= FAULT_CAP:
        # Encounters beyond the cap, NOT an invented number of distinct omitted events.
        coverage.fault_overflow += 1
        session.add(coverage)
    else:
        session.add(UsageFault(event_id=event_id, code=code, detected_at=_db_now(session)))
    session.flush()


def _pending_summary(session: Session) -> tuple[int, datetime | None]:
    count, oldest = session.execute(sql_select(func.count(), func.min(UsagePending.pending_at))
                                    .select_from(UsagePending)).one()
    return count, as_utc(oldest) if oldest is not None else None


# Alias keeps the fixed table references below readable, without a second drain implementation.
UsagePending = usage.UsagePending


def _pending_order():
    return (col(UsagePending.pending_at), col(UsagePending.event_at),
            col(UsagePending.event_id), col(UsagePending.revision))


def _after_cursor(columns, values):
    # Typed lexicographic comparison, portable to both supported databases.
    return or_(*(and_(*(columns[j] == values[j] for j in range(i)), columns[i] > values[i])
                 for i in range(len(columns))))


def _row_limit(session: Session, requested: int = MAX_BATCH) -> int:
    return min(MAX_BATCH, max(0, requested), session.info.get("usage_rows_left", MAX_BATCH))


def _consume_row(session: Session) -> None:
    if "usage_rows_left" in session.info:
        session.info["usage_rows_left"] = max(0, session.info["usage_rows_left"] - 1)


def drain_pending(session: Session, budget: float = DRAIN_BUDGET_SECONDS) -> dict[str, int]:
    """Complete one finite attempt, committing helper outcomes before its heartbeat.

    Owns transaction boundaries on the supplied session. At most200 candidates,
    at most20s admission budget (+one in-flight <=5s statement). No retry spin.
    Busy/deferred rows remain numeric pending; a cursor prevents head starvation.
    """
    counts = dict.fromkeys(("attempted", "drained", "already_final", "busy", "deferred", "missing", "faulted"), 0)
    if not enabled():
        return counts
    deadline = min(time.monotonic() + min(max(budget, 0.0), DRAIN_BUDGET_SECONDS),
                   session.info.get("usage_deadline", float("inf")))
    _bounded_statement(session)
    columns = _pending_order()
    stmt = sql_select(*columns).order_by(*columns).limit(_row_limit(session))
    heartbeat = session.get(UsageDrainHeartbeat, 1, populate_existing=True)
    cursor = None
    if heartbeat is not None and heartbeat.cursor_pending_at is not None:
        cursor = (heartbeat.cursor_pending_at, heartbeat.cursor_event_at,
                  heartbeat.cursor_event_id, heartbeat.cursor_revision)
    candidates = session.execute(stmt.where(_after_cursor(columns, cursor)) if cursor else stmt).all()
    if not candidates and cursor:
        candidates = session.execute(stmt).all()
    session.commit()  # No read snapshot or row lock spans the Python batch.
    last = None
    for pending_at, event_at, event_id, revision in candidates:
        if time.monotonic() >= deadline or _stop.is_set() or not enabled():
            break
        with usage.sqlite_transaction_lock():
            try:
                _bounded_statement(session)
                result = usage.drain_pending_row(session, event_id, revision)
                session.commit()  # MUST be immediately after the landed helper.
                counts[result.status.replace("-", "_")] += 1
            except Exception:  # fault code only; never copy database/event/exception contents
                session.rollback()
                counts["faulted"] += 1
                _bounded_statement(session)
                _fault(session, event_id, "drain-fault")
                session.commit()
        counts["attempted"] += 1
        _consume_row(session)
        last = (pending_at, event_at, event_id, revision)
        if _stop.wait(BATCH_PAUSE_SECONDS):
            break
    if not enabled() or _stop.is_set():
        # Interrupted/OFF attempts do not pretend to be completed.
        return counts
    with usage.sqlite_transaction_lock():
        _bounded_statement(session)
        remaining, _ = _pending_summary(session)
        kinds = [key for key in ("drained", "already_final", "busy", "deferred", "faulted", "missing") if counts[key]]
        outcome = "empty" if not kinds else (kinds[0].replace("_", "-") if len(kinds) == 1 else "mixed")
        if outcome in ("faulted", "missing"):
            outcome = "fault"
        if not counts["attempted"] and candidates:
            outcome = "budget"
        values = {"id": 1, "last_drain_at": _db_now(session), "outcome": outcome,
                  "remaining": remaining, **counts}
        if last is not None:
            values.update(zip(("cursor_pending_at", "cursor_event_at", "cursor_event_id", "cursor_revision"), last, strict=True))
        elif cursor:
            values.update(zip(("cursor_pending_at", "cursor_event_at", "cursor_event_id", "cursor_revision"), cursor, strict=True))
        session.execute(_insert(session, UsageDrainHeartbeat).values(**values).on_conflict_do_update(
            index_elements=["id"], set_=values,
        ))
        session.commit()  # Failed persistence never fabricates a completion.
    return counts


def drain_state(session: Session) -> dict[str, Any]:
    """Pure read. Application pending_at ages are assessed against the DB clock."""
    now = _db_now(session)
    with session.no_autoflush:
        count, oldest = _pending_summary(session)
        heartbeat = session.get(UsageDrainHeartbeat, 1, populate_existing=True)
    last = as_utc(heartbeat.last_drain_at) if heartbeat else None
    codes = []
    if count and oldest and (now - oldest).total_seconds() > 900:
        codes.append("pending-old")
    if count and (last is None or (now - last).total_seconds() > 300):
        codes.append("drain-silent")
    if count and not enabled():
        codes.append("drain-off")
    return {"enabled": enabled(), "pending_count": count, "oldest_pending_at": oldest,
            "last_drain_at": last, "checked_at": now, "stalled": bool(codes), "codes": codes,
            "outcome": heartbeat.outcome if heartbeat else None,
            "outcomes": {key: getattr(heartbeat, key) if heartbeat else 0 for key in
                         ("attempted", "drained", "remaining", "already_final", "busy", "deferred", "missing", "faulted")},
            "clock_provenance": {"checked_at": "database-clock", "last_drain_at": "database-completed-attempt",
                                 "oldest_pending_at": "application-record-construction"}}


def _not_captured():
    return (~exists(sql_select(1).where(usage.UsageCallRow.event_id == Event.id)),
            ~exists(sql_select(1).where(UsagePending.event_id == Event.id)))


def _not_fork(session: Session, model=Event):
    data = col(model.data)
    if session.get_bind().dialect.name == "postgresql":
        return func.coalesce(cast(data["restored_from_fork"], String), "null") != "true"
    return func.coalesce(func.json_type(data, "$.restored_from_fork"), "null") != "true"


def _lost_attempt_leaves(session: Session):
    data = col(Event.data)
    if session.get_bind().dialect.name == "postgresql":
        kind = func.json_typeof(data["lost_attempts"])
        length = func.json_array_length(data["lost_attempts"])
    else:
        kind = func.json_type(data, "$.lost_attempts")
        length = func.json_array_length(data, "$.lost_attempts")
    return (case((kind == "array", length), else_=None).label("lost_count"),
            func.coalesce(kind.not_in(("array", "null")), False).label("lost_invalid"))


def _scalar_leaf(session: Session, key: str):
    data = col(Event.data)
    postgres = session.get_bind().dialect.name == "postgresql"
    kind = func.json_typeof(data[key]) if postgres else func.json_type(data, "$." + key)
    if key in (*usage.TOKEN_FIELDS.values(), "cost_usd"):
        allowed = ("number", "null") if postgres else ("integer", "real", "null")
    elif key == "restored_from_fork":
        allowed = ("boolean", "null") if postgres else ("true", "false", "null")
    else:
        allowed = ("string", "null") if postgres else ("text", "null")
    # Malformed containers/strings in numeric slots never cross the SQL boundary.
    # A fixed invalid sentinel below preserves the landed extractor's fault code.
    return (case((kind.in_(allowed), data[key]), else_=None).label(key),
            func.coalesce(kind.not_in(allowed), False).label(key + "_invalid"))


def _leaf_select(session: Session) -> Select:
    return sql_select(col(Event.id), col(Event.type), col(Event.timestamp), col(Event.execution_id), col(Event.parent_id),
                      *(leaf for key in LEAVES for leaf in _scalar_leaf(session, key)), *_lost_attempt_leaves(session))


def _eligible(session: Session, now: datetime):
    current = pacific_week_start(now)
    return (_leaf_select(session).where(col(Event.type).in_(usage.CALL_TYPES),
            col(Event.timestamp) >= _history_start(now), col(Event.timestamp) <= now,
            _not_fork(session), *_not_captured())
            .order_by(case((col(Event.timestamp) >= current, 0), else_=1), col(Event.timestamp), col(Event.id)))


def _project(leaves) -> usage.UsageCallRow | None:
    data = {key: [] if leaves[key + "_invalid"] else leaves[key] for key in LEAVES}
    row = usage.extract(leaves["type"], data, {"event_id": leaves["id"], "execution_id": leaves["execution_id"],
                        "parent_id": leaves["parent_id"]}, leaves["timestamp"])
    if row is not None:
        row.origin = "reconciled"
        # Only SQL ARRAY LENGTH crosses this boundary, never the lost_attempts array.
        row.lost_attempts = leaves["lost_count"]
        if leaves["lost_invalid"]:
            row.fault_codes = ",".join(sorted(filter(None, [*row.fault_codes.split(","), "lost-invalid"])))
    return row


def _ready_boundary(session: Session) -> datetime | None:
    rows = session.exec(select(UsageWriterReady).where(UsageWriterReady.writer_version == 1)).all()
    if {row.kind for row in rows} != WRITER_KINDS:
        return None
    return max(_require_time(as_utc(row.ready_at)) for row in rows)


def _begin_lap(session: Session) -> dict[str, Any] | None:
    _bounded_statement(session)
    coverage = _coverage(session, lock=True)
    if coverage.cutover_at is not None:
        session.commit()
        return None
    now = _db_now(session)
    boundary = _ready_boundary(session)
    if boundary is not None and _earlier_execution_open(session, boundary):
        boundary = None
    lower = _history_start(now)
    if (coverage.lap_started_at is None or coverage.lap_complete
            or as_utc(coverage.lap_ready_at) != boundary or as_utc(coverage.lap_from) != lower):
        coverage.lap_generation += 1
        coverage.lap_ready_at = boundary
        coverage.lap_started_at = now
        coverage.lap_upper_at = now
        coverage.lap_from = lower
        coverage.lap_cursor_week = None
        coverage.lap_cursor_at = None
        coverage.lap_cursor_event_id = None
        coverage.lap_clean = True
        coverage.lap_complete = False
        coverage.backfilled_from = lower
        session.add(coverage)
    state = {key: getattr(coverage, key) for key in
             ("lap_generation", "lap_upper_at", "lap_cursor_week", "lap_cursor_at", "lap_cursor_event_id")}
    session.commit()
    return state


def _checkpoint_lap(session: Session, generation: int, cursor, *, clean: bool, complete: bool = False) -> None:
    _bounded_statement(session)
    coverage = _coverage(session, lock=True)
    if coverage.lap_generation == generation:
        coverage.lap_clean = coverage.lap_clean and clean
        if cursor is not None:
            previous = (coverage.lap_cursor_week, as_utc(coverage.lap_cursor_at), coverage.lap_cursor_event_id)
            if previous[0] is None or cursor > previous:
                coverage.lap_cursor_week, coverage.lap_cursor_at, coverage.lap_cursor_event_id = cursor
        coverage.lap_complete = coverage.lap_complete or complete
        session.add(coverage)
    session.commit()


def _lap_candidates(session: Session, upper: datetime, cursor):
    week = case((col(Event.timestamp) >= pacific_week_start(upper), 0), else_=1)
    stmt = _eligible(session, upper)
    if cursor is not None:
        stmt = stmt.where(_after_cursor((week, col(Event.timestamp), col(Event.id)), cursor))
    return stmt


def reconcile_batch(session: Session, limit: int = MAX_BATCH) -> int:
    """One typed-keyset lap slice; ordering locks never span this Python batch.

    A final lap starts AFTER readiness and the earlier-run barrier. Any skipped or
    failed row makes that entire lap dirty. The cursor is NOT coverage evidence.
    """
    limit = _row_limit(session, limit)
    if not enabled() or not limit:
        return 0
    lap = _begin_lap(session)
    if lap is None:
        return 0
    upper = _require_time(as_utc(lap["lap_upper_at"]))
    cursor = None if lap["lap_cursor_at"] is None else (
        lap["lap_cursor_week"], as_utc(lap["lap_cursor_at"]), lap["lap_cursor_event_id"])
    _bounded_statement(session)
    candidates = session.execute(_lap_candidates(session, upper, cursor).limit(limit)).mappings().all()
    session.commit()
    written = 0
    clean = True
    deadline = min(time.monotonic() + RECONCILE_BUDGET_SECONDS,
                   session.info.get("usage_deadline", float("inf")))
    for candidate in candidates:
        if not enabled() or _stop.is_set() or not _row_limit(session) or time.monotonic() >= deadline:
            break
        _consume_row(session)
        with usage.sqlite_transaction_lock():
            try:
                _bounded_statement(session)
                locked = session.exec(select(Event.id).where(Event.id == candidate["id"])
                                      .with_for_update(skip_locked=True)).first()
                if locked is None:
                    clean = False
                    session.commit()
                else:
                    # Reload ONLY leaves in the same Event transaction; a live
                    # final OR pending capture makes this old candidate ineligible.
                    leaves = session.execute(_eligible(session, upper).where(Event.id == locked)).mappings().first()
                    row = _project(leaves) if leaves is not None else None
                    if row is not None:
                        result = usage.write_or_queue_row(session, row)
                        session.commit()  # Immediately release #125's ordering lock.
                        written += 1
                        if result is None:
                            clean = False
                    else:
                        clean = False  # A changed candidate needs another clean lap.
                        session.commit()
            except Exception as error:
                session.rollback()
                clean = False
                logger.warning("Usage recovery row failed: %s", type(error).__name__)
            cursor = (0 if _require_time(as_utc(candidate["timestamp"])) >= pacific_week_start(upper) else 1,
                      _require_time(as_utc(candidate["timestamp"])), candidate["id"])
            _checkpoint_lap(session, lap["lap_generation"], cursor, clean=clean)
        if _stop.wait(BATCH_PAUSE_SECONDS):
            break
    _bounded_statement(session)
    complete = not session.execute(_lap_candidates(session, upper, cursor).limit(1)).first()
    session.commit()
    with usage.sqlite_transaction_lock():
        _checkpoint_lap(session, lap["lap_generation"], cursor, clean=clean, complete=complete)
        if written:
            _bounded_statement(session)
            progress = _coverage(session, lock=True)
            progress.reconciled_count += written
            session.add(progress)
            session.commit()
    return written


def _earlier_execution_open(session: Session, cutoff: datetime) -> bool:
    first = (sql_select(col(Event.execution_id).label("execution_id"), func.min(Event.timestamp).label("first_at"))
             .where(col(Event.execution_id).is_not(None)).group_by(Event.execution_id).subquery())
    bad_event = exists(sql_select(1).where(col(Event.execution_id) == first.c.execution_id,
                       col(Event.type) == "workflow.started",
                       (col(Event.status).is_(None) | col(Event.status).not_in(TERMINAL))))
    bad_run = exists(sql_select(1).where(col(WorkflowRun.execution_id) == first.c.execution_id,
                                      col(WorkflowRun.status).not_in(TERMINAL)))
    terminal_event = exists(sql_select(1).where(col(Event.execution_id) == first.c.execution_id,
                            col(Event.type) == "workflow.started", col(Event.status).in_(TERMINAL)))
    terminal_run = exists(sql_select(1).where(col(WorkflowRun.execution_id) == first.c.execution_id,
                                           col(WorkflowRun.status).in_(TERMINAL)))
    blocked = session.execute(sql_select(first.c.execution_id).where(first.c.first_at < cutoff,
                              bad_event | bad_run | (~terminal_event & ~terminal_run)).limit(1)).first()
    anonymous = session.exec(select(Event.id).where(Event.type == "workflow.started", Event.timestamp < cutoff,
                   col(Event.execution_id).is_(None), col(Event.status).is_(None) | col(Event.status).not_in(TERMINAL))
                   .limit(1)).first()
    return blocked is not None or anonymous is not None


def _start_captures():
    fields = tuple(usage.UsageObservation.model_fields)
    return sql_select(*(getattr(usage.UsageCallRow, key) for key in fields)).where(
        usage.UsageCallRow.event_type == "llm.call.started").union_all(
        sql_select(*(getattr(UsagePending, key) for key in fields)).where(
            UsagePending.event_type == "llm.call.started")).subquery()


def _has_unended(codes):
    return ("," + codes + ",").contains(",call-unended,")


def _start_candidates(session: Session, now: datetime, cursor):
    starts = _start_captures()
    latest = sql_select(func.max(starts.c.revision)).where(starts.c.event_id == Event.id).correlate(Event).scalar_subquery()
    marked = exists(sql_select(1).where(starts.c.event_id == Event.id, starts.c.revision == latest,
                                      _has_unended(starts.c.fault_codes)))
    instance = sql_select(col(usage.UsageSourceInstance.instance)).where(col(usage.UsageSourceInstance.id) == 1).scalar_subquery()
    proof = exists(sql_select(1).where(starts.c.event_id == Event.id, starts.c.instance == instance,
                   starts.c.origin == "live", or_(starts.c.token_source == "service",
                   and_(starts.c.token_source == "pi", starts.c.llm_call_id.is_not(None),
                        starts.c.call_kind.is_not(None)))))
    stmt = sql_select(col(Event.id), col(Event.timestamp)).where(col(Event.type) == "llm.call.started", proof,
                       col(Event.timestamp) <= now, _not_fork(session),
                       or_(col(Event.timestamp) >= _history_start(now), marked))
    if cursor is not None:
        stmt = stmt.where(_after_cursor((col(Event.timestamp), col(Event.id)), cursor))
    return stmt.order_by(col(Event.timestamp), col(Event.id)).limit(_row_limit(session))


def _string_leaf_matches(session: Session, model, key: str, value):
    data = col(model.data)
    kind = (func.json_typeof(data[key]) if session.get_bind().dialect.name == "postgresql"
            else func.json_type(data, "$." + key))
    return and_(kind == ("string" if session.get_bind().dialect.name == "postgresql" else "text"),
                data[key].as_string() == value)


def _start_snapshot(session: Session, event_id: str, now: datetime):
    """All producer, terminal-age, ambiguity and end evidence in ONE SQL snapshot."""
    starts = _start_captures()
    latest = sql_select(starts).where(starts.c.event_id == event_id).order_by(
        starts.c.revision.desc()).limit(1).subquery()
    current_instance = sql_select(col(usage.UsageSourceInstance.instance)).where(
        col(usage.UsageSourceInstance.id) == 1).scalar_subquery()
    def scope(m):
        return (m.instance == latest.c.instance,
                m.execution_id.is_not_distinct_from(latest.c.execution_id),
                m.parent_id.is_not_distinct_from(latest.c.parent_id),
                m.token_source == latest.c.token_source,
                m.call_kind.is_not_distinct_from(latest.c.call_kind),
                m.llm_call_id.is_not_distinct_from(latest.c.llm_call_id))
    proven = exists(sql_select(1).where(starts.c.event_id == latest.c.event_id,
                    starts.c.origin == "live", *scope(starts.c)))
    unique_pi_start = (sql_select(func.count(func.distinct(starts.c.event_id))).where(
        *scope(starts.c)).scalar_subquery() == 1)
    settled = exists(sql_select(1).where(col(WorkflowRun.execution_id) == latest.c.execution_id,
                     col(WorkflowRun.status).in_(TERMINAL),
                     col(WorkflowRun.completed_at) <= now - timedelta(minutes=15)))
    conflicting_status = exists(sql_select(1).where(col(Event.execution_id) == latest.c.execution_id,
                               col(Event.type) == "workflow.started",
                               col(Event.status).is_(None) | col(Event.status).not_in(TERMINAL)))
    end_conditions = []
    for model in (usage.UsageCallRow, UsagePending):
        end_conditions.append(exists(sql_select(1).where(
            col(model.instance) == latest.c.instance, col(model.execution_id).is_not_distinct_from(latest.c.execution_id),
            col(model.event_type).in_(("llm.call.completed", "llm.call.failed")),
            col(model.token_source) == latest.c.token_source,
            or_(and_(latest.c.token_source == "service", col(model.started_event_id) == latest.c.event_id),
                and_(latest.c.token_source == "pi", col(model.llm_call_id) == latest.c.llm_call_id,
                     col(model.parent_id).is_not_distinct_from(latest.c.parent_id),
                     col(model.call_kind).is_not_distinct_from(latest.c.call_kind))))))
    end = aliased(Event)
    end_conditions.append(exists(sql_select(1).where(
        col(end.execution_id).is_not_distinct_from(latest.c.execution_id),
        col(end.type).in_(("llm.call.completed", "llm.call.failed")), _not_fork(session, end),
        or_(and_(latest.c.token_source == "service",
                 _string_leaf_matches(session, end, "started_event_id", latest.c.event_id)),
            and_(latest.c.token_source == "pi", col(end.parent_id).is_not_distinct_from(latest.c.parent_id),
                 _string_leaf_matches(session, end, "llm_call_id", latest.c.llm_call_id),
                 _string_leaf_matches(session, end, "call_kind", latest.c.call_kind),
                 _string_leaf_matches(session, end, "executed_by", "pi"))))))
    return session.execute(sql_select(latest, or_(*end_conditions).label("end_seen"),
        and_(latest.c.instance == current_instance, proven,
             or_(latest.c.token_source == "service",
                 and_(latest.c.token_source == "pi", latest.c.llm_call_id.is_not(None),
                      latest.c.call_kind.is_not(None), unique_pi_start))).label("producer_proven"),
        and_(settled, ~conflicting_status).label("settled"),
        exists(sql_select(1).where(col(UsagePending.event_id) == latest.c.event_id)).label("start_pending")
        )).mappings().first()


def mark_unended(session: Session) -> int:
    """Live-proven, exactly linked diagnostic revisions; unknowns never become faults.

    Pi is live-only (no claim about the historical emitter). Service requires its
    own live capture, whose producer writes started_event_id on both end paths.
    Terminal age is a delay, not evidence that no late end can arrive.
    """
    if not enabled() or not _row_limit(session):
        return 0
    _bounded_statement(session)
    coverage = _coverage(session)
    cursor = None if coverage.start_cursor_at is None else (
        as_utc(coverage.start_cursor_at), coverage.start_cursor_event_id)
    now = _db_now(session)
    candidates = session.execute(_start_candidates(session, now, cursor)).all()
    if not candidates and cursor:
        candidates = session.execute(_start_candidates(session, now, None)).all()
    session.commit()
    deadline = min(time.monotonic() + UNENDED_BUDGET_SECONDS,
                   session.info.get("usage_deadline", float("inf")))
    written = 0
    for event_id, event_at in candidates:
        if not enabled() or _stop.is_set() or not _row_limit(session) or time.monotonic() >= deadline:
            break
        _consume_row(session)
        with usage.sqlite_transaction_lock():
            _bounded_statement(session)
            locked = session.exec(select(Event.id).where(Event.id == event_id).with_for_update(skip_locked=True)).first()
            snapshot = _start_snapshot(session, event_id, _db_now(session)) if locked else None
            if snapshot is not None and snapshot["producer_proven"] and not snapshot["start_pending"]:
                codes = set(filter(None, snapshot["fault_codes"].split(",")))
                marked = "call-unended" in codes
                if (marked and snapshot["end_seen"]) or (not marked and snapshot["settled"] and not snapshot["end_seen"]):
                    if marked:
                        codes.remove("call-unended")
                    else:
                        codes.add("call-unended")
                    values = {key: snapshot[key] for key in usage.UsageObservation.model_fields}
                    values.update(revision=snapshot["revision"] + 1, origin="reconciled",
                                  occurrence_basis="call_start", occurred_at=snapshot["event_at"],
                                  fault_codes=",".join(sorted(codes)), legacy_cost_usd=None, legacy_cost_source=None,
                                  **dict.fromkeys(usage.TOKEN_FIELDS, None))
                    usage.write_or_queue_row(session, usage.UsageCallRow(**values))
                    session.commit()  # No cursor/diagnostic SQL under ordering lock.
                    written += 1
                else:
                    session.commit()
            else:
                session.commit()
            _bounded_statement(session)
            progress = _coverage(session, lock=True)
            progress.start_cursor_at, progress.start_cursor_event_id = event_at, event_id
            session.add(progress)
            session.commit()
        if _stop.wait(BATCH_PAUSE_SECONDS):
            break
    return written


def try_cutover(session: Session) -> bool:
    """Freeze the ready boundary once, only after older execution and final-pass checks."""
    if not enabled():
        return False
    with usage.sqlite_transaction_lock():
        _bounded_statement(session)
        coverage = _coverage(session, lock=True)
        if coverage.cutover_at is not None:
            session.commit()
            return True
        ready = session.exec(select(UsageWriterReady).where(UsageWriterReady.writer_version == 1)
                             .with_for_update()).all()
        if {row.kind for row in ready} != WRITER_KINDS:
            session.commit()
            return False
        boundary = max(_require_time(as_utc(row.ready_at)) for row in ready)
        if (_earlier_execution_open(session, boundary)
                or as_utc(coverage.lap_ready_at) != boundary
                or coverage.lap_started_at is None or _require_time(as_utc(coverage.lap_started_at)) < boundary
                or not coverage.lap_clean or not coverage.lap_complete
                or session.execute(_eligible(session, _db_now(session)).limit(1)).first()):
            session.commit()
            return False
        coverage.cutover_at = boundary
        coverage.cutover_seq = session.exec(select(func.max(usage.UsageCallRow.seq))).one()
        coverage.phase = "cutover"
        session.add(coverage)
        session.commit()
        return True


def check_post_cutover(session: Session) -> int:
    if not enabled() or not _row_limit(session):
        return 0
    _bounded_statement(session)
    coverage = session.get(UsageCoverage, 1, populate_existing=True)
    if coverage is None or coverage.cutover_at is None:
        return 0
    missing = session.exec(select(Event.id).where(col(Event.type).in_(usage.CALL_TYPES),
                 Event.timestamp >= coverage.cutover_at, _not_fork(session), *_not_captured(),
                 ~exists(sql_select(1).where(col(UsageFault.event_id) == Event.id,
                                           col(UsageFault.code) == "post-cutover-missing-row")))
                 .order_by(col(Event.timestamp), col(Event.id)).limit(_row_limit(session))).all()
    session.commit()
    checked = 0
    for event_id in missing:
        if (_stop.is_set() or not enabled() or not _row_limit(session)
                or time.monotonic() >= session.info.get("usage_deadline", float("inf"))):
            break
        _consume_row(session)
        checked += 1
        with usage.sqlite_transaction_lock():
            _bounded_statement(session)
            # The old-writer event is committed before a capture. Check again
            # under its lock; a concurrent final/pending capture is never missing.
            locked = session.exec(select(Event.id).where(Event.id == event_id).with_for_update(skip_locked=True)).first()
            if locked and session.exec(select(Event.id).where(Event.id == event_id, *_not_captured())).first():
                _fault(session, event_id, "post-cutover-missing-row")
            session.commit()
    return checked


def coverage_state(session: Session) -> dict[str, Any]:
    """Pure read. Internal readiness/cutover/faults never certify occurrence coverage."""
    with session.no_autoflush:
        row = session.get(UsageCoverage, 1, populate_existing=True)
        counts = {code: 0 for code in sorted(FAULT_CODES)}
        counts.update({code: count for code, count in session.execute(
            sql_select(col(UsageFault.code), func.count()).group_by(UsageFault.code)).all()})
    return {"status": "UNKNOWN", "cutover_at": as_utc(row.cutover_at) if row and row.cutover_at else None,
            "cutover_seq": row.cutover_seq if row else None,
            "backfilled_from": as_utc(row.backfilled_from) if row and row.backfilled_from else None,
            "phase": row.phase if row else "backfill", "reconciled_count": row.reconciled_count if row else 0,
            "fault_counts": counts, "fault_overflow": row.fault_overflow if row else 0,
            "reconcile_lap": {"generation": row.lap_generation if row else 0,
                              "started_at": as_utc(row.lap_started_at) if row else None,
                              "ready_at": as_utc(row.lap_ready_at) if row else None,
                              "clean": row.lap_clean if row else None,
                              "complete": row.lap_complete if row else False},
            "checked_at": _db_now(session), "clock_provenance": "database-assessment; cutover=latest-ready-database-clock"}


def _sweep() -> None:
    if not enabled():
        return
    with get_database().session() as session:
        deadline = time.monotonic() + WAKE_BUDGET_SECONDS
        session.info["usage_deadline"] = deadline
        session.info["usage_rows_left"] = MAX_BATCH
        counts = drain_pending(session)
        for stage in (reconcile_batch, mark_unended, try_cutover, check_post_cutover):
            if _stop.is_set() or not enabled() or time.monotonic() >= deadline:
                break
            stage(session)
    logger.info("Usage attempt completed: attempted=%d drained=%d busy=%d deferred=%d faulted=%d",
                counts["attempted"], counts["drained"], counts["busy"], counts["deferred"], counts["faulted"])


def _loop() -> None:
    deadline = time.monotonic() + EVERY_SECONDS
    while not _stop.wait(max(0.0, deadline - time.monotonic())):
        try:
            _sweep()
        except Exception as error:
            logger.warning("Usage sweep failed: %s", type(error).__name__)
        deadline = max(deadline + EVERY_SECONDS, time.monotonic())


def start() -> bool:
    global _thread
    if not enabled():
        return False
    if _thread is not None and _thread.is_alive():
        return True
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="usage-reconcile", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()
    if _thread is not None:
        # Finish the bounded in-flight transaction before the server closes DB.
        _thread.join()
