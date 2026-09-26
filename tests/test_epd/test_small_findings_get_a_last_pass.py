"""A build whose last round wants only small changes gets one more pass, not a hand fix.

On 2026-09-25 four builds spent the gate's three rounds with review still asking for
changes, and each needed a hand fix before it reached the owner's merge gate (RETRO gap 9).
For two of them, b037 and b056, every review finding was minor and QA, security and CI's
checks passed. The owner's rule: "One more fix pass on just those, then ship."

epd_task v13 adds that pass after the gate's loop:
  minors (task_minors)        decides, by the rule;
  minors_fix (task_implement) fixes exactly those findings in one commit (`last_pass`);
  minors_branch               checks HEAD is that commit;
  minors_test                 runs CI's checks again;
  minors_review (task_review) reads only that commit (last-pass mode);
  final (task_final)          gives the build's verdict.

The rule is tried on the four builds' real round-3 gate outputs (round3_gates.json): b037
and b056 take the pass; b047 (a blocker) and b055 (a blocker, a major) do not. The scripts
run out of the shipped YAML through the real ScriptAgent, with their inputs served through
the workflow's own input_map, so a wrong path in the wiring fails here too.
"""

import copy
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.llm.prompt_renderer import PromptRenderer
from temper_ai.stage.executor import execute_graph
from temper_ai.tools.base import ToolResult
from tests.test_stage.test_executor import _make_agent_node, _make_context

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "configs" / "epd" / "agents"
WORKFLOW = ROOT / "configs" / "epd" / "workflows" / "epd_task.yaml"
ROUND3 = json.loads((Path(__file__).parent / "round3_gates.json").read_text())


def wiring() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def node_named(name: str) -> dict:
    return next(n for n in wiring()["workflow"]["nodes"] if n["name"] == name)


def script(agent: str, **inputs) -> dict:
    """Run a script agent from its shipped YAML, for real, and return what it emitted."""
    config = yaml.safe_load((AGENTS / f"{agent}.yaml").read_text())["agent"]
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "test", agent, agent
    ctx.workspace_path = tempfile.mkdtemp()

    def run(_tool, args, **_kw):
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", **args["env"]})
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = run
    result = ScriptAgent(config=config).run(inputs, ctx)
    assert result.status.value == "completed", result.error
    return result.structured_output


def served(node: str, outputs: dict) -> dict:
    """What `node`'s input_map hands it, given the structured output of each source node."""
    got = {}
    for local, source in node_named(node)["input_map"].items():
        head, _, field = source.partition(".structured.")
        if field and head in outputs:
            got[local] = (outputs[head] or {}).get(field)
    return got


def gate_of(bet: str, **changes) -> dict:
    """A build's real round-3 gate output, changed as a test needs."""
    gate = copy.deepcopy(ROUND3[bet]["gate"])
    gate.update(changes)
    return gate


def minors(gate: dict) -> dict:
    """The rule's answer for this gate output."""
    return script("task_minors", **served("minors", {"gate": gate}))


IMPLEMENTED = {"status": "done", "commit": "3333333333"}   # round 3's implementer
FIXED = {"status": "done", "commit": "4444444444", "deviations": []}
GREEN = {"verdict": "pass", "summary": "CI's checks pass on 4444444", "failures": []}
APPROVED = {"verdict": "approve", "summary": "Both findings are fixed and nothing else changed.",
            "findings": [], "earlier_findings": [
                {"finding": "frontend/src/lib/screener.ts:922-923", "status": "fixed", "evidence": "lines deleted"},
                {"finding": "frontend/src/lib/screener.ts:648", "status": "fixed", "evidence": "floor/ceil"}]}


def verdict_of(gate: dict, fix=None, pass_test=None, pass_review=None) -> dict:
    """The build's verdict (task_final), every input served through the workflow's input_map."""
    outputs = {
        "gate": gate,
        "implement": IMPLEMENTED,
        "review": {"verdict": gate.get("review_verdict")},
        "test": {"verdict": gate.get("test_verdict"), "summary": "round 3's checks pass", "failures": []},
        "minors": minors(gate),
        "minors_fix": fix,
        "minors_test": pass_test,
        "minors_review": pass_review,
    }
    return script("task_final", **served("final", outputs))


def rendered(agent: str, **inputs) -> str:
    """An LLM agent's first message for these inputs, rendered as the agent renders it."""
    config = yaml.safe_load((AGENTS / f"{agent}.yaml").read_text())["agent"]
    base = {"task_name": "Say every screener check in one sentence", "workspace_path": "/w",
            "branch": "epd/b056", "base_branch": "master"}
    return PromptRenderer().render(agent_config=config, input_data={**base, **inputs})[1]["content"]


class TestTheRule:
    """Take the pass only when review alone asks, only for small things, and all else passed."""

    @pytest.mark.parametrize("bet", ["b037", "b056"])
    def test_small_findings_with_every_other_judge_passing_take_it(self, bet):
        out = minors(gate_of(bet))
        assert out["take"] is True
        assert out["findings"] == ROUND3[bet]["gate"]["review_findings"]
        assert "only for 2 small change(s)" in out["reason"]
        assert out["refused_because"] == []

    def test_b047s_blocker_refuses_it(self):
        """b047's real round 3: one blocker beside two minors. That one stays a hand fix."""
        out = minors(gate_of("b047"))
        assert out["take"] is False
        assert out["findings"] == []
        assert "not every finding is small (1 blocker among 3)" in out["reason"]

    def test_b055s_blocker_and_major_refuse_it(self):
        out = minors(gate_of("b055"))
        assert out["take"] is False
        assert "(1 blocker, 1 major among 2)" in out["reason"]

    def test_one_major_among_minors_refuses_it(self):
        gate = gate_of("b056")
        gate["review_findings"][1]["severity"] = "major"
        out = minors(gate)
        assert out["take"] is False
        assert "1 major among 2" in out["reason"]

    def test_a_nit_is_small(self):
        gate = gate_of("b056")
        gate["review_findings"][0]["severity"] = "nit"
        assert minors(gate)["take"] is True

    def test_a_finding_with_no_severity_is_not_small(self):
        gate = gate_of("b056")
        del gate["review_findings"][0]["severity"]
        out = minors(gate)
        assert out["take"] is False
        assert "1 unrated" in out["reason"]

    @pytest.mark.parametrize("judge,said", [
        ("qa_verdict", "fail"), ("security_verdict", "fail"), ("test_verdict", "fail"),
        ("test_verdict", "skipped"), ("qa_verdict", None), ("security_verdict", None)])
    def test_any_other_judge_short_of_pass_refuses_it(self, judge, said):
        """Strict: a judge that failed, abstained or never ran has not passed."""
        out = minors(gate_of("b056", **{judge: said}))
        assert out["take"] is False
        assert "did not pass" in out["reason"]

    @pytest.mark.parametrize("wanted", [["review", "QA"], ["review", "tests"], ["QA"], []])
    def test_changes_wanted_by_anyone_but_review_alone_refuse_it(self, wanted):
        out = minors(gate_of("b056", changes_wanted_by=wanted))
        assert out["take"] is False
        assert "not by review alone" in out["reason"]

    def test_an_unreadable_verdict_refuses_it(self):
        assert minors(gate_of("b056", unreadable=["QA=maybe"]))["take"] is False

    def test_a_clause_qa_could_not_walk_refuses_it(self):
        out = minors(gate_of("b056", qa_unverified=["A rejected order says why: no way to make one reject"]))
        assert out["take"] is False
        assert "could not walk 1 threshold clause(s)" in out["reason"]

    def test_a_list_the_gate_may_have_cut_refuses_it(self):
        one = ROUND3["b056"]["gate"]["review_findings"][0]
        out = minors(gate_of("b056", review_findings=[one] * 40))
        assert out["take"] is False
        assert "may be cut" in out["reason"]

    def test_no_findings_refuses_it(self):
        out = minors(gate_of("b056", review_findings=[]))
        assert out["take"] is False
        assert "listed no finding" in out["reason"]

    def test_an_approved_build_needs_no_pass(self):
        out = minors(gate_of("b056", verdict="approve", changes_wanted_by=[], review_verdict="approve",
                             review_findings=[]))
        assert out["take"] is False
        assert out["reason"] == "the gate approved: no last pass needed"

    def test_a_finding_is_data_whatever_it_holds(self):
        gate = gate_of("b056")
        gate["review_findings"][0]["what"] = "it's `x`\n\"quoted\" $(touch /tmp/pwned) ${HOME}"
        out = minors(gate)
        assert out["take"] is True
        assert out["findings"][0]["what"] == gate["review_findings"][0]["what"]


class TestTheBuildsVerdict:
    """task_final: the gate's verdict untouched without a pass; approve only after a clean one."""

    def test_an_approved_build_is_unchanged(self):
        gate = gate_of("b056", verdict="approve", summary="review and QA and security and tests approved",
                       changes_wanted_by=[], review_verdict="approve", review_findings=[])
        out = verdict_of(gate)
        assert out["verdict"] == "approve"
        assert out["summary"] == gate["summary"]
        assert out["changes_wanted_by"] == []
        assert out["commit"] == "3333333333"
        assert (out["review_verdict"], out["test_verdict"]) == ("approve", "pass")
        assert out["last_pass"] == {"ran": False, "reason": "the gate approved: no last pass needed"}

    def test_a_refused_build_stops_and_says_why(self):
        out = verdict_of(gate_of("b047"))
        assert out["verdict"] == "request_changes"
        assert out["summary"].startswith("review asked for changes — no last pass: not every finding is small")
        assert out["changes_wanted_by"] == ["review"]
        assert out["commit"] == "3333333333"
        assert out["last_pass"]["ran"] is False

    def test_a_clean_pass_approves_the_build_on_its_own_commit(self):
        out = verdict_of(gate_of("b056"), FIXED, GREEN, APPROVED)
        assert out["verdict"] == "approve"
        assert out["changes_wanted_by"] == []
        assert out["commit"] == "4444444444"
        assert (out["review_verdict"], out["test_verdict"]) == ("approve", "pass")
        assert out["test_summary"] == GREEN["summary"]
        assert out["summary"].startswith(
            "approved after a last pass: review's round 3 asked only for 2 small change(s); commit 44444444 made them")
        assert out["last_pass"]["ran"] is True
        assert out["last_pass"]["asked"] == 2
        assert out["last_pass"]["earlier_findings"] == APPROVED["earlier_findings"]

    def test_failing_checks_after_the_pass_keep_it_back(self):
        red = {"verdict": "fail", "summary": "1 check fails", "failures": [{"check": "CI / test", "failure": "x"}]}
        out = verdict_of(gate_of("b056"), FIXED, red, APPROVED)
        assert out["verdict"] == "request_changes"
        assert out["changes_wanted_by"] == ["tests"]
        assert "CI's checks on it did not pass (fail: 1 check fails)" in out["summary"]
        assert out["test_failures"] == red["failures"]
        assert out["commit"] == "4444444444"  # the branch's head, for whoever fixes it by hand

    def test_a_finding_still_open_keeps_it_back(self):
        still = {"verdict": "request_changes", "summary": "One is still open.", "earlier_findings": [],
                 "findings": [{"severity": "minor", "where": "frontend/src/lib/screener.ts:648",
                               "what": "still rounds to nearest", "fix": "floor it"}]}
        out = verdict_of(gate_of("b056"), FIXED, GREEN, still)
        assert out["verdict"] == "request_changes"
        assert out["changes_wanted_by"] == ["review"]
        assert "frontend/src/lib/screener.ts:648: still rounds to nearest" in out["summary"]

    def test_no_new_commit_is_no_fix(self):
        out = verdict_of(gate_of("b056"), {"status": "done", "commit": "3333333333"}, GREEN, APPROVED)
        assert out["verdict"] == "request_changes"
        assert "the implementer made no new commit" in out["summary"]

    def test_an_implementer_that_did_not_finish_is_no_fix(self):
        out = verdict_of(gate_of("b056"), {"status": "blocked", "commit": "4444444444"}, GREEN, APPROVED)
        assert out["verdict"] == "request_changes"
        assert "the implementer reported blocked" in out["summary"]

    def test_a_gate_that_gave_no_verdict_gives_none(self):
        """The gate failed (nothing was built): as before v13, there is no verdict to ship on."""
        out = script("task_final", **served("final", {}))
        assert out["verdict"] is None


class TestThePassIsToldWhatToDo:
    """The two model steps of the pass, as their prompts render from the wiring."""

    def test_the_implementer_gets_just_those_findings(self):
        p = rendered("task_implement", stack_url="https://b056.example",
                     **served("minors_fix", {"minors": minors(gate_of("b056"))}))
        assert "LAST PASS" in p
        assert "Fix exactly these and nothing else" in p
        assert "frontend/src/lib/screener.ts:922-923" in p
        assert "frontend/src/lib/screener.ts:648" in p
        assert "judged four ways" not in p  # not the ordinary send-back
        assert "SOFI" not in p              # QA's note is not the pass's to fix

    def test_an_ordinary_fix_round_is_unchanged(self):
        gate = ROUND3["b056"]["gate"]
        p = rendered("task_implement", review_findings=gate["review_findings"], qa_issues=gate["qa_issues"])
        assert "judged four ways" in p
        assert "LAST PASS" not in p

    def test_the_reviewer_reads_only_that_commit(self):
        p = rendered("task_review", **served("minors_review", {"minors": minors(gate_of("b056")),
                                                                "implement": IMPLEMENTED}))
        assert "git -C /w diff 3333333333..HEAD" in p
        assert "frontend/src/lib/screener.ts:648" in p
        assert "Review that fix." in p
        assert "Review the change." not in p

    def test_an_ordinary_review_is_unchanged(self):
        p = rendered("task_review")
        assert "Review the change." in p
        assert "LAST PASS" not in p


class TestTheWiring:
    def test_the_pass_comes_after_the_gates_loop_and_before_the_teardown(self):
        assert node_named("minors")["depends_on"] == ["gate"]
        assert node_named("minors_fix")["depends_on"] == ["minors"]
        assert node_named("minors_branch")["depends_on"] == ["minors_fix"]
        assert node_named("minors_test")["depends_on"] == ["minors_branch"]
        assert node_named("minors_review")["depends_on"] == ["minors_branch"]
        assert node_named("final")["depends_on"] == ["minors_test", "minors_review"]
        assert node_named("final")["run_after_failure"] is True
        assert node_named("stack_down")["depends_on"] == ["final"]

    def test_every_step_of_the_pass_waits_on_the_rule(self):
        """A step whose dependency its condition skipped still runs, so each carries the rule."""
        for name in ("minors_fix", "minors_branch", "minors_test", "minors_review"):
            assert node_named(name)["condition"] == {
                "source": "minors.structured.take", "operator": "equals", "value": True}, name

    def test_the_pass_uses_the_rounds_own_agents(self):
        agents = {n: node_named(n)["agent"] for n in ("minors_fix", "minors_branch", "minors_test", "minors_review")}
        assert agents == {"minors_fix": "task_implement", "minors_branch": "task_branch_check",
                          "minors_test": "task_test", "minors_review": "task_review"}
        assert node_named("minors_branch")["input_map"]["commit"] == "minors_fix.structured.commit"
        assert node_named("minors_review")["input_map"]["last_pass_since"] == "implement.structured.commit"

    def test_the_verdict_and_what_ship_reads_come_from_final(self):
        outputs = wiring()["workflow"]["outputs"]
        for key, field in [("verdict", "verdict"), ("verdict_summary", "summary"),
                           ("changes_wanted_by", "changes_wanted_by"), ("implement_commit", "commit"),
                           ("review_verdict", "review_verdict"), ("test_verdict", "test_verdict"),
                           ("test_summary", "test_summary"), ("test_failures", "test_failures"),
                           ("last_pass", "last_pass")]:
            assert outputs[key] == f"final.structured.{field}", key

    def test_the_rule_reads_only_what_the_gate_puts_out(self):
        emitted = set(ROUND3["b056"]["gate"])  # a real round 3 of task_gate v8
        for source in node_named("minors")["input_map"].values():
            node, field = source.split(".structured.")
            assert node == "gate" and field in emitted, source

    def test_final_reads_only_what_its_sources_put_out(self):
        made = {"minors": set(minors(gate_of("b056"))), "gate": set(ROUND3["b056"]["gate"])}
        replies = {n: (AGENTS / f"{a}.yaml").read_text() for n, a in (
            ("implement", "task_implement"), ("minors_fix", "task_implement"), ("review", "task_review"),
            ("minors_review", "task_review"), ("test", "task_test"), ("minors_test", "task_test"))}
        for source in node_named("final")["input_map"].values():
            node, field = source.split(".structured.")
            if node in made:
                assert field in made[node], source
            else:
                # an LLM agent names the field in its reply's JSON; task_test's script as a keyword
                assert f'"{field}"' in replies[node] or f"{field}=" in replies[node], source


class TestTheEngineRunsThePassOnce:
    """The real epd_task graph through the real executor, every step a stand-in with a canned answer."""

    def graph(self, take: bool, gate_verdict: str = "request_changes") -> dict:
        canned = {
            "environment": {"run_plan": True, "run_implement": True, "run_verify": True,
                            "stack_teardown": True, "teardown": True},
            "implement": IMPLEMENTED,
            "deploy": {"verify": True},
            "gate": {"verdict": gate_verdict},
            "minors": {"take": take},
            "minors_fix": FIXED,
        }
        nodes = {}
        for spec in wiring()["workflow"]["nodes"]:
            node = _make_agent_node(spec["name"], depends_on=spec.get("depends_on"),
                                    condition=spec.get("condition"), loop_to=spec.get("loop_to"),
                                    max_loops=spec.get("max_loops", 1),
                                    structured_output=canned.get(spec["name"], {}))
            node.config.loop_condition = spec.get("loop_condition")
            node.config.on_max_loops = spec.get("on_max_loops", "silent")
            node.config.run_after_failure = bool(spec.get("run_after_failure"))
            nodes[spec["name"]] = node
        execute_graph(list(nodes.values()), {}, _make_context(), graph_name="epd_task", is_workflow=True)
        return nodes

    def test_the_pass_runs_once_after_the_third_round(self):
        nodes = self.graph(take=True)
        assert nodes["implement"].run.call_count == 3
        assert nodes["gate"].run.call_count == 3
        for name in ("minors", "minors_fix", "minors_branch", "minors_test", "minors_review", "final",
                     "stack_down", "cleanup"):
            assert nodes[name].run.call_count == 1, name

    def test_nothing_of_the_pass_runs_when_the_rule_refuses(self):
        nodes = self.graph(take=False)
        for name in ("minors_fix", "minors_branch", "minors_test", "minors_review"):
            nodes[name].run.assert_not_called()
        nodes["final"].run.assert_called_once()
        nodes["stack_down"].run.assert_called_once()

    def test_an_approved_build_goes_straight_on(self):
        nodes = self.graph(take=False, gate_verdict="approve")
        assert nodes["gate"].run.call_count == 1
        nodes["minors"].run.assert_called_once()
        nodes["minors_fix"].run.assert_not_called()
        nodes["final"].run.assert_called_once()
