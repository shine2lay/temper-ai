"""The Pi lane stopping and starting again, end to end (item 8, ADR-M4-06, SW-49, SW-16).

Each attempt runs as pi-worker runs it: claimed by the Pi lane, ``temper run-workflow`` in
external mode, the commit it ran on recorded on its row. A drain lets a run leave before
its next turn; a stop mid-turn leaves the turn running in the ledger. Either way the Pi
lane's next start ends the run and carries it on from the ledger, and an uncertain turn
becomes a recovery wait, never a second model call.
"""

from __future__ import annotations

import argparse

import pytest

from temper_ai.runner import pi_lane
from temper_ai.runner.lanes import LANE_RECORD_KEY, PI_LANE
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_lane import support as ls
from tests.test_runner.pi_lane.test_drain import Docker
from tests.test_runner.pi_parking import support as pw


class _Killed(BaseException):  # noqa: N818 - the process dying, not an error
    """The run process killed mid-turn: no handler of the run sees it."""


@pytest.fixture
def lane(pw_run, monkeypatch, tmp_path):
    """pi-worker's run processes, in this process (no box, no MCP, pytest's signals)."""
    from temper_ai.pi_agent.host import PiHost
    from temper_ai.runner.context import RunnerContext

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    monkeypatch.setenv(pi_lane.DRAIN_MARK_ENV, str(tmp_path / "drain" / "draining"))
    st = pw_run.state
    ctx = RunnerContext(config_store=st.config_store, graph_loader=st.graph_loader,
                        llm_providers=st.llm_providers, memory_service=st.memory_service)
    monkeypatch.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env",
                        lambda config_dir=None: ctx)
    monkeypatch.setattr("temper_ai.cli.run_workflow._start_mcp_manager", lambda config_dir: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._stop_mcp_manager", lambda: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._install_signal_handlers", lambda *a: None)
    monkeypatch.setattr(pi_lane, "read_commit", lambda root=None: ("5" * 40, ""))
    ls.give_accounts(monkeypatch, tmp_path / "settings")
    stopped: list[str] = []

    def stop_box(name):
        stopped.append(name)
        return {"box": name, "confirmed": True}

    monkeypatch.setattr(PiHost, "stop_box", stop_box)
    monkeypatch.setitem(sup.WORKFLOWS, "lane_pi", ls.WORKFLOWS["lane_pi"])
    pw_run.stopped = stopped
    return pw_run


def _attempt(eid: str, monkeypatch) -> int:
    """pi-worker's watcher claims the run and starts its run process."""
    from temper_ai.cli.run_workflow import cmd_run_workflow
    from temper_ai.cli.watch_queue import _claim_row

    assert ls.row(eid).status == "queued"
    from tests.test_runner.resume_support import install_launch_token
    install_launch_token(eid, monkeypatch, lane=PI_LANE)
    assert not _claim_row(eid, "docker"), "the main watcher claimed a Pi run"
    assert _claim_row(eid, "subprocess", PI_LANE)
    monkeypatch.setenv("TEMPER_RUN_CONTAINER", f"temper-run-{eid}")
    return cmd_run_workflow(argparse.Namespace(execution_id=eid, config_dir=None, debug=False))


def _commits(eid: str) -> list[str]:
    meta = ls.row(eid).spawner_metadata or {}
    return [c["start"] for c in (meta.get(LANE_RECORD_KEY) or {}).get("commits", [])]


def _turns(eid: str) -> list[dict]:
    return sup.ledger().snapshot(eid)["turns"]


def _lane_status() -> dict:
    from temper_ai.database import get_database

    return pi_lane.lane_status(get_database().engine)


def test_a_drain_leaves_before_the_turn_and_the_next_start_carries_the_run_on(lane,
                                                                              monkeypatch):
    eid = sup.start(lane.client, "lane_pi", lane.ws)
    pi_lane.set_draining()  # docker stop: the lane drains before this run's first turn
    assert _attempt(eid, monkeypatch) == pi_lane.DRAINED_EXIT
    row = ls.row(eid)
    assert row.status == "orphaned" and row.error["kind"] == "drained"
    assert row.error["message"].startswith("The Pi lane stopped; the run left at a turn "
                                           "boundary (Pi step talk)")
    assert [a["status"] for a in pw.attempts(eid)] == ["interrupted"]
    assert FakeBox.STARTS == [] and _turns(eid) == []
    assert _commits(eid) == ["new"]

    pi_lane.arm_drain_mark()  # the next start: no mark left over
    out = pi_lane.start_up(docker=Docker([]))
    assert out["picked_up"] == [eid]
    again = ls.row(eid)
    assert again.status == "queued" and again.spawner_metadata.get("start") == "resume"
    assert ls.lane(eid) == PI_LANE
    assert _lane_status()["queued"] == [{"run_id": eid}]

    assert _attempt(eid, monkeypatch) == 0
    assert len(FakeBox.STARTS) == 1, "the turn ran once, in the attempt after the drain"
    assert [t["state"] for t in _turns(eid)] == ["completed"]
    # After its turn the Pi step asks its owner (C7): the attempt lets go there.
    assert [a["status"] for a in pw.attempts(eid)] == ["interrupted", "waiting"]
    assert [w["kind"] for w in sup.ledger().snapshot(eid)["waits"]] == ["owner"]
    assert _commits(eid) == ["new", "resume"]


def test_a_turn_cut_off_by_a_stop_becomes_a_recovery_wait_at_the_next_start(lane,
                                                                           monkeypatch):
    eid = sup.start(lane.client, "lane_pi", lane.ws)

    def die(box) -> None:
        raise _Killed()

    FakeBox.on_prompt = die
    try:
        with pytest.raises(_Killed):
            _attempt(eid, monkeypatch)
    finally:
        FakeBox.on_prompt = None
    [cut] = _turns(eid)
    assert cut["state"] == "running" and ls.row(eid).status == "running"
    assert _lane_status()["active"] == [{"run_id": eid, "why": pi_lane.TURN_RUNNING}]

    out = pi_lane.start_up(docker=Docker([]))
    assert out["picked_up"] == [eid]
    assert ls.row(eid).status == "queued" and ls.lane(eid) == PI_LANE

    assert _attempt(eid, monkeypatch) == 0
    [turn] = _turns(eid)
    assert turn["state"] == "uncertain", "the cut-off turn is never sent again"
    assert len(FakeBox.STARTS) == 1
    assert lane.stopped == [cut["box_name"]], "its box confirmed gone, by exact name"
    waits = sup.ledger().snapshot(eid)["waits"]
    assert [(w["kind"], w["state"]) for w in waits] == [("recovery", "open")]
    assert pw.attempts(eid)[-1]["status"] == "waiting"
    assert _commits(eid) == ["new", "resume"]

    from tests.test_runner.pi_parking.test_external import _reaper

    _reaper().tick()  # the run process left at the wait: the lane lets the run go
    assert ls.row(eid).status == "waiting"
    status = _lane_status()
    assert status["active"] == [] and status["parked"] == [{"run_id": eid,
                                                            "waiting_on": "recovery"}]
