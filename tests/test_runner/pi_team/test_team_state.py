"""The tables themselves (tables.md): layout, the review record, the quiet-team check, the
team settings pin (C3), the claim's cutoff (C6), the creation race (N4), no turn while a wait
is open (B6), the router knowing ``all`` only (B7) and the end of a team (B12)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError

from temper_ai.pi_agent import ledger as ledger_module
from temper_ai.pi_agent.route.model import ControlError
from temper_ai.pi_agent.route.router import policy_for
from tests.test_runner.pi_team import support as ts
from tests.test_runner.pi_team.support import (
    PROMPTS,
    SCRIPTS,
    SENDS,
    check_invariants,
    make_team,
    member,
    message,
    open_team,
    run_until_quiet,
    send,
)


def _goal(team, run_id, to="lead", body="Write the README."):
    return team.post(to, body, sender="temper", sender_kind="temper", kind="goal",
                     dedupe_key=f"{run_id}:goal")


# --- layout ------------------------------------------------------------------------------

def test_tables_extend_l2_layout(led):
    """L2's four tables, extended in place, plus the review record: no parallel tables."""
    names = [t.name for t in ledger_module.TABLES]
    assert names == ["pi_participants", "pi_messages", "pi_turns", "pi_waits", "pi_reviews"]
    inspector = sa.inspect(led.engine)
    assert set(names) <= set(inspector.get_table_names())
    msg_cols = {c["name"] for c in inspector.get_columns("pi_messages")}
    assert {"message_id", "client_msg_id", "content_sha256", "sender_participant", "turn_id",
            "delivery_count", "redeliver_turn", "undelivered_reason", "review_id",
            "dedupe_key", "seq", "state"} <= msg_cols
    turn_cols = {c["name"] for c in inspector.get_columns("pi_turns")}
    assert {"claim_key", "epoch", "claimed_by", "retry_of", "input_seqs", "cut_seq",
            "effect_state", "refusals", "box_name", "box_stop"} <= turn_cols
    uniques = {u["name"]: u["column_names"]
               for u in inspector.get_unique_constraints("pi_messages")}
    assert uniques.get("uq_pi_message_client") == ["run_id", "sender_participant",
                                                   "client_msg_id"]
    # N5: the claim and the quiet check read turns by (run, team, state).
    indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("pi_turns")}
    assert indexes.get("ix_pi_turns_team_state") == ["run_id", "host_path", "state"]


def test_n4_ensure_creation_race_is_checked_again(led, monkeypatch):
    """N4: two processes creating the tables at once on Postgres: the loser's 'already exists'
    is checked again once, not failed; any other error still fails."""
    real = ledger_module.metadata.create_all
    calls = []

    def racing(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ProgrammingError("CREATE TABLE pi_turns", {},
                                   Exception('relation "pi_turns" already exists'))
        return real(*args, **kwargs)

    monkeypatch.setattr(ledger_module.metadata, "create_all", racing)
    led.ensure()
    assert len(calls) == 2

    def broken(*args, **kwargs):
        raise ProgrammingError("CREATE TABLE pi_turns", {}, Exception("permission denied"))

    monkeypatch.setattr(ledger_module.metadata, "create_all", broken)
    try:
        led.ensure()
    except ProgrammingError as exc:
        assert "permission denied" in str(exc)
    else:  # pragma: no cover - the assertion is the point
        raise AssertionError("a real error must not be swallowed")


# --- the review record (#38 writes it; the tables hold it) ------------------------------

def test_review_record_round_trip(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[{"say": "ready for review"}]]
    results = run_until_quiet(team)
    lead = led.member_row(run_id, ts.HOST, "lead")
    asked = results[0].turn["turn_id"]

    review = led.open_review(run_id, ts.HOST, round_no=1,
                             leader_participant=lead["participant_id"], asked_turn=asked,
                             commit_sha="0123abcd" * 5, files={"README.md": "e" * 64})
    assert team.state()["open_reviews"] == 1 and not team.state()["quiet"]
    # Each reviewer's view is a message carrying the review's id.
    for who in ("builder", "checker"):
        led.post(run_id, ts.HOST, "lead", f"{who}: looks fine", sender=who,
                 sender_kind="temper", kind="review_view", review_id=review["review_id"],
                 dedupe_key=f"{review['review_id']}:view:{who}")
    assert led.update_review(review["review_id"], state="decided", decision="done",
                             decided_turn=asked, summary="README written", cost={"usd": 0})

    (back,) = led.reviews_of(run_id, ts.HOST)
    assert (back["round"], back["commit_sha"], back["files"]) == (
        1, "0123abcd" * 5, {"README.md": "e" * 64})
    assert (back["state"], back["decision"], back["decided_turn"]) == ("decided", "done", asked)
    views = [m for m in led.snapshot(run_id)["messages"] if m["review_id"] == back["review_id"]]
    assert sorted(m["body"] for m in views) == ["builder: looks fine", "checker: looks fine"]
    state = team.state()
    assert state["open_reviews"] == 0 and state["done"] == 1 and not state["quiet"]


# --- the quiet-team check ---------------------------------------------------------------

def test_quiet_team_state(led, box, run_id):
    """Quiet = nothing running, nothing waiting to be delivered, no open wait or review, not
    done: each part read straight from the tables."""
    team = open_team(led, box, run_id=run_id)
    assert team.state()["quiet"]

    _goal(team, run_id)
    state = team.state()
    assert (state["quiet"], state["waiting_messages"]) == (False, 1)

    observed = {}

    def look(_fake, _prompt):
        observed["during"] = team.state()

    SCRIPTS["lead"] = [[{"call": look}]]
    run_until_quiet(team)
    assert (observed["during"]["quiet"], observed["during"]["unsettled"]) == (False, 1)
    assert team.state()["quiet"]

    wait = led.open_wait(run_id, ts.HOST, "owner", {"question": "go on?"}, "attempt-1")
    assert (team.state()["quiet"], team.state()["open_waits"]) == (False, 1)
    assert led.decide_wait(wait["wait_id"], {"answer": "yes"}, "attempt-1")
    assert team.state()["quiet"]


# --- C3: the team's settings are part of every member's pin ----------------------------

def test_c3_changed_team_refused(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    before = led.snapshot(run_id)

    roster = make_team(led, box, run_id=run_id, attempt="attempt-2",
                       names=("lead", "builder"))
    assert roster.open({}).startswith("team settings changed")
    renamed = make_team(led, box, run_id=run_id, attempt="attempt-2",
                        names=("lead", "builder", "reviewer"))
    assert renamed.open({}).startswith("team settings changed")
    paused = make_team(led, box, run_id=run_id, attempt="attempt-2",
                       settings={**ts.SETTINGS, "pause_after_rounds": 5})
    assert paused.open({}).startswith("team settings changed")
    leader = make_team(led, box, run_id=run_id, attempt="attempt-2",
                       settings={**ts.SETTINGS, "mode": {"type": "leader", "leader": "builder"}})
    assert leader.open({}).startswith("team settings changed")
    # A member's own settings changing is refused too, naming what changed.
    model = make_team(led, box, run_id=run_id, attempt="attempt-2",
                      members=[member("lead", thinking="high"), member("builder"),
                               member("checker")])
    refusal = model.open({})
    assert refusal.startswith("member lead's settings changed") and "thinking" in refusal
    assert led.snapshot(run_id) == before  # refused before any write or turn
    assert make_team(led, box, run_id=run_id, attempt="attempt-2").open({}) is None


# --- C6: the claim records the highest seq it could see ---------------------------------

def test_c6_claim_records_cut_seq(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    goal = _goal(team, run_id)
    team.post("builder", "for later")
    claimed = led.claim_turn(run_id, ts.HOST, attempt_id="attempt-1")
    turn, batch = claimed
    seqs = [m["seq"] for m in led.snapshot(run_id)["messages"]]
    assert turn["cut_seq"] == max(seqs)
    assert [m["message_id"] for m in batch] == [goal["message_id"]]
    assert led.turn(turn["turn_id"])["cut_seq"] == max(seqs)


# --- B6: no turn while any team wait is open --------------------------------------------

def test_b6_no_turn_while_wait_open(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    wait = led.open_wait(run_id, ts.HOST, "owner", {"question": "may I?"}, "attempt-1")
    assert led.claim_turn(run_id, ts.HOST, attempt_id="attempt-1") is None
    assert team.step().kind == "waiting"
    assert "lead" not in PROMPTS
    assert led.decide_wait(wait["wait_id"], {"answer": "yes"}, "attempt-1")
    assert team.step().kind == "completed"
    check_invariants(led, run_id)


# --- B7: the router knows `all` only ------------------------------------------------------

def test_b7_router_knows_all_only(led, box, run_id):
    for communication in ("edges", "chain", ""):
        try:
            policy_for(communication, run_id)
        except ControlError as exc:
            assert str(exc) == "communication_not_built"
        else:  # pragma: no cover
            raise AssertionError(communication)
    edges = make_team(led, box, run_id=run_id,
                      settings={**ts.SETTINGS, "communication": {
                          "type": "edges", "edges": [["lead", "builder"]]}})
    assert edges.open({}) == "communication 'edges' is not built; use all"
    assert led.participants_of(run_id, ts.HOST) == []  # nothing written


# --- B12: owner cancel ends the run cancelled; queued messages recorded undelivered ------

def test_b12_cancel_records_undelivered(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "build", kind="work_request")]]
    assert team.step().kind == "completed"  # the lead's send is now pending for the builder
    team.post("checker", "owner's note")

    ended = team.end("run_cancelled")
    assert (ended["undelivered"], ended["ended_members"]) == (2, 3)
    rows = [m for m in led.snapshot(run_id)["messages"] if m["state"] != "consumed"]
    assert {(m["to_member"], m["state"], m["undelivered_reason"]) for m in rows} == {
        ("builder", "undelivered", "run_cancelled"),
        ("checker", "undelivered", "run_cancelled")}
    assert all(p["state"] == "ended" for p in led.participants_of(run_id, ts.HOST))
    assert team.step().kind == "idle"
    assert "builder" not in PROMPTS and "checker" not in PROMPTS
    # Anything posted afterwards is recorded, never delivered, never dropped (B6).
    late = team.post("builder", "too late")
    assert (late["state"], late["undelivered_reason"]) == ("undelivered", "late")
    assert team.end("run_cancelled")["undelivered"] == 0  # idempotent
    check_invariants(led, run_id)


def test_b12_cancel_during_cut_turn(led, box, run_id):
    """Cancelled while a cut-off turn waits on the owner: the turn is cancelled, what it sent
    is recorded undelivered, the wait is cancelled."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "start"), {"die": True}]]
    held = run_until_quiet(team)[0]
    assert held.kind == "held"

    ended = team.end("run_cancelled")
    assert ended["cancelled_turns"] == [held.turn["turn_id"]]
    assert [w["wait_id"] for w in ended["cancelled_waits"]] == [held.wait["wait_id"]]
    row = message(led, run_id, SENDS[0]["reply"]["message_id"])
    assert (row["state"], row["undelivered_reason"]) == ("undelivered", "turn_cancelled")
    assert led.turn(held.turn["turn_id"])["state"] == "cancelled"
    assert led.open_waits(run_id, ts.HOST) == []
    check_invariants(led, run_id)
