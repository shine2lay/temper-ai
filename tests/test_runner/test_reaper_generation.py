"""The reaper ends a run's row only on the generation its tick judged.

Each tick judges every live row from one snapshot, then asks the spawner about the row's
box, signals it, and ends the row of a box that is gone. Between the snapshot and the end
the run can move on: its box ends it, a resume re-queues it, a new dispatch starts it
again, under the same name for a Docker run. Every end the reaper writes is fenced on the
judged generation (runner/row_generation.py): it changes the row only while the row is
still that generation, and the run's event is settled only when this write ended it.

The known-answer cases drive the real ``Reaper``: its snapshot, its spawner calls and its
fenced writes. A fake spawner lets the run move on at the exact call the race needs (after
its answer is fixed, as a box changes while the reaper waits on it), or a statement hook
lets it move on just before the reaper's write; where another reaper ends the row first,
that is a second real reaper's tick. Each case says what the reaper must change, answer,
settle and signal, and how it leaves the row.

The bites weaken one guard in the real module's own source (the reaper's, or the fence's)
and show exactly which cases it was keeping right, while every genuine end, and every dead
twin's, still lands. The stale cases are then run on: once the newer generation's box is
gone too, the next tick ends that generation.

Not fenced here yet: the reaper's effects. A stale SIGKILL still goes by the box's name,
which a new dispatch of a Docker run reuses (ABA1-C847F-B records it as it is today), and
a forced stop still clears a Pi run's member boxes and its grace whatever its write did.
Those are fenced on the same judged generation in a change of their own, which changes
ABA1-C847F-B's signal and row.

On a SQLite file, or on Postgres in the database tier (tests/pgtier.py): never the default
in-memory SQLite, whose one connection threads can't share.
"""

from __future__ import annotations

import inspect
import itertools
import logging
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy import event as sa_event
from sqlmodel import col

from temper_ai.database import get_database, get_session, init_database, reset_database
from temper_ai.observability.models import Event
from temper_ai.observability.reconcile import settle_run_event
from temper_ai.runner import row_generation
from temper_ai.runner.lanes import PI_LANE, mark_lane
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.parked import CARRIED_ON, WAITING
from temper_ai.spawner import reaper as reaper_module
from temper_ai.spawner.base import SpawnerError
from temper_ai.spawner.reaper import Reaper


@pytest.fixture(autouse=True)
def _shared_database(request, tmp_path):
    """Postgres in the database tier; otherwise a SQLite file, which threads can share."""
    from tests.conftest import TEST_DATABASE_URL

    if request.node.stash.get(TEST_DATABASE_URL, "").startswith("sqlite"):
        reset_database()
        init_database(f"sqlite:///{tmp_path / 'runs.db'}")


DOCKER, SUBPROC = "docker", "subprocess"
H = "temper-run-gen"               # a Docker run's box: the same name for every dispatch
C1, C2 = "ctr-gen-1", "ctr-gen-2"  # the container each Docker dispatch was stamped with
P1, P2 = "48101", "48202"          # a subprocess dispatch's pid
IDENTITIES = (H, C1, C2, P1, P2)
ENDED = ("completed", "failed", "cancelled", "orphaned")
INTERRUPTED = "interrupted"
CASE_KIND = "the case's kind"
_TIMES = itertools.count(1)
BASE = datetime(2026, 1, 1, tzinfo=UTC)


# ── Steps: how a run moves on, as its box, a resume or a dispatch writes it ─────────────


@dataclass(frozen=True)
class Put:
    """The run's row as a writer leaves it. ``kind`` None: no spawner (a lane re-queue)."""

    status: str
    attempts: int
    handle: str | None = None
    container_id: str | None = None
    cancel: bool = False
    kind: str | None = CASE_KIND


@dataclass(frozen=True)
class Started:
    """A box starts an attempt: its ``workflow.started`` event."""

    attempt: str


@dataclass(frozen=True)
class Moved:
    """An attempt's event moves on: it ends, or is claimed to carry on."""

    attempt: str
    status: str


@dataclass(frozen=True)
class Box:
    """A box comes up, or goes."""

    handle: str
    alive: bool


Step = Put | Started | Moved | Box


@dataclass(frozen=True)
class Expect:
    """What the reaper did: rows its UPDATEs changed (all reapers of the case), each end's
    answer in order, the event settles, the row it left, its signals, and whether the fence
    warned."""

    changed: int
    returns: tuple[bool, ...]
    settles: tuple[str, ...]
    row: tuple
    signals: tuple[tuple[str, bool], ...] = ()
    warned: bool = False


@dataclass(frozen=True)
class Case:
    """A row as the reaper's snapshot judges it, and how the run moves on before its write.

    ``hook``: where the run moves on (``cycle``): at the measured reaper's spawner call
    (``is_alive``, ``is_gone``, ``kill``), just before its first statement on the run rows
    (``write``), or just before its first UPDATE of them (``update``).
    """

    id: str
    kind: str
    judged: Put
    expect: Expect
    alive: bool = False             # the judged box, when the tick starts
    hook: str | None = None
    cycle: tuple[Step, ...] = ()
    early_reaper: bool = False      # another real reaper ticks after the snapshot, before the write
    early_steps: tuple[Step, ...] = ()  # ... or these moves happen then
    parked: bool = False            # the judged attempt waits parked (a Pi run let go at a gate)
    lane: str | None = None
    termed: bool = False            # SIGTERM went an earlier tick, and its grace is over
    kill_fails: bool = False        # the measured reaper's signal fails
    next_tick: bool = False         # one more tick of the measured reaper
    direct: bool = False            # the orphan end on the judged snapshot, no spawner call


def ended(status: str, attempts: int, handle: str | None, container_id: str | None = None,
          error: str | None = None) -> tuple:
    return (status, attempts, handle, container_id, True, error)


def live(status: str, attempts: int, handle: str | None = None,
         container_id: str | None = None) -> tuple:
    return (status, attempts, handle, container_id, False, None)


RUN_DOCKER = Put("running", 1, H, C1)
QUEUED_DOCKER = Put("queued", 1, H, C1)
RUN_PID = Put("running", 1, P1)
QUEUED_PID = Put("queued", 1, P1)
STOPPING_DOCKER = Put("running", 1, H, C1, cancel=True)
REQUEUED = Put("queued", 1)                   # a resume: back in the queue, no box
D2_DOCKER = Put("queued", 1, H, C2)           # a new Docker dispatch: same name, new container
D2_PID = Put("queued", 1, P2)
B_DOCKER = (Put("running", 2, H, C2), Started("b1"), Box(H, True))  # the new box starts the run
B_PID = (Put("running", 2, P2), Started("b1"), Box(P2, True))
CANCELLED_AT_GATE = (Moved("a1", "cancelled"), Put("cancelled", 1, P1))
B_DOCKER_ROW = live("running", 2, H, C2)
B_PID_ROW = live("running", 2, P2)
STALE = Expect(0, (False,), (), B_DOCKER_ROW)
STALE_PID = Expect(0, (False,), (), B_PID_ROW)

CASES = [
    # Running ends (the orphan, the forced cancel, the let-go of a parked Pi run).
    Case("ABA1-OWN", DOCKER, RUN_DOCKER, STALE, hook="is_alive",
         cycle=(Put("failed", 1, H, C1), Moved("a1", "failed"), REQUEUED, D2_DOCKER, *B_DOCKER)),
    Case("G-ABA1-OWN", DOCKER, RUN_DOCKER,
         Expect(1, (True,), (INTERRUPTED,), ended("orphaned", 1, H, C1, "orphaned"))),
    Case("G-DEAD-ABA1-OWN", DOCKER, Put("running", 2, H, C2),
         Expect(1, (True,), (INTERRUPTED,), ended("orphaned", 2, H, C2, "orphaned"))),
    Case("ABA1-C829", SUBPROC, RUN_PID, STALE_PID, hook="is_alive", parked=True, lane=PI_LANE,
         cycle=(*CANCELLED_AT_GATE, REQUEUED, D2_PID, *B_PID)),
    Case("ABA1-C829-LETGO", SUBPROC, RUN_PID, STALE_PID, hook="is_gone", parked=True,
         lane=PI_LANE, cycle=(*CANCELLED_AT_GATE, REQUEUED, D2_PID, *B_PID)),
    Case("G-ABA1-LETGO", SUBPROC, RUN_PID, Expect(1, (True,), (), live("waiting", 1, P1)),
         parked=True, lane=PI_LANE),
    Case("ABA1-C847F-A", DOCKER, STOPPING_DOCKER,
         Expect(1, (True, False), ("cancelled",), B_DOCKER_ROW, signals=((H, True),)),
         alive=True, termed=True, early_reaper=True, hook="is_alive",
         cycle=(REQUEUED, D2_DOCKER, *B_DOCKER)),
    # The stale SIGKILL still reaches the new box by name: the signal side's open part.
    Case("ABA1-C847F-B", DOCKER, STOPPING_DOCKER,
         Expect(1, (False, True), (INTERRUPTED,), ended("orphaned", 2, H, C2, "orphaned"),
                signals=((H, True),)),
         alive=True, termed=True, hook="is_alive", next_tick=True,
         cycle=(Put("cancelled", 1, H, C1, cancel=True), Moved("a1", "cancelled"), REQUEUED,
                D2_DOCKER, *B_DOCKER)),
    Case("G-ABA1-C847F", DOCKER, STOPPING_DOCKER,
         Expect(1, (True,), ("cancelled",), ended("cancelled", 1, H, C1),
                signals=((H, True),)),
         alive=True, termed=True),
    Case("ABA1-RPR-WAIT", SUBPROC, RUN_PID, STALE_PID, parked=True, lane=PI_LANE,
         early_steps=(Put("waiting", 1, P1), Moved("a1", CARRIED_ON), REQUEUED),
         hook="is_alive", cycle=(D2_PID, *B_PID)),
    Case("ABA1-RPR-ORPH", DOCKER, RUN_DOCKER,
         Expect(1, (True, False), (INTERRUPTED,), B_DOCKER_ROW),
         early_reaper=True, hook="is_alive", cycle=(REQUEUED, D2_DOCKER, *B_DOCKER)),
    Case("ABA1-NOH", DOCKER, Put("running", 1), STALE, hook="write",
         cycle=(Put("failed", 1), Moved("a1", "failed"), REQUEUED, D2_DOCKER, *B_DOCKER)),
    Case("G-ABA1-NOH", DOCKER, Put("running", 1),
         Expect(1, (True,), (INTERRUPTED,), ended("orphaned", 1, None, None, "orphaned"))),
    Case("ABA1-SIG", DOCKER, STOPPING_DOCKER,
         Expect(0, (False,), (), B_DOCKER_ROW, signals=((H, False),)),
         alive=True, hook="kill", kill_fails=True,
         cycle=(Put("cancelled", 1, H, C1, cancel=True), Moved("a1", "cancelled"), REQUEUED,
                D2_DOCKER, *B_DOCKER)),
    # Queued ends: a box gone before it started the run. Never settled: nothing started.
    Case("ABAQ-DOCKER", DOCKER, QUEUED_DOCKER, Expect(0, (False,), (), live("queued", 1, H, C2)),
         hook="is_alive", cycle=(Put("failed", 1, H, C1), REQUEUED, D2_DOCKER)),
    Case("G-ABAQ-DOCKER", DOCKER, QUEUED_DOCKER,
         Expect(1, (True,), (), ended("failed", 1, H, C1, "spawn"))),
    Case("G-DEAD-ABAQ-DOCKER", DOCKER, Put("queued", 1, H, C2),
         Expect(1, (True,), (), ended("failed", 1, H, C2, "spawn"))),
    Case("ABAQ-DOCKER-CANCEL", DOCKER, Put("queued", 1, H, C1, cancel=True),
         Expect(0, (False,), (), live("queued", 1, H, C2)), hook="is_alive",
         cycle=(Put("failed", 1, H, C1, cancel=True), REQUEUED, D2_DOCKER)),
    Case("ABAQ-SUBPROC", SUBPROC, QUEUED_PID, Expect(0, (False,), (), live("queued", 1, P2)),
         hook="is_alive", cycle=(Put("failed", 1, P1), REQUEUED, D2_PID)),
    Case("G-ABAQ-SUBPROC", SUBPROC, QUEUED_PID,
         Expect(1, (True,), (), ended("failed", 1, P1, None, "spawn"))),
    Case("G-DEAD-ABAQ-SUBPROC", SUBPROC, Put("queued", 1, P2),
         Expect(1, (True,), (), ended("failed", 1, P2, None, "spawn"))),
    Case("ABAQ-PILANE", SUBPROC, QUEUED_PID, Expect(0, (False,), (), live("queued", 1, P2)),
         lane=PI_LANE, hook="is_alive", cycle=(Put("queued", 1, kind=None), D2_PID)),
    Case("ABAQ-NOID-ADV", DOCKER, Put("queued", 1, H),
         Expect(0, (False,), (), live("queued", 1, H), warned=True),
         hook="is_alive", cycle=(REQUEUED, Put("queued", 1, H))),
    # Two reapers on one gone run: the second finds it ended, and settles nothing.
    Case("I5-TWO-REAPERS", DOCKER, RUN_DOCKER,
         Expect(1, (True, False), (INTERRUPTED,), ended("orphaned", 1, H, C1, "orphaned")),
         early_reaper=True),
    # A box that started its run during a queued judgement's grace: left to the next tick.
    Case("G-DEAD-HONOR-CANCEL-QUEUED", DOCKER, Put("queued", 1, H, C1, cancel=True),
         Expect(1, (False, True), (INTERRUPTED,), ended("orphaned", 2, H, C1, "orphaned"),
                signals=((H, True),)),
         alive=True, termed=True, hook="kill", next_tick=True,
         cycle=(Put("running", 2, H, C1, cancel=True), Started("d1"))),
    Case("CLEAN-ALIVE", DOCKER, RUN_DOCKER, Expect(0, (), (), live("running", 1, H, C1)),
         alive=True),
    Case("CLEAN-QUEUED-ALIVE", DOCKER, QUEUED_DOCKER,
         Expect(0, (), (), live("queued", 1, H, C1)), alive=True),
    Case("NOCHANGE-ENDED-NO-RESUME", DOCKER, RUN_DOCKER,
         Expect(0, (False,), (), ended("completed", 1, H, C1)), hook="is_alive",
         cycle=(Put("completed", 1, H, C1), Moved("a1", "completed"))),
    # The run moves on between the end's own read of the row and its write.
    Case("T13-R2-SAME", DOCKER, RUN_DOCKER,
         Expect(1, (True,), (INTERRUPTED,), ended("orphaned", 1, H, C1, "orphaned")),
         direct=True),
    Case("T13-R2-STATUS", DOCKER, RUN_DOCKER, Expect(0, (False,), (), live("queued", 1)),
         direct=True, hook="update", cycle=(REQUEUED,)),
    Case("T13-R2-ATTEMPTS", DOCKER, RUN_DOCKER, STALE, direct=True, hook="update",
         cycle=(REQUEUED, D2_DOCKER, *B_DOCKER)),
]
CASE = {case.id: case for case in CASES}
assert len(CASE) == len(CASES)

SPAWNER_CALLS = ("is_alive", "is_gone", "kill")
STATEMENTS = ("write", "update")


# ── The world a case runs in ────────────────────────────────────────────────────────────


def _put(execution_id: str, put: Put, *, kind: str | None, lane: str | None) -> None:
    """Write the run's row as ``put`` says, in a session (and commit) of its own."""
    metadata = mark_lane({"container_id": put.container_id} if put.container_id else {}, lane)
    with get_session() as session:
        row = session.get(WorkflowRun, execution_id) or WorkflowRun(
            execution_id=execution_id, workflow_name="wf", workspace_path="/ws")
        row.status, row.attempts = put.status, put.attempts
        row.spawner_kind = kind if put.kind == CASE_KIND else put.kind
        row.spawner_handle = put.handle
        row.spawner_metadata = metadata
        row.cancel_requested = put.cancel
        row.completed_at = datetime.now(UTC) if put.status in ENDED else None
        row.error = None
        session.add(row)


def _event(execution_id: str, attempt: str, status: str, data: dict | None = None) -> None:
    """An attempt's start event, newer than every event before it."""
    with get_session() as session:
        session.add(Event(
            id=f"{execution_id}:{attempt}", type="workflow.started", execution_id=execution_id,
            status=status, data=data or {}, timestamp=BASE + timedelta(seconds=next(_TIMES))))


def _event_status(execution_id: str, attempt: str) -> str | None:
    with get_session() as session:
        event = session.get(Event, f"{execution_id}:{attempt}")
        return None if event is None else event.status


def _row(execution_id: str) -> tuple:
    with get_session() as session:
        row = session.get(WorkflowRun, execution_id)
        return (row.status, row.attempts, row.spawner_handle,
                (row.spawner_metadata or {}).get("container_id"),
                row.completed_at is not None, (row.error or {}).get("kind"))


def _forget(execution_id: str) -> None:
    with get_session() as session:
        session.exec(delete(WorkflowRun).where(  # type: ignore[call-overload]
            col(WorkflowRun.execution_id) == execution_id))
        session.exec(delete(Event).where(  # type: ignore[call-overload]
            col(Event.execution_id) == execution_id))


class _World:
    """One case's run, its boxes, and what the reapers did to it."""

    def __init__(self, case: Case | None, execution_id: str) -> None:
        self.case, self.eid = case, execution_id
        self.alive: dict[str, bool] = {}
        self.signals: list[tuple[str, bool]] = []
        self.returns: list[bool] = []
        self.settles: list[str] = []
        self.rowcounts: list[int] = []   # rows each reaper UPDATE of the run rows changed
        self.moving = False              # the test's own writes, not a reaper's
        self.armed: str | None = None    # a statement hook waiting for the reaper's write

    def move(self, steps: tuple[Step, ...]) -> None:
        assert self.case is not None
        self.moving = True
        try:
            for step in steps:
                if isinstance(step, Put):
                    _put(self.eid, step, kind=self.case.kind, lane=self.case.lane)
                elif isinstance(step, Started):
                    _event(self.eid, step.attempt, "running")
                elif isinstance(step, Moved):
                    with get_session() as session:
                        event = session.get(Event, f"{self.eid}:{step.attempt}")
                        event.status = step.status
                        session.add(event)
                else:
                    self.alive[step.handle] = step.alive
        finally:
            self.moving = False

    def settle(self, execution_id: str, status: str, message: str) -> int:
        self.settles.append(status)
        return settle_run_event(execution_id, status, message)


def _insert(world: _World) -> None:
    """The row as the reaper's snapshot will judge it, with its attempt's start event."""
    case = world.case
    assert case is not None
    world.move((case.judged,))
    if case.judged.status == "running":
        if case.parked:
            _event(world.eid, "a1", WAITING, {"parked": {"path": "the gate"}})
        else:
            _event(world.eid, "a1", "running")
    if case.judged.handle:
        world.alive[case.judged.handle] = case.alive


@contextmanager
def _watching(world: _World) -> Iterator[None]:
    """Count the rows the reapers' UPDATEs change; fire the case's statement hook."""
    engine = get_database().engine

    def before(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if world.moving or world.armed is None or world.case is None:
            return
        sql = statement.lstrip().upper()
        if world.armed == "update" and not sql.startswith("UPDATE WORKFLOW_RUNS"):
            return
        if world.armed == "write" and "WORKFLOW_RUNS" not in sql:
            return
        world.armed = None
        world.move(world.case.cycle)

    def after(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if not world.moving and statement.lstrip().upper().startswith("UPDATE WORKFLOW_RUNS"):
            world.rowcounts.append(cursor.rowcount)

    sa_event.listen(engine, "before_cursor_execute", before)
    sa_event.listen(engine, "after_cursor_execute", after)
    try:
        yield
    finally:
        sa_event.remove(engine, "before_cursor_execute", before)
        sa_event.remove(engine, "after_cursor_execute", after)


class _Spawner:
    """Boxes that are ``alive`` (handle -> bool). ``hook`` runs once, at the ``at`` call,
    after the call's answer is fixed: the box changed while the reaper waited on it."""

    def __init__(self, alive: dict[str, bool], signals: list, *, hook: Callable | None = None,
                 at: str | None = None, kill_fails: bool = False) -> None:
        self.alive, self.signals = alive, signals
        self._hook, self._at, self._kill_fails = hook, at, kill_fails

    def _call(self, name: str) -> None:
        if self._hook is not None and self._at == name:
            hook, self._hook = self._hook, None
            hook()

    def is_alive(self, handle) -> bool:
        answer = self.alive.get(handle.handle, False)
        self._call("is_alive")
        return answer

    def is_gone(self, handle) -> bool:
        answer = not self.alive.get(handle.handle, False)
        self._call("is_gone")
        return answer

    def kill(self, handle, *, force: bool = False) -> None:
        self.signals.append((handle.handle, force))
        self._call("kill")
        if self._kill_fails:
            raise SpawnerError("the box would not take the signal")
        if force:
            self.alive[handle.handle] = False


def _reaper(module: ModuleType, world: _World, *, hooked: bool,
            spawner: Any = None) -> Reaper:
    """``module``'s Reaper on the world's boxes, its end answers recorded."""
    case = world.case
    assert case is not None
    if spawner is None:
        def move_on() -> None:
            world.move(case.cycle)

        spawner = _Spawner(world.alive, world.signals,
                           hook=move_on if hooked and case.hook in SPAWNER_CALLS else None,
                           at=case.hook, kill_fails=hooked and case.kill_fails)
    reaper = module.Reaper(spawner, interval_seconds=0, kill_grace_seconds=0, lane=case.lane)
    mark_status = reaper._mark_status

    def recorded(*args: Any, **kwargs: Any) -> bool:
        answer = mark_status(*args, **kwargs)
        world.returns.append(answer)
        return answer

    reaper._mark_status = recorded
    if case.termed:
        reaper._termed_at[world.eid] = datetime.now(UTC) - timedelta(minutes=1)
    return reaper


def _run_case(case: Case, module: ModuleType, execution_id: str, caplog,
              monkeypatch) -> tuple[Expect, list[str], _World, Reaper]:
    """The case through ``module``'s Reaper: judge from its own snapshot, let the run move
    on where the case says, end; and what it did."""
    world = _World(case, execution_id)
    _insert(world)
    monkeypatch.setattr(module, "settle_run_event", world.settle)
    first = len(caplog.records)
    with _watching(world):
        reaper = _reaper(module, world, hooked=True)
        if case.direct or case.early_reaper or case.early_steps or case.hook in STATEMENTS:
            [row] = [r for r in reaper._load_live_rows() if r["execution_id"] == execution_id]
            if case.early_reaper:
                _reaper(module, world, hooked=False).tick()
            world.move(case.early_steps)
            world.armed = case.hook if case.hook in STATEMENTS else None
            if case.direct:
                reaper._mark_orphaned(
                    execution_id, judged=module.RowGeneration.from_snapshot(row),
                    reason="worker process gone")
            else:
                reaper._process_row(row)
        else:
            reaper.tick()
        if case.next_tick:
            reaper.tick()
    warnings = [r.getMessage() for r in caplog.records[first:]
                if r.levelno == logging.WARNING and r.name.startswith(row_generation.__name__)]
    outcome = Expect(sum(world.rowcounts), tuple(world.returns), tuple(world.settles),
                     _row(execution_id), tuple(world.signals), bool(warnings))
    return outcome, warnings, world, reaper


# ── The reaper's whole job, as it should be ─────────────────────────────────────────────


def test_one_tick_ends_each_gone_run_once_and_leaves_the_others():
    """A tick of each lane: the gone run orphaned and its event interrupted, the unstarted
    runs failed or cancelled, the stopped run killed and cancelled, the parked Pi run
    waiting with no box, the live run untouched; each row changed by one UPDATE."""
    world = _World(None, "")
    world.alive.update({"temper-run-alive": True, "temper-run-stopped": True})
    _put("gone", Put("running", 1, "temper-run-gone", "ctr-gone"), kind=DOCKER, lane=None)
    _event("gone", "a1", "running")
    _put("unstarted", Put("queued", 1, "temper-run-unstarted", "ctr-unstarted"),
         kind=DOCKER, lane=None)
    _put("unstarted-stop", Put("queued", 1, "48303", cancel=True), kind=SUBPROC, lane=None)
    _put("stopped", Put("running", 1, "temper-run-stopped", "ctr-stopped", cancel=True),
         kind=DOCKER, lane=None)
    _event("stopped", "a1", "running")
    _put("alive", Put("running", 1, "temper-run-alive", "ctr-alive"), kind=DOCKER, lane=None)
    _event("alive", "a1", "running")
    _put("parked", Put("running", 1, "48404"), kind=SUBPROC, lane=PI_LANE)
    _event("parked", "a1", WAITING, {"parked": {"path": "the gate"}})
    main = Reaper(_Spawner(world.alive, world.signals), interval_seconds=0, kill_grace_seconds=0)
    main._termed_at["stopped"] = datetime.now(UTC) - timedelta(minutes=1)
    pi = Reaper(_Spawner(world.alive, world.signals), interval_seconds=0, kill_grace_seconds=0,
                lane=PI_LANE)

    with _watching(world):
        main.tick()
        pi.tick()

    assert world.rowcounts == [1, 1, 1, 1, 1]
    assert _row("gone") == ended("orphaned", 1, "temper-run-gone", "ctr-gone", "orphaned")
    assert _row("unstarted") == ended("failed", 1, "temper-run-unstarted", "ctr-unstarted",
                                      "spawn")
    assert _row("unstarted-stop") == ended("cancelled", 1, "48303")
    assert _row("stopped") == ended("cancelled", 1, "temper-run-stopped", "ctr-stopped")
    assert _row("alive") == live("running", 1, "temper-run-alive", "ctr-alive")
    assert _row("parked") == live("waiting", 1, "48404")
    assert world.signals == [("temper-run-stopped", True)]
    assert [_event_status(run, "a1") for run in ("gone", "stopped", "alive", "parked")] == [
        INTERRUPTED, "cancelled", "running", WAITING]


# ── The known answers ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_the_reaper_ends_only_the_generation_its_tick_judged(case, caplog, monkeypatch):
    caplog.set_level(logging.WARNING)
    run = f"run:{case.id}"
    outcome, warnings, _, _ = _run_case(case, reaper_module, run, caplog, monkeypatch)
    assert outcome == case.expect
    # A refused end says which run, never the identities it compared.
    assert all(run in w and not any(i in w for i in IDENTITIES) for w in warnings)


# ── The bites ───────────────────────────────────────────────────────────────────────────

ABA1 = {"ABA1-OWN", "ABA1-C829", "ABA1-C829-LETGO", "ABA1-C847F-A", "ABA1-C847F-B",
        "ABA1-RPR-WAIT", "ABA1-RPR-ORPH", "ABA1-NOH", "ABA1-SIG"}
STALE_QUEUED = {"ABAQ-DOCKER", "ABAQ-DOCKER-CANCEL", "ABAQ-SUBPROC", "ABAQ-PILANE"}
#: Every genuine end and every dead twin's: the fence must keep ending them.
LIVE = {"G-ABA1-OWN", "G-DEAD-ABA1-OWN", "G-ABA1-LETGO", "G-ABA1-C847F", "G-ABA1-NOH",
        "G-ABAQ-DOCKER", "G-DEAD-ABAQ-DOCKER", "G-ABAQ-SUBPROC", "G-DEAD-ABAQ-SUBPROC",
        "T13-R2-SAME"}
#: Every case in which some reaper ends the row.
ENDS = {case.id for case in CASES if case.expect.changed}

_ORPHAN_SETTLE = ('            error={"message": f"reaped: {reason}", "kind": "orphaned"},\n'
                  '        ):')
_FENCED_WRITE = """        if judged.status != from_status:
            return False
        with get_session() as session:
            return end_row_if_same_generation(
                session, execution_id, judged, status=status, keep_open=keep_open, error=error)"""
_ATTEMPTS_TERM = "        col(WorkflowRun.attempts) == judged.attempts,"

#: name: (module, [(its source, weakened)], exactly the cases it gets wrong, the cases the
#: design declared it must get wrong). Each runs every case through the real Reaper.
BITES: dict[str, tuple[ModuleType, list[tuple[str, str]], set[str], set[str]]] = {
    # The end as it was: a fresh read of the row, its status checked in Python, then a
    # write by primary key.
    "B9": (reaper_module, [(_FENCED_WRITE, """        with get_session() as session:
            row = session.exec(
                select(WorkflowRun).where(
                    WorkflowRun.execution_id == execution_id,
                ),
            ).first()
            if row is None or row.status != from_status:
                return False
            row.status = status
            if not keep_open:
                row.completed_at = datetime.now(UTC)
            if error is not None:
                row.error = error
            session.add(row)
            return True""")],
           ABA1 | STALE_QUEUED | {"ABAQ-NOID-ADV", "G-DEAD-HONOR-CANCEL-QUEUED",
                                  "T13-R2-STATUS", "T13-R2-ATTEMPTS"},
           {"T13-R2-STATUS", "T13-R2-ATTEMPTS"}),
    # Status alone: a newer start of the same run is still "running".
    "B9b": (row_generation, [(_ATTEMPTS_TERM, "")], ABA1 | {"T13-R2-ATTEMPTS"}, ABA1),
    # The box's name for the generation: every Docker dispatch of a run has the same one.
    "B-ABA-2": (row_generation,
                [(_ATTEMPTS_TERM, "        col(WorkflowRun.spawner_handle) == judged.handle,")],
                {"ABA1-OWN", "ABA1-C847F-A", "ABA1-C847F-B", "ABA1-RPR-ORPH", "ABA1-SIG",
                 "T13-R2-ATTEMPTS"},
                {"ABA1-OWN", "ABA1-C847F-A", "ABA1-C847F-B", "ABA1-RPR-ORPH", "ABA1-SIG"}),
    # The generation read again at the write, not the one the tick judged.
    "B-ABA-3": (reaper_module, [(
        "        with get_session() as session:\n            return end_row_if_same_generation(",
        "        with get_session() as session:\n"
        "            judged = __import__('dataclasses').replace(\n"
        "                judged, attempts=session.get(WorkflowRun, execution_id).attempts)\n"
        "            return end_row_if_same_generation(")], ABA1, ABA1),
    # A queued Docker row's dispatch by its name alone.
    "B-CID": (row_generation, [("            _ROW_CONTAINER_ID == judged.container_id,\n", "")],
              {"ABAQ-DOCKER", "ABAQ-DOCKER-CANCEL"}, {"ABAQ-DOCKER", "ABAQ-DOCKER-CANCEL"}),
    # A missing container compared, as NULL, with a row that has none either.
    "B-CID-NULLEQ": (row_generation, [('("container_id", judged.container_id))',
                                       '("container_id", "same"))')],
                     {"ABAQ-NOID-ADV"}, {"ABAQ-NOID-ADV"}),
    # A queued subprocess row's dispatch not named at all.
    "B-SUBPROC-HANDLE": (row_generation,
                         [("        return [col(WorkflowRun.spawner_handle) == judged.handle]",
                           "        return []")],
                         {"ABAQ-SUBPROC", "ABAQ-PILANE"}, {"ABAQ-SUBPROC", "ABAQ-PILANE"}),
    # A container asked of every kind: a subprocess row has none, so it is never ended.
    "B-CID-ALLKINDS": (row_generation,
                       [("        if not judged.handle:",
                         "        if not judged.handle or not judged.container_id:")],
                       {"G-ABAQ-SUBPROC", "G-DEAD-ABAQ-SUBPROC", "ABAQ-SUBPROC", "ABAQ-PILANE"},
                       {"G-ABAQ-SUBPROC", "G-DEAD-ABAQ-SUBPROC"}),
    # The event settled whatever the write did.
    "B-SETTLE": (reaper_module, [
        (_ORPHAN_SETTLE, _ORPHAN_SETTLE[:-1] + " or True:"),
        ('            if self._mark_status(execution_id, "cancelled", judged=judged):',
         '            if self._mark_status(execution_id, "cancelled", judged=judged) or True:')],
        (ABA1 - {"ABA1-C829-LETGO"}) | {"I5-TWO-REAPERS", "NOCHANGE-ENDED-NO-RESUME",
                                       "T13-R2-STATUS", "T13-R2-ATTEMPTS",
                                       "G-DEAD-HONOR-CANCEL-QUEUED"},
        {"ABA1-OWN", "ABA1-C829", "ABA1-C847F-A", "ABA1-C847F-B", "I5-TWO-REAPERS"}),
    # True for an UPDATE that changed nothing.
    "B-ROWCOUNT": (row_generation, [("    return result.rowcount == 1", "    return True")],
                   ABA1 | STALE_QUEUED | {"I5-TWO-REAPERS", "NOCHANGE-ENDED-NO-RESUME",
                                          "T13-R2-STATUS", "T13-R2-ATTEMPTS"},
                   {"ABA1-OWN", "ABA1-C829"}),
    # The attempts alone: an end rewrites a row its own generation already ended.
    "B-STATUS-TERM": (row_generation, [("        col(WorkflowRun.status) == judged.status,\n", "")],
                      {"I5-TWO-REAPERS", "NOCHANGE-ENDED-NO-RESUME", "T13-R2-STATUS"},
                      {"I5-TWO-REAPERS", "NOCHANGE-ENDED-NO-RESUME"}),
    # A fence nothing passes: safe against every race, and it never ends anything.
    "B-NEVER-END": (row_generation, [(_ATTEMPTS_TERM, "        col(WorkflowRun.attempts) == -1,")],
                    ENDS,
                    {"G-ABA1-OWN", "G-DEAD-ABA1-OWN", "G-ABA1-LETGO", "G-ABA1-C847F",
                     "G-ABA1-NOH", "G-ABAQ-DOCKER", "G-DEAD-ABAQ-DOCKER", "G-ABAQ-SUBPROC",
                     "G-DEAD-ABAQ-SUBPROC", "G-DEAD-HONOR-CANCEL-QUEUED"}),
}
#: The bites whose declared failure is a genuine end or a dead twin's not landing.
TWIN_BITES = {"B-CID-ALLKINDS", "B-NEVER-END"}


def _mutant(module: ModuleType, mutations: list[tuple[str, str]], monkeypatch) -> ModuleType:
    """``module`` built again from its own source with ``mutations`` made: the real body
    with one guard weakened, never a copy of its predicate."""
    source = inspect.getsource(module)
    for find, replace in mutations:
        assert source.count(find) == 1, f"{module.__name__} doesn't hold this once: {find!r}"
        source = source.replace(find, replace)
    mutant = ModuleType(f"{module.__name__}_bitten")
    mutant.__file__ = module.__file__
    monkeypatch.setitem(sys.modules, mutant.__name__, mutant)
    exec(compile(source, module.__file__, "exec"), mutant.__dict__)  # noqa: S102
    return mutant


@pytest.mark.timeout(240)
@pytest.mark.parametrize("bite", list(BITES))
def test_each_guard_has_a_bite(bite, caplog, monkeypatch):
    caplog.set_level(logging.WARNING)
    module, mutations, exact, declared = BITES[bite]
    bitten = _mutant(module, mutations, monkeypatch)
    if module is reaper_module:
        reaper = bitten
    else:
        reaper = reaper_module
        monkeypatch.setattr(reaper_module, "RowGeneration", bitten.RowGeneration)
        monkeypatch.setattr(reaper_module, "end_row_if_same_generation",
                            bitten.end_row_if_same_generation)
    wrong = set()
    for case in CASES:
        run = f"{bite}:{case.id}"
        outcome, _, _, _ = _run_case(case, reaper, run, caplog, monkeypatch)
        if outcome != case.expect:
            wrong.add(case.id)
        _forget(run)
    assert wrong == exact
    assert declared <= wrong
    if bite not in TWIN_BITES:
        assert not wrong & LIVE  # every genuine end, and every dead twin's, still lands


# ── Liveness: the next tick ends what a refused end left ─────────────────────────────────

#: A stale case, and the row the next tick leaves once the newer generation's box is gone.
NEXT_TICK = {
    "ABA1-OWN": ended("orphaned", 2, H, C2, "orphaned"),
    "ABA1-C829": ended("orphaned", 2, P2, None, "orphaned"),
    "ABA1-C829-LETGO": ended("orphaned", 2, P2, None, "orphaned"),
    "ABA1-C847F-A": ended("orphaned", 2, H, C2, "orphaned"),
    "ABA1-RPR-WAIT": ended("orphaned", 2, P2, None, "orphaned"),
    "ABA1-RPR-ORPH": ended("orphaned", 2, H, C2, "orphaned"),
    "ABA1-NOH": ended("orphaned", 2, H, C2, "orphaned"),
    "ABA1-SIG": ended("orphaned", 2, H, C2, "orphaned"),
    "T13-R2-ATTEMPTS": ended("orphaned", 2, H, C2, "orphaned"),
    "ABAQ-DOCKER": ended("failed", 1, H, C2, "spawn"),
    "ABAQ-DOCKER-CANCEL": ended("failed", 1, H, C2, "spawn"),
    "ABAQ-SUBPROC": ended("failed", 1, P2, None, "spawn"),
    "ABAQ-PILANE": ended("failed", 1, P2, None, "spawn"),
}


@pytest.mark.parametrize("stale", list(NEXT_TICK))
def test_the_next_tick_ends_the_generation_a_refused_end_left(stale, caplog, monkeypatch):
    case = CASE[stale]
    run = f"run:{stale}"
    outcome, _, world, reaper = _run_case(case, reaper_module, run, caplog, monkeypatch)
    assert outcome == case.expect
    for handle in world.alive:
        world.alive[handle] = False  # the newer generation's box goes too
    changed, settled = len(world.rowcounts), len(world.settles)
    with _watching(world):
        reaper.tick()
    assert world.rowcounts[changed:] == [1]
    assert _row(run) == NEXT_TICK[stale]
    # An orphaned run's event is interrupted; a run that never started has none to settle.
    assert world.settles[settled:] == ([INTERRUPTED] if NEXT_TICK[stale][0] == "orphaned"
                                       else [])


def test_a_docker_dispatch_without_its_container_is_never_ended_and_warns_each_tick(
        caplog, monkeypatch):
    caplog.set_level(logging.WARNING)
    run = "run-no-container"
    case = Case("ABAQ-NOID-DEAD", DOCKER, Put("queued", 1, H), STALE)
    world = _World(case, run)
    _insert(world)
    reaper = _reaper(reaper_module, world, hooked=False)
    with _watching(world):
        for _tick in range(3):
            reaper.tick()
    assert world.rowcounts == []  # no UPDATE was even sent
    assert world.returns == [False, False, False]
    assert _row(run) == live("queued", 1, H)
    warned = [r.getMessage() for r in caplog.records
              if r.name == row_generation.__name__ and r.levelno == logging.WARNING]
    assert len(warned) == 3
    assert all(run in w and "container_id" in w and H not in w for w in warned)


# ── Two reapers at once ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("round_", [1, 2])
def test_two_reapers_judging_one_gone_run_at_once_end_it_once(round_, monkeypatch):
    """Both snapshots are taken before either writes (they meet at the spawner call)."""
    run = f"run-two-reapers-{round_}"
    world = _World(CASE["G-ABA1-OWN"], run)
    _insert(world)
    monkeypatch.setattr(reaper_module, "settle_run_event", world.settle)
    both = threading.Barrier(2, timeout=20)

    class Meeting(_Spawner):
        def is_alive(self, handle) -> bool:
            both.wait()
            return False

    reapers = [_reaper(reaper_module, world, hooked=False,
                       spawner=Meeting(world.alive, world.signals)) for _ in range(2)]
    with _watching(world):
        threads = [threading.Thread(target=reaper.tick) for reaper in reapers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert sorted(world.rowcounts) == [0, 1]
    assert sorted(world.returns) == [False, True]
    assert world.settles == [INTERRUPTED]
    assert _row(run) == ended("orphaned", 1, H, C1, "orphaned")
