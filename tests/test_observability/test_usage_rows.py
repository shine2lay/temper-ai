"""Fixed-input stages; no model, provider, workflow, live database or raw-content reads.

The first test combines the whole happy path. In-memory mutation checks use the
same assertions as the clean checks: removing a guard must be caught, not merely
leave the suite green. This folder already belongs to tests/pgtier.py's tier.
"""

from __future__ import annotations

import hashlib
import inspect
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import func, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session, col, select

from temper_ai.database import get_database, get_session
from temper_ai.database.session import DatabaseManager
from temper_ai.llm.models import CallContext, LLMResponse
from temper_ai.llm.pi_stream import PiEventMapper
from temper_ai.llm.service import LLMService
from temper_ai.observability import recorder
from temper_ai.observability import usage_rows as usage
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType as ET
from temper_ai.observability.models import Event
from temper_ai.shared.clock import as_utc

AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
EXEC = "00000000-0000-4000-8000-000000000001"
PARENT = "00000000-0000-4000-8000-000000000002"
NUMBERS = {"prompt_tokens": 150, "completion_tokens": 10, "total_tokens": 160,
           "cached_prompt_tokens": 30, "cache_write_tokens": 20, "cost_usd": 0.30000000000000004}
COLUMNS = {
    "seq", "event_id", "revision", "instance", "execution_id", "parent_id", "event_type", "call_kind",
    "llm_call_id", "started_event_id", "provider", "model", "prompt_tokens", "completion_tokens",
    "total_tokens", "cache_read_tokens", "cache_write_tokens", "token_source", "legacy_cost_usd",
    "legacy_cost_source", "lost_attempts", "event_at", "occurred_at", "occurrence_basis", "origin", "fault_codes",
}


@pytest.fixture(autouse=True)
def isolated_ordering_key(monkeypatch, _test_db):
    # pgtier isolates SCHEMAS, but advisory locks are DATABASE-wide. A fixed test
    # key per worker schema prevents a 3s injected holder breaking other workers.
    # Production COMMIT_ORDER_LOCK and all transaction behavior are unchanged.
    if get_database().engine.dialect.name == "postgresql":
        with get_session() as session:
            schema = session.execute(text("SELECT current_schema()")).scalar_one()
        key = int.from_bytes(hashlib.sha256(schema.encode("ascii")).digest()[:8], "big", signed=True)
        monkeypatch.setattr(usage, "COMMIT_ORDER_LOCK", key)


def rows():
    with get_session() as session:
        result = list(session.exec(select(usage.UsageCallRow).order_by(col(usage.UsageCallRow.seq))).all())
        session.expunge_all()  # assertions use snapshots, not expired attached ORM instances
        return result


def extract(data, event_type=ET.LLM_CALL_COMPLETED, **ids):
    return usage.extract(event_type, data, {"event_id": str(uuid.uuid4()),
                         "execution_id": EXEC, "parent_id": PARENT, **ids}, AT)


def record(data=None, event_type=ET.LLM_CALL_COMPLETED, **kw):
    return recorder.record(event_type, data=data or {"model": "model-v1", **NUMBERS},
                           execution_id=kw.pop("execution_id", EXEC),
                           parent_id=kw.pop("parent_id", PARENT), **kw)


def pi_events():
    # Deliberately no words, prompts or tool data. Usage is an exclusive Pi observation.
    msg = {"role": "assistant", "provider": "provider-v1", "model": "model-v1", "content": [],
           "stopReason": "stop", "usage": {"input": 100, "output": 10, "cacheRead": 30,
                                            "cacheWrite": 20, "totalTokens": 160, "cost": {"total": 0}}}
    return [{"type": "message_start", "message": msg}, {"type": "message_end", "message": msg}]


def mapper(known=()):
    sink = Mock(wraps=EventRecorder(EXEC))
    sink.broadcast_stream_chunk = Mock()  # recording proof, not the live stream transport
    return PiEventMapper(sink, execution_id=EXEC, agent_event_id=PARENT,
                         agent_name="fixture", session_id="fixture-session", known_event_ids=known)


def service():
    # Test only the event path, not a provider: _invoke_provider is replaced below.
    llm = LLMService(SimpleNamespace(provider_name="provider-v1", model="model-v1",
                                     temperature=0, max_tokens=1))
    llm._ctx = CallContext(execution_id=EXEC, agent_event_id=PARENT)
    llm._record = recorder.record
    llm._messages, llm._tools, llm._stream_callback = [], None, None
    llm._active_fallback, llm._compressor, llm._extra_room = None, None, None
    return llm


def test_00_combined_native_call_happy_path(monkeypatch):
    llm = service()
    monkeypatch.setattr(llm, "_invoke_provider", lambda **kw: LLMResponse(
        content="", model="model-v2", provider="provider-v1", **{
            k: v for k, v in NUMBERS.items() if k != "cost_usd"
        }, raw_response={"total_cost_usd": NUMBERS["cost_usd"]},
    ))
    start_id, _, _ = llm._call_llm(1)
    start, end = rows()
    assert end.started_event_id == start_id == start.event_id
    assert end.provider == "provider-v1" and end.model == "model-v2"
    assert (end.prompt_tokens, end.completion_tokens, end.cache_read_tokens,
            end.cache_write_tokens, end.total_tokens) == (150, 10, 30, 20, 160)
    assert end.legacy_cost_usd == 0.30000000000000004 and end.legacy_cost_source == "service"
    assert start.occurrence_basis == "call_start" and start.started_event_id == start.event_id
    assert end.occurrence_basis == "call_end" and as_utc(end.occurred_at) == as_utc(end.event_at)
    assert start.seq < end.seq and start.instance == end.instance
    pi = mapper()
    pi.handle_all(pi_events())
    pi_start, pi_end = rows()[2:]
    assert pi_end.started_event_id == pi_start.event_id
    assert pi_end.prompt_tokens == 100  # NOT 100 - 30 - 20
    assert pi_end.token_source == "pi" and pi_end.legacy_cost_source == "pi_estimate"
    assert pi_end.legacy_cost_usd == 0  # native observation, never labelled a known price
    with get_session() as session:
        assert session.exec(select(func.count()).select_from(Event)).one() == 4
        assert session.exec(select(func.count()).select_from(usage.UsageSourceInstance)).one() == 1
    assert set(usage.UsageCallRow.__table__.columns.keys()) == COLUMNS
    assert_pending_happy_path(monkeypatch)


def test_failure_without_usage_and_pi_failure_with_usage(monkeypatch):
    llm = service()
    def fail(**kw):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(llm, "_invoke_provider", fail)
    monkeypatch.setattr(llm, "_drop_extra_room", lambda exc: False)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        llm._call_llm(1)
    start, failed = rows()
    assert failed.started_event_id == start.event_id
    assert all(getattr(failed, k) is None for k in usage.TOKEN_FIELDS)
    assert failed.legacy_cost_usd is None and "usage-missing" in failed.fault_codes
    events = pi_events()
    events[1]["message"] = {**events[1]["message"], "stopReason": "error", "errorMessage": "canary error"}
    mapper().handle_all(events)
    pi_failed = rows()[-1]
    assert pi_failed.event_type == ET.LLM_CALL_FAILED
    assert pi_failed.prompt_tokens == 100 and pi_failed.cache_read_tokens == 30
    assert "canary" not in str(pi_failed.model_dump())


def test_event_and_row_rollback_together(monkeypatch):
    def fail(*args):
        raise RuntimeError("synthetic projection failure")
    monkeypatch.setattr(usage, "write_or_queue_row", fail)
    monkeypatch.setattr(recorder.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="synthetic projection failure"):
        record()
    with get_session() as session:
        assert session.exec(select(func.count()).select_from(Event)).one() == 0
    assert rows() == []


@contextmanager
def unknown_commit_once(monkeypatch):
    db = get_database()
    original = db.session
    lost = False
    @contextmanager
    def session():
        nonlocal lost
        with original() as s:
            yield s
        if not lost:
            lost = True
            raise RuntimeError("synthetic acknowledgement lost")
    with monkeypatch.context() as m:
        m.setattr(db, "session", session)
        m.setattr(recorder.time, "sleep", lambda _: None)
        yield


def assert_unknown_commit(monkeypatch):
    count = len(rows())
    with unknown_commit_once(monkeypatch):
        eid = record()
    assert len(rows()) == count + 1
    with get_session() as session:
        assert session.get(Event, eid) is not None
    return eid


def test_unknown_commit_retry_is_idempotent(monkeypatch):
    eid = assert_unknown_commit(monkeypatch)
    recorder.record(ET.LLM_CALL_COMPLETED, data={"prompt_tokens": 999}, event_id=eid)
    assert len(rows()) == 1 and rows()[0].prompt_tokens == 150
    with unknown_commit_once(monkeypatch):
        recorder.update_event(eid, data={"prompt_tokens": 151})
    assert [r.prompt_tokens for r in rows()] == [150, 151]
    assert [r.revision for r in rows()] == [0, 1]


def test_fork_copies_no_rows_but_new_attempt_does():
    wf = recorder.record(ET.WORKFLOW_STARTED, execution_id=EXEC)
    stage = recorder.record(ET.STAGE_STARTED, data={"name": "fixture"}, parent_id=wf, execution_id=EXEC)
    agent = recorder.record(ET.AGENT_STARTED, parent_id=stage, execution_id=EXEC)
    record(parent_id=agent)
    before = len(rows())
    recorder.copy_events_for_fork(EXEC, "fork-execution", {"fixture"})
    assert len(rows()) == before
    with get_session() as session:
        copied = session.exec(select(Event).where(Event.execution_id == "fork-execution",
                                                 Event.type == ET.LLM_CALL_COMPLETED)).one()
        copied_id = copied.id
    recorder.update_event(copied_id, data={"prompt_tokens": 999})
    assert len(rows()) == before
    record(execution_id="fork-execution", parent_id=agent)
    assert len(rows()) == before + 1
    assert extract({"restored_from_fork": True, **NUMBERS}) is None


def test_pi_replay_and_real_retry_new_ordinal():
    first = mapper()
    first.handle_all(pi_events())
    known = first.recorded
    mapper(known).handle_all(pi_events())
    assert len(rows()) == 2
    # Even a lost mapper checkpoint is safe at the DB's stable event id boundary.
    mapper().handle_all(pi_events())
    assert len(rows()) == 2
    replay = mapper(known)
    replay.handle_all(pi_events() + pi_events())
    assert len(rows()) == 4
    assert len({r.event_id for r in rows()}) == 4
    assert len({r.llm_call_id for r in rows()}) == 2


def test_instance_once_and_survives_reinitialisation(tmp_path):
    db = get_database()
    if db.engine.dialect.name == "sqlite":
        # A memory database cannot survive a disposed engine; file SQLite can.
        db = DatabaseManager(f"sqlite:///{tmp_path}/instance.db")
    db.create_all_tables()
    with db.session() as session:
        instance = usage.ensure_instance(session)
    assert uuid.UUID(instance).version == 4
    db.create_all_tables()
    with db.session() as session:
        assert usage.ensure_instance(session) == instance
        assert session.exec(select(func.count()).select_from(usage.UsageSourceInstance)).one() == 1
    again = DatabaseManager(db.database_url)
    try:
        again.create_all_tables()
        with again.session() as session:
            assert usage.ensure_instance(session) == instance
    finally:
        again.dispose()
        if db is not get_database():
            db.dispose()


def test_allowlist_canaries_and_malformed_optional_ids():
    canary = "CONTENT CANARY /private/path\n"
    payload = {**NUMBERS, "provider": canary, "model": canary, "call_kind": canary,
               "llm_call_id": canary, "started_event_id": canary,
               "prompt": canary, "messages": [{"content": canary}], "response_content": canary,
               "tool_calls_requested": [{"name": canary, "arguments": {"secret": canary}}],
               "error": canary, "task": canary, "scope": canary,
               "lost_attempts": [{"error": canary, "cost_usd": 999}]}
    record(payload, execution_id=canary, parent_id=canary)
    row = rows()[0]
    assert set(row.model_dump()) == COLUMNS
    assert all(canary not in str(value) for value in row.model_dump().values())
    assert row.provider is row.model is row.call_kind is row.execution_id is row.parent_id is None
    assert row.llm_call_id is row.started_event_id is None
    assert row.lost_attempts == 1
    assert set(row.fault_codes.split(",")) <= usage.FAULT_CODES
    assert len(row.fault_codes) <= 256
    assert {"provider-invalid", "model-invalid", "kind-invalid", "id-invalid"} <= set(row.fault_codes.split(","))
    with pytest.raises(ValueError, match="^usage event reference invalid$"):
        extract({}, event_id=canary)


@pytest.mark.parametrize("value", [True, False, 0.5, -1, float("nan"), float("inf"),
                                  -float("inf"), 2**53, "10", [], {"tokens": 1}])
def test_bad_counts_are_null_not_coerced(value):
    row = extract({key: value for key in usage.TOKEN_FIELDS.values()})
    assert all(getattr(row, key) is None for key in usage.TOKEN_FIELDS)
    assert set(usage._TOKEN_FAULTS.values()) <= set(row.fault_codes.split(","))


def test_integer_boundaries_missing_fields_and_legacy_amount():
    for number in (0, usage.MAX_SAFE_INTEGER):
        row = extract({**{key: number for key in usage.TOKEN_FIELDS.values()}, "provider": "p/@+-._:1",
                       "model": "m/v1", "cost_usd": 0})
        assert all(getattr(row, key) == number for key in usage.TOKEN_FIELDS)
        assert row.provider == "p/@+-._:1" and row.legacy_cost_usd == 0
    assert extract({}).prompt_tokens is None
    for bad in (True, -1, float("nan"), float("inf"), 10**1000, "0.1", {}):
        row = extract({"cost_usd": bad})
        assert row.legacy_cost_usd is None and row.legacy_cost_source is None
        assert "cost-invalid" in row.fault_codes
    assert extract({"cost_usd": 0.30000000000000004}).legacy_cost_usd == 0.30000000000000004
    assert extract({"lost_attempts": "not a list"}).lost_attempts is None
    assert "lost-invalid" in extract({"lost_attempts": "not a list"}).fault_codes
    for bad in ("", "p\n", "p x", "p" * 129, "é", [], {}):
        row = extract({"provider": bad, "model": bad})
        assert row.provider is row.model is None
        assert "provider-invalid" in row.fault_codes and "model-invalid" in row.fault_codes
    assert usage._fault_text(set(usage.FAULT_CODES))  # even all closed faults fit
    with pytest.raises(ValueError, match="usage fault code invalid"):
        usage._fault_text({"CONTENT CANARY"})
    assert extract(NUMBERS, event_type=ET.AGENT_COMPLETED) is None


def assert_exact_link_scope():
    start = record({"provider": "provider-v1", "model": "model-v1"}, event_type=ET.LLM_CALL_STARTED)
    record({**NUMBERS, "model": "response-model", "started_event_id": start})
    linked = rows()[-1]
    assert linked.provider == "provider-v1" and linked.started_event_id == start
    for different in ({"execution_id": "other-execution"}, {"parent_id": "other-parent"}):
        record({**NUMBERS, "model": "response-model", "started_event_id": start}, **different)
        assert rows()[-1].provider is None and rows()[-1].started_event_id is None
        assert "link-unproven" in rows()[-1].fault_codes
    record({**NUMBERS, "model": "response-model", "started_event_id": start, "provider": "bad\n"})
    assert rows()[-1].provider is None and "provider-invalid" in rows()[-1].fault_codes
    call = str(uuid.uuid4())
    record({"executed_by": "pi", "llm_call_id": call, "call_kind": "compaction", "provider": "p", "model": "m"},
           event_type=ET.LLM_CALL_STARTED)
    record({"executed_by": "pi", "llm_call_id": call, "call_kind": "compaction", **NUMBERS,
            "tokens_before": 1000, "estimated_tokens_after": 10})
    assert rows()[-1].provider is rows()[-1].model is None
    assert rows()[-1].started_event_id == rows()[-2].event_id
    record({"executed_by": "pi", "llm_call_id": call, "call_kind": "model", **NUMBERS})
    assert rows()[-1].started_event_id is None  # same id, wrong call kind
    service_call = str(uuid.uuid4())
    record({"provider": "p", "model": "m", "llm_call_id": service_call}, event_type=ET.LLM_CALL_STARTED)
    record({"executed_by": "pi", "llm_call_id": service_call, **NUMBERS})
    assert rows()[-1].started_event_id is None  # same native ref, different source
    foreign_id = str(uuid.uuid4())
    foreign = extract({"provider": "p", "model": "m"}, event_type=ET.LLM_CALL_STARTED, event_id=foreign_id)
    foreign.instance = str(uuid.uuid4())  # fixture from a different source instance
    with get_session() as session:
        session.add(foreign)
    record({"started_event_id": foreign_id, **NUMBERS})
    assert rows()[-1].started_event_id is None


def test_exact_link_scope_and_no_compaction_inheritance():
    assert_exact_link_scope()


def assert_revisions():
    eid = record()
    before = rows()[-1]
    recorder.update_event(eid, status="completed")
    recorder.update_event(eid, data={"response_content": "ignored canary", "prompt_tokens": 150})
    assert [r.revision for r in rows() if r.event_id == eid] == [0]
    recorder.update_event(eid, data={"prompt_tokens": 151})
    matching = [r for r in rows() if r.event_id == eid]
    assert len(matching) == 2
    first, second = matching
    assert (first.revision, second.revision) == (0, 1)
    assert first.model_dump() == before.model_dump()  # previous observation immutable
    assert first.prompt_tokens == 150 and second.prompt_tokens == 151 and first.seq < second.seq
    recorder.update_event(eid, data={"prompt_tokens": 151})
    assert [r.revision for r in rows() if r.event_id == eid] == [0, 1]


def test_numeric_revision_not_status_or_content():
    assert_revisions()


def test_concurrent_numeric_updates_choose_distinct_revisions():
    eid = record()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda n: recorder.update_event(eid, data={"prompt_tokens": n}), (151, 152)))
    assert [r.revision for r in rows()] == [0, 1, 2]
    assert {r.prompt_tokens for r in rows()} == {150, 151, 152}


def _write_uncommitted(session):
    eid = str(uuid.uuid4())
    session.add(Event(id=eid, type=ET.LLM_CALL_COMPLETED, execution_id=EXEC, parent_id=PARENT,
                      data={"model": "model-v1", **NUMBERS}, timestamp=AT))
    row = extract({"model": "model-v1", **NUMBERS}, event_id=eid)
    usage.write_or_queue_row(session, row)
    return row.seq


def assert_commit_order(rollback=False):
    db = get_database()
    # Cold singleton creation is tested independently. Do not hold its insertion
    # lock in A: that would accidentally mask removal of the commit-order lock.
    with get_session() as session:
        usage.ensure_instance(session)
    initial = len(rows())
    a = Session(db.engine)
    waiting, finished = threading.Event(), threading.Event()
    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name.startswith("usage-order") and (
            "pg_advisory_xact_lock" in statement or "INSERT INTO usage_call_rows" in statement
        ):
            waiting.set()
    def b():
        # SQLite uses the whole-transaction mutex; Postgres uses its xact lock.
        waiting.set() if db.engine.dialect.name == "sqlite" else None
        record()
        finished.set()
    sa_event.listen(db.engine, "before_cursor_execute", before_execute)
    try:
        with usage.sqlite_transaction_lock():
            n = _write_uncommitted(a)
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="usage-order") as pool:
                future = pool.submit(b)
                try:
                    assert waiting.wait(5)
                    premature = finished.wait(0.1)
                    if db.engine.dialect.name != "sqlite":
                        assert len(rows()) == initial + (1 if premature else 0)
                finally:
                    a.rollback() if rollback else a.commit()
                    # RLock released before B tries to enter its SQLite transaction.
                    if db.engine.dialect.name == "sqlite":
                        usage._SQLITE_TRANSACTION_LOCK.release()
                        try:
                            future.result(timeout=10)
                        finally:
                            usage._SQLITE_TRANSACTION_LOCK.acquire()
                    else:
                        future.result(timeout=10)
                assert not premature, "later seq committed ahead of the uncommitted earlier seq"
        added = rows()[initial:]
        if rollback:
            assert len(added) == 1
            if db.engine.dialect.name == "postgresql":
                assert added[0].seq > n, "Postgres rollback gap must never fill in later"
        else:
            assert [r.seq for r in added] == [n, n + 1]
    finally:
        a.close()
        sa_event.remove(db.engine, "before_cursor_execute", before_execute)


def test_concurrent_commit_order_and_safe_rollback_gap():
    assert_commit_order()
    assert_commit_order(rollback=True)


class _ScalarResultCursor:
    """Test-only: hide timing RETURNING columns, leaving the real scalar result."""

    def __init__(self, cursor, seq):
        self.cursor = cursor
        self.description = cursor.description[:1]
        self.pending = [(seq,)]

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def fetchone(self):
        return self.pending.pop(0) if self.pending else None

    def fetchmany(self, size=None):
        size = self.cursor.arraysize if size is None else size
        result, self.pending = self.pending[:size], self.pending[size:]
        return result

    def fetchall(self):
        result, self.pending = self.pending, []
        return result


def _profile_statement(statement, extra_timestamps=True):
    """Keep original measuring CTEs; diagnostic adds ONLY two RETURNING clocks."""
    timed = statement.replace(
        "WITH commit_order AS MATERIALIZED (",
        "WITH wait_started AS MATERIALIZED (SELECT clock_timestamp() AS at), "
        "commit_order AS MATERIALIZED (",
    ).replace(
        ")\n    )", ") FROM wait_started\n    )", 1,
    ).replace(
        ")\n    INSERT INTO", "), lock_acquired AS MATERIALIZED "
        "(SELECT clock_timestamp() AS at FROM commit_order)\n    INSERT INTO", 1,
    ).replace("FROM commit_order\n", "FROM lock_acquired\n").replace(
        "RETURNING seq", "RETURNING seq, (SELECT at FROM wait_started), "
        "(SELECT at FROM lock_acquired)",
    )
    if extra_timestamps:
        timed = timed.replace(
            "(SELECT at FROM lock_acquired)",
            "(SELECT at FROM lock_acquired), statement_timestamp(), clock_timestamp()",
        )
    return timed


@contextmanager
def _profile_lock_transaction(engine, samples):
    """Diagnostic instrument only: server intervals and client monotonic intervals.

    A public psycopg2 connection_factory measures the DBAPI commit call itself,
    NOT pool return. Normal SQL and transaction boundaries remain unchanged.
    Cross-clock delivery is labelled/excluded from the decision table. No ids,
    params or payloads enter samples. No driver internals are patched.
    """
    import psycopg2
    from psycopg2.extensions import connection as PgConnection

    class ProfiledConnection(PgConnection):
        usage_profile = None

        def commit(self):
            profile = self.usage_profile
            if profile is None:
                return super().commit()
            sent = time.perf_counter()
            try:
                return super().commit()
            finally:
                returned = time.perf_counter()
                self.usage_profile = None
                sample = dict(profile["server"])
                sample["client_turnaround_ms"] = (sent - profile["result_received"]) * 1000
                sample["commit_ms"] = (returned - sent) * 1000
                sample["accounted_hold_segments_ms"] = (
                    sample["in_statement_grant_to_row_ms"]
                    + sample["client_turnaround_ms"] + sample["commit_ms"]
                )
                samples.append(sample)

    def connect(dialect, connection_record, cargs, cparams):
        return psycopg2.connect(*cargs, connection_factory=ProfiledConnection, **cparams)

    def execute(cursor, statement, parameters, context):
        if "WITH commit_order AS MATERIALIZED" not in statement:
            return False
        cursor.execute(_profile_statement(statement), parameters)
        received = time.perf_counter()
        received_wall = datetime.now(UTC)
        seq, waiting_at, acquired_at, statement_at, row_at = cursor.fetchone()
        profile = {
            "result_received": received,
            "server": {
                "server_received_to_prelock_ms": (waiting_at - statement_at).total_seconds() * 1000,
                "lock_wait_ms": (acquired_at - waiting_at).total_seconds() * 1000,
                "server_received_to_grant_ms": (acquired_at - statement_at).total_seconds() * 1000,
                "in_statement_grant_to_row_ms": (row_at - acquired_at).total_seconds() * 1000,
                "cross_clock_row_to_result_ms": (received_wall - row_at).total_seconds() * 1000,
            },
        }
        context.root_connection.connection.driver_connection.usage_profile = profile
        context.cursor = _ScalarResultCursor(cursor, seq)
        return True

    # New pool uses the public connection factory, preserving every connect arg
    # (including the isolated test schema). Only diagnostic instrumentation differs.
    sa_event.listen(engine, "do_connect", connect, retval=True)
    engine.dispose()
    sa_event.listen(engine, "do_execute", execute, retval=True)
    try:
        yield
    finally:
        sa_event.remove(engine, "do_execute", execute)
        sa_event.remove(engine, "do_connect", connect)
        engine.dispose()


@pytest.mark.timeout(240)
def test_eight_writers_500_events_lock_wait_p95(record_property):
    db = get_database()
    if db.engine.dialect.name == "sqlite":
        for _ in range(1005):
            record()
        assert len(rows()) == 1005
        return
    fixed_load = os.environ.get("TEMPER_USAGE_FIXED_LOAD") == "1"
    diagnostic = os.environ.get("TEMPER_USAGE_DIAGNOSTIC") == "1"
    record_property("usage_diagnostic_ineligible_for_pass", diagnostic)
    assert not diagnostic or fixed_load
    if fixed_load:
        assert os.sched_getaffinity(0) == set(range(5)) | set(range(10, 15))
    burners = []
    with get_session() as session:
        usage.ensure_instance(session)
    try:
        if fixed_load:
            for _ in range(8):
                burners.append(subprocess.Popen(
                    [sys.executable, "-c", "while True: pass"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                ))
        for trial in range(1 if diagnostic else (2 if fixed_load else 1)):
            baseline = len(rows())
            samples = []
            barrier = threading.Barrier(8)
            def writer(n):
                barrier.wait(timeout=10)
                for _ in range(500):
                    record()
            # Gate: all 4000 writes/order/duplicates on the unmodified statement.
            # Fixed stage only: declared repeatable CPU contention and timings.
            profiling = _profile_lock_transaction(db.engine, samples) if fixed_load else nullcontext()
            with profiling, ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(writer, range(8)))
            added = rows()[baseline:]
            seqs = [r.seq for r in added]
            with get_session() as session:
                pending_count = session.exec(select(func.count()).select_from(usage.UsagePending)).one()
            record_property(f"usage_pending_count_run_{trial + 1}", pending_count)
            assert pending_count == 0, "normal-load trial must not hide pending fallback"
            if fixed_load:
                metrics = {name: [s[name] for s in samples] for name in samples[0]} if samples else {}
                summary = {}
                # Report ALL series before asserting: a wait miss must not hide
                # the hold/COMMIT evidence needed to choose the next hypothesis.
                for name, values in metrics.items():
                    ordered = sorted(values)
                    stats = {"count": len(ordered)}
                    for label, quantile in (("p50", 0.5), ("p95", 0.95), ("max", 1)):
                        value = ordered[math.ceil(len(ordered) * quantile) - 1] if ordered else None
                        stats[label] = value
                        record_property(f"usage_{name}_{label}_run_{trial + 1}", value)
                    summary[name] = stats
                    print(f"usage fixed-load run={trial + 1} {name}: {stats}")
                if samples:
                    # A paired decomposition, not a sum of unrelated p95 values.
                    tail = sorted(samples, key=lambda s: s["accounted_hold_segments_ms"])[
                        math.ceil(len(samples) * 0.95) - 1
                    ]
                    for name in ("in_statement_grant_to_row_ms", "client_turnaround_ms",
                                 "commit_ms", "accounted_hold_segments_ms"):
                        record_property(f"usage_at_accounted_hold_p95_{name}", tail[name])
            assert len(seqs) == len(set(seqs)) == 4000 and seqs == sorted(seqs)
            if fixed_load:
                assert all(p.poll() is None for p in burners)
                assert len(samples) == 4000
                assert all(len(values) == 4000 and (name.startswith("cross_clock_") or min(values) >= 0)
                           for name, values in metrics.items())
                p95 = summary["lock_wait_ms"]["p95"]
                assert p95 <= 100, f"lock-wait p95 {p95:.3f}ms exceeds approved 100ms"
    finally:
        for process in burners:
            process.terminate()
        for process in burners:
            process.wait(timeout=10)


def mutated(monkeypatch, module, name, old, new):
    """Compile one exact guard removal IN MEMORY; never modify a source file."""
    original = getattr(module, name)
    source = inspect.getsource(original)
    assert source.count(old) == 1, "mutation no longer matches the guard"
    scope = dict(vars(module))
    exec(compile(source.replace(old, new), f"<usage-guard-{name}>", "exec"), scope)
    monkeypatch.setattr(module, name, scope[name])


@pytest.mark.parametrize(("old", "new", "data", "field"), [
    ("type(value) is int and 0 <= value <= MAX_SAFE_INTEGER", "isinstance(value, (int, float)) and 0 <= value <= MAX_SAFE_INTEGER", {"prompt_tokens": True}, "prompt_tokens"),
    ("0 <= value <= MAX_SAFE_INTEGER", "value <= MAX_SAFE_INTEGER", {"prompt_tokens": -1}, "prompt_tokens"),
    ("0 <= value <= MAX_SAFE_INTEGER", "0 <= value", {"prompt_tokens": 2**53}, "prompt_tokens"),
    ("type(value) is int and 0 <= value <= MAX_SAFE_INTEGER", "isinstance(value, (int, float)) and 0 <= value <= MAX_SAFE_INTEGER", {"prompt_tokens": 0.5}, "prompt_tokens"),
    ("math.isfinite(candidate) and candidate >= 0", "True", {"cost_usd": float("nan")}, "legacy_cost_usd"),
    ("math.isfinite(candidate) and candidate >= 0", "True", {"cost_usd": -1}, "legacy_cost_usd"),
    ("data.get(\"restored_from_fork\") is True", "False", {"restored_from_fork": True}, None),
])
def test_extraction_guards_bite(monkeypatch, old, new, data, field):
    def check():
        row = extract(data)
        assert row is None if field is None else getattr(row, field) is None
    check()
    mutated(monkeypatch, usage, "extract", old, new)
    with pytest.raises(AssertionError):
        check()


def test_label_guard_bites(monkeypatch):
    def check():
        assert extract({"provider": "CONTENT CANARY"}).provider is None
    check()
    mutated(monkeypatch, usage, "_label", "_LABEL.fullmatch(value)", "True")
    # extract looks up _label in the actual module globals.
    with pytest.raises(AssertionError):
        check()


def test_idempotency_guard_bites(monkeypatch):
    # Remove ON CONFLICT on EVENTS, not on usage rows: the original unknown-commit
    # check must now fail (event primary key collision), never falsely report done.
    mutated(monkeypatch, recorder, "record", ".on_conflict_do_nothing(\n            index_elements=[\"id\"],\n        )", "")
    with pytest.raises(IntegrityError):
        assert_unknown_commit(monkeypatch)


@pytest.mark.parametrize("replacement", ["True", "False"])
def test_revision_guard_bites(monkeypatch, replacement):
    mutated(monkeypatch, usage, "projection_changed", "return before.model_dump() != after.model_dump()", f"return {replacement}")
    with pytest.raises(AssertionError):
        assert_revisions()


@pytest.mark.parametrize("condition", [
    "model.instance == row.instance,", "model.execution_id == row.execution_id,",
    "model.parent_id == row.parent_id,", "model.token_source == row.token_source,",
    "model.call_kind == row.call_kind,",
])
def test_exact_link_scope_guards_bite(monkeypatch, condition):
    mutated(monkeypatch, usage, "_link_start", condition, "")
    with pytest.raises(AssertionError):
        assert_exact_link_scope()


@pytest.mark.parametrize(("old", "new"), [
    ('row.token_source == "service" and row.provider is None', 'row.provider is None'),
    (' and "provider-invalid" not in faults', ''),
])
def test_provider_inheritance_guards_bite(monkeypatch, old, new):
    mutated(monkeypatch, usage, "_link_start", old, new)
    with pytest.raises(AssertionError):
        assert_exact_link_scope()


def test_commit_order_lock_guard_bites(monkeypatch):
    if get_database().engine.dialect.name == "sqlite":
        # SQLite's database-wide serial writer plus the in-memory connection mutex
        # is checked by the same clean stage. There is no pg lock to remove here.
        assert_commit_order()
        return
    original = usage._POSTGRES_ROW_INSERT.text
    assert original.count("SELECT pg_advisory_xact_lock(:commit_order_lock)") == 1
    monkeypatch.setattr(usage, "_POSTGRES_ROW_INSERT", text(original.replace(
        "SELECT pg_advisory_xact_lock(:commit_order_lock)", "SELECT 1",
    )))
    with pytest.raises(AssertionError, match="later seq committed"):
        assert_commit_order()


# Approved A stage: no provider calls, real primary Postgres only where specified.
def pending_rows():
    with get_session() as session:
        result = list(session.exec(select(usage.UsagePending).order_by(
            col(usage.UsagePending.event_id), col(usage.UsagePending.revision),
        )).all())
        session.expunge_all()
        return result


@contextmanager
def force_pending(monkeypatch):
    # Exercises typed capture on BOTH dialects. Not claimed as a real PG timeout.
    with monkeypatch.context() as m:
        m.setattr(usage, "_append_final", lambda session, row, **kw: usage._AppendOutcome("deferred"))
        yield


def drain(event_id, revision=0):
    with usage.sqlite_transaction_lock(), get_session() as session:
        return usage.drain_pending_row(session, event_id, revision)


def event_count():
    with get_session() as session:
        return session.exec(select(func.count()).select_from(Event)).one()


def assert_pending_happy_path(monkeypatch):
    count = len(rows())
    with force_pending(monkeypatch):
        event_id = record()
    assert len(rows()) == count and len(pending_rows()) == 1
    pending = pending_rows()[0]
    assert pending.event_id == event_id and pending.revision == 0
    assert pending.prompt_tokens == 150 and pending.legacy_cost_usd == 0.30000000000000004
    assert pending.defer_reason == "ordering-lock-timeout" and pending.pending_at is not None
    assert "ordering-deferred" in pending.fault_codes
    outcome = drain(event_id)
    assert outcome.status == "drained" and outcome.seq is not None
    assert pending_rows() == [] and len(rows()) == count + 1
    assert "ordering-deferred" in rows()[-1].fault_codes  # evidence survives deletion
    assert drain(event_id).status == "missing" and len(rows()) == count + 1
    assert set(usage.UsagePending.__table__.columns.keys()) == COLUMNS - {"seq"} | {"pending_at", "defer_reason"}


def test_pending_capture_and_exactly_once_drain(monkeypatch):
    assert_pending_happy_path(monkeypatch)
    assert event_count() == 1


def test_pending_canaries_and_bad_values_are_not_projected(monkeypatch):
    canary = "CONTENT CANARY/private/path"
    with force_pending(monkeypatch):
        event_id = record({"prompt": canary, "response": canary, "error": canary,
                           "tool": {"output": canary}, "provider": canary, "model": canary,
                           "prompt_tokens": True, "completion_tokens": -1,
                           "total_tokens": 0.5, "cached_prompt_tokens": 2**53,
                           "cache_write_tokens": "invalid-number"})
    pending = pending_rows()[0]
    assert canary not in str(pending.model_dump())
    assert pending.provider is None and pending.model is None
    assert all(getattr(pending, field) is None for field in usage.TOKEN_FIELDS)
    assert len(pending.fault_codes) <= 256 and set(pending.fault_codes.split(",")) <= usage.FAULT_CODES
    assert drain(event_id).status == "drained"
    assert canary not in str(rows()[0].model_dump())


def assert_pending_revisions(monkeypatch):
    with force_pending(monkeypatch):
        event_id = record()
        recorder.update_event(event_id, data={"prompt_tokens": 151})
        recorder.update_event(event_id, status="completed")
    assert [row.revision for row in pending_rows()] == [0, 1]
    recorder.update_event(event_id, data={"prompt_tokens": 152})
    assert [(row.revision, row.prompt_tokens) for row in rows()] == [(2, 152)]
    # Arrival may reverse revisions. A consumer must restate by revision, not sum.
    assert drain(event_id, 1).status == "drained"
    assert drain(event_id, 0).status == "drained"
    assert [(row.revision, row.prompt_tokens) for row in rows()] == [(2, 152), (1, 151), (0, 150)]
    assert pending_rows() == []


def test_pending_revisions_and_status_only_update(monkeypatch):
    assert_pending_revisions(monkeypatch)


@pytest.mark.parametrize("source", ["service", "pi-model", "pi-compaction"])
def test_end_links_to_pending_start_without_changing_native_labels(monkeypatch, source):
    call_id = "00000000-0000-4000-8000-000000000003"
    pi = source != "service"
    kind = "compaction" if source == "pi-compaction" else "model"
    extra = {"executed_by": "pi", "llm_call_id": call_id, "call_kind": kind} if pi else {}
    with force_pending(monkeypatch):
        start = record({"provider": "provider-v1", "model": "model-v1", **extra}, ET.LLM_CALL_STARTED)
    end = record({**NUMBERS, **extra, **({} if pi else {"started_event_id": start})})
    final = rows()[0]
    assert final.event_id == end and final.started_event_id == start
    assert final.provider == (None if pi else "provider-v1")
    assert final.model is None  # a missing end model is never inherited
    assert final.prompt_tokens == 150
    assert drain(start).status == "drained"
    assert rows()[-1].event_id == start and rows()[-1].seq > final.seq


def test_pending_unknown_commit_and_real_pi_retry(monkeypatch):
    with force_pending(monkeypatch), unknown_commit_once(monkeypatch):
        first = mapper()
        first.handle_all(pi_events())
    assert event_count() == 2 and len(pending_rows()) == 2 and rows() == []
    mapper().handle_all(pi_events())
    assert event_count() == 2 and len(pending_rows()) == 2  # replay is not a retry
    first.handle_all(pi_events())
    assert event_count() == 4 and len(pending_rows()) == 2 and len(rows()) == 2


def test_pending_fork_copy_writes_neither_store(monkeypatch):
    wf = recorder.record(ET.WORKFLOW_STARTED, execution_id=EXEC)
    stage = recorder.record(ET.STAGE_STARTED, data={"name": "fixture"}, parent_id=wf, execution_id=EXEC)
    agent = recorder.record(ET.AGENT_STARTED, parent_id=stage, execution_id=EXEC)
    with force_pending(monkeypatch):
        record(parent_id=agent)
    before = [(row.event_id, row.revision) for row in pending_rows()]
    recorder.copy_events_for_fork(EXEC, str(uuid.uuid4()), {"fixture"})
    assert rows() == [] and [(row.event_id, row.revision) for row in pending_rows()] == before


def test_pending_insert_failure_rolls_back_event(monkeypatch):
    def fail(*args):
        raise RuntimeError("synthetic pending insert failure")
    with force_pending(monkeypatch), monkeypatch.context() as m:
        m.setattr(usage, "_queue_pending", fail)
        m.setattr(recorder.time, "sleep", lambda _: None)
        with pytest.raises(RuntimeError, match="synthetic pending insert failure"):
            record()
    assert event_count() == 0 and rows() == [] and pending_rows() == []


def assert_pending_capture_boundary(monkeypatch, boundary, different=False, event_id=None):
    if event_id is None:
        with force_pending(monkeypatch):
            event_id = record()
    snapshot = pending_rows()[0]
    candidate = usage.UsageCallRow(**snapshot.model_dump(exclude={"pending_at", "defer_reason"}))
    if different:
        candidate.prompt_tokens = 999
    caught = False
    with usage.sqlite_transaction_lock(), get_session() as session:
        session.exec(select(Event.id).where(Event.id == event_id).with_for_update()).one()
        try:
            if boundary == "capture":
                assert usage.write_or_queue_row(session, candidate) is None
            else:
                usage._queue_pending(session, candidate)
        except RuntimeError as error:
            assert str(error) == "usage observation conflict"
            assert not session.in_transaction(), "conflict must roll back the root transaction"
            caught = True
    assert caught is different
    after = pending_rows()
    assert len(after) == 1 and after[0].prompt_tokens == 150
    assert as_utc(after[0].pending_at) == as_utc(snapshot.pending_at) and rows() == []


@pytest.mark.parametrize("boundary", ["capture", "enqueue"])
@pytest.mark.parametrize("different", [False, True])
def test_existing_pending_capture_or_enqueue_is_idempotent_not_overwritten(monkeypatch, boundary, different):
    assert_pending_capture_boundary(monkeypatch, boundary, different)


@pytest.mark.parametrize("guard", ["capture-compare", "capture-rollback", "capture-return", "enqueue-compare", "enqueue-rollback"])
def test_pending_capture_boundary_guards_bite(monkeypatch, guard):
    # Compile mutations only AFTER fixture creation: mutated() snapshots globals.
    with force_pending(monkeypatch):
        event_id = record()
    if guard.startswith("capture"):
        if guard == "capture-return":
            mutated(monkeypatch, usage, "write_or_queue_row", "if existing_pending is not None:", "if False:")
        elif guard == "capture-compare":
            mutated(monkeypatch, usage, "write_or_queue_row", "if not _same_projection(existing_pending, expected):", "if False:")
        else:
            mutated(monkeypatch, usage, "write_or_queue_row", "session.rollback()", "pass")
        boundary = "capture"
    else:
        if guard == "enqueue-compare":
            mutated(monkeypatch, usage, "_queue_pending", "existing is None or not _same_projection(existing, pending)", "existing is None")
        else:
            mutated(monkeypatch, usage, "_queue_pending", "session.rollback()", "pass")
        boundary = "enqueue"
    with pytest.raises(AssertionError):
        assert_pending_capture_boundary(monkeypatch, boundary, different=guard != "capture-return", event_id=event_id)


def test_projection_utc_comparison_bites(monkeypatch):
    record()
    snapshot = rows()[0]
    candidate = usage.UsageCallRow(**snapshot.model_dump())
    candidate.event_at = as_utc(candidate.event_at)
    candidate.occurred_at = as_utc(candidate.occurred_at) if candidate.occurred_at else None
    def check():
        assert usage._same_projection(snapshot, candidate)
    check()
    mutated(monkeypatch, usage, "_same_projection", "result[field] = as_utc(result[field])", "result[field] = result[field]")
    with pytest.raises(AssertionError):
        check()


def test_pending_drain_rollback_and_unknown_commit(monkeypatch):
    with force_pending(monkeypatch):
        event_id = record()
    with pytest.raises(RuntimeError, match="synthetic rollback"):
        with usage.sqlite_transaction_lock(), get_session() as session:
            assert usage.drain_pending_row(session, event_id, 0).status == "drained"
            raise RuntimeError("synthetic rollback")
    assert rows() == [] and len(pending_rows()) == 1
    with unknown_commit_once(monkeypatch), pytest.raises(RuntimeError, match="acknowledgement lost"):
        drain(event_id)
    assert len(rows()) == 1 and pending_rows() == []
    assert drain(event_id).status == "missing" and len(rows()) == 1


def assert_drain_conflict(monkeypatch, different):
    with force_pending(monkeypatch):
        event_id = record()
    values = pending_rows()[0].model_dump(exclude={"pending_at", "defer_reason"})
    if different:
        values["prompt_tokens"] = 999
    # Known adversarial fixture, test database only. Never a live hand-write.
    with get_session() as session:
        session.add(usage.UsageCallRow(**values))
    caught = False
    with usage.sqlite_transaction_lock(), get_session() as session:
        try:
            outcome = usage.drain_pending_row(session, event_id, 0)
        except RuntimeError as error:
            assert str(error) == "usage observation conflict"
            assert not session.in_transaction(), "conflict must roll back the root transaction"
            caught = True
        # Deliberately catch INSIDE caller transaction: helper must rollback, not
        # merely raise then let a careless caller commit the DELETE CTE.
    assert caught is different
    if different:
        assert len(pending_rows()) == 1
    else:
        assert outcome.status == "already-final" and pending_rows() == []
    assert len(rows()) == 1


@pytest.mark.parametrize("different", [False, True])
def test_drain_conflict_equal_is_not_new_drain_different_retains_pending(monkeypatch, different):
    assert_drain_conflict(monkeypatch, different)


def assert_ordering_session_clean():
    caught = False
    with usage.sqlite_transaction_lock():
        with get_session() as session:
            event_id = str(uuid.uuid4())
            session.add(Event(id=event_id, type=ET.LLM_CALL_COMPLETED, data=NUMBERS,
                              timestamp=AT, execution_id=EXEC, parent_id=PARENT))
            def dirty_after_savepoint(conn, cursor, statement, parameters, context, many):
                if statement == usage._ORDERING_SAVEPOINT.text:
                    session.add(Event(type="stage.fixture"))
            sa_event.listen(get_database().engine, "after_cursor_execute", dirty_after_savepoint)
            try:
                try:
                    usage.write_or_queue_row(session, extract(NUMBERS, event_id=event_id))
                except RuntimeError as error:
                    assert str(error) == "usage ordering session not clean"
                    session.rollback()
                    caught = True
            finally:
                sa_event.remove(get_database().engine, "after_cursor_execute", dirty_after_savepoint)
    assert caught
    assert event_count() == 0 and rows() == []


def test_no_unflushed_state_can_enter_raw_savepoint():
    assert_ordering_session_clean()


def assert_no_autoflush_in_savepoint(monkeypatch):
    event_id = record()
    snapshot = rows()[0]
    expected_seq = snapshot.seq
    candidate = usage.UsageCallRow(**snapshot.model_dump(exclude={"seq"}))
    candidate.event_at = as_utc(candidate.event_at)
    candidate.occurred_at = as_utc(candidate.occurred_at) if candidate.occurred_at else None
    with usage.sqlite_transaction_lock(), get_session() as session:
        session.exec(select(Event.id).where(Event.id == event_id).with_for_update()).one()
        original = session.flush
        window = False
        def flush(*args, **kwargs):
            assert not window, "ORM flush in raw savepoint window"
            return original(*args, **kwargs)
        def before(conn, cursor, statement, parameters, context, many):
            nonlocal window
            if statement == usage._ORDERING_SAVEPOINT.text:
                window = True
        with monkeypatch.context() as m:
            m.setattr(session, "flush", flush)
            sa_event.listen(get_database().engine, "before_cursor_execute", before)
            try:
                assert usage.write_or_queue_row(session, candidate) == expected_seq
            finally:
                sa_event.remove(get_database().engine, "before_cursor_execute", before)


def test_no_autoflush_even_on_conflict_read(monkeypatch):
    assert_no_autoflush_in_savepoint(monkeypatch)


def postgres_stage(record_property):
    real = get_database().engine.dialect.name == "postgresql"
    record_property("usage_real_postgres_stage", real)
    return real


@contextmanager
def held_ordering_lock(seconds=3):
    acquired = threading.Event()
    def hold():
        with get_database().engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": usage.COMMIT_ORDER_LOCK})
            acquired.set()
            try:
                threading.Event().wait(seconds)  # fixed, declared fault-injection duration
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": usage.COMMIT_ORDER_LOCK})
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold)
        assert acquired.wait(2), "test holder did not start"
        try:
            yield
        finally:
            future.result(timeout=seconds + 2)


def assert_real_lock_timeout(monkeypatch):
    db = get_database()
    original = db.session
    settings = []
    @contextmanager
    def session():
        with original() as s:
            s.execute(text("SET LOCAL lock_timeout = '777ms'"))
            s.execute(text("SET LOCAL idle_in_transaction_session_timeout = '9s'"))
            yield s
            settings.append(s.execute(text("SELECT current_setting('lock_timeout'), "
                                           "current_setting('idle_in_transaction_session_timeout')")).one())
            assert s.execute(text("SELECT 1")).scalar_one() == 1
    with held_ordering_lock(), monkeypatch.context() as m:
        m.setattr(db, "session", session)
        start = time.monotonic()
        event_id = record()
        elapsed = time.monotonic() - start
    assert elapsed < 2.5 and event_count() == 1
    assert settings == [("777ms", "9s")]
    assert rows() == [] and len(pending_rows()) == 1
    assert drain(event_id).status == "drained" and pending_rows() == []


def test_real_pg_three_second_holder_captures_before_two_point_five(monkeypatch, record_property):
    if postgres_stage(record_property):
        assert_real_lock_timeout(monkeypatch)
    else:
        assert usage._ordering_timeout(DBAPIError("", {}, SimpleNamespace(pgcode="55P03")))


def test_real_pg_drain_under_held_lock_keeps_pending(monkeypatch, record_property):
    if not postgres_stage(record_property):
        assert_pending_happy_path(monkeypatch)
        return
    with force_pending(monkeypatch):
        event_id = record()
    prior = record()
    prior_seq = rows()[0].seq
    with held_ordering_lock():
        outcome = drain(event_id)
    assert outcome.status == "deferred" and outcome.seq is None
    assert len(pending_rows()) == 1 and [row.event_id for row in rows()] == [prior]
    outcome = drain(event_id)
    assert outcome.status == "drained" and outcome.seq > prior_seq
    assert drain(event_id).status == "missing"


def assert_event_lock_before_drain(monkeypatch):
    with force_pending(monkeypatch):
        event_id = record()
    with Session(get_database().engine) as holder:
        holder.exec(select(Event.id).where(Event.id == event_id).with_for_update()).one()
        assert drain(event_id).status == "busy"
        assert len(pending_rows()) == 1 and rows() == []


def test_real_pg_drain_skips_locked_correction(monkeypatch, record_property):
    if postgres_stage(record_property):
        assert_event_lock_before_drain(monkeypatch)
    else:
        assert_pending_happy_path(monkeypatch)


@pytest.mark.timeout(20)
def test_real_pg_idle_frozen_recorder_killed_and_retry_preserved(monkeypatch, record_property):
    if not postgres_stage(record_property):
        assert_pending_happy_path(monkeypatch)
        return
    db = get_database()
    # Match create_all startup: otherwise the waiter blocks on cold singleton
    # insertion BEFORE the ordering timeout, testing a different lock entirely.
    with get_session() as session:
        usage.ensure_instance(session)
    original = db.session
    frozen, resume = threading.Event(), threading.Event()
    holder_pid = []
    once = False
    @contextmanager
    def session():
        nonlocal once
        with original() as s:
            this_holder = threading.current_thread().name.startswith("usage-frozen") and not once
            if this_holder:
                once = True
                holder_pid.append(s.execute(text("SELECT pg_backend_pid()")).scalar_one())
            yield s
            if this_holder:
                frozen.set()  # INSERT done, COMMIT intentionally withheld
                assert resume.wait(8), "test did not release its frozen recorder"
    with monkeypatch.context() as m, ThreadPoolExecutor(max_workers=1, thread_name_prefix="usage-frozen") as pool:
        m.setattr(db, "session", session)
        m.setattr(recorder.time, "sleep", lambda _: None)
        first = pool.submit(record)
        try:
            assert frozen.wait(2)
            started = time.monotonic()
            pending_id = record()
            capture_ms = (time.monotonic() - started) * 1000
            record_property("usage_frozen_capture_ms", capture_ms)
            assert capture_ms < 2500
            assert rows() == [] and len(pending_rows()) == 1
            # Wait a FIXED remaining interval, not polling for a favorable result.
            threading.Event().wait(max(0, 5.6 - (time.monotonic() - started)))
            with get_session() as s:
                live = s.execute(text("SELECT count(*) FROM pg_stat_activity WHERE pid = :pid"),
                                 {"pid": holder_pid[0]}).scalar_one()
            absent_at_ms = (time.monotonic() - started) * 1000
            record_property("usage_frozen_holder_absent_at_ms", absent_at_ms)
            assert live == 0 and absent_at_ms < 6500
            later_id = record()
        finally:
            resume.set()
        first_id = first.result(timeout=3)
    assert event_count() == 3
    assert {row.event_id for row in rows()} == {first_id, later_id}
    assert drain(pending_id).status == "drained"
    assert len(rows()) == 3 and pending_rows() == []


def assert_pg_error_not_queued(monkeypatch, code="57014", target="ordering"):
    def replace(conn, cursor, statement, parameters, context, many):
        match = "WITH commit_order" in statement if target == "ordering" else statement == usage._ORDERING_SETTINGS.text
        if match:
            # A real server SQLSTATE, not a fake Python exception; no user inputs.
            return f"DO $$ BEGIN RAISE EXCEPTION USING ERRCODE = '{code}', MESSAGE = 'numeric stage rejection'; END $$", {}
        return statement, parameters
    with monkeypatch.context() as m:
        m.setattr(recorder.time, "sleep", lambda _: None)
        sa_event.listen(get_database().engine, "before_cursor_execute", replace, retval=True)
        caught = False
        try:
            try:
                record()
            except DBAPIError as error:
                assert error.orig.pgcode == code
                caught = True
        finally:
            sa_event.remove(get_database().engine, "before_cursor_execute", replace)
    assert caught and event_count() == 0 and rows() == [] and pending_rows() == []


@pytest.mark.parametrize("code", ["57014", "40P01", "23505", "22012"])
def test_real_pg_non_lock_failures_roll_back_event(monkeypatch, record_property, code):
    if postgres_stage(record_property):
        assert_pg_error_not_queued(monkeypatch, code)
    else:
        assert not usage._ordering_timeout(DBAPIError("", {}, SimpleNamespace(pgcode=code)))


def test_real_pg_55p03_outside_ordering_statement_is_not_queued(monkeypatch, record_property):
    if postgres_stage(record_property):
        assert_pg_error_not_queued(monkeypatch, "55P03", "settings")
    else:
        assert not usage._ordering_timeout(DBAPIError("", {}, SimpleNamespace(pgcode=None)))


def assert_statement_timeout_guard():
    caught = False
    try:
        with get_session() as session:
            session.execute(text("SET LOCAL statement_timeout = '1s'"))
            event_id = str(uuid.uuid4())
            session.add(Event(id=event_id, type=ET.LLM_CALL_COMPLETED, data=NUMBERS,
                              timestamp=AT, execution_id=EXEC, parent_id=PARENT))
            usage.write_or_queue_row(session, extract(NUMBERS, event_id=event_id))
    except RuntimeError as error:
        assert str(error) == "usage statement timeout incompatible"
        caught = True
    assert caught and event_count() == 0 and rows() == [] and pending_rows() == []


def assert_no_deferred_schema(session):
    names = ("events", "usage_call_rows", "usage_pending", "usage_source_instance")
    if session.get_bind().dialect.name != "postgresql":
        for name in names:
            assert all(not getattr(constraint, "deferrable", False)
                       for constraint in usage.UsageCallRow.metadata.tables[name].constraints)
        return
    count = session.execute(text("""
        SELECT count(*) FROM (
          SELECT conrelid AS rel FROM pg_constraint WHERE condeferrable
          UNION ALL
          SELECT tgrelid AS rel FROM pg_trigger WHERE tgdeferrable OR tginitdeferred
        ) d JOIN pg_class c ON c.oid = d.rel
        WHERE c.relnamespace = current_schema()::regnamespace
          AND c.relname IN ('events','usage_call_rows','usage_pending','usage_source_instance')
    """)).scalar_one()
    assert count == 0, "commit-time constraint or trigger"


def test_real_pg_statement_timeout_and_no_commit_time_constraints(record_property):
    real = postgres_stage(record_property)
    with get_session() as session:
        assert_no_deferred_schema(session)
        if real:
            session.execute(text("ALTER TABLE usage_pending ADD CONSTRAINT stage_deferred "
                                 "UNIQUE (event_id,revision,instance) DEFERRABLE INITIALLY DEFERRED"))
            with pytest.raises(AssertionError, match="commit-time constraint"):
                assert_no_deferred_schema(session)
            session.execute(text("ALTER TABLE usage_pending DROP CONSTRAINT stage_deferred"))
    if real:
        assert_statement_timeout_guard()


def assert_bad_pending_source(monkeypatch, kind):
    with force_pending(monkeypatch):
        event_id = record()
    with get_session() as session:
        if kind == "instance":
            session.get(usage.UsagePending, (event_id, 0)).instance = str(uuid.uuid4())
        else:
            session.execute(text("DELETE FROM events WHERE id = :id"), {"id": event_id})
    caught = False
    try:
        drain(event_id)
    except RuntimeError as error:
        assert str(error) == f"usage pending {'instance mismatch' if kind == 'instance' else 'event missing'}"
        caught = True
    assert caught and len(pending_rows()) == 1 and rows() == []


@pytest.mark.parametrize("kind", ["instance", "event"])
def test_pending_wrong_instance_or_orphan_is_never_published(monkeypatch, kind):
    assert_bad_pending_source(monkeypatch, kind)


@pytest.mark.parametrize("guard", ["clean-session", "no-autoflush", "conflict-compare", "conflict-rollback",
                                   "pending-revision", "durable-evidence", "instance", "event"])
def test_pending_shared_guard_bites(monkeypatch, guard):
    if guard == "clean-session":
        mutated(monkeypatch, usage, "_append_final", "if session.new or session.dirty or session.deleted:", "if False:")
        check = assert_ordering_session_clean
    elif guard == "no-autoflush":
        mutated(monkeypatch, usage, "_append_final", "with session.no_autoflush:", "with nullcontext():")
        check = partial(assert_no_autoflush_in_savepoint, monkeypatch)
    elif guard == "conflict-compare":
        mutated(monkeypatch, usage, "_append_final", "existing is None or not _same_projection(existing, row)", "existing is None")
        check = partial(assert_drain_conflict, monkeypatch, True)
    elif guard == "conflict-rollback":
        mutated(monkeypatch, usage, "_append_final", "session.rollback()", "pass")
        check = partial(assert_drain_conflict, monkeypatch, True)
    elif guard == "pending-revision":
        mutated(monkeypatch, usage, "next_revision", "select(UsagePending.revision).where(UsagePending.event_id == event_id)",
                "select(UsageCallRow.revision).where(UsageCallRow.event_id == event_id)")
        check = partial(assert_pending_revisions, monkeypatch)
    elif guard == "durable-evidence":
        mutated(monkeypatch, usage, "_queue_pending", ' | {"ordering-deferred"}', '')
        check = partial(assert_pending_happy_path, monkeypatch)
    else:
        old = "pending.instance != ensure_instance(session)" if guard == "instance" else "exists is None"
        mutated(monkeypatch, usage, "drain_pending_row", f"if {old}:", "if False:")
        check = partial(assert_bad_pending_source, monkeypatch, guard)
    with pytest.raises(AssertionError):
        check()


@pytest.mark.parametrize("guard", ["catch-only-55p03", "event-first", "settings-position", "idle-holder", "statement-timeout"])
def test_pending_real_pg_guard_bites(monkeypatch, record_property, guard):
    if not postgres_stage(record_property):
        assert usage._ordering_timeout(DBAPIError("", {}, SimpleNamespace(pgcode="55P03")))
        return
    if guard == "catch-only-55p03":
        mutated(monkeypatch, usage, "_ordering_timeout", 'return getattr(error.orig, "pgcode", None) == "55P03"', "return True")
        check = partial(assert_pg_error_not_queued, monkeypatch)
    elif guard == "event-first":
        mutated(monkeypatch, usage, "drain_pending_row", ".with_for_update(skip_locked=True)", "")
        check = partial(assert_event_lock_before_drain, monkeypatch)
    elif guard == "settings-position":
        old = '''with session.no_autoflush:
        session.execute(_ORDERING_SAVEPOINT)
        if session.new or session.dirty or session.deleted:
            raise RuntimeError("usage ordering session not clean")
        if postgres:
            # AFTER savepoint: a timeout rollback restores BOTH previous settings.
            session.execute(_ORDERING_SETTINGS)'''
        new = '''if postgres:
        session.execute(_ORDERING_SETTINGS)
    with session.no_autoflush:
        session.execute(_ORDERING_SAVEPOINT)
        if session.new or session.dirty or session.deleted:
            raise RuntimeError("usage ordering session not clean")'''
        mutated(monkeypatch, usage, "_append_final", old, new)
        check = partial(assert_real_lock_timeout, monkeypatch)
    elif guard == "statement-timeout":
        mutated(monkeypatch, usage, "_append_final", "if 0 < timeout <= 2000:", "if False:")
        check = assert_statement_timeout_guard
    else:
        # Bounded version of frozen-holder mutant: verify server setting at the
        # statement, not a 5s passive wait repeated with an intentionally immortal
        # backend. Clean frozen/retry stage above proves actual server behavior.
        monkeypatch.setattr(usage, "_ORDERING_SETTINGS", text("SELECT set_config('lock_timeout','2s',true)"))
        def check():
            seen = []
            def inspect_setting(conn, cursor, statement, parameters, context, many):
                if "WITH commit_order" in statement:
                    seen.append(conn.execute(text("SELECT current_setting('idle_in_transaction_session_timeout')")).scalar_one())
            sa_event.listen(get_database().engine, "before_cursor_execute", inspect_setting)
            try:
                record()
            finally:
                sa_event.remove(get_database().engine, "before_cursor_execute", inspect_setting)
            assert seen == ["5s"]
    with pytest.raises(AssertionError):
        check()
