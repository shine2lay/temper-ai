"""An owner answer with no words still reaches whoever asked (task #121, Architecture's P1
and S1 on #119).

The owner can answer a question with no words (empty, or only spaces) through the generic
approve route. #119 gave the leader's git-refused wait a fixed line of its own for that ("you
get another turn"), because that question promised the leader another turn. Any other owner
question -- a member's own ask_owner, the leader's own included -- now gets another fixed
line, "The owner answered your question with no words.", delivered to the member who asked
like any answer: it is told, and woken if it rested on its question. Before, an empty answer
delivered nothing, so a resting member stayed at rest, the team stalled and the owner was
asked again; a blank one delivered a blank reply. The line guesses nothing and promises
nothing: the member decides what comes next. An answer with words passes on as typed, and the
decision keeps the real answer's sha256.

Model-free: every member is a scripted Pi; the owner is leader_support's stand-in beneath the
real bridge.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from temper_ai.pi_agent.ledger import waits
from temper_ai.pi_agent.team_flow import FlowTeam
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts

NAMES = ("lead", "builder")
SETTINGS = {**ls.FLOW_SETTINGS, "max_parallel": 1}
#: What the member who asked gets when the owner answers its question with no words (#121).
MEMBER_LINE = "The owner answered your question with no words."
#: #119's line: only for the leader's git-refused wait (test_planted_git_notice.py pins it there).
LEADER_LINE = "The owner answered with no words: you get another turn."
QUESTION = "May I add part.md to the project?"
LEAD_QUESTION = "May I say done with only part.md?"
NO_WORDS = pytest.mark.parametrize("answer", ["", "  "], ids=["empty", "blank"])
#: The builder's part: write it, share it, tell the leader, rest.
BUILD = [ls.write("part.md", "# part\n"), ls.op("share", note="the part"),
         ts.send("lead", "part.md is shared", "info"), ls.op("idle")]


def _owner_replies(led: Any, run_id: str, member: str) -> list[str]:
    """The owner's answers delivered to ``member``, in order."""
    msgs = sorted(ts.rows(led, run_id)["messages"], key=lambda m: m["seq"])
    return [m["body"] for m in msgs if m["to_member"] == member and m["kind"] == "owner_reply"]


def _questions(led: Any, run_id: str) -> list[dict]:
    """The owner questions' wait rows, oldest first."""
    return [w for w in ls.table(led, waits, run_id) if w["kind"] == "owner"]


def _woken(led: Any, run_id: str, member: str) -> list[dict]:
    return [e["data"] for e in ts.team_events(led, run_id)
            if e["kind"] == "wake" and e["member"] == member]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _lead(*, asks: bool = False) -> ls.Turns:
    """The leader gives the builder its part and rests. Once the builder wrote back it says
    done; with ``asks``, it first asks the owner a question of its own, and says done on the
    turn that brings the answer."""
    def play() -> list[dict]:
        prompts = ts.PROMPTS["lead"]
        if len(prompts) == 1:
            return [ts.send("builder", "Write part.md, then share.", "work_request"),
                    ls.op("idle", note="waiting for the part")]
        heard = ts.headers(prompts[-1])
        if any(h["kind"] == "owner_reply" for h in heard):
            return [ls.op("done", summary="The part is in the shared version.")]
        if any(h["from"] == 'member "builder"' for h in heard):
            return ([ls.op("ask_owner", question=LEAD_QUESTION)] if asks else
                    [ls.op("done", summary="The part is in the shared version.")])
        return [ls.op("idle", note="waiting for the part")]
    return ls.Turns(play)


def _open(led: Any, box: Any, run_id: str, tmp_path: Path) -> FlowTeam:
    return ls.open_flow(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"),
                        names=NAMES, settings=SETTINGS)


# --- the whole feature --------------------------------------------------------------------------


@NO_WORDS
def test_every_wordless_answer_reaches_whoever_asked_and_the_team_ends_done(
        led, box, run_id, tmp_path, monkeypatch, answer):
    # The builder asks and rests on its question; later the leader asks one of its own. Both
    # are answered with no words: each gets the member line (never #119's leader line), the
    # line wakes the resting builder, the team ends done, and the owner is asked only twice.
    owner = ls.Owner(led, answer, answer, "stop").install(monkeypatch)
    ts.SCRIPTS["lead"] = _lead(asks=True)
    ts.SCRIPTS["builder"] = [[ls.op("ask_owner", question=QUESTION),
                              ls.op("idle", note="waiting for the owner")], BUILD]
    team = _open(led, box, run_id, tmp_path)

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    assert [a["header"] for a in owner.asked] == ["builder asks", "lead asks"]
    assert owner.answers == ["stop"]
    for name in NAMES:
        assert _owner_replies(led, run_id, name) == [MEMBER_LINE], name
    # the builder rested on its question, and the line woke it into the turn that shows it
    assert {"by": "owner", "was": "idle"} in _woken(led, run_id, "builder")
    assert len(ts.PROMPTS["builder"]) == 2
    told = ts.PROMPTS["builder"][1]
    assert any(h["kind"] == "owner_reply" for h in ts.headers(told))
    assert MEMBER_LINE in told and LEADER_LINE not in told
    # the leader's own question is no git-refused wait: the member line, not #119's
    assert len(ts.PROMPTS["lead"]) == 3
    told = ts.PROMPTS["lead"][2]
    assert any(h["kind"] == "owner_reply" for h in ts.headers(told))
    assert MEMBER_LINE in told and LEADER_LINE not in told
    # each decision keeps the real answer's digest, not the line's
    questions = _questions(led, run_id)
    assert [(q["subject"]["header"], q["decision"]["answer"], q["decision"]["text_sha256"])
            for q in questions] == [("builder asks", "given", _sha(answer)),
                                    ("lead asks", "given", _sha(answer))]


# --- edges --------------------------------------------------------------------------------------


@NO_WORDS
def test_a_member_that_kept_on_after_its_question_is_still_told_the_owner_answered(
        led, box, run_id, tmp_path, monkeypatch, answer):
    # A member that didn't rest on its question gets its next turn once the answer is in; that
    # turn now shows the owner answered, instead of nothing.
    owner = ls.Owner(led, answer, "stop").install(monkeypatch)
    ts.SCRIPTS["lead"] = _lead()
    ts.SCRIPTS["builder"] = [[ls.op("ask_owner", question=QUESTION)], BUILD]
    team = _open(led, box, run_id, tmp_path)

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    assert [a["header"] for a in owner.asked] == ["builder asks"] and owner.answers == ["stop"]
    assert _owner_replies(led, run_id, "builder") == [MEMBER_LINE]
    assert all(w["by"] != "owner" for w in _woken(led, run_id, "builder"))  # it never rested
    assert len(ts.PROMPTS["builder"]) == 2
    told = ts.PROMPTS["builder"][1]
    assert any(h["kind"] == "owner_reply" for h in ts.headers(told))
    assert MEMBER_LINE in told and LEADER_LINE not in told
    [question] = _questions(led, run_id)
    assert question["decision"]["text_sha256"] == _sha(answer)


@pytest.mark.parametrize("answer", ["Yes, add part.md.", " Yes, add part.md. "],
                         ids=["words", "padded"])
def test_an_answer_with_words_reaches_the_member_as_typed(
        led, box, run_id, tmp_path, monkeypatch, answer):
    owner = ls.Owner(led, answer, "stop").install(monkeypatch)
    ts.SCRIPTS["lead"] = _lead()
    ts.SCRIPTS["builder"] = [[ls.op("ask_owner", question=QUESTION),
                              ls.op("idle", note="waiting for the owner")], BUILD]
    team = _open(led, box, run_id, tmp_path)

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    assert [a["header"] for a in owner.asked] == ["builder asks"] and owner.answers == ["stop"]
    assert _owner_replies(led, run_id, "builder") == [answer]
    assert {"by": "owner", "was": "idle"} in _woken(led, run_id, "builder")
    told = ts.PROMPTS["builder"][1]
    assert "Yes, add part.md." in told
    assert MEMBER_LINE not in told and LEADER_LINE not in told
    [question] = _questions(led, run_id)
    assert question["decision"]["text_sha256"] == _sha(answer)
