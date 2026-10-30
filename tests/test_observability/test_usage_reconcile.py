"""Known-answer stages, SQLite and isolated Postgres5455; no workflow/model calls."""
from __future__ import annotations

import ast
import hashlib
import inspect
import logging
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import String, cast, func, literal, text, update
from sqlalchemy import event as sa_event
from sqlalchemy import select as sql_select
from sqlmodel import col, select

from temper_ai.database import get_database, get_session
from temper_ai.observability import usage_reconcile as reconcile
from temper_ai.observability import usage_rows as usage
from temper_ai.observability.models import Event
from temper_ai.runner.models import WorkflowRun
from temper_ai.shared.clock import as_utc

NOW = datetime(2026, 10, 21, 18, tzinfo=UTC)
VALUES = {"provider": "provider-v1", "model": "model-v1", "prompt_tokens": 10,
          "completion_tokens": 2, "total_tokens": 12, "cost_usd": 0.1}


@pytest.fixture(autouse=True)
def bounded_fixture(monkeypatch, _test_db):
    monkeypatch.setenv("TEMPER_USAGE_RECONCILER", "1")
    # Most cases here judge the cutover itself; the switch's own tests clear it.
    monkeypatch.setenv("TEMPER_USAGE_CUTOVER", "1")
    reconcile._stop.clear()
    monkeypatch.setattr(reconcile, "BATCH_PAUSE_SECONDS", 0)
    monkeypatch.setattr(reconcile, "_last_blocker_report", None)
    if get_database().engine.dialect.name == "postgresql":
        with get_session() as session:
            schema = session.execute(text("SELECT current_schema()")).scalar_one()
        key = int.from_bytes(hashlib.sha256(schema.encode()).digest()[:8], "big", signed=True)
        monkeypatch.setattr(usage, "COMMIT_ORDER_LOCK", key)
    yield
    reconcile._stop.clear()


def old(data=None, *, at=NOW, kind="llm.call.completed", execution_id=None, parent_id=None, event_id=None):
    event = Event(id=event_id or str(uuid.uuid4()), type=kind, timestamp=at, data=VALUES if data is None else data,
                  execution_id=execution_id, parent_id=parent_id)
    with usage.sqlite_transaction_lock(), get_session() as session:
        session.add(event)
        session.flush()
        session.expunge(event)
    return event


def capture(event, *, pending=False, revision=0, origin="live", row_changes=None):
    row = usage.extract(event.type, event.data, {"event_id": event.id, "execution_id": event.execution_id,
                        "parent_id": event.parent_id}, event.timestamp)
    assert row is not None
    row.revision = revision
    row.origin = origin
    for key, value in (row_changes or {}).items():
        setattr(row, key, value)
    with usage.sqlite_transaction_lock(), get_session() as session:
        session.exec(select(Event.id).where(Event.id == event.id).with_for_update()).one()
        if pending:
            row.instance = usage.ensure_instance(session)
            usage._link_start(session, row)
            usage._queue_pending(session, row)
        else:
            usage.write_or_queue_row(session, row)
    return row


def fixed_clock(monkeypatch, now=NOW):
    monkeypatch.setattr(reconcile, "_db_now", lambda session: now)


def final_rows():
    with get_session() as session:
        rows = list(session.exec(select(usage.UsageCallRow).order_by(col(usage.UsageCallRow.seq))).all())
        session.expunge_all()
        return rows


def native_terminal(execution_id, *, status="completed", minutes=16, root_status="completed"):
    root = old({}, at=NOW - timedelta(days=1), kind="workflow.started", execution_id=execution_id)
    with get_session() as session:
        session.get(Event, root.id).status = root_status
        session.add(WorkflowRun(execution_id=execution_id, workflow_name="fixed-fixture", workspace_path="/fixture",
                               status=status, completed_at=None if minutes is None else NOW - timedelta(minutes=minutes)))
    return root


def mutate_function(monkeypatch, function, before, after):
    """Remove one actual guard in memory; never edit source, DB schema or live state."""
    source = inspect.getsource(function)
    assert source.count(before) == 1, before
    namespace = dict(vars(reconcile))
    exec(compile(source.replace(before, after, 1), function.__code__.co_filename, "exec"), namespace)
    monkeypatch.setattr(reconcile, function.__name__, namespace[function.__name__])


def test_combined_happy_path_capture_drain_backfill_cutover_fault_unknown(monkeypatch):
    """Opening whole-feature path; all inputs numeric, no private/runtime data."""
    fixed_clock(monkeypatch)
    legacy = old(at=NOW - timedelta(days=1))
    pending = old(at=NOW - timedelta(minutes=1))
    capture(pending, pending=True)
    native_terminal("finished-service")
    started = old({"provider": "provider-v1", "model": "model-v1", "call_kind": "model"},
                  kind="llm.call.started", execution_id="finished-service", at=NOW - timedelta(hours=1))
    capture(started)
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    with get_session() as session:
        assert reconcile.reconcile_batch(session) == 1
        assert reconcile.reconcile_batch(session) == 0
        assert {r.event_id for r in final_rows()} == {legacy.id, started.id}
        assert reconcile.drain_pending(session)["drained"] == 1
        assert reconcile.drain_state(session)["pending_count"] == 0
        assert reconcile.mark_unended(session) == 1
        assert reconcile.mark_unended(session) == 0
        assert reconcile.try_cutover(session)
        first = reconcile.coverage_state(session)
        assert first["status"] == "UNKNOWN" and first["cutover_at"] == NOW
    later = old(at=NOW + timedelta(seconds=1))
    captured_later = old(at=NOW + timedelta(seconds=2))
    capture(captured_later, pending=True)
    late_end = old({**VALUES, "started_event_id": started.id, "call_kind": "model"},
                   at=NOW + timedelta(seconds=3), execution_id="finished-service")
    capture(late_end)
    with get_session() as session:
        assert reconcile.mark_unended(session) == 1
        assert reconcile.mark_unended(session) == 0
        assert reconcile.reconcile_batch(session) == 0  # no silent post-cutover fill
        assert reconcile.check_post_cutover(session) == 1
        assert reconcile.check_post_cutover(session) == 0
        state = reconcile.coverage_state(session)
        assert state["status"] == "UNKNOWN" and state["cutover_at"] == first["cutover_at"]
        assert state["fault_counts"]["post-cutover-missing-row"] == 1
        assert session.exec(select(reconcile.UsageFault.event_id)).all() == [later.id]
        assert reconcile.drain_pending(session)["drained"] == 1
        assert reconcile.drain_pending(session)["attempted"] == 0
        heartbeat = session.get(reconcile.UsageDrainHeartbeat, 1)
        assert heartbeat.outcome == "empty" and heartbeat.last_drain_at is not None
    rows = final_rows()
    assert len(rows) == len({(r.event_id, r.revision) for r in rows}) == 7
    assert next(r for r in rows if r.event_id == legacy.id).origin == "reconciled"
    revisions = [r for r in rows if r.event_id == started.id]
    assert [r.revision for r in revisions] == [0, 1, 2]
    assert ["call-unended" in r.fault_codes for r in revisions] == [False, True, False]
    assert revisions[1].occurrence_basis == "call_start" and revisions[1].total_tokens is None
    assert revisions[1].legacy_cost_usd is None and "call-unended" in usage.FAULT_CODES


def test_typed_oldest_first_rotation_busy_does_not_starve(monkeypatch):
    fixed_clock(monkeypatch)
    events = [old(at=NOW - timedelta(minutes=i), event_id=name) for i, name in enumerate(("z", "a", "m"))]
    for event in events:
        capture(event, pending=True)
    with get_session() as session:
        for event, minutes in zip(events, (3, 2, 1), strict=True):
            pending = session.get(usage.UsagePending, (event.id, 0))
            pending.pending_at = NOW - timedelta(minutes=minutes)
            session.add(pending)
    actual = usage.drain_pending_row
    attempted = []
    def drain(session, event_id, revision):
        attempted.append(event_id)
        if event_id in ("z", "a"):
            return usage.DrainOutcome("busy")
        return actual(session, event_id, revision)
    monkeypatch.setattr(usage, "drain_pending_row", drain)
    monkeypatch.setattr(reconcile, "MAX_BATCH", 2)
    with get_session() as session:
        assert reconcile.drain_pending(session)["busy"] == 2
        state = reconcile.drain_state(session)
        assert state["outcome"] == "busy" and state["pending_count"] == 3
        assert reconcile.drain_pending(session)["drained"] == 1
        assert attempted == ["z", "a", "m"]  # UUID lexical order is NOT the clock.
        assert reconcile.drain_pending(session)["busy"] == 2  # wraps, not permanent exclusion
        assert reconcile.drain_state(session)["pending_count"] == 2


@pytest.mark.parametrize("outcome", ["busy", "deferred", "already-final", "missing", "fault"])
def test_completed_non_success_attempt_heartbeat_and_pending_evidence(monkeypatch, outcome):
    fixed_clock(monkeypatch)
    event = old()
    capture(event, pending=True)
    def result(session, event_id, revision):
        if outcome == "fault":
            raise RuntimeError("fixed test failure")
        return usage.DrainOutcome(outcome)
    monkeypatch.setattr(usage, "drain_pending_row", result)
    with get_session() as session:
        counts = reconcile.drain_pending(session)
        state = reconcile.drain_state(session)
        assert counts["drained"] == 0 and state["pending_count"] == 1
        assert state["last_drain_at"] == NOW
        assert state["outcomes"]["attempted"] == 1
        assert state["outcomes"]["remaining"] == 1
        assert state["outcomes"][outcome.replace("-", "_") if outcome != "fault" else "faulted"] == 1
        assert reconcile.coverage_state(session)["status"] == "UNKNOWN"


def test_off_and_old_pending_fresh_silent_are_independent_pure_reads(monkeypatch):
    fixed_clock(monkeypatch)
    event = old()
    capture(event, pending=True)
    with get_session() as session:
        pending = session.get(usage.UsagePending, (event.id, 0))
        pending.pending_at = NOW - timedelta(minutes=16)
        session.add(pending)
    monkeypatch.setenv("TEMPER_USAGE_RECONCILER", "0")
    statements = []
    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    sa_event.listen(get_database().engine, "before_cursor_execute", before)
    try:
        with get_session() as session:
            assert reconcile.drain_pending(session)["attempted"] == 0
            assert reconcile.reconcile_batch(session) == 0
            assert not reconcile.try_cutover(session)
            assert reconcile.check_post_cutover(session) == 0
            assert not reconcile.start()
            state = reconcile.drain_state(session)
            assert state["codes"] == ["pending-old", "drain-silent", "drain-off"]
            assert state["last_drain_at"] is None and not state["enabled"]
            assert reconcile.coverage_state(session)["status"] == "UNKNOWN"
        assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
    finally:
        sa_event.remove(get_database().engine, "before_cursor_execute", before)
    monkeypatch.setenv("TEMPER_USAGE_RECONCILER", "1")
    monkeypatch.setattr(usage, "drain_pending_row", lambda *args: usage.DrainOutcome("busy"))
    with get_session() as session:
        reconcile.drain_pending(session)
        assert reconcile.drain_state(session)["codes"] == ["pending-old"]
        assert reconcile.drain_state(session)["stalled"]
        assert reconcile.drain_state(session)["clock_provenance"]["oldest_pending_at"] == "application-record-construction"


def test_hung_aborted_and_failed_heartbeat_persistence_do_not_advance(monkeypatch):
    fixed_clock(monkeypatch)
    with get_session() as session:
        reconcile.drain_pending(session)
    fixed_clock(monkeypatch, NOW + timedelta(minutes=1))
    capture(old(), pending=True)
    def abort(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(usage, "drain_pending_row", abort)
    with get_session() as session:
        with pytest.raises(KeyboardInterrupt):
            reconcile.drain_pending(session)
        session.rollback()
        assert as_utc(session.get(reconcile.UsageDrainHeartbeat, 1).last_drain_at) == NOW


def test_read_states_never_flush_callers_dirty_event(monkeypatch):
    fixed_clock(monkeypatch)
    writes = []
    def before(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)
    sa_event.listen(get_database().engine, "before_cursor_execute", before)
    try:
        with get_session() as session:
            uncommitted = Event(type="fixed.fixture", data={})
            session.add(uncommitted)
            assert reconcile.coverage_state(session)["status"] == "UNKNOWN"
            assert reconcile.drain_state(session)["pending_count"] == 0
            assert uncommitted in session.new and not writes
            session.rollback()
    finally:
        sa_event.remove(get_database().engine, "before_cursor_execute", before)


def test_db_completion_clock_is_not_transaction_start():
    with get_session() as session:
        started = reconcile._db_now(session)
        time.sleep(0.015)  # fixed test input, not a queue/CI polling wait
        ended = reconcile._db_now(session)
        assert (ended - started).total_seconds() >= 0.010


def test_zero_budget_is_completed_but_never_claims_drained(monkeypatch):
    fixed_clock(monkeypatch)
    capture(old(), pending=True)
    with get_session() as session:
        assert reconcile.drain_pending(session, budget=0)["attempted"] == 0
        state = reconcile.drain_state(session)
        assert state["pending_count"] == 1 and state["outcome"] == "budget"
        assert state["outcomes"]["drained"] == 0 and state["last_drain_at"] == NOW


def test_failed_heartbeat_write_does_not_publish_new_completion(monkeypatch):
    fixed_clock(monkeypatch)
    with get_session() as session:
        reconcile.drain_pending(session)
    fixed_clock(monkeypatch, NOW + timedelta(minutes=1))
    capture(old(), pending=True)
    actual = reconcile._insert
    def fail(session, model):
        if model is reconcile.UsageDrainHeartbeat:
            raise RuntimeError("fixed heartbeat persistence failure")
        return actual(session, model)
    monkeypatch.setattr(reconcile, "_insert", fail)
    with get_session() as session:
        with pytest.raises(RuntimeError, match="fixed heartbeat persistence failure"):
            reconcile.drain_pending(session)
        session.rollback()
        assert reconcile.drain_state(session)["last_drain_at"] == NOW
        assert reconcile.drain_state(session)["pending_count"] == 0  # committed helper, not fake heartbeat


def test_malformed_scalar_leaves_never_load_nested_content(monkeypatch):
    fixed_clock(monkeypatch)
    event = old({**VALUES, "provider": {"private": "CANARY_PROVIDER"},
                 "prompt_tokens": {"private": "CANARY_TOKEN"}, "cost_usd": ["CANARY_COST"],
                 "lost_attempts": {"private": "CANARY_LOST"}})
    with get_session() as session:
        raw = session.execute(reconcile._eligible(session, NOW)).mappings().one()
        assert "CANARY" not in repr(dict(raw))
        assert reconcile.reconcile_batch(session) == 1
    row = final_rows()[0]
    assert row.event_id == event.id and row.prompt_tokens is None and row.legacy_cost_usd is None
    assert {"provider-invalid", "prompt-invalid", "cost-invalid", "lost-invalid"} <= set(row.fault_codes.split(","))


def projects_whole_event_data(statement):
    """Audit projected columns, not raw-data operands of safe SQL path/type calls."""
    columns = getattr(statement, "selected_columns", None)
    if columns is None:
        return True  # an opaque textual SELECT is not leaf-only evidence
    def forbidden(column):
        while column.__visit_name__ in ("label", "grouping", "type_coerce", "cast"):
            column = column.clause if column.__visit_name__ == "cast" else column.element
        if getattr(column, "selected_columns", None) is not None:
            return projects_whole_event_data(column)
        if column.__visit_name__ == "scalar_select":
            return projects_whole_event_data(column.element)
        return column.shares_lineage(Event.__table__.c.data)
    return any(forbidden(column) for column in columns)


def test_projection_audit_known_catch_and_clean_ast_cases_without_fetching_data():
    clean = [select(Event.id), select(Event.data["model"].as_string()),
             select(func.json_type(Event.data, "$.model")), select(cast(Event.data["model"], String))]
    catch = [select(Event.data), select(Event), select(Event.data.label("hidden")),
             select(cast(Event.data, String)), select(select(Event).subquery()),
             select(select(Event.data).scalar_subquery()), text("SELECT data FROM events")]
    assert all(not projects_whole_event_data(statement) for statement in clean)
    assert all(projects_whole_event_data(statement) for statement in catch)


def test_history_current_first_previous_only_dst_and_leaf_canaries(monkeypatch):
    fixed_clock(monkeypatch)
    start = reconcile._history_start(NOW)
    current = reconcile.pacific_week_start(NOW)
    prior = old(at=start)
    today = old({**VALUES, "lost_attempts": [{"private": "CONTENT_CANARY"}],
                 "messages": ["CONTENT_CANARY"], "output": "CONTENT_CANARY"}, at=current)
    old(at=start - timedelta(microseconds=1))
    old({**VALUES, "restored_from_fork": True})
    capture(old(), pending=True)
    selected = []
    def before(conn, cursor, statement, parameters, context, executemany):
        if "events" in statement.lower() and statement.lstrip().upper().startswith("SELECT"):
            selected.append(projects_whole_event_data(context.compiled.statement))
    sa_event.listen(get_database().engine, "before_cursor_execute", before)
    try:
        with get_session() as session:
            assert reconcile.reconcile_batch(session, limit=1) == 1
            assert final_rows()[0].event_id == today.id
            assert reconcile.reconcile_batch(session) == 1
    finally:
        sa_event.remove(get_database().engine, "before_cursor_execute", before)
    rows = final_rows()
    assert {r.event_id for r in rows} == {today.id, prior.id}
    assert rows[0].lost_attempts == 1
    assert "CONTENT_CANARY" not in repr([r.model_dump() for r in rows])
    assert selected and not any(selected)
    # DST fall-back: previous Monday midnight is offset-07, current offset-08.
    november = datetime(2026, 11, 3, 12, tzinfo=UTC)
    assert reconcile.pacific_week_start(november).hour == 8
    assert reconcile._history_start(november).hour == 7
    assert (reconcile.pacific_week_start(november) - reconcile._history_start(november)).total_seconds() == 169 * 3600


@pytest.mark.parametrize("guard", ["pending", "final", "fork", "history"])
def test_selection_guards_have_individual_bites(monkeypatch, guard):
    fixed_clock(monkeypatch)
    event = old({**VALUES, **({"restored_from_fork": True} if guard == "fork" else {})},
                at=reconcile._history_start(NOW) - timedelta(seconds=1) if guard == "history" else NOW)
    if guard in ("pending", "final"):
        capture(event, pending=guard == "pending")
    with get_session() as session:
        def assert_excluded():
            assert session.execute(reconcile._eligible(session, NOW)).first() is None
        assert_excluded()
        if guard in ("pending", "final"):
            actual = reconcile._not_captured
            monkeypatch.setattr(reconcile, "_not_captured", lambda: (actual()[0 if guard == "pending" else 1],))
        elif guard == "fork":
            monkeypatch.setattr(reconcile, "_not_fork", lambda session: True)
        else:
            monkeypatch.setattr(reconcile, "_history_start", lambda now: NOW - timedelta(days=100))
        with pytest.raises(AssertionError):
            assert_excluded()


@pytest.mark.parametrize("status", ["running", "queued", "waiting", None, "orphaned"])
def test_cutover_waits_for_all_three_kinds_and_every_earlier_execution(monkeypatch, status):
    fixed_clock(monkeypatch)
    root = old({}, at=NOW - timedelta(days=30), kind="workflow.started", execution_id="old-execution")
    with get_session() as session:
        event = session.get(Event, root.id)
        event.status = status
        session.add(event)
    for kind in ("server", "worker"):
        reconcile.mark_ready(kind)
    with get_session() as session:
        assert not reconcile.try_cutover(session)
    reconcile.mark_ready("pi-worker")
    with get_session() as session:
        assert not reconcile.try_cutover(session)  # even parked/history-excluded executions
        event = session.get(Event, root.id)
        event.status = "interrupted"
        session.add(event)
        session.commit()
        assert not reconcile.try_cutover(session)  # requires a new full final lap
        assert reconcile.reconcile_batch(session) == 0
        assert reconcile.try_cutover(session)
        first = reconcile.coverage_state(session)
    fixed_clock(monkeypatch, NOW + timedelta(days=1))
    reconcile.mark_ready("worker")
    with get_session() as session:
        assert reconcile.try_cutover(session)
        assert reconcile.coverage_state(session)["cutover_at"] == first["cutover_at"]
    with pytest.raises(ValueError, match="usage writer kind invalid"):
        reconcile.mark_ready("other")


def test_cutover_final_pass_and_fault_cap_overflow(monkeypatch):
    fixed_clock(monkeypatch)
    legacy = old()
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    with get_session() as session:
        assert not reconcile.try_cutover(session)
        assert reconcile.reconcile_batch(session) == 1
        assert reconcile.try_cutover(session)
    for _ in range(3):
        old(at=NOW + timedelta(seconds=1))  # rollback-style old writer has same fault rule
    monkeypatch.setattr(reconcile, "FAULT_CAP", 2)
    with get_session() as session:
        reconcile.check_post_cutover(session)
        state = reconcile.coverage_state(session)
        assert state["fault_counts"]["post-cutover-missing-row"] == 2
        assert state["fault_overflow"] == 1
        assert len(final_rows()) == 1 and final_rows()[0].event_id == legacy.id
        assert state["status"] == "UNKNOWN" and "complete_through" not in state


def test_reconciler_live_writer_race_rechecks_after_event_lock(monkeypatch):
    fixed_clock(monkeypatch)
    event = old()
    with get_session() as session:
        actual = session.commit
        calls = 0
        def commit():
            nonlocal calls
            actual()
            calls += 1
            if calls == 2:  # candidate snapshot ended, BEFORE reconciler's Event lock
                capture(event)
        monkeypatch.setattr(session, "commit", commit)
        assert reconcile.reconcile_batch(session) == 0
    assert len(final_rows()) == 1 and final_rows()[0].origin == "live"


def test_normal_arrival_separate_fifteen_minute_obligation(monkeypatch):
    """Declared fixed load:10/min, initial200, available DB/no persistent locks.

    Accelerated known clock is a queue-age stage test, not a real15min live SLA.
    Wall-clock HOLD is separately measured under four real writers below.
    """
    fixed_clock(monkeypatch)
    from types import SimpleNamespace
    virtual = [0.0]
    monkeypatch.setattr(reconcile, "time", SimpleNamespace(monotonic=lambda: virtual[0]))
    actual = usage.drain_pending_row
    completed_ages = []
    def normal_service(session, event_id, revision):
        pending_at = as_utc(session.get(usage.UsagePending, (event_id, revision)).pending_at)
        result = actual(session, event_id, revision)
        virtual[0] += 0.125  # <=100ms transaction +25ms spacing, known service bound
        if result.status == "drained":
            completed_ages.append((NOW + timedelta(seconds=virtual[0]) - pending_at).total_seconds())
        return result
    monkeypatch.setattr(usage, "drain_pending_row", normal_service)
    for _ in range(200):
        capture(old(), pending=True)
    max_age = 0.0
    for minute in range(20):
        now = NOW + timedelta(minutes=minute)
        virtual[0] = minute * 60.0
        fixed_clock(monkeypatch, now)
        for _ in range(10):
            event = old(at=now)
            capture(event, pending=True)
            with get_session() as session:
                row = session.get(usage.UsagePending, (event.id, 0))
                row.pending_at = now
                session.add(row)
        with get_session() as session:
            # Give initial records the declared same-clock start (the fixture's
            # captured pending_at is otherwise the real construction clock).
            if minute == 0:
                for row in session.exec(select(usage.UsagePending)).all():
                    row.pending_at = NOW
                    session.add(row)
                session.commit()
            reconcile.drain_pending(session)
            state = reconcile.drain_state(session)
            if state["oldest_pending_at"]:
                max_age = max(max_age, (now - state["oldest_pending_at"]).total_seconds())
            assert max_age <= 900
            assert "drain-silent" not in state["codes"]
            assert reconcile.coverage_state(session)["status"] == "UNKNOWN"
    with get_session() as session:
        assert reconcile.drain_state(session)["pending_count"] == 0
    assert len(final_rows()) == len(completed_ages) == 400
    assert 0 <= min(completed_ages) <= max(completed_ages) <= 900


def test_budget_and_shutdown_do_not_loop_or_fake_heartbeat(monkeypatch):
    fixed_clock(monkeypatch)
    capture(old(), pending=True)
    calls = []
    def stopped(session, event_id, revision):
        calls.append(event_id)
        reconcile._stop.set()
        return usage.DrainOutcome("busy")
    monkeypatch.setattr(usage, "drain_pending_row", stopped)
    with get_session() as session:
        reconcile.drain_pending(session)
        assert len(calls) == 1
        assert session.get(reconcile.UsageDrainHeartbeat, 1) is None
        assert reconcile.drain_state(session)["pending_count"] == 1


def test_start_stop_and_sixty_second_drain_before_reconcile(monkeypatch):
    fixed_clock(monkeypatch)
    order = []
    monkeypatch.setattr(reconcile, "drain_pending", lambda session: order.append("drain") or dict(
        attempted=0, drained=0, busy=0, deferred=0, faulted=0))
    monkeypatch.setattr(reconcile, "reconcile_batch", lambda session: order.append("reconcile"))
    monkeypatch.setattr(reconcile, "mark_unended", lambda session: order.append("unended"))
    monkeypatch.setattr(reconcile, "try_cutover", lambda session: order.append("cutover"))
    monkeypatch.setattr(reconcile, "check_post_cutover", lambda session: order.append("faults"))
    reconcile._sweep()
    assert order == ["drain", "reconcile", "unended", "cutover", "faults"]
    assert reconcile.EVERY_SECONDS == 60
    assert reconcile.MAX_BATCH <= 200
    assert reconcile.DRAIN_BUDGET_SECONDS + reconcile.RECONCILE_BUDGET_SECONDS < 60
    assert reconcile.start() and reconcile.start()
    reconcile.stop()
    assert not reconcile._thread.is_alive()


def test_pending_equal_timestamps_keep_all_revisions_and_ids(monkeypatch):
    fixed_clock(monkeypatch)
    a, b = old(event_id="equal-a"), old(event_id="equal-b")
    capture(a, pending=True)
    capture(a, pending=True, revision=1)
    capture(b, pending=True)
    with get_session() as session:
        for row in session.exec(select(usage.UsagePending)).all():
            row.pending_at = NOW
            session.add(row)
    monkeypatch.setattr(reconcile, "MAX_BATCH", 1)
    with get_session() as session:
        assert [reconcile.drain_pending(session)["drained"] for _ in range(3)] == [1, 1, 1]
    assert [(r.event_id, r.revision) for r in final_rows()] == [(a.id, 0), (a.id, 1), (b.id, 0)]


def test_one_wake_shared_numeric_budget_is_drain_first(monkeypatch):
    fixed_clock(monkeypatch)
    native_terminal("bounded-start")
    started = old({"provider": "provider-v1", "model": "model-v1"}, kind="llm.call.started",
                  execution_id="bounded-start", at=NOW - timedelta(hours=1))
    capture(started)
    pending, legacy = old(), old()
    capture(pending, pending=True)
    monkeypatch.setattr(reconcile, "MAX_BATCH", 1)
    reconcile._sweep()
    assert {r.event_id for r in final_rows()} == {started.id, pending.id}
    reconcile._sweep()
    assert {r.event_id for r in final_rows()} == {started.id, pending.id, legacy.id}
    assert not any("call-unended" in r.fault_codes for r in final_rows())
    reconcile._sweep()
    assert sum("call-unended" in r.fault_codes for r in final_rows()) == 1


def test_unknown_start_checks_consume_shared_row_budget_and_rotate(monkeypatch):
    fixed_clock(monkeypatch)
    native_terminal("unknown-budget", minutes=None)
    for key in ("unknown-a", "unknown-b", "unknown-c"):
        capture(old({"provider": "provider-v1", "model": "model-v1"}, kind="llm.call.started",
                    execution_id="unknown-budget", event_id=key, at=NOW - timedelta(hours=1)))
    capture(old(), pending=True)
    monkeypatch.setattr(reconcile, "MAX_BATCH", 2)
    reconcile._sweep()
    with get_session() as session:
        assert session.get(reconcile.UsageCoverage, 1).start_cursor_event_id == "unknown-a"
    reconcile._sweep()
    with get_session() as session:
        assert session.get(reconcile.UsageCoverage, 1).start_cursor_event_id == "unknown-c"
    assert all("call-unended" not in row.fault_codes for row in final_rows())


def test_reconcile_lap_wraps_equal_times_and_rows_committed_behind_cursor(monkeypatch):
    fixed_clock(monkeypatch)
    stamp = NOW - timedelta(hours=2)
    a, z = old(at=stamp, event_id="lap-a"), old(at=stamp, event_id="lap-z")
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    with get_session() as session:
        assert reconcile.reconcile_batch(session, limit=1) == 1
        assert not reconcile.try_cutover(session)
    behind = old(at=stamp, event_id="lap-0")
    with get_session() as session:
        assert reconcile.reconcile_batch(session, limit=1) == 1
        state = reconcile.coverage_state(session)
        assert state["reconcile_lap"]["complete"] and state["reconcile_lap"]["clean"]
        assert not reconcile.try_cutover(session)  # end of cursor is NOT final-pass proof
        assert reconcile.reconcile_batch(session, limit=1) == 1  # wraps and sees the behind row
        assert reconcile.try_cutover(session)
        assert reconcile.coverage_state(session)["status"] == "UNKNOWN"
    assert [r.event_id for r in final_rows()] == [a.id, z.id, behind.id]


@pytest.mark.parametrize("changed", ["ready", "window"])
def test_lap_resets_when_ready_boundary_or_pacific_window_changes(monkeypatch, changed):
    fixed_clock(monkeypatch)
    old(event_id="before-a")
    old(event_id="before-z")
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    with get_session() as session:
        reconcile.reconcile_batch(session, limit=1)
        before = reconcile.coverage_state(session)["reconcile_lap"]["generation"]
    later = NOW + (timedelta(seconds=1) if changed == "ready" else timedelta(days=7))
    fixed_clock(monkeypatch, later)
    if changed == "ready":
        reconcile.mark_ready("worker")
    with get_session() as session:
        assert not reconcile.try_cutover(session)
        reconcile.reconcile_batch(session)
        assert reconcile.coverage_state(session)["reconcile_lap"]["generation"] == before + 1


@pytest.mark.parametrize("guard", ["clean", "complete", "ready", "started", "missing"])
def test_final_lap_guards_have_individual_removal_bites(monkeypatch, guard):
    fixed_clock(monkeypatch)
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    with get_session() as session:
        reconcile.reconcile_batch(session)
        coverage = session.get(reconcile.UsageCoverage, 1)
        before = {"clean": "or not coverage.lap_clean", "complete": "or not coverage.lap_complete",
                  "ready": "or as_utc(coverage.lap_ready_at) != boundary",
                  "started": "or _require_time(as_utc(coverage.lap_started_at)) < boundary",
                  "missing": "or session.execute(_eligible(session, _db_now(session)).limit(1)).first()"}[guard]
        if guard == "clean":
            coverage.lap_clean = False
        elif guard == "complete":
            coverage.lap_complete = False
        elif guard == "ready":
            coverage.lap_ready_at = NOW - timedelta(seconds=1)
        elif guard == "started":
            coverage.lap_started_at = NOW - timedelta(seconds=1)
        else:
            old(event_id="late-behind")
        session.add(coverage)
        session.commit()
        assert not reconcile.try_cutover(session)
        mutate_function(monkeypatch, reconcile.try_cutover, before, "or False")
        with pytest.raises(AssertionError):
            assert not reconcile.try_cutover(session)


def test_failed_recovery_row_makes_entire_final_lap_dirty(monkeypatch):
    fixed_clock(monkeypatch)
    old()
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    actual = usage.write_or_queue_row
    def fail(session, row):
        raise RuntimeError("fixed recovery failure")
    monkeypatch.setattr(usage, "write_or_queue_row", fail)
    with get_session() as session:
        assert reconcile.reconcile_batch(session) == 0
        assert not reconcile.coverage_state(session)["reconcile_lap"]["clean"]
        assert not reconcile.try_cutover(session)
    monkeypatch.setattr(usage, "write_or_queue_row", actual)
    with get_session() as session:
        assert reconcile.reconcile_batch(session) == 1
        assert reconcile.try_cutover(session)


def test_maximal_realizable_start_faults_plus_unended_fit_unchanged_256_bound(monkeypatch):
    fixed_clock(monkeypatch)
    native_terminal("fault-bound")
    bad = {field: True for field in usage.TOKEN_FIELDS.values()}
    bad.update(provider="bad\n", model="bad\n", call_kind="unsupported", cost_usd=-1, lost_attempts=1)
    started = old(bad, kind="llm.call.started", execution_id="fault-bound", parent_id="bad\n",
                  at=NOW - timedelta(hours=1))
    capture(started)
    with get_session() as session:
        assert reconcile.mark_unended(session) == 1
    row = [row for row in final_rows() if row.event_id == started.id][-1]
    faults = set(row.fault_codes.split(","))
    expected = {*usage._TOKEN_FAULTS.values(), "provider-invalid", "model-invalid", "kind-invalid",
                "id-invalid", "cost-invalid", "lost-invalid", "call-unended"}
    assert faults == expected and len(row.fault_codes) <= 256
    assert all(getattr(row, field) is None for field in usage.TOKEN_FIELDS)
    assert row.legacy_cost_usd is row.legacy_cost_source is None


@pytest.mark.parametrize("pi", [False, True])
def test_unended_proof_and_end_absence_use_one_snapshot_and_null_revision(monkeypatch, pi):
    fixed_clock(monkeypatch)
    native_terminal("exact-start")
    values = {"provider": "provider-v1", "model": "model-v1", "call_kind": "model"}
    if pi:
        values.update(executed_by="pi", llm_call_id="pi-exact-1")
    started = old(values, kind="llm.call.started", execution_id="exact-start", parent_id="node-a",
                  at=NOW - timedelta(hours=1))
    capture(started)
    statements = []
    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    sa_event.listen(get_database().engine, "before_cursor_execute", before)
    try:
        with get_session() as session:
            proof = reconcile._start_snapshot(session, started.id, NOW)
            assert proof["producer_proven"] and proof["settled"] and not proof["end_seen"]
        assert len(statements) == 1
    finally:
        sa_event.remove(get_database().engine, "before_cursor_execute", before)
    with get_session() as session:
        assert reconcile.mark_unended(session) == 1
        assert reconcile.mark_unended(session) == 0
    row = final_rows()[-1]
    assert row.event_id == started.id and row.revision == 1
    assert row.fault_codes == "call-unended" and row.occurrence_basis == "call_start"
    assert "call-unended" in usage.FAULT_CODES  # #127 wire mapping needs this closed storage code.
    assert row.origin == "reconciled" and as_utc(row.occurred_at) == started.timestamp
    assert all(getattr(row, key) is None for key in (*usage.TOKEN_FIELDS, "legacy_cost_usd", "legacy_cost_source"))


@pytest.mark.parametrize("case", ["no-capture", "reconciled", "pending", "young", "unknown-time",
                                  "nonterminal", "root-conflict", "outside-window", "pi-no-id", "pi-no-kind",
                                  "pi-ambiguous"])
def test_unended_unknown_or_unproven_starts_are_unmarked_never_faulted(monkeypatch, case):
    fixed_clock(monkeypatch)
    native_terminal("unproven-start", minutes=None if case == "unknown-time" else (14 if case == "young" else 16),
                    status="waiting" if case == "nonterminal" else "completed",
                    root_status="running" if case == "root-conflict" else "completed")
    values = {"provider": "provider-v1", "model": "model-v1", "call_kind": "model"}
    if case.startswith("pi-"):
        values.update(executed_by="pi", llm_call_id=None if case == "pi-no-id" else "pi-ambiguous")
        if case == "pi-no-kind":
            values.pop("call_kind")
    started = old(values, kind="llm.call.started", execution_id="unproven-start", parent_id="same-node",
                  at=reconcile._history_start(NOW) - timedelta(seconds=1) if case == "outside-window"
                  else NOW - timedelta(hours=1))
    if case != "no-capture":
        capture(started, pending=case == "pending", origin="reconciled" if case == "reconciled" else "live")
    if case == "pi-ambiguous":
        capture(old(values, kind="llm.call.started", execution_id="unproven-start", parent_id="same-node",
                    at=NOW - timedelta(hours=1)))
    with get_session() as session:
        assert reconcile.mark_unended(session) == 0
        assert not any(reconcile.coverage_state(session)["fault_counts"].values())
    assert all("call-unended" not in row.fault_codes for row in final_rows())


@pytest.mark.parametrize("store", ["final", "pending", "native"])
@pytest.mark.parametrize("pi", [False, True])
def test_exact_end_in_each_store_prevents_false_unended(monkeypatch, store, pi):
    fixed_clock(monkeypatch)
    native_terminal("has-end")
    start_values = {"provider": "provider-v1", "model": "model-v1", "call_kind": "model"}
    if pi:
        start_values.update(executed_by="pi", llm_call_id="ended-pi")
    started = old(start_values, kind="llm.call.started", execution_id="has-end", parent_id="node-a",
                  at=NOW - timedelta(hours=1))
    capture(started)
    changes = {"llm_call_id": "ended-pi"} if pi else {"started_event_id": started.id}
    native_end_values = {**VALUES, **(start_values if pi else {"started_event_id": started.id})}
    stored_end_values = {**VALUES, "call_kind": "model", **(
        {"executed_by": "pi", "llm_call_id": "different-native-id"} if pi else {})}
    end = old(native_end_values if store == "native" else stored_end_values,
              execution_id="has-end", parent_id="node-a")
    if store != "native":
        capture(end, pending=store == "pending", row_changes=changes)
    with get_session() as session:
        proof = reconcile._start_snapshot(session, started.id, NOW)
        assert proof["producer_proven"] and proof["end_seen"]
        assert reconcile.mark_unended(session) == 0


def test_late_end_supersedes_mark_once_even_after_history_window_rolls(monkeypatch):
    fixed_clock(monkeypatch)
    native_terminal("late-service")
    started = old({"provider": "provider-v1", "model": "model-v1"}, kind="llm.call.started",
                  execution_id="late-service", at=NOW - timedelta(hours=1))
    capture(started)
    ignored_history = old(at=NOW - timedelta(days=30))
    with get_session() as session:
        assert reconcile.mark_unended(session) == 1
    later = NOW + timedelta(days=21)
    fixed_clock(monkeypatch, later)
    capture(old({**VALUES, "started_event_id": started.id}, at=later, execution_id="late-service"))
    with get_session() as session:
        assert reconcile.mark_unended(session) == 1
        assert reconcile.mark_unended(session) == 0
    revisions = [r for r in final_rows() if r.event_id == started.id]
    assert [r.revision for r in revisions] == [0, 1, 2]
    assert ["call-unended" in r.fault_codes for r in revisions] == [False, True, False]
    assert all(r.event_id != ignored_history.id for r in final_rows())


@pytest.mark.parametrize("guard", ["terminal", "age", "root", "pending", "pi-unique"])
def test_unended_guards_have_individual_removal_bites(monkeypatch, guard):
    fixed_clock(monkeypatch)
    native_terminal("guard-start", status="waiting" if guard == "terminal" else "completed",
                    minutes=1 if guard == "age" else 16,
                    root_status="waiting" if guard == "root" else "completed")
    values = {"provider": "provider-v1", "model": "model-v1", "call_kind": "model"}
    if guard == "pi-unique":
        values.update(executed_by="pi", llm_call_id="duplicate")
    started = old(values, kind="llm.call.started", execution_id="guard-start", at=NOW - timedelta(hours=1))
    capture(started, pending=guard == "pending")
    if guard == "pi-unique":
        capture(old(values, kind="llm.call.started", execution_id="guard-start", at=NOW - timedelta(hours=1)))
    changes = {"terminal": ("col(WorkflowRun.status).in_(TERMINAL),", ""),
               "age": ("col(WorkflowRun.completed_at) <= now - timedelta(minutes=15)", "True"),
               "root": ("and_(settled, ~conflicting_status)", "settled"),
               "pi-unique": ("latest.c.call_kind.is_not(None), unique_pi_start", "latest.c.call_kind.is_not(None)")}
    with get_session() as session:
        assert reconcile.mark_unended(session) == 0
        if guard == "pending":
            mutate_function(monkeypatch, reconcile.mark_unended,
                            ' and not snapshot["start_pending"]', "")
        else:
            before, after = changes[guard]
            mutate_function(monkeypatch, reconcile._start_snapshot, before, after)
        with pytest.raises(AssertionError):
            assert reconcile.mark_unended(session) == 0


@pytest.mark.parametrize("guard", ["origin", "instance"])
def test_live_producer_snapshot_proof_has_its_own_bite(monkeypatch, guard):
    fixed_clock(monkeypatch)
    native_terminal("producer-proof")
    started = old({"provider": "provider-v1", "model": "model-v1"}, kind="llm.call.started",
                  execution_id="producer-proof", at=NOW - timedelta(hours=1))
    capture(started, origin="reconciled" if guard == "origin" else "live")
    if guard == "instance":
        with get_session() as session:
            row = session.exec(select(usage.UsageCallRow).where(usage.UsageCallRow.event_id == started.id)).one()
            row.instance = str(uuid.uuid4())
            session.add(row)
    with get_session() as session:
        def assert_unproven():
            assert not reconcile._start_snapshot(session, started.id, NOW)["producer_proven"]
        assert_unproven()
        before, after = (("starts.c.origin == \"live\", *scope(starts.c)", "True, *scope(starts.c)") if guard == "origin"
                         else ("latest.c.instance == current_instance, proven", "True, proven"))
        mutate_function(monkeypatch, reconcile._start_snapshot, before, after)
        with pytest.raises(AssertionError):
            assert_unproven()


@pytest.mark.parametrize("store", ["final", "pending"])
@pytest.mark.parametrize("guard", ["instance", "execution", "parent", "source", "kind", "call-id"])
def test_captured_pi_end_exact_scope_guards_have_individual_bites(monkeypatch, store, guard):
    fixed_clock(monkeypatch)
    native_terminal("pi-scope")
    started = old({"provider": "provider-v1", "model": "model-v1", "call_kind": "model",
                   "executed_by": "pi", "llm_call_id": "target-pi"}, kind="llm.call.started",
                  execution_id="pi-scope", parent_id="parent-a", at=NOW - timedelta(hours=1))
    capture(started)
    end = old({**VALUES, "call_kind": "model", "executed_by": "pi", "llm_call_id": "wrong-native"},
              execution_id="pi-scope", parent_id="parent-a")
    capture(end, pending=store == "pending", row_changes={"llm_call_id": "target-pi"})
    changes = {"instance": ("instance", str(uuid.uuid4()), "col(model.instance) == latest.c.instance"),
               "execution": ("execution_id", "wrong-execution", "col(model.execution_id).is_not_distinct_from(latest.c.execution_id)"),
               "parent": ("parent_id", "wrong-parent", "col(model.parent_id).is_not_distinct_from(latest.c.parent_id)"),
               "source": ("token_source", "service", "col(model.token_source) == latest.c.token_source"),
               "kind": ("call_kind", "compaction", "col(model.call_kind).is_not_distinct_from(latest.c.call_kind)"),
               "call-id": ("llm_call_id", "wrong-captured", "col(model.llm_call_id) == latest.c.llm_call_id")}
    key, wrong, before = changes[guard]
    with get_session() as session:
        model = usage.UsageCallRow if store == "final" else usage.UsagePending
        row = session.exec(select(model).where(model.event_id == end.id)).one()
        setattr(row, key, wrong)
        session.add(row)
    with get_session() as session:
        def assert_not_an_exact_end():
            assert not reconcile._start_snapshot(session, started.id, NOW)["end_seen"]
        assert_not_an_exact_end()
        mutate_function(monkeypatch, reconcile._start_snapshot, before, "True")
        with pytest.raises(AssertionError):
            assert_not_an_exact_end()


def test_service_exact_start_id_never_inferred_from_time_or_amount(monkeypatch):
    fixed_clock(monkeypatch)
    native_terminal("service-scope")
    values = {"provider": "provider-v1", "model": "model-v1", "call_kind": "model"}
    a, b = (old(values, kind="llm.call.started", execution_id="service-scope", parent_id="same-parent",
                at=NOW - timedelta(hours=1)) for _ in range(2))
    capture(a)
    capture(b)
    capture(old({**VALUES, "call_kind": "model", "started_event_id": b.id},
                execution_id="service-scope", parent_id="same-parent"))
    with get_session() as session:
        def assert_first_has_no_exact_end():
            assert not reconcile._start_snapshot(session, a.id, NOW)["end_seen"]
        assert_first_has_no_exact_end()
        assert reconcile._start_snapshot(session, b.id, NOW)["end_seen"]
        mutate_function(monkeypatch, reconcile._start_snapshot, "col(model.started_event_id) == latest.c.event_id", "True")
        with pytest.raises(AssertionError):
            assert_first_has_no_exact_end()


@pytest.mark.parametrize("pi", [False, True])
@pytest.mark.parametrize("wrong", ["execution", "parent", "kind", "call-id", "fork"])
def test_native_end_leaves_require_exact_pi_scope_not_a_near_match(monkeypatch, pi, wrong):
    fixed_clock(monkeypatch)
    native_terminal("native-scope")
    values = {"provider": "provider-v1", "model": "model-v1", "call_kind": "model"}
    if pi:
        values.update(executed_by="pi", llm_call_id="native-target")
    started = old(values, kind="llm.call.started", execution_id="native-scope", parent_id="node-a",
                  at=NOW - timedelta(hours=1))
    capture(started)
    end_values = {**VALUES, **values, "started_event_id": started.id}
    if wrong == "fork":
        end_values["restored_from_fork"] = True
    elif wrong == "kind":
        end_values["call_kind"] = "compaction"
    elif wrong == "call-id":
        end_values["llm_call_id" if pi else "started_event_id"] = "not-the-exact-id"
    old(end_values, execution_id="different-execution" if wrong == "execution" else "native-scope",
        parent_id="different-parent" if wrong == "parent" else "node-a")
    with get_session() as session:
        # Service's authoritative explicit start ID does not infer a Pi parent/kind scope.
        expected_end = not pi and wrong in ("parent", "kind")
        assert bool(reconcile._start_snapshot(session, started.id, NOW)["end_seen"]) == expected_end
        assert reconcile.mark_unended(session) == (0 if expected_end else 1)


class _ProfiledScalarCursor:
    """Test-only: preserve the production scalar API while retaining DB grant time."""
    def __init__(self, cursor, connection):
        self.cursor, self.connection = cursor, connection
    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            self.connection.usage_grant = row[-1]
            return row[:1]
        return row
    def __getattr__(self, name):
        return getattr(self.cursor, name)


def test_original_batch_lock_hold_p95_fifty_ms_with_four_live_writers(monkeypatch, capsys):
    """Actual grant→release upper bound, BOTH timestamps from Postgres.

    Grant timestamp is sampled inside the SAME materialized lock CTE. Release
    upper bound is the first DB clock after real COMMIT, including the return
    trip. No wall/monotonic clock is subtracted from a native timestamp, no
    workload retry, no100ms WAIT substitution. All rows/DB are throwaway5455.
    """
    database = get_database()
    if database.engine.dialect.name != "postgresql":
        # The matching SQLite stage still exercises the same bounded transactions.
        fixed_clock(monkeypatch)
        capture(old(), pending=True)
        old()
        with get_session() as session:
            assert reconcile.drain_pending(session)["drained"] == 1
            assert reconcile.reconcile_batch(session) == 1
        return
    import psycopg2
    from sqlalchemy import create_engine

    samples = []
    local = threading.local()
    samples_lock = threading.Lock()
    class MeasuredConnection(psycopg2.extensions.connection):
        usage_grant = None
        def commit(self):
            grant = self.usage_grant
            self.usage_grant = None
            super().commit()  # actual ordering-lock release
            if grant is not None:
                with self.cursor() as cursor:
                    cursor.execute("SELECT clock_timestamp()")
                    released_upper = cursor.fetchone()[0]
                super().rollback()  # close only the profiling SELECT's transaction
                with samples_lock:
                    samples.append((getattr(local, "kind", "other"),
                                    (released_upper - grant).total_seconds() * 1000))
    base = database.engine
    url = base.url.set(drivername="postgresql+psycopg2")
    measured = create_engine(url, pool_size=8, max_overflow=2,
                             connect_args={"connection_factory": MeasuredConnection})
    with base.connect() as connection:
        schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    @sa_event.listens_for(measured, "connect")
    def schema_path(connection, record):
        with connection.cursor() as cursor:
            cursor.execute('SET search_path TO "' + schema.replace('"', '""') + '"')
        connection.commit()
    @sa_event.listens_for(measured, "after_cursor_execute")
    def preserve_scalar(connection, cursor, statement, parameters, context, executemany):
        if "usage_grant_at" in statement:
            context.cursor = _ProfiledScalarCursor(cursor, connection.connection.driver_connection)
    monkeypatch.setattr(database, "engine", measured)
    # Add a dependent materialized clock AFTER the EXISTING lock CTE. A
    # clock in the lock SELECT-list could run BEFORE a blocked lock is granted.
    def profile(statement):
        original = str(statement)
        assert "RETURNING seq" in original and "pg_advisory_xact_lock" in original
        instrumented = original.replace("FROM commit_order", "FROM timed_order").replace("USING commit_order", "USING timed_order")
        instrumented = instrumented.replace("    )", "    ), timed_order AS MATERIALIZED (\n"
            "        SELECT clock_timestamp() AS usage_grant_at FROM commit_order\n    )", 1)
        return text(instrumented.replace("RETURNING seq", "RETURNING seq, (SELECT usage_grant_at FROM timed_order) AS usage_grant_at"))
    monkeypatch.setattr(usage, "_POSTGRES_ROW_INSERT", profile(usage._POSTGRES_ROW_INSERT))
    monkeypatch.setattr(usage, "_POSTGRES_PENDING_DRAIN", profile(usage._POSTGRES_PENDING_DRAIN))
    fixed_clock(monkeypatch)
    for _ in range(50):
        capture(old(), pending=True)
        old()
    monkeypatch.setattr(reconcile, "BATCH_PAUSE_SECONDS", 0.025)
    barrier = threading.Barrier(5)
    done = threading.Event()
    def writer(index):
        local.kind = "writer"
        barrier.wait(timeout=10)
        count = 0
        while not done.is_set() and count < 2000:
            # Same atomic Event + numeric projection boundary as the live writer,
            # not a provider call and not a two-transaction historical fixture.
            event = Event(type="llm.call.completed", timestamp=NOW, data=VALUES)
            row = usage.extract(event.type, VALUES, {"event_id": event.id}, NOW)
            assert row is not None
            with get_session() as session:
                session.add(event)
                session.flush()
                usage.write_or_queue_row(session, row)
            count += 1
        assert done.is_set(), "writers exhausted their fixed bound before the measured batch completed"
        return count
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            jobs = [executor.submit(writer, index) for index in range(4)]
            barrier.wait(timeout=10)
            local.kind = "batch"
            try:
                with get_session() as session:
                    assert reconcile.drain_pending(session)["drained"] == 50
                    assert reconcile.reconcile_batch(session) == 50
            finally:
                done.set()
            writer_counts = [job.result(timeout=20) for job in jobs]
        holds = sorted(ms for kind, ms in samples if kind == "batch")
        assert len(holds) == 100
        assert all(writer_counts), writer_counts
        p95 = holds[math.ceil(len(holds) * 0.95) - 1]
        all_holds = sorted(ms for kind, ms in samples if kind in ("batch", "writer"))
        all_p95 = all_holds[math.ceil(len(all_holds) * 0.95) - 1]
        print(f"q126 HOLD batch=100 writers=4 counts={writer_counts} p95_ms={p95:.3f} max_ms={max(holds):.3f} "
              f"all_grants={len(all_holds)} all_p95_ms={all_p95:.3f} all_max_ms={max(all_holds):.3f}")
        assert p95 <= 50, f"original50ms batch LOCK-HOLD miss: {p95:.3f}ms; route to Temper lead, do not relax"
        assert all_p95 <= 50, f"Architecture all-acquisition HOLD miss: {all_p95:.3f}ms"
    finally:
        measured.dispose()


# H-126-CUTOVER-2: the cutover barrier judges each earlier execution by its latest state.
# Fixed shapes only (the dead history seen on live, rebuilt by hand); T is NOW. Each shape is
# judged at two fixed database clocks: INSIDE (its after-T event is in the quiet window) and
# QUIET (that event is older than the window).

BEFORE, AFTER = NOW - timedelta(days=20), NOW + timedelta(minutes=5)
HOUR = timedelta(hours=1)
INSIDE = NOW + timedelta(minutes=30)
QUIET = AFTER + reconcile.QUIET_WINDOW + timedelta(minutes=1)


def execution(execution_id, *, row=None, starts=(), events=()):
    """One fixed execution: its run row status (None: no row), start events (time, status[, event id]),
    other events."""
    for at, status, *event_id in starts:
        start = old({}, at=at, kind="workflow.started", execution_id=execution_id,
                    event_id=event_id[0] if event_id else None)
        with get_session() as session:
            session.get(Event, start.id).status = status
    for at in events:
        old({}, at=at, kind="stage.completed", execution_id=execution_id)
    if row is not None:
        with get_session() as session:
            session.add(WorkflowRun(execution_id=execution_id, workflow_name="fixed-fixture",
                                    workspace_path="/fixture", status=row))


DEAD_ON_LIVE = {  # the shapes that held the live barrier forever; none may block
    "orphaned-interrupted": {"row": "orphaned", "starts": [(BEFORE, "interrupted")], "events": [BEFORE]},
    "orphaned-failed": {"row": "orphaned", "starts": [(BEFORE, "failed")]},
    "failed-old-parked": {"row": "failed", "starts": [(BEFORE, "parked"), (BEFORE + HOUR, "failed")]},
    "cancelled-old-parked": {"row": "cancelled", "starts": [(BEFORE, "parked"), (BEFORE + HOUR, "cancelled")]},
    "completed-old-parked": {"row": "completed", "starts": [(BEFORE, "parked"), (BEFORE + HOUR, "parked"),
                                                              (BEFORE + 2 * HOUR, "completed")]},
    "no-row-no-start-quiet": {"events": [BEFORE]},
}
MUST_PASS = {  # at either clock
    **DEAD_ON_LIVE,
    # Code-derived, not seen on live: claim -> queue -> box dies before its first start -> reaper.
    "ended-row-latest-parked": {"row": "orphaned", "starts": [(BEFORE, "parked")]},
    "pre-T-event-inside-W": {"row": "completed", "starts": [(BEFORE, "completed")],
                             "events": [NOW - timedelta(minutes=10)]},
    "no-row-carried-on": {"starts": [(BEFORE, "parked"), (BEFORE + HOUR, "completed")]},
    "post-cutover-running-row": {"row": "running", "starts": [(AFTER, "running")]},
    "post-cutover-open-start": {"starts": [(AFTER, "running")]},
    "post-cutover-no-start": {"events": [AFTER]},
}
MUST_BLOCK = {  # at either clock: shape, the rule that holds it
    "parked-row": ({"row": "parked", "starts": [(BEFORE, "parked")]}, 1),
    "running-row": ({"row": "running", "starts": [(BEFORE, "running")]}, 1),
    "orphaned-resumed-running": ({"row": "running", "starts": [(BEFORE, "interrupted"), (AFTER, "running")]}, 1),
    "failed-requeued-by-resume": ({"row": "queued", "starts": [(BEFORE, "failed")]}, 1),
    "claim-under-open-row": ({"row": "queued", "starts": [(BEFORE, "parked")]}, 1),
    "no-row-latest-parked": ({"starts": [(BEFORE, "completed"), (BEFORE + HOUR, "parked")]}, 2),
    "no-row-latest-open": ({"starts": [(BEFORE, "running")]}, 2),
    # The ended-row CARRIED_ON exemption must not exempt a NULL or actively resumed start.
    "ended-row-null-start": ({"row": "orphaned", "starts": [(BEFORE, None)]}, 2),
    # An in-process resume starts its running attempt without touching the ended row.
    "ended-row-resumed-in-process": ({"row": "failed", "starts": [(BEFORE, "failed"), (BEFORE + HOUR, "running")]},
                                     2),
}
WRITING = {  # rule 3 holds these at INSIDE; quiet past the window they clear
    "no-row-no-start-active": {"events": [BEFORE, AFTER]},
    "orphaned-active": {"row": "orphaned", "starts": [(BEFORE, "interrupted")], "events": [AFTER]},
    "cancelled-active": {"row": "cancelled", "starts": [(BEFORE, "cancelled")], "events": [AFTER]},
    "no-row-ended-start-active": {"starts": [(BEFORE, "completed")], "events": [AFTER]},
    "ended-row-no-start-active": {"row": "completed", "events": [BEFORE, AFTER]},
}
SHAPES = {**MUST_PASS, **{name: shape for name, (shape, _) in MUST_BLOCK.items()}, **WRITING}


def expected_rules(now, names=SHAPES):
    held = {name: rule for name, (_, rule) in MUST_BLOCK.items()}
    if now < AFTER + reconcile.QUIET_WINDOW:
        held |= dict.fromkeys(WRITING, 3)
    return {name: rule for name, rule in held.items() if name in names}


def blocking_rules(now, limit=100):
    with get_session() as session:
        report = reconcile._cutover_blockers(session, NOW, now, limit=limit)
    assert report["anonymous_open_start"] is False
    assert report["executions"] == len(report["first"])
    return {execution_id: rule for execution_id, rule, _ in report["first"]}


def test_dead_history_no_longer_holds_cutover_and_live_or_writing_runs_still_do(monkeypatch, caplog):
    """Opening path for the fix: live's dead shapes present; cutover waits for the live parked
    run, then for an orphaned box still writing until it has been quiet for the window."""
    caplog.set_level(logging.INFO, logger=reconcile.logger.name)
    fixed_clock(monkeypatch)
    for name, shape in DEAD_ON_LIVE.items():
        execution(name, **shape)
    execution("live-parked", row="parked", starts=[(BEFORE, "parked")])
    execution("survivor", row="orphaned", starts=[(BEFORE, "interrupted")], events=[AFTER])
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    with get_session() as session:
        assert reconcile.reconcile_batch(session) == 0
        assert not reconcile.try_cutover(session)
        assert ("earlier_executions=2 anonymous_open_start=False "
                "first=live-parked:rule1/parked survivor:rule3/orphaned") in caplog.text
        session.execute(update(WorkflowRun).where(col(WorkflowRun.execution_id) == "live-parked")
                        .values(status="queued"))
        session.commit()
        assert not reconcile.try_cutover(session)  # a carried-on claim still has an open row
        assert "first=live-parked:rule1/queued survivor:rule3/orphaned" in caplog.text
        session.execute(update(WorkflowRun).where(col(WorkflowRun.execution_id) == "live-parked")
                        .values(status="orphaned"))
        session.commit()  # box died before its own start; the latest start stays CARRIED_ON
    fixed_clock(monkeypatch, INSIDE)
    with get_session() as session:
        assert reconcile.reconcile_batch(session) == 0
        assert not reconcile.try_cutover(session)
        assert "earlier_executions=1 anonymous_open_start=False first=survivor:rule3/orphaned" in caplog.text
        assert reconcile.coverage_state(session)["cutover_at"] is None
    fixed_clock(monkeypatch, QUIET)
    with get_session() as session:
        assert not reconcile.try_cutover(session)  # the open barrier needs its own full final lap
        assert reconcile.reconcile_batch(session) == 0
        assert reconcile.try_cutover(session)
        state = reconcile.coverage_state(session)
    assert state["cutover_at"] == NOW and state["phase"] == "cutover" and state["status"] == "UNKNOWN"
    assert "Usage cutover barrier: no earlier execution open" in caplog.text


@pytest.mark.parametrize("now", [INSIDE, QUIET], ids=["inside-window", "quiet-past-window"])
def test_barrier_query_known_answers_for_every_shape(now):
    """The query alone, model-free: each shape's execution is judged on its own rows only."""
    for name, shape in SHAPES.items():
        execution(name, **shape)
    assert blocking_rules(now) == expected_rules(now)


@pytest.mark.parametrize("status", ["waiting", "queued", "running", "pending", "cancelling", "parked", "unknown-status"])
def test_every_open_row_status_blocks_even_with_an_ended_start(status):
    execution("open-row", row=status, starts=[(BEFORE, "completed")])
    with get_session() as session:
        assert reconcile._cutover_blockers(session, NOW, QUIET)["first"] == [("open-row", 1, status)]


@pytest.mark.parametrize(("status", "blocks"), [
    *[(status, False) for status in ("completed", "failed", "cancelled", "interrupted", "orphaned")],
    *[(status, True) for status in ("waiting", "queued", "running", "pending", "cancelling", "parked",
                                    "unknown-status", None)],
])
def test_row_open_pins_the_ended_set_and_null(status, blocks):
    with get_session() as session:
        value = session.execute(sql_select(reconcile._row_open(literal(status, String)))).scalar()
    assert value is not None and bool(value) is blocks
    assert reconcile.BARRIER_ENDED == ("completed", "failed", "cancelled", "interrupted", "orphaned")
    assert reconcile.TERMINAL == ("completed", "failed", "cancelled", "interrupted")


@pytest.mark.parametrize("status", reconcile.BARRIER_ENDED)
def test_dead_carried_on_exemption_for_every_ended_row_status(status):
    execution("dead-claim", row=status, starts=[(BEFORE, "parked")])
    assert blocking_rules(INSIDE) == blocking_rules(QUIET) == {}


def test_rule_two_carried_on_exemption_needs_ended_status_even_without_rule_one(monkeypatch):
    """Isolate rule 2: otherwise rule 1 hides an over-broad 'any row' exemption."""
    execution("open-claim", row="queued", starts=[(BEFORE, "parked")])
    original = reconcile._cutover_blockers
    source = inspect.getsource(original)
    row_rule = "union_all(by_row, by_start, by_activity)"
    ended_guard = "col(WorkflowRun.status).in_(BARRIER_ENDED)"
    assert source.count(row_rule) == source.count(ended_guard) == 1
    source = source.replace(row_rule, "union_all(by_start, by_activity)")
    for ended_only, expected in ((True, {"open-claim": 2}), (False, {})):
        isolated = source if ended_only else source.replace(ended_guard, "True")
        namespace = dict(vars(reconcile))
        exec(compile(isolated, original.__code__.co_filename, "exec"), namespace)
        monkeypatch.setattr(reconcile, original.__name__, namespace[original.__name__])
        assert blocking_rules(QUIET) == expected


def test_quiet_window_is_pinned_and_counts_from_the_latest_event():
    assert reconcile.QUIET_WINDOW == timedelta(minutes=240)
    execution("writing", row="orphaned", events=[BEFORE, AFTER, AFTER + HOUR])
    assert blocking_rules(AFTER + reconcile.QUIET_WINDOW + timedelta(minutes=1)) == {"writing": 3}
    assert blocking_rules(AFTER + HOUR + reconcile.QUIET_WINDOW - timedelta(seconds=1)) == {"writing": 3}
    assert blocking_rules(AFTER + HOUR + reconcile.QUIET_WINDOW + timedelta(seconds=1)) == {}


@pytest.mark.parametrize("open_id", ["tie-a", "tie-b"])
def test_latest_start_tie_blocks_when_any_is_open_never_broken_by_id(open_id):
    execution("tie", starts=[(BEFORE, "completed")])
    for event_id in ("tie-a", "tie-b"):
        start = old({}, at=BEFORE + HOUR, kind="workflow.started", execution_id="tie", event_id=event_id)
        with get_session() as session:
            session.get(Event, start.id).status = "running" if event_id == open_id else "completed"
    assert blocking_rules(QUIET) == {"tie": 2}


def test_start_without_execution_keeps_its_own_unchanged_check():
    start = old({}, at=BEFORE, kind="workflow.started")
    with get_session() as session:
        session.get(Event, start.id).status = "running"
    with get_session() as session:
        assert reconcile._cutover_blockers(session, NOW, INSIDE) == {"executions": 0, "anonymous_open_start": True,
                                                                     "first": []}
        assert reconcile._earlier_execution_open(session, NOW, INSIDE)
        session.get(Event, start.id).status = "completed"
        session.commit()
        assert not reconcile._earlier_execution_open(session, NOW, INSIDE)


def test_blocker_report_counts_all_and_names_the_first_five_once(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=reconcile.logger.name)
    for index in range(7):
        execution(f"open-{index}", row="running", starts=[(BEFORE + index * HOUR, "running")])
    execution("open-0", events=[AFTER])  # held by rules 1 and 3: counted once, under rule 1
    with get_session() as session:
        report = reconcile._cutover_blockers(session, NOW, INSIDE)
    assert report["executions"] == 7
    assert report["first"] == [(f"open-{index}", 1, "running") for index in range(5)]
    for _ in range(2):
        reconcile._report_blockers(report)
    assert caplog.text.count("Usage cutover held: earlier_executions=7") == 1
    assert "open-4:rule1/running" in caplog.text and "open-5" not in caplog.text
    mutate_function(monkeypatch, reconcile._report_blockers, "if report == _last_blocker_report:", "if False:")
    reconcile._report_blockers(report)
    reconcile._report_blockers(report)
    assert caplog.text.count("Usage cutover held: earlier_executions=7") == 3


BARRIER_GUARDS = {  # guard: function, its text, the text with the guard taken out, the shape that shows it, clock
    "orphaned-ended": (reconcile._row_open, "status.not_in(BARRIER_ENDED)", "status.not_in(TERMINAL)",
                       "orphaned-interrupted", QUIET),
    "row-begun-before": (reconcile._cutover_blockers, "began_before(run.execution_id)", "True",
                         "post-cutover-running-row", QUIET),
    "start-whatever-row": (reconcile._cutover_blockers, "began_before(opened.c.execution_id), latest_open",
                           "began_before(opened.c.execution_id), latest_open, ~exists(sql_select(1).where("
                           "col(WorkflowRun.execution_id) == opened.c.execution_id))",
                           "ended-row-resumed-in-process", QUIET),
    "start-begun-before": (reconcile._cutover_blockers, "began_before(opened.c.execution_id), latest_open",
                           "True, latest_open", "post-cutover-open-start", QUIET),
    "start-latest": (reconcile._cutover_blockers, "parked.latest_start_condition(start.execution_id, start)",
                     "True", "no-row-carried-on", QUIET),
    "start-latest-open": (reconcile._cutover_blockers, '"workflow.started", start_open(start),',
                          '"workflow.started", True,', "no-row-carried-on", QUIET),
    "dead-carry-on-exemption": (reconcile._cutover_blockers, "~dead_carry_on(start),", "True,",
                                 "ended-row-latest-parked", QUIET),
    "dead-carry-on-needs-row": (reconcile._cutover_blockers,
                                "col(event.status).is_not_distinct_from(parked.CARRIED_ON) & row_ended",
                                "col(event.status).is_not_distinct_from(parked.CARRIED_ON)",
                                "no-row-latest-parked", QUIET),
    "dead-carry-on-null-safe": (reconcile._cutover_blockers,
                                "col(event.status).is_not_distinct_from(parked.CARRIED_ON) & row_ended",
                                "(col(event.status) == parked.CARRIED_ON) & row_ended",
                                "ended-row-null-start", QUIET),
    "writing-rule": (reconcile._cutover_blockers, "union_all(by_row, by_start, by_activity)",
                     "union_all(by_row, by_start)", "orphaned-active", INSIDE),
    "writing-window": (reconcile._cutover_blockers, "lease = max(cutoff, now - QUIET_WINDOW)", "lease = cutoff",
                       "cancelled-active", QUIET),
    "writing-T-floor": (reconcile._cutover_blockers, "lease = max(cutoff, now - QUIET_WINDOW)",
                         "lease = now - QUIET_WINDOW", "pre-T-event-inside-W", INSIDE),
    "writing-begun-before": (reconcile._cutover_blockers, ".where(began_before(since.c.execution_id))", "",
                             "post-cutover-no-start", INSIDE),
    "lowest-rule": (reconcile._cutover_blockers, "func.min(held.c.rule)", "func.max(held.c.rule)",
                    "orphaned-resumed-running", INSIDE),
}


@pytest.mark.parametrize("guard", sorted(BARRIER_GUARDS))
def test_barrier_guards_have_individual_bites(monkeypatch, guard):
    function, before, after, name, now = BARRIER_GUARDS[guard]
    execution(name, **SHAPES[name])
    expected = expected_rules(now, names={name})
    assert blocking_rules(now) == expected
    mutate_function(monkeypatch, function, before, after)
    assert blocking_rules(now) != expected


# --- #126 A3 on S1 (AMENDMENT.md C-1, C-3) --------------------------------------------------

class recorded_statements:  # noqa: N801 - reads like the context manager it is
    """The SQL text this engine sends inside the block (statements only, never parameters)."""

    def __enter__(self):
        self.statements = []
        sa_event.listen(get_database().engine, "before_cursor_execute", self._record)
        return self.statements

    def __exit__(self, *exc):
        sa_event.remove(get_database().engine, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)


T10_SHAPES = ("running-row", "no-row-latest-parked", "ended-row-latest-parked")


def barrier_statements():
    """The barrier's answer and the SQL statements that read run rows while it was made."""
    with recorded_statements() as statements, get_session() as session:
        report = reconcile._cutover_blockers(session, NOW, QUIET)
    answer = {execution_id: rule for execution_id, rule, _ in report["first"]}
    return answer, [s for s in statements if WorkflowRun.__table__.name in s], statements


def test_t10_rules_one_and_two_are_read_in_one_statement():
    """T10: the run row (rule 1) and the latest starts (rule 2) are judged in ONE statement,
    one snapshot; only the separate anonymous-start check is a second statement."""
    for name in T10_SHAPES:
        execution(name, **SHAPES[name])
    answer, run_reads, statements = barrier_statements()
    assert answer == {"running-row": 1, "no-row-latest-parked": 2}
    assert len(run_reads) == 1 and Event.__table__.name in run_reads[0]
    assert len(statements) == 2


SPLIT_READ = (  # B4: rule 1 read by its own statement, its answers fed back as literals
    "held = union_all(by_row, by_start, by_activity).subquery()",
    "row_rows = session.execute(by_row).all()\n"
    "    held = union_all(*[sql_select(literal(r[0]).label('execution_id'), literal(1).label('rule'),"
    " literal(r[2], String).label('row_status')) for r in row_rows], by_start, by_activity).subquery()",
)


def test_t10_bite_b4_split_statement_keeps_answers_but_fails_one_snapshot(monkeypatch):
    for name in T10_SHAPES:
        execution(name, **SHAPES[name])
    mutate_function(monkeypatch, reconcile._cutover_blockers, *SPLIT_READ)
    answer, run_reads, _ = barrier_statements()
    assert answer == {"running-row": 1, "no-row-latest-parked": 2}  # the same answers
    assert len(run_reads) == 2  # T10's one-statement check fails


def frozen_at(clock: str) -> datetime:
    """The frozen cases' wall times (barrier-claim-cases.json) moved onto this table: T = NOW sits at
    12:00, the file's cutoff_T, so a 10:00 start is before T, 17:00's quiet-window lease is 13:00
    and lies after T, and 12:45's lease is T itself (lease = max(T, now - QUIET_WINDOW))."""
    hours, minutes, *rest = clock.split(":")
    seconds = float(rest[0]) if rest else 0.0
    return NOW + timedelta(hours=int(hours) - 12, minutes=int(minutes), seconds=seconds)


LEASE = frozen_at("13:00")
FROZEN = {  # case id (cases/barrier-claim-cases.json, sha256 80f0a983...): shape, observed at, rule or None
    "C05c-in-process-resume-under-ended-row": (
        {"row": "failed", "starts": [(frozen_at("10:00"), "failed"), (frozen_at("16:00"), "running")]},
        frozen_at("17:00"), 2),
    "C06a-tie-parked-and-waiting": (
        {"row": "orphaned", "starts": [(frozen_at("10:00"), "parked", "c06a-z-parked"),
                                     (frozen_at("10:00"), "waiting", "c06a-a-waiting")],
         "events": [frozen_at("10:30")]}, frozen_at("17:00"), 2),
    "C06b-tie-parked-and-running": (
        {"row": "orphaned", "starts": [(frozen_at("10:00"), "parked", "c06b-z-parked"),
                                     (frozen_at("10:00"), "running", "c06b-a-running")],
         "events": [frozen_at("10:30")]}, frozen_at("17:00"), 2),
    "C06c-tie-parked-and-failed-ended-row": (
        {"row": "failed", "starts": [(frozen_at("10:00"), "parked", "c06c-z-parked"),
                                   (frozen_at("10:00"), "failed", "c06c-a-failed")],
         "events": [frozen_at("10:30")]}, frozen_at("17:00"), None),
    "C06d-tie-two-parked-no-row": (
        {"starts": [(frozen_at("10:00"), "parked", "c06d-a"), (frozen_at("10:00"), "parked", "c06d-b")],
         "events": [frozen_at("10:30")]}, frozen_at("17:00"), 2),
    "C07a-fresh-activity-on-dead-claim-shape": (
        {"row": "failed", "starts": [(frozen_at("10:00"), "parked")], "events": [frozen_at("14:00")]},
        frozen_at("17:00"), 3),
    "C07b-activity-exactly-at-lease": (
        {"row": "failed", "starts": [(frozen_at("10:00"), "parked")], "events": [LEASE]},
        frozen_at("17:00"), 3),
    "C07c-activity-just-before-lease": (
        {"row": "failed", "starts": [(frozen_at("10:00"), "parked")],
         "events": [LEASE - timedelta(microseconds=1)]}, frozen_at("17:00"), None),
    "C08a-api-claim-with-no-row": (
        {"starts": [(frozen_at("10:00"), "parked")], "events": [frozen_at("10:30")]}, frozen_at("17:00"), 2),
    # A dead claim one second old: the barrier reads no claim time, so dead history clears.
    "K9c-same-state-claimant-dead-pre-repair": (
        {"row": "orphaned", "starts": [(frozen_at("10:00"), "parked")], "events": [frozen_at("10:30")]},
        frozen_at("12:45"), None),
}


def frozen_answer(name):
    shape, now, _ = FROZEN[name]
    execution(name, **shape)
    return blocking_rules(now)


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_t11_frozen_barrier_cases_known_answers(name):
    """T11: the parent plan's frozen cases, each alone, at its own database clock."""
    assert reconcile.QUIET_WINDOW == frozen_at("17:00") - LEASE
    rule = FROZEN[name][2]
    assert frozen_answer(name) == ({name: rule} if rule else {})


# The file's C03c (a pre-repair claimant killed between its two commits, required PASS) is a
# liveness case this table leaves out: after S1 (the claim repair in runner/parked.py) a claim marks
# CARRIED_ON and re-queues its row in ONE transaction, so no claimant can die between the two any
# more. K9c is its barrier-level
# twin: every column the barrier reads (row status, start status and time, event times) is the
# same; only the observation time and the claim's carried_on_at, which the barrier never reads,
# differ.
LIVENESS = sorted(name for name, (shape, _, rule) in FROZEN.items()
                  if rule is None and any(status == "parked" for _, status, *_ in shape["starts"]))


@pytest.mark.parametrize("name", LIVENESS)
def test_t11_bite_b8_without_dead_carry_on_exemption_liveness_rows_block(monkeypatch, name):
    assert LIVENESS == ["C06c-tie-parked-and-failed-ended-row", "C07c-activity-just-before-lease",
                        "K9c-same-state-claimant-dead-pre-repair"]
    mutate_function(monkeypatch, reconcile._cutover_blockers, "~dead_carry_on(start),", "True,")
    assert frozen_answer(name) == {name: 2}


def test_mf32_barrier_uses_s1_latest_start_definition_only():
    """MF3.2: one definition of "latest start", S1's; the barrier keeps no copy of its own."""
    from temper_ai.runner import parked

    source = inspect.getsource(reconcile._cutover_blockers)
    assert source.count("parked.latest_start_condition(start.execution_id, start)") == 1
    assert source.count("aliased(Event)") == 1 and "> start.timestamp" not in source
    assert reconcile.parked is parked


def own_latest_breaking_ties_by_id(start):
    """A drifted copy: ties broken by event id (what MF3.2 forbids)."""
    from sqlalchemy import exists
    from sqlalchemy.orm import aliased

    later = aliased(Event)
    return ~exists(sql_select(1).where(
        col(later.execution_id) == start.execution_id, col(later.type) == "workflow.started",
        (col(later.timestamp) > start.timestamp)
        | ((col(later.timestamp) == start.timestamp) & (col(later.id) > start.id))))


@pytest.mark.parametrize("name", ["C06a-tie-parked-and-waiting", "C06b-tie-parked-and-running"])
def test_mf32_bite_own_latest_rule_breaking_ties_fails_tie_cases(monkeypatch, name):
    monkeypatch.setattr(reconcile, "_own_latest", own_latest_breaking_ties_by_id, raising=False)
    mutate_function(monkeypatch, reconcile._cutover_blockers,
                    "parked.latest_start_condition(start.execution_id, start)", "_own_latest(start)")
    assert frozen_answer(name) == {}  # the parked start wins the tie by id: dead history, passes
    assert FROZEN[name][2] == 2


def test_qg2_a2_attempts_before_and_after_the_boundary_each_counted_once(monkeypatch):
    """QG2-A2-COUNT-ONCE: a1 began and ended before the boundary; after it E is re-queued
    and a2 starts anew. a1's call counted once (reconciled), a2's once (live); neither twice."""
    fixed_clock(monkeypatch)
    execution("E", row="completed", starts=[(NOW - 2 * HOUR, "completed")])
    a1_call = old(at=NOW - HOUR, execution_id="E")
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    with get_session() as session:
        assert reconcile.reconcile_batch(session) == 1
        assert reconcile.reconcile_batch(session) == 0
        assert reconcile.try_cutover(session)
        session.execute(update(WorkflowRun).where(col(WorkflowRun.execution_id) == "E").values(status="running"))
        session.commit()
    a2_start = old({}, at=NOW + timedelta(minutes=1), kind="workflow.started", execution_id="E")
    with get_session() as session:
        session.get(Event, a2_start.id).status = "running"
    a2_call = old(at=NOW + timedelta(minutes=2), execution_id="E")
    capture(a2_call)
    for _ in range(2):
        with get_session() as session:
            assert reconcile.reconcile_batch(session) == 0
            assert reconcile.check_post_cutover(session) == 0
            assert reconcile.coverage_state(session)["cutover_at"] == NOW
    assert sorted((r.event_id, r.origin) for r in final_rows()) == sorted(
        [(a1_call.id, "reconciled"), (a2_call.id, "live")])
    with get_session() as session:
        assert session.exec(select(func.count()).select_from(reconcile.UsageFault)).one() == 0


SWITCH_VALUES = ((None, False), ("", False), (" ", False), ("0", False), ("false", False), ("true", False),
                 ("TRUE", False), ("on", False), ("yes", False), ("01", False), ("1.0", False), (" 1 ", False),
                 ("1 ", False), ("\t1", False), ("1\n", False), ("1", True))


def switch_answers(monkeypatch):
    """cutover_enabled() for every value above, then for "1" with the reconciler off."""
    seen = []
    for value, _ in SWITCH_VALUES:
        if value is None:
            monkeypatch.delenv("TEMPER_USAGE_CUTOVER", raising=False)
        else:
            monkeypatch.setenv("TEMPER_USAGE_CUTOVER", value)
        seen.append(reconcile.cutover_enabled())
    monkeypatch.setenv("TEMPER_USAGE_CUTOVER", "1")
    monkeypatch.setenv("TEMPER_USAGE_RECONCILER", "0")
    seen.append(reconcile.cutover_enabled())
    return seen


SWITCH_ANSWERS = [on for _, on in SWITCH_VALUES] + [False]


def test_cutover_switch_is_on_only_for_exactly_one(monkeypatch):
    """Fail-closed, one read: only the exact value "1"; whitespace, case and synonyms are off."""
    assert SWITCH_ANSWERS.count(True) == 1
    assert switch_answers(monkeypatch) == SWITCH_ANSWERS


@pytest.mark.parametrize("loose", ['("TEMPER_USAGE_CUTOVER", "").strip() == "1"',
                                   '("TEMPER_USAGE_CUTOVER", "").strip().lower() in ("1", "true", "on")',
                                   '("TEMPER_USAGE_CUTOVER") != "0"', '("TEMPER_USAGE_CUTOVER") is not None'])
def test_cutover_switch_exact_value_bites(monkeypatch, loose):
    mutate_function(monkeypatch, reconcile.cutover_enabled, '("TEMPER_USAGE_CUTOVER") == "1"', loose)
    assert switch_answers(monkeypatch) != SWITCH_ANSWERS


def only_switch_observations(monkeypatch, guard=None):
    """Every other condition allows the cutover (three kinds ready, no earlier execution open,
    final lap clean and complete at the ready boundary); only the switch differs."""
    fixed_clock(monkeypatch)
    if guard:
        mutate_function(monkeypatch, *SWITCH_GUARDS[guard])
    old(at=NOW - timedelta(days=1))
    execution("ended-before-T", row="completed", starts=[(NOW - HOUR, "completed")])
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    seen = {}
    with get_session() as session:
        seen["laps"] = [reconcile.reconcile_batch(session), reconcile.reconcile_batch(session)]
        seen["boundary"] = reconcile._ready_boundary(session)
        seen["blockers"] = reconcile._cutover_blockers(session, NOW, NOW)
        coverage = session.get(reconcile.UsageCoverage, 1, populate_existing=True)
        seen["final_lap"] = (as_utc(coverage.lap_ready_at), coverage.lap_clean, coverage.lap_complete)
    for value in ("0", "1"):
        monkeypatch.setenv("TEMPER_USAGE_CUTOVER", value)
        with get_session() as session:
            recorded = reconcile.try_cutover(session)
            checked = reconcile.check_post_cutover(session)
            state = reconcile.coverage_state(session)
            stored = session.get(reconcile.UsageCoverage, 1, populate_existing=True)
            seen[value] = (recorded, checked, state["phase"], state["cutover_at"], as_utc(stored.cutover_at),
                           stored.phase, sum(state["fault_counts"].values()))
    return seen


ONLY_SWITCH_ANSWER = {
    "laps": [1, 0], "boundary": NOW, "blockers": {"executions": 0, "anonymous_open_start": False, "first": []},
    "final_lap": (NOW, True, True),
    "0": (False, 0, "cutover-off", None, None, "backfill", 0),  # off: no row, no fault, phase cutover-off
    "1": (True, 0, "cutover", NOW, NOW, "cutover", 0),  # exactly "1": the cutover is written
}


def test_only_the_switch_stops_a_cutover_every_other_condition_allows(monkeypatch):
    assert only_switch_observations(monkeypatch) == ONLY_SWITCH_ANSWER


def cutover_switch_observations(monkeypatch, guard=None):
    """Switch off from the start: fill and drain run, the barrier is never read. Then on, long
    enough to record a cutover; then off again: the cutover is kept, nothing is faulted.
    A guard is taken out after the clock and recorders are in place (the copy keeps them)."""
    monkeypatch.delenv("TEMPER_USAGE_CUTOVER")
    fixed_clock(monkeypatch)
    barrier_reads = []
    for name in ("_ready_boundary", "_earlier_execution_open"):
        original = getattr(reconcile, name)
        monkeypatch.setattr(reconcile, name,
                            lambda *a, _o=original, _n=name, **k: barrier_reads.append(_n) or _o(*a, **k))
    if guard:
        mutate_function(monkeypatch, *SWITCH_GUARDS[guard])
    old(at=NOW - timedelta(days=1))
    capture(old(at=NOW - timedelta(minutes=1)), pending=True)
    for kind in reconcile.WRITER_KINDS:
        reconcile.mark_ready(kind)
    seen = {}
    with get_session() as session:
        seen["filled"] = [reconcile.reconcile_batch(session), reconcile.reconcile_batch(session)]
        seen["drained"] = reconcile.drain_pending(session)["drained"]
        with recorded_statements() as statements:
            seen["try"] = reconcile.try_cutover(session)
            seen["post"] = reconcile.check_post_cutover(session)
        seen["gated_sql"] = len(statements)
        state = reconcile.coverage_state(session)
        seen["off"] = (state["status"], state["phase"], state["cutover_switch"], state["cutover_at"])
    seen["barrier_reads"] = list(barrier_reads)
    monkeypatch.setenv("TEMPER_USAGE_CUTOVER", "1")
    with get_session() as session:
        while reconcile.reconcile_batch(session):
            pass
        seen["recorded"] = reconcile.try_cutover(session)
    old(at=NOW + timedelta(seconds=1))  # an old-writer call after the cutover, no capture
    monkeypatch.setenv("TEMPER_USAGE_CUTOVER", "0")
    with get_session() as session:
        with recorded_statements() as statements:
            seen["post_kept"] = reconcile.check_post_cutover(session)
        seen["post_kept_sql"] = len(statements)
        seen["fill_after"] = reconcile.reconcile_batch(session)
        state = reconcile.coverage_state(session)
        seen["kept"] = (state["phase"], state["cutover_at"], sum(state["fault_counts"].values()))
    return seen


SWITCH_OFF_ANSWER = {
    "filled": [1, 0], "drained": 1, "try": False, "post": 0, "gated_sql": 0,
    "off": ("UNKNOWN", "cutover-off", "off", None), "barrier_reads": [], "recorded": True,
    "post_kept": 0, "post_kept_sql": 0, "fill_after": 0, "kept": ("cutover-off", NOW, 0),
}


def test_cutover_switch_off_keeps_drain_and_fill_and_never_reads_the_barrier(monkeypatch):
    assert cutover_switch_observations(monkeypatch) == SWITCH_OFF_ANSWER


SWITCH_GUARDS = {  # guard: function, its text, the text with the guard taken out
    "switch-ignored": (reconcile.cutover_enabled,
                       'return enabled() and os.environ.get("TEMPER_USAGE_CUTOVER") == "1"',
                       "return enabled()"),
    "try-cutover": (reconcile.try_cutover, "if not cutover_enabled():", "if not enabled():"),
    "final-lap": (reconcile._begin_lap, "_ready_boundary(session) if cutover_enabled() else None",
                  "_ready_boundary(session)"),
    "post-check": (reconcile.check_post_cutover, "if not cutover_enabled() or", "if not enabled() or"),
    "phase": (reconcile.coverage_state, 'if switch else "cutover-off"', 'if True else "cutover-off"'),
}


@pytest.mark.parametrize("guard", sorted(SWITCH_GUARDS))
def test_cutover_switch_guards_have_individual_bites(monkeypatch, guard):
    assert cutover_switch_observations(monkeypatch, guard) != SWITCH_OFF_ANSWER


@pytest.mark.parametrize("guard", ["switch-ignored", "try-cutover", "phase"])
def test_only_switch_known_answer_bites(monkeypatch, guard):
    assert only_switch_observations(monkeypatch, guard) != ONLY_SWITCH_ANSWER


# Census: every site in the code that runs or in the files that start processes or set their
# environment (CENSUS_ROOTS, plus the top-level compose, Dockerfile and .env files) that runs or
# records a cutover, makes a post-cutover fault, touches the coverage/fault tables by name or
# reads or sets the switch. Docstrings are not sites. A folder root is scanned whole; a file root
# (pyproject.toml: its [project.scripts] and every [tool.*] section) as its whole text.
REPO = Path(__file__).resolve().parents[2]
CENSUS_ROOTS = ("temper_ai", "scripts", "configs", "docker", ".github/workflows",
                "entrypoint.sh", "Makefile", "pyproject.toml")
CUTOVER_CALLS = frozenset({"try_cutover", "check_post_cutover"})
CUTOVER_COLUMNS = frozenset({"cutover_at", "cutover_seq", "phase"})
CUTOVER_TEXT = ("usage_coverage", "usage_faults", "post-cutover-missing-row", "TEMPER_USAGE_CUTOVER",
                "try_cutover", "check_post_cutover")
RECONCILE = "temper_ai/observability/usage_reconcile.py"


def census_sources() -> dict[str, str]:
    missing = [root for root in CENSUS_ROOTS if not (REPO / root).exists()]
    assert not missing, f"census roots missing from the repo: {missing}"
    files = [path for root in CENSUS_ROOTS
             for path in ((REPO / root).rglob("*") if (REPO / root).is_dir() else [REPO / root])
             if path.is_file() and "__pycache__" not in path.parts]
    files += [path for path in REPO.iterdir() if path.is_file() and path.name.startswith(
        ("docker-compose", "compose", "Dockerfile", ".env"))]
    sources = {}
    for path in sorted(files):
        try:
            sources[str(path.relative_to(REPO))] = path.read_text()
        except UnicodeDecodeError:
            continue
    return sources


def scoped(node, scope="<module>"):
    for child in ast.iter_child_nodes(node):
        inner = scope
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inner = child.name if scope == "<module>" else f"{scope}.{child.name}"
        yield scope, child
        yield from scoped(child, inner)


def docstrings(tree):
    return {id(body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and (body := node.body) and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)}


def cutover_census(sources) -> set[tuple[str, str, str]]:
    """(file, function or class, form) for each site; names and codes only."""
    sites = set()
    for path, source in sources.items():
        if not path.endswith(".py"):
            sites |= {(path, "<file>", f"text {word}") for word in CUTOVER_TEXT if word in source}
            continue
        tree = ast.parse(source, filename=path)
        skip = docstrings(tree)
        coverage_module = "UsageCoverage" in source or "usage_coverage" in source
        for scope, node in scoped(tree):
            if isinstance(node, ast.Name) and node.id in CUTOVER_CALLS:
                sites.add((path, scope, f"uses {node.id}"))
            elif isinstance(node, ast.alias) and node.name.rsplit(".", 1)[-1] in CUTOVER_CALLS:
                sites.add((path, scope, f"imports {node.name}"))
            elif isinstance(node, ast.Attribute) and node.attr in CUTOVER_CALLS:
                sites.add((path, scope, f"uses {node.attr}"))
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and (
                    node.attr in CUTOVER_COLUMNS - {"phase"} or (node.attr == "phase" and coverage_module)):
                sites.add((path, scope, f"writes {node.attr}"))
            elif isinstance(node, ast.keyword) and node.arg in CUTOVER_COLUMNS - {"phase"}:
                sites.add((path, scope, f"keyword {node.arg}"))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                sites |= {(path, scope, f"text {word}") for word in CUTOVER_TEXT if word in node.value}
    return sites


CUTOVER_SITES = {
    (RECONCILE, "<module>", "text post-cutover-missing-row"),  # FAULT_CODES
    (RECONCILE, "UsageCoverage", "text usage_coverage"),  # __tablename__
    (RECONCILE, "UsageFault", "text usage_faults"),  # __tablename__
    (RECONCILE, "UsageFault", "text post-cutover-missing-row"),  # CHECK constraint
    (RECONCILE, "cutover_enabled", "text TEMPER_USAGE_CUTOVER"),  # the one read of the switch
    (RECONCILE, "try_cutover", "writes cutover_at"),
    (RECONCILE, "try_cutover", "writes cutover_seq"),
    (RECONCILE, "try_cutover", "writes phase"),
    (RECONCILE, "check_post_cutover", "text post-cutover-missing-row"),
    (RECONCILE, "_sweep", "uses try_cutover"),  # the 60 s wake: the only caller of either
    (RECONCILE, "_sweep", "uses check_post_cutover"),
}


def gated(source, name):
    """The function's first statement after its docstring returns unless cutover_enabled()."""
    function = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)
                    and node.name == name)
    first = function.body[1] if ast.get_docstring(function) else function.body[0]
    test = first.test if isinstance(first, ast.If) else None
    return (isinstance(test, (ast.UnaryOp, ast.BoolOp)) and isinstance(first.body[0], ast.Return)
            and "not cutover_enabled()" in ast.unparse(test) and not first.orelse)


def census_holds(sources):
    return (cutover_census(sources) == CUTOVER_SITES
            and all(gated(sources[RECONCILE], name) for name in sorted(CUTOVER_CALLS)))


def test_cutover_census_every_caller_and_writer_is_behind_the_switch():
    """Off: nothing in this commit runs try_cutover or check_post_cutover except the wake loop,
    whose callees each return first unless cutover_enabled(); only try_cutover writes the
    cutover columns, only check_post_cutover makes the post-cutover fault, and no CLI, script,
    config, compose or Docker file, entrypoint, Makefile, pyproject.toml or CI workflow names
    the switch, the tables or the two functions."""
    sources = census_sources()
    assert RECONCILE in sources and "temper_ai/cli/watch_queue.py" in sources and "temper_ai/server.py" in sources
    assert cutover_census(sources) == CUTOVER_SITES
    assert census_holds(sources)


CENSUS_BITES = {  # bite: file, its text, the text with a bypass or a missing gate
    "cli-caller": ("temper_ai/cli/watch_queue.py", "from temper_ai.observability.usage_reconcile import mark_ready",
                   "from temper_ai.observability.usage_reconcile import mark_ready, try_cutover"),
    "script-sql": ("scripts/usage_feed_epoch.py", 'if __name__ == "__main__":',
                   'SQL = "UPDATE usage_coverage SET phase = 1"\nif __name__ == "__main__":'),
    "compose-env": ("docker-compose.yml", "services:", "# TEMPER_USAGE_CUTOVER\nservices:"),
    "entrypoint-setter": ("entrypoint.sh", 'exec "$@"', 'export TEMPER_USAGE_CUTOVER=1\nexec "$@"'),
    "docker-setter": ("docker/playwright-mcp-webkit/Dockerfile", "\nFROM ",
                      "\nARG TEMPER_USAGE_CUTOVER=1\nFROM "),
    "makefile-setter": ("Makefile", ".PHONY:", "export TEMPER_USAGE_CUTOVER = 1\n.PHONY:"),
    "pyproject-script-caller": ("pyproject.toml", "[project.scripts]\n",
                                '[project.scripts]\ncutover = "temper_ai.observability.usage_reconcile:try_cutover"\n'),
    "pyproject-tool-setter": ("pyproject.toml", "[tool.pytest.ini_options]\n",
                              '[tool.pytest.ini_options]\nenv = ["TEMPER_USAGE_CUTOVER=1"]\n'),
    "workflow-setter": (".github/workflows/ci.yml", 'env:\n  UV_FROZEN: "1"\n',
                        'env:\n  UV_FROZEN: "1"\n  TEMPER_USAGE_CUTOVER: "1"\n'),
    "try-ungated": (RECONCILE, "    if not cutover_enabled():\n        return False", "    if False:\n        return False"),
    "post-ungated": (RECONCILE, "if not cutover_enabled() or not _row_limit(session):",
                     "if not _row_limit(session):"),
    "second-writer": (RECONCILE, "    coverage = _coverage(session, lock=True)\n    if coverage.cutover_at is not None:",
                      "    coverage = _coverage(session, lock=True)\n    coverage.cutover_seq = None\n"
                      "    if coverage.cutover_at is not None:"),
}


@pytest.mark.parametrize("bite", sorted(CENSUS_BITES))
def test_cutover_census_bites(bite):
    path, before, after = CENSUS_BITES[bite]
    sources = census_sources()
    assert sources[path].count(before) == 1, (bite, before)
    assert census_holds(sources)
    sources[path] = sources[path].replace(before, after, 1)
    assert not census_holds(sources)


def test_cutover_census_names_a_missing_root(monkeypatch):
    """A listed root the repo no longer has fails the census by name, never a silent skip."""
    monkeypatch.setitem(globals(), "CENSUS_ROOTS", (*CENSUS_ROOTS, "no-such-root"))
    with pytest.raises(AssertionError, match="no-such-root"):
        census_sources()
