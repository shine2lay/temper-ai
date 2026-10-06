"""A team stage outside the Pi lane refuses (M4 SW-42), before its ledger or any member box.

The backstop behind the lane mark, as the Pi step's own (tests/test_pi_agent/
test_outside_the_pi_lane.py): the team node refuses first and writes nothing.
"""

from __future__ import annotations

from temper_ai.pi_agent import team_leader
from temper_ai.runner.lanes import OUTSIDE_PI_LANE
from tests.test_pi_agent import test_team as tt
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking import test_team_runs as runs

team_on = tt.team_on
tr = runs.tr


def test_a_team_stage_outside_the_pi_lane_refuses_before_any_member_is_set_up(tr, monkeypatch):
    monkeypatch.setattr(team_leader, "in_pi_lane", lambda: False)
    runs.install(tr, runs.BRIEF_NODE, tt.team_stage(depends_on=["brief"]))
    runs.script(tr.led, ["done"])
    eid = runs.start(tr, {"goal": runs.GOAL})
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    assert runs.team_row(eid)[-1] == "failed"
    error = runs.stage_error(eid, "build")
    assert f"{OUTSIDE_PI_LANE}: this worker isn't the Pi lane, so the team did not start" in error
    assert runs.prompts() == {"design": 0, "frontend": 0, "qa": 0}
    assert FakeBox.STARTS == []
    snap = tr.led.snapshot(eid)
    assert {name: rows for name, rows in snap.items() if rows} == {}


def test_the_same_team_in_the_pi_lane_runs(tr):
    """The positive control: in the lane, the same team runs to its decision."""
    runs.install(tr, runs.BRIEF_NODE, tt.team_stage(depends_on=["brief"]))
    runs.script(tr.led, ["done"])
    eid = runs.start(tr, {"goal": runs.GOAL})
    assert pw.wait_ended(eid, 1)[-1]["status"] == "completed"
    assert OUTSIDE_PI_LANE not in runs.stage_error(eid, "build")
