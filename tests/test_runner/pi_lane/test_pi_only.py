"""The Pi-only rule at submit (ADR-M4-01, SW-30, SW-41; docs/pi-lane.md).

The Pi lane holds the Docker socket, so it runs only what the Pi worker box contains: Pi
steps, team stages of Pi members, and gates on them. A Pi run with anything else is refused
when it is started, resumed or forked, with each step named, and nothing is written. The same
rule runs again when the Pi lane claims the run (test_run_gate.py). An ordinary run is never
held to it.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.runner import lanes
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.models import NodeConfig
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_lane import support as ls

RULE = ("This workflow has Pi steps, so it runs in the Pi lane, which runs only Pi steps, team "
        "stages of Pi members and gates: ")


def agent(name: str, kind: str | None, depends_on=(), **cfg) -> AgentNode:
    values = {"name": name, **({"type": kind} if kind else {}), **cfg}
    return AgentNode(NodeConfig(name=name, depends_on=list(depends_on)), values)


def mixed_team():
    from temper_ai.pi_agent.team_node import TeamNode
    from temper_ai.stage.stage_node import StageNode

    members = [{**ls.MEMBER, "name": "design"}, {**ls.MEMBER, "name": "qa", "type": "llm"}]
    team = TeamNode(NodeConfig(name="team"), members, settings=None)  # type: ignore[arg-type]
    return StageNode(NodeConfig(name="crew"), [team])


#: Pi runs the lane refuses, and what the refusal names.
REFUSED = {
    "script_step": (lambda: [agent("ship", "script", script="echo hi"), sup.pi_node(depends_on=())],
                    ["step 'ship' is a script step; the Pi lane runs only Pi steps"]),
    "llm_step": (lambda: [agent("plan", None), sup.pi_node(depends_on=())],
                 ["step 'plan' is a llm step; the Pi lane runs only Pi steps"]),
    "test_step": (lambda: [sup.step("brief"), sup.pi_node()],
                  ["step 'brief' is a pi_test_step step; the Pi lane runs only Pi steps"]),
    "mcp_servers": (lambda: [sup.pi_node(depends_on=(), mcp_servers=["github"])],
                    ["step 'talk' asks for tool servers (github); the Pi lane runs no MCP or "
                     "tool servers"]),
    "mcp_tool": (lambda: [sup.pi_node(depends_on=(), tools=["Read", "linear.search_issues"])],
                 ["step 'talk' asks for tool servers (linear); the Pi lane runs no MCP or tool "
                  "servers"]),
    "team_member": (lambda: [mixed_team()],
                    ["team member 'crew.team.qa' is a llm step; the Pi lane runs only Pi steps"]),
    "two_at_once": (lambda: [agent("ship", "script"), sup.pi_node(depends_on=()),
                             agent("plan", None, ["talk"])],
                    ["step 'ship' is a script step; the Pi lane runs only Pi steps",
                     "step 'plan' is a llm step; the Pi lane runs only Pi steps"]),
}


def _no_rows() -> bool:
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        return session.exec(select(WorkflowRun)).first() is None


def _post(srv, workflow: str):
    return srv.client.post("/api/runs", json={"workflow": workflow, "inputs": {"topic": "lane"},
                                              "workspace_path": str(srv.ws)})


@pytest.mark.parametrize("which", sorted(REFUSED))
def test_a_pi_run_with_anything_else_is_refused_at_start_naming_each_step(
        srv, monkeypatch, which):
    build, problems = REFUSED[which]
    monkeypatch.setitem(sup.WORKFLOWS, "refused", build)
    r = _post(srv, "refused")
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == RULE + "; ".join(problems)
    assert _no_rows()


def test_a_pi_run_that_sets_safety_policies_is_refused_by_name(srv, monkeypatch):
    """SW-30: the Pi lane doesn't run the workflow's policies; the member box is the
    boundary. Refused, not silently dropped."""
    loader = srv.state.graph_loader
    real = loader.load_workflow

    def with_policies(name, inputs=None, **kw):
        nodes, config = real(name, inputs, **kw)
        return nodes, SimpleNamespace(**{**vars(config), "safety": {"policies": ["no_rm"]}})

    monkeypatch.setattr(loader, "load_workflow", with_policies)
    r = _post(srv, "lane_pi")
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == RULE + (
        "the workflow sets safety: policies:, which the Pi lane doesn't run")
    assert _no_rows()


@pytest.mark.parametrize("workflow", ["lane_pi", "lane_pi_gate", "lane_team"])
def test_pi_steps_gates_and_team_stages_of_pi_members_are_let_through(srv, workflow):
    r = _post(srv, workflow)
    assert r.status_code == 200, r.text


def test_an_ordinary_run_is_never_held_to_the_rule(srv, monkeypatch):
    """Script and llm steps, MCP servers and policies, as always: no Pi step, no rule."""
    monkeypatch.setitem(sup.WORKFLOWS, "ordinary", lambda: [
        agent("ship", "script", script="echo hi"), agent("plan", None, ["ship"],
                                                         mcp_servers=["github"])])
    r = _post(srv, "ordinary")
    assert r.status_code == 200, r.text
    ls.only_the_main_lane_claims(r.json()["execution_id"])


def test_a_resume_and_a_fork_are_held_to_the_rule_as_the_workflow_is_now(srv, monkeypatch):
    """Both load the workflow again: one that gained a script step since is refused."""
    from temper_ai.api import routes
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.stage.executor import NodeResult, Status

    ls.make_row("old", "lane_pi", status="failed", spawner_kind="subprocess", handle="1")
    service = CheckpointService("old")
    service.save_node_completed("talk", NodeResult(status=Status.COMPLETED, output="done"))
    monkeypatch.setattr(routes, "get_workflow_execution", lambda eid: {
        "workflow_name": "lane_pi", "status": "failed", "input_data": {},
        "workspace_path": str(srv.ws)})
    build, problems = REFUSED["script_step"]
    monkeypatch.setitem(sup.WORKFLOWS, "lane_pi", build)
    r = srv.client.post("/api/runs/old/resume", json={})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == RULE + "; ".join(problems)
    assert ls.row("old").status == "failed"
    r = srv.client.post("/api/runs/fork", json={
        "workflow": "lane_pi", "source_execution_id": "old",
        "sequence": service.get_latest_sequence(), "inputs": {}, "workspace_path": str(srv.ws)})
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == RULE + "; ".join(problems)


# --- the rule itself -------------------------------------------------------------------------


class Webhook:
    """A node kind the Pi lane has never heard of."""

    def __init__(self, name: str) -> None:
        self.name = name


def test_any_other_kind_of_node_is_refused_by_its_kind():
    assert lanes.pi_only_problems([sup.pi_node(depends_on=()), Webhook("ping")]) == [
        "step 'ping' is a Webhook, which the Pi lane doesn't run"]


def test_only_the_pi_step_is_on_the_list_in_production():
    """Tests of the Pi step's parking add their own test step types for their package only
    (their conftests); nothing in temper widens it."""
    assert lanes.PI_LANE_AGENT_TYPES == ("pi",)
    assert lanes.PI_LANE_OTHER_NODES == ()


#: Where the list is widened: the Pi step's own test packages (their fixtures), the one file
#: that runs the committed ci_pi_waits, the helper itself, and L2's crash child (a process
#: of its own).
WIDENED_IN = ["test_pi_agent/child.py", "test_pi_agent/conftest.py", "test_pi_agent/support.py",
              "test_runner/pi_parking/conftest.py",
              "test_runner/pi_parking/test_ci_workflow.py", "test_runner/pi_team/conftest.py"]


def test_the_rule_s_own_tests_are_out_of_reach_of_the_widening():
    """Architecture, rm-e61c9a39: the widening is per test, through pytest's monkeypatch
    (function scope, undone after each test), and never in this package, which holds the
    rule's own tests: the default list, one refusal per kind and the entry points
    (test_mark.py), and a Pi-only resume as in production (test_resume_as_in_production.py)."""
    tests = Path(__file__).resolve().parents[2]
    widens = re.compile(r"into_the_pi_lane\(|setattr\([^)]*PI_LANE_(AGENT_TYPES|OTHER_NODES)")
    found = sorted(path.relative_to(tests).as_posix() for path in tests.rglob("*.py")
                   if widens.search(path.read_text(encoding="utf-8")))
    assert found == WIDENED_IN
    for conftest in (name for name in WIDENED_IN if name.endswith("conftest.py")):
        text = (tests / conftest).read_text(encoding="utf-8")
        assert "@pytest.fixture(autouse=True)\ndef _in_the_pi_lane(monkeypatch):" in text, conftest
