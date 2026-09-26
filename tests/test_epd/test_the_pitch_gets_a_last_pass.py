"""The pitch stage (workflows/epd_pitch.yaml v4): two checks, then the writer's last pass.

On the v4 re-test (2026-09-25) the stage ran three full checks, and on 4 of 8 bets (b015 b019 b020
b021) nothing applied the last check's issues. Now `previous` counts the rounds as the plan stage's
`docs` does: round 3 is the writer's last pass, it applies the second check's issues, and the check
is skipped. A re-check starts from its own previous issues and a diff of what the writer changed
(`changes`), instead of reading everything again (v4's re-checks took 7-22 minutes, like first checks).

The scripts run for real here, through ScriptAgent and /bin/sh, as the Bash tool runs them.
"""

import subprocess
import tempfile
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
WORKFLOW = ROOT / "configs" / "epd" / "workflows" / "epd_pitch.yaml"

ISSUES_1 = [{"where": "criterion 2", "kind": "cannot_fail", "what": "It's what today's app shows: \"$5\".",
             "evidence": "screener.ts:922", "fix": "Read the lot's call."}]
ISSUES_2 = [{"where": "threshold", "kind": "contradiction", "what": "Says 3 criteria; there are 4.",
             "evidence": "the pitch", "fix": "Say 4."}]


def config(name: str) -> dict:
    """The agent config as the server hands it out."""
    return substitute_env_vars(yaml.safe_load((AGENTS / f"{name}.yaml").read_text()))["agent"]


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


def previous(out: Path, verdict=None, issues=None) -> dict:
    """The `previous` step as the workflow calls it: the check's verdict and issues are null on the first pass."""
    return run("epd_pitch_previous", {"out_path": str(out), "check_verdict": verdict, "check_issues": issues})


def changes(out: Path) -> dict:
    return run("epd_pitch_changes", {"out_path": str(out)})


@pytest.fixture
def out(tmp_path):
    return tmp_path / "bet.md"


def test_the_first_pass_is_round_one_with_no_draft_and_no_diff(out):
    assert previous(out) == {"pitch": "", "round": 1, "issues": []}
    out.write_text("# Bet b099: the lot's call\n1. QA reads $5.\n")
    assert changes(out) == {"diff": "", "changed_lines": 0, "no_pitch": False}


def test_two_revises_make_round_three_and_hand_over_each_draft_and_issues(out):
    previous(out)
    out.write_text("# Bet b099: the lot's call\n1. QA reads $5.\n2. It's covered.\n")
    got = previous(out, "revise", ISSUES_1)
    assert got["round"] == 2
    assert got["pitch"] == "# Bet b099: the lot's call\n1. QA reads $5.\n2. It's covered.\n"
    assert got["issues"] == ISSUES_1, "the re-check starts from these, apostrophes and quotes intact"

    out.write_text("# Bet b099: the lot's call\n1. QA reads $5.\n2. It's covered by the lot's call.\n")
    diff = changes(out)
    assert diff["changed_lines"] == 2
    assert "-2. It's covered.\n" in diff["diff"] and "+2. It's covered by the lot's call.\n" in diff["diff"]
    assert "the version you checked" in diff["diff"]

    got = previous(out, "revise", ISSUES_2)
    assert got["round"] == 3, "round 3 is the writer's last pass: the check is skipped"
    assert got["issues"] == ISSUES_2 and "covered by the lot's call" in got["pitch"]


def test_a_new_first_pass_starts_the_rounds_again(out):
    previous(out)
    out.write_text("draft 1\n")
    assert previous(out, "revise", ISSUES_1)["round"] == 2
    # a retried run writes to the same folder: its first pass is round 1, with nothing to compare
    assert previous(out) == {"pitch": "", "round": 1, "issues": []}
    assert changes(out)["diff"] == ""


def test_a_no_bet_the_check_sends_back_is_written_fresh(out):
    previous(out)  # the writer wrote no pitch (no_bet); the check disagreed
    got = previous(out, "revise", ISSUES_1)
    assert (got["round"], got["pitch"]) == (2, "")
    out.write_text("# Bet b099: now written\n")
    assert changes(out) == {"diff": "", "changed_lines": 0, "no_pitch": False}, "nothing to diff: check it in full"


def test_the_workflow_skips_the_check_on_the_last_pass():
    wf = yaml.safe_load(WORKFLOW.read_text())["workflow"]
    nodes = {n["name"]: n for n in wf["nodes"]}
    assert wf["version"] == 4
    check = nodes["check"]
    assert check["condition"] == {"source": "previous.structured.round", "operator": "not_equals", "value": 3}
    assert check["loop_to"] == "previous" and check["max_loops"] == 3
    assert set(check["depends_on"]) == {"write", "changes"}
    assert check["input_map"]["check_round"] == "previous.structured.round"
    assert check["input_map"]["last_issues"] == "previous.structured.issues"
    assert check["input_map"]["changes"] == "changes.structured.diff"
    assert nodes["previous"]["input_map"]["check_issues"] == "check.structured.issues"
    assert nodes["write"]["input_map"]["round"] == "previous.structured.round"
    assert nodes["changes"]["agent"] == "epd_pitch_changes" and nodes["changes"]["depends_on"] == ["write"]
    assert wf["outputs"]["rounds"] == "previous.structured.round"


def test_the_writer_keeps_only_write_and_room_to_answer():
    writer = config("epd_pitch_write")
    assert writer["tools"] == ["Write"], "owner, 2026-09-24: no Read tool for the writer"
    assert writer["provider_config"]["max_tokens"] == 64000, "b019's v4 run died on its first write at 32000"


def render(name: str, inputs: dict) -> str:
    return PromptRenderer().render(config(name), inputs)[1]["content"]


WRITE_INPUTS = {k: None for k in (
    "bet_id", "problem", "report", "goals", "profile", "reach", "out_path", "reach_situations", "reach_moving",
    "reach_cannot", "code_real", "code_cause", "code_claims", "code_places", "code_relies_on", "code_pinned",
    "code_size", "break_must", "break_fakes", "break_undecidable", "check_verdict", "check_issues", "previous",
    "round")}


def test_only_the_third_write_is_told_it_is_the_last_pass():
    first = render("epd_pitch_write", {**WRITE_INPUTS, "round": 1})
    assert "sent your previous version back" not in first
    second = render("epd_pitch_write", {**WRITE_INPUTS, "round": 2, "check_verdict": "revise",
                                        "check_issues": ISSUES_1, "previous": "# draft 1"})
    assert "sent your previous version back" in second and "This is your last pass" not in second
    third = render("epd_pitch_write", {**WRITE_INPUTS, "round": 3, "check_verdict": "revise",
                                       "check_issues": ISSUES_2, "previous": "# draft 2"})
    assert "This is your last pass" in third and "Says 3 criteria; there are 4." in third


CHECK_INPUTS = {k: None for k in (
    "bet_id", "problem_path", "pitch_path", "report_path", "code_dir", "reach", "qa_config_path",
    "measure_config_path", "reach_situations", "reach_cannot", "code_real", "code_places", "code_relies_on",
    "code_pinned", "code_size", "break_fakes", "write_status", "write_why_no_bet", "write_threshold",
    "write_test_data", "write_not_claimed", "write_not_followed", "write_calls", "write_walk", "write_fixes",
    "check_round", "last_issues", "changes", "changed_lines")}


def test_the_re_check_starts_from_its_issues_and_the_diff():
    first = render("epd_pitch_check", {**CHECK_INPUTS, "check_round": 1, "last_issues": [], "changes": "",
                                       "changed_lines": 0, "write_fixes": []})
    assert "This is a re-check" not in first
    again = render("epd_pitch_check", {**CHECK_INPUTS, "check_round": 2, "last_issues": ISSUES_1,
                                       "changes": "-2. It's covered.\n+2. It's covered by the lot's call.\n",
                                       "changed_lines": 2, "write_fixes": [{"issue": "c2", "fix": "reads the call"}]})
    assert "This is a re-check: start from your previous issues and what changed" in again
    assert "screener.ts:922" in again, "its own previous issues"
    assert "+2. It's covered by the lot's call." in again and "(2 lines)" in again
    fresh = render("epd_pitch_check", {**CHECK_INPUTS, "check_round": 2, "last_issues": ISSUES_1, "changes": "",
                                       "changed_lines": 0, "write_fixes": []})
    assert "Read the pitch in full" in " ".join(fresh.split()), "a no-bet sent back has no diff: check it all"


def test_a_no_bet_must_survive_the_check():
    prompt = " ".join(config("epd_pitch_check")["system_prompt"].split())
    assert "If the writer wrote no pitch (status no_bet), test each reason it gives." in prompt
    assert "never that the bet should go" in prompt
    writer = " ".join(config("epd_pitch_write")["system_prompt"].split())
    assert "That is the only reason for no_bet." in writer
