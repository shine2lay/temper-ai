"""R2 C2 + B12: a run cancelled while it waits on you ends its Pi teams through Temper's
cancel path, because no team node is running to do it (#38 parks every team wait).

The team's rows are made by hand the way a parked team leaves them -- a cut-off turn holding
what it sent, its recovery wait open, mail pending for others -- since the team node is
wired in #38. The run itself is a real parked Pi run, cancelled through the API.
"""

from __future__ import annotations

from temper_ai.pi_agent.ledger import Ledger
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_team import support as ts


def _parked_team(pw_run, eid: str):
    """A team in the state a parked team run is in: the lead's turn cut off after it sent a
    message (held), a recovery wait open, and mail pending for the builder."""
    from temper_ai.database import get_database

    led = Ledger(get_database().engine)
    led.ensure()
    team = ts.open_team(led, sup.box_config(pw_run.tmp / "team-box"), run_id=eid)
    goal = team.post("lead", "Write the README.", sender="temper", sender_kind="temper",
                     kind="goal", dedupe_key=f"{eid}:goal")
    queued = team.post("builder", "the builder's mail")
    turn, _batch, binding = ts.claim_bound(led, eid)
    held = led.member_send(binding, ts.info("checker", "a note the lead sent"))
    wait = led.hold_turn(turn["turn_id"], "the service stopped during the turn", [], None,
                         "attempt-1", epoch=turn["epoch"])
    assert wait and held["ok"]
    return led, team, {"goal": goal["message_id"], "queued": queued["message_id"],
                       "held": held["message_id"], "turn": turn["turn_id"],
                       "wait": wait["wait_id"]}


def test_c2_cancel_parked_team_run(pw_run, monkeypatch):
    """C2: cancelling a parked team run ends the team in the same cancel: the cut-off turn is
    cancelled and its held message recorded undelivered (turn_cancelled, transaction 10),
    pending mail undelivered (run_cancelled), the recovery wait cancelled, every member
    ended (run_cancelled); I8 holds and a later post is recorded late."""
    monkeypatch.setenv("TEMPER_PI_AGENT", "1")
    c = pw_run.client
    eid = sup.start(c, "pw_before_pi", pw_run.ws)
    pw.wait_parked(pw_run.state, eid)
    pw.open_gate(c, eid, "check")
    led, team, ids = _parked_team(pw_run, eid)

    r = c.post(f"/api/runs/{eid}/cancel", json={"reason": "not this one"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text

    msg = {m["message_id"]: m for m in ts.rows(led, eid)["messages"]}
    assert (msg[ids["goal"]]["state"], msg[ids["goal"]]["turn_id"]) == ("consumed", ids["turn"])
    assert (msg[ids["held"]]["state"], msg[ids["held"]]["undelivered_reason"]) == (
        "undelivered", "turn_cancelled")
    assert (msg[ids["queued"]]["state"], msg[ids["queued"]]["undelivered_reason"]) == (
        "undelivered", "run_cancelled")
    turn = led.turn(ids["turn"])
    assert (turn["state"], turn["claim_key"]) == ("cancelled", None)
    (wait,) = ts.rows(led, eid)["waits"]
    assert (wait["wait_id"], wait["state"]) == (ids["wait"], "cancelled")
    assert {(p["state"], p["ended_reason"]) for p in led.participants_of(eid, ts.HOST)} == {
        ("ended", "run_cancelled")}
    state = led.team_state(eid, ts.HOST)
    assert (state["unsettled"], state["waiting_messages"], state["open_waits"]) == (0, 0, 0)
    assert {m["state"] for m in state["members"]} == {"ended"}
    ts.check_invariants(led, eid)

    late = team.post("lead", "after the cancel")
    assert (late["state"], late["undelivered_reason"]) == ("undelivered", "late")
    assert team.step().kind == "idle"
    assert [a["status"] for a in pw.attempts(eid)] == ["cancelled"]
    assert FakeBox.STARTS == []


def test_c2_switch_off_cancel_leaves_pi_rows_alone(pw_run, monkeypatch):
    """C2, switch off: the cancel path imports nothing of the team code and changes no pi_
    row (with the switch off the tables would not exist at all; test_switch.py proves that)."""
    monkeypatch.setenv("TEMPER_PI_AGENT", "1")
    c = pw_run.client
    eid = sup.start(c, "pw_before_pi", pw_run.ws)
    pw.wait_parked(pw_run.state, eid)
    pw.open_gate(c, eid, "check")
    led, _team, ids = _parked_team(pw_run, eid)
    before = ts.rows(led, eid)
    monkeypatch.delenv("TEMPER_PI_AGENT")

    r = c.post(f"/api/runs/{eid}/cancel", json={"reason": "not this one"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    assert ts.rows(led, eid) == before
    assert led.turn(ids["turn"])["state"] == "uncertain"
