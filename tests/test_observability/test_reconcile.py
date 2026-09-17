"""Runs interrupted by a restart are marked, and nothing else is touched.

The risk in this feature is not failing to mark an orphan — it is marking a
run that is actually alive. Most of these tests are about what it must leave
alone.
"""

import datetime as dt

import pytest

from temper_ai.database.session import get_session
from temper_ai.observability.models import Event
from temper_ai.observability.reconcile import reconcile_interrupted_runs


def _run(session, *, status: str, minutes_ago: int, etype: str = "workflow.started") -> str:
    ev = Event(
        id=f"ev-{status}-{minutes_ago}-{etype}",
        type=etype,
        execution_id=f"run-{status}-{minutes_ago}-{etype}",
        status=status,
        data={},
        timestamp=dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(minutes=minutes_ago),
    )
    session.add(ev)
    return ev.id


@pytest.fixture
def now():
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def test_marks_a_run_left_running_by_a_previous_process(now):
    with get_session() as s:
        eid = _run(s, status="running", minutes_ago=30)
        s.commit()

    assert reconcile_interrupted_runs(started_before=now) == 1

    with get_session() as s:
        ev = s.get(Event, eid)
        assert ev.status == "interrupted"
        assert "restarted" in ev.data["error"]


def test_leaves_finished_runs_alone(now):
    with get_session() as s:
        ids = [
            _run(s, status="completed", minutes_ago=30),
            _run(s, status="failed", minutes_ago=31),
            _run(s, status="cancelled", minutes_ago=32),
        ]
        s.commit()

    reconcile_interrupted_runs(started_before=now)

    with get_session() as s:
        assert [s.get(Event, i).status for i in ids] == ["completed", "failed", "cancelled"]


def test_leaves_runs_started_by_this_process_alone(now):
    """A run newer than the process start is live work, not an orphan."""
    with get_session() as s:
        eid = _run(s, status="running", minutes_ago=0)
        s.commit()

    # Cutoff an hour ago: this run started after it.
    reconcile_interrupted_runs(started_before=now - dt.timedelta(hours=1))

    with get_session() as s:
        assert s.get(Event, eid).status == "running"


def test_ignores_events_that_are_not_runs(now):
    with get_session() as s:
        eid = _run(s, status="running", minutes_ago=30, etype="agent.started")
        s.commit()

    reconcile_interrupted_runs(started_before=now)

    with get_session() as s:
        assert s.get(Event, eid).status == "running"


def test_does_nothing_with_an_external_worker(now, monkeypatch):
    """The worker outlives this process; its runs are not ours to bury."""
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    with get_session() as s:
        eid = _run(s, status="running", minutes_ago=30)
        s.commit()

    assert reconcile_interrupted_runs(started_before=now) == 0

    with get_session() as s:
        assert s.get(Event, eid).status == "running"


def test_can_be_switched_off(now, monkeypatch):
    monkeypatch.setenv("TEMPER_RECONCILE_ORPHANS", "0")
    with get_session() as s:
        eid = _run(s, status="running", minutes_ago=30)
        s.commit()

    assert reconcile_interrupted_runs(started_before=now) == 0

    with get_session() as s:
        assert s.get(Event, eid).status == "running"
