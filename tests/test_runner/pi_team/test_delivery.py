"""Team messages: posted once, held with the sending turn, delivered exactly once at the
receiver's next turn boundary (R2 B1, B3, B4, B6; C4, C5, N2). No model: every member is a
scripted stand-in Pi (support.TeamFakeBox). Runs on SQLite and on the tier's Postgres."""

from __future__ import annotations

import pytest

from temper_ai.pi_agent.ledger import LedgerConflict
from tests.test_runner.pi_team import support as ts
from tests.test_runner.pi_team.support import (
    PROMPTS,
    SCRIPTS,
    SENDS,
    check_invariants,
    headers,
    ids_in,
    message,
    open_team,
    reply_to_first,
    run_until_quiet,
    send,
)


def _goal(team, run_id, body="Write the README."):
    return team.post("lead", body, sender="temper", sender_kind="temper", kind="goal",
                     dedupe_key=f"{run_id}:goal")


def test_one_message_delivered_once(led, box, run_id):
    """The offline core: one member's message reaches another exactly once, at its turn."""
    team = open_team(led, box, run_id=run_id)
    goal = _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "Please draft the README.", kind="work_request")]]
    SCRIPTS["builder"] = [[{"say": "drafted"}]]

    results = run_until_quiet(team)
    assert ts.by_member(results) == [("lead", "completed"), ("builder", "completed"),
                                     (None, "idle")]
    sent = SENDS[0]["reply"]
    assert sent["ok"] and not sent["duplicate"] and sent["to"] == "builder"
    assert ids_in(PROMPTS["lead"][0]) == [goal["message_id"]]
    assert ids_in(PROMPTS["builder"][0]) == [sent["message_id"]]
    row = message(led, run_id, sent["message_id"])
    assert row["state"] == "consumed" and row["delivery_count"] == 1
    assert row["sender"] == "lead" and row["sender_kind"] == "member"
    assert row["turn_id"] == results[1].turn["turn_id"]
    assert team.state()["quiet"]
    check_invariants(led, run_id)


# --- B3: one key, one message ----------------------------------------------------------

def test_b3_duplicate_returns_original(led, box, run_id):
    """The same send twice (same client id, same content) returns the original message."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    again = {"to": "builder", "kind": "info", "body": "hello", "client_msg_id": "call_same"}
    SCRIPTS["lead"] = [[{"send": dict(again)}, {"send": dict(again)}]]
    run_until_quiet(team)

    first, second = (s["reply"] for s in SENDS)
    assert first["ok"] and second["ok"] and second["duplicate"] and not first["duplicate"]
    assert first["message_id"] == second["message_id"]
    rows = [m for m in led.snapshot(run_id)["messages"] if m["client_msg_id"] == "call_same"]
    assert len(rows) == 1 and rows[0]["delivery_count"] == 1
    assert ids_in(PROMPTS["builder"][0]) == [first["message_id"]]
    check_invariants(led, run_id)


def test_b3_conflict_refused(led, box, run_id):
    """The same client id with different content is refused; the original stands."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "first", client_msg_id="call_k"),
                        send("builder", "second", client_msg_id="call_k")]]
    run_until_quiet(team)

    first, second = (s["reply"] for s in SENDS)
    assert first["ok"]
    assert second == {"ok": False, "code": "idempotency_conflict",
                      "detail": "that message id was already used for a different message"}
    rows = [m for m in led.snapshot(run_id)["messages"] if m["client_msg_id"] == "call_k"]
    assert [r["body"] for r in rows] == ["first"]
    lead_turn = led.snapshot(run_id)["turns"][0]
    assert [r["code"] for r in lead_turn["refusals"]] == ["idempotency_conflict"]
    # Temper's own posts follow the same rule.
    assert team.post("builder", "note", dedupe_key=f"{run_id}:n")["duplicate"] is False
    assert team.post("builder", "note", dedupe_key=f"{run_id}:n")["duplicate"] is True
    with pytest.raises(LedgerConflict):
        team.post("builder", "another note", dedupe_key=f"{run_id}:n")
    check_invariants(led, run_id)


def test_c4_member_sends_have_no_counted_key(led, box, run_id):
    """R2 C4: a member's send is keyed by A7's key only (run, sender, client id)."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "a"), send("checker", "b")]]
    run_until_quiet(team)
    sent = [m for m in led.snapshot(run_id)["messages"] if m["sender_kind"] == "member"]
    assert len(sent) == 2
    assert all(m["dedupe_key"] is None and m["client_msg_id"] for m in sent)
    check_invariants(led, run_id)


# --- B4: a turn's messages leave when it settles ------------------------------------------

def test_b4_messages_leave_on_settle(led, box, run_id):
    """While the sending turn runs its message is held: nobody can take it. It becomes
    pending only when the turn completes."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    seen = {}

    def look(_box, _prompt):
        mid = SENDS[-1]["reply"]["message_id"]
        seen["state"] = message(led, run_id, mid)["state"]
        builder = led.member_row(run_id, ts.HOST, "builder")
        seen["builder_pending"] = led.pending_for(builder["participant_id"])
        seen["claim"] = led.claim_turn(run_id, ts.HOST, attempt_id="other")

    SCRIPTS["lead"] = [[send("builder", "draft it", kind="work_request"), {"call": look}]]
    results = run_until_quiet(team)

    assert seen == {"state": "held", "builder_pending": [], "claim": None}
    assert results[0].released == {"pending": 1, "undelivered": 0}
    row = message(led, run_id, SENDS[0]["reply"]["message_id"])
    assert row["state"] == "consumed" and row["released_at"] is not None
    check_invariants(led, run_id)


def test_b4_failed_turn_messages_withheld(led, box, run_id):
    """A turn that fails visibly: what it sent is recorded undelivered, never delivered."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "start", kind="work_request"),
                        {"error": "400 invalid_request_error: the request was refused"}]]
    results = run_until_quiet(team)

    assert ts.by_member(results) == [("lead", "failed")]
    row = message(led, run_id, SENDS[0]["reply"]["message_id"])
    assert (row["state"], row["undelivered_reason"]) == ("undelivered", "turn_failed")
    assert "builder" not in PROMPTS
    # Nothing else runs until the owner answers (retry or stop, N1).
    assert team.step().kind == "failed"
    check_invariants(led, run_id)


def test_b4_cut_turn_retry_delivers_once(led, box, run_id):
    """A turn cut off after sending, retried: the first try's send is never delivered, the
    retry's send is, once."""
    team = open_team(led, box, run_id=run_id)
    goal = _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "try 1", kind="work_request"), {"die": True}],
                       [send("builder", "try 2", kind="work_request")]]
    SCRIPTS["builder"] = [[{"say": "on it"}]]

    first = run_until_quiet(team)
    assert ts.by_member(first) == [("lead", "held")]
    assert team.decide(first[0].wait, "retry") is None
    results = run_until_quiet(team)
    assert ts.by_member(results) == [("lead", "completed"), ("builder", "completed"),
                                     (None, "idle")]

    try1, try2 = (message(led, run_id, s["reply"]["message_id"]) for s in SENDS)
    assert (try1["state"], try1["undelivered_reason"]) == ("undelivered", "turn_superseded")
    assert (try2["state"], try2["delivery_count"]) == ("consumed", 1)
    assert ids_in(PROMPTS["builder"][0]) == [try2["message_id"]]
    assert len(PROMPTS["builder"]) == 1
    assert ids_in(PROMPTS["lead"][1]) == [goal["message_id"]]
    check_invariants(led, run_id)


def test_c5_release_rechecks_recipient(led, box, run_id):
    """R2 C5: at release each recipient is checked again. Retired since the send: recorded
    undelivered (recipient_retired), never left pending for nobody."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)

    def retire_builder(_box, _prompt):
        row = led.member_row(run_id, ts.HOST, "builder")
        led.set_participant_state(row["participant_id"], "retired")

    SCRIPTS["lead"] = [[send("builder", "for you"), send("checker", "for you too"),
                        {"call": retire_builder}]]
    results = run_until_quiet(team)
    assert results[0].released == {"pending": 1, "undelivered": 1}
    to_builder, to_checker = (message(led, run_id, s["reply"]["message_id"]) for s in SENDS)
    assert (to_builder["state"], to_builder["undelivered_reason"]) == (
        "undelivered", "recipient_retired")
    assert to_checker["state"] == "consumed"
    check_invariants(led, run_id)


# --- B6: FIFO, one batch per turn boundary, nothing mid-turn ---------------------------

def test_b6_mid_turn_arrival_waits(led, box, run_id):
    """A message that arrives during the receiver's turn waits for its next turn."""
    team = open_team(led, box, run_id=run_id)
    goal = _goal(team, run_id)
    late = {}

    def owner_posts(_box, _prompt):
        late["row"] = team.post("lead", "one more thing")

    SCRIPTS["lead"] = [[{"call": owner_posts}], [{"say": "got it"}]]
    results = run_until_quiet(team)

    assert ts.by_member(results) == [("lead", "completed"), ("lead", "completed"),
                                     (None, "idle")]
    assert ids_in(PROMPTS["lead"][0]) == [goal["message_id"]]
    assert ids_in(PROMPTS["lead"][1]) == [late["row"]["message_id"]]
    first_turn = results[0].turn
    assert late["row"]["seq"] > first_turn["cut_seq"]
    check_invariants(led, run_id)


def test_b6_two_inputs_one_batch(led, box, run_id):
    """Everything pending for a member at its turn boundary comes as one ordered batch."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "first"), send("builder", "second")]]
    team_note = {}

    def owner_note(_box, _prompt):
        team_note["row"] = team.post("builder", "owner's note")

    SCRIPTS["lead"][0].append({"call": owner_note})
    run_until_quiet(team)

    ids = ids_in(PROMPTS["builder"][0])
    assert len(PROMPTS["builder"]) == 1 and len(ids) == 3
    seqs = [message(led, run_id, i)["seq"] for i in ids]
    assert seqs == sorted(seqs)
    # The owner's note was posted while the lead's turn ran, after the lead's two sends were
    # stored held; it became pending first, the held ones at the lead's settle. FIFO by seq.
    assert ids[2] == team_note["row"]["message_id"]
    assert [h["from"] for h in headers(PROMPTS["builder"][0])] == [
        'member "lead"', 'member "lead"', "the owner"]
    check_invariants(led, run_id)


def test_b6_oldest_pending_goes_first(led, box, run_id):
    """One turn at a time: the idle member holding the team's oldest pending message goes."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[send("checker", "to checker first"), send("builder", "then builder")]]
    results = run_until_quiet(team)
    assert [m for m, _ in ts.by_member(results)] == ["lead", "checker", "builder", None]
    check_invariants(led, run_id)


# --- N2: replies without obligations -------------------------------------------------

def test_n2_reply_goes_back_to_its_sender(led, box, run_id):
    """A reply names a message the member received and goes to that message's sender; a
    second reply to the same message is allowed (no obligations in this slice)."""
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "what is 2+2?", kind="work_request")], [{"say": "ok"}]]
    SCRIPTS["builder"] = [[reply_to_first("4", sender="lead"),
                           reply_to_first("still 4", sender="lead")]]
    run_until_quiet(team)

    ask = SENDS[0]["reply"]["message_id"]
    r1, r2 = SENDS[1]["reply"], SENDS[2]["reply"]
    assert r1["ok"] and r2["ok"] and r1["to"] == r2["to"] == "lead"
    rows = [message(led, run_id, r["message_id"]) for r in (r1, r2)]
    assert all(r["kind"] == "reply" and r["in_reply_to"] == ask and r["outcome"] == "answered"
               and r["thread_id"] == ask for r in rows)
    lead_second = headers(PROMPTS["lead"][1])
    assert [h["id"] for h in lead_second] == [r1["message_id"], r2["message_id"]]
    assert all(f"in reply to {ask}" in h["rest"] for h in lead_second)
    check_invariants(led, run_id)


def test_n2_reply_rules_refuse_what_was_not_received(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    goal = _goal(team, run_id)
    SCRIPTS["lead"] = [[send("builder", "hello", kind="info")]]
    SCRIPTS["builder"] = [[
        # A reply to a message it never received.
        {"send": {"kind": "reply", "body": "x", "in_reply_to": goal["message_id"]}},
        # A reply to a message it received, sent to someone else.
        {"send": lambda p: {"kind": "reply", "body": "x", "in_reply_to": ids_in(p)[0],
                            "to": "checker"}},
        # A reply without in_reply_to.
        {"send": {"kind": "reply", "body": "x", "to": "lead"}},
    ]]
    run_until_quiet(team)
    codes = [s["reply"].get("code") for s in SENDS[1:]]
    assert codes == ["invalid_reference", "invalid_reference", "invalid_message"]
    # The lead answering the goal (a message from Temper, not a member) is refused too.
    stored = [m for m in led.snapshot(run_id)["messages"] if m["kind"] == "reply"]
    assert stored == []
    check_invariants(led, run_id)


def test_n2_reply_to_temper_message_refused(led, box, run_id):
    team = open_team(led, box, run_id=run_id)
    _goal(team, run_id)
    SCRIPTS["lead"] = [[reply_to_first("done")]]
    run_until_quiet(team)
    assert SENDS[0]["reply"] == {"ok": False, "code": "invalid_reference",
                                 "detail": "a reply answers a message from another member"}
    check_invariants(led, run_id)
