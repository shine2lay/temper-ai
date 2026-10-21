"""Content-free native call observations, committed atomically with their events.

No pricing or allocation happens here. In particular, Pi's stored zeros and the
service's legacy cost are observations, not proof of free usage or a price basis.
"""

from __future__ import annotations

import math
import re
import threading
import uuid
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    delete,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DBAPIError
from sqlmodel import Column, Field, Session, SQLModel, col, select

from temper_ai.database import get_database
from temper_ai.observability.models import Event
from temper_ai.shared.clock import as_utc, utcnow

CALL_TYPES = frozenset({"llm.call.started", "llm.call.completed", "llm.call.failed"})
STARTED = "llm.call.started"
MAX_SAFE_INTEGER = 2**53 - 1
# Fixed, project-specific key, shared by server, workers and per-run containers.
# Never hash Python objects (hash randomisation would give each process a different lock).
COMMIT_ORDER_LOCK = 0x54454D5055534147
_LABEL = re.compile(r"[A-Za-z0-9._:/@+\-]{1,128}", re.ASCII)
_ID = re.compile(r"[A-Za-z0-9._:\-]{1,128}", re.ASCII)
TOKEN_FIELDS = {
    "prompt_tokens": "prompt_tokens",
    "completion_tokens": "completion_tokens",
    "total_tokens": "total_tokens",
    "cache_read_tokens": "cached_prompt_tokens",
    "cache_write_tokens": "cache_write_tokens",
}
_TOKEN_FAULTS = {
    "prompt_tokens": "prompt-invalid", "completion_tokens": "completion-invalid",
    "total_tokens": "total-invalid", "cache_read_tokens": "cache-read-invalid",
    "cache_write_tokens": "cache-write-invalid",
}
FAULT_CODES = frozenset({
    *_TOKEN_FAULTS.values(), "provider-invalid", "provider-unproven", "model-invalid",
    "model-unproven", "kind-invalid", "id-invalid", "cost-invalid", "lost-invalid",
    "link-unproven", "usage-missing", "ordering-deferred",
})
# In-memory SQLite tests share a connection. Keep its whole recorder transaction
# together, not just the INSERT. File SQLite also serialises writers in the DB.
_SQLITE_TRANSACTION_LOCK = threading.RLock()


class UsageSourceInstance(SQLModel, table=True):
    """One random database incarnation; never derived from runtime surroundings."""

    __tablename__ = "usage_source_instance"
    __table_args__ = (CheckConstraint("id = 1", name="usage_instance_singleton"),)

    id: int = Field(default=1, primary_key=True)
    instance: str = Field(sa_column=Column(String(36), nullable=False))


def _projection_constraints(prefix: str) -> tuple[CheckConstraint, ...]:
    """Identical closed schema bounds, with a separate constraint object per table."""
    return (
        CheckConstraint("revision >= 0", name=f"{prefix}_revision_nonnegative"),
        CheckConstraint("event_type IN ('llm.call.started','llm.call.completed','llm.call.failed')",
                        name=f"{prefix}_event_type"),
        CheckConstraint("call_kind IS NULL OR call_kind IN ('model','compaction')", name=f"{prefix}_call_kind"),
        CheckConstraint("token_source IN ('pi','service')", name=f"{prefix}_token_source"),
        CheckConstraint("origin IN ('live','reconciled')", name=f"{prefix}_origin"),
        CheckConstraint("occurrence_basis IS NULL OR occurrence_basis IN ('call_start','call_end')",
                        name=f"{prefix}_occurrence_basis"),
        CheckConstraint("legacy_cost_source IS NULL OR legacy_cost_source IN ('pi_estimate','service')",
                        name=f"{prefix}_cost_source"),
        CheckConstraint("length(fault_codes) <= 256", name=f"{prefix}_fault_bound"),
    )


class UsageObservation(SQLModel):
    """The exact typed projection shared by final and pending storage. No JSON."""

    event_id: str = Field(max_length=128, index=True)
    revision: int = Field(default=0)
    instance: str = Field(default="", max_length=36)
    execution_id: str | None = Field(default=None, max_length=128)
    parent_id: str | None = Field(default=None, max_length=128)
    event_type: str = Field(max_length=32)
    call_kind: str | None = Field(default=None, max_length=16)
    llm_call_id: str | None = Field(default=None, max_length=128)
    started_event_id: str | None = Field(default=None, max_length=128)
    provider: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    prompt_tokens: int | None = Field(default=None, sa_type=BigInteger)
    completion_tokens: int | None = Field(default=None, sa_type=BigInteger)
    total_tokens: int | None = Field(default=None, sa_type=BigInteger)
    cache_read_tokens: int | None = Field(default=None, sa_type=BigInteger)
    cache_write_tokens: int | None = Field(default=None, sa_type=BigInteger)
    token_source: str = Field(max_length=8)
    legacy_cost_usd: float | None = None
    legacy_cost_source: str | None = Field(default=None, max_length=16)
    lost_attempts: int | None = Field(default=None, sa_type=BigInteger)
    event_at: datetime
    occurred_at: datetime | None = None
    occurrence_basis: str | None = Field(default=None, max_length=16)
    origin: str = Field(default="live", max_length=16)
    fault_codes: str = Field(default="", max_length=256)


class UsageCallRow(UsageObservation, table=True):
    """Append-only final observations. Sequence numbers mean visibility order."""

    __tablename__ = "usage_call_rows"
    __table_args__ = (
        *_projection_constraints("usage"),
        UniqueConstraint("event_id", "revision", name="usage_event_revision"),
        Index("usage_start_call", "llm_call_id", "event_type", "revision"),
    )
    # BIGSERIAL is evaluated AFTER the lock. SQLite allocates inside its single writer.
    seq: int | None = Field(default=None, sa_column=Column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True,
    ))


class UsagePending(UsageObservation, table=True):
    """Durable numeric capture when the final ordering statement cannot get its lock."""

    __tablename__ = "usage_pending"
    __table_args__ = (
        *_projection_constraints("usage_pending"),
        CheckConstraint("defer_reason = 'ordering-lock-timeout'", name="usage_pending_reason"),
        Index("usage_pending_start_call", "llm_call_id", "event_type", "revision"),
    )
    event_id: str = Field(max_length=128, primary_key=True)
    revision: int = Field(default=0, primary_key=True)
    pending_at: datetime = Field(default_factory=utcnow)
    defer_reason: str = Field(default="ordering-lock-timeout", max_length=32)


@dataclass(frozen=True)
class DrainOutcome:
    """Caller must commit. Only 'drained' means a newly appended observation."""

    status: Literal["drained", "already-final", "deferred", "busy", "missing"]
    seq: int | None = None


@dataclass(frozen=True)
class _AppendOutcome:
    status: Literal["inserted", "already-final", "deferred"]
    seq: int | None = None


# Fixed Core statement, compiled/cached once per engine. All parameter values
# are prepared before execution; never compile an uncached INSERT under the lock.
_POSTGRES_ROW_INSERT = text("""
    WITH commit_order AS MATERIALIZED (
        SELECT pg_advisory_xact_lock(:commit_order_lock)
    )
    INSERT INTO usage_call_rows (
        event_id, revision, instance, execution_id, parent_id, event_type,
        call_kind, llm_call_id, started_event_id, provider, model,
        prompt_tokens, completion_tokens, total_tokens, cache_read_tokens,
        cache_write_tokens, token_source, legacy_cost_usd, legacy_cost_source,
        lost_attempts, event_at, occurred_at, occurrence_basis, origin, fault_codes
    )
    SELECT
        :event_id, :revision, :instance, :execution_id, :parent_id, :event_type,
        :call_kind, :llm_call_id, :started_event_id, :provider, :model,
        :prompt_tokens, :completion_tokens, :total_tokens, :cache_read_tokens,
        :cache_write_tokens, :token_source, :legacy_cost_usd, :legacy_cost_source,
        :lost_attempts, :event_at, :occurred_at, :occurrence_basis, :origin, :fault_codes
    FROM commit_order
    ON CONFLICT (event_id, revision) DO NOTHING
    RETURNING seq
""")

# Constructed once from OUR fixed, tested schema, never from payload/identifier input.
# DELETE depends on the lock CTE; INSERT defaults allocate seq only after DELETE.
_PROJECTION_COLUMNS = ", ".join(UsageObservation.model_fields)
_POSTGRES_PENDING_DRAIN = text(f"""
    WITH commit_order AS MATERIALIZED (
        SELECT pg_advisory_xact_lock(:commit_order_lock)
    ), drained AS (
        DELETE FROM usage_pending USING commit_order
        WHERE event_id = :event_id AND revision = :revision
        RETURNING {_PROJECTION_COLUMNS}
    )
    INSERT INTO usage_call_rows ({_PROJECTION_COLUMNS})
    SELECT {_PROJECTION_COLUMNS} FROM drained
    ON CONFLICT (event_id, revision) DO NOTHING
    RETURNING seq
""")
_ORDERING_SAVEPOINT = text("SAVEPOINT usage_ordering")
_ORDERING_ROLLBACK = text("ROLLBACK TO SAVEPOINT usage_ordering")
_ORDERING_SETTINGS = text("""
    SELECT set_config('lock_timeout', '2s', true),
           set_config('idle_in_transaction_session_timeout', '5s', true)
""")
_STATEMENT_TIMEOUT = text("SELECT setting::bigint FROM pg_settings WHERE name = 'statement_timeout'")


def sqlite_transaction_lock():
    """Serialize whole recorder transactions only for SQLite's shared test connection."""
    return (_SQLITE_TRANSACTION_LOCK if get_database().engine.dialect.name == "sqlite"
            else nullcontext())


def _identifier(value: Any, faults: set[str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _ID.fullmatch(value):
        return value
    faults.add("id-invalid")
    return None


def _label(value: Any, field: str, faults: set[str]) -> str | None:
    if value is None:
        faults.add(f"{field}-unproven")
        return None
    if isinstance(value, str) and _LABEL.fullmatch(value):
        return value
    faults.add(f"{field}-invalid")
    return None


def extract(event_type: str, data: Mapping[str, Any], ids: Mapping[str, Any],
            event_at: datetime) -> UsageCallRow | None:
    """Pure allowlist extraction. Never copy, stringify, walk or hash unknown fields.

    ``ids`` holds event_id, execution_id and parent_id, not event payload values.
    An invalid required event reference refuses the transaction without echoing it.
    Optional malformed references and numbers become NULL plus closed fault codes.
    """
    if event_type not in CALL_TYPES or data.get("restored_from_fork") is True:
        return None
    faults: set[str] = set()
    event_id = _identifier(ids.get("event_id"), faults)
    if event_id is None:
        raise ValueError("usage event reference invalid")
    pi = data.get("executed_by") == "pi"
    kind = data.get("call_kind")
    if kind is not None and (not isinstance(kind, str) or kind not in ("model", "compaction")):
        kind = None
        faults.add("kind-invalid")
    tokens: dict[str, int | None] = {}
    for field, key in TOKEN_FIELDS.items():
        value = data.get(key)
        if value is None:
            tokens[field] = None
        elif type(value) is int and 0 <= value <= MAX_SAFE_INTEGER:
            tokens[field] = value
        else:
            tokens[field] = None
            faults.add(_TOKEN_FAULTS[field])
    if event_type != STARTED and all(value is None for value in tokens.values()):
        faults.add("usage-missing")
    raw_cost = data.get("cost_usd")
    cost = None
    if raw_cost is not None:
        if type(raw_cost) in (int, float):
            try:
                candidate = float(raw_cost)
                if math.isfinite(candidate) and candidate >= 0:
                    cost = candidate
            except (OverflowError, ValueError):
                pass
        if cost is None:
            faults.add("cost-invalid")
    lost = data.get("lost_attempts")
    lost_count = len(lost) if isinstance(lost, list) else None
    if lost is not None and lost_count is None:
        faults.add("lost-invalid")
    start_id = (event_id if event_type == STARTED
                else _identifier(data.get("started_event_id"), faults))
    row = UsageCallRow(
        event_id=event_id, event_type=event_type,
        execution_id=_identifier(ids.get("execution_id"), faults),
        parent_id=_identifier(ids.get("parent_id"), faults),
        call_kind=kind, llm_call_id=_identifier(data.get("llm_call_id"), faults),
        started_event_id=start_id,
        provider=_label(data.get("provider"), "provider", faults),
        model=_label(data.get("model"), "model", faults),
        **tokens, token_source="pi" if pi else "service",
        legacy_cost_usd=cost,
        legacy_cost_source=("pi_estimate" if pi else "service") if cost is not None else None,
        lost_attempts=lost_count, event_at=as_utc(event_at),
        # A start references ITSELF exactly; terminal events carry their own end time.
        occurred_at=as_utc(event_at),
        occurrence_basis="call_start" if event_type == STARTED else "call_end",
    )
    row.fault_codes = _fault_text(faults)
    return row


def _fault_text(faults: set[str]) -> str:
    # Every caller supplies only these literals, never unknown input strings.
    if not faults <= FAULT_CODES:
        raise ValueError("usage fault code invalid")
    result = ",".join(sorted(faults))
    if len(result) > 256:
        raise ValueError("usage fault codes exceed bound")
    return result


def _insert(session: Session, model):
    return (pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert)(model)


def ensure_instance(session: Session) -> str:
    """Create the singleton once, in the caller's transaction; never cache an uncommitted id."""
    instance = session.exec(select(UsageSourceInstance.instance).where(UsageSourceInstance.id == 1)).first()
    if instance is None:
        session.execute(_insert(session, UsageSourceInstance).values(
            id=1, instance=str(uuid.uuid4()),
        ).on_conflict_do_nothing(index_elements=["id"]))
        instance = session.exec(select(UsageSourceInstance.instance).where(UsageSourceInstance.id == 1)).one()
    return instance


def _link_start(session: Session, row: UsageCallRow) -> None:
    if row.event_type == STARTED:
        return
    faults = set(filter(None, row.fault_codes.split(",")))
    candidates: list[UsageObservation] = []
    for model in (UsageCallRow, UsagePending):
        stmt = select(model).where(
            model.event_type == STARTED,
            model.instance == row.instance,
            model.execution_id == row.execution_id,
            model.parent_id == row.parent_id,
            model.token_source == row.token_source,
            model.call_kind == row.call_kind,
        )
        if row.token_source == "pi" and row.llm_call_id is not None:
            stmt = stmt.where(model.llm_call_id == row.llm_call_id)
        elif row.token_source == "service" and row.started_event_id is not None:
            stmt = stmt.where(model.event_id == row.started_event_id)
        else:
            row.started_event_id = None
            faults.add("link-unproven")
            row.fault_codes = _fault_text(faults)
            return
        found = session.exec(stmt.order_by(col(model.revision).desc()).limit(1)).first()
        if found is not None:
            candidates.append(found)
    start = max(candidates, key=lambda candidate: candidate.revision, default=None)
    if start is None:
        row.started_event_id = None
        faults.add("link-unproven")
    else:
        row.started_event_id = start.event_id
        # Same-provider-object proof is in service.py. Never inherit Pi labels
        # or overwrite an explicitly malformed provider, even from pending.
        if row.token_source == "service" and row.provider is None and "provider-invalid" not in faults:
            row.provider = start.provider
            if row.provider is not None:
                faults.discard("provider-unproven")
    row.fault_codes = _fault_text(faults)


def _same_projection(left: UsageObservation, right: UsageObservation) -> bool:
    def values(row: UsageObservation) -> dict[str, Any]:
        result = row.model_dump(exclude={"seq", "pending_at", "defer_reason"})
        for field in ("event_at", "occurred_at"):
            if result[field] is not None:
                result[field] = as_utc(result[field])
        return result
    return values(left) == values(right)


def _ordering_timeout(error: DBAPIError) -> bool:
    # No message parsing, exception stringification, or catch-all fallback.
    return getattr(error.orig, "pgcode", None) == "55P03"


def _append_final(session: Session, row: UsageCallRow, *, delete_pending: bool = False) -> _AppendOutcome:
    """One ordering statement; raw savepoint is closed by the OUTER commit.

    Caller holds the source Event row lock (or inserted that Event). Everything
    is flushed/prepared before SAVEPOINT. No ORM flush can be undone behind the
    unit of work's back by a raw ROLLBACK TO SAVEPOINT. No success-path RELEASE.
    """
    session.flush()
    postgres = session.get_bind().dialect.name == "postgresql"
    values = row.model_dump(exclude={"seq"})
    if postgres:
        statement = _POSTGRES_PENDING_DRAIN if delete_pending else _POSTGRES_ROW_INSERT
        params = {**values, "commit_order_lock": COMMIT_ORDER_LOCK}
        timeout = session.execute(_STATEMENT_TIMEOUT).scalar_one()
        if 0 < timeout <= 2000:
            raise RuntimeError("usage statement timeout incompatible")
    else:
        statement = _insert(session, UsageCallRow).values(**values).on_conflict_do_nothing(
            index_elements=["event_id", "revision"],
        ).returning(col(UsageCallRow.seq))
        params = {}
    pending_delete = delete(UsagePending).where(
        col(UsagePending.event_id) == row.event_id, col(UsagePending.revision) == row.revision,
    )
    final_lookup = select(UsageCallRow).where(
        UsageCallRow.event_id == row.event_id, UsageCallRow.revision == row.revision,
    )
    with session.no_autoflush:
        session.execute(_ORDERING_SAVEPOINT)
        if session.new or session.dirty or session.deleted:
            raise RuntimeError("usage ordering session not clean")
        if postgres:
            # AFTER savepoint: a timeout rollback restores BOTH previous settings.
            session.execute(_ORDERING_SETTINGS)
        try:
            seq = session.execute(statement, params).scalar_one_or_none()
        except DBAPIError as error:
            if not postgres or not _ordering_timeout(error):
                raise
            session.execute(_ORDERING_ROLLBACK)
            return _AppendOutcome("deferred")
        if seq is None:
            # A DELETE CTE runs even if ON CONFLICT inserts nothing. Compare before
            # committing its deletion: a different fact must leave pending intact.
            existing = session.exec(final_lookup).first()
            if existing is None or not _same_projection(existing, row):
                session.rollback()
                raise RuntimeError("usage observation conflict")
            seq = existing.seq
            status: Literal["inserted", "already-final"] = "already-final"
        else:
            status = "inserted"
        if delete_pending and not postgres:
            session.execute(pending_delete)
        return _AppendOutcome(status, seq)


def _queue_pending(session: Session, row: UsageCallRow) -> None:
    values = row.model_dump(exclude={"seq"})
    values["fault_codes"] = _fault_text(set(filter(None, row.fault_codes.split(","))) | {"ordering-deferred"})
    pending = UsagePending(**values)
    inserted = session.execute(_insert(session, UsagePending).values(
        **pending.model_dump(),
    ).on_conflict_do_nothing(index_elements=["event_id", "revision"]).returning(
        col(UsagePending.event_id),
    )).scalar_one_or_none()
    if inserted is None:
        existing = session.get(UsagePending, (row.event_id, row.revision))
        if existing is None or not _same_projection(existing, pending):
            session.rollback()
            raise RuntimeError("usage observation conflict")


def write_or_queue_row(session: Session, row: UsageCallRow) -> int | None:
    """Atomic capture with caller's Event; None means typed pending, NOT lost/zero.

    Caller inserted/locked the Event and must commit immediately after this call.
    Reconciliation must follow the same lock order. SQLite callers also hold the
    whole-transaction sqlite_transaction_lock through commit. No commit here.
    """
    row.instance = ensure_instance(session)
    _link_start(session, row)
    existing_pending = session.get(UsagePending, (row.event_id, row.revision))
    if existing_pending is not None:
        expected = UsageCallRow(**row.model_dump())
        expected.fault_codes = _fault_text(set(filter(None, row.fault_codes.split(","))) | {"ordering-deferred"})
        if not _same_projection(existing_pending, expected):
            session.rollback()
            raise RuntimeError("usage observation conflict")
        return None
    result = _append_final(session, row)
    if result.status == "deferred":
        _queue_pending(session, row)
        return None
    row.seq = result.seq
    return result.seq


def drain_pending_row(session: Session, event_id: str, revision: int) -> DrainOutcome:
    """Move ONE numeric observation, without Event.data; caller commits the result.

    A busy Event is skipped, never counted as drained. One source Event lock is
    always acquired before the ordering lock. No worker/cadence is enabled here.
    SQLite caller must hold sqlite_transaction_lock across this whole transaction.
    """
    locked = session.exec(select(Event.id).where(Event.id == event_id).with_for_update(skip_locked=True)).first()
    pending = session.get(UsagePending, (event_id, revision))
    if pending is None:
        return DrainOutcome("missing")
    if locked is None:
        exists = session.exec(select(Event.id).where(Event.id == event_id)).first()
        if exists is None:
            raise RuntimeError("usage pending event missing")
        return DrainOutcome("busy")
    if pending.instance != ensure_instance(session):
        raise RuntimeError("usage pending instance mismatch")
    row = UsageCallRow(**pending.model_dump(exclude={"pending_at", "defer_reason"}))
    result = _append_final(session, row, delete_pending=True)
    status: Literal["drained", "already-final", "deferred"] = (
        "drained" if result.status == "inserted" else result.status
    )
    return DrainOutcome(status, result.seq)


def projection_changed(before: UsageCallRow, after: UsageCallRow) -> bool:
    """Compare only pure projected values; content-only edits never create revisions."""
    return before.model_dump() != after.model_dump()


def next_revision(session: Session, event_id: str) -> int | None:
    """Next revision of an ALREADY projected event; legacy/fork copies stay unprojected.

    Caller holds the Event's row lock, so concurrent corrections cannot choose the
    same revision. Retry after an unknown commit compares the already-merged data.
    """
    revisions = select(UsageCallRow.revision).where(UsageCallRow.event_id == event_id).union_all(
        select(UsagePending.revision).where(UsagePending.event_id == event_id),
    ).subquery()
    latest = session.execute(select(func.max(revisions.c.revision))).scalar_one()
    return latest + 1 if latest is not None else None
