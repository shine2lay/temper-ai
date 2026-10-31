"""One database decision for a claim, a re-queue or a conditional end (S1 groundwork).

* ``runner.row_generation``: a run row's judged generation, and the end write fenced on it;
* ``recorder.deciding_events`` / ``decide_event_in``: an event's compare-and-set inside the
  caller's transaction (``decide_event`` is the two together);
* ``queue.queue_run_in``: the re-queue inside it, the run row read FOR UPDATE
  (``queue_run`` is it in a session of its own).

Nothing in the engine calls the new forms yet; the cancel, the claim and the reaper will.

The known-answer cases (G1) are rows as one read judged them and as they stand at the
write; each says whether the fence changes the row. The bites weaken one guard in the real
module's own source and show which cases it was keeping right, while every case that should
end its row still does.

On a SQLite file, or on Postgres in the database tier (tests/pgtier.py): never the default
in-memory SQLite, whose one connection threads can't share.
"""

from __future__ import annotations

import inspect
import logging
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, dataclass
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import text

from temper_ai.database import get_database, get_session, init_database, reset_database
from temper_ai.observability import recorder
from temper_ai.observability.event_types import EventType
from temper_ai.observability.models import Event
from temper_ai.observability.recorder import (
    decide_event,
    decide_event_in,
    deciding_events,
    get_event,
    record,
)
from temper_ai.runner import queue, row_generation
from temper_ai.runner.lanes import lane_of, mark_lane
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.parked import CANCELLED, CARRIED_ON, WAITING
from temper_ai.runner.queue import AlreadyQueued, queue_run, queue_run_in
from temper_ai.runner.row_generation import RowGeneration, end_row_if_same_generation


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

    def locked(self) -> bool:
        return self._lock.locked()


@pytest.fixture
def decision_lock(monkeypatch) -> _WatchedLock:
    watched = _WatchedLock()
    monkeypatch.setattr(recorder, "_SQLITE_DECIDE_LOCK", watched)
    return watched


# Who a dispatch is. Distinct strings, so a warning can be checked for not showing them.
H = "box-h"                   # the run's Docker box name: the same for every dispatch
C1, C2 = "ctr-c1", "ctr-c2"   # the containers of dispatches D1 and D2
P101, P202 = "pid-101", "pid-202"
JOB = "job-7"
IDENTITIES = (H, C1, C2, P101, P202, JOB)
DOCKER, SUBPROC = "docker", "subprocess"
#: What the worker keeps in a run's metadata: the fence never touches it.
KEPT = {"box_profile": {"generation": 2}}
ERROR = {"message": "ended by the test"}


@dataclass(frozen=True)
class Gen:
    status: str
    attempts: int
    handle: str | None = None
    container_id: str | None = None


@dataclass(frozen=True)
class Case:
    id: str
    kind: str | None      # the row's spawner kind
    judged: Gen           # the row as the judging read found it
    at_write: Gen | None  # the row when the end is written; None: still the judged one
    end: str              # the status the end writes
    changed: bool         # the known answer: the fence ends the row (True) or leaves it alone
    keep_open: bool = False
    refused: bool = False  # left alone without an UPDATE (the dispatch can't be named), warned


SAME = None
OPEN_WAITING = "waiting"  # the let-go: the row waits again, its run not over

G1 = [
    # A newer box of the same run started meanwhile (attempts 1 -> 2): the old end misses.
    Case("ABA1-OWN", DOCKER, Gen("running", 1, H, C1), Gen("running", 2, H, C2), "orphaned", False),
    Case("G-ABA1-OWN", DOCKER, Gen("running", 1, H, C1), SAME, "orphaned", True),
    Case("G-DEAD-ABA1-OWN", DOCKER, Gen("running", 2, H, C2), SAME, "orphaned", True),
    Case("ABA1-C829", SUBPROC, Gen("running", 1, P101), Gen("running", 2, P202), "orphaned", False),
    Case("ABA1-C829-LETGO", SUBPROC, Gen("running", 1, P101), Gen("running", 2, P202),
         OPEN_WAITING, False, keep_open=True),
    Case("G-ABA1-LETGO", SUBPROC, Gen("running", 1, P101), SAME, OPEN_WAITING, True,
         keep_open=True),
    Case("ABA1-C847F-A", DOCKER, Gen("running", 1, H, C1), Gen("running", 2, H, C2), "orphaned", False),
    Case("ABA1-C847F-B", DOCKER, Gen("running", 1, H, C1), Gen("running", 2, H, C2), "cancelled", False),
    Case("G-ABA1-C847F", DOCKER, Gen("running", 1, H, C1), SAME, "cancelled", True),
    Case("ABA1-RPR-WAIT", SUBPROC, Gen("running", 1, P101), Gen("running", 2, P202), "orphaned", False),
    Case("ABA1-RPR-ORPH", DOCKER, Gen("running", 1, H, C1), Gen("running", 2, H, C2), "orphaned", False),
    Case("ABA1-NOH", DOCKER, Gen("running", 1), Gen("running", 2, H, C2), "orphaned", False),
    Case("G-ABA1-NOH", DOCKER, Gen("running", 1), SAME, "orphaned", True),
    Case("ABA1-SIG", DOCKER, Gen("running", 1, H, C1), Gen("running", 2, H, C2), "orphaned", False),
    Case("ABA1-BOXCANCEL", SUBPROC, Gen("running", 1, P101), Gen("running", 2, P202), "cancelled", False),
    Case("G-BOX-OWN-CANCEL", SUBPROC, Gen("running", 1, P101), SAME, "cancelled", True),
    # The cancel's own end: waiting -> waiting and running -> running of a newer attempt.
    Case("ABA1C", SUBPROC, Gen("waiting", 1, P101), Gen("waiting", 2, P202), "cancelled", False),
    Case("G-ABA1C", SUBPROC, Gen("waiting", 1, P101), SAME, "cancelled", True),
    Case("ABA-RR", SUBPROC, Gen("running", 1, P101), Gen("running", 2, P202), "cancelled", False),
    Case("G-ABA-RR", SUBPROC, Gen("running", 1, P101), SAME, "cancelled", True),
    Case("ABA1R", SUBPROC, Gen("running", 1, P101), Gen("running", 2, P202), "cancelled", False),
    Case("G-ABA1R", SUBPROC, Gen("running", 1, P101), SAME, "cancelled", True),
    Case("G-DEAD-ABA1R", SUBPROC, Gen("running", 2, P202), SAME, OPEN_WAITING, True, keep_open=True),
    # A queued run re-dispatched with no box start between: attempts stay 1, the dispatch
    # identity tells them apart.
    Case("ABAQ-DOCKER", DOCKER, Gen("queued", 1, H, C1), Gen("queued", 1, H, C2), "failed", False),
    Case("G-ABAQ-DOCKER", DOCKER, Gen("queued", 1, H, C1), SAME, "failed", True),
    Case("G-DEAD-ABAQ-DOCKER", DOCKER, Gen("queued", 1, H, C2), SAME, "failed", True),
    Case("ABAQ-DOCKER-CANCEL", DOCKER, Gen("queued", 1, H, C1), Gen("queued", 1, H, C2), "cancelled", False),
    Case("ABAQ-SUBPROC", SUBPROC, Gen("queued", 1, P101), Gen("queued", 1, P202), "failed", False),
    Case("G-ABAQ-SUBPROC", SUBPROC, Gen("queued", 1, P101), SAME, "failed", True),
    Case("G-DEAD-ABAQ-SUBPROC", SUBPROC, Gen("queued", 1, P202), SAME, "failed", True),
    Case("ABAQ-PILANE", SUBPROC, Gen("queued", 1, P101), Gen("queued", 1, P202), "failed", False),
    # Residual, recorded: a later subprocess dispatch on the same pid compares equal.
    Case("ABAQ-PID", SUBPROC, Gen("queued", 1, P101), Gen("queued", 1, P101), "failed", True),
    # A Docker dispatch the judging read can't name never compares equal: no write, a warning.
    Case("ABAQ-NOID-ADV", DOCKER, Gen("queued", 1, H), SAME, "failed", False, refused=True),
    # Ended already, same attempts: a second reaper, or the box's own end. Never rewritten.
    Case("I5-TWO-REAPERS", DOCKER, Gen("running", 1, H, C1), Gen("orphaned", 1, H, C1), "orphaned", False),
    Case("NOCHANGE-ENDED-NO-RESUME", DOCKER, Gen("running", 1, H, C1), Gen("completed", 1, H, C1),
         "orphaned", False),
    # Judged queued, started meanwhile: the next tick judges the running row afresh.
    Case("G-DEAD-HONOR-CANCEL-QUEUED", DOCKER, Gen("queued", 1, H, C1), Gen("running", 2, H, C1),
         "cancelled", False),
    # Residual, recorded: two boxes started from one queued generation share attempts.
    Case("ABA-DOUBLE-START", SUBPROC, Gen("running", 2, P101), Gen("running", 2, P202), "completed", True),
    # The fence's own edges: NULL never equals, from either side; a kind with no identity.
    Case("Q-ROW-LOST-CID", DOCKER, Gen("queued", 1, H, C1), Gen("queued", 1, H), "failed", False),
    Case("Q-DOCKER-NO-HANDLE", DOCKER, Gen("queued", 1, None, C1), SAME, "failed", False, refused=True),
    Case("Q-SUBPROC-NO-HANDLE", SUBPROC, Gen("queued", 1), SAME, "failed", False, refused=True),
    Case("Q-UNKNOWN-KIND", "k8s_job", Gen("queued", 1, JOB), SAME, "failed", False, refused=True),
    Case("Q-UNSTAMPED", None, Gen("queued", 1), SAME, "failed", False, refused=True),
]
CASES = {case.id: case for case in G1}


def _metadata(gen: Gen) -> dict:
    return {**KEPT, **({"container_id": gen.container_id} if gen.container_id else {})}


def _put_row(execution_id: str, kind: str | None, gen: Gen) -> None:
    with get_session() as session:
        session.add(WorkflowRun(
            execution_id=execution_id, workflow_name="wf", workspace_path="",
            status=gen.status, attempts=gen.attempts, spawner_kind=kind,
            spawner_handle=gen.handle, spawner_metadata=_metadata(gen),
        ))


def _move_row(execution_id: str, gen: Gen) -> None:
    """The run moves on as another box or dispatch would write it."""
    with get_session() as session:
        row = session.get(WorkflowRun, execution_id)
        row.status, row.attempts, row.spawner_handle = gen.status, gen.attempts, gen.handle
        row.spawner_metadata = _metadata(gen)
        session.add(row)


ROW_FIELDS = ("status", "attempts", "spawner_kind", "spawner_handle", "spawner_metadata",
              "cancel_requested", "started_at", "completed_at", "error")


def _row(execution_id: str) -> dict | None:
    with get_session() as session:
        row = session.get(WorkflowRun, execution_id)
        return None if row is None else {name: getattr(row, name) for name in ROW_FIELDS}


def _snapshot(execution_id: str) -> dict:
    """One read of the row, keyed as the reaper's snapshot is."""
    row = _row(execution_id)
    return {
        "status": row["status"], "attempts": row["attempts"],
        "spawner_kind": row["spawner_kind"], "spawner_handle": row["spawner_handle"],
        "container_id": (row["spawner_metadata"] or {}).get("container_id"),
        "cancel_requested": row["cancel_requested"],
    }


@contextmanager
def _run_updates() -> Iterator[list[str]]:
    """The UPDATEs of workflow_runs sent to the database meanwhile."""
    seen: list[str] = []
    engine = get_database().engine

    def listen(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().upper().startswith("UPDATE WORKFLOW_RUNS"):
            seen.append(statement)

    sa_event.listen(engine, "before_cursor_execute", listen)
    try:
        yield seen
    finally:
        sa_event.remove(engine, "before_cursor_execute", listen)


def _run_case(case: Case, module: ModuleType, execution_id: str,
              caplog: pytest.LogCaptureFixture) -> dict:
    """The case through ``module``'s own body: judge from a real read, let the run move
    on, then the fenced end, committed."""
    _put_row(execution_id, case.kind, case.judged)
    judged = module.RowGeneration.from_snapshot(_snapshot(execution_id))
    if case.at_write is not None:
        _move_row(execution_id, case.at_write)
    before = _row(execution_id)
    first = len(caplog.records)
    with _run_updates() as updates, get_session() as session:
        answer = module.end_row_if_same_generation(
            session, execution_id, judged, status=case.end, keep_open=case.keep_open,
            error=None if case.keep_open else ERROR)
    warnings = [r.getMessage() for r in caplog.records[first:] if r.levelno == logging.WARNING]
    return {"id": execution_id, "answer": answer, "updates": len(updates),
            "warnings": warnings, "before": before, "after": _row(execution_id)}


def _wrong(case: Case, outcome: dict) -> list[str]:
    """What the outcome got wrong against the case's known answer (empty: all right)."""
    wrong = []
    if outcome["answer"] is not case.changed:
        wrong.append(f"answered {outcome['answer']!r}")
    before, after = outcome["before"], outcome["after"]
    if case.changed:
        ended = {**before, "status": case.end,
                 "error": before["error"] if case.keep_open else ERROR,
                 "completed_at": after["completed_at"]}
        if after != ended:
            wrong.append(f"ended the row as {after}")
        if (after["completed_at"] is None) is not case.keep_open:
            wrong.append(f"completed_at {after['completed_at']!r}")
    elif after != before:
        wrong.append(f"changed the row to {after}")
    if case.refused:
        if outcome["updates"]:
            wrong.append("sent an UPDATE")
        warnings = outcome["warnings"]
        if len(warnings) != 1 or outcome["id"] not in warnings[0]:
            wrong.append(f"warnings {warnings}")
        if any(identity in w for w in warnings for identity in IDENTITIES):
            wrong.append("a warning shows a dispatch identity")
    elif outcome["updates"] != 1:
        wrong.append(f"{outcome['updates']} UPDATEs")
    return wrong


def _put_ended_run(execution_id: str) -> None:
    """A run whose box ended it: failed(1), the worker's records and lane mark in place."""
    with get_session() as session:
        session.add(WorkflowRun(
            execution_id=execution_id, workflow_name="wf", workspace_path="/workspaces/ws",
            status="failed", attempts=1, spawner_kind=DOCKER, spawner_handle=H,
            spawner_metadata=mark_lane({**KEPT, "container_id": C1}, "pi"),
        ))


def _stamp(execution_id: str, kind: str, handle: str, container_id: str) -> None:
    """The worker dispatches the queued run: its box and this dispatch's container."""
    with get_session() as session:
        row = session.get(WorkflowRun, execution_id)
        row.spawner_kind, row.spawner_handle = kind, handle
        row.spawner_metadata = {**row.spawner_metadata, "container_id": container_id}
        session.add(row)


def _waiting_attempt(execution_id: str, **data: Any) -> str:
    return record(EventType.WORKFLOW_STARTED, execution_id=execution_id, status=WAITING,
                  data=data)


# ── The whole groundwork, as the repair will use it ──────────────────────────────────────


def test_a_claim_its_requeue_and_a_fenced_end_each_land_as_one_decision():
    run = "run-happy"
    _put_ended_run(run)
    attempt = _waiting_attempt(run, attempt=1)

    # The claim: the attempt's compare-and-set and the run's re-queue in one commit.
    with deciding_events() as session:
        won, event = decide_event_in(session, attempt, expect=(WAITING,), status=CARRIED_ON,
                                     data={"carried_on_by": "owner"})
        queue_run_in(session, run, "wf", "/workspaces/ws", {"x": 1}, start="resume")
    assert won
    assert event["status"] == CARRIED_ON
    assert event["data"] == {"attempt": 1, "carried_on_by": "owner"}
    assert get_event(attempt)["status"] == CARRIED_ON
    row = _row(run)
    assert row["status"] == "queued"
    assert row["attempts"] == 1
    assert row["spawner_kind"] is None and row["spawner_handle"] is None
    assert row["spawner_metadata"]["start"] == "resume"
    assert row["spawner_metadata"]["box_profile"] == KEPT["box_profile"]
    assert lane_of(row["spawner_metadata"]) == "pi"
    assert "container_id" not in row["spawner_metadata"]

    # The worker dispatches it; the reaper judges that dispatch from one read and ends it,
    # fenced on what it read.
    _stamp(run, DOCKER, H, C2)
    judged = RowGeneration.from_snapshot(_snapshot(run))
    assert judged == RowGeneration("queued", 1, DOCKER, H, C2)
    with get_session() as session:
        assert end_row_if_same_generation(session, run, judged, status="failed", error=ERROR)
    row = _row(run)
    assert row["status"] == "failed" and row["error"] == ERROR
    assert row["completed_at"] is not None
    # The same judgement again changes nothing: True meant that one write.
    with get_session() as session:
        assert not end_row_if_same_generation(session, run, judged, status="cancelled")
    assert _row(run) == row

    # The public forms are the same decisions, each in a transaction of its own.
    other = _waiting_attempt(run, attempt=2)
    won, event = decide_event(other, expect=(WAITING,), status=CANCELLED, data={"by": "owner"})
    assert won and event["status"] == CANCELLED and event["data"] == {"attempt": 2, "by": "owner"}
    won, event = decide_event(other, expect=(WAITING,), status=CARRIED_ON)
    assert not won and event["status"] == CANCELLED
    assert decide_event("no-such-event", expect=(WAITING,), status=CANCELLED) == (False, None)
    queue_run(run, "wf", "/workspaces/ws", None, start="fork")
    assert _row(run)["status"] == "queued"
    with pytest.raises(AlreadyQueued) as refused:
        queue_run(run, "wf", "/workspaces/ws", None)
    assert refused.value.status == "queued"


# ── The generation fence: G1 known answers ───────────────────────────────────────────────


@pytest.mark.parametrize("case", G1, ids=[case.id for case in G1])
def test_the_fence_ends_only_the_generation_it_judged(case, caplog):
    caplog.set_level(logging.WARNING)
    outcome = _run_case(case, row_generation, f"run-{case.id}", caplog)
    assert _wrong(case, outcome) == []


#: Every case whose end should land: a genuine end, or a dead twin's on a fresh read.
LIVE = frozenset(case.id for case in G1 if case.changed)
#: Every case the fence answers with an UPDATE that changes no row.
ZERO_ROWS = frozenset(case.id for case in G1 if not case.changed and not case.refused)
#: A newer box of the run started meanwhile: the same status, attempts raised.
ATTEMPTS_ONLY = frozenset({
    "ABA1-OWN", "ABA1-C829", "ABA1-C829-LETGO", "ABA1-C847F-A", "ABA1-C847F-B",
    "ABA1-RPR-WAIT", "ABA1-RPR-ORPH", "ABA1-NOH", "ABA1-SIG", "ABA1-BOXCANCEL", "ABA1C",
    "ABA-RR", "ABA1R",
})

#: Each bite weakens one guard in row_generation.py's own source, and gets exactly these
#: cases wrong: never a LIVE one. The r2 bites' counterexamples are among them.
BITES = {
    # True only on rowcount exactly 1 (r2 names ABA1-OWN, ABA1-C829, ABA1C and ABA-RR).
    "B-ROWCOUNT": ([("return result.rowcount == 1", "return True")], ZERO_ROWS),
    # A missing container_id compared as equal. With the refusal gone, the judged None
    # reaches SQL, where SQLAlchemy writes `== None` as IS NULL: NULL-safe equality. So the
    # refusal is the guard; the SQL compare can't be.
    "B-CID-NULLEQ": ([('("container_id", judged.container_id)', '("container_id", "same")')],
                     {"ABAQ-NOID-ADV"}),
    # The status the read judged, not attempts alone.
    "B-STATUS-TERM": ([("col(WorkflowRun.status) == judged.status,", "")],
                      {"I5-TWO-REAPERS", "NOCHANGE-ENDED-NO-RESUME"}),
    # This piece's own guards.
    "B-ATTEMPTS-TERM": ([("col(WorkflowRun.attempts) == judged.attempts,", "")],
                        ATTEMPTS_ONLY),
    "B-CID-TERM": ([("_ROW_CONTAINER_ID == judged.container_id,", "")],
                   {"ABAQ-DOCKER", "ABAQ-DOCKER-CANCEL", "Q-ROW-LOST-CID"}),
    "B-PID-TERM": ([("return [col(WorkflowRun.spawner_handle) == judged.handle]", "return []")],
                   {"ABAQ-SUBPROC", "ABAQ-PILANE"}),
    "B-HANDLE-NULLEQ": ([('(("handle", judged.handle),', '(("handle", "same"),')],
                        {"Q-DOCKER-NO-HANDLE"}),
    "B-PID-NULLEQ": ([("if not judged.handle:", "if False:")], {"Q-SUBPROC-NO-HANDLE"}),
    "B-KIND-OPEN": ([("_no_end(execution_id, kind, [])\n    return None", "return []")],
                    {"Q-UNKNOWN-KIND", "Q-UNSTAMPED"}),
}


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


@pytest.mark.parametrize("bite", list(BITES))
def test_each_fence_guard_has_a_bite(bite, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    mutations, expected = BITES[bite]
    bitten = _mutant(row_generation, mutations, monkeypatch)
    wrong = {case.id for case in G1
             if _wrong(case, _run_case(case, bitten, f"{bite}:{case.id}", caplog))}
    assert wrong == expected
    assert not wrong & LIVE  # every genuine end, and every dead twin's, still lands


@pytest.mark.parametrize("stale", ["ABA1-OWN", "ABAQ-DOCKER", "ABA1C", "G-DEAD-HONOR-CANCEL-QUEUED"])
def test_the_next_tick_ends_what_a_refused_end_left(stale, caplog):
    case = CASES[stale]
    run = f"run-next-{stale}"
    assert _wrong(case, _run_case(case, row_generation, run, caplog)) == []
    # The next tick judges the newer generation from a fresh read, and ends it.
    judged = RowGeneration.from_snapshot(_snapshot(run))
    with get_session() as session:
        assert end_row_if_same_generation(session, run, judged, status=case.end, error=ERROR)
    assert _row(run)["status"] == case.end


def test_a_docker_dispatch_without_container_id_is_left_alone_each_tick_with_a_warning(caplog):
    caplog.set_level(logging.WARNING)
    run = "run-no-container"
    _put_row(run, DOCKER, Gen("queued", 1, H))
    for _tick in range(2):
        judged = RowGeneration.from_snapshot(_snapshot(run))
        with get_session() as session:
            assert not end_row_if_same_generation(session, run, judged, status="failed")
    assert _row(run)["status"] == "queued"
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == 2
    assert all(run in w and "container_id" in w and H not in w for w in warned)


def test_true_means_this_write_ended_the_row():
    """An end that finds the judged generation already ended answers False and leaves its end
    alone: a caller that must say "already ended" reads the row in its own transaction."""
    run = "run-ended-twice"
    _put_row(run, SUBPROC, Gen("waiting", 1, P101))
    judged = RowGeneration.from_snapshot(_snapshot(run))
    with get_session() as session:
        assert end_row_if_same_generation(session, run, judged, status="cancelled", error=ERROR)
    ended = _row(run)
    with get_session() as session:
        assert not end_row_if_same_generation(session, run, judged, status="cancelled",
                                              error={"message": "again"})
        now = session.get(WorkflowRun, run)
        assert (now.status, now.attempts) == ("cancelled", judged.attempts)
    assert _row(run) == ended
    with get_session() as session:
        assert not end_row_if_same_generation(session, "run-nobody", judged, status="cancelled")


def test_the_fence_writes_nothing_until_the_caller_commits():
    run = "run-uncommitted"
    _put_row(run, DOCKER, Gen("running", 1, H, C1))
    judged = RowGeneration.from_snapshot(_snapshot(run))
    with get_session() as session:
        assert end_row_if_same_generation(session, run, judged, status="orphaned")
        session.rollback()
    assert _row(run)["status"] == "running"


@pytest.mark.parametrize("snapshot", [
    {"attempts": 1},
    {"status": "", "attempts": 1},
    {"status": "running"},
    {"status": "running", "attempts": None},
    {"status": "running", "attempts": True},
    {"status": "running", "attempts": "1"},
], ids=["no-status", "empty-status", "no-attempts", "null-attempts", "bool-attempts",
        "text-attempts"])
def test_a_generation_needs_the_status_and_attempts_its_read_found(snapshot):
    with pytest.raises(ValueError):
        RowGeneration.from_snapshot(snapshot)


def test_a_generation_keeps_only_identities_its_read_had():
    judged = RowGeneration.from_snapshot({
        "status": "queued", "attempts": 0, "spawner_kind": DOCKER, "spawner_handle": "",
        "container_id": 7, "cancel_requested": True,
    })
    assert judged == RowGeneration("queued", 0, DOCKER, None, None)
    with pytest.raises(FrozenInstanceError):
        judged.status = "running"  # type: ignore[misc]


# ── One transaction for a decision and its writes ────────────────────────────────────────


class _Abandon(Exception):
    """A step after the decision failed."""


def test_a_decision_and_its_row_end_land_together_or_not_at_all():
    run = "run-cancel"
    _put_row(run, SUBPROC, Gen("waiting", 1, P101))
    attempt = _waiting_attempt(run)
    judged = RowGeneration.from_snapshot(_snapshot(run))

    with pytest.raises(_Abandon), deciding_events() as session:
        assert decide_event_in(session, attempt, expect=(WAITING,), status=CANCELLED)[0]
        assert end_row_if_same_generation(session, run, judged, status="cancelled")
        raise _Abandon
    assert get_event(attempt)["status"] == WAITING
    assert _row(run)["status"] == "waiting"

    with deciding_events() as session:
        assert decide_event_in(session, attempt, expect=(WAITING,), status=CANCELLED)[0]
        assert end_row_if_same_generation(session, run, judged, status="cancelled")
    assert get_event(attempt)["status"] == CANCELLED
    assert _row(run)["status"] == "cancelled"


def test_a_decision_that_loses_leaves_the_transaction_as_it_was():
    run = "run-lost"
    _put_ended_run(run)
    attempt = _waiting_attempt(run)
    decide_event(attempt, expect=(WAITING,), status=CANCELLED, data={"by": "owner"})
    with deciding_events() as session:
        won, event = decide_event_in(session, attempt, expect=(WAITING,), status=CARRIED_ON)
        assert not won
        assert (event["status"], event["data"]) == (CANCELLED, {"by": "owner"})
        assert decide_event_in(session, "no-such-event", expect=(WAITING,),
                               status=CARRIED_ON) == (False, None)
        queue_run_in(session, run, "wf", "/workspaces/ws", None)
    assert get_event(attempt)["status"] == CANCELLED
    assert _row(run)["status"] == "queued"


def test_a_refused_requeue_rolls_its_decision_back():
    run = "run-busy"
    _put_row(run, DOCKER, Gen("running", 1, H, C1))
    attempt = _waiting_attempt(run)
    with pytest.raises(AlreadyQueued) as refused, deciding_events() as session:
        assert decide_event_in(session, attempt, expect=(WAITING,), status=CARRIED_ON)[0]
        queue_run_in(session, run, "wf", "/workspaces/ws", None, start="resume")
    assert refused.value.status == "running"
    assert get_event(attempt)["status"] == WAITING
    assert _row(run)["status"] == "running"


def test_deciding_events_refuses_a_second_decision_transaction_inside_it():
    attempt = _waiting_attempt("run-nested")
    with pytest.raises(RuntimeError, match="already open"), deciding_events() as session:
        decide_event_in(session, attempt, expect=(WAITING,), status=CARRIED_ON)
        decide_event(attempt, expect=(WAITING,), status=CANCELLED)
    assert get_event(attempt)["status"] == WAITING
    assert decide_event(attempt, expect=(WAITING,), status=CANCELLED)[0]


def _on_postgres() -> bool:
    return get_database().engine.dialect.name == "postgresql"


def test_the_sqlite_decision_lock_spans_the_commit_and_the_rollback(decision_lock):
    """On SQLite the next decision must read this one's outcome, so the lock is still held
    when it commits or rolls back. Postgres takes no process lock: row locks do that."""
    held: dict[str, bool] = {}

    def watch(session, name):
        real = getattr(session, name)

        def call():
            held.setdefault(name, decision_lock.locked())  # the first call: deciding_events'
            real()
        setattr(session, name, call)

    attempt = _waiting_attempt("run-lock")
    with deciding_events() as session:
        watch(session, "commit")
        decide_event_in(session, attempt, expect=(WAITING,), status=CARRIED_ON)
    with pytest.raises(_Abandon), deciding_events() as session:
        watch(session, "rollback")
        raise _Abandon
    on_sqlite = not _on_postgres()
    assert held == {"commit": on_sqlite, "rollback": on_sqlite}
    assert not decision_lock.locked()
    assert get_event(attempt)["status"] == CARRIED_ON


def test_decide_event_in_merges_into_the_event_as_it_is_when_locked(monkeypatch):
    assert _merge_after_a_stale_read(recorder) == {"asked": "q1", "answer": "yes", "go": True}
    bitten = _mutant(recorder, [(
        "with_for_update()\n        .execution_options(populate_existing=True),",
        "with_for_update(),")], monkeypatch)
    assert _merge_after_a_stale_read(bitten) == {"asked": "q1", "go": True}  # the answer lost


def _merge_after_a_stale_read(module: ModuleType) -> dict:
    attempt = _waiting_attempt("run-merge", asked="q1")
    with module.deciding_events() as session:
        # The caller read the event before deciding, and still holds it (a session keeps
        # only the objects someone holds)...
        read = session.get(Event, attempt)
        assert read.data == {"asked": "q1"}
        with get_session() as other:  # ...and meanwhile the answer is stored with it
            row = other.get(Event, attempt)
            row.data = {**row.data, "answer": "yes"}
            other.add(row)
        assert module.decide_event_in(session, attempt, expect=(WAITING,), status=CARRIED_ON,
                                      data={"go": True})[0]
    return get_event(attempt)["data"]


def test_queue_run_in_decides_on_the_row_as_it_is_when_locked(monkeypatch):
    assert _requeue_after_a_stale_read(queue, "run-stale") == "queued"
    bitten = _mutant(queue, [(".with_for_update().execution_options(populate_existing=True),",
                              ".with_for_update(),")], monkeypatch)
    assert _requeue_after_a_stale_read(bitten, "run-stale-bitten") == "requeued again"


def _requeue_after_a_stale_read(module: ModuleType, run: str) -> str:
    _put_ended_run(run)
    with deciding_events() as session:
        read = session.get(WorkflowRun, run)  # the caller read the row and holds it...
        assert read.status == "failed"
        queue_run(run, "wf", "/workspaces/ws", None, start="resume")  # ...meanwhile another re-queue
        try:
            module.queue_run_in(session, run, "wf", "/workspaces/ws", None, start="fork")
        except module.AlreadyQueued as refused:
            return refused.status
    return "requeued again"


# ── Two at once ──────────────────────────────────────────────────────────────────────────


def _backend_pid(session) -> int | None:
    if not _on_postgres():
        return None
    return session.connection().exec_driver_sql("select pg_backend_pid()").scalar()


def _wait_until_waiting(lock: _WatchedLock, holder_pid: int | None) -> None:
    """Until the other thread waits on the open decision: on SQLite for the decision lock,
    on Postgres for a lock the holder's transaction has."""
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
    raise AssertionError("the second decision never waited for the open one")


def test_a_second_decision_waits_for_the_open_one_and_finds_its_answer(decision_lock):
    attempt = _waiting_attempt("run-race")
    decided, go = threading.Event(), threading.Event()
    holder: dict[str, Any] = {}

    def first():
        with deciding_events() as session:
            outcome = decide_event_in(session, attempt, expect=(WAITING,), status=CARRIED_ON,
                                      data={"by": "first"})
            holder["pid"] = _backend_pid(session)
            decided.set()
            assert go.wait(15)
        return outcome

    with ThreadPoolExecutor(2) as pool:
        one = pool.submit(first)
        assert decided.wait(15)
        two = pool.submit(decide_event, attempt, expect=(WAITING,), status=CANCELLED,
                          data={"by": "second"})
        _wait_until_waiting(decision_lock, holder["pid"])
        assert not two.done()
        go.set()
        won_one, _ = one.result(20)
        won_two, seen = two.result(20)
    assert won_one and not won_two
    assert (seen["status"], seen["data"]) == (CARRIED_ON, {"by": "first"})
    assert get_event(attempt)["status"] == CARRIED_ON


def _two_claims(module: ModuleType, lock: _WatchedLock, run: str) -> dict:
    """Two claims on one run at once, through ``module``'s queue_run_in: the first holds its
    transaction open until the second waits on it."""
    _put_ended_run(run)
    first, second = _waiting_attempt(run, n=1), _waiting_attempt(run, n=2)
    ready, go = threading.Event(), threading.Event()
    holder: dict[str, Any] = {}

    def claim(attempt, who):
        try:
            with deciding_events() as session:
                won, _ = decide_event_in(session, attempt, expect=(WAITING,), status=CARRIED_ON)
                assert won
                module.queue_run_in(session, run, "wf", "/workspaces/ws", None, start="resume",
                                    extra={"by": who})
                if who == "first":
                    session.flush()  # its re-queue written, not committed, while it waits
                    holder["pid"] = _backend_pid(session)
                    ready.set()
                    assert go.wait(15)
        except module.AlreadyQueued as refused:
            return f"refused: {refused.status}"
        return "requeued"

    with ThreadPoolExecutor(2) as pool:
        one = pool.submit(claim, first, "first")
        assert ready.wait(15)
        two = pool.submit(claim, second, "second")
        _wait_until_waiting(lock, holder["pid"])
        go.set()
        outcome = {"first": one.result(20), "second": two.result(20)}
    row = _row(run)
    return {**outcome, "row": (row["status"], row["spawner_metadata"].get("by")),
            "attempts": (get_event(first)["status"], get_event(second)["status"])}


ONE_CLAIM = {"first": "requeued", "second": "refused: queued", "row": ("queued", "first"),
             "attempts": (CARRIED_ON, WAITING)}


def test_two_claims_on_one_run_requeue_it_once(decision_lock, monkeypatch):
    assert _two_claims(queue, decision_lock, "run-claims") == ONE_CLAIM
    # Without FOR UPDATE, Postgres lets the second claim read the row before the first
    # commits, and re-queue it a second time. SQLite's decision lock already lets one
    # decision through at a time.
    bitten = _mutant(queue, [(".with_for_update()", "")], monkeypatch)
    twice = {"first": "requeued", "second": "requeued", "row": ("queued", "second"),
             "attempts": (CARRIED_ON, CARRIED_ON)}
    expected = twice if _on_postgres() else ONE_CLAIM
    assert _two_claims(bitten, decision_lock, "run-claims-bitten") == expected
