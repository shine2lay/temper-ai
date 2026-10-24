"""W-B3 readiness: a supported v2 row AND no legacy row, on file SQLite and Postgres.

Known-answer cases with fixed database clocks; no workflow, model or provider call,
and nothing but the test's own throwaway database. A legacy start is reproduced with
the statement pre-#126 code runs at startup: a writer_version 1 upsert of its own
usage_writer_ready row (master 5b0be339, usage_reconcile.py:185-194). Legacy code never
reads or writes the v2 table. Mutations change code in memory only, never the source,
the schema or any live state.
"""

from __future__ import annotations

import hashlib
import inspect
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, text
from sqlalchemy import event as sa_event
from sqlmodel import col, select

from temper_ai.database import get_database, get_session
from temper_ai.observability import usage_reconcile as reconcile
from temper_ai.observability import usage_rows as usage
from temper_ai.shared.clock import as_utc

NOW = datetime(2026, 10, 21, 18, tzinfo=UTC)
KINDS = ("server", "worker", "pi-worker")
READY_TABLE = re.compile(r"\b(usage_writer_ready(?:_v2)?)\b")
CLOCK_SQL = re.compile(r"\b(clock_timestamp|strftime)\b", re.IGNORECASE)
FIRST_READY_DML = re.compile(r"^\s*(DELETE FROM usage_writer_ready\b|INSERT INTO usage_writer_ready_v2\b)")


@pytest.fixture(autouse=True)
def readiness_database(request, monkeypatch, tmp_path, _test_db):
    """The Postgres tier when it is on; otherwise a SQLite FILE, never the in-memory one.

    The in-memory database is one shared connection, so it can't show what a file
    database does across connections.
    """
    from temper_ai.database import init_database, reset_database
    from tests.conftest import TEST_DATABASE_URL

    if request.node.stash.get(TEST_DATABASE_URL, "").startswith("sqlite"):
        reset_database()
        init_database(f"sqlite:///{tmp_path / 'readiness.sqlite'}")
    assert postgres() or get_database().engine.url.database == str(tmp_path / "readiness.sqlite")
    monkeypatch.setenv("TEMPER_USAGE_RECONCILER", "1")
    reconcile._stop.clear()
    monkeypatch.setattr(reconcile, "BATCH_PAUSE_SECONDS", 0)
    if postgres():
        with get_session() as session:
            schema = session.execute(text("SELECT current_schema()")).scalar_one()
        key = int.from_bytes(hashlib.sha256(schema.encode()).digest()[:8], "big", signed=True)
        monkeypatch.setattr(usage, "COMMIT_ORDER_LOCK", key)
    yield
    reconcile._stop.clear()


def postgres() -> bool:
    return get_database().engine.dialect.name == "postgresql"


def at(seconds: float) -> datetime:
    return NOW + timedelta(seconds=seconds)


def clock(monkeypatch, value: datetime) -> None:
    """The one DB clock every start and the reconciler read: a fixed, known input."""
    monkeypatch.setattr(reconcile, "_db_now", lambda session: value)


def legacy_marker(kind: str) -> None:
    """Exactly what pre-#126 code runs at startup: upsert its own writer_version 1 row."""
    with usage.sqlite_transaction_lock(), get_database().session() as session:
        reconcile._bounded_statement(session)
        values = {"kind": kind, "writer_version": 1, "ready_at": reconcile._db_now(session)}
        session.execute(reconcile._insert(session, reconcile.UsageWriterReady).values(**values)
                        .on_conflict_do_update(index_elements=["kind"], set_=values))


def start(monkeypatch, kind: str, when: datetime) -> None:
    """A #126 start of one kind at a fixed DB clock."""
    clock(monkeypatch, when)
    reconcile.mark_ready(kind)


def legacy_start(monkeypatch, kind: str, when: datetime) -> None:
    """A legacy start of one kind (a revert, an old checkout or an old image) at a fixed DB clock."""
    clock(monkeypatch, when)
    legacy_marker(kind)


def future_start(monkeypatch, kind: str, when: datetime) -> None:
    """A hypothetical later writer of the same shape, writer_version 3: this reader must not count it."""
    clock(monkeypatch, when)
    with usage.sqlite_transaction_lock(), get_database().session() as session:
        session.execute(delete(reconcile.UsageWriterReady).where(col(reconcile.UsageWriterReady.kind) == kind))
        values = {"kind": kind, "writer_version": 3, "ready_at": reconcile._db_now(session)}
        session.execute(reconcile._insert(session, reconcile.UsageWriterReadyV2).values(**values)
                        .on_conflict_do_update(index_elements=["kind"], set_=values))


def legacy_rows() -> dict[str, datetime]:
    with get_session() as session:
        return {row.kind: as_utc(row.ready_at) for row in session.exec(select(reconcile.UsageWriterReady)).all()}


def current_rows() -> dict[str, tuple[int, datetime]]:
    with get_session() as session:
        return {row.kind: (row.writer_version, as_utc(row.ready_at))
                for row in session.exec(select(reconcile.UsageWriterReadyV2)).all()}


def boundary() -> datetime | None:
    with get_session() as session:
        return reconcile._ready_boundary(session)


def cutover() -> bool:
    """One full lap bound to the readiness as it stands, then a cutover attempt (it locks both tables)."""
    with get_session() as session:
        reconcile.reconcile_batch(session)
        return reconcile.try_cutover(session)


def cutover_at() -> datetime | None:
    with get_session() as session:
        return reconcile.coverage_state(session)["cutover_at"]


def legacy_reader_boundary(*, lock: bool = False) -> datetime | None:
    """The pre-#126 readiness predicate, verbatim: master 5b0be339 :411-415 (lock: :722-728)."""
    with get_session() as session:
        stmt = select(reconcile.UsageWriterReady).where(reconcile.UsageWriterReady.writer_version == 1)
        rows = session.exec(stmt.with_for_update() if lock else stmt).all()
        if {row.kind for row in rows} != reconcile.WRITER_KINDS:
            return None
        return max(as_utc(row.ready_at) for row in rows)


def mutate(monkeypatch, function: Callable[..., Any], before: str, after: str) -> None:
    """Change one actual piece of code in memory; never the source file, schema or live state."""
    source = inspect.getsource(function)
    assert source.count(before) == 1, before
    namespace = dict(vars(reconcile))
    exec(compile(source.replace(before, after, 1), function.__code__.co_filename, "exec"), namespace)
    monkeypatch.setattr(reconcile, function.__name__, namespace[function.__name__])


class SqlLog:
    """Test-only SQL hook: transaction events, DB-clock reads and readiness statements, in order."""

    def __init__(self) -> None:
        self.entries: list[tuple[Any, ...]] = []
        self.connections: set[int] = set()

    def __enter__(self) -> SqlLog:
        self.engine = get_database().engine
        self.listeners = (("begin", self.begin), ("commit", self.commit), ("rollback", self.rollback),
                          ("before_cursor_execute", self.statement))
        for name, listener in self.listeners:
            sa_event.listen(self.engine, name, listener)
        return self

    def __exit__(self, *exc: object) -> None:
        for name, listener in self.listeners:
            sa_event.remove(self.engine, name, listener)

    def begin(self, conn) -> None:
        self.connections.add(id(conn))
        self.entries.append(("begin",))

    def commit(self, conn) -> None:
        self.connections.add(id(conn))
        self.entries.append(("commit",))

    def rollback(self, conn) -> None:
        self.entries.append(("rollback",))

    def statement(self, conn, cursor, statement, parameters, context, executemany) -> None:
        sql = " ".join(statement.split())
        if CLOCK_SQL.search(sql):
            self.connections.add(id(conn))
            self.entries.append(("clock",))
        names = set(READY_TABLE.findall(sql))
        if names:
            self.connections.add(id(conn))
            assert len(names) == 1, sql
            table = "v2" if names.pop() == "usage_writer_ready_v2" else "legacy"
            values = list(parameters.values()) if isinstance(parameters, dict) else list(parameters or ())
            self.entries.append((sql.split()[0].upper(), table, sql, values))

    def shape(self) -> list[tuple[Any, ...]]:
        return [entry[:2] for entry in self.entries]

    def tables(self) -> list[str]:
        return [entry[1] for entry in self.entries if len(entry) == 4]

    def locked(self) -> bool:
        return all("FOR UPDATE" in entry[2] for entry in self.entries if len(entry) == 4)

    def only(self, verb: str) -> tuple[str, list[Any]]:
        found = [entry for entry in self.entries if len(entry) == 4 and entry[0] == verb]
        assert len(found) == 1, found
        return found[0][2], found[0][3]


# --- the seven known-answer cases (each runs on file SQLite and on Postgres) -----------


def clock_repeat(monkeypatch) -> None:
    t = at(0)
    for kind in KINDS:
        start(monkeypatch, kind, t)
    assert boundary() == t
    # The #126 start has stopped; a legacy start of the same kind gets exactly t again.
    legacy_start(monkeypatch, "worker", t)
    assert legacy_rows()["worker"] == current_rows()["worker"][1] == t  # equal stamps, different code
    assert boundary() is None, "CLOCK-REPEAT: a legacy start at the repeated stamp counted ready"
    assert not cutover() and cutover_at() is None
    start(monkeypatch, "worker", t)  # a #126 start, even at that same stamp, makes it ready again
    assert legacy_rows() == {} and boundary() == t
    assert cutover() and cutover_at() == t


def reroll_stale(monkeypatch) -> None:
    for kind in KINDS:  # roll forward: every kind starts #126 code
        start(monkeypatch, kind, at(0))
    assert boundary() == at(0)
    for offset, kind in enumerate(KINDS, start=10):  # revert: every kind restarts legacy code
        legacy_start(monkeypatch, kind, at(offset))
    assert set(current_rows()) == set(KINDS)  # the first roll's v2 rows stay behind, stale
    assert boundary() is None, "REROLL-STALE: stale v2 rows counted after a revert"
    assert legacy_reader_boundary() == at(12)  # the revert alone made legacy readers ready again
    start(monkeypatch, "server", at(20))  # re-roll: so far only the server runs #126 code again
    assert boundary() is None, "REROLL-STALE: stale v2 rows counted while the workers run legacy code"
    assert not cutover() and cutover_at() is None
    start(monkeypatch, "worker", at(21))
    assert boundary() is None, "REROLL-STALE: a stale pi-worker row counted"
    start(monkeypatch, "pi-worker", at(22))
    assert boundary() == at(22) and cutover() and cutover_at() == at(22)


def old_restart_after_new(monkeypatch) -> None:
    for kind in KINDS:
        start(monkeypatch, kind, at(0))
    assert boundary() == at(0)
    legacy_start(monkeypatch, "pi-worker", at(5))  # an old checkout or image restarts one kind later
    assert boundary() is None, "OLD-RESTART-AFTER-NEW: a later legacy restart counted ready"
    assert not cutover() and cutover_at() is None
    start(monkeypatch, "pi-worker", at(6))
    assert boundary() == at(6) and cutover() and cutover_at() == at(6)


def clock_back(monkeypatch) -> None:
    for kind in KINDS:
        start(monkeypatch, kind, at(0))
    legacy_start(monkeypatch, "worker", at(-30))  # the clock stepped back: the legacy stamp is EARLIER
    assert boundary() is None, "CLOCK-BACK: an earlier-stamped legacy restart counted ready"
    assert not cutover() and cutover_at() is None
    start(monkeypatch, "worker", at(-60))  # stepped back again: no stamp is compared with another
    assert legacy_rows() == {}
    assert boundary() == at(0), "CLOCK-BACK: T is the latest v2 stamp"
    assert not cutover()  # unchanged barrier: a lap started (DB clock at(-60)) before T never counts
    clock(monkeypatch, at(1))
    assert cutover() and cutover_at() == at(0)


def fresh_db(monkeypatch) -> None:
    assert legacy_rows() == {} and current_rows() == {}  # never had a legacy start
    clock(monkeypatch, at(0))
    assert boundary() is None and not cutover()
    start(monkeypatch, "server", at(1))
    start(monkeypatch, "worker", at(2))
    assert boundary() is None, "FRESH-DB: two kinds counted as all three"
    start(monkeypatch, "pi-worker", at(3))
    assert legacy_rows() == {}  # a #126 start never writes a legacy row
    assert current_rows() == {"server": (2, at(1)), "worker": (2, at(2)), "pi-worker": (2, at(3))}
    assert boundary() == at(3) and cutover() and cutover_at() == at(3)


def mixed_kinds(monkeypatch) -> None:
    for offset, kind in enumerate(KINDS):  # legacy era: server at(0), worker at(1), pi-worker at(2)
        legacy_start(monkeypatch, kind, at(offset))
    start(monkeypatch, "server", at(10))
    assert legacy_rows() == {"worker": at(1), "pi-worker": at(2)}, "MIXED-KINDS: another kind's marker changed"
    assert boundary() is None, "MIXED-KINDS: legacy kinds counted"
    start(monkeypatch, "worker", at(11))
    assert legacy_rows() == {"pi-worker": at(2)}, "MIXED-KINDS: another kind's marker changed"
    assert boundary() is None, "MIXED-KINDS: a legacy kind counted"
    future_start(monkeypatch, "pi-worker", at(12))  # a later, unsupported writer_version
    assert legacy_rows() == {} and current_rows()["pi-worker"] == (3, at(12))
    assert boundary() is None, "MIXED-KINDS: an unsupported writer_version counted"
    assert not cutover() and cutover_at() is None
    start(monkeypatch, "pi-worker", at(13))
    assert current_rows() == {"server": (2, at(10)), "worker": (2, at(11)), "pi-worker": (2, at(13))}
    assert boundary() == at(13) and cutover() and cutover_at() == at(13)


def old_reader(monkeypatch) -> None:
    for offset, kind in enumerate(KINDS):
        legacy_start(monkeypatch, kind, at(offset))
    assert legacy_reader_boundary() == at(2) and boundary() is None  # before #126: legacy readers only
    start(monkeypatch, "worker", at(10))
    assert legacy_reader_boundary() is None, "OLD-READER: the legacy reader stayed ready after a #126 start"
    assert legacy_reader_boundary(lock=True) is None  # legacy try_cutover's locked read refuses too
    for kind in ("server", "pi-worker"):
        start(monkeypatch, kind, at(11))
    assert legacy_reader_boundary() is None and boundary() == at(11)
    legacy_start(monkeypatch, "server", at(20))  # a revert restarts the server first
    assert legacy_reader_boundary() is None and boundary() is None
    for kind in ("worker", "pi-worker"):
        legacy_start(monkeypatch, kind, at(21))
    assert legacy_reader_boundary() == at(21)  # the revert alone heals legacy readers: no operator step


# --- lock order: legacy table before v2 in mark_ready and try_cutover --------------------


def waits_on(pids: dict[str, int], waiter: str, holder: int, limit: float = 20.0) -> bool:
    """Whether the waiter's backend is blocked by the holder's lock, read live from Postgres."""
    deadline = time.monotonic() + limit
    with get_database().engine.connect() as conn:
        while time.monotonic() < deadline:
            if waiter in pids and holder in conn.execute(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[waiter]}).scalar_one():
                return True
            time.sleep(0.005)
    return False


def interleaved_start_and_cutover(monkeypatch, stamp: datetime) -> None:
    """A worker start paused after its first statement (test-only SQL hook) while a cutover runs.

    Same order on both sides: the cutover waits on the start's legacy-row lock, then reads
    the start's committed v2 row. Opposite orders deadlock or hit lock_timeout instead.
    """
    engine = get_database().engine
    paused, release = threading.Event(), threading.Event()
    pids: dict[str, int] = {}
    seen: list[datetime | None] = []
    errors: list[BaseException] = []
    ready_boundary = reconcile._ready_boundary

    def hook(conn, cursor, statement, parameters, context, executemany):
        if (threading.current_thread().name == "wb3-start" and not paused.is_set()
                and FIRST_READY_DML.match(statement)):
            pids["start"] = cursor.connection.get_backend_pid()
            paused.set()
            release.wait(30)

    def observed(session, *, lock=False):
        found = ready_boundary(session, lock=lock)
        if threading.current_thread().name == "wb3-cutover":
            seen.append(found)
        return found

    def reported(work):
        def run():
            try:
                work()
            except BaseException as error:  # reported below, never retried
                errors.append(error)
        return run

    def attempt():
        with get_session() as session:
            pids["cutover"] = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
            reconcile.try_cutover(session)

    clock(monkeypatch, stamp)
    monkeypatch.setattr(reconcile, "_ready_boundary", observed)
    sa_event.listen(engine, "after_cursor_execute", hook)
    starter = threading.Thread(target=reported(lambda: reconcile.mark_ready("worker")), name="wb3-start")
    cutter = threading.Thread(target=reported(attempt), name="wb3-cutover")
    blocked = False
    try:
        starter.start()
        assert paused.wait(30), "LOCK-ORDER: the start never ran its first statement"
        cutter.start()
        blocked = waits_on(pids, "cutover", pids["start"])
    finally:
        release.set()
        starter.join(30)
        cutter.join(30)
        sa_event.remove(engine, "after_cursor_execute", hook)
        monkeypatch.setattr(reconcile, "_ready_boundary", ready_boundary)
    assert not starter.is_alive() and not cutter.is_alive(), "LOCK-ORDER: a side never finished"
    assert not errors, "LOCK-ORDER: " + "; ".join(
        f"{type(error).__name__}: {str(error).splitlines()[0]}" for error in errors)
    assert blocked, "LOCK-ORDER: the cutover never waited on the start's legacy-row lock"
    assert seen == [stamp], f"LOCK-ORDER: the cutover read {seen}, not the start's committed row"


def statement_order(monkeypatch) -> None:
    legacy_start(monkeypatch, "server", at(60))
    clock(monkeypatch, at(61))
    with SqlLog() as log:
        reconcile.mark_ready("server")
    assert log.tables() == ["legacy", "v2"], f"LOCK-ORDER: mark_ready order {log.tables()}"
    with SqlLog() as log, get_session() as session:
        reconcile.try_cutover(session)
    assert log.tables() == ["legacy", "v2"], f"LOCK-ORDER: try_cutover order {log.tables()}"
    assert not postgres() or log.locked(), "LOCK-ORDER: try_cutover read readiness without FOR UPDATE"


def lock_order(monkeypatch) -> None:
    for kind in KINDS:
        start(monkeypatch, kind, at(0))
    if postgres():
        for stamp in (at(40), at(50)):  # the interleaving twice in a row; a failure is never retried
            legacy_start(monkeypatch, "worker", stamp - timedelta(seconds=5))  # a real legacy row to lock
            interleaved_start_and_cutover(monkeypatch, stamp)
            assert legacy_rows() == {} and current_rows()["worker"] == (2, stamp)
    # Both dialects: the statements themselves run legacy table first, then v2. SQLite has
    # no row locks to order; usage.sqlite_transaction_lock() serializes the whole transactions.
    statement_order(monkeypatch)


# --- tests ------------------------------------------------------------------------------


def test_combined_happy_path_starts_replace_legacy_markers_then_cutover(monkeypatch):
    """Legacy era, each kind's #126 start, readiness, one full lap and cutover, on the real DB clock."""
    assert set(KINDS) == reconcile.WRITER_KINDS
    for kind in KINDS:  # the legacy era: every kind's latest start was legacy code
        legacy_marker(kind)
    assert set(legacy_rows()) == set(KINDS) and legacy_reader_boundary() is not None
    assert boundary() is None and current_rows() == {}
    real_now = reconcile._db_now
    stamps: dict[str, datetime] = {}
    for done, kind in enumerate(KINDS, start=1):
        reads: list[datetime] = []

        def counted(session, reads=reads):
            reads.append(real_now(session))
            return reads[-1]

        monkeypatch.setattr(reconcile, "_db_now", counted)
        with SqlLog() as log:
            reconcile.mark_ready(kind)
        monkeypatch.setattr(reconcile, "_db_now", real_now)
        # ONE transaction: this kind's legacy DELETE, one DB-clock read, then the v2 upsert binding it.
        assert log.shape() == [("begin",), ("DELETE", "legacy"), ("clock",), ("INSERT", "v2"), ("commit",)]
        assert len(log.connections) == 1
        assert log.only("DELETE")[1] == [kind]
        assert len(reads) == 1 and not CLOCK_SQL.search(log.only("INSERT")[0])
        stamps[kind] = as_utc(reads[0])
        assert current_rows()[kind] == (2, stamps[kind])
        assert set(legacy_rows()) == set(KINDS[done:])  # only the starting kind's legacy row went
        assert boundary() == (max(stamps.values()) if done == len(KINDS) else None)
    with get_session() as session:
        reconcile.reconcile_batch(session)
    with SqlLog() as log, get_session() as session:
        assert reconcile.try_cutover(session)
    assert log.tables() == ["legacy", "v2"]
    assert not postgres() or log.locked()
    assert cutover_at() == max(stamps.values())
    assert legacy_reader_boundary() is None  # legacy readers fail closed, they never cut over


def test_clock_repeat_legacy_start_at_the_repeated_stamp_is_not_ready(monkeypatch):
    clock_repeat(monkeypatch)


def test_reroll_stale_v2_rows_never_count_until_every_kind_restarts(monkeypatch):
    reroll_stale(monkeypatch)


def test_old_restart_after_new_is_not_ready(monkeypatch):
    old_restart_after_new(monkeypatch)


def test_clock_back_compares_no_stamps(monkeypatch):
    clock_back(monkeypatch)


def test_fresh_db_needs_all_three_starts(monkeypatch):
    fresh_db(monkeypatch)


def test_mixed_kinds_delete_only_own_marker_and_unsupported_version_fails_closed(monkeypatch):
    mixed_kinds(monkeypatch)


def test_old_reader_fails_closed_after_a_start_and_a_revert_heals_it(monkeypatch):
    old_reader(monkeypatch)


def test_lock_order_legacy_before_v2_in_start_and_cutover(monkeypatch):
    lock_order(monkeypatch)


# --- bites: each guard removed in memory fails its declared case ----------------------

EQUALITY_WITNESS = (
    "    ready = [row for row in session.exec(current).all() if row.kind not in stale]\n",
    "    paired = {row.kind: as_utc(row.ready_at) for row in session.exec(select(UsageWriterReady)).all()}\n"
    "    ready = [row for row in session.exec(current).all()\n"
    "             if row.kind not in stale or paired[row.kind] == as_utc(row.ready_at)]\n",
)
NO_ABSENCE = (" if row.kind not in stale]", "]")
REVERSED_READER = (
    "    stale = set(session.exec(legacy).all())\n"
    "    ready = [row for row in session.exec(current).all() if row.kind not in stale]\n",
    "    rows = session.exec(current).all()\n"
    "    stale = set(session.exec(legacy).all())\n"
    "    ready = [row for row in rows if row.kind not in stale]\n",
)
_DELETE = ("        session.execute(delete(UsageWriterReady).where(col(UsageWriterReady.kind) == kind)\n"
           "                        .execution_options(synchronize_session=False))\n")
_UPSERT = ('        values = {"kind": kind, "writer_version": READY_VERSION, "ready_at": _db_now(session)}\n'
           "        session.execute(_insert(session, UsageWriterReadyV2).values(**values).on_conflict_do_update(\n"
           '            index_elements=["kind"], set_=values,\n'
           "        ))\n")
REVERSED_WRITER = (_DELETE + _UPSERT, _UPSERT + _DELETE)


def test_equality_witness_bite_fails_clock_repeat(monkeypatch):
    mutate(monkeypatch, reconcile._ready_boundary, *EQUALITY_WITNESS)
    with pytest.raises(AssertionError, match="CLOCK-REPEAT: a legacy start at the repeated stamp counted ready"):
        clock_repeat(monkeypatch)


@pytest.mark.parametrize(("name", "case"), [("OLD-RESTART-AFTER-NEW", old_restart_after_new),
                                            ("REROLL-STALE", reroll_stale)])
def test_dropped_absence_check_bites(monkeypatch, name, case):
    mutate(monkeypatch, reconcile._ready_boundary, *NO_ABSENCE)
    with pytest.raises(AssertionError, match=f"{name}: "):
        case(monkeypatch)


@pytest.mark.parametrize("side", ["reader", "writer"])
def test_reversed_lock_order_bites(monkeypatch, side):
    if side == "reader":
        mutate(monkeypatch, reconcile._ready_boundary, *REVERSED_READER)
    else:
        mutate(monkeypatch, reconcile.mark_ready, *REVERSED_WRITER)
    expected = (r"LOCK-ORDER: .*(deadlock detected|due to lock timeout)" if postgres()
                else r"LOCK-ORDER: \w+ order \['v2', 'legacy'\]")
    with pytest.raises(AssertionError, match=expected):
        lock_order(monkeypatch)
