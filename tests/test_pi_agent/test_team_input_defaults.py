"""A team whose goal input has a declared default, started without it (the Pi switch on).

The run-start check reads the run's inputs (team_check.goal_problem); it must see the default,
not refuse the run with "goal: ... not set". The run records the goal it used and the team node
is handed it. (The team node's own check at a fresh start, after a resume and after a fork,
queue #38, reads the same filled inputs: tests/test_runner/pi_parking/test_team_runs.py.)
"""

from __future__ import annotations

import pytest

from temper_ai.pi_agent.team_node import TeamNode
from temper_ai.shared.types import NodeResult, Status
from tests.test_pi_agent import support as sup
from tests.test_pi_agent import test_team
from tests.test_pi_agent.support import FakeBox
from tests.test_pi_agent.test_team import store, team_stage

team_on = test_team.team_on  # the fixture: the team switched on, with the fixture role list

GOAL_DEFAULT = "Add a sign-up page"
NOT_SET = "goal: the stage reads it from the run input 'goal', which is not set"
REQUIRED = "goal: required: give the run a 'goal' input"
# the two ways a team stage reads its goal from the run: mapped in its input_map, or the run's
# own 'goal' input (team_check.goal_problem); each refused, without a default, its own way
READS = [({"input_map": {"goal": "input.goal"}}, NOT_SET), ({"input_map": {}}, REQUIRED)]


def defaulted(**stage_over):
    """The team workflow with its goal input declared, required, with a default."""
    stage = team_stage(**stage_over)
    workflow = {"name": "team_wf", "nodes": [stage],
                "inputs": {"goal": {"type": "string", "required": True,
                                    "default": GOAL_DEFAULT}}}
    return store(stage, extra={"workflow:team_wf": workflow})


@pytest.mark.usefixtures("team_on")
@pytest.mark.parametrize("reads, refusal", READS, ids=["input_map", "run-input"])
@pytest.mark.parametrize("given", [{}, {"goal": None}, {"goal": ""}], ids=["absent", "null", "empty"])
def test_a_goal_left_out_passes_the_run_start_check_with_its_default(given, reads, refusal):
    from temper_ai.stage.exceptions import ValidationError
    from temper_ai.stage.loader import GraphLoader

    nodes, _ = GraphLoader(defaulted(**reads)).load_workflow("team_wf", inputs=given,
                                                             run_start=True)
    (team,) = nodes[0].child_nodes
    assert isinstance(team, TeamNode)
    # without the declared default the same start is refused, as before
    with pytest.raises(ValidationError, match=refusal):
        GraphLoader(store(team_stage(**reads))).load_workflow("team_wf", inputs=given,
                                                              run_start=True)


@pytest.mark.usefixtures("team_on")
@pytest.mark.parametrize("given, goal", [
    ({}, GOAL_DEFAULT), ({"goal": None}, GOAL_DEFAULT), ({"goal": ""}, GOAL_DEFAULT),
    ({"goal": "Fix the footer"}, "Fix the footer"),
], ids=["absent", "null", "empty", "given"])
def test_the_run_start_check_reads_the_goal_the_run_will_use(given, goal, monkeypatch):
    from temper_ai.pi_agent import team_check
    from temper_ai.stage.loader import GraphLoader

    seen = []
    real = team_check.goal_problem

    def spy(input_map, inputs):
        seen.append(dict(inputs))
        return real(input_map, inputs)

    monkeypatch.setattr(team_check, "goal_problem", spy)
    GraphLoader(defaulted()).load_workflow("team_wf", inputs=given, run_start=True)
    assert [s.get("goal") for s in seen] == [goal]


def test_a_team_run_started_without_its_goal_records_it_and_its_node_gets_it(pi, team_on,
                                                                              monkeypatch):
    # pi before team_on: team_on's worker box config (with the role list) must be the one set
    from temper_ai.stage.loader import GraphLoader

    handed = []
    stopped = "stopped here by the test: only the goal handed to the team node is checked"

    def run(self, input_data, context):  # the team itself is never run here (no member)
        handed.append(dict(input_data))
        return NodeResult(status=Status.FAILED, error=stopped)

    monkeypatch.setattr(TeamNode, "run", run)
    pi.state.graph_loader = GraphLoader(defaulted())
    pi.ws.mkdir(parents=True, exist_ok=True)
    r = pi.client.post("/api/runs", json={"workflow": "team_wf", "inputs": {},
                                          "workspace_path": str(pi.ws)})
    assert r.status_code == 200, r.text  # not refused with "goal: ... not set"
    eid = r.json()["execution_id"]
    attempts = sup.wait_ended(eid)
    assert attempts[-1]["status"] == "failed"  # the stand-in node fails red, and the run with it
    assert (attempts[-1]["data"] or {})["input_data"] == {"goal": GOAL_DEFAULT}
    assert [h.get("goal") for h in handed] == [GOAL_DEFAULT]
    assert any(stopped in str(e["data"]) for e in sup.events(eid))
    assert FakeBox.STARTS == []
