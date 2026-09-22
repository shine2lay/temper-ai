"""The gate's answer to a success threshold QA could not reach.

The dev stack exists so the promise can be checked before the merge. It was being
checked and then waved through: the verify agent reported clauses it could not walk,
the gate put the count in a sentence, and the pull request was approved. b004 and b005
both reached production that way, and `measure` -- a build, a ship, a deploy and a
round later -- recorded `iterate` for exactly the clause QA had already named.

So an unwalked clause now asks for changes, and the implementer's next round is the
route to that state. The one exception is a clause no build can settle at all ("no
confused item in the next report"): looping on that is a fix round spent on a
sentence, so it stays a note.

These tests run the gate script out of the shipped YAML through the real ScriptAgent,
so the Jinja that carries the clause lists into the environment is exercised too -- a
list that arrives as the text "None" is the bug class that made version 3 necessary.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.tools.base import ToolResult

AGENTS = Path(__file__).resolve().parents[2] / "configs" / "epd" / "agents"
GATE = AGENTS / "task_gate.yaml"
VERIFY = AGENTS / "task_verify.yaml"
WORKFLOW = Path(__file__).resolve().parents[2] / "configs" / "epd" / "workflows" / "epd_task.yaml"

PASSED = {"review_verdict": "approve", "qa_verdict": "pass", "security_verdict": "pass"}


def node_named(wiring: dict, name: str) -> dict:
    return next(n for n in wiring["workflow"]["nodes"] if n["name"] == name)


def gate(**inputs) -> dict:
    """The gate's decision for these inputs: the real agent, the real script, really run."""
    config = yaml.safe_load(GATE.read_text())["agent"]
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "test", "gate", "task_gate"
    ctx.workspace_path = "/tmp"

    def run(_tool, args, **_kw):
        done = subprocess.run(args["command"], shell=True, capture_output=True,
                              text=True, env={"PATH": "/usr/bin:/bin", **args["env"]})
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = run
    result = ScriptAgent(config=config).run(inputs, ctx)
    assert result.status.value == "completed", result.error
    return result.structured_output


class TestAClauseWithNoRouteSendsTheBuildBack:
    """The b004/b005 hole: every judge happy, one clause never walked, shipped anyway."""

    def test_an_unwalked_clause_asks_for_changes(self):
        """What used to be a sentence in an approval is now the send-back."""
        out = gate(**PASSED, qa_unverified=["The offer is cancelled and re-made: no cancel control"])
        assert out["verdict"] == "request_changes"
        assert "QA" in out["changes_wanted_by"]

    def test_the_summary_says_to_build_the_route(self):
        """The one line a human reads has to name the work, not just the shortfall."""
        out = gate(**PASSED, qa_unverified=["A rejected order says why: no way to make one reject"])
        assert "1 threshold clause(s) no browser action reached" in out["summary"]
        assert "build the route" in out["summary"]

    def test_qa_is_named_once_when_it_also_failed(self):
        """QA reports `fail` for these clauses itself, so the two paths must not double it."""
        out = gate(**PASSED | {"qa_verdict": "fail"},
                   qa_unverified=["A closed market says when it will fill: market never closes here"])
        assert out["changes_wanted_by"].count("QA") == 1
        assert out["summary"].startswith("QA asked for changes")

    def test_the_clauses_ride_out_on_the_gate(self):
        """A rewind keeps only the triggering node's output, so verify's list is gone by the
        time the implementer runs. It can only learn which clauses to open up from here."""
        clauses = ["no cancel control", "no rejected order"]
        assert gate(**PASSED, qa_unverified=clauses)["qa_unverified"] == clauses


class TestAClauseNoBuildCanSettleStillShips:
    """b007's fifth criterion names the NEXT report. No stack, dev or live, can walk it."""

    def test_it_does_not_hold_the_build(self):
        out = gate(**PASSED, qa_out_of_build=["No confused item in the next report: a future round"])
        assert out["verdict"] == "approve"
        assert out["changes_wanted_by"] == []

    def test_the_owner_is_told_on_the_pull_request(self):
        out = gate(**PASSED, qa_out_of_build=["No confused item in the next report: a future round"])
        assert "1 threshold clause(s) no build can settle" in out["summary"]
        assert "verify_out_of_build" in out["summary"]

    def test_both_kinds_at_once_send_back_and_still_note_the_other(self):
        out = gate(**PASSED,
                   qa_unverified=["No cancel control"],
                   qa_out_of_build=["No confused item in the next report"])
        assert out["verdict"] == "request_changes"
        assert "no browser action reached" in out["summary"]
        assert "no build can settle" in out["summary"]


class TestNothingUnwalkedIsStillAnApproval:
    """The change must not turn a clean round into a loop."""

    def test_a_clean_round_approves(self):
        out = gate(**PASSED)
        assert out["verdict"] == "approve"
        assert out["summary"] == "review and QA and security approved"

    def test_empty_lists_are_not_a_clause(self):
        out = gate(**PASSED, qa_unverified=[], qa_out_of_build=[])
        assert out["verdict"] == "approve"

    @pytest.mark.parametrize("junk", [None, "", "None", "not a list", "{}"])
    def test_a_list_that_arrives_as_junk_is_no_clauses(self, junk):
        """Version 3's bug was a value arriving as its own text. A malformed list must not
        invent a send-back -- the judges' verdicts decide the round on their own."""
        out = gate(**PASSED, qa_unverified=junk)
        assert out["verdict"] == "approve"
        assert out["qa_unverified"] == []

    def test_a_clause_with_quotes_and_braces_survives_the_journey(self):
        """The clause is model-written prose; it travels as JSON through the environment."""
        clause = 'The card says "Done" {not $(whoami)} \u2014 no route to a filled roll'
        assert gate(**PASSED, qa_unverified=[clause])["qa_unverified"] == [clause]


class TestTheWiringMatches:
    """The three files have to agree, or the lists arrive empty and the gate is back to v4."""

    def test_verify_emits_both_lists(self):
        text = VERIFY.read_text()
        assert '"unverified"' in text and '"out_of_build"' in text

    def test_verify_fails_on_a_clause_it_could_not_walk(self):
        """The gate's belt is `unverified` -- but QA's own verdict is the braces, and the
        rest of the loop (the ship card, the owner) reads that verdict."""
        text = VERIFY.read_text()
        assert 'verdict is `fail` when any clause is `unmet` OR any clause is\n      `unverified`' in text

    def test_the_workflow_hands_both_lists_to_the_gate(self):
        wiring = yaml.safe_load(WORKFLOW.read_text())
        gate_inputs = node_named(wiring, "gate")["input_map"]
        assert gate_inputs["qa_unverified"] == "verify.structured.unverified"
        assert gate_inputs["qa_out_of_build"] == "verify.structured.out_of_build"

    def test_the_implementer_reads_the_clauses_from_the_gate(self):
        """Not from verify: on a rewind that output is already cleared."""
        wiring = yaml.safe_load(WORKFLOW.read_text())
        assert node_named(wiring, "implement")["input_map"]["qa_unreachable"] == "gate.structured.qa_unverified"
        assert "{% if qa_unreachable %}" in (AGENTS / "task_implement.yaml").read_text()
