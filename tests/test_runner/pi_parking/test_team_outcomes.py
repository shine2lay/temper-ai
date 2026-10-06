"""How a team run ends, through a real in-process Temper (M3 E2/E3/E16/E18, A2/A3, M4 item 0).

Every team node writes its typed outcome to ``pi_team_outcomes`` on every way out, the only
record the Team page reads. Proven here, with every member a scripted Pi and the owner
answering through the approve route (nothing reaches a model):

- E18: a stop at the pause, or when the team had nothing left to do, ends the run cancelled --
  run row, the attempt's workflow.started event and the run list -- with E16's neutral text
  and the words given with the stop, never "Workflow cancelled by user". Pickup leaves such a
  run alone, and a resume of it starts nothing. A stop at a recovery wait still fails.
- E3/A3: a team whose node-start check fails before any turn didn't start; one whose turn
  failed failed; a cancelled run's team is cancelled, with the canceller's words.
- M4 item 0: the project folder is checked for real where the team runs, before any copy or
  model call: a folder that isn't there is "<path> isn't reachable inside Temper".
"""

from __future__ import annotations

from temper_ai.shared.clock import utcnow
from tests.test_pi_agent import support as sup
from tests.test_pi_agent import test_team as tt
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking import test_team_runs as runs
from tests.test_runner.pi_parking.test_team_runs import (
    CUT_OFF,
    GOAL,
    HOST,
    OUTPUTS,
    PAUSE_1,
    REFUSED,
    answer,
    install,
    parked_at,
    pick,
    prompts,
    script,
    stage_error,
    stage_row,
    start,
    team_row,
    team_waits,
)
from tests.test_runner.pi_team import support as ts

team_on = tt.team_on
tr = runs.tr


def outcome(tr, eid: str) -> dict:
    (row,) = tr.led.outcomes_of(eid)
    assert row["host_path"] == HOST
    return row


def listed_status(tr, eid: str) -> str:
    return pw.listed(tr.client, eid)["status"]


def pickup_why(eid: str) -> str:
    """Why pickup would leave the run alone if a restart had found it."""
    from temper_ai.runner.pickup import candidates_from, choose

    picks = choose(candidates_from([{"execution_id": eid, "workflow_name": "team_wf",
                                     "status_before": "running", "timestamp": utcnow()}]))
    assert not picks.picked
    (left,) = picks.left
    return left.why


def ended_cancelled(tr, eid: str, n: int, text: str) -> list[dict]:
    """The run ended cancelled in every place its status is read, with the stop's own text:
    the attempt's workflow.started event and the run list. (An in-process run has no
    WorkflowRun row; a run of its own writes the same status and text there,
    tests/test_cli/test_run_workflow.py's E18 test.)"""
    attempts = pw.wait_ended(eid, n)
    assert attempts[-1]["status"] == "cancelled", stage_error(eid, "build")
    assert listed_status(tr, eid) == "cancelled"
    assert stage_row(eid)[-1] == "cancelled" and team_row(eid)[-1] == "cancelled"
    assert text in stage_error(eid, "build")
    assert text in str(attempts[-1])
    assert "Workflow cancelled by user" not in str(attempts[-1])
    return attempts


# --- E18: the owner's stop at the pause or when stalled ends the run cancelled ------------------


def test_e18_a_stop_at_the_pause_with_words_ends_the_run_cancelled(tr):
    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "e18_pause_stop")
    assert answer(tr, eid, row, gate, "stop: we have what we need")["carries_on"] is True

    attempts = ended_cancelled(tr, eid, 2, "stopped at the pause after round 1")
    assert attempts[-1]["data"]["workflow_output"]["decision"] == "stopped"
    got = outcome(tr, eid)
    assert (got["decision"], got["reason"], got["owner_words"]) == (
        "stopped", "stopped at the pause after round 1", "we have what we need")
    assert got["decided_by"] == row_decision(tr, eid)["by"]
    assert got["by_source"] == row_decision(tr, eid)["source"]
    assert got["problems"] == []
    assert prompts() == {"design": 2, "frontend": 1, "qa": 1}  # nothing ran after the stop

    # pickup never starts a run its owner stopped
    assert pickup_why(eid) == "it was cancelled"
    # a resume reads the ended team and starts nothing
    turns = len(ts.rows(tr.led, eid, HOST)["turns"])
    r = tr.client.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert len(pw.attempts(eid)) == 2  # state-only: no replay of the stopped team
    assert prompts() == {"design": 2, "frontend": 1, "qa": 1}
    assert len(ts.rows(tr.led, eid, HOST)["turns"]) == turns
    assert [w["state"] for w in team_waits(tr, eid)] == ["decided"]
    assert outcome(tr, eid)["owner_words"] == "we have what we need"


def row_decision(tr, eid: str) -> dict:
    (row,) = [w for w in team_waits(tr, eid) if w["state"] == "decided"]
    return row["decision"] or {}


def test_e18_a_stop_when_the_team_had_nothing_left_to_do_ends_the_run_cancelled(tr):
    install(tr, tt.team_stage(), outputs=OUTPUTS)
    ts.SCRIPTS["design"] = [[{"say": "nothing to do"}]]
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "e18_stalled_stop")
    assert row["kind"] == "stalled"
    assert answer(tr, eid, row, gate, "stop: not worth it")["carries_on"] is True

    ended_cancelled(tr, eid, 2, "stopped when the team had nothing left to do")
    got = outcome(tr, eid)
    assert (got["decision"], got["reason"], got["owner_words"]) == (
        "stopped", "stopped when the team had nothing left to do", "not worth it")
    assert pickup_why(eid) == "it was cancelled"


def test_e18_a_stop_at_a_recovery_wait_still_fails_the_run(tr):
    install(tr, tt.team_stage())
    script(tr.led, ["done"])
    ts.SCRIPTS["design"].insert(0, CUT_OFF)
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "e18_recovery_stop")
    assert row["kind"] == "recovery"
    assert answer(tr, eid, row, gate, "stop: this is broken")["carries_on"] is True

    attempts = pw.wait_ended(eid, 2)
    assert attempts[-1]["status"] == "failed"
    assert listed_status(tr, eid) == "failed"
    text = "design turn 1 did not finish and the team was stopped"
    assert text in stage_error(eid, "build")
    got = outcome(tr, eid)
    assert (got["decision"], got["reason"], got["owner_words"]) == (
        "stopped", text, "this is broken")


# --- E17: a picked choice plus written words, through the approve route ----------------------


def test_e17_a_picked_guide_with_written_words_passes_the_words_to_the_leader(tr):
    """On the run page the owner picks 'guide' and writes the guidance: the pick is the choice
    and the written text is the words, never the rendered "Q: ... A: ..." text."""
    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "e17_guide_pick")
    assert pick(tr, eid, row, gate, "guide", custom="focus on the tests")["carries_on"] is True

    assert pw.wait_ended(eid, 2)[-1]["status"] == "completed", stage_error(eid, "build")
    (decided,) = team_waits(tr, eid)
    assert decided["decision"]["answer"] == "guide"
    (guidance,) = [m for m in ts.rows(tr.led, eid, HOST)["messages"]
                   if m["sender_kind"] == "owner"]
    assert guidance["to_member"] == "design"
    assert guidance["body"] == ("Guidance from the owner at the pause after round 1: "
                                "focus on the tests")


def test_e17_a_picked_stop_with_written_words_keeps_them_as_the_owners_words(tr):
    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "e17_stop_pick")
    assert pick(tr, eid, row, gate, "stop", custom="good enough")["carries_on"] is True
    ended_cancelled(tr, eid, 2, "stopped at the pause after round 1")
    assert outcome(tr, eid)["owner_words"] == "good enough"


# --- E3/A3: didn't start, failed, cancelled ---------------------------------------------------


def test_e3_a_turn_that_failed_makes_the_outcome_failed(tr):
    install(tr, tt.team_stage())
    ts.SCRIPTS["design"] = [REFUSED]
    eid = start(tr, {"goal": GOAL})
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    got = outcome(tr, eid)
    assert got["decision"] == "failed" and "design (architecture) turn 1 failed" in got["reason"]
    assert got["owner_words"] is None and got["decided_by"] is None


def test_m4_item0_a_missing_project_folder_is_refused_at_node_start_before_any_copy(
        tr, monkeypatch, tmp_path):
    """The real folder check runs where the team runs: a folder that isn't there is a plain
    problem, and the team didn't start (no copy made, no model called)."""
    from tests.test_runner.pi_team import leader_support as ls

    # any folder under the run's workspace is an allowed project folder by its text
    ls.allow_projects(monkeypatch, tmp_path / "more-settings", str(tr.ws), f"{tr.ws}/*")
    install(tr, tt.team_stage())
    script(tr.led, ["done"])
    missing = tr.ws / "not-there"
    r = tr.client.post("/api/runs", json={"workflow": "team_wf", "inputs": {"goal": GOAL},
                                          "workspace_path": str(missing)})
    assert r.status_code == 200, r.text
    eid = r.json()["execution_id"]
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    problem = f"project: {missing} isn't reachable inside Temper"
    got = outcome(tr, eid)
    assert got["decision"] == "didnt_start"
    assert got["reason"] == f"the team can't start: {problem}"
    assert got["problems"] == [problem]
    assert prompts() == {"design": 0, "frontend": 0, "qa": 0}
    assert ts.rows(tr.led, eid, HOST)["participants"] == []  # nobody set up, nothing copied
    assert not missing.exists()


def test_e3_a_cancelled_runs_team_is_cancelled_with_the_cancellers_words(tr):
    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    parked_at(tr, eid, 1, "e3_cancel_parked")
    r = tr.client.post(f"/api/runs/{eid}/cancel", json={"reason": "enough for today"})
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 1)[-1]["status"] == "cancelled"
    got = sup.wait_for(lambda: (o := outcome(tr, eid))["owner_words"] and o,
                       what="the cancel's words on the team's outcome")
    assert (got["decision"], got["reason"]) == ("cancelled", "the run was cancelled")
    assert got["owner_words"] == "enough for today"
    assert got["decided_by"] is not None
