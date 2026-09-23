"""Every judge's findings reach the fix round, and CI's checks are one of the judges.

A gate send-back rewinds the build to the implementer, and a rewind keeps one result:
the triggering node's (executor: `loop_feedback[trigger] = result`). The judges' own
outputs are cleared with the rest of the loop, so the implementer's
`review.structured.findings` resolved to nothing on every fix round there had been:
b007 and five runs before it opened on "no findings reached you" and were told not to
guess. The lists now ride out on the gate's result -- the one copy a rewind keeps.

The test step (task_test) runs the repository's CI checks on the candidate and is a
fourth judge. Its `fail` sends the build back like any other judge's; its `skipped`
(the step itself could not run) abstains, so a harness fault neither sends a build
back nor, at max_loops, throws one away -- and the summary says the checks were not run.

The gate runs out of the shipped YAML through the real ScriptAgent (the harness in
test_a_clause_nobody_walked_is_not_a_pass), the implementer's prompt through the real
PromptRenderer, so the Jinja on both hops is exercised.
"""

import re
from pathlib import Path

import pytest
import yaml

from temper_ai.llm.prompt_renderer import PromptRenderer
from tests.test_epd.test_a_clause_nobody_walked_is_not_a_pass import (
    AGENTS,
    PASSED,
    WORKFLOW,
    gate,
    node_named,
)

ROOT = Path(__file__).resolve().parents[2]
ALL_PASS = {**PASSED, "test_verdict": "pass"}

REVIEW = [{"severity": "major", "where": "api/routes/browse.py:361", "what": "Shows the RegT figure, not the effective one",
           "fix": "Read effective_buying_power"}]
SECURITY = [{"severity": "blocker", "where": ".env:3", "what": "A broker key is committed",
             "fix": "Rewrite the branch without it", "commits": ["abc1234"]}]
TESTS = [{"check": "CI / test / Run tests",
          "failure": "FAILED tests/unit/test_margin.py::test_cushion - assert 1 == 2"}]
QA = [{"where": "/browse", "what": "The buying power tile reads $0.00"}]


def wiring() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def prompt(**inputs) -> str:
    """The implementer's first message for these inputs, rendered as the agent renders it."""
    config = yaml.safe_load((AGENTS / "task_implement.yaml").read_text())["agent"]
    base = {"task_name": "Show effective buying power", "workspace_path": "/w", "branch": "epd/b009",
            "base_branch": "master", "stack_url": "https://b009.example"}
    return PromptRenderer().render(agent_config=config, input_data={**base, **inputs})[1]["content"]


class TestTheTestStepIsAJudge:
    """CI's checks on the candidate, beside the diff, the running app and the security read."""

    def test_a_check_the_change_broke_sends_the_build_back(self):
        out = gate(**PASSED, test_verdict="fail", test_failures=TESTS)
        assert out["verdict"] == "request_changes"
        assert out["changes_wanted_by"] == ["tests"]

    def test_passing_checks_are_one_more_approval(self):
        out = gate(**ALL_PASS)
        assert out["verdict"] == "approve"
        assert out["summary"] == "review and QA and security and tests approved"

    def test_three_approvals_do_not_carry_a_failing_suite(self):
        """No judge outranks another -- CI would reject the pull request anyway."""
        assert gate(**PASSED, test_verdict="fail")["verdict"] == "request_changes"

    def test_a_step_that_could_not_run_abstains_and_says_so(self):
        out = gate(**PASSED, test_verdict="skipped",
                   test_summary="the test step could not run: no worktree at (none given)")
        assert out["verdict"] == "approve"
        assert "tests" not in out["changes_wanted_by"]
        assert "CI's checks were not run on this commit (the test step could not run: no worktree" in out["summary"]
        assert "CI on the pull request is the first to run them" in out["summary"]

    def test_an_abstention_does_not_hide_another_judges_objection(self):
        out = gate(**{**PASSED, "review_verdict": "request_changes"}, test_verdict="skipped")
        assert out["verdict"] == "request_changes"
        assert out["changes_wanted_by"] == ["review"]

    def test_an_unreadable_test_verdict_is_not_consent(self):
        out = gate(**PASSED, test_verdict="probably fine")
        assert out["verdict"] == "request_changes"
        assert out["unreadable"] == ["tests=probablyfine"]

    def test_a_run_without_the_step_is_decided_by_the_others(self):
        """A run still on the v8 workflow has no test node; its gate must not stall on it."""
        out = gate(**PASSED)
        assert out["verdict"] == "approve"
        assert out["test_verdict"] is None

    def test_the_verdict_is_recorded(self):
        assert gate(**PASSED, test_verdict="fail")["test_verdict"] == "fail"


class TestTheListsRideOutOnTheGate:
    """The rewind keeps the gate's result and clears the judges'. Whatever the implementer
    is to answer has to be IN the gate's result."""

    def test_every_list_comes_back_out_as_it_went_in(self):
        out = gate(review_verdict="request_changes", qa_verdict="fail", security_verdict="fail",
                   test_verdict="fail", review_findings=REVIEW, qa_issues=QA, qa_summary="The tile is wrong",
                   security_findings=SECURITY, test_failures=TESTS)
        assert out["review_findings"] == REVIEW
        assert out["qa_issues"] == QA
        assert out["qa_summary"] == "The tile is wrong"
        assert out["security_findings"] == SECURITY
        assert out["test_failures"] == TESTS

    def test_a_finding_in_awkward_characters_arrives_whole(self):
        """Model-written prose, carried as JSON through the environment -- never as shell
        text and never as template text."""
        odd = [{"where": "a.py:1", "what": 'says "$(id)" and `id`; then\nexits \u2014 {{ x }} {% if y %}',
                "fix": "don't"}]
        out = gate(**{**ALL_PASS, "review_verdict": "request_changes"}, review_findings=odd)
        assert out["review_findings"] == odd

    def test_at_most_forty_of_each(self):
        many = [{"check": f"check {i}", "failure": "failed"} for i in range(55)]
        assert gate(**{**ALL_PASS, "test_verdict": "fail"}, test_failures=many)["test_failures"] == many[:40]

    @pytest.mark.parametrize("junk", [None, "", "None", "not a list", {"where": "a dict"}, 7])
    def test_a_list_that_is_not_one_is_none_and_the_gate_still_decides(self, junk):
        out = gate(**{**ALL_PASS, "review_verdict": "request_changes"}, review_findings=junk)
        assert out["verdict"] == "request_changes"
        assert out["review_findings"] == []

    def test_a_list_too_long_for_the_environment_is_dropped_not_fatal(self):
        """One environment variable holds at most 128 KB; past it the gate could not start,
        and a gate that does not answer is a build thrown away."""
        huge = [{"where": "x", "what": "y" * 3000, "fix": "z"} for _ in range(60)]  # ~180 KB of JSON
        out = gate(**{**ALL_PASS, "review_verdict": "request_changes"}, review_findings=huge)
        assert out["verdict"] == "request_changes"
        assert out["review_findings"] == []


class TestTheFixRoundReadsOnlyWhatARewindKeeps:
    """The structural form of the bug, checked for every node in the loop."""

    def test_no_node_in_the_loop_reads_a_result_the_rewind_cleared(self):
        """On a rewind to X the executor clears X and everything after it, and keeps the
        result of each node that triggered a rewind. So a node in the loop may read: a
        node before the loop, a node it depends on (made again this round, before it), or
        a trigger (kept). Anything else is nothing by the time it runs -- which is what
        `review.structured.findings` was to the implementer."""
        nodes = {n["name"]: n for n in wiring()["workflow"]["nodes"]}
        deps = {name: set(n.get("depends_on") or []) for name, n in nodes.items()}

        def ancestors(name: str) -> set:
            seen, todo = set(), list(deps[name])
            while todo:
                d = todo.pop()
                if d not in seen:
                    seen.add(d)
                    todo += deps.get(d, ())
            return seen

        triggers = {name for name, n in nodes.items() if n.get("loop_to")}
        cleared = {name for name in nodes
                   if any(nodes[t]["loop_to"] == name or nodes[t]["loop_to"] in ancestors(name)
                          for t in triggers)}
        assert {"implement", "review", "gate"} <= cleared  # the loop was found at all

        unreadable = []
        for name in sorted(cleared):
            for local, source in (nodes[name].get("input_map") or {}).items():
                read = source.split(".", 1)[0]
                if read in ("input", "workflow") or read not in cleared:
                    continue
                if read in ancestors(name) or read in triggers:
                    continue
                unreadable.append(f"{name}.{local} <- {source}")
        assert not unreadable, f"cleared by the rewind and not made again before they are read: {unreadable}"

    def test_every_list_the_implementer_reads_is_one_the_gate_prints(self):
        """A key the gate does not print resolves to nothing, just as quietly."""
        printed = set(gate(**ALL_PASS))
        for local, source in node_named(wiring(), "implement")["input_map"].items():
            node, _, field = source.partition(".structured.")
            if node == "gate":
                assert field in printed, f"implement.{local} reads gate.structured.{field}; the gate never prints it"

    def test_the_gate_is_handed_every_list(self):
        g = node_named(wiring(), "gate")["input_map"]
        assert g["review_findings"] == "review.structured.findings"
        assert g["security_findings"] == "security.structured.findings"
        assert g["qa_issues"] == "verify.structured.issues"
        assert g["qa_summary"] == "verify.structured.summary"
        assert g["test_failures"] == "test.structured.failures"
        assert g["test_verdict"] == "test.structured.verdict"
        assert g["test_summary"] == "test.structured.summary"

    def test_the_gate_waits_for_the_test_step(self):
        w = wiring()
        assert "test" in node_named(w, "gate")["depends_on"]
        step = node_named(w, "test")
        assert step["agent"] == "task_test"
        assert step["depends_on"] == ["implement"]
        assert "condition" not in step  # like security: it needs only git and the worktree

    def test_every_field_the_loop_records_is_one_the_workflow_puts_out(self):
        """epd_loop copies these into the bet's state and the pull request; a name the
        workflow does not output is a None in both, quietly."""
        loop = (ROOT / "configs" / "epd" / "bin" / "epd_loop.py").read_text()
        block = loop.split('st["stages"]["build"] = {k: out.get(k) for k in (', 1)[1].split(")}", 1)[0]
        recorded = [k for k in re.findall(r'"(\w+)"', block) if not k.startswith("_")]
        assert {"test_verdict", "test_summary"} <= set(recorded)
        outputs = wiring()["workflow"]["outputs"]
        assert [k for k in recorded if k not in outputs] == []


class TestTheImplementerIsToldWhatCameBack:
    """The last hop: the lists, as the rewind serves them, in the implementer's prompt."""

    def test_a_failing_check_is_in_the_prompt_with_its_report(self):
        p = prompt(test_failures=TESTS)
        assert "CI's checks fail on this commit where they pass on master" in p
        assert "- CI / test / Run tests \u2014 FAILED tests/unit/test_margin.py::test_cushion - assert 1 == 2" in p
        assert "/w/.epd/tests.md" in p
        assert "It was judged four ways" in p

    def test_every_judges_list_is_in_the_prompt(self):
        p = prompt(review_findings=REVIEW, qa_issues=QA, qa_summary="The tile is wrong",
                   security_findings=SECURITY, test_failures=TESTS)
        for text in ("Shows the RegT figure, not the effective one", "The buying power tile reads $0.00",
                     "A broker key is committed", "test_margin.py::test_cushion"):
            assert text in p
        assert "no findings reached you" not in p

    def test_what_the_gate_sends_back_is_what_the_prompt_shows(self):
        """Across the hop that was broken: the gate's result, served through the
        workflow's own input_map, rendered into the implementer's prompt."""
        out = gate(review_verdict="request_changes", qa_verdict="pass", security_verdict="pass",
                   test_verdict="fail", review_findings=REVIEW, test_failures=TESTS)
        served = {local: out[source.split(".structured.", 1)[1]]
                  for local, source in node_named(wiring(), "implement")["input_map"].items()
                  if source.startswith("gate.structured.")}
        p = prompt(**served)
        assert "Shows the RegT figure, not the effective one" in p
        assert "test_margin.py::test_cushion" in p
        assert "no findings reached you" not in p

    def test_the_first_round_is_not_told_it_was_sent_back(self):
        p = prompt()
        assert "sent back" not in p
        assert "Implement the plan." in p
