"""Inert epoch phases, private scalar identity and pre-snapshot PostgreSQL fence.

No caller here initializes a reader, allocates a cross-resource epoch, writes a
host receipt, changes source identity or opens admission. Only the explicit host
transaction exposes append helpers; READY alone is not release authority.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import (
    DDL,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    String,
    Table,
    UniqueConstraint,
    event,
    func,
    select,
    text,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlmodel import SQLModel, col

from temper_ai.observability.usage_feed_cursor import (
    MAX_EPOCH,
    CursorError,
    FinalRowAnchor,
    RowCursor,
    TargetCursor,
    canonical_uuid,
    decode_row_cursor,
    decode_target_cursor,
)
from temper_ai.observability.usage_rows import UsageCallRow, UsageSourceInstance

IDENTITY_BASIS = "postgresql-primary-insert"
HOST_ACTOR = "authorized-host"
Reason = Literal["activation", "restore", "migration"]
Phase = Literal["PREPARED", "READY"]
EPOCH_TABLE = "usage_feed_epochs"
READER_LOCK_SQL = "LOCK TABLE usage_feed_epochs IN ACCESS SHARE MODE"
HOST_LOCK_SQL = "LOCK TABLE usage_feed_epochs IN ACCESS EXCLUSIVE MODE"
_FENCE_ADMISSION = object()

# Additive schema only. create_all never replaces an existing table or its data.
EPOCHS = Table(
    EPOCH_TABLE, SQLModel.metadata,
    Column("epoch", BigInteger, primary_key=True, autoincrement=False),
    Column("phase", String(8), primary_key=True),
    Column("transition_id", String(36), nullable=False),
    Column("source_instance", String(36), nullable=False),
    Column("system_identifier", String(20), nullable=False),
    Column("database_oid", BigInteger, nullable=False),
    Column("insert_timeline", BigInteger, nullable=False),
    Column("basis", String(32), nullable=False),
    Column("actor", String(24), nullable=False),
    Column("reason", String(16), nullable=False),
    Column("target_seq", BigInteger),
    Column("target_event_id", String(128)),
    Column("target_revision", BigInteger),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()),
    CheckConstraint(f"epoch BETWEEN 1 AND {MAX_EPOCH}", name="usage_epoch_range"),
    CheckConstraint("phase IN ('PREPARED','READY')", name="usage_epoch_phase"),
    CheckConstraint("length(transition_id) = 36 AND length(source_instance) = 36", name="usage_epoch_ids"),
    CheckConstraint("length(system_identifier) BETWEEN 1 AND 20", name="usage_epoch_system"),
    CheckConstraint("database_oid BETWEEN 1 AND 4294967295 AND insert_timeline BETWEEN 1 AND 4294967295",
                    name="usage_epoch_identity_range"),
    CheckConstraint("basis = 'postgresql-primary-insert' AND actor = 'authorized-host'",
                    name="usage_epoch_basis_actor"),
    CheckConstraint("reason IN ('activation','restore','migration')", name="usage_epoch_reason"),
    CheckConstraint("(target_seq IS NULL AND target_event_id IS NULL AND target_revision IS NULL) OR "
                    "(target_seq IS NOT NULL AND target_seq > 0 AND target_event_id IS NOT NULL "
                    "AND length(target_event_id) BETWEEN 1 AND 128 AND target_revision IS NOT NULL "
                    "AND target_revision BETWEEN 0 AND 2147483647)", name="usage_epoch_target"),
    UniqueConstraint("transition_id", "phase", name="usage_epoch_transition_phase"),
)

# The transaction-local marker is an accidental-application-write guard, NOT an
# authorization boundary against DB owners/superusers/same-UID code. Deployment
# of a separately authorized least-privilege reader/host role is a later task.
_OPERATION_COLUMNS = (
    "transition_id", "source_instance", "system_identifier", "database_oid", "insert_timeline",
    "basis", "actor", "reason", "target_seq", "target_event_id", "target_revision",
)
_NEW_OPERATION = ", ".join(f"NEW.{name}" for name in _OPERATION_COLUMNS)
_PREPARED_OPERATION = ", ".join(f"p.{name}" for name in _OPERATION_COLUMNS)
_POSTGRES_GUARD = DDL(f"""
CREATE FUNCTION usage_epoch_append_guard() RETURNS trigger LANGUAGE plpgsql AS $guard$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'usage-epoch-append-only' USING ERRCODE = '23514';
    END IF;
    IF current_setting('temper.usage_epoch_host', true) IS DISTINCT FROM 'append-v1' THEN
        RAISE EXCEPTION 'usage-epoch-host-only' USING ERRCODE = '23514';
    END IF;
    IF NEW.source_instance !~ '^[0-9a-f]{{8}}(-[0-9a-f]{{4}}){{3}}-[0-9a-f]{{12}}$'
       OR NEW.transition_id !~ '^[0-9a-f]{{8}}(-[0-9a-f]{{4}}){{3}}-[0-9a-f]{{12}}$'
       OR NEW.system_identifier !~ '^[1-9][0-9]{{0,19}}$'
       OR NEW.system_identifier::numeric > 18446744073709551615
       OR (NEW.target_event_id IS NOT NULL AND NEW.target_event_id !~ '^[A-Za-z0-9._:\\-]{{1,128}}$')
       OR NOT EXISTS (SELECT 1 FROM usage_source_instance s WHERE s.id = 1 AND s.instance = NEW.source_instance)
    THEN
        RAISE EXCEPTION 'usage-epoch-operation-invalid' USING ERRCODE = '23514';
    END IF;
    IF NEW.phase = 'PREPARED' THEN
        IF EXISTS (SELECT 1 FROM usage_feed_epochs p WHERE p.epoch >= NEW.epoch OR p.transition_id = NEW.transition_id) THEN
            RAISE EXCEPTION 'usage-epoch-operation-conflict' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.phase = 'READY' THEN
        IF EXISTS (SELECT 1 FROM usage_feed_epochs p WHERE p.epoch > NEW.epoch)
           OR NOT EXISTS (SELECT 1 FROM usage_feed_epochs p WHERE p.epoch = NEW.epoch AND p.phase = 'PREPARED'
                          AND ROW({_PREPARED_OPERATION}) IS NOT DISTINCT FROM ROW({_NEW_OPERATION})) THEN
            RAISE EXCEPTION 'usage-epoch-operation-conflict' USING ERRCODE = '23514';
        END IF;
    END IF;
    NEW.created_at := clock_timestamp();
    RETURN NEW;
END
$guard$;
CREATE TRIGGER usage_epoch_append_only BEFORE INSERT OR UPDATE OR DELETE ON usage_feed_epochs
FOR EACH ROW EXECUTE FUNCTION usage_epoch_append_guard();
CREATE TRIGGER usage_epoch_no_rewrite BEFORE UPDATE OR DELETE ON usage_feed_epochs
FOR EACH STATEMENT EXECUTE FUNCTION usage_epoch_append_guard();
""")
event.listen(EPOCHS, "after_create", _POSTGRES_GUARD.execute_if(dialect="postgresql"))
for _verb in ("INSERT", "UPDATE", "DELETE"):
    event.listen(EPOCHS, "after_create", DDL(
        f"CREATE TRIGGER usage_epoch_no_{_verb.lower()} BEFORE {_verb} ON usage_feed_epochs "
        "BEGIN SELECT RAISE(ABORT, 'usage-epoch-unsupported'); END"
    ).execute_if(dialect="sqlite"))


class EpochError(RuntimeError):
    """Fixed codes/changed field NAMES only; never stringify driver/input values."""

    def __init__(self, code: str, *, changed: tuple[str, ...] = ()) -> None:
        self.code = code
        self.changed = changed
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class PrivateIdentity:
    system_identifier: str
    database_oid: int
    insert_timeline: int

    def __post_init__(self) -> None:
        if (type(self.system_identifier) is not str
                or not re.fullmatch(r"[1-9][0-9]{0,19}", self.system_identifier, re.ASCII)
                or int(self.system_identifier) > 2**64 - 1
                or type(self.database_oid) is not int or not 1 <= self.database_oid <= 2**32 - 1
                or type(self.insert_timeline) is not int or not 1 <= self.insert_timeline <= 2**32 - 1):
            raise EpochError("identity-unreadable")


def identity_changes(expected: PrivateIdentity, live: PrivateIdentity) -> tuple[str, ...]:
    return tuple(name for name, left, right in (
        ("system", expected.system_identifier, live.system_identifier),
        ("database", expected.database_oid, live.database_oid),
        ("timeline", expected.insert_timeline, live.insert_timeline),
    ) if left != right)


def probe_primary_identity(connection: Connection) -> PrivateIdentity:
    """Only primary + required scalars, no grant, fallback, control file or log.

    The WAL filename is the CURRENT timeline, not checkpoint timeline. This uses
    the accepted paper's pg_current_wal_lsn expression, never pg_control_checkpoint.
    """
    try:
        if connection.execute(text("SELECT pg_is_in_recovery()")).scalar_one() is not False:
            raise EpochError("not-primary")
        row = connection.execute(text(
            "SELECT c.system_identifier::text AS system_identifier, "
            "(SELECT d.oid::bigint FROM pg_database d WHERE d.datname = current_database()) AS database_oid, "
            "left(pg_walfile_name(pg_current_wal_lsn()), 8) AS timeline_hex "
            "FROM pg_control_system() c"
        )).one()
        if type(row.timeline_hex) is not str or not re.fullmatch(r"[0-9A-F]{8}", row.timeline_hex, re.ASCII):
            raise EpochError("identity-unreadable")
        return PrivateIdentity(row.system_identifier, row.database_oid, int(row.timeline_hex, 16))
    except DBAPIError as error:
        code = getattr(error.orig, "pgcode", None)
        raise EpochError("epoch-timeout" if code in ("55P03", "57014") else "identity-unreadable") from None
    except (SQLAlchemyError, AttributeError, TypeError, ValueError):
        raise EpochError("identity-unreadable") from None


@dataclass(frozen=True)
class EpochOperation:
    epoch: int
    transition_id: str
    source_instance: str
    identity: PrivateIdentity = field(repr=False)
    reason: Reason
    target: FinalRowAnchor | None
    basis: str = IDENTITY_BASIS
    actor: str = HOST_ACTOR

    def __post_init__(self) -> None:
        try:
            canonical_uuid(self.transition_id)
            canonical_uuid(self.source_instance)
            if (type(self.epoch) is not int or not 1 <= self.epoch <= MAX_EPOCH
                    or type(self.identity) is not PrivateIdentity or type(self.reason) is not str
                    or self.reason not in ("activation", "restore", "migration")
                    or self.basis != IDENTITY_BASIS or self.actor != HOST_ACTOR
                    or (self.target is not None and type(self.target) is not FinalRowAnchor)):
                raise CursorError()
        except CursorError:
            raise EpochError("epoch-operation-invalid") from None

    def values(self, phase: Phase) -> dict[str, Any]:
        if phase not in ("PREPARED", "READY"):
            raise EpochError("epoch-operation-invalid")
        return dict(epoch=self.epoch, phase=phase, transition_id=self.transition_id,
                    source_instance=self.source_instance, system_identifier=self.identity.system_identifier,
                    database_oid=self.identity.database_oid, insert_timeline=self.identity.insert_timeline,
                    basis=self.basis, actor=self.actor, reason=self.reason,
                    target_seq=self.target.seq if self.target else None,
                    target_event_id=self.target.event_id if self.target else None,
                    target_revision=self.target.revision if self.target else None)


def _operation(row: Mapping[str, Any]) -> EpochOperation:
    try:
        target = (None if all(row[name] is None for name in ("target_seq", "target_event_id", "target_revision"))
                  else FinalRowAnchor(row["target_seq"], row["target_event_id"], row["target_revision"]))
        return EpochOperation(row["epoch"], row["transition_id"], row["source_instance"],
                              PrivateIdentity(row["system_identifier"], row["database_oid"], row["insert_timeline"]),
                              row["reason"], target, row["basis"], row["actor"])
    except (KeyError, CursorError, EpochError):
        raise EpochError("epoch-transition") from None


class EpochFence:
    """Only made by fresh owned transaction helpers; cannot reuse an RR snapshot.

    Connection access is private core/route/host plumbing, not a general app API.
    The caller must buffer results and finish this context successfully BEFORE
    releasing any response. The route still owns its full request deadline.
    """

    def __init__(self, connection: Connection, host: bool, deadline: float, *, _admission: object = None) -> None:
        if _admission is not _FENCE_ADMISSION:
            raise EpochError("epoch-fence-unadmitted")
        self.connection = connection
        self.host = host
        self.deadline = deadline
        self.active = True
        self._identity: PrivateIdentity | None = None

    def require(self, *, host: bool = False) -> None:
        if not self.active or (host and not self.host):
            raise EpochError("epoch-host-only" if host else "epoch-fence-closed")
        if time.monotonic() >= self.deadline:
            raise EpochError("epoch-timeout")

    def recheck_identity(self) -> None:
        self.require()
        if self._identity is not None:
            changed = identity_changes(self._identity, probe_primary_identity(self.connection))
            if changed:
                raise EpochError("identity-changed", changed=changed)
        self.require()


@contextmanager
def _fenced_transaction(engine: Engine, *, host: bool, deadline: float | None) -> Iterator[EpochFence]:
    if engine.dialect.name != "postgresql":
        raise EpochError("epoch-unsupported")
    end = min(deadline, time.monotonic() + 3.0) if deadline is not None else time.monotonic() + 3.0
    fence = None
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
            remaining_ms = min(2000, int((end - time.monotonic()) * 1000))
            if remaining_ms < 1:
                raise EpochError("epoch-timeout")
            connection.exec_driver_sql("SET TRANSACTION READ WRITE" if host else "SET TRANSACTION READ ONLY")
            connection.exec_driver_sql(f"SET LOCAL statement_timeout = {remaining_ms}")
            connection.exec_driver_sql(f"SET LOCAL lock_timeout = {remaining_ms}")
            connection.exec_driver_sql("SET LOCAL idle_in_transaction_session_timeout = '3s'")
            if host:
                connection.exec_driver_sql("SET LOCAL temper.usage_epoch_host = 'append-v1'")
            # LOCK, unlike a SELECT (including SELECT advisory_lock), creates no
            # RR data snapshot. Do NOT move any probe/source query above it.
            connection.exec_driver_sql(HOST_LOCK_SQL if host else READER_LOCK_SQL)
            fence = EpochFence(connection, host, end, _admission=_FENCE_ADMISSION)
            yield fence
            fence.recheck_identity()
    except DBAPIError as error:
        code = getattr(error.orig, "pgcode", None)
        raise EpochError("epoch-timeout" if code in ("55P03", "57014") else "epoch-unavailable") from None
    finally:
        if fence is not None:
            fence.active = False


def reader_epoch_snapshot(engine: Engine, *, deadline: float | None = None):
    """Fresh READ ONLY RR; ACCESS SHARE before any data/identity SELECT."""
    return _fenced_transaction(engine, host=False, deadline=deadline)


def host_epoch_transaction(engine: Engine, *, deadline: float | None = None):
    """Fresh host-only RR; ACCESS EXCLUSIVE before any data/identity SELECT.

    Caller owes prior authorization, synced reservation, custody, OFF and durable
    quiescence. No such authority is inferred, performed or represented here.
    """
    return _fenced_transaction(engine, host=True, deadline=deadline)


def read_source_instance(fence: EpochFence) -> str:
    fence.require()
    values = fence.connection.execute(select(col(UsageSourceInstance.instance))).scalars().all()
    try:
        if len(values) != 1:
            raise CursorError()
        return canonical_uuid(values[0])
    except CursorError:
        raise EpochError("epoch-unavailable") from None


def greatest_issued_epoch(fence: EpochFence) -> int:
    """ALL phases, never max(READY). Zero is private absence, not a row anchor."""
    fence.require()
    return fence.connection.execute(select(func.max(EPOCHS.c.epoch))).scalar_one() or 0


def _phases(fence: EpochFence, epoch: int) -> dict[str, EpochOperation]:
    fence.require()
    rows = fence.connection.execute(select(EPOCHS).where(EPOCHS.c.epoch == epoch)).mappings().all()
    if any(row["phase"] not in ("PREPARED", "READY") for row in rows):
        raise EpochError("epoch-transition")
    return {row["phase"]: _operation(dict(row)) for row in rows}


def read_current_ready_epoch(fence: EpochFence) -> EpochOperation:
    fence.require()
    live = probe_primary_identity(fence.connection)
    source = read_source_instance(fence)
    epoch = greatest_issued_epoch(fence)
    if not epoch:
        raise EpochError("reader-uninitialized")
    phases = _phases(fence, epoch)
    prepared, ready = phases.get("PREPARED"), phases.get("READY")
    if prepared is None or ready is None or prepared != ready:
        raise EpochError("epoch-transition")
    if ready.source_instance != source:
        raise EpochError("instance-changed")
    changed = identity_changes(ready.identity, live)
    if changed:
        raise EpochError("identity-changed", changed=changed)
    fence._identity = live
    return ready


def capture_final_target(fence: EpochFence, source_instance: str) -> FinalRowAnchor | None:
    fence.require(host=True)
    # An actual FINAL tuple, never sequence last_value/nextval or pending.
    row = fence.connection.execute(select(col(UsageCallRow.seq), col(UsageCallRow.event_id), col(UsageCallRow.revision),
                                           col(UsageCallRow.instance)).order_by(col(UsageCallRow.seq).desc()).limit(1)).first()
    if row is None:
        return None
    if row.instance != source_instance:
        raise EpochError("instance-changed")
    try:
        return FinalRowAnchor(row.seq, row.event_id, row.revision)
    except CursorError:
        raise EpochError("anchor-changed") from None


def append_prepared_epoch(fence: EpochFence, *, epoch: int, transition_id: str, source_instance: str,
                          expected_identity: PrivateIdentity, expected_db_epoch: int, reason: Reason) -> EpochOperation:
    """Host append only; epoch allocation/history validation belong to the host.

    No retry becomes a new init. Recovery reads the exact existing operation;
    this initial append refuses an occupied/stale allocation.
    """
    fence.require(host=True)
    live = probe_primary_identity(fence.connection)
    changed = identity_changes(expected_identity, live)
    if changed:
        raise EpochError("identity-changed", changed=changed)
    if read_source_instance(fence) != source_instance:
        raise EpochError("instance-changed")
    current = greatest_issued_epoch(fence)
    if type(expected_db_epoch) is not int or expected_db_epoch != current or type(epoch) is not int or epoch <= current:
        raise EpochError("epoch-operation-conflict")
    operation = EpochOperation(epoch, transition_id, source_instance, live, reason,
                               capture_final_target(fence, source_instance))
    fence.connection.execute(EPOCHS.insert().values(**operation.values("PREPARED")))
    fence._identity = live
    return operation


def append_ready_epoch(fence: EpochFence, prepared: EpochOperation) -> EpochOperation:
    """Append exact READY, only AFTER caller's durable matching host receipt.

    This core cannot attest an outside-mount receipt or publish host COMPLETE.
    Matching same-operation READY is an idempotent read, not fresh issuance.
    """
    fence.require(host=True)
    if type(prepared) is not EpochOperation or greatest_issued_epoch(fence) != prepared.epoch:
        raise EpochError("epoch-operation-conflict")
    if read_source_instance(fence) != prepared.source_instance:
        raise EpochError("instance-changed")
    live = probe_primary_identity(fence.connection)
    changed = identity_changes(prepared.identity, live)
    if changed:
        raise EpochError("identity-changed", changed=changed)
    phases = _phases(fence, prepared.epoch)
    if phases.get("PREPARED") != prepared or ("READY" in phases and phases["READY"] != prepared):
        raise EpochError("epoch-operation-conflict")
    validate_fixed_target(fence, prepared)
    if "READY" not in phases:
        fence.connection.execute(EPOCHS.insert().values(**prepared.values("READY")))
    fence._identity = live
    return prepared


def _validate_scope(operation: EpochOperation, source_instance: str, epoch: int) -> None:
    if source_instance != operation.source_instance:
        raise EpochError("instance-changed")
    if epoch != operation.epoch:
        raise EpochError("epoch-changed")


def _validate_real_anchor(fence: EpochFence, operation: EpochOperation, anchor: FinalRowAnchor) -> None:
    row = fence.connection.execute(select(col(UsageCallRow.event_id), col(UsageCallRow.revision),
                                           col(UsageCallRow.instance)).where(col(UsageCallRow.seq) == anchor.seq)).first()
    if row is None or (row.event_id, row.revision, row.instance) != (
            anchor.event_id, anchor.revision, operation.source_instance):
        raise EpochError("anchor-changed")


def validate_fixed_target(fence: EpochFence, operation: EpochOperation) -> None:
    """Validate retained T; EMPTY is not absence of epoch or fabricated row zero."""
    fence.require()
    if operation.target is not None:
        _validate_real_anchor(fence, operation, operation.target)


def validate_target_cursor(fence: EpochFence, operation: EpochOperation, token: str | None) -> None:
    """Exact authorized T, including explicit null for EMPTY, never a moving max."""
    validate_fixed_target(fence, operation)
    if token is None:
        if operation.target is not None:
            raise EpochError("anchor-changed")
        return
    target: TargetCursor = decode_target_cursor(token)
    _validate_scope(operation, target.source_instance, target.epoch)
    if target.anchor != operation.target:
        raise EpochError("anchor-changed")


def validate_row_cursor(fence: EpochFence, operation: EpochOperation, token: str) -> RowCursor:
    """Real current-source/epoch FINAL anchor, not issuance/consumption proof."""
    fence.require()
    cursor = decode_row_cursor(token)
    _validate_scope(operation, cursor.source_instance, cursor.epoch)
    visible_max = fence.connection.execute(select(func.max(col(UsageCallRow.seq)))).scalar_one()
    if visible_max is None or cursor.anchor.seq > visible_max:
        raise EpochError("seq-regression")
    _validate_real_anchor(fence, operation, cursor.anchor)
    return cursor
