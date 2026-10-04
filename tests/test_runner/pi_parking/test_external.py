"""Pi runs in external mode: each attempt runs in its own box (``temper run-workflow``). At an
approval the box exits; the worker's reaper sees it gone and frees the run; the answer queues
the next box through Resume's own path (temper_ai/runner/parked.py)."""

from __future__ import annotations

import argparse
import threading
from datetime import timedelta

import pytest

from temper_ai.shared.clock import utcnow
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw


class _GoneBoxes:
    """The docker spawner, as the reaper sees it once a run's box has exited and been removed."""

    def is_alive(self, handle) -> bool:
        return False

    def is_gone(self, handle) -> bool:
        return True


@pytest.fixture
def ext(pw_run, monkeypatch):
    from temper_ai.runner.context import RunnerContext

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    st = pw_run.state
    ctx = RunnerContext(config_store=st.config_store, graph_loader=st.graph_loader,
                        llm_providers=st.llm_providers, memory_service=st.memory_service)
    monkeypatch.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env",
                        lambda config_dir=None: ctx)
    monkeypatch.setattr("temper_ai.cli.run_workflow._start_mcp_manager", lambda config_dir: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._stop_mcp_manager", lambda: None)
    # Signals stay pytest's: the box's handlers only matter in a real box.
    monkeypatch.setattr("temper_ai.cli.run_workflow._install_signal_handlers", lambda *a: None)
    return pw_run


def _row(eid: str) -> dict:
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == eid)).one()
        return {"status": row.status, "meta": dict(row.spawner_metadata or {}),
                "cancel_requested": row.cancel_requested}


def _box(ext, eid: str, monkeypatch, *, finish_pi: bool = False) -> int:
    """One box for the run, as the worker starts it: claim the queued row, run to the end."""
    from temper_ai.cli.run_workflow import cmd_run_workflow
    from temper_ai.cli.watch_queue import _claim_row

    assert _row(eid)["status"] == "queued"
    assert _claim_row(eid, spawner_kind="docker")
    monkeypatch.setenv("TEMPER_RUN_CONTAINER", f"temper-run-{eid}")
    helper = None
    if finish_pi:
        helper = threading.Thread(target=pw.finish_pi, args=(ext.client, eid), daemon=True)
        helper.start()
    code = cmd_run_workflow(argparse.Namespace(execution_id=eid, config_dir=None, debug=False))
    if helper is not None:
        helper.join(timeout=20)
    return code


def _reaper():
    from temper_ai.spawner.reaper import Reaper

    return Reaper(_GoneBoxes(), interval_seconds=60)  # type: ignore[arg-type]


def test_the_box_exits_at_the_approval_and_the_answer_queues_the_next_one(ext, monkeypatch):
    c = ext.client
    eid = sup.start(c, "pw_before_pi", ext.ws)
    assert _box(ext, eid, monkeypatch) == 0
    attempt = pw.attempts(eid)[-1]
    assert attempt["status"] == "waiting" and pw.parked(attempt)["path"] == "check"
    # The box left its row as it was: the reaper, seeing the box gone, frees the run.
    assert _row(eid)["status"] == "running"
    _reaper().tick()
    assert _row(eid)["status"] == "waiting"
    _reaper().tick()  # nothing more to do: no answer yet
    assert _row(eid)["status"] == "waiting" and len(pw.attempts(eid)) == 1
    assert pw.detail(c, eid)["status"] == "waiting"
    assert pw.listed(c, eid)["status"] == "waiting"

    gate = pw.open_gate(c, eid, "check")
    r = pw.approve(c, eid, "check", event_id=gate["event_id"], request_id="tab-1")
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    row = _row(eid)
    assert row["status"] == "queued" and row["meta"].get("start") == "resume"
    again = pw.approve(c, eid, "check", event_id=gate["event_id"], request_id="tab-2")
    assert again.status_code == 409 and again.json()["detail"]["reason"] == "already_answered"

    assert _box(ext, eid, monkeypatch, finish_pi=True) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "completed"]
    assert _row(eid)["status"] == "completed"
    assert pw.RAN == {"brief": 1, "check": 1} and len(FakeBox.STARTS) == 1


def test_an_answer_while_the_worker_is_down_carries_on_when_it_is_back(ext, monkeypatch):
    """The box let go, the worker (and its reaper) are down; the answer goes in. When the
    worker is back its reaper frees the run and carries it on with that answer."""
    from temper_ai.observability.reconcile import reconcile_and_report

    c = ext.client
    eid = sup.start(c, "pw_before_pi", ext.ws)
    _box(ext, eid, monkeypatch)
    gate = pw.open_gate(c, eid, "check")
    r = pw.approve(c, eid, "check", event_id=gate["event_id"])
    assert r.status_code == 200, r.text
    # The reply says so: the worker carries it on when it is back (and the same goes for an
    # answer in the few seconds before the reaper sees a box gone).
    assert r.json()["carries_on"] is True and r.json()["needs_resume"] is False, r.text
    assert _row(eid)["status"] == "running" and len(pw.attempts(eid)) == 1

    # A server restart meanwhile marks nothing interrupted.
    assert eid not in [m["execution_id"] for m in reconcile_and_report(started_before=utcnow())]
    _reaper().tick()
    row = _row(eid)
    assert row["status"] == "queued" and row["meta"].get("start") == "resume"
    _reaper().tick()  # a queued row with no box yet is the queue's, not the reaper's
    assert _box(ext, eid, monkeypatch, finish_pi=True) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "completed"]
    assert pw.RAN == {"brief": 1, "check": 1}


def test_a_first_node_wait_in_a_box_resumes_without_a_checkpoint(ext, monkeypatch):
    c = ext.client
    eid = sup.start(c, "pw_first", ext.ws)
    _box(ext, eid, monkeypatch)
    _reaper().tick()
    asked = pw.open_gate(c, eid, "ask")
    r = c.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200 and r.json()["status"] == "queued", r.text
    # A second Resume while that box is queued is refused: never two boxes.
    assert c.post(f"/api/runs/{eid}/resume", json={}).status_code == 409
    _box(ext, eid, monkeypatch)
    _reaper().tick()
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "waiting"]
    assert len(pw.waits(eid, "ask")) == 1
    r = pw.approve(c, eid, "ask", event_id=asked["event_id"])
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    assert _box(ext, eid, monkeypatch, finish_pi=True) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "parked", "completed"]
    assert pw.RAN == {"ask": 1, "audit": 1}


def test_cancel_a_parked_run_whose_box_is_gone(ext, monkeypatch):
    c = ext.client
    eid = sup.start(c, "pw_before_pi", ext.ws)
    _box(ext, eid, monkeypatch)
    _reaper().tick()
    r = c.post(f"/api/runs/{eid}/cancel", json={"reason": "no longer needed"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    assert _row(eid)["status"] == "cancelled"
    assert [a["status"] for a in pw.attempts(eid)] == ["cancelled"]
    assert pw.waits(eid, "check")[0]["status"] == "rejected"
    _reaper().tick()
    assert _row(eid)["status"] == "cancelled" and len(pw.attempts(eid)) == 1


def test_cancel_while_the_box_is_letting_go_ends_it_once_the_box_is_gone(ext, monkeypatch):
    c = ext.client
    eid = sup.start(c, "pw_before_pi", ext.ws)
    _box(ext, eid, monkeypatch)
    # The reaper has not seen the box go yet: the row still says running.
    r = c.post(f"/api/runs/{eid}/cancel", json={})
    assert r.status_code == 200 and r.json()["status"] == "cancelling", r.text
    _reaper().tick()
    assert _row(eid)["status"] == "cancelled"
    assert [a["status"] for a in pw.attempts(eid)] == ["cancelled"]
    gate = pw.waits(eid, "check")[0]
    assert pw.approve(c, eid, "check", event_id=gate["id"]).status_code in (404, 409)


def test_a_box_wait_of_days_is_left_alone_by_restarts_and_pick_up(ext, monkeypatch):
    from temper_ai.observability.reconcile import reconcile_and_report
    from temper_ai.runner import parked

    c = ext.client
    eid = sup.start(c, "pw_before_pi", ext.ws)
    _box(ext, eid, monkeypatch)
    _reaper().tick()
    from tests.test_runner.pi_parking.test_in_process import _age

    _age(eid, timedelta(days=4))
    marked = reconcile_and_report(started_before=utcnow())
    assert eid not in [m["execution_id"] for m in marked]
    assert eid not in str(sup.restart_service(now=utcnow(), marked=marked))
    assert parked.carry_on_at_startup() == []
    _reaper().tick()
    assert _row(eid)["status"] == "waiting" and len(pw.attempts(eid)) == 1
    gate = pw.open_gate(c, eid, "check")
    assert pw.approve(c, eid, "check", event_id=gate["event_id"]).json()["carries_on"] is True
    assert _box(ext, eid, monkeypatch, finish_pi=True) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "completed"]
