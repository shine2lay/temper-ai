"""Fixed core stages against throwaway PG, never a Temper server/live DB.

SQLite runs schema/codec/refusal cases, not fictitious reset-safety parity.
The observability folder already belongs to tests/pgtier.py's Postgres tier.
"""

from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.pool import NullPool

from temper_ai.database import get_database, get_session
from temper_ai.observability import recorder
from temper_ai.observability import usage_feed_epochs as core
from temper_ai.observability import usage_rows as source_writer
from temper_ai.observability.usage_feed_cursor import (
    MAX_EPOCH,
    CursorError,
    FinalRowAnchor,
    InitializedNoProgress,
    RowCursor,
    TargetCursor,
    encode_row_cursor,
    encode_target_cursor,
)
from temper_ai.observability.usage_rows import (
    UsageCallRow,
    UsagePending,
    ensure_instance,
)
from temper_ai.shared.clock import utcnow

TRANSITION = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
CANARY = core.PrivateIdentity("18446744073709551511", 4294967201, 4294967202)


def engine():
    return get_database().engine


def pg_or_fixed_refusal():
    if engine().dialect.name == "postgresql":
        return True
    for helper in (core.reader_epoch_snapshot, core.host_epoch_transaction):
        with pytest.raises(core.EpochError, match="^epoch-unsupported$"):
            with helper(engine()):
                pytest.fail("SQLite must never enter a reset-safe transaction")
    return False


@pytest.fixture(autouse=True)
def isolated_source_ordering_key(monkeypatch, _test_db):
    # Same worker isolation as #125's source tests; advisory keys are DB-wide.
    if engine().dialect.name == "postgresql":
        with engine().connect() as connection:
            schema = connection.execute(text("SELECT current_schema()")).scalar_one()
        key = int.from_bytes(hashlib.sha256(schema.encode("ascii")).digest()[:8], "big", signed=True)
        monkeypatch.setattr(source_writer, "COMMIT_ORDER_LOCK", key)


def source():
    with get_session() as session:
        return ensure_instance(session)


def record_numbers():
    # #125's actual Event+FINAL writer, numeric fixture only, no provider.
    recorder.record("llm.call.completed", data={"prompt_tokens": 7, "completion_tokens": 3},
                    execution_id=TRANSITION)
    with get_session() as session:
        row = session.execute(select(UsageCallRow).order_by(UsageCallRow.seq.desc()).limit(1)).scalar_one()
        return FinalRowAnchor(row.seq, row.event_id, row.revision)


def prepare(epoch=1, transition=TRANSITION, reason="activation"):
    source()
    with core.host_epoch_transaction(engine()) as host:
        operation = core.append_prepared_epoch(host, epoch=epoch, transition_id=transition,
            source_instance=core.read_source_instance(host), expected_identity=core.probe_primary_identity(host.connection),
            expected_db_epoch=core.greatest_issued_epoch(host), reason=reason)
    return operation


def publish(epoch=1, transition=TRANSITION):
    operation = prepare(epoch, transition)
    # A fixed fixture stands in for the caller's matching durable host receipt.
    # This is not the host journal protocol or permission to operate one.
    with core.host_epoch_transaction(engine()) as host:
        assert core.append_ready_epoch(host, operation) == operation
    return operation


def test_00_combined_epoch_identity_phase_anchor_codec_readonly_happy_path():
    if not pg_or_fixed_refusal():
        return
    first, last = record_numbers(), record_numbers()
    operation = publish()
    assert operation.target == last and first.seq < last.seq
    with core.reader_epoch_snapshot(engine()) as reader:
        actual = core.read_current_ready_epoch(reader)
        assert actual == operation
        assert reader.connection.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        assert reader.connection.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read"
        actual_returned = reader.connection.execute(select(UsageCallRow.seq, UsageCallRow.event_id, UsageCallRow.revision)
            .order_by(UsageCallRow.seq).limit(1)).one()
        last_returned = FinalRowAnchor(*actual_returned)
        row_token = encode_row_cursor(RowCursor(actual.source_instance, actual.epoch, last_returned))
        target_token = encode_target_cursor(TargetCursor(actual.source_instance, actual.epoch, actual.target))
        assert core.validate_row_cursor(reader, actual, row_token).anchor == first
        assert core.validate_row_cursor(reader, actual, row_token).anchor != actual.target
        core.validate_fixed_target(reader, actual)
        core.validate_target_cursor(reader, actual, target_token)
        assert core.identity_changes(actual.identity, core.probe_primary_identity(reader.connection)) == ()
    with engine().connect() as connection:
        phases = connection.execute(select(core.EPOCHS.c.phase, core.EPOCHS.c.created_at)
                                    .order_by(core.EPOCHS.c.phase)).all()
        assert [phase for phase, _ in phases] == ["PREPARED", "READY"]
        assert all(created is not None and created.tzinfo is not None for _, created in phases)
    with pytest.raises(core.EpochError, match="^epoch-fence-closed$"):
        core.read_current_ready_epoch(reader)


def assert_newer_prepared_blocks():
    with pytest.raises(core.EpochError, match="^epoch-transition$"):
        with core.reader_epoch_snapshot(engine()) as reader:
            core.read_current_ready_epoch(reader)


def test_newest_any_phase_blocks_old_ready_and_guard_bite(monkeypatch):
    if not pg_or_fixed_refusal():
        return
    publish()
    prepare(2, OTHER, "restore")
    assert_newer_prepared_blocks()
    with core.reader_epoch_snapshot(engine()) as reader:
        assert core.greatest_issued_epoch(reader) == 2
    # Plant max(READY) fallback. The SAME expected-state assertion must fail.
    with monkeypatch.context() as mutation:
        mutation.setattr(core, "greatest_issued_epoch", lambda fence: 1)
        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            assert_newer_prepared_blocks()


@pytest.mark.parametrize("change", [{"transition_id": OTHER}, {"source_instance": OTHER},
    {"reason": "migration"}, {"identity": CANARY}, {"target": FinalRowAnchor(3, "not-the-target", 0)},
    {"epoch": 2}])
def test_ready_requires_exact_prepared_operation(change):
    if not pg_or_fixed_refusal():
        return
    operation = prepare()
    with pytest.raises(core.EpochError):
        with core.host_epoch_transaction(engine()) as host:
            core.append_ready_epoch(host, replace(operation, **change))
    with engine().connect() as connection:
        assert connection.execute(select(func.count()).select_from(core.EPOCHS)).scalar_one() == 1


@pytest.mark.parametrize("field,value", [("transition_id", OTHER), ("source_instance", OTHER),
    ("system_identifier", "111"), ("database_oid", 77), ("insert_timeline", 77), ("reason", "migration"),
    ("target_seq", 1), ("target_event_id", "different"), ("target_revision", 1)])
def test_database_itself_rejects_mixed_phase_metadata(field, value):
    if not pg_or_fixed_refusal():
        return
    operation = prepare()
    with pytest.raises(core.EpochError, match="^epoch-unavailable$"):
        with core.host_epoch_transaction(engine()) as host:
            values = operation.values("READY")
            values[field] = value
            host.connection.execute(core.EPOCHS.insert().values(**values))


@pytest.mark.parametrize("statement", ["UPDATE usage_feed_epochs SET reason = 'migration'",
                                      "DELETE FROM usage_feed_epochs"])
@pytest.mark.parametrize("populated", [False, True])
def test_database_rejects_application_update_and_delete(statement, populated):
    if not pg_or_fixed_refusal():
        # Controlled seed bypasses INSERT only, then restores it BEFORE testing
        # the actual UPDATE/DELETE guard. This is not SQLite protocol support.
        if populated:
            values = core.EpochOperation(1, TRANSITION, OTHER, CANARY, "activation", None).values("PREPARED")
            with engine().begin() as connection:
                insert_ddl = connection.execute(text("SELECT sql FROM sqlite_master WHERE type = 'trigger' "
                    "AND name = 'usage_epoch_no_insert'")).scalar_one()
                connection.exec_driver_sql("DROP TRIGGER usage_epoch_no_insert")
                connection.execute(core.EPOCHS.insert().values(**values))
                connection.exec_driver_sql(insert_ddl)
        with engine().connect() as connection:
            assert connection.execute(select(func.count()).select_from(core.EPOCHS)).scalar_one() == int(populated)
        if populated:
            with pytest.raises(IntegrityError, match="usage-epoch-unsupported"):
                with engine().begin() as connection:
                    connection.execute(text(statement))
        else:
            # SQLite has row triggers, not PG's zero-row statement trigger.
            # No row is changed; both public protocol contexts already refused.
            with engine().begin() as connection:
                assert connection.execute(text(statement)).rowcount == 0
        return
    if populated:
        publish()
    with pytest.raises(IntegrityError, match="usage-epoch-append-only"):
        with engine().begin() as connection:
            connection.execute(text(statement))
    # Host is append-only too; it has no privileged reset/update shortcut.
    with pytest.raises(core.EpochError, match="^epoch-unavailable$"):
        with core.host_epoch_transaction(engine()) as host:
            host.connection.execute(text(statement))


def test_application_insert_is_not_host_and_reader_is_read_only():
    if not pg_or_fixed_refusal():
        # Valid values, no seed/trigger lookup: missing registrations must fail
        # at this actual INSERT assertion, not poison another test's setup.
        values = core.EpochOperation(1, TRANSITION, OTHER, CANARY, "activation", None).values("PREPARED")
        with engine().connect() as connection:
            assert connection.execute(select(func.count()).select_from(core.EPOCHS)).scalar_one() == 0
        with pytest.raises(IntegrityError, match="usage-epoch-unsupported"):
            with engine().begin() as connection:
                connection.execute(core.EPOCHS.insert().values(**values))
        with engine().connect() as connection:
            assert connection.execute(select(func.count()).select_from(core.EPOCHS)).scalar_one() == 0
        return
    operation = prepare()
    with pytest.raises(IntegrityError, match="usage-epoch-host-only"):
        with engine().begin() as connection:
            connection.execute(core.EPOCHS.insert().values(**operation.values("READY")))
    with core.reader_epoch_snapshot(engine()) as reader:
        with pytest.raises(core.EpochError, match="^epoch-host-only$"):
            core.append_ready_epoch(reader, operation)
    with pytest.raises(core.EpochError, match="^epoch-unavailable$"):
        with core.reader_epoch_snapshot(engine()) as reader:
            reader.connection.execute(text("UPDATE usage_source_instance SET instance = instance"))


def test_ready_idempotent_same_operation_but_newer_prepared_prevents_old_recovery():
    if not pg_or_fixed_refusal():
        return
    operation = publish()
    with core.host_epoch_transaction(engine()) as host:
        core.append_ready_epoch(host, operation)
    prepare(2, OTHER, "restore")
    with pytest.raises(core.EpochError, match="^epoch-operation-conflict$"):
        with core.host_epoch_transaction(engine()) as host:
            core.append_ready_epoch(host, operation)
    with pytest.raises(core.EpochError, match="^epoch-operation-conflict$"):
        prepare(1, TRANSITION)


def test_no_epoch_is_uninitialized_not_empty_target_or_automatic_initialization():
    before = source()
    if pg_or_fixed_refusal():
        with pytest.raises(core.EpochError, match="^reader-uninitialized$"):
            with core.reader_epoch_snapshot(engine()) as reader:
                core.read_current_ready_epoch(reader)
    assert source() == before
    with engine().connect() as connection:
        assert connection.execute(select(func.count()).select_from(core.EPOCHS)).scalar_one() == 0


def test_empty_target_null_start_and_later_final_are_not_fabricated_progress():
    if not pg_or_fixed_refusal():
        return
    operation = publish()
    assert operation.target is None
    start = InitializedNoProgress(operation.source_instance, operation.epoch)
    with core.reader_epoch_snapshot(engine()) as reader:
        actual = core.read_current_ready_epoch(reader)
        core.validate_target_cursor(reader, actual, None)
        with pytest.raises(CursorError):
            core.validate_row_cursor(reader, actual, None)
        with pytest.raises(core.EpochError, match="^seq-regression$"):
            core.validate_row_cursor(reader, actual, encode_row_cursor(RowCursor(start.source_instance, start.epoch,
                FinalRowAnchor(1, "not-a-row", 0))))
    later = record_numbers()
    with core.reader_epoch_snapshot(engine()) as reader:
        actual = core.read_current_ready_epoch(reader)
        assert actual.target is None
        core.validate_target_cursor(reader, actual, None)
        token = encode_row_cursor(RowCursor(start.source_instance, start.epoch, later))
        assert core.validate_row_cursor(reader, actual, token).anchor == later
        with pytest.raises(core.EpochError, match="^anchor-changed$"):
            core.validate_target_cursor(reader, actual, encode_target_cursor(TargetCursor(start.source_instance,
                start.epoch, later)))


def test_actual_final_target_not_sequence_highwater_pending_or_moving_max():
    if not pg_or_fixed_refusal():
        return
    last = record_numbers()
    with engine().begin() as connection:
        connection.execute(text("SELECT setval(pg_get_serial_sequence('usage_call_rows','seq'), 10000, true)"))
        # An actual pending projection, with no FINAL seq, cannot become T.
        values = connection.execute(select(UsageCallRow.__table__).where(UsageCallRow.seq == last.seq)).mappings().one()
        pending = {name: value for name, value in values.items() if name != "seq"}
        pending.update(event_id="pending-not-final", defer_reason="ordering-lock-timeout", pending_at=values["event_at"])
        connection.execute(UsagePending.__table__.insert().values(**pending))
    operation = publish()
    assert operation.target == last
    later = record_numbers()
    assert later.seq > 10000
    with core.reader_epoch_snapshot(engine()) as reader:
        actual = core.read_current_ready_epoch(reader)
        assert actual.target == last
        core.validate_fixed_target(reader, actual)
        with pytest.raises(core.EpochError, match="^anchor-changed$"):
            core.validate_target_cursor(reader, actual, encode_target_cursor(TargetCursor(actual.source_instance,
                actual.epoch, later)))
        with pytest.raises(core.EpochError, match="^anchor-changed$"):
            core.validate_target_cursor(reader, actual, None)
        with pytest.raises(core.EpochError, match="^seq-regression$"):
            core.validate_row_cursor(reader, actual, encode_row_cursor(RowCursor(actual.source_instance,
                actual.epoch, FinalRowAnchor(later.seq + 1, "sequence-only", 0))))


@pytest.mark.parametrize("kind,expected", [("source", "instance-changed"), ("epoch", "epoch-changed"),
    ("event", "anchor-changed"), ("revision", "anchor-changed"), ("instance", "anchor-changed"),
    ("missing", "anchor-changed"),
    ("highwater", "seq-regression"), ("target-domain", "cursor")])
def test_row_scope_and_real_exact_tuple(kind, expected):
    if not pg_or_fixed_refusal():
        return
    first, last = record_numbers(), record_numbers()
    operation = publish()
    anchor = first
    token_source, token_epoch = operation.source_instance, operation.epoch
    if kind == "source":
        token_source = OTHER
    elif kind == "epoch":
        token_epoch += 1
    elif kind == "event":
        anchor = replace(first, event_id="wrong-event")
    elif kind == "revision":
        anchor = replace(first, revision=first.revision + 1)
    elif kind == "instance":
        with engine().begin() as connection:
            connection.execute(UsageCallRow.__table__.update().where(UsageCallRow.seq == first.seq).values(instance=OTHER))
    elif kind == "missing":
        with engine().begin() as connection:
            connection.execute(UsageCallRow.__table__.delete().where(UsageCallRow.seq == first.seq))
    elif kind == "highwater":
        anchor = replace(first, seq=last.seq + 1)
    token = (encode_target_cursor(TargetCursor(token_source, token_epoch, anchor)) if kind == "target-domain"
             else encode_row_cursor(RowCursor(token_source, token_epoch, anchor)))
    with core.reader_epoch_snapshot(engine()) as reader:
        with pytest.raises(CursorError if expected == "cursor" else core.EpochError,
                           match="^usage-cursor-invalid$" if expected == "cursor" else f"^{expected}$"):
            core.validate_row_cursor(reader, operation, token)


def test_missing_or_changed_target_blocks_even_when_row_cursor_survives():
    if not pg_or_fixed_refusal():
        return
    first, last = record_numbers(), record_numbers()
    operation = publish()
    with engine().begin() as connection:
        connection.execute(UsageCallRow.__table__.update().where(UsageCallRow.seq == last.seq).values(revision=1))
    with core.reader_epoch_snapshot(engine()) as reader:
        assert core.validate_row_cursor(reader, operation,
            encode_row_cursor(RowCursor(operation.source_instance, 1, first))).anchor == first
        with pytest.raises(core.EpochError, match="^anchor-changed$"):
            core.validate_fixed_target(reader, operation)


def test_final_identity_reprobe_refuses_buffered_success(monkeypatch):
    if not pg_or_fixed_refusal():
        return
    operation = publish()
    with pytest.raises(core.EpochError, match="^identity-changed$") as refusal:
        with core.reader_epoch_snapshot(engine()) as reader:
            core.read_current_ready_epoch(reader)
            buffered = ("not-released",)
            monkeypatch.setattr(core, "probe_primary_identity", lambda connection: CANARY)
    assert buffered == ("not-released",)
    assert set(refusal.value.changed) <= {"system", "database", "timeline"}
    assert operation.identity.system_identifier not in str(refusal.value)


def test_private_identity_only_scalars_primary_denied_and_canary_redaction(caplog):
    primary = Mock()
    primary.execute.side_effect = [SimpleNamespace(scalar_one=lambda: False), SimpleNamespace(one=lambda:
        SimpleNamespace(system_identifier=CANARY.system_identifier, database_oid=CANARY.database_oid, timeline_hex="FFFFFFA2"))]
    identity = core.probe_primary_identity(primary)
    assert identity.insert_timeline == int("FFFFFFA2", 16)
    sql = " ".join(str(call.args[0]) for call in primary.execute.call_args_list)
    assert "SELECT *" not in sql and "pg_control_checkpoint" not in sql and "pg_stat" not in sql
    assert "c.system_identifier" in sql and "d.oid::bigint" in sql and "pg_walfile_name(pg_current_wal_lsn())" in sql
    # Exact minimum projection, not merely the presence of required names.
    assert [" ".join(str(call.args[0]).split()) for call in primary.execute.call_args_list] == [
        "SELECT pg_is_in_recovery()",
        "SELECT c.system_identifier::text AS system_identifier, "
        "(SELECT d.oid::bigint FROM pg_database d WHERE d.datname = current_database()) AS database_oid, "
        "left(pg_walfile_name(pg_current_wal_lsn()), 8) AS timeline_hex FROM pg_control_system() c",
    ]
    recovery = Mock()
    recovery.execute.return_value.scalar_one.return_value = True
    with pytest.raises(core.EpochError, match="^not-primary$"):
        core.probe_primary_identity(recovery)
    assert recovery.execute.call_count == 1  # no WAL/control fallback on a standby
    denied = Mock()
    denied.execute.side_effect = DBAPIError("query-private-digit-canary", {"private": CANARY.system_identifier},
                                          RuntimeError("private-digit-canary"))
    with pytest.raises(core.EpochError, match="^identity-unreadable$") as refusal:
        core.probe_primary_identity(denied)
    for private in (CANARY.system_identifier, str(CANARY.database_oid), str(CANARY.insert_timeline)):
        assert private not in repr(identity) + repr(refusal.value) + caplog.text
    assert refusal.value.__suppress_context__ is True
    assert "private-digit-canary" not in str(refusal.value) + caplog.text


@pytest.mark.parametrize("values", [("0", 1, 1), ("01", 1, 1), ("x", 1, 1), (str(2**64), 1, 1),
    ("1", 0, 1), ("1", True, 1), ("1", 2**32, 1), ("1", 1, 0), ("1", 1, 2**32)])
def test_identity_closed_ranges(values):
    with pytest.raises(core.EpochError, match="^identity-unreadable$"):
        core.PrivateIdentity(*values)


def test_actual_minimum_reader_role_and_denied_identity_no_grant_fallback():
    if not pg_or_fixed_refusal():
        return
    operation = publish()
    with engine().connect() as connection:
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    role = f"epoch_reader_{schema}"
    role_engine = create_engine(engine().url, poolclass=NullPool)
    def set_role(dbapi_connection, record):
        with dbapi_connection.cursor() as cursor:
            cursor.execute(f'SET ROLE "{role}"')
        # Engine initialization rolls back its inspection transaction. Preserve
        # this SESSION setting, so the clean proof really uses the reader role.
        dbapi_connection.commit()
    event.listen(role_engine, "connect", set_role)
    try:
        with engine().begin() as connection:
            connection.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS')
            connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
            connection.exec_driver_sql(f'GRANT SELECT ON usage_feed_epochs, usage_source_instance, usage_call_rows TO "{role}"')
        # PG16 installations differ in PUBLIC defaults. Arrange REAL denial in
        # this connection's uncommitted catalog view, not a mock or a shared
        # committed REVOKE that could disturb other workers on the test server.
        with engine().connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql('REVOKE EXECUTE ON FUNCTION pg_catalog.pg_control_system() FROM PUBLIC')
                connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
                with pytest.raises(core.EpochError, match="^identity-unreadable$"):
                    core.probe_primary_identity(connection)
            finally:
                transaction.rollback()
        with engine().begin() as connection:
            connection.exec_driver_sql(f'GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO "{role}"')
        with core.reader_epoch_snapshot(role_engine) as reader:
            actual = core.read_current_ready_epoch(reader)
            assert actual == operation
            assert reader.connection.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar_one() is False
        with pytest.raises(core.EpochError, match="^epoch-unavailable$"):
            with core.host_epoch_transaction(role_engine):
                pytest.fail("SELECT-only role must not acquire host ACCESS EXCLUSIVE")
    finally:
        role_engine.dispose()
        with engine().begin() as connection:
            connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
            connection.exec_driver_sql(f'DROP ROLE "{role}"')


def assert_reader_first_conflicts():
    with core.reader_epoch_snapshot(engine()):
        with pytest.raises(core.EpochError, match="^epoch-timeout$"):
            with core.host_epoch_transaction(engine()):
                pass


def test_reader_first_real_conflict_timeout_and_exclusive_guard_bite(monkeypatch):
    if not pg_or_fixed_refusal():
        return
    assert_reader_first_conflicts()
    with monkeypatch.context() as mutation:
        mutation.setattr(core, "HOST_LOCK_SQL", "LOCK TABLE usage_feed_epochs IN EXCLUSIVE MODE")
        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            assert_reader_first_conflicts()


def test_reset_first_blocks_reader_before_snapshot_and_observes_newest_phase():
    if not pg_or_fixed_refusal():
        return
    publish()
    with core.host_epoch_transaction(engine()) as host:
        operation = core.append_prepared_epoch(host, epoch=2, transition_id=OTHER,
            source_instance=core.read_source_instance(host), expected_identity=core.probe_primary_identity(host.connection),
            expected_db_epoch=1, reason="restore")
        with ThreadPoolExecutor(max_workers=1) as pool:
            # Timeout is actual SQL lock wait, NOT a mocked timeout/identity read.
            def reader_attempt():
                with core.reader_epoch_snapshot(engine()) as reader:
                    return core.read_current_ready_epoch(reader)
            future = pool.submit(reader_attempt)
            with pytest.raises(core.EpochError, match="^epoch-timeout$"):
                future.result(timeout=5)
    assert operation.epoch == 2
    assert_newer_prepared_blocks()


def assert_lock_before_first_snapshot(statements, lock):
    first_select = next(i for i, sql in enumerate(statements) if sql.lstrip().upper().startswith("SELECT"))
    assert statements.index(lock) < first_select


def test_real_statement_order_and_premature_snapshot_guard_bite():
    if not pg_or_fixed_refusal():
        return
    publish()
    for helper, lock in ((core.reader_epoch_snapshot, core.READER_LOCK_SQL),
                         (core.host_epoch_transaction, core.HOST_LOCK_SQL)):
        statements = []
        def trace(connection, cursor, statement, parameters, context, many):
            statements.append(statement)
        event.listen(engine(), "before_cursor_execute", trace)
        try:
            with helper(engine()) as fence:
                core.read_current_ready_epoch(fence)
        finally:
            event.remove(engine(), "before_cursor_execute", trace)
        assert_lock_before_first_snapshot(statements, lock)
        # Plant exactly the forbidden snapshot-before-lock order; same assertion
        # fails even if both later identity probes agree.
        mutant = ["SELECT pg_is_in_recovery()", *statements]
        with pytest.raises(AssertionError):
            assert_lock_before_first_snapshot(mutant, lock)


def test_deadline_closed_fence_and_additive_schema_preserve_source():
    before = source()
    names = set(inspect(engine()).get_table_names())
    assert {"usage_source_instance", "usage_call_rows", "usage_pending", "usage_feed_epochs"} <= names
    assert list(core.EPOCHS.primary_key.columns.keys()) == ["epoch", "phase"]
    with engine().connect() as connection:
        connection.execute(text("SELECT 1"))  # already frozen, not an admissible raw fence
        with pytest.raises(core.EpochError, match="^epoch-fence-unadmitted$"):
            core.EpochFence(connection, False, time.monotonic() + 3)
    if pg_or_fixed_refusal():
        with pytest.raises(core.EpochError, match="^epoch-timeout$"):
            with core.reader_epoch_snapshot(engine(), deadline=time.monotonic() - 1):
                pytest.fail("expired request cannot create a snapshot")
    get_database().create_all_tables()
    assert source() == before
    with engine().connect() as connection:
        assert connection.execute(select(func.count()).select_from(core.EPOCHS)).scalar_one() == 0


@pytest.mark.parametrize("change", [{"epoch": 0}, {"epoch": MAX_EPOCH + 1}, {"epoch": True},
    {"transition_id": "invalid"}, {"source_instance": "invalid"}, {"reason": "init"},
    {"actor": "route"}, {"basis": "sqlite"}, {"identity": None}, {"target": "max"}])
def test_closed_operation_schema(change):
    base = core.EpochOperation(1, TRANSITION, OTHER, CANARY, "activation", None)
    with pytest.raises(core.EpochError, match="^epoch-operation-invalid$"):
        replace(base, **change)
    with pytest.raises(core.EpochError, match="^epoch-operation-invalid$"):
        base.values("OTHER")


@pytest.mark.parametrize("field,value", [("phase", "BROKEN"), ("epoch", 0),
    ("transition_id", "A" * 36), ("system_identifier", "01"), ("system_identifier", str(2**64)),
    ("basis", "different"), ("actor", "route"), ("reason", "init"), ("insert_timeline", 0),
    ("database_oid", 0), ("target_seq", 0), ("target_revision", 1)])
def test_database_closed_phase_operation_guards(field, value):
    if not pg_or_fixed_refusal():
        return
    source()
    with pytest.raises(core.EpochError, match="^epoch-unavailable$"):
        with core.host_epoch_transaction(engine()) as host:
            operation = core.EpochOperation(1, TRANSITION, core.read_source_instance(host),
                core.probe_primary_identity(host.connection), "activation", None)
            values = operation.values("PREPARED")
            values[field] = value
            host.connection.execute(core.EPOCHS.insert().values(**values))


@pytest.mark.parametrize("bad_max", [1, -1, False])
def test_host_stale_observed_db_max_refuses_without_issuing_epoch(bad_max):
    if not pg_or_fixed_refusal():
        return
    source()
    with pytest.raises(core.EpochError, match="^epoch-operation-conflict$"):
        with core.host_epoch_transaction(engine()) as host:
            core.append_prepared_epoch(host, epoch=1, transition_id=TRANSITION,
                source_instance=core.read_source_instance(host), expected_identity=core.probe_primary_identity(host.connection),
                expected_db_epoch=bad_max, reason="activation")
    with engine().connect() as connection:
        assert connection.execute(select(func.count()).select_from(core.EPOCHS)).scalar_one() == 0


@pytest.mark.parametrize("kind,code", [("source", "instance-changed"), ("epoch", "epoch-changed"),
    ("tuple", "anchor-changed"), ("row-domain", "usage-cursor-invalid")])
def test_target_scope_exact_tuple_and_row_domain(kind, code):
    if not pg_or_fixed_refusal():
        return
    record_numbers()
    operation = publish()
    instance, epoch, anchor = operation.source_instance, operation.epoch, operation.target
    if kind == "source":
        instance = OTHER
    elif kind == "epoch":
        epoch += 1
    elif kind == "tuple":
        anchor = replace(anchor, revision=anchor.revision + 1)
    token = (encode_row_cursor(RowCursor(instance, epoch, anchor)) if kind == "row-domain"
             else encode_target_cursor(TargetCursor(instance, epoch, anchor)))
    with core.reader_epoch_snapshot(engine()) as reader:
        with pytest.raises(CursorError if kind == "row-domain" else core.EpochError, match=f"^{code}$"):
            core.validate_target_cursor(reader, operation, token)


def test_source_identity_mismatch_and_final_host_identity_change_fail_closed(monkeypatch):
    if not pg_or_fixed_refusal():
        return
    source()
    with pytest.raises(core.EpochError, match="^identity-changed$"):
        with core.host_epoch_transaction(engine()) as host:
            core.append_prepared_epoch(host, epoch=1, transition_id=TRANSITION,
                source_instance=core.read_source_instance(host), expected_identity=CANARY,
                expected_db_epoch=0, reason="activation")
    with pytest.raises(core.EpochError, match="^instance-changed$"):
        with core.host_epoch_transaction(engine()) as host:
            core.append_prepared_epoch(host, epoch=1, transition_id=TRANSITION,
                source_instance=OTHER, expected_identity=core.probe_primary_identity(host.connection),
                expected_db_epoch=0, reason="activation")
    # A live identity change before commit aborts the whole phase transaction.
    with monkeypatch.context() as changed:
        with pytest.raises(core.EpochError, match="^identity-changed$"):
            with core.host_epoch_transaction(engine()) as host:
                core.append_prepared_epoch(host, epoch=1, transition_id=TRANSITION,
                    source_instance=core.read_source_instance(host), expected_identity=core.probe_primary_identity(host.connection),
                    expected_db_epoch=0, reason="activation")
                changed.setattr(core, "probe_primary_identity", lambda connection: CANARY)
    with engine().connect() as connection:
        assert connection.execute(select(func.count()).select_from(core.EPOCHS)).scalar_one() == 0
    operation = publish()
    with monkeypatch.context() as changed:
        changed.setattr(core, "read_source_instance", lambda fence: OTHER)
        with pytest.raises(core.EpochError, match="^instance-changed$"):
            with core.reader_epoch_snapshot(engine()) as reader:
                core.read_current_ready_epoch(reader)
    with monkeypatch.context() as changed:
        changed.setattr(core, "probe_primary_identity", lambda connection: CANARY)
        with pytest.raises(core.EpochError, match="^identity-changed$") as refusal:
            with core.reader_epoch_snapshot(engine()) as reader:
                core.read_current_ready_epoch(reader)
        assert refusal.value.changed == core.identity_changes(operation.identity, CANARY)


@pytest.mark.parametrize("bad_hex", [None, "", "00000000", "GGGGGGGG", "000000001", 1])
def test_unreadable_identity_scalar_has_fixed_error(bad_hex):
    connection = Mock()
    connection.execute.side_effect = [SimpleNamespace(scalar_one=lambda: False), SimpleNamespace(one=lambda:
        SimpleNamespace(system_identifier="1", database_oid=1, timeline_hex=bad_hex))]
    with pytest.raises(core.EpochError, match="^identity-unreadable$"):
        core.probe_primary_identity(connection)


def test_corrupt_phase_metadata_refuses_instead_of_reinterpreting():
    values = core.EpochOperation(1, TRANSITION, OTHER, CANARY, "activation", None).values("READY")
    for name, value in (("target_seq", 1), ("transition_id", "corrupt"), ("system_identifier", "corrupt")):
        with pytest.raises(core.EpochError, match="^epoch-transition$"):
            core._operation({**values, name: value})


def test_installed_redundant_database_policies_are_independently_present():
    if not pg_or_fixed_refusal():
        return
    schema = inspect(engine())
    uniques = {item["name"]: tuple(item["column_names"])
               for item in schema.get_unique_constraints(core.EPOCH_TABLE)}
    assert uniques["usage_epoch_transition_phase"] == ("transition_id", "phase")
    # pg_get_constraintdef adds casts/parens and expands BETWEEN. Normalize
    # only that presentation, retaining every column, operator and bound.
    checks = {item["name"]: re.sub(r"[\s()]", "", item["sqltext"].lower().replace("::text", ""))
              for item in schema.get_check_constraints(core.EPOCH_TABLE)}
    assert checks["usage_epoch_ids"] == "lengthtransition_id=36andlengthsource_instance=36"
    assert checks["usage_epoch_system"] in {
        "lengthsystem_identifierbetween1and20",
        "lengthsystem_identifier>=1andlengthsystem_identifier<=20",
    }
    with engine().connect() as connection:
        triggers = connection.execute(text(
            "SELECT t.tgname, t.tgtype, t.tgenabled, p.proname FROM pg_trigger t "
            "JOIN pg_proc p ON p.oid = t.tgfoid WHERE t.tgrelid = 'usage_feed_epochs'::regclass "
            "AND NOT t.tgisinternal")).all()
        # Bitset: row=1, before=2, INSERT=4, DELETE=8, UPDATE=16. The row
        # and statement layers must BOTH remain even when one masks the other.
        assert {name: (kind, enabled, function) for name, kind, enabled, function in triggers} == {
            "usage_epoch_append_only": (31, "O", "usage_epoch_append_guard"),
            "usage_epoch_no_rewrite": (26, "O", "usage_epoch_append_guard"),
        }
        body = connection.execute(text("SELECT prosrc FROM pg_proc "
            "WHERE oid = 'usage_epoch_append_guard()'::regprocedure")).scalar_one()
        normalized = " ".join(body.lower().split())
        # UNIQUE also blocks reuse; assert the independent EARLIER trigger policy.
        assert "where p.epoch >= new.epoch or p.transition_id = new.transition_id" in normalized


@pytest.mark.parametrize("kind,diagnostic", [("source", "usage-epoch-operation-invalid"),
    ("stale", "usage-epoch-operation-conflict"), ("reuse", "usage-epoch-operation-conflict"),
    ("superseded", "usage-epoch-operation-conflict"), ("target-alphabet", "usage-epoch-operation-invalid")])
def test_direct_host_sql_reaches_database_policies_without_python_masking(kind, diagnostic):
    if not pg_or_fixed_refusal():
        return
    operation = prepare(3)
    values = replace(operation, epoch=4, transition_id=OTHER).values("PREPARED")
    if kind == "source":
        values["source_instance"] = OTHER
    elif kind == "stale":
        values["epoch"] = 2
    elif kind == "reuse":
        values["transition_id"] = TRANSITION
    elif kind == "superseded":
        prepare(4, OTHER)
        values = operation.values("READY")
    elif kind == "target-alphabet":
        values.update(target_seq=1, target_event_id="bad/id", target_revision=0)
    # Deliberately no append helper: the DB layer must supply this refusal.
    with pytest.raises(IntegrityError, match=diagnostic):
        with engine().begin() as connection:
            connection.exec_driver_sql("SET LOCAL temper.usage_epoch_host = 'append-v1'")
            connection.execute(core.EPOCHS.insert().values(**values))


def test_database_clock_overwrites_caller_timestamp():
    if not pg_or_fixed_refusal():
        return
    source()
    supplied = utcnow() - timedelta(days=3650)
    with core.host_epoch_transaction(engine()) as host:
        operation = core.EpochOperation(1, TRANSITION, core.read_source_instance(host),
            core.probe_primary_identity(host.connection), "activation", None)
        before = host.connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        actual = host.connection.execute(core.EPOCHS.insert().values(**operation.values("PREPARED"),
            created_at=supplied).returning(core.EPOCHS.c.created_at)).scalar_one()
        after = host.connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        assert actual != supplied and before <= actual <= after


@pytest.mark.parametrize("budget", [None, 1.75, 30.0])
def test_each_local_timing_policy_and_three_second_cap(budget, monkeypatch):
    if not pg_or_fixed_refusal():
        return
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(core, "time", SimpleNamespace(monotonic=lambda: clock.now))
    deadline = None if budget is None else clock.now + budget
    with core.reader_epoch_snapshot(engine(), deadline=deadline) as reader:
        assert reader.deadline == clock.now + min(3.0, budget if budget is not None else 3.0)
        expected = "1750ms" if budget == 1.75 else "2s"
        for setting in ("statement_timeout", "lock_timeout"):
            assert reader.connection.exec_driver_sql(f"SHOW {setting}").scalar_one() == expected
        assert reader.connection.exec_driver_sql("SHOW idle_in_transaction_session_timeout").scalar_one() == "3s"


@pytest.mark.parametrize("at", ["helper", "before-final-probe", "after-final-probe"])
def test_same_deadline_exhausted_after_admission_aborts_helper_or_final_check(at, monkeypatch):
    if not pg_or_fixed_refusal():
        return
    publish()
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(core, "time", SimpleNamespace(monotonic=lambda: clock.now))
    end = clock.now + 2.0
    original_probe = core.probe_primary_identity
    def consumes_remaining_budget(connection):
        identity = original_probe(connection)
        clock.now = end
        return identity
    with pytest.raises(core.EpochError, match="^epoch-timeout$"):
        with core.reader_epoch_snapshot(engine(), deadline=end) as reader:
            core.read_current_ready_epoch(reader)
            if at == "after-final-probe":
                monkeypatch.setattr(core, "probe_primary_identity", consumes_remaining_budget)
            else:
                clock.now = end
                if at == "helper":
                    core.greatest_issued_epoch(reader)
    assert not reader.active


@pytest.mark.parametrize("values", [[], [TRANSITION, OTHER], ["not-canonical"]])
def test_source_scalar_requires_exactly_one_canonical_instance(values):
    fence = SimpleNamespace(require=Mock(), connection=Mock())
    fence.connection.execute.return_value.scalars.return_value.all.return_value = values
    with pytest.raises(core.EpochError, match="^epoch-unavailable$"):
        core.read_source_instance(fence)
    fence.require.assert_called_once_with()


def test_stored_unknown_phase_is_not_reinterpreted():
    fence = SimpleNamespace(require=Mock(), connection=Mock())
    values = core.EpochOperation(1, TRANSITION, OTHER, CANARY, "activation", None).values("PREPARED")
    fence.connection.execute.return_value.mappings.return_value.all.return_value = [{**values, "phase": "UNKNOWN"}]
    with pytest.raises(core.EpochError, match="^epoch-transition$"):
        core._phases(fence, 1)


@pytest.mark.parametrize("bad", ["missing-prepared", "missing-ready", "mixed"])
def test_current_requires_both_exact_phases_even_if_storage_is_inconsistent(bad, monkeypatch):
    if not pg_or_fixed_refusal():
        return
    operation = publish()
    phases = {"PREPARED": operation, "READY": operation}
    if bad == "mixed":
        phases["PREPARED"] = replace(operation, reason="migration")
    else:
        phases.pop("PREPARED" if bad == "missing-prepared" else "READY")
    monkeypatch.setattr(core, "_phases", lambda fence, epoch: phases)
    with pytest.raises(core.EpochError, match="^epoch-transition$"):
        with core.reader_epoch_snapshot(engine()) as reader:
            core.read_current_ready_epoch(reader)


@pytest.mark.parametrize("kind,code", [("type", "epoch-operation-conflict"), ("source", "instance-changed"),
    ("identity", "identity-changed"), ("prepared-metadata", "epoch-operation-conflict"),
    ("stored-ready-metadata", "epoch-operation-conflict"), ("target", "anchor-changed")])
def test_ready_refuses_at_the_precise_defensive_boundary(kind, code, monkeypatch):
    if not pg_or_fixed_refusal():
        return
    last = record_numbers()
    operation = prepare()
    candidate = operation
    if kind == "type":
        candidate = None
    elif kind == "source":
        candidate = replace(operation, source_instance=OTHER)
    elif kind == "identity":
        candidate = replace(operation, identity=CANARY)
    elif kind == "prepared-metadata":
        candidate = replace(operation, reason="migration")
    elif kind == "stored-ready-metadata":
        monkeypatch.setattr(core, "_phases", lambda fence, epoch: {
            "PREPARED": operation, "READY": replace(operation, reason="migration")})
    elif kind == "target":
        with engine().begin() as connection:
            connection.execute(UsageCallRow.__table__.update().where(UsageCallRow.seq == last.seq).values(revision=1))
    with pytest.raises(core.EpochError, match=f"^{code}$"):
        with core.host_epoch_transaction(engine()) as host:
            core.append_ready_epoch(host, candidate)


def test_captured_target_must_belong_to_requested_source():
    if not pg_or_fixed_refusal():
        return
    actual = record_numbers()
    with core.host_epoch_transaction(engine()) as host:
        assert core.capture_final_target(host, core.read_source_instance(host)) == actual
        with pytest.raises(core.EpochError, match="^instance-changed$"):
            core.capture_final_target(host, OTHER)
