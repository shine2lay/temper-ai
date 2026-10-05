"""A step that asks the owner from inside its own work, in a Pi workflow in external mode:
each attempt runs in its own box (``temper run-workflow``); where the step asks, the box exits,
the worker's reaper frees the run, and the answer queues the next box through Resume's path.
The step runs again in the new box and reads its answer (temper_ai/stage/step_waits.py)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from temper_ai.shared.clock import utcnow
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import step_support as ask
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking.test_external import _box, _reaper, _row
from tests.test_runner.pi_parking.test_in_process import _age


@pytest.fixture
def swx(pw_run, monkeypatch):
    """External mode, as test_external.py's ``ext``, with the asking step known."""
    from temper_ai.runner.context import RunnerContext

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    st = pw_run.state
    ctx = RunnerContext(config_store=st.config_store, graph_loader=st.graph_loader,
                        llm_providers=st.llm_providers, memory_service=st.memory_service)
    monkeypatch.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env",
                        lambda config_dir=None: ctx)
    monkeypatch.setattr("temper_ai.cli.run_workflow._start_mcp_manager", lambda config_dir: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._stop_mcp_manager", lambda: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._install_signal_handlers", lambda *a: None)
    ask.install(monkeypatch, pw_run.tmp)
    pw_run.before = ask.threads_now()
    return pw_run


def _let_go(swx, eid: str, path: str, n_round: int, test: str, *, attempt: int) -> dict:
    """The box let go where the step at ``path`` asked after round ``n_round``: the reaper
    frees the run and nothing holds it. Returns the wait as GET .../gates lists it."""
    last = pw.attempts(eid)[-1]
    note = pw.parked(last)
    assert last["status"] == "waiting" and note["path"] == path
    assert note["wait_id"] == ask.wait_id(n_round)
    # The box left its row as it was: the reaper, seeing the box gone, frees the run.
    assert _row(eid)["status"] == "running"
    _reaper().tick()
    assert _row(eid)["status"] == "waiting"
    wait = pw.open_gate(swx.client, eid, ask.name_of(path, n_round))
    assert note["event_id"] == wait["event_id"]
    counts = ask.held(swx.state, eid, before=swx.before, test=test, mode="external",
                      attempt=attempt, wait_id=note["wait_id"], row=_row(eid)["status"])
    assert ask.nothing_held(counts), counts
    return wait


def test_the_box_exits_where_the_step_asks_and_the_answer_queues_the_next_one(swx, monkeypatch):
    c = swx.client
    eid = sup.start(c, "sw_after_pi", swx.ws)
    assert _box(swx, eid, monkeypatch, finish_pi=True) == 0
    wait = _let_go(swx, eid, "ask", 1, "box_exits", attempt=2)
    assert [cp["id"] for cp in ask.checkpoints(c, eid, "step_parked")] == [wait["event_id"]]
    _reaper().tick()  # nothing more to do: no answer yet
    assert _row(eid)["status"] == "waiting" and len(pw.attempts(eid)) == 2
    seen = pw.detail(c, eid)
    assert seen["status"] == "waiting" and seen.get("waiting_on_you") is True
    assert pw.listed(c, eid)["status"] == "waiting"

    r = pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"], request_id="tab-1")
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    row = _row(eid)
    assert row["status"] == "queued" and row["meta"].get("start") == "resume"
    again = pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"], request_id="tab-2")
    assert again.status_code == 409 and again.json()["detail"]["reason"] == "already_answered"
    repeat = pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"], request_id="tab-1")
    assert repeat.status_code == 200 and repeat.json()["repeated"] is True, repeat.text

    assert _box(swx, eid, monkeypatch) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "parked", "completed"]
    assert _row(eid)["status"] == "completed"
    assert ask.RUNS["ask"] == 2 and ask.WORK == {("ask", 1): 1}
    assert ask.READ == [("ask", "pause-after-round-1", "go on")]
    assert pw.RAN == {"brief": 1, "ship": 1} and len(FakeBox.STARTS) == 1


def test_each_round_lets_go_in_its_own_box_with_its_own_checkpoint(swx, monkeypatch):
    c = swx.client
    eid = sup.start(c, "sw_rounds", swx.ws)
    assert _box(swx, eid, monkeypatch, finish_pi=True) == 0
    first = _let_go(swx, eid, "ask", 1, "box_rounds", attempt=2)
    assert pw.approve(c, eid, ask.name_of("ask", 1),
                      event_id=first["event_id"]).json()["carries_on"] is True
    assert _box(swx, eid, monkeypatch) == 0
    second = _let_go(swx, eid, "ask", 2, "box_rounds", attempt=3)
    stale = pw.approve(c, eid, ask.name_of("ask", 1), event_id=first["event_id"],
                       request_id="old-tab")
    assert stale.status_code == 409 and stale.json()["detail"]["reason"] == "already_answered"
    assert [cp["id"] for cp in ask.checkpoints(c, eid, "step_parked")] == [first["event_id"],
                                                                         second["event_id"]]
    assert pw.approve(c, eid, ask.name_of("ask", 2),
                      event_id=second["event_id"]).json()["carries_on"] is True
    assert _box(swx, eid, monkeypatch) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked"] * 3 + ["completed"]
    assert ask.RUNS["ask"] == 3 and ask.WORK == {("ask", 1): 1, ("ask", 2): 1}
    assert pw.RAN == {"brief": 1, "ship": 1} and len(FakeBox.STARTS) == 1


def test_a_first_step_asking_in_a_box_survives_worker_and_server_restarts(swx, monkeypatch):
    from temper_ai.observability.reconcile import reconcile_and_report
    from temper_ai.runner import parked

    c = swx.client
    eid = sup.start(c, "sw_first", swx.ws)
    assert _box(swx, eid, monkeypatch) == 0
    asked = _let_go(swx, eid, "ask", 1, "box_first_position_restarts", attempt=1)
    assert pw.RAN == {} and FakeBox.STARTS == []

    # Worker restarts: each new worker's reaper finds the run waiting, and leaves it so.
    for _restart in range(2):
        _reaper().tick()
        assert _row(eid)["status"] == "waiting" and len(pw.attempts(eid)) == 1
    # Server restarts: nothing marked interrupted, picked up, or carried on.
    _age(eid, timedelta(days=2))
    marked = reconcile_and_report(started_before=utcnow())
    assert eid not in [m["execution_id"] for m in marked]
    assert eid not in str(sup.restart_service(now=utcnow(), marked=marked))
    assert parked.carry_on_at_startup() == []
    assert _row(eid)["status"] == "waiting" and len(pw.attempts(eid)) == 1

    # The answer queues the next box; the worker takes it whenever it is back.
    r = pw.approve(c, eid, ask.name_of("ask"), event_id=asked["event_id"])
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    assert r.json()["needs_resume"] is False
    row = _row(eid)
    assert row["status"] == "queued" and row["meta"].get("start") == "resume"
    assert _box(swx, eid, monkeypatch, finish_pi=True) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "parked", "completed"]
    assert ask.RUNS["ask"] == 2 and ask.READ == [("ask", "pause-after-round-1", "go on")]
    assert pw.RAN == {"audit": 1} and len(FakeBox.STARTS) == 1


def test_an_answer_while_the_worker_is_down_carries_on_when_it_is_back(swx, monkeypatch):
    """The box let go and the worker (with its reaper) is down when the answer goes in. When
    the worker is back its reaper frees the run and carries it on with that answer."""
    from temper_ai.observability.reconcile import reconcile_and_report

    c = swx.client
    eid = sup.start(c, "sw_after_pi", swx.ws)
    assert _box(swx, eid, monkeypatch, finish_pi=True) == 0
    wait = pw.open_gate(c, eid, ask.name_of("ask"))
    r = pw.approve(c, eid, ask.name_of("ask"), event_id=wait["event_id"])
    assert r.status_code == 200, r.text
    assert r.json()["carries_on"] is True and r.json()["needs_resume"] is False, r.text
    assert _row(eid)["status"] == "running" and len(pw.attempts(eid)) == 2
    assert eid not in [m["execution_id"] for m in reconcile_and_report(started_before=utcnow())]

    _reaper().tick()
    row = _row(eid)
    assert row["status"] == "queued" and row["meta"].get("start") == "resume"
    _reaper().tick()  # a queued row with no box yet is the queue's, not the reaper's
    assert _box(swx, eid, monkeypatch) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "parked", "completed"]
    assert ask.RUNS["ask"] == 2 and ask.READ == [("ask", "pause-after-round-1", "go on")]


def test_cancel_a_step_wait_whose_box_is_gone(swx, monkeypatch):
    c = swx.client
    eid = sup.start(c, "sw_after_pi", swx.ws)
    _box(swx, eid, monkeypatch, finish_pi=True)
    _reaper().tick()
    r = c.post(f"/api/runs/{eid}/cancel", json={"reason": "no longer needed"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    assert _row(eid)["status"] == "cancelled"
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "cancelled"]
    assert ask.step_waits(eid, "ask")[0]["status"] == "rejected"
    _reaper().tick()
    assert _row(eid)["status"] == "cancelled" and len(pw.attempts(eid)) == 2
    assert ask.RUNS["ask"] == 1 and pw.RAN == {"brief": 1}


def test_reject_while_the_box_is_letting_go_ends_it_once_the_box_is_gone(swx, monkeypatch):
    from temper_ai.integrations.slack.ops import TemperOps

    c = swx.client
    eid = sup.start(c, "sw_after_pi", swx.ws)
    _box(swx, eid, monkeypatch, finish_pi=True)
    # The reaper has not seen the box go yet: the row still says running.
    out = TemperOps().cancel(eid, "Rejected in Slack by Owner", by="Owner (Slack)")
    assert out["status"] == "cancelling", out
    _reaper().tick()
    assert _row(eid)["status"] == "cancelled"
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "cancelled"]
    (asked,) = ask.step_waits(eid, "ask")
    assert asked["status"] == "rejected"
    assert "Rejected in Slack by Owner" in str(asked["data"].get("gate_response"))
    late = pw.approve(c, eid, ask.name_of("ask"), event_id=asked["id"])
    assert late.status_code in (404, 409)


def test_a_step_in_a_stage_waits_days_in_boxes_and_carries_on(swx, monkeypatch):
    """The team stage's shape, two rounds, a box each; days pass at the first wait."""
    from temper_ai.observability.reconcile import reconcile_and_report
    from temper_ai.runner import parked

    c = swx.client
    eid = sup.start(c, "sw_stage", swx.ws)
    assert _box(swx, eid, monkeypatch, finish_pi=True) == 0
    first = _let_go(swx, eid, "team.asker", 1, "box_stage_days", attempt=2)
    _age(eid, timedelta(days=4))
    marked = reconcile_and_report(started_before=utcnow())
    assert eid not in [m["execution_id"] for m in marked]
    assert eid not in str(sup.restart_service(now=utcnow(), marked=marked))
    assert parked.carry_on_at_startup() == []
    _reaper().tick()
    assert _row(eid)["status"] == "waiting" and len(pw.attempts(eid)) == 2

    assert pw.approve(c, eid, ask.name_of("team.asker", 1),
                      event_id=first["event_id"]).json()["carries_on"] is True
    assert _box(swx, eid, monkeypatch) == 0
    second = _let_go(swx, eid, "team.asker", 2, "box_stage_days", attempt=3)
    assert pw.approve(c, eid, ask.name_of("team.asker", 2),
                      event_id=second["event_id"]).json()["carries_on"] is True
    assert _box(swx, eid, monkeypatch) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked"] * 3 + ["completed"]
    assert ask.RUNS["asker"] == 3 and ask.WORK == {("asker", 1): 1, ("asker", 2): 1}
    assert pw.RAN == {"brief": 1, "ship": 1}
