"""A Pi-only run parks and resumes as it would in production (Architecture, rm-e61c9a39).

The parking and resume proofs in tests/test_pi_agent, tests/test_runner/pi_parking and
tests/test_runner/pi_team run with their own zero-cost test steps allowed beside the Pi step
(their conftests widen the Pi-only list, per test). Production has only Pi-only workflows, and
a finished Pi step run again costs a real model turn. So here, with the default list and no
widening: a workflow of two Pi steps, the second behind a gate, parks at each wait. Each answer
queues it again, and every box goes back through the lane's own claim and the Pi-only check
before it runs anything. A finished Pi step is never started again.

The server is production's: external mode, no lane setting, Pi switched off. Each box is the
run process pi-worker starts: the Pi lane's settings, with L2's stand-in Pi box (FakeBox, no
model). Only the preflight's checks of the real machine are left out (test_preflight.py tests
them), and the commit it would read is planted (test_run_gate.py tests the read).
"""

from __future__ import annotations

import argparse

import pytest
import sqlalchemy as sa

from temper_ai.runner import lanes, pi_lane
from temper_ai.runner.lanes import PI_LANE
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_lane import support as ls
from tests.test_runner.pi_parking import support as pw

WORKFLOW = "lane_pi_two_steps"
SHA = "1f2e3d4c5b6a79881f2e3d4c5b6a79881f2e3d4c"


def two_pi_steps() -> list:
    """Pi step ``a``, then Pi step ``b`` behind a gate: Pi-only, as production's are."""
    second = sup.pi_node("b", depends_on=("a",))
    second.config.gate = True
    return [sup.pi_node("a", depends_on=()), second]


class _GoneBoxes:
    """The Pi lane's spawner after each box has exited."""

    def is_alive(self, handle) -> bool:
        return False

    def is_gone(self, handle) -> bool:
        return True


@pytest.fixture
def lane_box(srv, monkeypatch, tmp_path):
    import temper_ai.stage.executor as executor_mod
    from temper_ai.runner import pi_preflight
    from temper_ai.runner.context import RunnerContext

    st = srv.state
    ctx = RunnerContext(config_store=st.config_store, graph_loader=st.graph_loader,
                        llm_providers=st.llm_providers, memory_service=st.memory_service)
    monkeypatch.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env",
                        lambda config_dir=None: ctx)
    monkeypatch.setattr("temper_ai.cli.run_workflow._start_mcp_manager", lambda config_dir: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._stop_mcp_manager", lambda: None)
    # Signals stay pytest's: the run process's handlers only matter in a real one.
    monkeypatch.setattr("temper_ai.cli.run_workflow._install_signal_handlers", lambda *a: None)
    monkeypatch.setattr(pi_preflight, "preflight", lambda **_kw: [])
    monkeypatch.setattr(pi_lane, "read_commit", lambda root=None: (SHA, ""))
    monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)
    monkeypatch.setitem(sup.WORKFLOWS, WORKFLOW, two_pi_steps)
    srv.box_json = sup.make_box_config(tmp_path / "box")
    sup.reset_fake()
    sup.register_types()
    yield srv
    sup.reset_fake()
    sup.stop_running(srv.state)
    sup.unregister_types()


def _box(srv, eid: str, monkeypatch) -> int:
    """One box for the run, as pi-worker starts it: the main lane's claim never takes the run,
    the Pi lane's does, and its run process checks the run again before it runs anything
    (runner/pi_lane.py check_run). Returns the run process's exit code."""
    from temper_ai.cli.run_workflow import cmd_run_workflow
    from temper_ai.cli.watch_queue import _claim_row

    assert ls.row(eid).status == "queued"
    assert ls.lane(eid) == PI_LANE
    assert not _claim_row(eid, spawner_kind="docker")  # the main lane's claim
    assert _claim_row(eid, spawner_kind="subprocess", lane=PI_LANE)
    with monkeypatch.context() as box:
        box.setenv(lanes.LANE_ENV, PI_LANE)
        box.setenv("TEMPER_PI_AGENT", "1")
        box.setenv("TEMPER_PI_BOX_CONFIG", str(srv.box_json))
        return cmd_run_workflow(argparse.Namespace(execution_id=eid, config_dir=None,
                                                   debug=False))


def _let_go(eid: str) -> None:
    """The box let go at a wait: the Pi lane's reaper, seeing it gone, frees the run (and
    queues it at once when its answer is already in)."""
    from temper_ai.spawner.reaper import Reaper

    Reaper(_GoneBoxes(), interval_seconds=60, lane=PI_LANE).tick()  # type: ignore[arg-type]


def _parked_at(eid: str) -> str:
    last = pw.attempts(eid)[-1]
    assert last["status"] == "waiting", last
    return pw.parked(last)["path"]


def _turns(eid: str) -> dict[str, int]:
    """How many turns each Pi step of the run has had, from the ledger."""
    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import turns

    with get_database().engine.connect() as conn:
        found = conn.execute(sa.select(turns.c.host_path, sa.func.count())
                             .where(turns.c.run_id == eid).group_by(turns.c.host_path)).all()
    return {str(path): int(n) for path, n in found}


def test_a_pi_only_run_resumes_through_the_lane_s_claim_and_never_runs_a_finished_step_again(
        lane_box, monkeypatch):
    c = lane_box.client
    assert lanes.PI_LANE_AGENT_TYPES == ("pi",) and lanes.PI_LANE_OTHER_NODES == ()
    checked: list[tuple[list[str], list[str]]] = []
    real_check = pi_lane.pi_only_problems

    def counted(nodes, safety=None):
        problems = real_check(nodes, safety)
        checked.append(([node.name for node in nodes], problems))
        return problems

    monkeypatch.setattr(pi_lane, "pi_only_problems", counted)

    eid = sup.start(c, WORKFLOW, lane_box.ws)
    assert ls.lane(eid) == PI_LANE

    # Box 1: step a's turn, then a's own "what next" wait: the box lets go there.
    assert _box(lane_box, eid, monkeypatch) == 0
    assert _parked_at(eid) == "a"
    assert ls.row(eid).status == "running"  # the box left its row as it was
    pw.answer_pi(c, eid)
    _let_go(eid)

    # Box 2: a is done (its answer is in the ledger); the gate before b: the box lets go.
    assert _box(lane_box, eid, monkeypatch) == 0
    assert _parked_at(eid) == "b"
    _let_go(eid)
    assert ls.row(eid).status == "waiting"
    gate = pw.open_gate(c, eid, "b")
    r = pw.approve(c, eid, "b", event_id=gate["event_id"])
    assert r.status_code == 200 and r.json()["carries_on"] is True, r.text
    resumed = ls.row(eid)
    assert resumed.status == "queued" and resumed.spawner_kind is None
    assert (resumed.spawner_metadata or {}).get("start") == "resume"

    # Box 3: b's turn, then b's own wait.
    assert _box(lane_box, eid, monkeypatch) == 0
    assert _parked_at(eid) == "b"
    pw.answer_pi(c, eid)
    _let_go(eid)

    # Box 4: b is done; the run ends.
    assert _box(lane_box, eid, monkeypatch) == 0
    assert ls.row(eid).status == "completed"
    assert pw.attempts(eid)[-1]["status"] == "completed"

    # Every box went through the lane's claim and its Pi-only check, with the default list.
    assert checked == [(["a", "b"], [])] * 4
    assert lanes.PI_LANE_AGENT_TYPES == ("pi",) and lanes.PI_LANE_OTHER_NODES == ()
    # A finished Pi step was never started again: one box and one turn for each step.
    assert len(FakeBox.STARTS) == 2
    assert _turns(eid) == {"a": 1, "b": 1}
    # The commit was recorded at the start and at each resume (SW-16).
    commits = (ls.row(eid).spawner_metadata or {})["pi_lane"]["commits"]
    assert [entry["commit"] for entry in commits] == [SHA] * 4
