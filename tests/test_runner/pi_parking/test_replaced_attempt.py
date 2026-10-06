"""SW-84: an attempt whose held wait a later attempt of the run took over stands down.

The wait could not be saved, so the step held its worker there (hold mode). A later attempt
of the same run took the wait over (``replaced``) and is mid-turn in the same conversation.
The old attempt must not retry its step: a retry would take the conversation's turns over and
fence the newer attempt's live turn (raise its epoch, stop its box, put it to the owner as
cut off). It stands down instead, and writes down only its own ending. A team step's held ask
is the same: before SW-84 the old attempt ended the team -- the newer attempt's -- as
cancelled. Runs on SQLite and on the Postgres tier.
"""

from __future__ import annotations

import uuid

import pytest

from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType
from temper_ai.pi_agent.host import PiHost
from temper_ai.pi_agent.team_runtime import Team
from temper_ai.runner.attempts import attempt_of, later_attempts, stand_down_if_replaced
from temper_ai.shared.clock import utcnow
from temper_ai.stage.exceptions import REPLACED_MARK, ReplacedByLaterAttempt
from temper_ai.stage.gate import REPLACED, WAITING
from tests.test_pi_agent import support as sup
from tests.test_pi_agent import test_team as tt
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking import test_team_runs as runs
from tests.test_runner.pi_parking.test_team_runs import (
    GOAL,
    HOST,
    OUTPUTS,
    PAUSE_1,
    install,
    open_team_wait,
    prompts,
    script,
    start,
    team_waits,
)
from tests.test_runner.pi_team import support as ts

team_on = tt.team_on
tr = runs.tr


def test_an_attempt_knows_the_attempts_that_started_after_it(pw_run):
    """runner/attempts.py, which both stand-down checks use: an event is placed under its
    attempt's ``workflow.started`` through its stage graphs; the attempts that started after
    one are named with every event of their trees (what a Pi turn records as its attempt);
    only an attempt that is not the run's newest stands down; an id that can't be placed
    changes nothing."""
    eid = f"run-attempts-{uuid.uuid4().hex[:8]}"
    rec = EventRecorder(eid)

    def started() -> str:
        return rec.record(EventType.WORKFLOW_STARTED, data={"name": "w"}, execution_id=eid,
                          status="running")

    def under(parent: str, name: str) -> str:
        return rec.record(EventType.STAGE_STARTED, data={"name": name}, parent_id=parent,
                          execution_id=eid, status="running")

    first = started()
    first_graph = under(first, "build")
    first_step = under(first_graph, "team")
    second = started()
    second_graph = under(second, "build")
    second_step = under(second_graph, "team")

    assert (attempt_of(eid, first_step), attempt_of(eid, second_graph)) == (first, second)
    assert later_attempts(eid, first_graph) == {second, second_graph, second_step}
    assert later_attempts(eid, second_step) == frozenset()
    with pytest.raises(ReplacedByLaterAttempt, match=f"{second}.*stands down before it"):
        stand_down_if_replaced(eid, first_step, where="before it takes its turns over")
    stand_down_if_replaced(eid, second_step, where="at the newest attempt")  # carries on
    assert attempt_of(eid, "attempt-made-up") is None
    assert later_attempts(eid, "attempt-made-up") == frozenset()
    stand_down_if_replaced(eid, "attempt-made-up", where="at an id it can't place")


def _hold_every_wait(monkeypatch) -> None:
    """No wait can be saved, so each holds its worker (as when the checkpoint store is down)."""
    from temper_ai.checkpoint.service import CheckpointService

    def cannot_save(self, event_id, path, gate_round, *, wait_id=None):
        raise RuntimeError("the checkpoint store is down")

    monkeypatch.setattr(CheckpointService, "save_wait_parked", cannot_save)


def _watch_runs(monkeypatch) -> list[str]:
    """What each call of a Pi step's run ended with: "returned" or the exception's name."""
    ended: list[str] = []
    real_run = PiHost.run

    def watched(self, input_data, context):
        try:
            result = real_run(self, input_data, context)
        except BaseException as exc:
            ended.append(type(exc).__name__)
            raise
        ended.append("returned")
        return result

    monkeypatch.setattr(PiHost, "run", watched)
    return ended


def _later_attempt_takes_over(eid: str, wait: dict, ws, *, host: str = "talk",
                              to: str = sup.ROLE, workflow: str = "pi_talk"
                              ) -> tuple[str, dict, dict]:
    """What a later attempt of the run does, in its order: it starts, decides the held wait
    with the owner's message (to member ``to``), claims the next turn (its box named) and
    retires the wait the old attempt holds (``replaced``, as ``step_waits._retire`` does).
    Its turn stays running: that attempt is mid-turn. Returns its attempt id, its turn and
    that turn's member."""
    rec = EventRecorder(eid)
    later = rec.record(EventType.WORKFLOW_STARTED,
                       data={"name": workflow, "node_count": 3, "input_data": {},
                             "workspace_path": str(ws)},
                       execution_id=eid, status="running")
    led = sup.ledger()
    assert led.decide_wait(wait["wait_id"], {"owner": "message", "by": "the later attempt"},
                           later, deliveries=[(to, "look once more")])
    claimed = led.claim_turn(eid, host, attempt_id=later)
    assert claimed is not None, "the later attempt claims the next turn"
    turn, _batch = claimed
    assert led.record_box(turn["turn_id"], turn["epoch"], "pi-box-of-the-later-attempt")
    won, _after = rec.decide(wait["ask_event_id"], expect=(WAITING,), status=REPLACED,
                             data={"gate_status": REPLACED,
                                   "gate_replaced_at": utcnow().isoformat(),
                                   "gate_replaced_by": later})
    assert won, "the held wait was still open"
    member = led.participant(turn["participant_id"])
    return later, _turn(eid, turn["turn_id"]), member


def _turn(eid: str, turn_id: str) -> dict:
    return next(t for t in sup.ledger().snapshot(eid)["turns"] if t["turn_id"] == turn_id)


def test_a_held_wait_taken_over_by_a_later_attempt_mid_turn_stands_down(pw_run, monkeypatch):
    _hold_every_wait(monkeypatch)
    ended = _watch_runs(monkeypatch)
    stopped: list[str] = []

    def stop_box(name):
        stopped.append(name)
        return {"box": name, "confirmed": True}

    monkeypatch.setattr(PiHost, "stop_box", stop_box)
    c, state = pw_run.client, pw_run.state
    eid = sup.start(c, "pi_talk", pw_run.ws)
    w1 = sup.open_wait(eid, "owner")
    sup.wait_for(lambda: pw.run_threads(eid), what="the worker to hold at the question")
    assert pw.parked(pw.attempts(eid)[-1]) is None, "held, not parked"
    [first] = pw.attempts(eid)

    later, turn, member = _later_attempt_takes_over(eid, w1, pw_run.ws)

    # The old attempt stands down -- or, before SW-84, retried its step and took the newer
    # attempt's turn over (its box stopped): wait for whichever comes first.
    sup.wait_for(lambda: stopped or (not pw.run_threads(eid) and eid not in state.running),
                 what="the replaced attempt to stand down")
    assert stopped == [], "the newer attempt's box is never stopped"
    assert ended == ["ReplacedByLaterAttempt"], "the step ran once: no retry"

    led = sup.ledger()
    now = _turn(eid, turn["turn_id"])
    assert {k: now[k] for k in ("state", "epoch", "attempt_id", "box_name", "box_stop")} == {
        k: turn[k] for k in ("state", "epoch", "attempt_id", "box_name", "box_stop")}, (
        "the newer attempt's turn is untouched")
    assert now["state"] == "running" and now["attempt_id"] == later
    again = led.participant(member["participant_id"])
    assert (again["state"], again["epoch"]) == (member["state"], member["epoch"]), (
        "the newer attempt's member is untouched")
    assert led.open_waits(eid, "talk") == [], "no recovery wait opens"
    assert led.mark_effect(turn["turn_id"], "intent", epoch=turn["epoch"]), (
        "the newer attempt's own writes still pass its turn's fence")

    # The old attempt ends as replaced (a stop of its own, marked so); the newer one and the
    # run go on as they were.
    old, new = pw.attempts(eid)
    assert old["id"] == first["id"] and new["id"] == later
    assert old["status"] == "cancelled" and (old.get("data") or {}).get(REPLACED_MARK) is True
    assert new["status"] == "running" and REPLACED_MARK not in (new.get("data") or {})
    talk = [e for e in sup.events(eid, event_type="stage.started")
            if (e.get("data") or {}).get("name") == "talk"]
    assert [(e["status"], (e.get("data") or {}).get(REPLACED_MARK)) for e in talk] == [
        ("cancelled", True)], "the step stood down with its attempt, not failed"
    assert sup.node_status(eid, "audit") == [], "nothing after the step ran"
    assert sum(s["prompts"] for s in FakeBox.STARTS) == 1, "no turn was run again"


def _marked(eid: str, name: str) -> list[tuple[str, object]]:
    """(status, replaced mark) of every row of the run's node or stage ``name``."""
    return [(e["status"], (e.get("data") or {}).get(REPLACED_MARK))
            for e in sup.events(eid, event_type="stage.started")
            if (e.get("data") or {}).get("name") == name]


def test_a_team_whose_held_pause_a_later_attempt_took_over_mid_turn_is_left_to_it(
        tr, monkeypatch):
    """The same for a team step: its pause could not be saved, so the leader's ask held the
    worker; a later attempt took the pause over and runs a member's turn. The old attempt
    stands down: the team is not ended and no cancelled outcome is written (both are the
    newer attempt's), the member's turn, box and row are untouched, no recovery wait opens."""
    _hold_every_wait(monkeypatch)
    install(tr, tt.team_stage(strategy_config=PAUSE_1), outputs=OUTPUTS)
    script(tr.led, ["keep_going", "done"])
    eid = start(tr, {"goal": GOAL})
    row = open_team_wait(tr, eid)
    gate = pw.open_gate(tr.client, eid, row["gate_name"])
    assert row["kind"] == "pause"
    assert [a["status"] for a in pw.attempts(eid)] == ["running"], "held, not parked"
    assert prompts() == {"design": 2, "frontend": 1, "qa": 1}
    [first] = pw.attempts(eid)

    later, turn, member = _later_attempt_takes_over(
        eid, {**row, "ask_event_id": gate["event_id"]}, tr.ws, host=HOST, to="design",
        workflow="team_wf")
    sup.wait_for(lambda: Team.stop_box.calls or (
        not pw.run_threads(eid) and eid not in tr.state.running),
        what="the replaced attempt to stand down")
    assert Team.stop_box.calls == [], "the newer attempt's box is never stopped"

    now = _turn(eid, turn["turn_id"])
    assert {k: now[k] for k in ("state", "epoch", "attempt_id", "box_name", "box_stop")} == {
        k: turn[k] for k in ("state", "epoch", "attempt_id", "box_name", "box_stop")}, (
        "the newer attempt's turn is untouched")
    assert now["state"] == "running" and now["attempt_id"] == later
    snap = ts.rows(tr.led, eid, HOST)
    again = next(p for p in snap["participants"]
                 if p["participant_id"] == member["participant_id"])
    assert (again["state"], again["epoch"]) == (member["state"], member["epoch"]), (
        "the newer attempt's member is untouched")
    assert {p["ended_reason"] for p in snap["participants"]} == {None}, "the team goes on"
    assert not [m for m in snap["messages"] if m["undelivered_reason"]], "nothing dropped"
    assert [(w["wait_id"], w["state"]) for w in team_waits(tr, eid)] == [
        (row["wait_id"], "decided")], "no recovery wait opens"
    assert [o["decision"] for o in tr.led.outcomes_of(eid)] == [None], (
        "the team's ending is the newer attempt's to write")

    old, new = pw.attempts(eid)
    assert old["id"] == first["id"] and new["id"] == later
    assert old["status"] == "cancelled" and (old.get("data") or {}).get(REPLACED_MARK) is True
    assert new["status"] == "running" and REPLACED_MARK not in (new.get("data") or {})
    assert _marked(eid, "team") == [("cancelled", True)], "the team node stood down, once"
    assert set(_marked(eid, "build")) == {("cancelled", True)}, "so did its stage, not failed"
    assert prompts() == {"design": 2, "frontend": 1, "qa": 1}, "no member turn ran again"
