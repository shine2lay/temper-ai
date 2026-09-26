"""The plan stage, faster (queue task 4, 2026-09-26): fewer steps, files asked for in batches, a check
whose second look starts from its own issues and a diff of what the lead changed, and a rule for each
problem the graders found in 3 or more of the 25 graded plans.

On the 29-bet plan test (2026-09-25/26) the stage took a median 63 min and up to 142 (b014): the
architect a median 35 min at high effort, and every agent used nearly all of its steps (architect 49-58
of 60, engineers 48 of 50, check 57 of 60), reading one or two files a turn. The check's second look
took as long as its first. The scripts run for real here, through ScriptAgent and /bin/sh, as the Bash
tool runs them.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.config.helpers import substitute_env_vars
from temper_ai.llm.prompt_renderer import PromptRenderer
from temper_ai.tools.base import ToolResult

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "configs" / "epd" / "agents"
WORKFLOW = ROOT / "configs" / "epd" / "workflows" / "epd_plan.yaml"
ENGINEERS = ("epd_plan_frontend", "epd_plan_backend", "epd_plan_numbers", "epd_plan_qa")
READERS = ("epd_plan_architect", *ENGINEERS, "epd_plan_check")

# b022's wrong fact, with the characters a shell would trip on
ISSUES = [{"kind": "fact", "task": 2, "what": "It's `dispatch(alert)`; the real one takes \"tenant_id\" first.",
           "fix": "Call dispatch(tenant_id, alert) $HOME.", "code": "backend/rollcall/alerts/dispatch.py:41"}]


def config(name: str) -> dict:
    """The agent config as the server hands it out."""
    return substitute_env_vars(yaml.safe_load((AGENTS / f"{name}.yaml").read_text()))["agent"]


def prompt(name: str) -> str:
    return " ".join(config(name)["system_prompt"].split())


def run(name: str, inputs: dict) -> dict:
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", name, name
    ctx.workspace_path = None

    def execute(_tool, args, **_kw):
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(), **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env, timeout=60)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    result = ScriptAgent(config=config(name)).run(inputs, ctx)
    assert result.status.value == "completed", f"{name}: {result.error} {result.output}"
    return result.structured_output


def render(name: str, inputs: dict) -> str:
    return PromptRenderer().render(config(name), inputs)[1]["content"]


# ---- fewer steps, read in batches ----------------------------------------------------------------

def test_fewer_steps_and_the_clock_never_binds_first():
    arch = config("epd_plan_architect")
    assert (arch["max_iterations"], arch["provider_config"]["effort"]) == (40, "medium")
    assert {n: config(n)["max_iterations"] for n in ENGINEERS} == dict.fromkeys(ENGINEERS, 30)
    assert config("epd_plan_check")["max_iterations"] == 40
    # A time limit ends a node with no answer, while the step limit lets it wrap up (four architects lost
    # their designs to the clock on 2026-09-25): every step must fit at ~90 s, the slowest seen.
    for name in (*READERS, "epd_plan_lead"):
        c = config(name)
        assert c["total_timeout"] >= c["max_iterations"] * 90, name


def test_every_reader_asks_for_its_files_in_one_turn():
    for name in READERS:
        assert "Read" in config(name)["tools"]
        assert "Ask for every file you need in one turn" in prompt(name), name


# ---- the second look ------------------------------------------------------------------------------

def test_the_second_look_is_wired_to_the_issues_and_the_diff():
    wf = yaml.safe_load(WORKFLOW.read_text())["workflow"]
    nodes = {n["name"]: n for n in wf["nodes"]}
    assert wf["version"] == 5
    assert nodes["docs"]["input_map"]["check_issues"] == "check.structured.issues"
    assert nodes["changes"]["agent"] == "epd_plan_changes" and nodes["changes"]["depends_on"] == ["lead"]
    check = nodes["check"]
    assert set(check["depends_on"]) == {"lead", "docs", "changes"}
    assert check["input_map"]["last_issues"] == "docs.structured.issues"
    assert check["input_map"]["changes"] == "changes.structured.diff"
    assert check["input_map"]["changed_lines"] == "changes.structured.changed_lines"
    # the lead's last pass stays: round 3 skips the check, and the revises rewind to docs
    assert check["loop_to"] == "docs" and check["max_loops"] == 3
    assert check["condition"] == {"source": "docs.structured.round", "operator": "not_equals", "value": 3}


@pytest.fixture
def plan(tmp_path):
    (tmp_path / "kb" / "core").mkdir(parents=True)
    (tmp_path / "kb" / "core" / "map.md").write_text("# map\n")
    pitch = tmp_path / "bet.md"
    pitch.write_text("# Say which pushes went out\n")
    d = tmp_path / "plan"
    d.mkdir()
    (d / "design.md").write_text("# Design\n")
    past = time.time() - 60  # the design came first; everything the lead writes is newer
    os.utime(d / "design.md", (past, past))
    return {"bet_path": str(pitch), "kb_dir": str(tmp_path / "kb"), "plan_dir": str(d),
            "tasks_path": str(tmp_path / "tasks.json")}


def docs(plan: dict, issues=None) -> dict:
    """The docs step as the workflow calls it: the check's issues are null until a check has run."""
    return run("epd_plan_docs", {**plan, "check_issues": issues})


def changes(plan: dict) -> dict:
    return run("epd_plan_changes", {"plan_dir": plan["plan_dir"], "tasks_path": plan["tasks_path"]})


def lead_writes(plan: dict, tasks: list, text: str, indent=None) -> None:
    Path(plan["tasks_path"]).write_text(json.dumps({"tasks": tasks}, indent=indent))
    (Path(plan["plan_dir"]) / "plan.md").write_text(text)


def test_the_second_look_gets_its_issues_and_only_what_the_lead_changed(plan):
    first = docs(plan)
    assert (first["round"], first["issues"]) == (1, [])
    lead_writes(plan, [{"id": 1, "change": "Call dispatch(alert)."}, {"id": 2, "change": "Show it."}],
                "# Plan\n\nD1. Push through dispatch.\n")
    assert changes(plan) == {"diff": "", "changed_lines": 0}, "the first look has nothing to compare"

    again = docs(plan, ISSUES)  # the check said revise: back to docs
    assert again["round"] == 2 and again["issues"] == ISSUES, "the issues reach the second look untouched"
    # the lead writes both files again in full, tasks.json laid out another way; only task 1 and D1 change
    lead_writes(plan, [{"id": 1, "change": "Call dispatch(tenant_id, alert)."}, {"id": 2, "change": "Show it."}],
                "# Plan\n\nD1. Push through dispatch(tenant_id, alert).\n", indent=4)
    got = changes(plan)
    lines = got["diff"].splitlines()
    minus = [x for x in lines if x.startswith("-") and not x.startswith("---")]
    plus = [x for x in lines if x.startswith("+") and not x.startswith("+++")]
    assert got["changed_lines"] == 4 == len(minus) + len(plus)
    assert any("Call dispatch(alert)." in x for x in minus)
    assert any("Call dispatch(tenant_id, alert)." in x for x in plus)
    assert "+D1. Push through dispatch(tenant_id, alert)." in plus
    assert not any("Show it." in x for x in minus + plus), "another layout is not a change"
    assert "--- tasks.json, the version you checked" in lines and "--- plan.md, the version you checked" in lines


def test_a_new_design_drops_the_kept_drafts_and_the_issues(plan):
    docs(plan)
    lead_writes(plan, [{"id": 1}], "# Plan\n")
    docs(plan, ISSUES)
    d = Path(plan["plan_dir"])
    assert (d / ".plan.before").read_text() == "# Plan\n" and (d / ".tasks.before").is_file()
    later = time.time() + 60  # a new run's architect wrote a new design after all of that
    os.utime(d / "design.md", (later, later))
    out = docs(plan, ISSUES)
    assert (out["round"], out["issues"]) == (1, [])
    assert not (d / ".plan.before").exists() and not (d / ".tasks.before").exists()
    assert changes(plan)["diff"] == "", "an older attempt's draft is not what this check read"


CHECK_INPUTS = dict.fromkeys((
    "bet_id", "bet_path", "gate", "kb_dir", "repo_path", "plan_dir", "tasks_path", "reach", "check_round",
    "lead_status", "lead_blocked", "last_issues", "changes", "changed_lines"))


def test_only_the_second_look_is_told_to_start_from_its_issues():
    first = render("epd_plan_check", {**CHECK_INPUTS, "check_round": 1, "last_issues": [], "changes": "",
                                      "changed_lines": 0})
    assert "The second look" not in first
    diff = "-D1. Push through dispatch.\n+D1. Push through dispatch(tenant_id, alert).\n"
    second = render("epd_plan_check", {**CHECK_INPUTS, "check_round": 2, "last_issues": ISSUES, "changes": diff,
                                       "changed_lines": 2})
    assert "The second look: start from your previous issues and what changed (about 20 tool calls)" in second
    assert "backend/rollcall/alerts/dispatch.py:41" in second, "its own previous issues"
    assert "+D1. Push through dispatch(tenant_id, alert)." in second and "(2 lines)" in second
    lost = render("epd_plan_check", {**CHECK_INPUTS, "check_round": 2, "last_issues": ISSUES, "changes": "",
                                     "changed_lines": 0})
    assert "Read the plan in full" in " ".join(lost.split()), "no diff: check it all"


LEAD_INPUTS = dict.fromkeys((
    "bet_id", "tasks_path", "plan_dir", "check_verdict", "check_issues", "round", "previous_tasks", "previous_plan",
    "pitch", "gate", "profile", "core", "design", "frontend", "backend", "numbers", "qa", "frontend_out",
    "backend_out", "numbers_out", "qa_out"))


def test_the_lead_fixes_each_issue_in_the_tasks():
    got = " ".join(render("epd_plan_lead", {**LEAD_INPUTS, "check_verdict": "revise", "check_issues": ISSUES,
                                            "round": 2, "previous_tasks": "{}", "previous_plan": "# Plan"}).split())
    assert "Fix each issue below in tasks.json itself" in got
    assert "say for each issue which task now carries its fix" in got


# ---- a rule for each problem the graders found in 3 or more plans (plan/results.md) --------------

@pytest.mark.parametrize(("name", "words"), [
    # work no criterion needs: 16 of the 25 graded plans
    ("epd_plan_architect", "adding behaviour is not"),
    ("epd_plan_lead", "adding behaviour is not"),
    ("epd_plan_check", "it adds work no criterion or the invariant needs"),
    ("epd_plan_frontend", "Not needed, and the lead leaves it out"),
    ("epd_plan_backend", "Not needed, and the lead leaves it out"),
    ("epd_plan_numbers", "Not needed, and the lead leaves it out"),
    # a place left saying the old thing: 12
    ("epd_plan_frontend", "Words the change makes false count too"),
    ("epd_plan_architect", "plus every place that would otherwise contradict the change"),
    # an acceptance that cannot fail (12) or fails on the base anyway (5)
    ("epd_plan_lead", "Never the whole suite or typecheck"),
    ("epd_plan_qa", "Never the whole suite or typecheck"),
    ("epd_plan_lead", "renders the component (renderToStaticMarkup)"),
    ("epd_plan_qa", "renders the component (renderToStaticMarkup"),
    # a criterion's state out of a checker's reach: 12
    ("epd_plan_qa", "A criterion proved only by a unit test is not reached"),
    # wrong facts about the code (9), a pinned test broken (6)
    ("epd_plan_check", "grep each one a task tells the implementer to call, keep, import or edit"),
    ("epd_plan_check", "name every test that renders or pins it"),
    # the pitch's literal words overridden: 5
    ("epd_plan_lead", "says something literally"),
    ("epd_plan_architect", "says something literally"),
    # a fix the check asked for that never reached tasks.json: 4
    ("epd_plan_check", "First confirm each previous issue is fixed in tasks.json itself"),
])
def test_each_common_plan_problem_has_a_rule(name, words):
    assert words in prompt(name), name
