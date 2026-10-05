"""desk_check's mechanical check (configs/workflows/desk_check.yaml, product role) fails a check that a
researcher left without usable output, and names the assumption (queue #23).

An account limit can end a researcher's turn with "You've hit your session limit" and nothing else
(run 99732fd1 lost an opportunity_brief lens that way and its brief still passed). check_desk.py, which
desk_setup writes into the workspace, now fails an assumption whose checks/<id>.json or .md is missing,
empty, not valid JSON or such a message, and with --final one whose final answer, passed in by
desk_final from the workflow's input_map, is such a message. An answer the workflow could not find
arrives as __unwired__ and leaves the files to judge. No model and no network.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jinja2 import BaseLoader, ChainableUndefined, meta
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.script_agent import (
    BARE_FILTER,
    ENV_FILTER,
    QUOTED_FILTER,
    _rewrite_interpolations,
    _ValueStash,
)
from temper_ai.config.helpers import substitute_env_vars

ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = ROOT / "configs" / "agents"
WORKFLOW = ROOT / "configs" / "workflows" / "desk_check.yaml"
INJECTED = {"workspace_path", "run_id"}  # the script agent adds these to every template
LIMIT = "You've hit your session limit \u00b7 resets 10:50pm (UTC)"
# What the Claude provider returns as an answer when its call failed (finish_reason "error", not read yet).
TIMED_OUT = "Error: Claude Code CLI timed out"
STREAM_ENDED = "[claude_code error] stream ended with no result event: " + " | ".join(["node: stderr line"] * 40)
SLOTS = ("A1", "A2")


def served(path):
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def by_name(name):
    return served(AGENTS_DIR / f"{name}.yaml")["agent"]


def jinja(stash=None):
    """Jinja as the script agent sets it up, with its value filters."""
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    stash = stash if stash is not None else _ValueStash()
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    return env


def helper():
    """check_desk.py's source, cut from the heredoc desk_setup writes it with."""
    script = by_name("desk_setup")["script_template"]
    found = re.search(r"^cat > state/desk/check_desk\.py <<'(\w+)'\n(.*?)\n\1$", script, re.S | re.M)
    assert found, "desk_setup no longer writes check_desk.py"
    source = found.group(2)
    assert "{{" not in source and "{%" not in source and "{#" not in source, "the script agent's Jinja would rewrite it"
    return source


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


def findings(slot):
    """A researcher's checks/<id>.json for an honest unknown (no claims to verify against kept pages)."""
    return {"id": slot, "verdict": "unknown", "confidence": "low", "claims": [], "decisive": [],
            "why": "No public source states the share either way; two registries were searched in full.",
            "against_bar": "Neither the pass bar nor the kill bar can be judged from what was found.",
            "next_test": "Ask five offices how they verify coverage today.",
            "searched": ["the state registry", "the trade association's survey"],
            "not_found": "a count of offices that still verify by phone"}


@pytest.fixture
def workspace(tmp_path):
    """A finished desk check of two assumptions: both researchers' files, the report and check_desk.py."""
    desk = tmp_path / "state" / "desk"
    write(desk / "check_desk.py", helper())
    for slot in SLOTS:
        write(desk / "assumptions" / f"{slot}.json", {"id": slot, "assumption": f"Assumption {slot}",
                                                      "pass_if": "at least 3 sources", "kill_if": "none", "fatal": True})
        write(desk / "checks" / f"{slot}.json", findings(slot))
        write(desk / "checks" / f"{slot}.md", f"# {slot}\nWhat was searched, what was found and what it means.\n")
    write(desk / "report.json", {
        "verdicts": [{"id": s, "verdict": "unknown", "researcher_verdict": "unknown",
                      "why": "Nothing public settles it; the next test is a short call round.",
                      "next_test": "Ask five offices how they verify coverage today."} for s in SLOTS],
        "hypothesis_status": "open", "status_why": "Both assumptions are still unknown after the desk research.",
        "next_steps": ["Ask five offices how they verify coverage today."]})
    write(desk / "report.md", "# Desk check\n")
    return tmp_path


def run(ws, *args, **answers):
    """check_desk.py, with each given researcher's final answer passed the way desk_final passes it."""
    env, extra = dict(os.environ), []
    for slot, text in answers.items():
        env[f"ANSWER_{slot}"] = text
        extra += ["--answer", f"{slot}=ANSWER_{slot}"]
    return subprocess.run([sys.executable, "state/desk/check_desk.py", *args, *extra], cwd=ws, capture_output=True,
                          text=True, timeout=60, env=env)


def final(ws, **answers):
    done = run(ws, "--final", **answers)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def checks(ws, name):
    return ws / "state" / "desk" / "checks" / name


# ---- the configs ---------------------------------------------------------------------------------


def test_the_final_step_gets_each_researchers_answer():
    nodes = {n["name"]: n for n in served(WORKFLOW)["workflow"]["nodes"]}
    assert nodes["final"]["input_map"] == {f"a{n}": f"check_{n}.output" for n in range(1, 7)}
    for n in range(1, 7):
        assert nodes[f"check_{n}"]["input_map"] == {"slot": f"A{n}"}, "check_<n> researches assumption A<n>"
    cfg = by_name("desk_final")
    used = meta.find_undeclared_variables(jinja().parse(cfg["script_template"]))
    assert used <= set(nodes["final"]["input_map"]) | INJECTED, f"desk_final uses {sorted(used)}"
    for name in nodes["final"]["input_map"]:
        assert f"{name} is string else '__unwired__'" in cfg["script_template"], f"{name} left unfed is __unwired__"


def test_the_final_step_parses_under_sh():
    cfg = by_name("desk_final")
    script = jinja().from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr


# ---- the check ------------------------------------------------------------------------------------


def test_a_check_whose_researchers_all_answered_passes(workspace):
    result = final(workspace)
    assert result["verdict"] == "pass", result["problems"]
    assert result["parts"] == {"A1": "ok", "A2": "ok"} and result["answers_checked"] == []


LOST = [
    ("its findings gone", lambda ws: checks(ws, "A2.json").unlink(), "A2: state/desk/checks/A2.json is missing"),
    ("its write-up gone", lambda ws: checks(ws, "A2.md").unlink(), "A2: state/desk/checks/A2.md is missing"),
    ("an empty write-up", lambda ws: checks(ws, "A2.md").write_text(" \n"), "A2: state/desk/checks/A2.md is empty"),
    ("broken JSON", lambda ws: checks(ws, "A1.json").write_text('{"id": "A1",'),
     "A1: state/desk/checks/A1.json is not valid JSON"),
    ("a limit message for findings", lambda ws: checks(ws, "A2.json").write_text(LIMIT),
     "A2: state/desk/checks/A2.json is an account-limit or error message"),
    ("a limit message for a write-up", lambda ws: checks(ws, "A1.md").write_text("API Error: 529 overloaded_error"),
     "A1: state/desk/checks/A1.md is an account-limit or error message"),
    ("a failed call for a write-up", lambda ws: checks(ws, "A2.md").write_text(STREAM_ENDED),
     "A2: state/desk/checks/A2.md is an account-limit or error message"),
]


@pytest.mark.parametrize(("lose", "problem"), [x[1:] for x in LOST], ids=[x[0] for x in LOST])
def test_an_assumption_whose_researcher_left_no_usable_output_fails_by_name(workspace, lose, problem):
    lose(workspace)
    result = final(workspace)
    assert result["verdict"] == "fail"
    assert result["problems"][0].startswith(problem), result["problems"]
    slot = problem[:2]
    assert [s for s, why in result["parts"].items() if why != "ok"] == [slot]


def test_a_researcher_whose_final_answer_is_a_limit_message_fails_the_check(workspace):
    result = final(workspace, A2=LIMIT)
    assert result["verdict"] == "fail"
    assert result["problems"] == [f'A2: its final answer is an account-limit or error message ("{LIMIT}")']
    assert result["parts"]["A2"] == f'its final answer is an account-limit or error message ("{LIMIT}")'


@pytest.mark.parametrize("answer", [TIMED_OUT, "Error: claude token pool exhausted \u2014 all 3 tokens cooling",
                                    STREAM_ENDED], ids=["timed out", "pool exhausted", "stream ended"])
def test_a_researcher_whose_final_answer_is_a_failed_call_fails_the_check(workspace, answer):
    result = final(workspace, A1=answer)
    assert result["verdict"] == "fail"
    assert result["problems"][0].startswith("A1: its final answer is an account-limit or error message")
    assert [s for s, why in result["parts"].items() if why != "ok"] == ["A1"]


def test_research_answers_and_answers_not_passed_in_leave_the_check_passing(workspace):
    research = '```json\n{"status": "completed", "slot": "A1", "verdict": "unknown", "note": "quota data paywalled"}\n```'
    result = final(workspace, A1=research, A2="__unwired__", A5=LIMIT)
    assert result["verdict"] == "pass", result["problems"]
    assert result["answers_checked"] == ["A1"], "only listed assumptions, and only answers the workflow found"


def test_a_researchers_own_check_flags_its_empty_write_up_and_ignores_answers(workspace):
    checks(workspace, "A1.md").write_text("")
    done = run(workspace, "A1")
    assert done.returncode == 1 and "- A1: state/desk/checks/A1.md is empty" in done.stdout
    assert run(workspace, "A2", A2=LIMIT).returncode == 0, "final answers are judged only by the last step"


def test_the_final_step_passes_each_researchers_answer_to_the_check(workspace):
    """desk_final rendered the way the script agent renders it: a researcher's answer reaches check_desk.py,
    and one the workflow could not find (None, or a slot that never ran) is left to the files."""
    cfg = by_name("desk_final")
    stash = _ValueStash()
    script = jinja(stash).from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(
        workspace_path=str(workspace), a1="y" * 9000, a2=LIMIT, a3="", a4=None)
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120, cwd=workspace,
                          env={**os.environ, **stash.env})
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["answers_checked"] == ["A1", "A2"]
    assert result["verdict"] == "fail" and result["problems"][0].startswith("A2: its final answer is an account-limit")
    assert max(len(v) for v in stash.env.values()) <= 4000, "a long answer is cut to its first 4000 characters"
