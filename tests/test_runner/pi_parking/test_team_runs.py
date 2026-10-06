"""Team runs through a real in-process Temper (#38): a team stage's node runs the leader loop,
its owner waits park the run, and the owner's answer carries it on in the same run.

Every member is a scripted Pi (tests/test_runner/pi_team/support.py's TeamFakeBox) behind the
real turn code, and the owner answers through the API's approve route. Nothing reaches a model
or the network (pi_parking/conftest.py's guard), and tables.md's invariants I1-I8 are checked
for every team after every test here (pi_parking/conftest.py, #37's land check binding 3).

Proven here, on top of pi_team/test_leader_loop.py's unit tests of the loop itself:

- PARK P1: a team pause in a Pi workflow holds no running entry, thread or child process for
  the run (counted with step_support.held, the way PARK counted), and carrying the run on
  re-runs no member turn that had already finished (R2 B10, LR4).
- PARK P2: two pauses in one go each ask the owner, under their own wait ids.
- Every team wait is a ``pi_waits`` row written before the owner is asked, and the wait the
  owner is asked is that row's id.
- A failed team node fails its stage row and the run (M2-roles P2, R2 B13); other stages keep
  the tolerant rule.
- A team node may be the workflow's first node, through a resume and restarts there.
- The node's own start check (M2 binding): a left-out goal's declared default reaches it at a
  fresh start, after a resume and after a fork; a resume or a fork with a bad config fails red
  before any member is set up (R2 B7, B8, T4T5 N3).
- G-a: a process that dies between ending a cancelled run's row and ending its team leaves the
  team's messages for the next sweep, which records them undelivered; a cancel while the Pi
  switch is off leaves the team for the first sweep after it is back on (M4 SW-09).
- The Pi switch going off while a team run is parked (M4 SW-32): the run waits, saying "Pi
  switched off", and never fails with "Unknown strategy 'team'"; back on, it carries on.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
from datetime import datetime

import pytest

from temper_ai.pi_agent.ledger import Ledger, reviews, waits
from temper_ai.pi_agent.team_runtime import Team
from temper_ai.shared.clock import as_utc, utcnow
from tests.test_pi_agent import support as sup
from tests.test_pi_agent import test_team as tt
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import step_support as ss
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts

team_on = tt.team_on  # the team switched on with the fixture role list; asked for after pw_run

HOST = "build.team"
GOAL = "This tiny project has no README. Write a short one."
GOAL_DEFAULT = "Write a short README for this tiny project."
README = "# Tiny\n\nPrints hello. Run it with `python app.py`.\n"
PAUSE_1 = {**tt.RUNNABLE, "pause_after_rounds": 1}
BRIEF = {"agent:brief": {"name": "brief", "type": sup.STEP_TYPE}}
BRIEF_NODE = {"name": "brief", "type": "agent", "agent": "brief"}
DEFAULTED = {"goal": {"type": "string", "required": True, "default": GOAL_DEFAULT}}
# The team node's outputs, read by the workflow's outputs the way a later node reads them.
OUTPUTS = {"decision": "build.structured.decision", "version": "build.structured.version",
           "views": "build.structured.views", "summary": "build.structured.summary",
           "rounds": "build.structured.rounds", "round": "build.structured.round"}


class Crash(BaseException):
    """The process dies here (nothing catches it on the way up)."""


@pytest.fixture
def tr(pw_run, team_on, monkeypatch, tmp_path):
    """A real in-process Temper with the team switched on, a git project as the run's
    workspace (an allowed project folder, M3 E5), and every member a scripted Pi."""
    from temper_ai.database import get_database

    ts.reset()
    Team.turn_runner = ts.fake_runner
    Team.stop_box = ts.Stopper()
    ls.project(pw_run.ws, {"app.py": "print('hello')\n"})
    ls.allow_projects(monkeypatch, tmp_path / "team-settings", str(pw_run.ws))
    pw_run.led = Ledger(get_database().engine)
    pw_run.led.ensure()
    pw_run.before = ss.threads_now()
    yield pw_run
    ts.reset()


# --- helpers ---------------------------------------------------------------------------------


def install(tr, *nodes: dict, inputs: dict | None = None, outputs: dict | None = None,
            agents: dict | None = None) -> None:
    """The workflow ``team_wf`` the run loads (a resume or a fork reads it as it is then)."""
    from temper_ai.stage.loader import GraphLoader

    workflow: dict = {"name": "team_wf", "nodes": list(nodes)}
    if inputs:
        workflow["inputs"] = inputs
    if outputs:
        workflow["outputs"] = outputs
    extra = {"workflow:team_wf": workflow, **BRIEF, **(agents or {})}
    tr.state.graph_loader = GraphLoader(tt.store(*nodes, extra=extra))


def start(tr, inputs: dict) -> str:
    r = tr.client.post("/api/runs", json={"workflow": "team_wf", "inputs": inputs,
                                          "workspace_path": str(tr.ws)})
    assert r.status_code == 200, r.text
    return r.json()["execution_id"]


def script(led: Ledger, decisions: list[str], *, last_views: str = "satisfied") -> None:
    """design's rounds: write a version and ask for a review; frontend and qa each give a view
    of it (changes, or ``last_views`` before a done); design decides each in its own turn."""
    design, frontend, qa = [], [], []
    for i, d in enumerate(decisions, 1):
        verdict = last_views if d == "done" else "changes"
        design.append([ls.write("README.md", README if d == "done" else f"# Tiny v{i}\n"),
                       ls.request_review(f"draft {i}")])
        frontend.append([ls.give_view(led, None, verdict, f"frontend note {i}")])
        qa.append([ls.give_view(led, None, verdict, f"qa note {i}")])
        design.append([ls.decide(led, None, d, f"summary {i}")])
    ts.SCRIPTS["design"], ts.SCRIPTS["frontend"], ts.SCRIPTS["qa"] = design, frontend, qa


def prompts() -> dict[str, int]:
    return {name: len(ts.PROMPTS[name]) for name in ("design", "frontend", "qa")}


def team_waits(tr, eid: str) -> list[dict]:
    return ls.table(tr.led, waits, eid, HOST)


def open_team_wait(tr, eid: str) -> dict:
    """The team's open owner wait, once it is asked (its row names its event)."""
    def find():
        rows = [w for w in team_waits(tr, eid) if w["state"] == "open"
                and w["gate_name"] == f"{HOST}~ask-{w['wait_id']}"]
        return rows[0] if rows else None
    return sup.wait_for(find, what=f"an open team wait in {eid}")


def parked_at(tr, eid: str, n_attempts: int, test: str) -> tuple[dict, dict]:
    """Attempt ``n_attempts`` let go at the team's open wait and nothing holds the run (PARK
    P1, counted the way PARK counted). Returns (the wait's row, the wait as GET .../gates
    lists it)."""
    attempt = pw.wait_parked(tr.state, eid, n_attempts=n_attempts)
    row = open_team_wait(tr, eid)
    note = pw.parked(attempt)
    gate = pw.open_gate(tr.client, eid, row["gate_name"])
    # the wait the owner is asked is the row's own id, at the team node's path
    assert note["wait_id"] == row["wait_id"] and note["path"] == HOST and note["node"] == "team"
    assert gate["event_id"] == note["event_id"] and gate["path"] == HOST
    counts = ss.held(tr.state, eid, before=tr.before, test=test, attempt=n_attempts,
                     wait_id=row["wait_id"], kind=row["kind"])
    assert ss.nothing_held(counts), counts
    return row, gate


def asked_after_its_row(eid: str, row: dict) -> None:
    """The wait's row was written before the owner was asked: its event came after the row."""
    (event,) = [e for e in ss.step_waits(eid, HOST)
                if (e.get("data") or {}).get("name") == row["gate_name"]]
    assert (event["data"]["step_wait"] or {}).get("wait_id") == row["wait_id"]
    assert _when(row["opened_at"]) <= _when(event["timestamp"]), (row["opened_at"],
                                                                    event["timestamp"])


def _when(value) -> datetime:
    return as_utc(value if isinstance(value, datetime) else datetime.fromisoformat(str(value)))


def answer(tr, eid: str, row: dict, gate: dict, text: str) -> dict:
    r = pw.approve(tr.client, eid, row["gate_name"], event_id=gate["event_id"], response=text)
    assert r.status_code == 200, r.text
    return r.json()


def _node_events(eid: str, name: str, type_: str) -> list[dict]:
    return [e for e in sup.events(eid, event_type="stage.started")
            if (e.get("data") or {}).get("name") == name
            and (e.get("data") or {}).get("type") == type_]


def stage_row(eid: str, name: str = "build") -> list[str]:
    """The stage's own row (its node event in the run's graph), one per attempt that ran it."""
    return [e["status"] for e in _node_events(eid, name, "stage")]


def team_row(eid: str) -> list[str]:
    """The team node's row inside the stage."""
    return [e["status"] for e in _node_events(eid, "team", "team")]


def stage_error(eid: str, name: str) -> str:
    """Every error the stage's rows and its team node's rows show, newest last."""
    rows = [e for e in sup.events(eid, event_type="stage.started")
            if (e.get("data") or {}).get("name") in (name, "team")]
    return " | ".join(str((e.get("data") or {}).get("error") or "") for e in rows)


def turns_by_member(tr, eid: str) -> dict[str, list[str]]:
    snap = ts.rows(tr.led, eid, HOST)
    who = {p["participant_id"]: p["member"] for p in snap["participants"]}
    out: dict[str, list[str]] = {}
    for t in sorted(snap["turns"], key=lambda t: (who[t["participant_id"]], t["turn_no"])):
        out.setdefault(who[t["participant_id"]], []).append(t["state"])
    return out


# --- a team stage runs -------------------------------------------------------------------------


def test_a_team_stage_runs_its_review_rounds_and_ends_on_the_reviewed_version(tr):
    """The leader writes, asks for a review, the others give their views, the leader decides;
    Temper records done on the reviewed version, and its record is the node's outputs."""
    install(tr, tt.team_stage(), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    attempts = pw.wait_ended(eid, 1)
    assert [a["status"] for a in attempts] == ["completed"], stage_error(eid, "build")
    assert stage_row(eid) == ["completed"] and team_row(eid) == ["completed"]

    out = attempts[-1]["data"]["workflow_output"]
    (_first, second) = ls.table(tr.led, reviews, eid, HOST)
    assert out["decision"] == "done" and out["rounds"] == 2 and out["round"] == 2
    assert out["version"]["commit"] == second["commit_sha"]
    assert out["version"]["files"]["README.md"] == hashlib.sha256(README.encode()).hexdigest()
    assert {m: v["verdict"] for m, v in out["views"].items()} == {"frontend": "satisfied",
                                                                   "qa": "satisfied"}
    assert out["summary"] == "summary 2"
    # every turn ran once; one conversation (participant, session) per member
    assert prompts() == {"design": 4, "frontend": 2, "qa": 2}
    assert turns_by_member(tr, eid) == {"design": ["completed"] * 4,
                                        "frontend": ["completed"] * 2, "qa": ["completed"] * 2}
    snap = ts.rows(tr.led, eid, HOST)
    assert sorted(p["member"] for p in snap["participants"]) == ["design", "frontend", "qa"]
    assert {p["ended_reason"] for p in snap["participants"]} == {"team_done"}
    # each message delivered exactly once, nothing left pending
    assert all(m["state"] == "consumed" and m["delivery_count"] == 1 for m in snap["messages"])
    assert team_waits(tr, eid) == []
    assert len(FakeBox.STARTS) == 8


# --- the pause (R2 B10, PARK P1 and P2) ---------------------------------------------------------


def test_b10_p1_the_pause_holds_no_worker_and_continue_carries_the_same_run_on(tr):
    """PARK P1: paused after round 1, nothing holds the run; the owner's continue carries the
    same run on, and no member turn that had finished runs again."""
    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "team_pause")
    assert row["kind"] == "pause" and row["subject"]["header"] == "pause-after-round-1"
    assert row["subject"]["options"] == ["continue", "guide", "stop"]
    asked_after_its_row(eid, row)
    assert prompts() == {"design": 2, "frontend": 1, "qa": 1}
    sessions = {p["member"]: p["session_id"] for p in ts.rows(tr.led, eid, HOST)["participants"]}
    seen = pw.detail(tr.client, eid)
    assert seen["status"] == "waiting" and seen.get("waiting_on_you") is True
    assert stage_row(eid) == ["waiting"] and team_row(eid) == ["waiting"]

    reply = answer(tr, eid, row, gate, "continue")
    assert reply["carries_on"] is True and reply["needs_resume"] is False
    attempts = pw.wait_ended(eid, 2)
    assert [a["status"] for a in attempts] == ["parked", "completed"], stage_error(eid, "build")
    # carried on in the same run: no finished turn ran again, the same conversations went on
    assert prompts() == {"design": 4, "frontend": 2, "qa": 2}
    assert turns_by_member(tr, eid) == {"design": ["completed"] * 4,
                                        "frontend": ["completed"] * 2, "qa": ["completed"] * 2}
    after = {p["member"]: p["session_id"] for p in ts.rows(tr.led, eid, HOST)["participants"]}
    assert after == sessions
    (decided,) = team_waits(tr, eid)
    assert decided["wait_id"] == row["wait_id"] and decided["state"] == "decided"
    assert decided["decision"]["answer"] == "continue"
    out = attempts[-1]["data"]["workflow_output"]
    assert out["decision"] == "done" and out["round"] == 2


def _team_view(tr, eid: str) -> list[dict]:
    """The team's story as the run page gets it: the team node inside the stage, latest attempt."""
    page = tr.client.get(f"/api/workflows/{eid}")
    assert page.status_code == 200, page.text
    (stage,) = [n for n in page.json()["nodes"] if n["name"] == "build"]
    (team,) = [n for n in stage["child_nodes"] if n["name"] == "team"]
    return team["collaboration_events"]


def test_the_run_view_shows_messages_reviews_the_pause_its_answer_and_the_decision(tr):
    """The brief's run view: messages sender to receiver, each review round with its views, the
    pause with the owner's answer, and the decision, on the team node's row (the stage view's
    Collaboration fold), while paused and after a reload."""
    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "team_view")
    paused = _team_view(tr, eid)
    (wait,) = [e for e in paused if e["event_type"] == "owner wait: pause"]
    assert wait["data"]["wait_id"] == row["wait_id"] and wait["data"]["state"] == "open"
    assert "answer" not in wait["data"]

    answer(tr, eid, row, gate, "continue")
    assert [a["status"] for a in pw.wait_ended(eid, 2)] == ["parked", "completed"]
    view = _team_view(tr, eid)
    kinds = [e["event_type"] for e in view]
    # messages, sender to receiver, each with its id, delivered once
    msgs = [e for e in view if e["event_type"].startswith("message: ")]
    snap = ts.rows(tr.led, eid, HOST)
    assert sorted(e["data"]["message_id"] for e in msgs) == sorted(
        m["message_id"] for m in snap["messages"])
    (goal,) = [e for e in msgs if e["event_type"] == "message: goal"]
    assert goal["from_agent"] == "temper" and goal["to_agent"] == "design"
    asks = [e for e in msgs if e["event_type"] == "message: review_request"]
    assert sorted(e["to_agent"] for e in asks) == ["frontend", "frontend", "qa", "qa"]
    # Temper asks: it pinned the version the leader's request names
    assert all(e["from_agent"] == "temper" and e["data"]["review_id"] for e in asks)
    views = [e for e in msgs if e["event_type"] == "message: view"]
    assert sorted(e["from_agent"] for e in views) == ["frontend", "frontend", "qa", "qa"]
    assert all(e["to_agent"] == "design" and e["data"]["deliveries"] == 1 for e in msgs
               if e in views)
    # each review round with its version and views; the pause with its answer; the decision
    first, second = ls.table(tr.led, reviews, eid, HOST)
    r1, r2 = [e for e in view if e["event_type"].startswith("review round ")]
    assert r1["data"]["commit"] == first["commit_sha"] and r1["data"]["decision"] == "keep_going"
    assert {m: v["verdict"] for m, v in r1["data"]["views"].items()} == {
        "frontend": "changes", "qa": "changes"}
    assert {m: v["verdict"] for m, v in r2["data"]["views"].items()} == {
        "frontend": "satisfied", "qa": "satisfied"}
    (wait,) = [e for e in view if e["event_type"] == "owner wait: pause"]
    assert wait["data"] == {**wait["data"], "wait_id": row["wait_id"], "state": "decided",
                            "answer": "continue", "round": 1}
    assert wait["from_agent"] == "temper" and wait["to_agent"] == "owner"
    (done,) = [e for e in view if e["event_type"] == "decision: done"]
    assert done["data"]["commit"] == second["commit_sha"] and done["data"]["round"] == 2
    # in the order it happened: round 1, its keep-going, the pause, round 2, done
    order = [k for k in kinds if not k.startswith("message: ")]
    assert order == ["review round 1", "decision: keep_going", "owner wait: pause",
                     "review round 2", "decision: done"], order


def test_b10_p2_two_pauses_in_one_go_each_ask_the_owner_and_stop_ends_it_cancelled(tr):
    """PARK P2: the go the owner's continue starts reaches a second pause, which asks the owner
    again under its own wait id (the first answer is not reused). Stop then ends the run
    cancelled (M3 E18: an owner's stop is a decision, not a failure): stopped, never done."""
    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    first, gate1 = parked_at(tr, eid, 1, "team_pause_1")
    assert answer(tr, eid, first, gate1, "continue")["carries_on"] is True

    second, gate2 = parked_at(tr, eid, 2, "team_pause_2")
    assert second["wait_id"] != first["wait_id"]
    assert second["subject"]["header"] == "pause-after-round-2"
    asked_after_its_row(eid, first)
    asked_after_its_row(eid, second)
    assert len(ss.step_waits(eid, HOST)) == 2
    assert prompts() == {"design": 4, "frontend": 2, "qa": 2}

    assert answer(tr, eid, second, gate2, "stop")["carries_on"] is True
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "cancelled"]
    assert stage_row(eid)[-1] == "cancelled" and team_row(eid)[-1] == "cancelled"
    assert "stopped at the pause after round 2" in stage_error(eid, "build")
    assert "Workflow cancelled by user" not in str(attempts[-1])
    # the stop is recorded the way done is, as stopped (the node's outputs say so)
    assert attempts[-1]["data"]["workflow_output"]["decision"] == "stopped"
    snap = ts.rows(tr.led, eid, HOST)
    assert {p["ended_reason"] for p in snap["participants"]} == {"team_stopped"}
    assert [r["decision"] for r in ls.table(tr.led, reviews, eid, HOST)] == ["keep_going"] * 2
    assert prompts() == {"design": 4, "frontend": 2, "qa": 2}  # nothing ran after the stop


def test_a_pause_that_cannot_park_holds_its_worker_and_a_cancel_there_ends_the_team(
        tr, monkeypatch):
    """When where the run waits cannot be saved, ask_owner holds the worker (step_waits.park
    returns None), as any wait outside a Pi workflow does. A cancel then reaches the team inside
    the ask, not at a parked run's cancel: the team ends there all the same (R2 B12), its wait
    cancelled, nothing left to deliver, and the run ends cancelled, never done."""
    from temper_ai.checkpoint.service import CheckpointService

    def cannot_save(self, *args, **kwargs):
        raise RuntimeError("the checkpoint store is full")

    monkeypatch.setattr(CheckpointService, "save_wait_parked", cannot_save)
    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row = open_team_wait(tr, eid)
    gate = pw.open_gate(tr.client, eid, row["gate_name"])
    assert row["kind"] == "pause" and gate["path"] == HOST
    # held, not parked: the run's one attempt is still going
    assert [a["status"] for a in pw.attempts(eid)] == ["running"]
    assert prompts() == {"design": 2, "frontend": 1, "qa": 1}

    r = tr.client.post(f"/api/runs/{eid}/cancel", json={"reason": "stop it"})
    assert r.status_code == 200, r.text
    attempts = pw.wait_ended(eid, 1, timeout=30)
    assert attempts[-1]["status"] == "cancelled"
    snap = ts.rows(tr.led, eid, HOST)
    assert {p["ended_reason"] for p in snap["participants"]} == {"run_cancelled"}
    assert not [m for m in snap["messages"] if m["state"] in ("pending", "held")]
    assert [(w["wait_id"], w["state"]) for w in team_waits(tr, eid)] == [
        (row["wait_id"], "cancelled")]
    assert "done" not in [r["decision"] for r in ls.table(tr.led, reviews, eid, HOST)]
    assert stage_row(eid)[-1] != "completed" and team_row(eid)[-1] != "completed"
    assert prompts() == {"design": 2, "frontend": 1, "qa": 1}  # nothing ran after the cancel


# --- failures are red (R2 B13, M2-roles P2) ---------------------------------------------------


HELD_FAIL_TYPE = "pi_team_held_fail"


class _Handshake:
    """Orders two stages that run side by side: the failing lane starts, then the team's first
    turn runs, then the lane fails. Without it the lane could fail first and stop the run before
    the team started (a race that once showed the team's stage row completed)."""

    def __init__(self) -> None:
        import threading

        self.lane_started = threading.Event()
        self.turn_done = threading.Event()


HANDSHAKE = _Handshake()


def _held_fail_agent():
    from temper_ai.agent.base import AgentABC
    from temper_ai.shared.types import AgentResult, Status

    class HeldFailAgent(AgentABC):
        def run(self, input_data, context):
            HANDSHAKE.lane_started.set()
            HANDSHAKE.turn_done.wait(30)
            pw.RAN[self.name] += 1
            return AgentResult(status=Status.FAILED, output="", error=f"{self.name} failed")

    return HeldFailAgent


def test_b13_a_failed_team_fails_its_stage_row_and_the_run_while_other_stages_stay_tolerant(
        tr):
    """Control run 41177ca4's case: the team node failed but its stage row showed completed.
    Now a failed team node fails its stage, and the run; a parallel stage with one failed lane
    still completes as before (the two stages run side by side)."""
    from temper_ai.agent import AGENT_TYPES, register_agent_type

    global HANDSHAKE
    HANDSHAKE = _Handshake()
    register_agent_type(HELD_FAIL_TYPE, _held_fail_agent())

    def after_the_lane(cfg, req, ledger):
        assert HANDSHAKE.lane_started.wait(30)
        try:
            return ts.fake_runner(cfg, req, ledger)
        finally:
            HANDSHAKE.turn_done.set()

    Team.turn_runner = after_the_lane
    review = {"name": "review", "type": "stage", "strategy": "parallel", "agents": ["ok", "bad"]}
    install(tr, review, tt.team_stage(),
            agents={"agent:ok": {"name": "ok", "type": sup.STEP_TYPE},
                    "agent:bad": {"name": "bad", "type": HELD_FAIL_TYPE}})
    ts.SCRIPTS["design"] = [[{"error": "400 invalid_request_error: the request was refused"}]]
    try:
        eid = start(tr, {"goal": GOAL})
        attempts = pw.wait_ended(eid, 1)
    finally:
        HANDSHAKE.turn_done.set()
        AGENT_TYPES.pop(HELD_FAIL_TYPE, None)
    assert attempts[-1]["status"] == "failed"
    assert pw.RAN["bad"] == 1  # the lane ran and failed
    assert stage_row(eid, "review") == ["completed"]  # the tolerant rule, unchanged
    assert stage_row(eid) == ["failed"] and team_row(eid) == ["failed"]
    assert "design (architecture) turn 1 failed" in stage_error(eid, "build")
    assert turns_by_member(tr, eid) == {"design": ["failed"]}
    assert prompts() == {"design": 1, "frontend": 0, "qa": 0}


# --- M3 F1: the owner's pick at a recovery wait, through the approve route --------------------


CUT_OFF = [ts.send("frontend", "an early note"), {"die": True}]  # sent, then the worker dies
REFUSED = [{"error": "400 invalid_request_error: the request was refused"}]


def pick(tr, eid: str, row: dict, gate: dict, *selected: str, custom: str = "") -> dict:
    """The owner answers on the run page: a picked option and/or written words (GateModal's
    ``answers``), no typed response; nothing at all is a plain approval."""
    r = pw.pick(tr.client, eid, row["gate_name"], *selected, event_id=gate["event_id"],
                question=row["subject"]["question"], custom=custom)
    assert r.status_code == 200, r.text
    return r.json()


def recovery_decisions(tr, eid: str) -> list:
    rows = sorted((w for w in team_waits(tr, eid) if w["kind"] == "recovery"),
                  key=lambda w: _when(w["opened_at"]))
    return [(w["decision"] or {}).get("recovery") for w in rows]


def test_f1_retry_picked_at_a_cut_off_turn_runs_it_again(tr):
    """Picking "retry" on the run page at a cut-off turn's wait retries the turn; it was read
    as accept while the rendered answer ("Q: ...\\nA: retry") was read."""
    install(tr, tt.team_stage())
    script(tr.led, ["done"])
    ts.SCRIPTS["design"].insert(0, CUT_OFF)
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "f1_cut_off_retry")
    assert (row["kind"], row["subject"]["options"]) == ("recovery", ["accept", "retry"])

    assert pick(tr, eid, row, gate, "retry")["carries_on"] is True
    assert pw.wait_ended(eid, 2)[-1]["status"] == "completed", stage_error(eid, "build")
    assert recovery_decisions(tr, eid) == ["retry"]
    assert turns_by_member(tr, eid)["design"][0] == "superseded"
    early = ts.message(tr.led, eid, ts.SENDS[0]["reply"]["message_id"])
    assert (early["state"], early["undelivered_reason"]) == ("undelivered", "turn_superseded")
    assert stage_row(eid)[-1] == "completed" and team_row(eid)[-1] == "completed"


def test_f1_retry_picked_at_a_failed_turn_runs_it_again(tr):
    """After a Resume, picking "retry" at a failed turn's wait retries it; it was read as stop
    and ended the team."""
    install(tr, tt.team_stage())
    script(tr.led, ["done"])
    ts.SCRIPTS["design"].insert(0, REFUSED)
    eid = start(tr, {"goal": GOAL})
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    assert tr.client.post(f"/api/runs/{eid}/resume", json={}).status_code == 200
    row, gate = parked_at(tr, eid, 2, "f1_failed_retry")
    assert (row["kind"], row["subject"]["options"]) == ("recovery", ["retry", "stop"])

    assert pick(tr, eid, row, gate, "retry")["carries_on"] is True
    assert pw.wait_ended(eid, 3)[-1]["status"] == "completed", stage_error(eid, "build")
    assert recovery_decisions(tr, eid) == ["retry"]
    assert turns_by_member(tr, eid)["design"][0] == "superseded"
    assert stage_row(eid)[-1] == "completed" and team_row(eid)[-1] == "completed"


def test_f1_an_answer_naming_no_choice_never_accepts_or_stops_and_is_asked_again(tr):
    """A plain approval, or words naming no choice, decide nothing at a recovery wait: the turn
    and what it sent stay held, the team goes on waiting, and the owner is asked again at a
    new wait for the same turn. A picked retry then runs it again."""
    install(tr, tt.team_stage())
    script(tr.led, ["done"])
    ts.SCRIPTS["design"].insert(0, CUT_OFF)
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "f1_no_choice_1")
    held = ts.SENDS[0]["reply"]["message_id"]

    assert pick(tr, eid, row, gate)["carries_on"] is True  # approved with nothing said
    second, gate2 = parked_at(tr, eid, 2, "f1_no_choice_2")
    assert pick(tr, eid, second, gate2, custom="not sure yet")["carries_on"] is True
    third, gate3 = parked_at(tr, eid, 3, "f1_no_choice_3")

    assert len({row["wait_id"], second["wait_id"], third["wait_id"]}) == 3
    for again in (second, third):
        assert again["kind"] == "recovery"
        assert again["subject"]["turn_id"] == row["subject"]["turn_id"]
        assert again["subject"]["options"] == ["accept", "retry"]
        assert again["subject"]["question"] == ("That answer was not one of: accept, retry, "
                                                 "stop. Nothing was decided. "
                                                 + row["subject"]["question"])
    assert third["subject"]["asked_again"] == 2
    assert recovery_decisions(tr, eid) == ["invalid", "invalid", None]
    assert turns_by_member(tr, eid) == {"design": ["uncertain"]}, "not accepted, not stopped"
    assert ts.message(tr.led, eid, held)["state"] == "held", "what it sent was not released"
    assert prompts() == {"design": 1, "frontend": 0, "qa": 0}

    assert pick(tr, eid, third, gate3, "retry")["carries_on"] is True
    assert pw.wait_ended(eid, 4)[-1]["status"] == "completed", stage_error(eid, "build")
    assert recovery_decisions(tr, eid) == ["invalid", "invalid", "retry"]
    assert ts.message(tr.led, eid, held)["undelivered_reason"] == "turn_superseded"


# --- the first node, through a resume and restarts --------------------------------------------


def test_a_team_node_first_in_its_workflow_parks_survives_restarts_and_carries_on(tr):
    """A team node may be the workflow's first node (most team workflows are one stage): its
    pause parks, a resume waits on the same wait (asked once), restarts leave it put, and the
    owner's answer carries it on to done."""
    from temper_ai.observability.reconcile import reconcile_and_report
    from temper_ai.runner import parked

    install(tr, tt.team_stage(strategy_config=PAUSE_1))
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "team_first_node")

    r = tr.client.post(f"/api/runs/{eid}/resume", json={})
    assert r.status_code == 200, r.text
    again, gate_again = parked_at(tr, eid, 2, "team_first_node_resumed")
    assert again["wait_id"] == row["wait_id"] and gate_again["event_id"] == gate["event_id"]
    assert len(ss.step_waits(eid, HOST)) == 1, "the same wait, not a second one"
    assert prompts() == {"design": 2, "frontend": 1, "qa": 1}

    for _restart in range(2):
        marked = reconcile_and_report(started_before=utcnow())
        assert eid not in [m["execution_id"] for m in marked], "not marked interrupted"
        assert eid not in str(sup.restart_service(now=utcnow(), marked=marked))
        assert parked.carry_on_at_startup() == [], "no answer: it stays put"
    assert [a["status"] for a in pw.attempts(eid)] == ["parked", "waiting"]

    assert answer(tr, eid, again, gate_again, "continue")["carries_on"] is True
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "completed"]
    assert prompts() == {"design": 4, "frontend": 2, "qa": 2}
    assert stage_row(eid)[-1] == "completed" and team_row(eid)[-1] == "completed"


# --- the node's own start check (M2 binding, #40) --------------------------------------------


@pytest.fixture
def node_checks(monkeypatch):
    """The goal each check_team call made by the team node itself saw (not the run-start
    check's calls)."""
    from temper_ai.pi_agent import team_check

    seen: list = []
    real = team_check.check_team

    def spy(*args, **kwargs):
        frame = inspect.currentframe()
        caller = frame.f_back.f_code.co_name if frame and frame.f_back else ""
        if caller == "run_team_node":
            seen.append((kwargs.get("inputs") or {}).get("goal"))
        return real(*args, **kwargs)

    monkeypatch.setattr(team_check, "check_team", spy)
    return seen


def test_a_left_out_goal_reaches_the_nodes_own_check_with_its_default_at_start_resume_and_fork(
        tr, node_checks):
    """The goal input has a declared default and the run starts without it. The team node's
    own start check sees the default at a fresh start, after a resume (the Resume button, and
    the owner's answer carrying the run on) and after a fork (which loads without the run-start
    check and counts as a resume)."""
    install(tr, BRIEF_NODE, tt.team_stage(strategy_config=PAUSE_1, depends_on=["brief"]),
            inputs=DEFAULTED)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {})
    row, _gate = parked_at(tr, eid, 1, "team_default_goal")
    assert node_checks == [GOAL_DEFAULT]
    assert any(GOAL_DEFAULT in p for p in ts.PROMPTS["design"][:1])  # the brief the leader got

    assert tr.client.post(f"/api/runs/{eid}/resume", json={}).status_code == 200
    row, gate = parked_at(tr, eid, 2, "team_default_goal_resumed")
    assert node_checks == [GOAL_DEFAULT] * 2
    assert answer(tr, eid, row, gate, "continue")["carries_on"] is True
    assert pw.wait_ended(eid, 3)[-1]["status"] == "completed"
    assert node_checks == [GOAL_DEFAULT] * 3
    assert pw.RAN["brief"] == 1

    (brief_done,) = [cp for cp in ss.checkpoints(tr.client, eid, "node_completed")
                     if cp["node_name"] == "brief"]
    script(tr.led, ["done"])
    r = tr.client.post("/api/runs/fork", json={
        "workflow": "team_wf", "source_execution_id": eid, "sequence": brief_done["sequence"],
        "inputs": {}, "workspace_path": str(tr.ws)})
    assert r.status_code == 200, r.text
    fork = r.json()["execution_id"]
    assert pw.wait_ended(fork, 1)[-1]["status"] == "completed", stage_error(fork, "build")
    assert node_checks == [GOAL_DEFAULT] * 4
    assert pw.RAN["brief"] == 1  # the fork restored it


BAD_CONFIGS = {
    # R2 B7: edges stay refused when the node starts, as at run start
    "edges": ({"strategy_config": {**tt.GOOD, "pause_after_rounds": 1}}, {},
              "communication: edges isn't built yet; use all"),
    # M2 binding B8: one member per role
    "same_role": ({"agents": ["design", "design2", "qa"]},
                  {"agent:design2": {"name": "design2", "type": "pi", "role": "architecture"}},
                  "same role 'architecture' as member 'design'"),
    # T4T5 N3: a member may not be named like one of Temper's own ids
    "reserved_name": ({"agents": ["design", "owner", "qa"]},
                      {"agent:owner": {"name": "owner", "type": "pi", "role": "frontend"}},
                      "member 'owner'"),
    # R2 B10: a team stage has no timeout (it would end the pause); the stage itself refuses it,
    # before its team node runs
    "stage_timeout": ({"timeout_seconds": 600}, {}, "timeout_seconds is not allowed here"),
}


def _refused_red(eid: str, which: str, problem: str, team_rows_before: int,
                 sentence: str = "the team can't start: ") -> None:
    """The attempt's stage row failed, naming the problem; the team node failed with it, or
    (a stage timeout) never ran at all. ``sentence`` is A3's: "can't start" before any turn of
    this team began, "can't go on" once one had."""
    assert stage_row(eid)[-1] == "failed"
    error = stage_error(eid, "build")
    assert problem in error, error
    if which == "stage_timeout":
        assert len(team_row(eid)) == team_rows_before  # the stage refused before its node ran
    else:
        assert team_row(eid)[-1] == "failed" and sentence in error, error


def _bad(tr, which: str, *, depends_on=("brief",)) -> str:
    over, agents, problem = BAD_CONFIGS[which]
    stage = tt.team_stage(depends_on=list(depends_on), **over)
    install(tr, BRIEF_NODE, stage, agents=agents)
    return problem


@pytest.mark.parametrize("which", sorted(BAD_CONFIGS))
def test_a_resume_with_a_bad_team_config_fails_red_before_any_member_is_set_up(tr, which):
    """A resume runs the workflow config as it is now, and never gets the run-start check: the
    team node checks again when it starts and fails red, listing the problem, before any member
    turn or box. Turns of this team ran before the pause, so it reads "can't go on" (A3)."""
    install(tr, BRIEF_NODE, tt.team_stage(strategy_config=PAUSE_1, depends_on=["brief"]))
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, f"team_bad_resume_{which}")
    before = (prompts(), len(FakeBox.STARTS))
    team_rows = len(team_row(eid))

    problem = _bad(tr, which)
    assert answer(tr, eid, row, gate, "continue")["carries_on"] is True
    attempts = pw.wait_ended(eid, 2)
    assert [a["status"] for a in attempts] == ["parked", "failed"]
    _refused_red(eid, which, problem, team_rows, "the team can't go on: ")
    assert "the team can't start" not in stage_error(eid, "build")
    assert (prompts(), len(FakeBox.STARTS)) == before


@pytest.mark.parametrize("which", [*sorted(BAD_CONFIGS), "no_goal"])
def test_a_fork_with_a_bad_team_config_or_goal_fails_red_before_any_member_is_set_up(tr, which):
    """A fork loads the workflow without the run-start check and starts with the source's
    finished results (it counts as a resume): the team node's own check refuses it red, before
    any member of the fork's team is set up."""
    install(tr, BRIEF_NODE, tt.team_stage(depends_on=["brief"]))
    script(tr.led, ["done"])
    eid = start(tr, {"goal": GOAL})
    assert pw.wait_ended(eid, 1)[-1]["status"] == "completed", stage_error(eid, "build")
    (brief_done,) = [cp for cp in ss.checkpoints(tr.client, eid, "node_completed")
                     if cp["node_name"] == "brief"]
    before = (prompts(), len(FakeBox.STARTS))

    if which == "no_goal":  # no goal given and none declared: the node's check names it
        install(tr, BRIEF_NODE, tt.team_stage(depends_on=["brief"]))
        problem = "goal: "
    else:
        problem = _bad(tr, which)
    r = tr.client.post("/api/runs/fork", json={
        "workflow": "team_wf", "source_execution_id": eid, "sequence": brief_done["sequence"],
        "inputs": {}, "workspace_path": str(tr.ws)})
    assert r.status_code == 200, r.text
    fork = r.json()["execution_id"]
    assert pw.wait_ended(fork, 1)[-1]["status"] == "failed"
    _refused_red(fork, which, problem, 0)
    assert (prompts(), len(FakeBox.STARTS)) == before
    assert ts.rows(tr.led, fork, HOST)["participants"] == []


# --- G-a: ending a cancelled run's team can be re-run ----------------------------------------


def _parked_team_rows(pw_run, eid: str) -> dict:
    """A parked team's rows (as pi_parking/test_team_cancel.py makes them): the lead's turn cut
    off after it sent a message (held), its recovery wait open, mail pending for the builder."""
    from temper_ai.database import get_database

    led = Ledger(get_database().engine)
    led.ensure()
    team = ts.open_team(led, sup.box_config(pw_run.tmp / "team-box"), run_id=eid)
    team.post("lead", "Write the README.", sender="temper", sender_kind="temper", kind="goal",
              dedupe_key=f"{eid}:goal")
    queued = team.post("builder", "the builder's mail")
    turn, _batch, binding = ts.claim_bound(led, eid)
    held = led.member_send(binding, ts.info("checker", "a note the lead sent"))
    wait = led.hold_turn(turn["turn_id"], "the service stopped during the turn", [], None,
                         "attempt-1", epoch=turn["epoch"])
    assert wait and held["ok"]
    return {"queued": queued["message_id"], "held": held["message_id"], "wait": wait["wait_id"]}


def _sweep_at_startup(_pw_run) -> None:
    from temper_ai.runner import parked

    assert parked.carry_on_at_startup() == []


def _sweep_in_trim(_pw_run) -> None:
    from temper_ai.database import get_session
    from temper_ai.observability.trim import TrimPolicy, run_trim

    with get_session() as session:
        run_trim(session, TrimPolicy(), now=utcnow())


def _sweep_at_team_open(pw_run) -> None:
    """Another team run opens its team: its node sweeps first (temper_ai/pi_agent/team_leader.py
    run_team_node)."""
    install(pw_run, tt.team_stage())
    script(pw_run.led, ["done"])
    other = start(pw_run, {"goal": GOAL})
    assert pw.wait_ended(other, 1)[-1]["status"] == "completed", stage_error(other, "build")


@pytest.mark.parametrize("sweep", [_sweep_at_startup, _sweep_in_trim, _sweep_at_team_open],
                         ids=["startup", "trim", "team_open"])
def test_g_a_a_crash_between_ending_the_run_and_ending_its_team_is_swept_up_later(
        tr, monkeypatch, sweep):
    """#37's land check binding 4: a cancel ends the run's row, then its teams. The process
    dies between the two writes; the next sweep (start-up, the trim sweep, a team's open)
    ends the team: held and queued messages recorded undelivered, never dropped (B12)."""
    from temper_ai.runner import parked

    c = tr.client
    eid = sup.start(c, "pw_before_pi", tr.ws)
    pw.wait_parked(tr.state, eid)
    pw.open_gate(c, eid, "check")
    ids = _parked_team_rows(tr, eid)

    def die(execution_id: str) -> None:
        raise Crash(execution_id)

    with monkeypatch.context() as m:
        m.setattr(parked, "_end_pi_teams", die)
        with pytest.raises(Crash):
            parked.cancel_parked(eid, "not this one")
    assert [a["status"] for a in pw.attempts(eid)] == ["cancelled"]  # the run's row ended
    msg = {m["message_id"]: m for m in ts.rows(tr.led, eid)["messages"]}
    assert (msg[ids["held"]]["state"], msg[ids["queued"]]["state"]) == ("held", "pending")

    sweep(tr)

    msg = {m["message_id"]: m for m in ts.rows(tr.led, eid)["messages"]}
    assert (msg[ids["held"]]["state"], msg[ids["held"]]["undelivered_reason"]) == (
        "undelivered", "turn_cancelled")
    assert (msg[ids["queued"]]["state"], msg[ids["queued"]]["undelivered_reason"]) == (
        "undelivered", "run_cancelled")
    (wait,) = ts.rows(tr.led, eid)["waits"]
    assert (wait["wait_id"], wait["state"]) == (ids["wait"], "cancelled")
    assert {(p["state"], p["ended_reason"]) for p in tr.led.participants_of(eid, ts.HOST)} == {
        ("ended", "run_cancelled")}
    ts.check_invariants(tr.led, eid)


# --- the Pi switch goes off (M4 ADR-M4-05: SW-09, SW-32) --------------------------------------


@contextlib.contextmanager
def switched_off(monkeypatch):
    """The server as it is after a restart with the Pi switch off: no ``TEMPER_PI_AGENT``, so
    no ``team`` strategy and no ``pi`` agent type. Leaving the block switches it back on."""
    from temper_ai.agent import AGENT_TYPES
    from temper_ai.pi_agent import AGENT_TYPE, SWITCH_ENV
    from temper_ai.pi_agent.team import STRATEGY
    from temper_ai.stage import topology

    with monkeypatch.context() as m:
        m.delenv(SWITCH_ENV, raising=False)
        for registry in (topology._GENERATORS, topology._VALIDATORS, topology._RUN_START_CHECKS):
            if STRATEGY in registry:
                m.delitem(registry, STRATEGY)
        if AGENT_TYPE in AGENT_TYPES:
            m.delitem(AGENT_TYPES, AGENT_TYPE)
        yield


@pytest.mark.parametrize("back_on", ["resume", "start-up"])
def test_sw32_a_team_run_parked_when_pi_goes_off_waits_visibly_and_carries_on_once_back_on(
        tr, monkeypatch, back_on):
    """M4 SW-32: park; the switch goes off; the owner answers. The answer is kept and the run
    waits, never failing with "Unknown strategy 'team'" (what loading it now says): the
    answer, start-up and the worker's reaper each leave it put, and the answer's reply, the run
    page and Resume's refusal say "Pi switched off". Switched back on, Resume or the next
    start-up carries it on with the kept answer, and no finished turn runs again."""
    from temper_ai.runner import parked

    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row, gate = parked_at(tr, eid, 1, "sw32_" + back_on)

    with switched_off(monkeypatch):
        with pytest.raises(Exception, match="Unknown strategy"):
            tr.state.graph_loader.load_workflow("team_wf")
        reply = answer(tr, eid, row, gate, "continue")
        assert (reply["carries_on"], reply["needs_resume"], reply["pi_switched_off"]) == (
            False, False, True)
        assert reply["message"] == parked.PI_SWITCHED_OFF
        refused = tr.client.post(f"/api/runs/{eid}/resume", json={})
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == parked.PI_SWITCHED_OFF
        assert parked.carry_on_at_startup() == []
        assert parked.carry_on(eid, start=parked.queue_resume, by="reaper") is False
        seen = pw.detail(tr.client, eid)
        assert seen["status"] == "waiting" and seen["pi_switched_off"] == parked.PI_SWITCHED_OFF
        assert [a["status"] for a in pw.attempts(eid)] == ["waiting"]
        assert prompts() == {"design": 2, "frontend": 1, "qa": 1}

    assert "pi_switched_off" not in pw.detail(tr.client, eid)
    if back_on == "resume":
        r = tr.client.post(f"/api/runs/{eid}/resume", json={})
        assert r.status_code == 200, r.text
    else:
        assert parked.carry_on_at_startup() == [eid]
    attempts = pw.wait_ended(eid, 2)
    assert [a["status"] for a in attempts] == ["parked", "completed"], stage_error(eid, "build")
    assert prompts() == {"design": 4, "frontend": 2, "qa": 2}
    (decided,) = team_waits(tr, eid)
    assert decided["wait_id"] == row["wait_id"] and decided["decision"]["answer"] == "continue"
    assert attempts[-1]["data"]["workflow_output"]["decision"] == "done"


def test_sw09_a_cancel_while_pi_is_switched_off_leaves_the_team_for_the_sweep_once_back_on(
        tr, monkeypatch):
    """M4 SW-09 (T4T5 G-a, also while the switch is off): a parked run cancelled while the
    switch is off ends at once, but its team is left exactly as it was -- nothing Pi runs while
    off, and no sweep touches it then. Once the switch is back on, start-up's sweep ends the
    team (held and queued messages recorded undelivered, never dropped), and sweeping again
    changes nothing."""
    from temper_ai.runner import parked

    c = tr.client
    eid = sup.start(c, "pw_before_pi", tr.ws)
    pw.wait_parked(tr.state, eid)
    pw.open_gate(c, eid, "check")
    ids = _parked_team_rows(tr, eid)
    before = ts.rows(tr.led, eid)

    with switched_off(monkeypatch):
        assert parked.cancel_parked(eid, "not this one") is True
        assert [a["status"] for a in pw.attempts(eid)] == ["cancelled"]
        assert parked.carry_on_at_startup() == []
        _sweep_in_trim(tr)
        assert ts.rows(tr.led, eid) == before

    assert parked.carry_on_at_startup() == []
    after = ts.rows(tr.led, eid)
    msg = {m["message_id"]: m for m in after["messages"]}
    assert (msg[ids["held"]]["state"], msg[ids["held"]]["undelivered_reason"]) == (
        "undelivered", "turn_cancelled")
    assert (msg[ids["queued"]]["state"], msg[ids["queued"]]["undelivered_reason"]) == (
        "undelivered", "run_cancelled")
    (wait,) = after["waits"]
    assert (wait["wait_id"], wait["state"]) == (ids["wait"], "cancelled")
    assert {(p["state"], p["ended_reason"]) for p in tr.led.participants_of(eid, ts.HOST)} == {
        ("ended", "run_cancelled")}
    _sweep_in_trim(tr)
    assert parked.carry_on_at_startup() == []
    assert ts.rows(tr.led, eid) == after
    ts.check_invariants(tr.led, eid)
