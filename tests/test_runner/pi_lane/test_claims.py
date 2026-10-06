"""Each watcher claims only its own lane's runs, and the Pi lane one run at a time.

ADR-M4-01 and -11, SW-40 and SW-55 (docs/pi-lane.md): the main watcher, its reaper and its
restart pass never touch a Pi run; the Pi lane's touch nothing else. The Pi lane claims a
queued Pi run, oldest first, only while no other Pi run is running, parked or claimed; the
others wait, saying so, and never start anywhere else. Cancelling one that waits ends it.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace

import pytest

from temper_ai.cli import watch_queue as wq
from temper_ai.runner.lanes import LANE_KEY, PI_LANE, WAITING_FOR_PI_LANE
from temper_ai.shared.clock import utcnow
from temper_ai.spawner.reaper import CLAIMING, Reaper
from temper_ai.worker_proto import SpawnerKind
from tests.test_runner.pi_lane import support as ls


class _Docker(ls.FakeSpawner):
    """The main watcher's spawner (docker), without Docker."""

    def __init__(self) -> None:
        super().__init__()
        self.kind = SpawnerKind.docker


@pytest.fixture(autouse=True)
def _nothing_told_yet(monkeypatch):
    monkeypatch.setattr(wq, "_TOLD_WAITING", set())


# --- the claims ------------------------------------------------------------------------------


@pytest.mark.parametrize("metadata", [None, {}, {"start": "resume"}])
def test_a_row_with_no_mark_is_the_main_lane_s(metadata):
    ls.make_row("plain", "lane_plain", pi=False)
    ls.set_row("plain", spawner_metadata=metadata)
    assert not ls.pi_lane_claims("plain")
    assert ls.main_claims("plain")


@pytest.mark.parametrize("status,kind,handle", [
    ("running", "subprocess", "4242"),
    ("waiting", "subprocess", "4242"),  # parked at a wait: it still holds the lane
    ("queued", "subprocess", CLAIMING),  # claimed, its box not asked for yet
    ("queued", "subprocess", "4242"),  # handed to its box, not started yet
])
def test_one_pi_run_at_a_time_counting_a_parked_or_claimed_one(status, kind, handle):
    ls.make_row("holder", status=status, spawner_kind=kind, handle=handle)
    ls.make_row("second")
    assert not ls.pi_lane_claims("second")
    assert not ls.main_claims("second"), "a waiting Pi run fell back to the main worker"
    ls.set_row("holder", status="completed")
    assert ls.pi_lane_claims("second")


@pytest.mark.parametrize("ended", ["completed", "failed", "cancelled", "orphaned"])
def test_the_lane_frees_when_its_run_ends_however_it_ends(ended):
    ls.make_row("holder", status="running", spawner_kind="subprocess", handle="4242")
    ls.make_row("second")
    assert not ls.pi_lane_claims("second")
    ls.set_row("holder", status=ended)
    assert ls.pi_lane_claims("second")


def test_an_ordinary_run_never_holds_the_pi_lane():
    ls.make_row("plain", "lane_plain", pi=False, status="running", spawner_kind="docker",
                handle="temper-run-plain")
    ls.make_row("pi")
    assert ls.pi_lane_claims("pi")


def test_a_claim_and_an_unclaim_leave_the_mark_alone():
    ls.make_row("pi", metadata={"start": "resume"})
    assert wq._claim_row("pi", "subprocess", PI_LANE)
    assert ls.row("pi").spawner_metadata == {"start": "resume", LANE_KEY: PI_LANE}
    assert wq._unclaim("pi")
    found = ls.row("pi")
    assert found.spawner_kind is None
    assert found.spawner_metadata == {"start": "resume", LANE_KEY: PI_LANE}


@pytest.mark.parametrize("pi", [True, False])
def test_a_box_s_handle_never_changes_the_row_s_lane(pi):
    """_stamp_handle merges the box's metadata over the row's: the row's own lane stays,
    whatever a handle says."""
    ls.make_row("run", pi=pi, metadata={"start": "fork"})
    assert wq._claim_row("run", "subprocess", PI_LANE if pi else None)
    wq._stamp_handle("run", SimpleNamespace(handle="77", metadata={
        "pid": 77, LANE_KEY: "main" if pi else PI_LANE}))
    found = ls.row("run")
    assert found.spawner_handle == "77"
    assert found.spawner_metadata == (
        {"start": "fork", "pid": 77, LANE_KEY: PI_LANE} if pi else {"start": "fork", "pid": 77})


# --- the watchers' scans ---------------------------------------------------------------------


def test_the_pi_lane_starts_its_oldest_run_and_says_once_that_the_next_one_waits(caplog):
    ls.make_row("late", created_at=utcnow())
    ls.make_row("early", created_at=utcnow() - timedelta(minutes=1))
    ls.make_row("plain", "lane_plain", pi=False)
    fake = ls.FakeSpawner()
    with caplog.at_level(logging.INFO, logger=wq.logger.name):
        assert wq._scan_and_dispatch(fake, PI_LANE) == 1
        assert wq._scan_and_dispatch(fake, PI_LANE) == 0
    assert fake.spawned == ["early"]
    told = [r.getMessage() for r in caplog.records if WAITING_FOR_PI_LANE in r.getMessage()]
    assert told == [f"late is {WAITING_FOR_PI_LANE}: another Pi run holds it"]
    early = ls.row("early")
    assert early.spawner_handle == "4242"
    assert early.spawner_metadata == {"pid": 4242, LANE_KEY: PI_LANE}
    assert ls.row("late").spawner_kind is None and ls.row("plain").spawner_kind is None


def test_the_main_watcher_starts_only_ordinary_runs():
    ls.make_row("pi")
    ls.make_row("plain", "lane_plain", pi=False)
    fake = _Docker()
    assert wq._scan_and_dispatch(fake, None) == 1
    assert fake.spawned == ["plain"]
    assert ls.row("pi").spawner_kind is None


def test_each_lane_s_unclaimed_cancel_ends_only_its_own_runs():
    ls.make_row("pi", cancel_requested=True)
    ls.make_row("plain", "lane_plain", pi=False, cancel_requested=True)
    assert wq._scan_and_dispatch(_Docker(), None) == 0
    assert (ls.row("plain").status, ls.row("pi").status) == ("cancelled", "queued")
    assert wq._scan_and_dispatch(ls.FakeSpawner(), PI_LANE) == 0
    assert ls.row("pi").status == "cancelled"


def test_a_restart_puts_back_only_its_own_lane_s_half_claimed_runs():
    for eid, pi in (("pi", True), ("plain", False)):
        ls.make_row(eid, pi=pi, spawner_kind="subprocess", handle=CLAIMING)
    spawner = SimpleNamespace(kind=SpawnerKind.subprocess)
    assert wq._requeue_stuck_claims(spawner, PI_LANE) == 1
    assert (ls.row("pi").spawner_kind, ls.row("plain").spawner_kind) == (None, "subprocess")
    assert wq._requeue_stuck_claims(spawner, None) == 1
    assert ls.row("plain").spawner_kind is None


def test_each_reaper_looks_only_at_its_own_lane_s_runs():
    from temper_ai.runner.pi_lane import _GoneSpawner

    for eid, pi in (("pi", True), ("plain", False)):
        ls.make_row(eid, pi=pi, status="running", spawner_kind="subprocess", handle="4242")
    Reaper(_GoneSpawner(), lane=PI_LANE).tick()
    assert (ls.row("pi").status, ls.row("plain").status) == ("orphaned", "running")
    Reaper(_GoneSpawner()).tick()
    assert ls.row("plain").status == "orphaned"


# --- what the owner sees ---------------------------------------------------------------------


def test_the_run_page_says_a_queued_pi_run_waits_for_the_pi_lane(srv):
    from temper_ai.api import routes

    ls.make_row("pi")
    ls.make_row("plain", "lane_plain", pi=False)
    ls.make_row("claimed", spawner_kind="subprocess", handle=CLAIMING)
    found = srv.client.get("/api/workflows/pi").json()
    assert (found["status"], found["queued_reason"]) == ("queued", WAITING_FOR_PI_LANE)
    assert "queued_reason" not in routes.get_workflow("plain")
    assert "queued_reason" not in routes.get_workflow("claimed")


def test_a_resumed_pi_run_waiting_for_the_lane_says_so_in_any_server_mode(srv, monkeypatch):
    """The events say how the attempt before ended; the row says it's queued again."""
    from temper_ai.api import routes

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    ls.make_row("pi", metadata={"start": "resume"})
    monkeypatch.setattr(routes, "get_workflow_execution", lambda eid: {
        "id": eid, "workflow_name": "lane_pi", "status": "failed"})
    found = routes.get_workflow("pi")
    assert (found["status"], found["queued_reason"]) == ("queued", WAITING_FOR_PI_LANE)


def test_cancelling_a_pi_run_that_waits_for_the_lane_ends_it_at_once(srv):
    ls.make_row("pi")
    r = srv.client.post("/api/runs/pi/cancel", json={"reason": "not now"})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "cancelled", "execution_id": "pi"}
    found = ls.row("pi")
    assert found.status == "cancelled" and found.completed_at is not None
    assert not ls.pi_lane_claims("pi")


def test_a_cancel_between_the_lane_s_scan_and_its_claim_wins(srv, monkeypatch):
    """The Pi lane read the row as queued; the server ended it before the claim: no box."""
    ls.make_row("pi")
    real_load = wq._load_queued

    def load_then_cancel(lane=None):
        rows = real_load(lane)
        assert srv.client.post("/api/runs/pi/cancel", json={}).json()["status"] == "cancelled"
        return rows

    monkeypatch.setattr(wq, "_load_queued", load_then_cancel)
    fake = ls.FakeSpawner()
    assert wq._scan_and_dispatch(fake, PI_LANE) == 0
    assert fake.spawned == []
    found = ls.row("pi")
    assert (found.status, found.spawner_kind) == ("cancelled", None)


@pytest.mark.parametrize("eid,pi,kind", [("plain", False, None),
                                         ("claimed", True, "subprocess")])
def test_a_cancel_of_any_other_queued_run_goes_the_usual_way(srv, eid, pi, kind):
    """An ordinary queued run, or a Pi run the lane has claimed: its watcher or its box
    ends it (cancel_requested), as before."""
    ls.make_row(eid, "lane_pi" if pi else "lane_plain", pi=pi, spawner_kind=kind,
                handle=CLAIMING if kind else None)
    r = srv.client.post(f"/api/runs/{eid}/cancel", json={})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "cancelling", "execution_id": eid}
    found = ls.row(eid)
    assert (found.status, found.cancel_requested) == ("queued", True)
