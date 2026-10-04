"""Kept conversations (R2 B8): one Pi session per member per run, reused for every turn. The
member's box exists only during a turn; its next turn's box reopens the same session."""

from __future__ import annotations

import json

from tests.test_runner.pi_team import support as ts
from tests.test_runner.pi_team.support import (
    PROMPTS,
    SCRIPTS,
    check_invariants,
    ids_in,
    open_team,
    reply_to_first,
    run_until_quiet,
    send,
)


def _user_texts(path) -> list[str]:
    out = []
    for line in path.read_text().splitlines():
        entry = json.loads(line)
        msg = entry.get("message") or {}
        if entry.get("type") == "message" and msg.get("role") == "user":
            out.append(msg["content"][0]["text"])
    return out


def test_b8_a_b_a_same_conversation(led, box, run_id):
    """lead -> builder -> lead: the lead's second turn is in the lead's first conversation."""
    team = open_team(led, box, run_id=run_id)
    team.post("lead", "Write the README.", sender="temper", sender_kind="temper", kind="goal",
              dedupe_key=f"{run_id}:goal")
    seen = {}

    def look(fake, _prompt):
        seen["file"] = fake.session_file
        seen["before"] = _user_texts(seen["file"])

    SCRIPTS["lead"] = [[send("builder", "draft it", kind="work_request")],
                       [{"call": look}, {"say": "thanks"}]]
    SCRIPTS["builder"] = [[reply_to_first("drafted", sender="lead")]]
    results = run_until_quiet(team)
    assert [m for m, _ in ts.by_member(results)] == ["lead", "builder", "lead", None]

    lead = led.member_row(run_id, ts.HOST, "lead")
    starts = [s for s in ts.FakeBox.STARTS if s.get("member") == "lead"]
    assert len(starts) == 2
    assert {s["session_id"] for s in starts} == {lead["session_id"]}
    # When the second turn began, its box already held the first turn's conversation...
    assert seen["before"] == [PROMPTS["lead"][0], PROMPTS["lead"][1]]
    # ...and afterwards the one file holds both turns, nothing else.
    assert _user_texts(seen["file"]) == PROMPTS["lead"]
    assert seen["file"].name.endswith(f"_{lead['session_id']}.jsonl")
    assert len(led.participants_of(run_id, ts.HOST)) == 3  # one row per member, still
    check_invariants(led, run_id)


def test_b8_idle_stop_reopen(led, box, run_id):
    """An idle member has no box: its box closed when its turn ended. A later message opens a
    new box on the same session, which carries on the conversation."""
    team = open_team(led, box, run_id=run_id)
    team.post("lead", "first", sender="temper", sender_kind="temper", kind="goal",
              dedupe_key=f"{run_id}:goal")
    SCRIPTS["lead"] = [[{"say": "one"}]]
    assert ts.by_member(run_until_quiet(team)) == [("lead", "completed"), (None, "idle")]

    first = [s for s in ts.FakeBox.STARTS if s.get("member") == "lead"]
    assert len(first) == 1 and first[0].get("closed") is True  # idle: no box left
    assert team.state()["quiet"]

    later = team.post("lead", "one more thing")
    seen = {}

    def look(fake, _prompt):
        seen["open_boxes"] = [s for s in ts.FakeBox.STARTS if not s.get("closed")]
        seen["texts"] = _user_texts(fake.session_file)

    SCRIPTS["lead"] = [[{"call": look}, {"say": "two"}]]
    assert ts.by_member(run_until_quiet(team)) == [("lead", "completed"), (None, "idle")]
    starts = [s for s in ts.FakeBox.STARTS if s.get("member") == "lead"]
    assert len(starts) == 2 and starts[0]["session_id"] == starts[1]["session_id"]
    assert len(seen["open_boxes"]) == 1  # only the box of the turn running now
    assert seen["texts"] == PROMPTS["lead"]
    assert ids_in(PROMPTS["lead"][1]) == [later["message_id"]]
    assert all(s.get("closed") for s in ts.FakeBox.STARTS)
    check_invariants(led, run_id)
