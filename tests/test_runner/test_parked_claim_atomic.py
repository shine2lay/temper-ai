"""A parked run's claim and its row's re-queue in one commit (S1-C1/C2).

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
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
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
def _shared_database(request, tmp_path, monkeypatch):
    """Postgres in the database tier; otherwise a SQLite file, which threads can share."""
    from tests.conftest import TEST_DATABASE_URL

    monkeypatch.setenv("WORKSPACE_DIR", "/workspaces")
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
            execution_id=run, workflow_name="wf", workspace_path="/workspaces/ws", inputs={"topic": "t"},
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
        module.claim_and_queue(attempt, "wf", "/workspaces/ws", {"topic": "t"}, start="resume",
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
        parked.claim_and_queue(a1, "wf", "/workspaces/ws2", {"topic": "again"}, start="resume",
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
    assert (row["workflow_name"], row["workspace_path"], row["inputs"]) == (
        "wf", "/workspaces/ws2", {"topic": "again"})
    assert (row["spawner_kind"], row["spawner_handle"]) == (None, None)
    assert row["spawner_metadata"] == {**KEPT, "start": "resume", "rerun": ["talk"], LANE_KEY: PI_LANE}

    # A second asker holding the same read: refused, and nothing written.
    before = _state(run)
    with pytest.raises(AlreadyCarriedOn):
        parked.claim_and_queue(a1, "wf", "/workspaces/ws", None, start="resume", extra=None, lane=KEEP_LANE)
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
    parked.claim_and_queue(a1, "wf", "/workspaces/ws", None, start="resume", extra=None, lane=PI_LANE)
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
        parked.claim_and_queue(get_event(a1["id"]) or {}, "wf", "/workspaces/ws", None, start="resume",
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


# ── C2: the actual Resume route, with threads counted, never run ───────────────────────────


@pytest.fixture
def resume_rig(monkeypatch):
    from temper_ai.api import routes
    from temper_ai.stage.agent_node import AgentNode
    from temper_ai.stage.models import NodeConfig, WorkflowConfig

    nodes = [AgentNode(NodeConfig(name="talk"), {"name": "pi", "type": "pi"})]
    config = WorkflowConfig(name="wf", inputs={"topic": {"default": "default-topic"}})
    state = SimpleNamespace(
        graph_loader=SimpleNamespace(load_workflow=lambda name: (nodes, config)),
        running={}, gates={}, memory_service=None, llm_providers={})
    rig = SimpleNamespace(routes=routes, state=state, nodes=nodes, config=config,
                          starts=[], took=[], released=[], start_error=None,
                          before_take=None, hold_error=None)
    monkeypatch.setattr(routes, "_state", lambda: state)
    monkeypatch.setattr(routes, "_build_notifier", lambda *args: None)
    monkeypatch.setattr(parked, "pi_switched_off", lambda: False)
    monkeypatch.setattr(parked, "utcnow", lambda: K9["K9a"])
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    monkeypatch.setenv("TEMPER_LANE", PI_LANE)
    monkeypatch.delenv("TEMPER_BOX_RUNTIME_BOUNDARY", raising=False)

    class CountedThread:
        def __init__(self, *, args, **kwargs):
            self.run = args[4]

        def start(self):
            rig.starts.append((self.run, _seen(self.run)))
            if rig.start_error is not None:
                raise rig.start_error
            # No target called: no workflow, box, provider or model.

    monkeypatch.setattr(routes, "threading", SimpleNamespace(Thread=CountedThread))
    real_take, real_release = holds.take_over, parked.release

    def take_over(eid, by):
        rig.took.append((eid, _seen(eid)))
        if rig.before_take is not None:
            rig.before_take(eid)
        if rig.hold_error is not None:
            raise rig.hold_error
        return real_take(eid, by)

    def release(attempt):
        rig.released.append(attempt["id"])
        real_release(attempt)

    monkeypatch.setattr(holds, "take_over", take_over)
    monkeypatch.setattr(parked, "release", release)
    return rig


def _resume_reply(module: ModuleType, run: str, **body) -> tuple[int, str]:
    try:
        response = module._resume_run(run, module.ResumeRequest(**body))
    except HTTPException as exc:
        return exc.status_code, exc.detail
    return 200, response.status


def _hold(run: str) -> None:
    holds.record(run, workflow_name="wf", workspace_path="/workspaces/ws", inputs={"topic": "t"},
                 held=[{"path": "cleanup"}], deadline=at("11:00:00"))


def _hold_state(run: str) -> dict:
    with get_database().engine.connect() as conn:
        return dict(conn.execute(text("select * from cleanup_holds where execution_id = :id"),
                                 {"id": run}).mappings().one())


def test_t8_resume_queues_atomically_then_takes_the_hold_and_keeps_its_api_reply(resume_rig):
    """Opening combined happy path: the real route, real atomic claim, actual held cleanup,
    loaded workflow inputs/lane, rerun and workspace, and the old second-Resume refusal."""
    rig = resume_rig
    run = "run-t8-happy"
    _attempt(run)
    _row(run, "orphaned", handle="old-box")
    _hold(run)
    assert _resume_reply(rig.routes, run, workspace_path="/workspaces/resumed", rerun=["talk"]) == (200, "queued")
    assert _seen(run) == _claimed(K9["K9a"])
    assert rig.took == [(run, _claimed(K9["K9a"]))]
    assert _hold_state(run)["status"] == "taken_over"
    row = _state(run)["row"]
    assert (row["workflow_name"], row["workspace_path"], row["inputs"]) == (
        "wf", "/workspaces/resumed", {"topic": "default-topic"})
    assert row["spawner_metadata"] == {**KEPT, "start": "resume", "rerun": ["talk"], LANE_KEY: PI_LANE}
    assert row["spawner_kind"] is None and row["spawner_handle"] is None
    assert _resume_reply(rig.routes, run) == (409, f"Execution '{run}' is already running")
    assert len(rig.took) == 1 and rig.released == rig.starts == []


def test_unsafe_parked_resume_is_400_and_preserves_claim_row_and_cleanup(resume_rig):
    run = "workspace-refused-resume"
    _attempt(run)
    _row(run, "orphaned", handle="old-box")
    _hold(run)
    before, hold_before = _state(run), _hold_state(run)
    status, detail = _resume_reply(resume_rig.routes, run, workspace_path="/outside")
    assert status == 400 and "'/outside'" in detail
    assert _state(run) == before and _hold_state(run) == hold_before
    assert resume_rig.took == resume_rig.released == resume_rig.starts == []


IN_PROCESS_ROWS = ("orphaned", WAITING, "queued", "running", "completed", "failed", "cancelled")


def _in_process_row_answer(module: ModuleType, rig, status: str, suffix: str) -> dict:
    run = f"run-t7-row-{status}-{suffix}"
    _attempt(run)
    _row(run, status)
    _hold(run)
    before, hold_before = _state(run), _hold_state(run)
    counts = len(rig.took), len(rig.released), len(rig.starts)
    reply = _resume_reply(module, run)
    return {"reply": reply, "unwritten": _state(run) == before,
            "hold_unchanged": _hold_state(run) == hold_before,
            "counts_unchanged": counts == (len(rig.took), len(rig.released), len(rig.starts)),
            "not_running_here": run not in rig.state.running}


def _in_process_row_known(status: str, suffix: str) -> dict:
    run = f"run-t7-row-{status}-{suffix}"
    return {"reply": (409, f"Execution '{run}' is carried on in its box"), "unwritten": True,
            "hold_unchanged": True, "counts_unchanged": True, "not_running_here": True}


@pytest.mark.parametrize("status", IN_PROCESS_ROWS)
def test_t7_in_process_resume_of_any_box_row_is_a_409_and_writes_nothing(status, resume_rig, monkeypatch):
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    assert _in_process_row_answer(resume_rig.routes, resume_rig, status, "real") == _in_process_row_known(status, "real")


def test_t7_only_no_row_thread_start_failure_releases_and_the_retry_can_start(resume_rig, monkeypatch):
    rig = resume_rig
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    run = "run-t7-no-row"
    _attempt(run)
    _hold(run)
    rig.start_error = _Stalled("thread failed to start")
    with pytest.raises(_Stalled, match="thread failed to start"):
        rig.routes._resume_run(run)
    assert rig.took == rig.starts == [(run, _claimed(K9["K9a"], row=None))]
    assert rig.released == [f"A1-{run}"]
    assert _seen(run) == {"attempt": WAITING, "carried_on_at": None, "row": None}
    assert run not in rig.state.running
    rig.start_error = None
    assert _resume_reply(rig.routes, run) == (200, "resuming")
    assert _seen(run) == _claimed(K9["K9a"], row=None)
    assert rig.starts == rig.took == [(run, _claimed(K9["K9a"], row=None))] * 2
    assert rig.released == [f"A1-{run}"]  # not released after the successful start


@pytest.mark.parametrize("failure", ["holds", "thread-preparation"])
def test_t7_a_no_row_failure_other_than_thread_start_never_releases(failure, resume_rig, monkeypatch):
    rig = resume_rig
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    run = f"run-t7-{failure}"
    _attempt(run)
    if failure == "holds":
        rig.hold_error = _Stalled("holds failed")
    else:
        def fail(*args, **kwargs):
            raise _Stalled("preparation failed")
        monkeypatch.setattr(rig.routes, "_register_run_tools", fail)
    with pytest.raises(_Stalled):
        rig.routes._resume_run(run)
    assert _seen(run) == _claimed(K9["K9a"], row=None)
    assert rig.released == rig.starts == []


@pytest.mark.parametrize("mode", ["external", "inprocess"])
def test_non_parked_resume_keeps_its_claim_hold_and_error_release(mode, resume_rig, monkeypatch):
    """Pre-admission failure releases the claim; admitted work keeps its claim on later errors."""
    from temper_ai.runner import resume_claim

    rig = resume_rig
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", mode)
    run = f"run-non-parked-{mode}"
    _attempt(run, status="interrupted", note={})
    _hold(run)
    rig.hold_error = _Stalled("hold failed")
    with pytest.raises(_Stalled, match="hold failed"):
        rig.routes._resume_run(run)
    assert rig.released == rig.starts == []
    assert _state(run)["event"]["status"] == "interrupted"
    rig.hold_error = None
    if mode == "external":
        assert _state(run)["row"]["status"] == "queued"
        assert resume_claim._read(run) is not None
        assert _hold_state(run)["status"] == "waiting"
        # A hold-writer fault after commit never admits a second successor.
        assert _resume_reply(rig.routes, run)[0] == 409
    else:
        assert resume_claim._read(run) is None
        assert _resume_reply(rig.routes, run) == (200, "resuming")
        assert resume_claim._read(run) is not None
        assert _hold_state(run)["status"] == "taken_over"


HOLD_CASES = ("winner", "cancel-first", "superseded", "busy", "queue-error", "post-commit-error", "sweep")


def _holds_answer(module: ModuleType, rig, case: str, monkeypatch) -> dict:
    """P10/P11 plus busy/failure twins, using Resume's observed attempt and its real claims.
    Cancel-first is injected after the route's read, before entering the real atomic claim."""
    run = f"run-t8-{case}-{module.__name__}"
    _attempt(run)
    status = "running" if case == "busy" else WAITING if case == "cancel-first" else "orphaned"
    _row(run, status, handle="old-box")
    _hold(run)
    cleanup: list[tuple[int, str]] = []
    if case in ("cancel-first", "superseded"):
        real_claim = parked.claim_and_queue

        def delayed(attempt, *args, **kwargs):
            if case == "cancel-first":
                assert parked.cancel_parked(run, "owner cancelled") is True
                _hold(run)  # the cancel's fresh hold must not be ended by this stale asker
            else:
                _attempt(run, name="A2", status="failed", started=at("10:05:00"), note={})
            return real_claim(attempt, *args, **kwargs)

        monkeypatch.setattr(parked, "claim_and_queue", delayed)
    elif case == "queue-error":
        def fail_queue(*args, **kwargs):
            raise _Stalled("queue failed")
        monkeypatch.setattr(queue, "queue_run_in", fail_queue)
    elif case == "post-commit-error":
        rig.hold_error = _Stalled("hold failed")
    elif case == "sweep":
        def sweep(eid):
            due = [h for h in holds.due(now=K9["K9a"]) if h["execution_id"] == eid]
            assert len(due) == 1
            try:
                module._queue_cleanup_pass(eid, by="deadline")
            except HTTPException as exc:
                cleanup.append((exc.status_code, exc.detail))
        rig.before_take = sweep
    try:
        reply = _resume_reply(module, run)
    except _Stalled as exc:
        reply = (500, str(exc))
    return {"reply": reply, "seen": _seen(run), "takeovers": list(rig.took),
            "hold": _hold_state(run)["status"], "releases": list(rig.released),
            "starts": list(rig.starts), "cleanup": cleanup}


def _holds_known(module: ModuleType, case: str) -> dict:
    run = f"run-t8-{case}-{module.__name__}"
    claimed = _claimed(K9["K9a"])
    seen = {"attempt": WAITING, "carried_on_at": None,
            "row": "running" if case == "busy" else "orphaned"}
    replies = {"cancel-first": (409, f"Execution '{run}' is already being carried on"),
               "superseded": (409, f"Execution '{run}' is already being carried on"),
               "busy": (409, f"Execution '{run}' is already running"),
               "queue-error": (500, "queue failed"), "post-commit-error": (500, "hold failed")}
    won = case in ("winner", "post-commit-error", "sweep")
    if case == "cancel-first":
        seen = {"attempt": CANCELLED, "carried_on_at": None, "row": "cancelled"}
    return {"reply": replies.get(case, (200, "queued")), "seen": claimed if won else seen,
            "takeovers": [(run, claimed)] if won else [],
            "hold": "taken_over" if case in ("winner", "sweep") else "waiting",
            "releases": [], "starts": [],
            "cleanup": [(409, f"Execution '{run}' is already queued")] if case == "sweep" else []}


@pytest.mark.parametrize("case", HOLD_CASES)
def test_t8_only_a_winning_resume_takes_over_and_a_post_commit_sweep_cannot_queue(case, resume_rig, monkeypatch):
    assert _holds_answer(resume_rig.routes, resume_rig, case, monkeypatch) == _holds_known(resume_rig.routes, case)


@pytest.mark.parametrize("path", ["api", "worker"])
@pytest.mark.parametrize("round_", [1, 2])
def test_t12_a_busy_box_gets_409_then_the_actual_reaper_lets_go_and_resume_queues_once(
        path, round_, resume_rig, monkeypatch):
    from temper_ai.spawner.reaper import Reaper

    rig = resume_rig
    run = f"run-t12-{path}-{round_}"
    note = {**PARKED_NOTE, "wake_at": at("12:00:00").isoformat()} if path == "worker" else None
    _attempt(run, note=note)
    _row(run, "running", handle="box-h")
    with get_session() as session:
        row = session.get(WorkflowRun, run)
        assert row is not None
        row.spawner_metadata = {**(row.spawner_metadata or {}), "container_id": "d" * 64}
    _hold(run)
    before = _state(run)
    assert _resume_reply(rig.routes, run) == (409, f"Execution '{run}' is already running")
    assert _state(run) == before and rig.took == rig.released == rig.starts == []
    letting_go: list[dict] = []
    real_carry = parked.carry_on

    def carry(eid, **kwargs):
        letting_go.append(_seen(eid))
        return real_carry(eid, **kwargs)

    monkeypatch.setattr(parked, "carry_on", carry)
    spawner = SimpleNamespace(is_alive=lambda handle: False, is_gone=lambda handle: True)
    reaper = Reaper(spawner, lane=PI_LANE)
    reaper.tick()  # no background thread, no spawner call except the two stand-ins above
    assert letting_go == [{"attempt": WAITING, "carried_on_at": None, "row": WAITING}]
    if path == "api":
        assert _seen(run) == letting_go[0]
        assert _resume_reply(rig.routes, run) == (200, "queued")
    assert _seen(run) == _claimed(K9["K9a"])
    assert rig.took == [(run, _claimed(K9["K9a"]))]
    assert rig.released == rig.starts == []
    assert _state(run)["row"]["completed_at"] is None
    before = _state(run)
    reaper.tick()
    assert _state(run) == before and len(rig.took) == 1


@pytest.mark.parametrize("path", ["boxed", "inprocess"])
@pytest.mark.parametrize("round_", [1, 2])
def test_two_actual_resumes_at_once_have_one_claim_one_hold_takeover_and_one_start(
        path, round_, resume_rig, decision_lock, monkeypatch):
    rig = resume_rig
    run = f"run-route-race-{path}-{round_}"
    _attempt(run)
    if path == "boxed":
        _row(run, "orphaned", handle="box-h")
    else:
        monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    _hold(run)
    paused, go = threading.Event(), threading.Event()
    holder: dict[str, Any] = {}
    real_locked = parked._locked_row

    def locked(session, eid):
        if threading.current_thread().name == "route-first":
            holder["pid"] = _backend_pid(session)
            paused.set()
            assert go.wait(15)
        return real_locked(session, eid)

    if path == "boxed":
        def split(session, eid, *args, **kwargs):
            if threading.current_thread().name == "route-first":
                holder["pid"] = _backend_pid(session)
                paused.set()
                assert go.wait(15)
            return _QUEUE_RUN_IN(session, eid, *args, **kwargs)
        monkeypatch.setattr(queue, "queue_run_in", split)
    else:
        monkeypatch.setattr(parked, "_locked_row", locked)
    outcome: dict[str, Any] = {}

    def ask():
        try:
            outcome[threading.current_thread().name] = _resume_reply(rig.routes, run)
        except BaseException as exc:  # noqa: BLE001 - fail with the actual exception, no retry
            outcome[threading.current_thread().name] = repr(exc)

    first = threading.Thread(target=ask, name="route-first")
    first.start()
    assert paused.wait(15)
    second = threading.Thread(target=ask, name="route-second")
    second.start()
    try:
        _wait_until_waiting(decision_lock, holder["pid"])
        assert second.is_alive()
    finally:
        go.set()
        first.join(20)
        second.join(20)
    assert not first.is_alive() and not second.is_alive()
    assert outcome == {"route-first": (200, "queued" if path == "boxed" else "resuming"),
                       "route-second": (409, f"Execution '{run}' is already being carried on")}
    claimed = _claimed(K9["K9a"], row="queued" if path == "boxed" else None)
    assert _seen(run) == claimed and rig.took == [(run, claimed)]
    assert rig.released == []
    assert rig.starts == ([] if path == "boxed" else [(run, claimed)])


# ── C2 bites: actual guarded source, the same named known-answer cases ─────────────────────


def _routes_mutant(mutations: list[tuple[str, str]], monkeypatch) -> ModuleType:
    from temper_ai.api import routes

    source = inspect.getsource(routes._resume_run) + "\n" + inspect.getsource(routes._start_resume)
    for find, replace in mutations:
        assert source.count(find) == 1, f"Resume source doesn't hold this once: {find!r}"
        source = source.replace(find, replace)
    mutant = ModuleType(f"{routes.__name__}_bitten")
    mutant.__dict__.update(vars(routes))
    mutant.__name__ = f"{routes.__name__}_bitten"
    monkeypatch.setitem(sys.modules, mutant.__name__, mutant)
    exec(compile(source, str(routes.__file__), "exec"), mutant.__dict__)  # noqa: S102
    return mutant


def test_b3_allowing_an_in_process_claim_over_a_row_breaks_t7_all_row_cases(resume_rig, monkeypatch):
    rig = resume_rig
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    bitten = _mutant([("            if _locked_row(session, execution_id) is not None:\n",
                       "            if False:  # B3: claim a boxed run in process\n")], monkeypatch)
    monkeypatch.setattr(bitten, "pi_switched_off", lambda: False)
    monkeypatch.setattr(bitten, "utcnow", lambda: K9["K9a"])
    monkeypatch.setattr(rig.routes, "pi_parked", bitten)
    wrong = {status for status in IN_PROCESS_ROWS
             if _in_process_row_answer(rig.routes, rig, status, "B3") != _in_process_row_known(status, "B3")}
    assert wrong == set(IN_PROCESS_ROWS)


@pytest.mark.parametrize("case", HOLD_CASES)
def test_b7_taking_over_before_the_claim_breaks_t8_named_cases(case, resume_rig, monkeypatch):
    rig = resume_rig
    before = "        else:\n            try:\n                pi_parked.claim_and_queue("
    after = "            holds.take_over(execution_id, by=execution_id)\n        return RunResponse(execution_id=execution_id, status=\"queued\")"
    bitten = _routes_mutant([
        (before, before.replace("            try:", "            holds.take_over(execution_id, by=execution_id)\n            try:")),
        (after, after.replace("            holds.take_over(execution_id, by=execution_id)\n", "")),
    ], monkeypatch)
    got = _holds_answer(bitten, rig, case, monkeypatch)
    assert got != _holds_known(bitten, case)
