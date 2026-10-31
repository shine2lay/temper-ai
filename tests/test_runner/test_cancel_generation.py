"""S1-X: a parked cancel and its permitted row outcome commit together.

Happy path first; known answers from T13-R2/P17, T16 and adopted F-A. A judged
reaper/own-box stop is not a fresh API stop. Same attempts now waiting ends once;
same attempts already ended preserves the row; newer attempts/queued refuses.

On Postgres a before-UPDATE hook commits a second connection's actual row cycle.
File SQLite serialises that writer behind the cancel's transaction: assert that
order, not an impossible concurrent commit. A separate same-transaction SQL seam
on both tiers checks the conditional predicate/rowcount against fixed changed
rows, including attempts-only ABA. Mutations must change a known answer, not just
miss a source anchor. No server, box, provider or model is started.
"""

from __future__ import annotations

import argparse
import inspect
import sys
import threading
from dataclasses import replace
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import update as sa_update
from sqlmodel import col, select

from temper_ai.cli import run_workflow
from temper_ai.database import get_database, get_session
from temper_ai.observability import recorder
from temper_ai.observability.event_types import EventType
from temper_ai.observability.models import Event
from temper_ai.observability.recorder import get_event
from temper_ai.runner import holds, parked, queue, row_generation
from temper_ai.runner.execute import ExecuteResult
from temper_ai.runner.lanes import KEEP_LANE
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.parked import CANCELLED, CARRIED_ON, WAITING, AlreadyCarriedOn
from temper_ai.runner.row_generation import RowGeneration
from temper_ai.spawner import reaper as reaper_module
from tests.test_runner.test_parked_claim_atomic import (
    _attempt,
    _backend_pid,
    _on_postgres,
    _row,
    _state,
    _wait_until_waiting,
    _writes_and_commits,
    at,
)
from tests.test_runner.test_parked_claim_atomic import (
    _shared_database as _shared_database,
)
from tests.test_runner.test_parked_claim_atomic import (
    decision_lock as decision_lock,
)

_END_ROW_IN = parked._end_row_in
_QUEUE_RUN_IN = queue.queue_run_in


def _judged(status: str = "running", attempts: int = 1) -> RowGeneration:
    return RowGeneration(status, attempts, "subprocess", "pid-101", None)


def _change(run: str, *, status: str, attempts: int, session=None) -> None:
    """A fixed stand-in row writer; never invokes a worker or execution."""
    stmt = (sa_update(WorkflowRun).where(col(WorkflowRun.execution_id) == run)
            .values(status=status, attempts=attempts, spawner_handle="pid-202",
                    completed_at=at("10:31:00") if status == "orphaned" else None)
            .execution_options(synchronize_session=False))
    if session is not None:
        session.exec(stmt)
    else:
        with get_session() as connection:
            connection.exec(stmt)


def _effects(module: ModuleType, monkeypatch) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "_reject_open_waits", lambda run, why: seen.append(("waits", run)))
    monkeypatch.setattr(module, "_end_pi_teams", lambda run: seen.append(("teams", run)))
    monkeypatch.setattr(module, "_hold", lambda run, *args: seen.append(("hold", run)))
    return seen


# ── Opening combined happy path ──────────────────────────────────────────────


def test_owner_stop_commits_once_then_rejects_the_wait_and_keeps_the_held_cleanup(monkeypatch):
    run = "cancel-whole"
    held = [{"path": "close", "name": "close"}]
    a1 = _attempt(run, note={"path": "talk", "event_id": "gate-whole", "on_cancel": {
        "mode": "hold", "held": held, "hold_hours": 24}})
    _row(run, "running", handle="pid-101")
    with get_session() as session:
        session.add(Event(id="gate-whole", type=EventType.STAGE_STARTED, execution_id=run,
                          status=WAITING, data={"gate": True, "name": "talk"}, timestamp=at("10:01:00")))
    before = _state(run)
    split: list[dict] = []
    post: list[dict] = []

    def end(session, execution_id, status, *, judged):
        split.append(_state(execution_id))  # another connection: CAS still invisible
        return _END_ROW_IN(session, execution_id, status, judged=judged)

    monkeypatch.setattr(parked, "_end_row_in", end)
    monkeypatch.setattr(parked, "_end_pi_teams", lambda eid: post.append(_state(eid)))
    with _writes_and_commits() as writes:
        assert parked.cancel_parked(run, "  keep my setup  ", judged=_judged()) is True
    assert split == [before]
    first_write = writes.index("UPDATE events")
    first_commit = writes.index("COMMIT", first_write)
    assert set(writes[:first_write]) <= {"COMMIT"}  # parked_attempt's read-only session
    assert writes[first_write:first_commit] == ["UPDATE events", "UPDATE workflow_runs"]
    assert writes.count("UPDATE workflow_runs") == 1
    state = _state(run)
    assert state["event"]["status"] == state["row"]["status"] == CANCELLED
    assert state["row"]["completed_at"] is not None
    assert state["event"]["timestamp"] == before["event"]["timestamp"]
    assert state["event"]["data"]["parked"] == a1["data"]["parked"]
    assert state["event"]["data"]["cancelled_reason"] == "keep my setup"
    assert state["event"]["data"]["stopped"]["held"] == held
    assert post == [state]  # team effects see both committed
    gate = get_event("gate-whole")
    assert gate is not None and gate["status"] == "rejected"
    assert gate["data"]["gate_response"]["text"] == "keep my setup"
    kept = holds.waiting(run)
    assert kept is not None and kept["cleanups"] == held and kept["stop_reason"] == "keep my setup"
    assert parked.cancel_parked(run, "again", judged=_judged()) is False
    assert _state(run) == state and post == [state]


# ── F-A and judged versus fresh stops ────────────────────────────────────────


def _disposition(module: ModuleType, case: str, monkeypatch) -> dict:
    run = f"disposition-{case}"
    _attempt(run)
    status, attempts, judged = {
        "G-ABA1R": ("running", 1, _judged()),
        "G-ABA1C": (WAITING, 1, None),
        "G-ABA-RR": ("running", 1, None),
        "ABA1R-SAMEGEN": (WAITING, 1, _judged()),
        "ABA1R-SAMEGEN-ORPH": ("orphaned", 1, _judged()),
        "SAMEGEN-COMPLETED": ("completed", 1, _judged()),
        "SAMEGEN-CANCELLED": (CANCELLED, 1, _judged()),
        "ABA1R": ("running", 2, _judged()),
        "ABA1R-WAITING": (WAITING, 2, _judged()),
        "ABA1R-ENDED": ("orphaned", 2, _judged()),
        "NEWLY-QUEUED": ("queued", 1, _judged()),
        "FRESH-QUEUED": ("queued", 1, None),
        "JUDGED-QUEUED": (WAITING, 1, _judged("queued")),
        "FRESH-NOW": (WAITING, 2, None),
        "FRESH-ENDED": ("orphaned", 2, None),
    }[case]
    _row(run, status, handle="pid-101")
    _change(run, status=status, attempts=attempts)
    before = _state(run)
    effects = _effects(module, monkeypatch)
    with _writes_and_commits() as writes:
        result = module.cancel_parked(run, "owner stop", judged=judged)
    after = _state(run)
    return {"result": result, "event": after["event"]["status"],
            "row": after["row"]["status"], "attempts": after["row"]["attempts"],
            "row_unchanged": after["row"] == before["row"],
            "all_unchanged": after == before, "row_writes": writes.count("UPDATE workflow_runs"),
            "effects": len(effects)}


def _expected(case: str) -> dict:
    refused = case in {"ABA1R", "ABA1R-WAITING", "ABA1R-ENDED", "NEWLY-QUEUED",
                       "FRESH-QUEUED", "JUDGED-QUEUED"}
    ended = case in {"ABA1R-SAMEGEN-ORPH", "SAMEGEN-COMPLETED", "SAMEGEN-CANCELLED", "FRESH-ENDED"}
    status = {"ABA1R": "running", "ABA1R-WAITING": WAITING, "ABA1R-ENDED": "orphaned",
              "NEWLY-QUEUED": "queued", "FRESH-QUEUED": "queued", "JUDGED-QUEUED": WAITING,
              "ABA1R-SAMEGEN-ORPH": "orphaned", "SAMEGEN-COMPLETED": "completed",
              "SAMEGEN-CANCELLED": CANCELLED, "FRESH-ENDED": "orphaned"}.get(case, CANCELLED)
    return {"result": not refused, "event": WAITING if refused else CANCELLED,
            "row": status, "attempts": 2 if case in {
                "ABA1R", "ABA1R-WAITING", "ABA1R-ENDED", "FRESH-NOW", "FRESH-ENDED"} else 1,
            "row_unchanged": refused or ended, "all_unchanged": refused,
            "row_writes": 0 if refused or ended else 1, "effects": 0 if refused else 2}


DISPOSITIONS = ["G-ABA1R", "G-ABA1C", "G-ABA-RR", "ABA1R-SAMEGEN", "ABA1R-SAMEGEN-ORPH",
                "SAMEGEN-COMPLETED", "SAMEGEN-CANCELLED", "ABA1R", "ABA1R-WAITING",
                "ABA1R-ENDED", "NEWLY-QUEUED", "FRESH-QUEUED", "JUDGED-QUEUED",
                "FRESH-NOW", "FRESH-ENDED"]


@pytest.mark.parametrize("case", DISPOSITIONS)
def test_t16_judged_stops_keep_same_generation_and_refuse_newer_or_queued(case, monkeypatch):
    assert _disposition(parked, case, monkeypatch) == _expected(case)


def test_no_row_is_in_process_only_and_a_refused_judgment_can_be_followed_by_a_fresh_stop(monkeypatch):
    effects = _effects(parked, monkeypatch)
    run = "cancel-no-row"
    _attempt(run)
    before = _state(run)
    assert parked.cancel_parked(run, judged=_judged()) is False
    assert _state(run) == before and effects == []
    assert parked.cancel_parked(run) is True
    assert _state(run)["row"] is None
    assert _state(run)["event"]["data"]["cancelled_reason"] == parked.CANCEL_MESSAGE

    # G-DEAD-ABA1R: stale tick refuses; the next fresh tick may free the new dead
    # box's row, and a stop judged on that new generation must still work.
    run = "cancel-dead-new-generation"
    _attempt(run)
    _row(run, "running", handle="pid-101")
    _change(run, status="running", attempts=2)
    assert parked.cancel_parked(run, judged=_judged()) is False
    with get_session() as session:
        assert row_generation.end_row_if_same_generation(
            session, run, _judged(attempts=2), status=WAITING, keep_open=True) is True
    state = _state(run)
    assert state["row"]["status"] == WAITING and state["row"]["completed_at"] is None
    assert state["event"]["status"] == WAITING
    assert parked.cancel_parked(run, judged=_judged(attempts=2)) is True
    assert _state(run)["row"]["status"] == CANCELLED


def _ended_reread(module: ModuleType, moved: str, monkeypatch) -> dict:
    run = f"ended-reread-{moved}"
    _attempt(run)
    _row(run, "orphaned")
    before = _state(run)
    effects = _effects(module, monkeypatch)
    locked_row = parked._locked_row

    def lock(session, execution_id):
        if moved == "missing":
            row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == run)).one()
            session.delete(row)
            session.flush()
        else:
            status, attempts = {"newer": ("orphaned", 2), "queued": ("queued", 1),
                                "waiting": (WAITING, 1)}[moved]
            _change(run, status=status, attempts=attempts, session=session)
            # Give a queued row a complete dispatch identity, so only this cancel's
            # queued refusal (not G's separate missing-identity guard) can save it.
            session.exec(sa_update(WorkflowRun).where(col(WorkflowRun.execution_id) == run)
                         .values(spawner_kind="subprocess").execution_options(synchronize_session=False))
        return locked_row(session, execution_id)

    monkeypatch.setattr(module, "_locked_row", lock)
    result = module.cancel_parked(run, judged=_judged())
    after = _state(run)
    return {"result": result, "unchanged": after == before,
            "event": after["event"]["status"], "effects": len(effects)}


def _reread_expected(moved: str) -> dict:
    return {"result": moved == "waiting", "unchanged": moved != "waiting",
            "event": CANCELLED if moved == "waiting" else WAITING,
            "effects": 2 if moved == "waiting" else 0}


@pytest.mark.parametrize("moved", ["newer", "queued", "missing", "waiting"])
def test_ended_row_lock_rereads_the_generation_before_permitting_the_event_cancel(moved, monkeypatch):
    assert _ended_reread(parked, moved, monkeypatch) == _reread_expected(moved)


# ── T13-R2/P17, T16 inner predicate, split rollback ───────────────────────────


def _inside_write(module: ModuleType, moved: str, monkeypatch) -> dict:
    """Fixed SQL predicate seam on both tiers. This writer shares the transaction;
    it is not claimed to be a concurrent SQLite commit (the real race is below)."""
    run = f"inside-{moved}"
    status = "running" if moved == "ABA-RR" else WAITING
    _attempt(run)
    _row(run, status, handle="pid-101")
    before = _state(run)
    effects = _effects(module, monkeypatch)
    mutated = row_generation.end_row_if_same_generation
    seen: list[tuple[str, int]] = []

    def cycle(session, execution_id, judged, **kwargs):
        new_status = status if moved in {"ABA1C", "ABA-RR"} else "queued"
        attempts = 2 if moved in {"ABA1C", "ABA-RR"} else 1
        _change(execution_id, status=new_status, attempts=attempts, session=session)
        seen.append((new_status, attempts))
        return mutated(session, execution_id, judged, **kwargs)

    monkeypatch.setattr(row_generation, "end_row_if_same_generation", cycle)
    result = module.cancel_parked(run)
    after = _state(run)
    return {"result": result, "rolled_back": after == before, "effects": len(effects),
            "hook": seen, "event": after["event"]["status"]}


def _inside_expected(moved: str) -> dict:
    status = "running" if moved == "ABA-RR" else WAITING
    return {"result": False, "rolled_back": True, "effects": 0, "event": WAITING,
            "hook": [(status, 2) if moved in {"ABA1C", "ABA-RR"} else ("queued", 1)]}


@pytest.mark.parametrize("moved", ["ABA1C", "ABA-RR", "P17-STATUS"])
def test_t13_p17_t16_the_actual_conditional_update_refuses_changed_status_or_attempts(moved, monkeypatch):
    assert _inside_write(parked, moved, monkeypatch) == _inside_expected(moved)


@pytest.mark.parametrize("status", [WAITING, "running"])
def test_t16_real_second_connection_cycle_is_fenced_or_serialised(status, monkeypatch):
    """ABA1C/ABA-RR: PG commits between read/write; SQLite's writer waits for
    the cancel. Both orders are asserted from committed state, no retry."""
    run = f"real-cycle-{status}"
    _attempt(run)
    _row(run, status, handle="pid-101")
    entered, done = threading.Event(), threading.Event()
    errors: list[str] = []
    observed: list[dict] = []
    thread: threading.Thread | None = None

    def writer() -> None:
        try:
            entered.set()
            _change(run, status=status, attempts=2)
            _attempt(run, name="B1", started=at("10:05:00"))
            observed.append(_state(run))
        except BaseException as exc:  # noqa: BLE001 - main test asserts, no retry
            errors.append(repr(exc))
        finally:
            done.set()

    engine = get_database().engine
    fired = False

    def before_update(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        nonlocal fired, thread
        if (fired or threading.current_thread() is not threading.main_thread()
                or not statement.upper().startswith("UPDATE WORKFLOW_RUNS")):
            return
        fired = True
        thread = threading.Thread(target=writer, name="cycle")
        thread.start()
        assert entered.wait(15)
        if _on_postgres():
            assert done.wait(15)  # another connection really commits before the UPDATE
            assert _state(run)["row"]["attempts"] == 2
        else:
            assert not done.is_set()  # the open event write owns SQLite's writer lock
            assert _state(run)["row"]["attempts"] == 1

    sa_event.listen(engine, "before_cursor_execute", before_update)
    effects = _effects(parked, monkeypatch)
    try:
        result = parked.cancel_parked(run)
    finally:
        sa_event.remove(engine, "before_cursor_execute", before_update)
        if thread is not None:
            thread.join(20)
    assert fired and done.is_set() and errors == []
    assert result is (not _on_postgres())
    state = _state(run)
    assert state["row"]["status"] == status and state["row"]["attempts"] == 2
    assert state["event"]["status"] == (WAITING if _on_postgres() else CANCELLED)
    b1 = get_event(f"B1-{run}")
    assert b1 is not None and b1["status"] == WAITING
    assert observed[0]["event"]["status"] == state["event"]["status"]
    assert len(effects) == (0 if _on_postgres() else 2)
    # A new owner stop judges what is current, not the old generation.
    assert parked.cancel_parked(run) is True
    assert get_event(f"B1-{run}")["status"] == CANCELLED


class _RowFailure(Exception):  # noqa: N818 - the test seam's failure
    pass


def test_a_row_failure_rolls_back_the_cas_and_no_post_effect_happens(monkeypatch):
    run = "cancel-row-failure"
    _attempt(run)
    _row(run, WAITING)
    before = _state(run)
    effects = _effects(parked, monkeypatch)

    def fail(session, execution_id, status, *, judged):
        assert _state(execution_id) == before
        raise _RowFailure

    monkeypatch.setattr(parked, "_end_row_in", fail)
    with pytest.raises(_RowFailure):
        parked.cancel_parked(run)
    assert _state(run) == before and effects == []


def test_a_newer_start_after_the_initial_read_rolls_the_old_cas_back(monkeypatch):
    run = "cancel-superseded"
    _attempt(run)
    read = parked.parked_attempt(run)
    _attempt(run, name="B1", started=at("10:05:00"))
    monkeypatch.setattr(parked, "parked_attempt", lambda eid: read)
    before = _state(run)
    effects = _effects(parked, monkeypatch)
    assert parked.cancel_parked(run) is False
    assert _state(run) == before and effects == []
    assert get_event(f"B1-{run}")["status"] == WAITING


# ── T16e / F-A: the real reaper's let-go cancel, never a fresh stop ──────────


_REAPER_CASES = {
    "CURRENT": ("running", 1),
    "ABA1R-SAMEGEN": (WAITING, 1),
    "ABA1R-SAMEGEN-ORPH": ("orphaned", 1),
    "SAMEGEN-COMPLETED": ("completed", 1),
    "SAMEGEN-CANCELLED": (CANCELLED, 1),
    "ABA1R": ("running", 2),
    "ABA1R-WAITING": (WAITING, 2),
    "ABA1R-ENDED": ("orphaned", 2),
    "NEWLY-QUEUED": ("queued", 1),
    "NEWER-QUEUED": ("queued", 2),
}
_CANCEL_PARKED = parked.cancel_parked


def _reaper_cancel(module: ModuleType, case: str, monkeypatch, *, fresh_tick: bool = False) -> list[dict]:
    """A real tick's single judgment, then a committed interleaving at is_gone.

    F-A waiting is a second real reaper's pre-stop judgment. Other transitions
    commit on a separate connection before cancel begins, on both DB tiers.
    No reaper/cancel/row-fence body is copied or replaced with a success stub.
    """
    from temper_ai.api import caller
    from temper_ai.runner.lanes import PI_LANE

    run = f"letgo-{case}"
    gate_id = f"gate-{run}"
    _attempt(run, note={"path": "talk", "event_id": gate_id, "on_cancel": {
        "mode": "hold", "held": [{"path": "close", "name": "close"}]}})
    _row(run, "running", handle="pid-101")
    with get_session() as session:
        session.exec(sa_update(WorkflowRun).where(col(WorkflowRun.execution_id) == run)
                     .values(spawner_kind="subprocess", cancel_requested=True)
                     .execution_options(synchronize_session=False))
        session.add(Event(id=gate_id, type=EventType.STAGE_STARTED, execution_id=run,
                          status=WAITING, data={"gate": True}, timestamp=at("10:01:00")))
    monkeypatch.setattr(parked, "utcnow", lambda: at("12:44:59"))
    monkeypatch.setattr(row_generation, "utcnow", lambda: at("12:44:59"))
    monkeypatch.setattr(caller, "recorded_cancel_words", lambda eid: "stop while letting go")
    status, attempts = _REAPER_CASES[case]
    attempt_id = f"{'B1' if attempts == 2 else 'A1'}-{run}"
    observations: list[dict] = []
    post: list[dict] = []
    monkeypatch.setattr(parked, "_end_pi_teams", lambda eid: post.append(_state(eid, attempt_id)))
    monkeypatch.setattr(parked, "_hold", lambda eid, *args: post.append(_state(eid, attempt_id)))
    snapshots: list[dict] = []
    moved = False

    class Gone:
        def is_alive(self, handle):
            return False

        def is_gone(self, handle):
            nonlocal moved
            if moved:
                return True
            moved = True
            if case == "ABA1R-SAMEGEN":
                # B read before the flag; A read after it. B frees this same
                # generation to waiting while A is still judging running.
                early = module.Reaper(Gone(), lane=PI_LANE)
                early._process_row({**snapshots[0], "cancel_requested": False})
            elif case != "CURRENT":
                with get_session() as session:
                    session.exec(sa_update(WorkflowRun).where(col(WorkflowRun.execution_id) == run)
                                 .values(status=status, attempts=attempts, spawner_handle="pid-202",
                                         completed_at=(at("10:31:00") if status not in {
                                             "running", WAITING, "queued"} else None))
                                 .execution_options(synchronize_session=False))
                if attempts == 2:
                    _attempt(run, name="B1", started=at("10:05:00"), note={
                        "path": "talk", "event_id": gate_id, "on_cancel": {
                            "mode": "hold", "held": [{"path": "close", "name": "close"}]}})
            return True

    reaper = module.Reaper(Gone(), lane=PI_LANE)
    load = reaper._load_live_rows

    def snapshot():
        rows = load()
        snapshots.extend(rows)
        return rows

    reaper._load_live_rows = snapshot

    def cancel(execution_id, reason=None, *, by="cancel", judged=None):
        before = _state(run, attempt_id)
        before_post = len(post)
        split: list[dict] = []
        end = parked._end_row_in

        def end_observed(session, eid, status, *, judged):
            split.append(_state(run, attempt_id))
            return end(session, eid, status, judged=judged)

        with monkeypatch.context() as inner:
            inner.setattr(parked, "_end_row_in", end_observed)
            with _writes_and_commits() as writes:
                result = _CANCEL_PARKED(execution_id, reason, by=by, judged=judged)
        after = _state(run, attempt_id)
        observations.append({
            "result": result, "event": after["event"]["status"], "row": after["row"]["status"],
            "attempts": after["row"]["attempts"], "row_unchanged": after["row"] == before["row"],
            "all_unchanged": after == before, "row_writes": writes.count("UPDATE workflow_runs"),
            "snapshot": judged == RowGeneration.from_snapshot(snapshots[-1]),
            "reads": len(snapshots), "split_uncommitted": split == [before],
            "effects": len(post) - before_post,
            "effects_committed": all(state == after for state in post[before_post:]),
            "reason": after["event"]["data"].get("cancelled_reason"),
            "gate": get_event(gate_id)["status"],
        })
        return result

    monkeypatch.setattr(parked, "cancel_parked", cancel)
    reaper.tick()
    if fresh_tick:
        reaper.tick()  # genuinely fresh judgment of the newer dead parked box
    return observations


def _reaper_expected(case: str) -> dict:
    status, attempts = _REAPER_CASES[case]
    refused = attempts == 2 or status == "queued"
    ended = not refused and status not in {"running", WAITING}
    return {"result": not refused, "event": WAITING if refused else CANCELLED,
            "row": status if refused or ended else CANCELLED, "attempts": attempts,
            "row_unchanged": refused or ended, "all_unchanged": refused,
            "row_writes": 0 if refused or ended else 1, "snapshot": True, "reads": 1,
            "split_uncommitted": True, "effects": 0 if refused else 2, "effects_committed": True,
            "reason": None if refused else "stop while letting go", "gate": WAITING if refused else "rejected"}


def test_t16e_combined_owner_stop_survives_plain_letgo_and_preserves_ended_rows(monkeypatch):
    """Combined happy path first: real tick/cancel, owner words, gate, teams, hold."""
    for case in ("CURRENT", "ABA1R-SAMEGEN", "ABA1R-SAMEGEN-ORPH"):
        with monkeypatch.context() as patch:
            assert _reaper_cancel(reaper_module, case, patch) == [_reaper_expected(case)]


@pytest.mark.parametrize("round_", [1, 2])
@pytest.mark.parametrize("case", list(_REAPER_CASES))
def test_t16e_immutable_judgment_refuses_stale_or_queued_but_keeps_same_generation(case, round_, monkeypatch):
    assert _reaper_cancel(reaper_module, case, monkeypatch) == [_reaper_expected(case)]


@pytest.mark.parametrize("round_", [1, 2])
def test_t16e_next_fresh_tick_can_cancel_the_newer_dead_parked_generation(round_, monkeypatch):
    first, second = _reaper_cancel(reaper_module, "ABA1R", monkeypatch, fresh_tick=True)
    assert first == _reaper_expected("ABA1R")
    assert second == {**_reaper_expected("CURRENT"), "attempts": 2, "reads": 2}


# ── Actual API and own-box CLI, no real execution ────────────────────────────


def test_api_stop_is_fresh_but_still_refuses_a_queued_attempt(monkeypatch):
    from temper_ai.api import routes
    from temper_ai.api.caller import Caller

    effects = _effects(parked, monkeypatch)
    monkeypatch.setattr(routes, "_state", lambda: SimpleNamespace(running={}))
    monkeypatch.setattr(routes, "_run_is_alive", lambda eid: False)
    monkeypatch.setattr(routes, "_cancel_unclaimed_pi_run", lambda eid: False)
    caller = Caller(name="owner")
    for status, expected in [(WAITING, "cancelled"), ("queued", "cancelling")]:
        run = f"api-fresh-{status}"
        _attempt(run)
        _row(run, status)
        _change(run, status=status, attempts=2)
        response = routes._cancel_run(run, routes.CancelRequest(reason="fresh stop"), caller)
        state = _state(run)
        assert response == {"status": expected, "execution_id": run}
        assert state["event"]["status"] == (CANCELLED if status == WAITING else WAITING)
        assert state["row"]["status"] == (CANCELLED if status == WAITING else "queued")
        assert bool(state["row"]["cancel_requested"]) is (status == "queued")
    assert len(effects) == 2  # only the waiting row's successful cancel


class _Sink:
    enabled = False

    def __init__(self, *args, **kwargs):
        pass

    def cleanup(self, execution_id):
        pass

    def close(self):
        pass


def _own_box(module: ModuleType, case: str, monkeypatch) -> dict:
    from temper_ai.runner import bootstrap, execute, pi_lane
    from temper_ai.spawner import box_guard, box_view

    run = f"own-box-{case}"
    _row(run, "queued", handle="pid-101")
    _change(run, status="queued", attempts=0)
    monkeypatch.setenv("TEMPER_RUN_CONTAINER", "owned-box")
    monkeypatch.setattr(box_view, "check_box", lambda: None)
    monkeypatch.setattr(box_guard, "activate", lambda doc: None)
    monkeypatch.setattr(module, "_unboxed_under_sealed", lambda doc: None)
    monkeypatch.setattr(module, "_box_refused", lambda *args: None)
    monkeypatch.setattr(bootstrap, "bootstrap_runner_context_from_env", lambda **kw: SimpleNamespace(graph_loader=None))
    monkeypatch.setattr(pi_lane, "check_run", lambda *args, **kw: None)
    monkeypatch.setattr(module, "_start_mcp_manager", lambda config: None)
    monkeypatch.setattr(module, "_stop_mcp_manager", lambda: None)
    monkeypatch.setattr(module, "_install_signal_handlers", lambda *args: None)
    for target in ("temper_ai.streaming.RedisChunkNotifier",
                   "temper_ai.observability.jsonl_logger.JsonlNotifier",
                   "temper_ai.observability.webhook_notifier.WebhookNotifier",
                   "temper_ai.observability.composite_notifier.CompositeNotifier"):
        monkeypatch.setattr(target, _Sink)
    snapshots: list[dict] = []

    def execute_fixed(*, cancel_event, **kwargs):
        _attempt(run)
        with get_session() as session:
            row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == run)).one()
            assert (row.status, row.attempts, row.spawner_handle) == ("running", 1, "owned-box")
        if case == "stale":
            _change(run, status="running", attempts=2)
            _attempt(run, name="B1", started=at("10:05:00"))
        elif case in {"waiting", "orphaned"}:
            _change(run, status=case, attempts=1)
        snapshots.append(_state(run, attempt_id=f"B1-{run}" if case == "stale" else None))
        cancel_event.cancel("own-box stop")
        return ExecuteResult(exit_code=0, status=WAITING)

    monkeypatch.setattr(execute, "execute_workflow", execute_fixed)
    effects = _effects(parked, monkeypatch)
    assert module.cmd_run_workflow(argparse.Namespace(execution_id=run, config_dir=None)) == 0
    state = _state(run, attempt_id=f"B1-{run}" if case == "stale" else None)
    return {"event": state["event"]["status"], "row": state["row"]["status"],
            "attempts": state["row"]["attempts"], "unchanged": state == snapshots[0],
            "effects": len(effects)}


def _own_expected(case: str) -> dict:
    return {"event": WAITING if case == "stale" else CANCELLED,
            "row": {"stale": "running", "orphaned": "orphaned"}.get(case, CANCELLED),
            "attempts": 2 if case == "stale" else 1, "unchanged": case == "stale",
            "effects": 0 if case == "stale" else 2}


@pytest.mark.parametrize("case", ["current", "waiting", "orphaned", "stale"])
def test_t16_own_box_carries_the_generation_its_start_wrote_not_a_fresh_read(case, monkeypatch):
    assert _own_box(run_workflow, case, monkeypatch) == _own_expected(case)


# ── Real C1 claim versus cancel, both winners, twice ──────────────────────────


@pytest.mark.parametrize("round_", [1, 2])
@pytest.mark.parametrize("first_action", ["claim", "cancel"])
def test_claim_and_cancel_take_the_same_lock_order_and_exactly_one_wins(
        first_action, round_, decision_lock, monkeypatch):
    run = f"claim-cancel-{first_action}-{round_}"
    a1 = _attempt(run)
    _row(run, WAITING)
    paused, go = threading.Event(), threading.Event()
    holder: dict[str, Any] = {}
    effects = _effects(parked, monkeypatch)

    def pause(session) -> None:
        if threading.current_thread().name == "first":
            holder["pid"] = _backend_pid(session)
            paused.set()
            assert go.wait(15)

    def end(session, execution_id, status, *, judged):
        pause(session)
        return _END_ROW_IN(session, execution_id, status, judged=judged)

    def requeue(session, execution_id, *args, **kwargs):
        pause(session)
        return _QUEUE_RUN_IN(session, execution_id, *args, **kwargs)

    monkeypatch.setattr(parked, "_end_row_in", end)
    monkeypatch.setattr(queue, "queue_run_in", requeue)
    outcome: dict[str, str] = {}

    def ask(action: str) -> None:
        try:
            if action == "claim":
                parked.claim_and_queue(a1, "wf", "/workspaces/ws", None,
                                       start="resume", extra=None, lane=KEEP_LANE)
                outcome[action] = "claimed"
            else:
                outcome[action] = "cancelled" if parked.cancel_parked(run, judged=_judged()) else "refused"
        except AlreadyCarriedOn:
            outcome[action] = "refused"
        except BaseException as exc:  # noqa: BLE001 - reported, never retried
            outcome[action] = repr(exc)

    with _writes_and_commits() as writes:
        first = threading.Thread(target=ask, args=(first_action,), name="first")
        second = threading.Thread(target=ask, args=("cancel" if first_action == "claim" else "claim",), name="second")
        first.start()
        assert paused.wait(15)
        second.start()
        try:
            _wait_until_waiting(decision_lock, holder["pid"])
            assert second.is_alive()
        finally:
            go.set()
            first.join(20)
            second.join(20)
    assert not first.is_alive() and not second.is_alive()
    assert outcome == ({"claim": "claimed", "cancel": "refused"} if first_action == "claim"
                       else {"claim": "refused", "cancel": "cancelled"})
    state = _state(run)
    assert state["event"]["status"] == (CARRIED_ON if first_action == "claim" else CANCELLED)
    assert state["row"]["status"] == ("queued" if first_action == "claim" else CANCELLED)
    assert writes.count("UPDATE workflow_runs") == 1
    assert writes.count("UPDATE events") == 1  # locked fresh-read: the loser writes nothing
    assert len(effects) == (0 if first_action == "claim" else 2)


# ── Bites from real production source; changed known answers required ─────────


def _mutant(module: ModuleType, changes: list[tuple[str, str]], monkeypatch) -> ModuleType:
    source = inspect.getsource(module)
    for old, new in changes:
        assert source.count(old) == 1, f"mutation anchor not unique: {old!r}"
        source = source.replace(old, new)
    mutant = ModuleType(f"{module.__name__}_cancel_bite")
    mutant.__file__ = module.__file__
    monkeypatch.setitem(sys.modules, mutant.__name__, mutant)
    exec(compile(source, str(module.__file__), "exec"), mutant.__dict__)  # noqa: S102
    return mutant


@pytest.mark.parametrize("case", ["ABA1R-SAMEGEN", "ABA1R-SAMEGEN-ORPH"])
def test_b_status_equality_really_loses_the_owner_stop_on_f_a(case, monkeypatch):
    mutant = _mutant(parked, [(
        'if row.attempts != attempts or row.status == "queued":',
        'if row.attempts != attempts or row.status == "queued" or (judged is not None and row.status != judged.status):',
    )], monkeypatch)
    got = _disposition(mutant, case, monkeypatch)
    assert got != _expected(case)
    assert got["result"] is False and got["event"] == WAITING and got["all_unchanged"] is True


@pytest.mark.parametrize("case", ["ABA1R", "ABA1R-WAITING", "ABA1R-ENDED"])
@pytest.mark.parametrize("bite", ["B-ABA-1r", "B-ATTEMPTS-READ", "B-CAS-SPLIT"])
def test_a_judgment_or_transaction_mutation_breaks_its_stale_case(case, bite, monkeypatch):
    changes = {
        "B-ABA-1r": [('row_outcome = _end_row_in(session, execution_id, CANCELLED, judged=judged)',
                       'row_outcome = _end_row_in(session, execution_id, CANCELLED, judged=None)')],
        "B-ATTEMPTS-READ": [('attempts = row.attempts if judged is None else judged.attempts',
                             'attempts = row.attempts')],
        "B-CAS-SPLIT": [('            row_outcome = _end_row_in(',
                           '            session.commit()\n            row_outcome = _end_row_in(')],
    }[bite]
    mutant = _mutant(parked, changes, monkeypatch)
    got = _disposition(mutant, case, monkeypatch)
    assert got != _expected(case)
    assert got["event"] == CANCELLED
    if bite == "B-CAS-SPLIT":
        assert got["result"] is False and got["row_unchanged"] is True
    else:
        assert got["result"] is True


@pytest.mark.parametrize(("bite", "moved"), [
    ("B-ABA-4", "ABA1C"), ("B-ABA-4", "ABA-RR"),
    ("B-ROWCOUNT", "ABA1C"), ("B-ROWCOUNT", "ABA-RR"), ("B11", "P17-STATUS"),
])
def test_sql_guard_mutations_produce_the_declared_wrong_answer_on_both_tiers(bite, moved, monkeypatch):
    changes = {
        "B-ABA-4": [('        col(WorkflowRun.attempts) == judged.attempts,\n', '')],
        "B-ROWCOUNT": [('    return result.rowcount == 1', '    return True')],
        "B11": [('        col(WorkflowRun.status) == judged.status,\n', '')],
    }[bite]
    mutant = _mutant(row_generation, changes, monkeypatch)
    monkeypatch.setattr(row_generation, "end_row_if_same_generation", mutant.end_row_if_same_generation)
    got = _inside_write(parked, moved, monkeypatch)
    assert got != _inside_expected(moved)
    assert got["result"] is True and got["rolled_back"] is False and got["event"] == CANCELLED


@pytest.mark.parametrize("case", ["G-ABA1R", "G-ABA1C", "G-ABA-RR", "ABA1R-SAMEGEN"])
def test_b_never_end_breaks_each_current_twin(case, monkeypatch):
    mutant = _mutant(row_generation, [('    result = session.exec(', '    return False\n    result = session.exec(')], monkeypatch)
    monkeypatch.setattr(row_generation, "end_row_if_same_generation", mutant.end_row_if_same_generation)
    got = _disposition(parked, case, monkeypatch)
    assert got != _expected(case)
    assert got["result"] is False and got["all_unchanged"] is True


@pytest.mark.parametrize("moved", ["newer", "queued"])
def test_the_ended_row_reread_guards_each_bite_their_own_changed_row(moved, monkeypatch):
    old = 'if row is None or row.attempts != attempts or row.status == "queued":'
    new = ('if row is None or row.status == "queued":' if moved == "newer"
           else 'if row is None or row.attempts != attempts:')
    mutant = _mutant(parked, [(old, new)], monkeypatch)
    got = _ended_reread(mutant, moved, monkeypatch)
    assert got != _reread_expected(moved)
    assert got["result"] is True and got["event"] == CANCELLED and got["unchanged"] is False


def test_b_box_own_nojudged_breaks_the_actual_cli_stale_case(monkeypatch):
    mutant = _mutant(run_workflow, [('                          judged=own_generation)',
                                    '                          judged=None)')], monkeypatch)
    got = _own_box(mutant, "stale", monkeypatch)
    assert got != _own_expected("stale")
    assert got["event"] == got["row"] == CANCELLED


@pytest.mark.parametrize("case", ["ABA1R", "ABA1R-WAITING", "ABA1R-ENDED"])
def test_t16e_b_aba_1r_the_final_reaper_call_cannot_drop_its_judged_generation(case, monkeypatch):
    mutant = _mutant(reaper_module, [(
        'by="reaper", judged=judged)', 'by="reaper", judged=None)',
    )], monkeypatch)
    [got] = _reaper_cancel(mutant, case, monkeypatch)
    assert got != _reaper_expected(case)
    assert got["result"] is True and got["event"] == CANCELLED and got["effects"] == 2
    assert got["snapshot"] is False


@pytest.mark.parametrize("case", ["ABA1R-SAMEGEN", "ABA1R-SAMEGEN-ORPH"])
def test_t16e_b_status_equality_loses_a_real_same_generation_owner_stop(case, monkeypatch):
    mutant = _mutant(parked, [(
        'if row.attempts != attempts or row.status == "queued":',
        'if row.attempts != attempts or row.status == "queued" or (judged is not None and row.status != judged.status):',
    )], monkeypatch)
    monkeypatch.setattr(parked, "_end_row_in", mutant._end_row_in)
    [got] = _reaper_cancel(reaper_module, case, monkeypatch)
    assert got != _reaper_expected(case)
    assert got["result"] is False and got["event"] == WAITING and got["all_unchanged"] is True
    assert got["effects"] == 0


@pytest.mark.parametrize("case", ["CURRENT", "ABA1R-SAMEGEN"])
def test_t16e_b_never_end_loses_the_real_current_twins(case, monkeypatch):
    mutant = _mutant(row_generation, [('    return result.rowcount == 1', '    return False')], monkeypatch)
    monkeypatch.setattr(row_generation, "end_row_if_same_generation", mutant.end_row_if_same_generation)
    [got] = _reaper_cancel(reaper_module, case, monkeypatch)
    assert got != _reaper_expected(case)
    assert got["result"] is False and got["event"] == WAITING and got["all_unchanged"] is True
    assert got["effects"] == 0


def test_helper_outcomes_are_explicit_and_do_not_commit(monkeypatch):
    effects = _effects(parked, monkeypatch)
    run = "explicit-disposition"
    _attempt(run)
    _row(run, "orphaned")
    before = _state(run)
    with recorder.deciding_events() as session, _writes_and_commits() as writes:
        assert _END_ROW_IN(session, run, CANCELLED, judged=_judged()) == "already ended"
        assert _END_ROW_IN(session, run, CANCELLED, judged=replace(_judged(), attempts=2)) == "refused"
        assert _END_ROW_IN(session, "absent", CANCELLED, judged=None) == "no box row"
        assert _END_ROW_IN(session, "absent", CANCELLED, judged=_judged()) == "refused"
        assert writes == []
    assert _state(run) == before and effects == []
