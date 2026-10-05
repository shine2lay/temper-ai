"""A gated stage whose inner step's approval lets the worker go (#39's finding 2).

The stage's own approval comes first and lets go; the answer carries the run on, the stage
starts, and the approval of a step inside it lets go in turn. Carrying the run on after that
answer runs the stage again from its start: its gate must take the answer it was already
given, not ask the owner a second time for the same go (temper_ai/stage/executor.py,
``_keep_gate_answer``). A rejection still stops the run, and a stage in a loop still asks on
each new lap.

In-process and external (each attempt in its own box), as the rest of pi_parking. Nothing
reaches a model or the network (pi_parking/conftest.py's guard).
"""

from __future__ import annotations

import pytest

from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.stage_node import StageNode
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import step_support as ask
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking.test_external import _box, _reaper, _row


def gated_stage(name: str = "stage", depends_on=("talk",)) -> StageNode:
    """A stage behind an approval, holding a step behind an approval of its own."""
    return StageNode(NodeConfig(name=name, type="stage", depends_on=list(depends_on), gate=True),
                     [pw.gated("inner")])


def judge(name: str = "judge", depends_on=("stage",)) -> AgentNode:
    """Sends the run back to the stage while it says "again" (at most twice; then red)."""
    config = NodeConfig(name=name, depends_on=list(depends_on), loop_to="stage", max_loops=2,
                        on_max_loops="fail",
                        loop_condition={"source": f"{name}.structured.verdict",
                                        "operator": "equals", "value": "again"})
    return AgentNode(config, {"name": name, "type": pw.VERDICT_TYPE})


WORKFLOWS = {
    "gs_stage": lambda: [sup.step("brief"), sup.pi_node(), gated_stage(),
                         sup.step("ship", ["stage"])],
    "gs_loop": lambda: [sup.step("brief"), sup.pi_node(), gated_stage(), judge(),
                        sup.step("ship", ["judge"])],
}


@pytest.fixture
def gs(pw_run, monkeypatch):
    for name, build in WORKFLOWS.items():
        monkeypatch.setitem(sup.WORKFLOWS, name, build)
    return pw_run


def _settled(state, eid: str, n_attempts: int, timeout: float = 20.0) -> list[dict]:
    """Attempt ``n_attempts`` has let go at a wait (and nothing holds the run) or ended."""
    def done():
        a = pw.attempts(eid)
        if len(a) < n_attempts:
            return None
        last = a[-1]
        if last["status"] in ("completed", "failed", "cancelled"):
            return a
        if (last["status"] == "waiting" and pw.parked(last) and eid not in state.running
                and not pw.run_threads(eid)):
            return a
        return None
    return sup.wait_for(done, timeout, what=f"attempt {n_attempts} of {eid} to let go or end")


def _approve(c, eid: str, name: str, wait: dict, **kw) -> None:
    r = pw.approve(c, eid, name, event_id=wait["event_id"], **kw)
    assert r.status_code == 200, r.text
    assert r.json()["carries_on"] is True, r.text


def _stage_then_inner(gs, eid: str, n: int) -> tuple[dict, dict]:
    """In attempt ``n`` the stage's gate lets go, its answer carries the run on, then the
    inner step's gate lets go. Returns (the stage's wait, the inner step's wait)."""
    c = gs.client
    first = pw.wait_parked(gs.state, eid, n_attempts=n)
    stage_wait = pw.open_gate(c, eid, "stage")
    assert pw.parked(first)["path"] == "stage"
    _approve(c, eid, "stage", stage_wait)
    second = pw.wait_parked(gs.state, eid, n_attempts=n + 1)
    inner_wait = pw.open_gate(c, eid, "inner")
    assert pw.parked(second)["path"] == "stage.inner"
    assert pw.parked(second)["event_id"] == inner_wait["event_id"]
    return stage_wait, inner_wait


def test_a_gated_stage_whose_inner_approval_lets_go_is_approved_once(gs):
    c = gs.client
    eid = sup.start(c, "gs_stage", gs.ws)
    n = pw.finish_pi(c, eid)
    stage_wait, inner_wait = _stage_then_inner(gs, eid, n)
    # The stage's answer is kept for the go that carries the stage on.
    (asked,) = pw.waits(eid, "stage")
    assert asked["status"] == "approved" and not asked["data"].get("gate_used_at")
    assert asked["data"].get("gate_kept_while") == inner_wait["event_id"]

    _approve(c, eid, "inner", inner_wait)
    attempts = _settled(gs.state, eid, n + 2)
    assert [a["status"] for a in attempts] == ["parked"] * (n + 1) + ["completed"], (
        f"the stage's gate was asked again: {pw.waits(eid, 'stage')}")
    (stage,) = pw.waits(eid, "stage")
    assert stage["id"] == stage_wait["event_id"] and stage["data"].get("gate_used_at")
    # The inner step's own gate let go once and was asked once.
    (inner,) = pw.waits(eid, "inner")
    assert inner["status"] == "approved" and inner["data"].get("gate_used_at")
    assert [cp["id"] for cp in ask.checkpoints(c, eid, "gate_parked")] == [
        stage_wait["event_id"], inner_wait["event_id"]]
    assert pw.RAN == {"brief": 1, "inner": 1, "ship": 1} and len(FakeBox.STARTS) == 1
    assert pw.detail(c, eid)["status"] == "completed"


def test_a_rejected_inner_approval_stops_the_run_and_the_stage_is_not_asked_again(gs):
    from temper_ai.integrations.slack.ops import TemperOps
    from temper_ai.runner import parked

    c = gs.client
    eid = sup.start(c, "gs_stage", gs.ws)
    n = pw.finish_pi(c, eid)
    stage_wait, inner_wait = _stage_then_inner(gs, eid, n)

    # Reject (Slack's button): the run stops, as a rejected approval stops it today.
    out = TemperOps().cancel(eid, "Rejected in Slack by Owner", by="Owner (Slack)")
    assert out["status"] == "cancelled", out
    assert [a["status"] for a in pw.attempts(eid)] == ["parked"] * n + ["cancelled"]
    (inner,) = pw.waits(eid, "inner")
    assert inner["status"] == "rejected"
    assert "Rejected in Slack by Owner" in str(inner["data"].get("gate_response"))
    assert parked.carry_on_at_startup() == []
    assert pw.detail(c, eid)["status"] == "cancelled"
    assert [w["id"] for w in pw.waits(eid, "stage")] == [stage_wait["event_id"]]
    assert pw.RAN == {"brief": 1}

    # Resumed later: the stage goes on with the answer it was given; only the step whose
    # approval was rejected asks again.
    r = c.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    third = pw.wait_parked(gs.state, eid, n_attempts=n + 2)
    assert pw.parked(third)["path"] == "stage.inner", pw.parked(third)
    assert [w["id"] for w in pw.waits(eid, "stage")] == [stage_wait["event_id"]]
    again = pw.open_gate(c, eid, "inner")
    assert again["event_id"] != inner_wait["event_id"]
    assert [w["status"] for w in pw.waits(eid, "inner")] == ["rejected", "waiting"]
    _approve(c, eid, "inner", again)
    attempts = _settled(gs.state, eid, n + 3)
    assert [a["status"] for a in attempts] == (["parked"] * n
                                               + ["cancelled", "parked", "completed"])
    assert len(pw.waits(eid, "stage")) == 1
    assert pw.RAN == {"brief": 1, "inner": 1, "ship": 1}


def test_a_gated_stage_in_a_loop_still_asks_on_each_new_lap(gs):
    c = gs.client
    eid = sup.start(c, "gs_loop", gs.ws)
    n = pw.finish_pi(c, eid)
    lap1_stage, lap1_inner = _stage_then_inner(gs, eid, n)
    _approve(c, eid, "inner", lap1_inner)

    # Lap 1 finishes (the judge says "again"), and lap 2 asks the stage's gate afresh.
    third = _settled(gs.state, eid, n + 2)[-1]
    assert pw.RAN["judge"] == 1, f"lap 1 did not finish: {pw.waits(eid, 'stage')}"
    assert pw.parked(third)["path"] == "stage" and pw.parked(third)["round"] == 2
    lap2_stage = pw.open_gate(c, eid, "stage")
    assert lap2_stage["event_id"] != lap1_stage["event_id"]
    _approve(c, eid, "stage", lap2_stage)
    fourth = _settled(gs.state, eid, n + 3)[-1]
    assert pw.parked(fourth)["path"] == "stage.inner" and pw.parked(fourth)["round"] == 2
    lap2_inner = pw.open_gate(c, eid, "inner")

    pw.VERDICT["say"] = "done"
    _approve(c, eid, "inner", lap2_inner)
    attempts = _settled(gs.state, eid, n + 4)
    assert [a["status"] for a in attempts] == ["parked"] * (n + 3) + ["completed"]
    stage_waits = pw.waits(eid, "stage")
    assert [w["id"] for w in stage_waits] == [lap1_stage["event_id"], lap2_stage["event_id"]]
    assert all(w["status"] == "approved" and w["data"].get("gate_used_at") for w in stage_waits)
    assert [w["id"] for w in pw.waits(eid, "inner")] == [lap1_inner["event_id"],
                                                         lap2_inner["event_id"]]
    assert pw.RAN == {"brief": 1, "inner": 2, "judge": 2, "ship": 1}


# --- external mode: each attempt in its own box ------------------------------------------------


@pytest.fixture
def gsx(gs, monkeypatch):
    """External mode, as test_external.py's ``ext``."""
    from temper_ai.runner.context import RunnerContext

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    st = gs.state
    ctx = RunnerContext(config_store=st.config_store, graph_loader=st.graph_loader,
                        llm_providers=st.llm_providers, memory_service=st.memory_service)
    monkeypatch.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env",
                        lambda config_dir=None: ctx)
    monkeypatch.setattr("temper_ai.cli.run_workflow._start_mcp_manager", lambda config_dir: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._stop_mcp_manager", lambda: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._install_signal_handlers", lambda *a: None)
    return gs


def _box_lets_go(gsx, eid: str, monkeypatch, path: str, *, finish_pi: bool = False) -> dict:
    """One box runs until it lets go at the wait at ``path``; the reaper frees the run.
    Returns that wait, as GET .../gates lists it."""
    assert _box(gsx, eid, monkeypatch, finish_pi=finish_pi) == 0
    last = pw.attempts(eid)[-1]
    assert last["status"] == "waiting" and pw.parked(last), last
    assert pw.parked(last)["path"] == path, pw.parked(last)
    _reaper().tick()
    assert _row(eid)["status"] == "waiting"
    wait = pw.open_gate(gsx.client, eid, path.rsplit(".", 1)[-1])
    assert wait["event_id"] == pw.parked(last)["event_id"]
    return wait


def test_a_gated_stage_whose_inner_approval_lets_go_of_its_box_is_approved_once(gsx, monkeypatch):
    c = gsx.client
    eid = sup.start(c, "gs_stage", gsx.ws)
    stage_wait = _box_lets_go(gsx, eid, monkeypatch, "stage", finish_pi=True)
    _approve(c, eid, "stage", stage_wait)
    assert _row(eid)["status"] == "queued"
    inner_wait = _box_lets_go(gsx, eid, monkeypatch, "stage.inner")
    _approve(c, eid, "inner", inner_wait)
    assert _row(eid)["status"] == "queued"

    assert _box(gsx, eid, monkeypatch) == 0
    assert [a["status"] for a in pw.attempts(eid)] == ["parked"] * 3 + ["completed"], (
        f"the stage's gate was asked again: {pw.waits(eid, 'stage')}")
    assert _row(eid)["status"] == "completed"
    (stage,) = pw.waits(eid, "stage")
    assert stage["id"] == stage_wait["event_id"] and stage["data"].get("gate_used_at")
    (inner,) = pw.waits(eid, "inner")
    assert inner["status"] == "approved" and inner["data"].get("gate_used_at")
    assert pw.RAN == {"brief": 1, "inner": 1, "ship": 1} and len(FakeBox.STARTS) == 1
