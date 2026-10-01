"""A question about the repos: which answerer takes it, how the answer is
taken out of the agent's text, waited for, and shown in Slack."""

from __future__ import annotations

import json

import pytest

from temper_ai.integrations.slack import blocks
from temper_ai.integrations.slack.answer import (
    ANSWER_NODE,
    ANSWER_WORKFLOW,
    ROAMEE_WORKFLOW,
    Answerer,
    extract,
    workflow_for,
)
from temper_ai.integrations.slack.commands import parse
from temper_ai.integrations.slack.ops import OpsError

from .conftest import OWNER


def finish(ops, text: str = "<answer>Yes.</answer>", status: str = "completed", why: str = "") -> None:
    """Every answering run ``ops`` starts ends at once, with ``text``."""
    def done(eid, workflow, inputs):
        if workflow in (ANSWER_WORKFLOW, ROAMEE_WORKFLOW):
            ops.runs[eid]["status"] = status
            ops.summaries[eid].update(duration_seconds=42, total_cost_usd=0.12, failure_summary=why or None)
            ops.agent_texts[(eid, ANSWER_NODE)] = text
    ops.on_start = done


def quick(ops) -> Answerer:
    return Answerer(ops, timeout_s=0, sleep=lambda _s: None)


class TestExtract:
    def test_the_answer_is_what_is_between_the_tags(self):
        raw = "That's enough to answer.\n<answer>\n**Yes.** `backend/trips/routes.py` has it.\n</answer>"
        assert extract(raw) == "*Yes.* `backend/trips/routes.py` has it."

    def test_the_last_answer_wins_and_a_missing_close_keeps_the_rest(self):
        assert extract("<answer>draft</answer> hmm <answer>final</answer>") == "final"
        assert extract("thinking <answer>cut off mid") == "cut off mid"

    def test_no_tags_means_the_whole_text(self):
        assert extract("  just this  ") == "just this"
        assert extract("") == ""

    def test_markdown_becomes_slack_formatting(self):
        raw = "<answer>## **Export**\nSee [the route](https://x.test/a).\n```python\nx = 1\n```</answer>"
        assert extract(raw) == "*Export*\nSee the route (https://x.test/a).\n```\nx = 1\n```"


class TestAnswerer:
    def test_a_finished_run_gives_its_answer(self, ops):
        finish(ops, "Checking.\n<answer>It can: `GET /api/trips/{id}/ics`.</answer>")
        got = quick(ops).answer("can rollcall export a roster?", "shine: which app?")
        assert ops.started == [(ANSWER_WORKFLOW, {"question": "can rollcall export a roster?",
                                                  "conversation": "shine: which app?"})]
        assert got.text == "It can: `GET /api/trips/{id}/ics`."
        assert (got.seconds, got.cost_usd) == (42, 0.12)

    def test_a_failed_run_says_why(self, ops):
        finish(ops, status="failed", why="failed at answer: out of credit")
        with pytest.raises(OpsError, match="failed \\(failed at answer: out of credit\\)"):
            quick(ops).answer("q")

    def test_too_slow_is_stopped(self, ops):
        with pytest.raises(OpsError, match="took more than"):
            quick(ops).answer("q")  # the fake run never ends
        assert ops.cancelled and ops.cancelled[0][1] == "Answering in Slack took too long"

    def test_no_answer_text_is_an_error(self, ops):
        finish(ops, text="   ")
        with pytest.raises(OpsError, match="without an answer"):
            quick(ops).answer("q")


class TestWhichAnswerer:
    """A question about roamee goes to roamee's own answerer, which can also
    see its staging stack and data; everything else stays with repo_answer."""

    @pytest.mark.parametrize("question", [
        "is roamee staging up?",
        "how many trips are in roamee's database?",
        "Roamee: what's open on GitHub?",
        "can roamee export a trip?",
    ])
    def test_a_question_that_names_roamee_alone_goes_to_roamees_answerer(self, question):
        assert workflow_for(question) == ROAMEE_WORKFLOW

    @pytest.mark.parametrize("question", [
        "can rollcall export a roster?",
        "what does temper-ai do when a run fails?",
        "do roamee and rollcall share the trip model?",   # two repos: the one that can read both
        "how does the pick work?",                        # no repo named at all
        "is roameeish a word?",                           # whole words only
    ])
    def test_everything_else_stays_with_repo_answer(self, question):
        assert workflow_for(question) == ANSWER_WORKFLOW

    def test_a_role_that_may_only_ask_about_roamee_always_gets_roamees_answerer(self):
        assert workflow_for("how does the pick work?", repos=["roamee"]) == ROAMEE_WORKFLOW
        assert workflow_for("what is open?", repos=("roamee",)) == ROAMEE_WORKFLOW
        assert workflow_for("what is open?", repos=("rollcall",)) == ANSWER_WORKFLOW

    def test_the_thread_counts_too(self):
        assert workflow_for("and is it up?", "shine: roamee's staging") == ROAMEE_WORKFLOW
        assert workflow_for("and is it up?", "shine: rollcall and roamee") == ANSWER_WORKFLOW

    def test_roamees_answerer_is_not_told_which_repos_it_may_read(self, ops):
        """It is roamee's and only roamee's, so it has no repos input to fill."""
        finish(ops, "<answer>It is up.</answer>")
        got = quick(ops).answer("is roamee staging up?", repos=["roamee"])
        assert ops.started == [(ROAMEE_WORKFLOW, {"question": "is roamee staging up?", "conversation": ""})]
        assert got.text == "It is up."

    def test_repo_answer_still_gets_them(self, ops):
        finish(ops, "<answer>It can.</answer>")
        quick(ops).answer("can rollcall export a roster?", repos=["rollcall", "temper-ai"])
        assert ops.started == [(ANSWER_WORKFLOW, {"question": "can rollcall export a roster?",
                                                  "conversation": "", "repos": "rollcall,temper-ai"})]


class TestShown:
    def test_the_model_cannot_ping_anyone(self):
        shown = blocks.answer("Tell <!channel> and <@U123> & co.", "abcd1234-x")
        dumped = json.dumps(shown)
        assert "<!channel>" not in dumped and "<@U123>" not in dumped
        assert "&lt;!channel&gt;" in dumped and "&amp; co." in dumped
        assert "<!channel>" not in shown["text"]

    def test_who_asked_what_it_took_and_where_to_look(self):
        shown = blocks.answer("*Yes.*\nMore.", "abcd1234-ffff", "https://temper.test/run/abcd1234",
                              seconds=51, usd=0.24, question="can it export?", by=OWNER)
        dumped = json.dumps(shown)
        assert f"<@{OWNER}> asked" in dumped and "can it export?" in dumped
        assert "<https://temper.test/run/abcd1234|`abcd1234`>" in dumped and "51s" in dumped and "$0.24" in dumped
        assert shown["text"] == "Yes."

    def test_a_long_answer_is_split_between_paragraphs(self):
        paras = [f"{i}" + "x" * 1400 for i in range(6)]
        shown = blocks.answer("\n\n".join(paras), "abcd1234-x")
        sections = [b["text"]["text"] for b in shown["blocks"] if b["type"] == "section"]
        assert len(sections) == 3 and all(len(s) <= blocks.SECTION_MAX for s in sections)
        assert "\n\n".join(sections) == "\n\n".join(paras)

    def test_one_huge_paragraph_is_cut_and_a_very_long_answer_ends_with_a_note(self):
        assert all(len(c) <= 100 for c in blocks.chunks("y" * 1000, 100))
        shown = blocks.answer("\n\n".join("z" * 2800 for _ in range(20)), "abcd1234-x")
        sections = [b for b in shown["blocks"] if b["type"] == "section"]
        assert len(sections) == blocks.ANSWER_SECTIONS and "cut short" in sections[-1]["text"]["text"]


class TestAskCommand:
    def test_the_question_is_taken_as_typed(self):
        cmd = parse("ask can roamee's app export a trip?  ")
        assert (cmd.verb, cmd.query, cmd.error) == ("ask", "can roamee's app export a trip?", "")
        assert parse("ASK\twhere is it").query == "where is it"

    def test_ask_without_a_question(self):
        cmd = parse("ask")
        assert cmd.verb == "ask" and "Ask what?" in cmd.error

    def test_help_mentions_it(self):
        assert "/temper ask <question>" in blocks.HELP
