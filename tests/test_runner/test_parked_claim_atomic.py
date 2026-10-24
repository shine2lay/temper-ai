"""A parked run's claim and its row's re-queue in one commit (S1-C1).

``runner.parked`` claims a parked attempt three ways, each one transaction
(``recorder.deciding_events``): the attempt's compare-and-set (still waiting, still the
execution's latest start), then the run's row, locked, and one commit.

* ``claim_and_queue``: the API's path. Re-queues the row, or inserts it.
* ``claim_and_requeue_row``: the worker's. Re-queues the row; a run with no row is refused.
* ``claim_without_box_row``: the in-process one. Claims only a run with no row.

So no connection ever sees the attempt claimed under a row that isn't queued, and every
refusal writes nothing. ``queue_resume`` takes over held clean-ups only after its winning
commit, and never puts a committed claim back.

The known answers come from the S1 cases (producer-claim-cases.json P01-P09;
barrier-claim-cases.json C01-C04, C09, C11, C12 and the K9 clocks). What another connection
sees is read from the tables themselves, not through a barrier. Each bite weakens one guard
in parked.py's own source and gets exactly the declared cases wrong.

On a SQLite file, or on Postgres in the database tier (tests/pgtier.py): never the default
in-memory SQLite, whose one connection threads can't share.
"""

from __future__ import annotations

import inspect
import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import text
from sqlalchemy.orm import aliased
from sqlmodel import col, select

from temper_ai.database import get_database, get_session, init_database, reset_database
from temper_ai.observability import recorder
from temper_ai.observability.event_types import EventType
from temper_ai.observability.models import Event
from temper_ai.observability.recorder import get_event
from temper_ai.runner import holds, parked, queue
from temper_ai.runner.lanes import KEEP_LANE, LANE_KEY, PI_LANE, mark_lane
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.parked import CANCELLED, CARRIED_ON, WAITING, AlreadyCarriedOn
from temper_ai.runner.queue import AlreadyQueued

#: The real re-queue body: a hook wraps this one, never an earlier hook.
_QUEUE_RUN_IN = queue.queue_run_in


@pytest.fixture(autouse=True)
def _shared_database(request, tmp_path):
    """Postgres in the database tier; otherwise a SQLite file, which threads can share."""
    from tests.conftest import TEST_DATABASE_URL

    if request.node.stash.get(TEST_DATABASE_URL, "").startswith("sqlite"):
        reset_database()
        init_database(f"sqlite:///{tmp_path / 'runs.db'}")


class _WatchedLock:
    """The SQLite decision lock, counting the threads that wait on it (test-only)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = threading.Lock()
        self.waiting = 0

    def __enter__(self) -> _WatchedLock:
        with self._count:
            self.waiting += 1
        self._lock.acquire()
        with self._count:
            self.waiting -= 1
        return self

    def __exit__(self, *exc: object) -> None:
        self._lock.release()


@pytest.fixture
def decision_lock(monkeypatch) -> _WatchedLock:
    watched = _WatchedLock()
    monkeypatch.setattr(recorder, "_SQLITE_DECIDE_LOCK", watched)
    return watched


# ── The cases' clock (barrier-claim-cases.json H0, K9a, K9b) ────────────────────────────────

DAY = datetime(2000, 1, 1, tzinfo=UTC)  # the cases' day (cutoff_T 2000-01-01T12:00:00Z)


def at(hms: str) -> datetime:
    hour, minute, second = (int(part) for part in hms.split(":"))
    return DAY.replace(hour=hour, minute=minute, second=second)


H0_START = at("10:00:00")  # A1, the attempt that parked
#: A claim one second old when the barrier looks: inside the quiet window (T+45 min, lease
#: 12:00) and past it (T+6 h, lease 14:00). The claim must not depend on either.
K9 = {"K9a": at("12:44:59"), "K9b": at("17:59:59")}
KEPT = {"box_profile": {"generation": 2}}  # the worker's record: a re-queue keeps it
PARKED_NOTE = {"path": "talk", "event_id": "gate-1"}


def _attempt(run: str, *, name: str = "A1", status: str = WAITING, started: datetime = H0_START,
             note: dict | None = None) -> dict:
    """A run's start; parked (with its note) unless ``note`` is ``{}``. As a reader holds it."""
    event_id = f"{name}-{run}"
    data: dict[str, Any] = {"name": "wf"}
    if note != {}:
        data["parked"] = note or PARKED_NOTE
    with get_session() as session:
        session.add(Event(id=event_id, type=EventType.WORKFLOW_STARTED, execution_id=run,
                          status=status, data=data, timestamp=started))
    read = get_event(event_id)
    assert read is not None
    return read


def _row(run: str, status: str, *, handle: str | None = None, lane: str | None = PI_LANE) -> None:
    """The run's box row: ``running`` with a handle is a box still letting go (C12)."""
    ended = status not in ("queued", "running", WAITING)
    with get_session() as session:
        session.add(WorkflowRun(
            execution_id=run, workflow_name="wf", workspace_path="/ws", inputs={"topic": "t"},
            status=status, spawner_kind="docker" if handle else None, spawner_handle=handle,
            spawner_metadata=mark_lane(dict(KEPT), lane), attempts=1,
            completed_at=at("10:31:00") if ended else None))


def _loads(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _state(run: str, attempt_id: str | None = None) -> dict:
    """The attempt and the run's row as another connection sees them: committed state only,
    every column."""
    with get_database().engine.connect() as conn:
        event = conn.execute(text("select * from events where id = :id"),
                             {"id": attempt_id or f"A1-{run}"}).mappings().one()
        row = conn.execute(text("select * from workflow_runs where execution_id = :id"),
                           {"id": run}).mappings().first()
    return {"event": {**event, "data": _loads(event["data"])},
            "row": None if row is None else {
                **row, "spawner_metadata": _loads(row["spawner_metadata"]),
                "inputs": _loads(row["inputs"])}}


def _seen(run: str) -> dict:
    """What a reader of the claim sees from another connection: A1's status and claim time,
    and the row's status."""
    state = _state(run)
    return {"attempt": state["event"]["status"],
            "carried_on_at": (state["event"]["data"].get("parked") or {}).get("carried_on_at"),
            "row": None if state["row"] is None else state["row"]["status"]}


def _claimed(when: datetime, row: str | None = "queued") -> dict:
    return {"attempt": CARRIED_ON, "carried_on_at": when.isoformat(), "row": row}


UNCLAIMED_ORPHAN = {"attempt": WAITING, "carried_on_at": None, "row": "orphaned"}


def _at_the_split(monkeypatch, then: Callable[[str], None]) -> None:
    """Run ``then`` between the claim's compare-and-set and its re-queue, in the claimant's
    own thread, its transaction open."""

    def split(session, execution_id, *args, **kwargs):
        then(execution_id)
        return _QUEUE_RUN_IN(session, execution_id, *args, **kwargs)

    monkeypatch.setattr(queue, "queue_run_in", split)


def _claim(module: ModuleType, path: str, attempt: dict) -> None:
    if path == "api":
        module.claim_and_queue(attempt, "wf", "/ws", {"topic": "t"}, start="resume",
                               extra={"rerun": []}, lane=KEEP_LANE)
    else:
        module.claim_and_requeue_row(attempt, start="resume", extra={"rerun": []})


@contextmanager
def _writes_and_commits() -> Iterator[list[str]]:
    """The writes and the commits sent to the database meanwhile, in order."""
    seen: list[str] = []
    engine = get_database().engine

    def on_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        words = statement.split()
        verb = words[0].upper()
        if verb in ("UPDATE", "INSERT", "DELETE"):
            table = words[1] if verb == "UPDATE" else words[2]
            seen.append(f"{verb} {table.strip(chr(34)).lower()}")

    def on_commit(conn):  # noqa: ARG001
        seen.append("COMMIT")

    sa_event.listen(engine, "before_cursor_execute", on_execute)
    sa_event.listen(engine, "commit", on_commit)
    try:
        yield seen
    finally:
        sa_event.remove(engine, "before_cursor_execute", on_execute)
        sa_event.remove(engine, "commit", on_commit)


# ── T1: the whole claim, happy path first ─────────────────────────────────────────────────


def test_t1_each_claim_lands_whole_in_one_commit_and_only_its_winner_takes_over(monkeypatch):
    """P01, C04, P06, P07: the three claims and queue_resume, as Resume and the reaper use
    them."""
    claimed_at = K9["K9a"]
    monkeypatch.setattr(parked, "utcnow", lambda: claimed_at)
    at_split: list[tuple[str, dict]] = []
    _at_the_split(monkeypatch, lambda run: at_split.append((run, _seen(run))))

    # The API's Resume over an orphaned row: one commit carries the claim and the re-queue.
    run = "run-t1-api"
    a1 = _attempt(run)
    _row(run, "orphaned", handle="box-h")
    unclaimed = _state(run)
    with _writes_and_commits() as writes:
        parked.claim_and_queue(a1, "wf", "/ws2", {"topic": "again"}, start="resume",
                               extra={"rerun": ["talk"]}, lane=KEEP_LANE)
    assert at_split == [(run, UNCLAIMED_ORPHAN)]  # at the split, nothing shows yet
    first_commit = writes.index("COMMIT")
    assert {"UPDATE events", "UPDATE workflow_runs"} <= set(writes[:first_commit])
    assert set(writes[first_commit:]) == {"COMMIT"}  # no write after the first commit
    assert _seen(run) == _claimed(claimed_at)
    state = _state(run)
    assert state["event"]["data"]["parked"] == {**PARKED_NOTE, "carried_on_at": claimed_at.isoformat()}
    assert state["event"]["timestamp"] == unclaimed["event"]["timestamp"]  # still its start time
    row = state["row"]
    assert (row["workflow_name"], row["workspace_path"], row["inputs"]) == ("wf", "/ws2", {"topic": "again"})
    assert (row["spawner_kind"], row["spawner_handle"]) == (None, None)
    assert row["spawner_metadata"] == {**KEPT, "start": "resume", "rerun": ["talk"], LANE_KEY: PI_LANE}

    # A second asker holding the same read: refused, and nothing written.
    before = _state(run)
    with pytest.raises(AlreadyCarriedOn):
        parked.claim_and_queue(a1, "wf", "/ws", None, start="resume", extra=None, lane=KEEP_LANE)
    assert _state(run) == before

    # The worker's: the reaper let the box go (row waiting). queue_resume claims and
    # re-queues in one commit, and takes over only after it, and only the winner does.
    took: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(holds, "take_over", lambda eid, by: took.append((eid, by, _seen(eid))))
    run = "run-t1-worker"
    _attempt(run)
    _row(run, WAITING)
    parked.queue_resume(run)
    assert took == [(run, run, _claimed(claimed_at))]
    assert _state(run)["row"]["spawner_metadata"] == {**KEPT, "start": "resume", LANE_KEY: PI_LANE}
    before = _state(run)
    with pytest.raises(AlreadyCarriedOn):
        parked.queue_resume(run)  # the attempt is claimed: a loser, which takes nothing over
    assert len(took) == 1
    assert _state(run) == before

    # The API's Resume of a run with no row inserts it, queued.
    run = "run-t1-new"
    a1 = _attempt(run)
    parked.claim_and_queue(a1, "wf", "/ws", None, start="resume", extra=None, lane=PI_LANE)
    assert _seen(run) == _claimed(claimed_at)
    assert _state(run)["row"]["spawner_metadata"] == {"start": "resume", LANE_KEY: PI_LANE}

    # In process: a run with no row is claimed, and no row is made (P13). Only this claim is
    # ever released, when its thread fails to start: back to waiting.
    run = "run-t1-thread"
    a1 = _attempt(run)
    assert parked.claim_without_box_row(a1) is True
    assert _seen(run) == _claimed(claimed_at, row=None)
    parked.release(a1)
    assert _seen(run) == {"attempt": WAITING, "carried_on_at": None, "row": None}
    # ...but a run with a row, of any status, is carried on in its box: nothing written (P12).
    for status in ("orphaned", WAITING, "queued", "running", "completed"):
        run = f"run-t1-boxed-{status}"
        a1 = _attempt(run)
        _row(run, status)
        before = _state(run)
        assert parked.claim_without_box_row(a1) is False
        assert _state(run) == before
    assert len(at_split) == 3  # the in-process claims never re-queue


# ── T2: the split point, at both K9 clocks ────────────────────────────────────────────────


class _Stalled(Exception):  # noqa: N818 - the hook's way out, said as a fact
    pass


SPLIT_CASES = [(path, clock) for path in ("api", "worker") for clock in K9]


def _split_point(module: ModuleType, path: str, clock: str, monkeypatch) -> dict:
    """C01, C09, K9a/K9b: a claimant stalls between its compare-and-set and its re-queue
    while another connection looks; then its re-queue fails; then it claims again."""
    run = f"run-t2-{path}-{clock}-{module.__name__}"
    a1 = _attempt(run)
    _row(run, "orphaned", handle="box-h")
    monkeypatch.setattr(module, "utcnow", lambda: K9[clock])
    before = _state(run)
    seen: list[dict] = []

    def stall(execution_id: str) -> None:
        seen.append(_seen(execution_id))
        raise _Stalled

    _at_the_split(monkeypatch, stall)
    with pytest.raises(_Stalled):
        _claim(module, path, a1)
    rolled_back = _state(run) == before
    _at_the_split(monkeypatch, lambda execution_id: None)
    try:
        _claim(module, path, a1)
    except (AlreadyCarriedOn, AlreadyQueued) as refused:
        return {"at_split": seen, "rolled_back": rolled_back, "again": type(refused).__name__}
    return {"at_split": seen, "rolled_back": rolled_back, "again": _seen(run)}


def _split_known_answer(clock: str) -> dict:
    return {"at_split": [UNCLAIMED_ORPHAN], "rolled_back": True, "again": _claimed(K9[clock])}


@pytest.mark.parametrize(("path", "clock"), SPLIT_CASES)
def test_t2_between_the_claim_and_the_requeue_nothing_shows_and_a_failure_undoes_both(
        path, clock, monkeypatch):
    assert _split_point(parked, path, clock, monkeypatch) == _split_known_answer(clock)


def _wrong_at_the_split(module: ModuleType, monkeypatch) -> set[tuple[str, str]]:
    return {(path, clock) for path, clock in SPLIT_CASES
            if _split_point(module, path, clock, monkeypatch) != _split_known_answer(clock)}


# ── T3: a delayed claimant ────────────────────────────────────────────────────────────────

DELAYED = ("claimed-first", "cancelled-first", "superseded")
REFUSED_UNWRITTEN = ("AlreadyCarriedOn", False)


def _delayed(module: ModuleType, variant: str) -> tuple[str | None, bool]:
    """P03, P04, C02, C02b, C02c: a claimant read the attempt, then stalled before its
    transaction; meanwhile another claim won, a cancel won, or a later start superseded it.
    Returns (its refusal, whether it wrote anything)."""
    run = f"run-t3-{variant}-{module.__name__}"
    a1 = _attempt(run)  # what the delayed claimant read
    if variant == "claimed-first":
        _row(run, WAITING)
        parked.claim_and_queue(get_event(a1["id"]) or {}, "wf", "/ws", None, start="resume",
                               extra=None, lane=KEEP_LANE)
    elif variant == "cancelled-first":
        _row(run, WAITING)
        assert parked.cancel_parked(run, "stopped by the owner")
        assert _state(run)["event"]["status"] == CANCELLED
    else:  # a later start of the run, which ended; A1 itself still says waiting
        _attempt(run, name="A2", status="failed", started=at("10:05:00"), note={})
        _row(run, "failed")
    before = _state(run)
    try:
        _claim(module, "api", a1)
    except (AlreadyCarriedOn, AlreadyQueued) as refused:
        return type(refused).__name__, _state(run) != before
    return None, _state(run) != before


@pytest.mark.parametrize("variant", DELAYED)
def test_t3_a_delayed_claimant_is_refused_and_writes_nothing(variant):
    assert _delayed(parked, variant) == REFUSED_UNWRITTEN


def _wrong_when_delayed(module: ModuleType) -> set[str]:
    return {variant for variant in DELAYED if _delayed(module, variant) != REFUSED_UNWRITTEN}


# ── T4: a busy row ────────────────────────────────────────────────────────────────────────

BUSY_CASES = [(path, busy) for path in ("api", "worker") for busy in ("queued", "running")]
BUSY_REFUSED = ("AlreadyQueued", False)


def _busy(module: ModuleType, path: str, busy: str) -> tuple[str | None, bool]:
    """P05, P15/C12: the row is queued, or running (a Pi box still letting go). Returns
    (the refusal, whether anything was written)."""
    run = f"run-t4-{path}-{busy}-{module.__name__}"
    a1 = _attempt(run)
    _row(run, busy, handle="box-h")
    before = _state(run)
    try:
        _claim(module, path, a1)
    except (AlreadyCarriedOn, AlreadyQueued) as refused:
        return type(refused).__name__, _state(run) != before
    return None, _state(run) != before


@pytest.mark.parametrize(("path", "busy"), BUSY_CASES)
def test_t4_a_busy_row_refuses_the_claim_and_the_attempt_stays_waiting(path, busy):
    assert _busy(parked, path, busy) == BUSY_REFUSED


def _wrong_when_busy(module: ModuleType) -> set[tuple[str, str]]:
    return {(path, busy) for path, busy in BUSY_CASES if _busy(module, path, busy) != BUSY_REFUSED}


# ── T5: a failure after the commit ────────────────────────────────────────────────────────

AFTER_COMMIT_KNOWN = {"raised": "the hold store is down", "seen": _claimed(K9["K9b"]), "released": 0}


def _fails_after_the_commit(module: ModuleType, monkeypatch) -> dict:
    """P08: queue_resume's claim committed, then taking over the holds fails."""
    run = f"run-t5-{module.__name__}"
    _attempt(run)
    _row(run, WAITING)
    monkeypatch.setattr(module, "utcnow", lambda: K9["K9b"])

    def take_over(execution_id: str, by: str) -> None:
        raise RuntimeError("the hold store is down")

    monkeypatch.setattr(holds, "take_over", take_over)
    released: list[str] = []
    real_release = module.release

    def release(attempt: dict) -> None:
        released.append(str(attempt["id"]))
        real_release(attempt)

    monkeypatch.setattr(module, "release", release)
    with pytest.raises(RuntimeError) as raised:
        module.queue_resume(run)
    return {"raised": str(raised.value), "seen": _seen(run), "released": len(released)}


def test_t5_a_failure_after_the_commit_leaves_the_run_queued_and_never_releases(monkeypatch):
    assert _fails_after_the_commit(parked, monkeypatch) == AFTER_COMMIT_KNOWN


# ── T6: the worker path ───────────────────────────────────────────────────────────────────


def test_t6_the_worker_never_makes_a_row_and_carries_a_let_go_run_on_once(monkeypatch):
    """P06, C11: no row is refused with nothing written; the reaper's let-go flow (row
    waiting, then carry_on with queue_resume) carries the run on once."""
    claimed_at = K9["K9a"]
    monkeypatch.setattr(parked, "utcnow", lambda: claimed_at)
    run = "run-t6-no-row"
    a1 = _attempt(run)
    before = _state(run)
    with pytest.raises(RuntimeError, match="the run has no box row"):
        parked.claim_and_requeue_row(a1, start="resume", extra={"rerun": []})
    assert _state(run) == before
    with pytest.raises(RuntimeError, match="the run has no box row"):
        parked.queue_resume(run)
    assert _state(run) == before  # still waiting, and still no row

    monkeypatch.setattr(parked, "pi_switched_off", lambda: False)
    took: list[str] = []
    monkeypatch.setattr(holds, "take_over", lambda eid, by: took.append(eid))
    run = "run-t6-let-go"
    _attempt(run, note={**PARKED_NOTE, "wake_at": at("12:00:00").isoformat()})  # its timer is due
    _row(run, WAITING)  # the reaper's let-go: no box, the row kept open
    assert parked.carry_on(run, start=parked.queue_resume, by="reaper") is True
    assert parked.carry_on(run, start=parked.queue_resume, by="reaper") is False
    assert _seen(run) == _claimed(claimed_at)
    assert took == [run]


# ── The one definition of a latest start ──────────────────────────────────────────────────


def test_latest_start_condition_is_no_strictly_later_start_of_the_same_run():
    _attempt("run-L", name="S0", status="failed", started=at("09:00:00"), note={})
    _attempt("run-L", name="S1", status="completed", started=at("10:00:00"), note={})
    _attempt("run-L", name="S2", started=at("10:00:00"))  # a tie at the latest time
    _attempt("run-M", name="S9", started=at("11:00:00"))  # another run's later start
    with get_session() as session:
        session.add(Event(id="later-step", type="agent.completed", execution_id="run-L",
                          timestamp=at("12:00:00")))  # not a start: it never counts
    latest = {"S1-run-L", "S2-run-L", "S9-run-M"}
    start = aliased(Event)
    with get_session() as session:
        by_column = set(session.exec(select(col(Event.id)).where(
            col(Event.type) == EventType.WORKFLOW_STARTED,
            parked.latest_start_condition(Event.execution_id))).all())
        by_alias = set(session.exec(select(col(start.id)).where(
            col(start.type) == EventType.WORKFLOW_STARTED,
            parked.latest_start_condition(start.execution_id, start))).all())
        # A value: the starts no start of run-L comes after.
        by_value = set(session.exec(select(col(Event.id)).where(
            col(Event.type) == EventType.WORKFLOW_STARTED,
            parked.latest_start_condition("run-L"))).all())
    assert by_column == by_alias == latest
    assert by_value == {"S1-run-L", "S2-run-L", "S9-run-M"}


# ── Two at once ───────────────────────────────────────────────────────────────────────────


def _on_postgres() -> bool:
    return get_database().engine.dialect.name == "postgresql"


def _backend_pid(session) -> int | None:
    if not _on_postgres():
        return None
    return session.connection().exec_driver_sql("select pg_backend_pid()").scalar()


def _wait_until_waiting(lock: _WatchedLock, holder_pid: int | None) -> None:
    """Until the other asker waits on the open claim: on SQLite for the decision lock, on
    Postgres for a lock the holder's transaction has."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if holder_pid is None:
            if lock.waiting:
                return
        else:
            with get_database().engine.connect() as conn:
                if conn.execute(text("select count(*) from pg_stat_activity "
                                     "where :pid = any(pg_blocking_pids(pid))"),
                                {"pid": holder_pid}).scalar():
                    return
        time.sleep(0.01)
    raise AssertionError("the second asker never waited for the open claim")


@pytest.mark.parametrize("round_", [1, 2])
@pytest.mark.parametrize("path", ["api", "worker"])
def test_two_askers_at_once_carry_the_run_on_once(path, round_, decision_lock, monkeypatch):
    """P09: the second asker waits on the first's open claim, then finds it claimed: one
    winner, one re-queue, the loser refused with nothing written."""
    run = f"run-race-{path}-{round_}"
    monkeypatch.setattr(parked, "utcnow", lambda: K9["K9a"])
    a1 = _attempt(run)
    _row(run, "orphaned", handle="box-h")
    paused, go = threading.Event(), threading.Event()
    holder: dict[str, Any] = {}

    def split(session, execution_id, *args, **kwargs):
        if threading.current_thread().name == "first":
            holder["pid"] = _backend_pid(session)
            paused.set()
            assert go.wait(15)
        return _QUEUE_RUN_IN(session, execution_id, *args, **kwargs)

    monkeypatch.setattr(queue, "queue_run_in", split)
    outcome: dict[str, str] = {}

    def ask() -> None:
        try:
            _claim(parked, path, a1)
            outcome[threading.current_thread().name] = "claimed"
        except AlreadyCarriedOn:
            outcome[threading.current_thread().name] = "refused"
        except BaseException as exc:  # noqa: BLE001 - reported below, never retried
            outcome[threading.current_thread().name] = repr(exc)

    with _writes_and_commits() as writes:
        first = threading.Thread(target=ask, name="first")
        first.start()
        assert paused.wait(15)
        second = threading.Thread(target=ask, name="second")
        second.start()
        try:
            _wait_until_waiting(decision_lock, holder["pid"])
            assert second.is_alive()
        finally:
            go.set()
            first.join(20)
            second.join(20)
    assert outcome == {"first": "claimed", "second": "refused"}
    assert writes.count("UPDATE workflow_runs") == 1
    assert writes.count("UPDATE events") == 1
    assert _seen(run) == _claimed(K9["K9a"])


# ── Bites: each guard, weakened in parked.py's own source ─────────────────────────────────


def _mutant(mutations: list[tuple[str, str]], monkeypatch) -> ModuleType:
    """parked.py built again from its own source with ``mutations`` made: the real body with
    one guard weakened, never a copy. It raises parked's own AlreadyCarriedOn."""
    source = inspect.getsource(parked)
    for find, replace in mutations:
        assert source.count(find) == 1, f"parked.py doesn't hold this once: {find!r}"
        source = source.replace(find, replace)
    mutant = ModuleType(f"{parked.__name__}_bitten")
    mutant.__file__ = parked.__file__
    monkeypatch.setitem(sys.modules, mutant.__name__, mutant)
    exec(compile(source, str(parked.__file__), "exec"), mutant.__dict__)  # noqa: S102
    mutant.AlreadyCarriedOn = AlreadyCarriedOn  # type: ignore[attr-defined]
    return mutant


_API_CLAIM = ("execution_id = _claim_in(session, attempt)\n"
              "        queue_run_in(session, execution_id, workflow_name")
_WORKER_CLAIM = ("execution_id = _claim_in(session, attempt)\n"
                 "        row = _locked_row(session, execution_id)\n")
_TAKE_OVER = "    holds.take_over(execution_id, by=execution_id)\n"

#: bite -> (its mutations, the test it bites, exactly the cases that test then gets wrong).
BITES: dict[str, tuple[list[tuple[str, str]], str, set]] = {
    # B1: the claim committed before the re-queue, as two commits again.
    "B1-api": ([(_API_CLAIM, _API_CLAIM.replace(
        "\n        queue_run_in", "\n        session.commit()\n        queue_run_in"))],
        "T2", {("api", "K9a"), ("api", "K9b")}),
    "B1-worker": ([(_WORKER_CLAIM, _WORKER_CLAIM.replace(
        "\n        row =", "\n        session.commit()\n        row ="))],
        "T2", {("worker", "K9a"), ("worker", "K9b")}),
    # B2: a committed claim released when what follows fails.
    "B2": ([(_TAKE_OVER, "    try:\n    " + _TAKE_OVER
             + "    except Exception:\n        release(attempt)\n        raise\n")],
           "T5", {"released"}),
    # B6: the compare-and-set's expect, or the still-latest check, dropped.
    "B6-expect": ([("decide_event_in(session, attempt_id, expect=(WAITING,), status=CARRIED_ON,",
                    "decide_event_in(session, attempt_id, expect=(WAITING, CARRIED_ON, CANCELLED), "
                    "status=CARRIED_ON,")],
                  "T3", {"claimed-first", "cancelled-first"}),
    "B6-latest": ([("    if latest is None:\n        raise AlreadyCarriedOn(execution_id)\n", "")],
                  "T3", {"superseded"}),
    # B10: the claim committed before a busy row refuses it (today's order).
    "B10": ([(_API_CLAIM, _API_CLAIM.replace(
        "\n        queue_run_in",
        "\n        if _locked_row(session, execution_id).status in ('queued', 'running'):"
        "\n            session.commit()\n        queue_run_in"))],
        "T4", {("api", "queued"), ("api", "running")}),
}


def _wrong_after_the_commit(module: ModuleType, monkeypatch) -> set[str]:
    got = _fails_after_the_commit(module, monkeypatch)
    return {"released"} if got != AFTER_COMMIT_KNOWN else set()


@pytest.mark.parametrize("bite", list(BITES))
def test_each_claim_guard_has_a_bite(bite, monkeypatch):
    mutations, bitten_test, expected = BITES[bite]
    bitten = _mutant(mutations, monkeypatch)
    wrong: set = {
        "T2": lambda: _wrong_at_the_split(bitten, monkeypatch),
        "T3": lambda: _wrong_when_delayed(bitten),
        "T4": lambda: _wrong_when_busy(bitten),
        "T5": lambda: _wrong_after_the_commit(bitten, monkeypatch),
    }[bitten_test]()
    assert wrong == expected
