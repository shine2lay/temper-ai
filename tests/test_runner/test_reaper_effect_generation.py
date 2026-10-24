"""F9: judged signals, generation grace and pre-write, True-only Pi cleanup.

A combined happy path comes first. Counting Docker fakes exercise the REAL corrected
DockerSpawner interface; a reused name resolves to B while the judged id still names A.
Pi cases use real throwaway ledger reads and fenced row writes, but only fake Docker.
The exact mutation matrix below changes the production source, not a copy of its rule.
No workflow, model, subprocess worker, live database or real box is used.
"""

from __future__ import annotations

import inspect
import itertools
import logging
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import event as sa_event

from temper_ai.database import get_database, get_session, init_database, reset_database
from temper_ai.observability.models import Event
from temper_ai.observability.reconcile import settle_run_event
from temper_ai.runner import pi_lane
from temper_ai.runner.lanes import PI_LANE, mark_lane
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.row_generation import RowGeneration
from temper_ai.spawner import reaper as reaper_module
from temper_ai.spawner.docker_spawner import DockerSpawner
from tests.test_runner.pi_lane.test_forced_stop import Docker as MemberDocker
from tests.test_runner.test_docker_judged_identity import A, B, CountingDocker

NAME = "temper-run-effects"
PID = "4242"
M1, M2, M3, OTHER = ("temper-pi-" + c * 20 for c in "1234")
T0 = datetime(2026, 1, 5, 9, tzinfo=UTC)
_IDS = itertools.count()


@pytest.fixture(autouse=True)
def _file_or_postgres(request, tmp_path):
    """A file for real concurrent SQLite writes; otherwise the isolated Postgres tier."""
    from tests.conftest import TEST_DATABASE_URL

    if request.node.stash.get(TEST_DATABASE_URL, "").startswith("sqlite"):
        reset_database()
        init_database(f"sqlite:///{tmp_path / 'effects.db'}")


@pytest.fixture(autouse=True)
def _no_real_processes(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("F9 attempted a real subprocess")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


class World:
    """Real row/event/ledger state, a controlled clock, and counted effects."""

    def __init__(self, module, monkeypatch):
        self.module, self.patch = module, monkeypatch
        self.eid = f"fx-{next(_IDS)}"
        self.name = f"temper-run-{self.eid}"
        self.now = T0
        self.rowcounts: list[int] = []
        self.returns: list[bool] = []
        self.settles: list[str] = []
        self.probes: list[str] = []
        self.trace: list[str] = []
        self.moving = False
        self.before_write: Callable[[], None] | None = None
        self.docker = CountingDocker()
        self.docker.add(A, self.name, running=True)
        self.member_docker = MemberDocker()
        self.ledger_reads = 0
        self.signals: list[tuple[str, bool]] = []
        self.after_kill: Callable[[], None] | None = None
        self.after_inspect: Callable[[], None] | None = None
        self.removes: list[str] = []

        world = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: ARG003 - always UTC here
                return world.now

        monkeypatch.setattr(module, "datetime", Clock)
        monkeypatch.setattr(module, "settle_run_event", self.settle)
        sa_event.listen(get_database().engine, "after_cursor_execute", self.after_sql)

    def close(self):
        sa_event.remove(get_database().engine, "after_cursor_execute", self.after_sql)

    def after_sql(self, conn, cursor, statement, parameters, context, executemany):  # noqa: ARG002
        if not self.moving and statement.lstrip().upper().startswith("UPDATE WORKFLOW_RUNS"):
            self.rowcounts.append(cursor.rowcount)

    def put(self, *, attempt=1, cid=A, kind="docker", status="running", cancel=True,
            handle=NAME, lane=None):
        self.moving = True
        try:
            with get_session() as session:
                row = session.get(WorkflowRun, self.eid) or WorkflowRun(
                    execution_id=self.eid, workflow_name="wf", workspace_path="/ws")
                row.status, row.attempts = status, attempt
                row.spawner_kind = kind
                row.spawner_handle = self.name if kind == "docker" and handle == NAME else handle
                row.spawner_metadata = mark_lane({"container_id": cid} if cid is not None else {}, lane)
                row.cancel_requested = cancel
                row.completed_at = None
                session.add(row)
        finally:
            self.moving = False

    def start(self, attempt=1):
        with get_session() as session:
            session.add(Event(id=f"{self.eid}:{attempt}", type="workflow.started",
                              execution_id=self.eid, status="running", data={},
                              timestamp=T0 + timedelta(seconds=attempt)))

    def settle(self, eid, status, message):
        self.trace.append("settle")
        self.settles.append(status)
        return settle_run_event(eid, status, message)

    def row(self):
        with get_session() as session:
            row = session.get(WorkflowRun, self.eid)
            return (row.status, row.attempts, (row.spawner_metadata or {}).get("container_id"))

    def events(self):
        with get_session() as session:
            return tuple(session.get(Event, f"{self.eid}:{n}").status for n in (1, 2)
                         if session.get(Event, f"{self.eid}:{n}") is not None)

    def docker_spawner(self):
        def docker(argv, **kwargs):
            result = self.docker(argv, **kwargs)
            if argv[1] == "inspect" and self.after_inspect is not None:
                hook, self.after_inspect = self.after_inspect, None
                hook()
            return result

        spawner = DockerSpawner(template_container="fake-worker", run=docker,
                                workspace_lookup=lambda _eid: "/nonexistent", profile_store=object())
        original = spawner.is_alive

        def alive(handle):
            self.probes.append("alive")
            return original(handle)

        spawner.is_alive = alive
        return spawner

    def process_spawner(self):
        world = self

        class Process:
            def is_alive(self, handle):
                world.probes.append("alive")
                return True

            def kill(self, handle, *, force=False):
                world.signals.append((handle.handle, force))
                world.trace.append("kill" if force else "term")
                if force and world.after_kill:
                    world.after_kill()

        return Process()

    def reaper(self, spawner=None, *, lane=None):
        r = self.module.Reaper(spawner or self.docker_spawner(), kill_grace_seconds=30, lane=lane)
        mark = r._mark_status

        def write(*args, **kwargs):
            self.trace.append("write")
            if self.before_write:
                hook, self.before_write = self.before_write, None
                hook()
            answer = mark(*args, **kwargs)
            self.returns.append(answer)
            return answer

        r._mark_status = write
        return r

    def judged(self, r):
        [row] = [row for row in r._load_live_rows() if row["execution_id"] == self.eid]
        return row

    def expired(self, r):
        judged = RowGeneration.from_snapshot(self.judged(r))
        r._termed_at[r._grace_key(self.eid, judged)] = self.now - timedelta(seconds=31)

    def new_dispatch(self):
        self.put(attempt=2, cid=B, cancel=False)
        self.start(2)
        self.docker.boxes.pop(A, None)
        self.docker.add(B, self.name, running=True)

    def member(self, tag, name, *, run=None, state="running"):
        from temper_ai.pi_agent.ledger import turns

        with get_database().engine.begin() as conn:
            conn.execute(turns.insert().values(
                turn_id=f"{self.eid}:{tag}", participant_id=f"{self.eid}:{tag}",
                run_id=run or self.eid, host_path="team", turn_no=1, state=state, epoch=0,
                claimed_by="attempt-1", input_seqs=[], model_call_ids=[], effect_state="intent",
                refusals=[], box_name=name))
        if name in (M1, M2, M3, OTHER):
            self.member_docker.boxes[name] = "running"

    def pi(self):
        from temper_ai.pi_agent import box
        from temper_ai.pi_agent.ledger import Ledger

        Ledger(get_database().engine).ensure()
        self.put(kind="subprocess", handle=PID, cid=None, lane=PI_LANE)
        self.start()
        self.patch.setattr(box, "_docker_cli", self.member_docker)
        read = pi_lane._ledger_box_names
        stop = box.stop_leftover_box

        def names(*, run_id=None):
            self.ledger_reads += 1
            self.trace.append("snapshot")
            return read(run_id=run_id)

        def remove(name, **kwargs):
            self.trace.append("remove")
            self.removes.append(name)
            return stop(name, **kwargs)

        self.patch.setattr(pi_lane, "_ledger_box_names", names)
        self.patch.setattr(box, "stop_leftover_box", remove)
        return self.reaper(self.process_spawner(), lane=PI_LANE)


def happy(w):
    w.put()
    w.start()
    r = w.reaper()
    r.tick()  # TERM, and a full grace
    w.now += timedelta(seconds=30)
    r.tick()  # equality is still grace, not KILL
    w.now += timedelta(seconds=1)
    r.tick()  # KILL + one fenced end/settle
    r.tick()  # terminal row cannot be re-ended
    return (w.docker.targets(), w.docker.signals, w.row(), w.events(), w.returns,
            w.rowcounts, w.settles, r._termed_at)


def signal(w, *, force, stale):
    w.put()
    w.start()
    r = w.reaper()
    if force:
        w.expired(r)
    if stale:
        w.after_inspect = w.new_dispatch  # answer fixed on A; name belongs to B before signal
    r.tick()
    return (w.docker.targets(), w.docker.signals, w.row(), w.events(), w.returns,
            w.rowcounts, w.settles, bool(w.docker.boxes.get(B) and w.docker.boxes[B].running))


def liveness(w, *, stale):
    w.put(cancel=False)
    w.start()
    r = w.reaper()
    row = w.judged(r)
    if stale:
        w.new_dispatch()
    else:
        w.docker.boxes.pop(A)
    r._process_row(row)  # A has gone, independently of B's reused shared name
    return (w.docker.targets(), w.row(), w.events(), w.returns, w.rowcounts, w.settles,
            bool(w.docker.boxes.get(B) and w.docker.boxes[B].running))


def no_id(w, *, cid, status, handle=NAME):
    w.put(cid=cid, status=status, handle=handle)
    if status == "running":
        w.start()
    r = w.reaper()
    r.tick()
    return (w.probes, w.docker.calls, w.docker.signals, w.returns, w.rowcounts, w.settles,
            w.row(), r._termed_at)


def grace(w, *, change):
    process = change == "pid-attempt"
    kind, cid, handle = ("subprocess", None, PID) if process else ("docker", A, NAME)
    w.put(kind=kind, cid=cid, handle=handle)
    w.start()
    r = w.reaper(w.process_spawner() if process else None)
    r.tick()
    # Age A's grace beyond expiry, then resume: either attempts alone or dispatch alone changes.
    w.now += timedelta(seconds=31)
    attempt = 1 if change == "cid" else 2
    new_cid = B if change == "cid" else cid
    w.put(kind=kind, cid=new_cid, handle=handle, attempt=attempt)
    if change == "cid":
        w.docker.boxes.pop(A)
        w.docker.add(B, w.name, running=True)
    r.tick()
    # Normalize only the execution id, which differs across cases and mutation repetitions.
    resumed = [(key[1:], at - T0) for key, at in r._termed_at.items()]
    w.now += timedelta(seconds=30)
    r.tick()
    before_expiry = list(w.signals if process else w.docker.signals)
    w.now += timedelta(seconds=1)
    r.tick()
    return (resumed, before_expiry, w.signals if process else w.docker.signals,
            w.row(), w.returns, w.rowcounts, w.settles, r._termed_at)


def prune(w):
    w.put()
    r = w.reaper()
    r.tick()
    w.put(status="completed")
    r.tick()  # no live rows: the old key must disappear without another signal
    return r._termed_at, w.docker.targets(), w.docker.signals


def pi_cleanup(w, *, stale, empty):
    r = w.pi()
    if not empty:
        w.member("a", M1)
        w.member("duplicate", M1)
        w.member("invalid", M1 + "\n")
        w.member("ended", OTHER, state="completed")
        w.after_kill = lambda: w.member("after-kill", M2)
    w.member("other-run", OTHER, run=w.eid + "-other")

    def before_write():
        # Added AFTER the saved read, even when it saved nothing. Never a cleanup target.
        w.member("after-snapshot", M3)
        if stale:
            w.put(kind="subprocess", handle="4343", cid=None, lane=PI_LANE, attempt=2)
            w.start(2)

    w.before_write = before_write
    w.expired(r)
    r.tick()
    return (w.trace, w.removes, w.ledger_reads, w.member_docker.touched(), w.row(),
            w.events(), w.returns, w.rowcounts, w.settles, r._termed_at)


def exact_members(w):
    w.pi()
    w.member("exact", M1)
    w.member("duplicate", M1)
    w.member("trailing-lf", M1 + "\n")
    w.member("other-run", OTHER, run=w.eid + "-other")
    saved = pi_lane.snapshot_member_box_names_of_killed_run(w.eid)
    # Revalidate a saved input without expanding it or looking the run up again.
    pi_lane.remove_saved_member_boxes_of_killed_run(w.eid, (M1 + "\n", M1))
    return saved, w.removes, w.ledger_reads, w.member_docker.touched()


@dataclass(frozen=True)
class Case:
    name: str
    run: Callable[[World], Any]
    expected: Any


# Explicit known answers: no production predicate determines the expected side.
CASES = [
    Case("HAPPY", happy,
         ([("inspect", A), ("kill", A), ("inspect", A), ("inspect", A), ("kill", A)],
          [(A, "TERM"), (A, "KILL")], ("cancelled", 1, A), ("cancelled",),
          [True], [1], ["cancelled"], {})),
]
for force in (False, True):
    for stale in (False, True):
        CASES.append(Case(
            ("STALE-" if stale else "TWIN-") + ("KILL" if force else "TERM"),
            lambda w, f=force, s=stale: signal(w, force=f, stale=s),
            ([("inspect", A), ("kill", A)], [] if stale else [(A, "KILL" if force else "TERM")],
             ("running", 2, B) if stale else ("cancelled" if force else "running", 1, A),
             ("running", "running") if stale else ("cancelled" if force else "running",),
             [not stale] if force else [], [0 if stale else 1] if force else [],
             ["cancelled"] if force and not stale else [], stale)))
for stale in (False, True):
    CASES.append(Case(
        "STALE-ALIVE" if stale else "TWIN-GONE", lambda w, s=stale: liveness(w, stale=s),
        ([("inspect", A)], ("running", 2, B) if stale else ("orphaned", 1, A),
         ("running", "running") if stale else ("interrupted",), [not stale],
         [0 if stale else 1], [] if stale else ["interrupted"], stale)))
for label, cid in (("ABSENT", None), ("EMPTY", ""), ("NONSTRING", 7)):
    for status in ("running", "queued"):
        CASES.append(Case(
            f"NOID-{label}-{status}", lambda w, c=cid, s=status: no_id(w, cid=c, status=s),
            ([], [], [], [], [], [], (status, 1, cid), {})))
CASES.append(Case("NOID-NOHANDLE", lambda w: no_id(w, cid=None, status="running", handle=None),
                  ([], [], [], [], [], [], ("running", 1, None), {})))
for change in ("attempt", "cid", "pid-attempt"):
    proc = change == "pid-attempt"
    next_id, attempt = (None if proc else B if change == "cid" else A), (1 if change == "cid" else 2)
    initial = (PID, False) if proc else (A, "TERM")
    term = (PID, False) if proc else (next_id, "TERM")
    kill = (PID, True) if proc else (next_id, "KILL")
    CASES.append(Case(
        f"GRACE-RESUMED-{change}", lambda w, c=change: grace(w, change=c),
        ([((attempt, next_id), timedelta(seconds=31))], [initial, term], [initial, term, kill],
         ("cancelled", attempt, next_id), [True], [1], ["cancelled"], {})))
CASES.append(Case("GRACE-PRUNE", prune,
                  ({}, [("inspect", A), ("kill", A)], [(A, "TERM")])))
for stale in (False, True):
    for empty in (False, True):
        names = [] if empty or stale else [M1, M2]
        CASES.append(Case(
            f"PI-{'FALSE' if stale else 'TRUE'}-{'EMPTY' if empty else 'SAVED'}",
            lambda w, s=stale, e=empty: pi_cleanup(w, stale=s, empty=e),
            (["kill", "snapshot", "write"] + ([] if stale else ["settle"] + ["remove"] * len(names)),
             names, 1, set(names), ("running", 2, None) if stale else ("cancelled", 1, None),
             ("running", "running") if stale else ("cancelled",), [not stale],
             [0 if stale else 1], [] if stale else ["cancelled"], {})))

CASES.append(Case("PI-EXACT-NAMES", exact_members, ((M1,), [M1], 1, {M1})))
CASE = {case.name: case for case in CASES}
assert len(CASE) == len(CASES)


def run_case(case, module, monkeypatch):
    # A fresh patch context also restores wrapped ledger reads between mutation cases.
    with monkeypatch.context() as patch:
        w = World(module, patch)
        try:
            return case.run(w)
        finally:
            w.close()
            # Other cases in the same test must not be swept by this case's reaper.
            with get_session() as session:
                row = session.get(WorkflowRun, w.eid)
                if row is not None:
                    row.status = "completed"
                    session.add(row)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_judged_effects_known_answers(case, monkeypatch):
    assert run_case(case, reaper_module, monkeypatch) == case.expected


@pytest.mark.parametrize("missing", [None, "", 7])
def test_missing_id_warning_is_metadata_only_and_each_tick(missing, monkeypatch, caplog):
    with monkeypatch.context() as patch:
        w = World(reaper_module, patch)
        try:
            w.put(cid=missing)
            r = w.reaper()
            with caplog.at_level(logging.WARNING):
                r.tick()
                r.tick()
            warnings = [rec.getMessage() for rec in caplog.records
                        if rec.name == reaper_module.__name__]
            assert len(warnings) == 2
            assert all(w.eid in s and "container_id" in s and w.name not in s and A not in s
                       for s in warnings)
            assert not w.probes and not w.docker.calls and not w.rowcounts and not w.settles
        finally:
            w.close()


@pytest.mark.parametrize("empty", [False, True])
def test_false_cleanup_warns_honestly_about_running_leftovers(empty, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        result = run_case(CASE[f"PI-FALSE-{'EMPTY' if empty else 'SAVED'}"],
                          reaper_module, monkeypatch)
    assert result == CASE[f"PI-FALSE-{'EMPTY' if empty else 'SAVED'}"].expected
    warnings = [rec.getMessage() for rec in caplog.records]
    assert any("no member boxes removed" in s and "may still be running" in s
               and "start-up sweep" in s for s in warnings)


# One guard at a time, applied to actual source. All known cases are run for each mutation;
# its EXACT failures are asserted, so setup errors and accidental collateral do not count.
GRACE_CASES = {f"GRACE-RESUMED-{c}" for c in ("attempt", "cid", "pid-attempt")}
PI_CASES = {name for name in CASE if name.startswith(("PI-TRUE-", "PI-FALSE-"))}
NOID_CASES = {name for name in CASE if name.startswith("NOID-")}
BITES = {
    "NAME-TARGET": (reaper_module, [(
        '            metadata[JUDGED_CONTAINER_ID] = judged.container_id',
        '            metadata.pop(JUDGED_CONTAINER_ID, None)')],
        {name for name in CASE if name.startswith(("STALE-", "TWIN-"))} |
        {"HAPPY", "GRACE-PRUNE"}),
    "MISSING-GUARD": (reaper_module, [(
        '        if judged.spawner_kind == SpawnerKind.docker.value and judged.container_id is None:',
        '        if False:')], NOID_CASES),
    "EXECUTION-GRACE": (reaper_module, [(
        '        return execution_id, judged.attempts, judged.container_id',
        '        return execution_id, 0, None')], GRACE_CASES),
    "NO-PRUNE": (reaper_module, [('                           if key in live_generations}',
                                  '                           if True}')],
                 GRACE_CASES | {"GRACE-PRUNE"}),
    "UNCONDITIONAL-CLEANUP": (reaper_module, [(
        '            if self._mark_status(execution_id, "cancelled", judged=judged):',
        '            if self._mark_status(execution_id, "cancelled", judged=judged) or True:')],
        {"STALE-KILL", "PI-FALSE-SAVED", "PI-FALSE-EMPTY"}),
    "LATE-REREAD": (pi_lane, [(
        '    for name in names:\n        if not pibox.BOX_NAME.fullmatch(name):',
        '    for name in _ledger_box_names(run_id=execution_id):\n'
        '        if not pibox.BOX_NAME.fullmatch(name):')],
        {"PI-TRUE-SAVED", "PI-TRUE-EMPTY", "PI-EXACT-NAMES"}),
    "EMPTY-REREAD": (pi_lane, [(
        '    for name in names:\n        if not pibox.BOX_NAME.fullmatch(name):',
        '    for name in names or _ledger_box_names(run_id=execution_id):\n'
        '        if not pibox.BOX_NAME.fullmatch(name):')], {"PI-TRUE-EMPTY"}),
    "SNAPSHOT-MATCH": (pi_lane, [(
        'if pibox.BOX_NAME.fullmatch(name)}))',
        'if pibox.BOX_NAME.match(name)}))')], {"PI-EXACT-NAMES"}),
    "REMOVE-MATCH": (pi_lane, [(
        '        if not pibox.BOX_NAME.fullmatch(name):',
        '        if not pibox.BOX_NAME.match(name):')], {"PI-EXACT-NAMES"}),
    "BEFORE-KILL-SNAPSHOT": (reaper_module, [(
        '        if now - sent_at > timedelta(seconds=self._kill_grace):\n            try:',
        '        if now - sent_at > timedelta(seconds=self._kill_grace):\n'
        '            from temper_ai.runner.lanes import PI_LANE\n'
        '            from temper_ai.runner.pi_lane import snapshot_member_box_names_of_killed_run\n'
        '            early_names = (snapshot_member_box_names_of_killed_run(execution_id)\n'
        '                           if self._lane == PI_LANE else ())\n            try:'), (
        '                member_names = snapshot_member_box_names_of_killed_run(execution_id)',
        '                member_names = early_names')], PI_CASES),
}


def mutant(module, edits, monkeypatch):
    source = inspect.getsource(module)
    for old, new in edits:
        assert source.count(old) == 1, f"mutation needs exactly one anchor: {old!r}"
        source = source.replace(old, new)
    bitten = ModuleType(module.__name__ + "_effect_bite")
    bitten.__file__ = module.__file__
    monkeypatch.setitem(sys.modules, bitten.__name__, bitten)
    exec(compile(source, module.__file__, "exec"), bitten.__dict__)  # noqa: S102
    return bitten


@pytest.mark.parametrize("bite", list(BITES))
def test_effect_guard_exact_mutation_bites(bite, monkeypatch):
    module, edits, expected = BITES[bite]
    bitten = mutant(module, edits, monkeypatch)
    if module is pi_lane:
        # Reaper imports these names at the effect boundary, as in production.
        for name in ("snapshot_member_box_names_of_killed_run", "remove_saved_member_boxes_of_killed_run"):
            monkeypatch.setattr(pi_lane, name, getattr(bitten, name))
        # The mutated functions must use the instrumented REAL ledger read and fake Docker.
        original_read = pi_lane._ledger_box_names

        def names(*, run_id=None):
            return pi_lane._ledger_box_names(run_id=run_id)

        monkeypatch.setattr(bitten, "_ledger_box_names", names)
        assert pi_lane._ledger_box_names is original_read
        run_module = reaper_module
    else:
        run_module = bitten
    results = {case.name: run_case(case, run_module, monkeypatch) for case in CASES}
    wrong = {case.name for case in CASES if results[case.name] != case.expected}
    assert wrong == expected
    if bite == "NAME-TARGET":
        # It must bite by actually signalling the reused name's newer box, not by
        # accidentally asking for an unrelated nonexistent test name.
        assert results["STALE-TERM"][1] == [(B, "TERM")]
        assert results["STALE-KILL"][1] == [(B, "KILL")]
        assert results["STALE-TERM"][-1] is True
        assert results["STALE-KILL"][-1] is False


@pytest.mark.parametrize("round_", [1, 2])
def test_two_forced_reapers_only_successful_fence_cleans_saved_names(round_, monkeypatch):
    w = World(reaper_module, monkeypatch)
    try:
        r1 = w.pi()
        w.member(f"member-{round_}", M1)
        r2 = w.reaper(w.process_spawner(), lane=PI_LANE)
        both = threading.Barrier(2, timeout=20)
        w.after_kill = both.wait
        w.expired(r1)
        w.expired(r2)
        threads = [threading.Thread(target=r.tick) for r in (r1, r2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not any(thread.is_alive() for thread in threads)
        assert sorted(w.returns) == [False, True]
        assert sorted(w.rowcounts) == [0, 1]
        assert w.settles == ["cancelled"]
        assert w.removes == [M1]
        assert w.ledger_reads == 2
        assert w.member_docker.touched() == {M1}
        assert w.row() == ("cancelled", 1, None)
        assert w.events() == ("cancelled",)
        assert r1._termed_at == r2._termed_at == {}
    finally:
        w.close()
