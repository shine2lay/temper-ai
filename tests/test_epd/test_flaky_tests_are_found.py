"""qa_flaky_report: tests that pass and fail on the same code are found, and told apart from broken ones.

QA's flaky-test report runs a repository's CI (the live task_test, unchanged) N times on one commit
and counts per test how often it failed (configs/epd/bin/qa_flaky_tally.py). A report that calls a
stable test flaky, or a broken one flaky, sends its owner after nothing, so it is held to its rules
here on a fictional bakery app:

- a test that failed in some repetitions and passed in others is flaky, with its rate, its first
  error line and the repetitions it failed in; one that failed in every repetition is broken;
- a pass is inferred only where the test's check completed: a check that failed without naming a
  test (a download that went wrong), timed out or never ran says nothing about its tests, and a
  test whose file did not import in a repetition is neither passed nor failed there;
- such a check is counted apart: an infrastructure flake when it completed in other repetitions,
  "never completes" when it completed in none; a repetition that never answered is listed apart;
- a failure list task_test cut short is read whole from its report, or not counted at all;
- the live builds' history is read with GETs only, and a history that cannot be read costs the
  report nothing.

The workflow's own steps run under /bin/sh as the script agent runs them, task_test really runs the
fixture's CI, and the workflow is laid out from its templates as a run start lays it out.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from jinja2 import BaseLoader, ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.script_agent import (
    BARE_FILTER,
    ENV_FILTER,
    QUOTED_FILTER,
    ScriptAgent,
    _rewrite_interpolations,
    _ValueStash,
)
from temper_ai.config.helpers import substitute_env_vars
from temper_ai.stage.input_defaults import fill_input_defaults
from temper_ai.stage.models import WorkflowConfig
from temper_ai.stage.template_expansion import expand_templates
from temper_ai.tools.base import ToolResult

ROOT = Path(__file__).resolve().parents[2]
EPD = ROOT / "configs" / "epd"
TALLY = EPD / "bin" / "qa_flaky_tally.py"
WORKFLOW = EPD / "workflows" / "qa_flaky_report.yaml"


def load(path: Path, name: str) -> types.ModuleType:
    """A helper script loaded as a module, without leaving bytecode next to it."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


tally = load(TALLY, "qa_flaky_tally_under_test")


def served(path: Path) -> dict:
    """The config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))


def agent_config(name: str) -> dict:
    return served(EPD / "agents" / f"{name}.yaml")["agent"]


def run_step(name: str, cwd: Path, **values) -> tuple[int, dict | None, str]:
    """A script step rendered the way the script agent renders it, then run by /bin/sh. The shipped
    scripts it calls (/app/configs/...) are this checkout's."""
    cfg = agent_config(name)
    stash = _ValueStash()
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    script = env.from_string(_rewrite_interpolations(cfg["script_template"], cfg["name"])).render(**values)
    script = script.replace("/app/configs/", f"{ROOT}/configs/")
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120, cwd=cwd,
                          env={**os.environ, **stash.env, "PYTHONDONTWRITEBYTECODE": "1"})
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    return done.returncode, (json.loads(lines[-1]) if lines else None), done.stdout + done.stderr


def ci_once(slot: str, base: str) -> str:
    """One repetition's task_test: the real agent and script on one copy; what it printed."""
    config = served(EPD / "agents" / "task_test.yaml")["agent"]
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", "run", "task_test"
    ctx.workspace_path = slot

    def execute(_tool, args, **_kw):
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(), **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env,
                              timeout=120)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    result = ScriptAgent(config=config).run({"workspace_path": slot, "base_branch": base}, ctx)
    assert result.status.value == "completed", result.error
    return result.output


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(repo.parent),
                               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return done.stdout.strip()


# ---- the fixture: a bakery whose tests fail as the dice say ---------------------------------------

# A stand-in for pytest, found by `python3 -m pytest` because the checkout is the working directory:
# it prints the summary lines in a file outside the repository, which each repetition rewrites, and
# fails when there are any. Same commit, different outcomes: what a flaky suite looks like.
FAKE_PYTEST = '''\
import pathlib, sys
dice = pathlib.Path(DICE)
lines = [l for l in dice.read_text().splitlines() if l.strip()] if dice.exists() else []
for l in lines:
    print(l)
print(f"{len(lines)} failed, 9 passed" if lines else "12 passed")
sys.exit(1 if lines else 0)
'''

CRUST = "tests/test_crust.py::test_crust_is_golden"
OVEN = "tests/test_oven.py::test_oven_heats_to_220"
ICING = "tests/test_icing.py"
ICING_SETS = "tests/test_icing.py::test_icing_sets"
FONTS = "curl: (6) Could not resolve host: fonts.bakery.example"
NO_BROWSER = "browserType.launch: Host system is missing dependencies to run browsers."

# What each repetition's CI says; None: the repetition never answered (its step timed out).
ROLLS = [
    {"backend": [f"FAILED {CRUST} - AssertionError: the crust took 61 s, the limit is 60 s",
                 f"FAILED {OVEN} - assert 200 == 220",
                 f"FAILED {ICING_SETS} - AssertionError: still runny after 5 s"], "fonts": ""},
    {"backend": [f"FAILED {OVEN} - assert 200 == 220"], "fonts": FONTS},
    {"backend": [f"FAILED {CRUST} - AssertionError: the crust took 63 s, the limit is 60 s",
                 f"FAILED {OVEN} - assert 200 == 220",
                 f"ERROR {ICING} - ModuleNotFoundError: No module named 'sugar'"], "fonts": ""},
    {"backend": [f"FAILED {OVEN} - assert 200 == 220"], "fonts": ""},
    None,
]


def bakery_ci(dice: Path) -> dict:
    return {
        "name": "ci",
        "on": {"pull_request": None},
        "jobs": {
            "backend": {"runs-on": "ubuntu-latest", "steps": [
                {"uses": "actions/checkout@v4"},
                {"name": "Tests", "run": "python3 -m pytest -q"}]},
            "frontend": {"runs-on": "ubuntu-latest", "steps": [
                {"uses": "actions/checkout@v4"},
                # A download that sometimes fails: it says how, but names no test.
                {"name": "Fetch fonts", "run": f"cat {dice}/fonts.txt 2>/dev/null || true; test ! -s {dice}/fonts.txt"},
                {"name": "Tests", "run": "echo '12 passed'"}]},
            "walk": {"runs-on": "ubuntu-latest", "steps": [
                {"uses": "actions/checkout@v4"},
                # A browser that cannot start where the CI runs: it never gets to a test.
                {"name": "Walk every page", "run": f"echo '{NO_BROWSER}'; exit 1"}]},
        },
    }


@pytest.fixture
def bakery(tmp_path: Path) -> types.SimpleNamespace:
    dice = tmp_path / "dice"
    dice.mkdir()
    repo = tmp_path / "bakery"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    files = {"pytest.py": FAKE_PYTEST.replace("DICE", repr(str(dice / "backend.txt"))),
             "tests/test_crust.py": "", "tests/test_oven.py": "", "tests/test_icing.py": "",
             ".github/workflows/ci.yml": yaml.safe_dump(bakery_ci(dice), sort_keys=False)}
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "the bakery")
    bundle = tmp_path / "bakery.bundle"
    git(repo, "bundle", "create", str(bundle), "--all")
    return types.SimpleNamespace(repo=repo, bundle=bundle, dice=dice, sha=git(repo, "rev-parse", "HEAD"))


def prepare(tmp_path: Path, bakery, runs=5, **values) -> dict:
    values = {"repo": str(bakery.bundle), "commit": "main", "runs": runs, "parallel": 2,
              "out": str(tmp_path / "out"), "work_root": str(tmp_path / "work"), **values}
    code, ready, log = run_step("qa_flaky_prepare", tmp_path, **values)
    assert code == 0 and ready and ready["status"] == "ready", log
    return ready


@pytest.fixture
def report(tmp_path: Path, bakery) -> types.SimpleNamespace:
    """The whole report on the bakery, step by step as the workflow runs it: prepare, then for each
    repetition task_test on its copy and keep, then the tally."""
    ready = prepare(tmp_path, bakery)
    kept = []
    for i, roll in enumerate(ROLLS):
        slot = ready[f"slot_{i}"]
        if roll is None:
            values = {"result": "", "step_status": "failed", "step_error": "the step did not finish in 3000 s"}
        else:
            (bakery.dice / "backend.txt").write_text("\n".join(roll["backend"]) + "\n")
            (bakery.dice / "fonts.txt").write_text(roll["fonts"])
            values = {"result": ci_once(slot, ready["commit"]), "step_status": "completed", "step_error": None}
        code, answer, log = run_step("qa_flaky_keep", tmp_path, index=str(i), tree=slot, out=ready["out"], **values)
        assert code == 0 and answer["status"] == "kept", log
        kept.append(answer)
    code, brief, log = run_step(
        "qa_flaky_tally", tmp_path, prepare_status="ready", prepare_error=None, out=ready["out"],
        runs=ready["runs"], commit=ready["commit"], repo=ready["repo"], subject=ready["subject"],
        parallel=ready["parallel"], work_root=ready["work_root"], history=False,
        history_api="http://127.0.0.1:9", history_workflows="epd_loop", run_id="run-bakery")
    assert code == 0, log
    out = Path(ready["out"])
    return types.SimpleNamespace(ready=ready, kept=kept, brief=brief, out=out,
                                 json=json.loads((out / "report.json").read_text()),
                                 md=(out / "report.md").read_text())


def test_by_test(report):
    tests = {t["id"]: t for t in report.json["tests"]}
    assert set(tests) == {CRUST, OVEN, ICING, ICING_SETS}, "every test that ever failed, and none other"

    crust = tests[CRUST]
    assert (crust["class"], crust["failures"], crust["completed"], crust["rate"]) == ("flaky", 2, 4, 0.5)
    assert crust["failed_in"] == [0, 2]
    assert crust["first_error"] == "AssertionError: the crust took 61 s, the limit is 60 s"
    assert crust["other_errors"] == ["AssertionError: the crust took 63 s, the limit is 60 s"]
    assert crust["check"] == "backend · Tests"
    assert crust["rate_95"][0] < 0.5 < crust["rate_95"][1]

    oven = tests[OVEN]
    assert (oven["class"], oven["failures"], oven["completed"]) == ("broken", 4, 4), \
        "failing every time is broken, not flaky"

    # In repetition 2 the file did not import: its test neither passed nor failed there.
    sets = tests[ICING_SETS]
    assert (sets["class"], sets["failures"], sets["completed"], sets["unknown_in"]) == ("flaky", 1, 3, [2])
    icing = tests[ICING]
    assert (icing["kind"], icing["class"], icing["failures"], icing["completed"]) == ("file", "flaky", 1, 4)
    assert icing["first_error"] == "ModuleNotFoundError: No module named 'sugar'"

    assert [t["id"] for t in report.json["tests"]] == [CRUST, ICING_SETS, ICING, OVEN], \
        "flaky first, the most frequent first; then broken"


def test_by_check(report):
    checks = {c["check"]: c for c in report.json["checks"]}
    fonts = checks["frontend · Fetch fonts"]
    assert fonts["class"] == "infrastructure flake"
    assert (fonts["completed"], fonts["no_test_lines_in"]) == (3, [1])
    assert FONTS in fonts["said"]
    walk = checks["walk · Walk every page"]
    assert (walk["class"], walk["completed"]) == ("never completes", 0)
    assert NO_BROWSER in walk["said"]
    assert checks["frontend · Tests"]["class"] == "stable"
    assert checks["frontend · Tests"]["passed"] == 4
    assert checks["backend · Tests"]["class"] == "has failing tests"
    assert all(c["no_answer"] == 1 for c in checks.values()), "the silent repetition is counted for no check"


def test_a_repetition_that_never_answered_is_listed_and_counted_nowhere(report):
    assert report.json["answered"] == 4
    assert report.json["no_answer"] == [
        {"repetition": 4, "why": "task_test gave no answer (the step did not finish in 3000 s)"}]
    assert "the step did not finish in 3000 s" in report.md


def test_the_report_and_the_answer(report):
    brief = report.brief
    assert brief["status"] == "reported" and brief["answered"] == 4 and brief["runs"] == 5
    assert [x["id"] for x in brief["flaky"]] == [CRUST, ICING_SETS, ICING]
    assert [x["id"] for x in brief["broken"]] == [OVEN]
    assert [x["check"] for x in brief["infrastructure"]] == ["frontend · Fetch fonts"]
    assert brief["never_completes"] == ["walk · Walk every page"]
    assert brief["history"] == "off"
    assert brief["summary"].startswith("3 flaky, 1 broken, 1 check(s) with infrastructure flakes, "
                                       "1 check(s) that never completed in 4 of 5 repetitions")
    assert report.json["commit"] == report.ready["commit"] and report.json["run_id"] == "run-bakery"
    for line in (CRUST, "61 s", OVEN, FONTS, NO_BROWSER, "## Flaky tests", "## Broken tests"):
        assert line in report.md, f"report.md lacks {line}"
    assert "2 repetitions ran at a time" in report.md, "parallel repetitions share a box: said"


def test_each_repetition_is_kept_and_its_copy_removed(report):
    for i, kept in enumerate(report.kept):
        folder = report.out / "runs" / f"run_{i}"
        assert kept["kept"] == str(folder) and kept["removed"] is True
        assert not Path(report.ready[f"slot_{i}"]).exists()
    assert (report.out / "runs" / "run_0" / "tests.md").read_text().startswith("# Tests: ")
    assert list((report.out / "runs" / "run_0" / "logs").glob("*.log")), "task_test's logs are kept"
    assert json.loads((report.out / "runs" / "run_4" / "step.json").read_text())["status"] == "failed"
    assert report.brief["work_removed"] is True and not Path(report.ready["work_root"]).exists()


def test_the_tally_is_the_same_twice(report):
    tally.main(["--out", str(report.out), "--runs", "5", "--commit", report.ready["commit"],
                "--subject", report.ready["subject"], "--repo", report.ready["repo"], "--parallel", "2",
                "--run-id", "run-bakery"])
    assert json.loads((report.out / "report.json").read_text()) == report.json


# ---- prepare --------------------------------------------------------------------------------------


def test_prepare_makes_a_fresh_copy_of_the_commit_per_repetition(tmp_path, bakery):
    ready = prepare(tmp_path, bakery, runs=3)
    assert ready["commit"] == bakery.sha and ready["subject"] == "the bakery"
    assert (ready["runs"], ready["parallel"]) == (3, 2)
    root = Path(ready["work_root"])
    assert root.parent == tmp_path / "work" and root.name.startswith("qa-flaky.")
    for i in range(3):
        slot = Path(ready[f"slot_{i}"])
        assert slot == root / f"run_{i}" and (slot / ".git").is_dir(), "each copy is a clone of its own"
        assert git(slot, "rev-parse", "HEAD") == bakery.sha
        assert (slot / "pytest.py").is_file()
    assert "slot_3" not in ready
    assert (tmp_path / "out" / "runs").is_dir()


def test_prepare_takes_a_repository_folder_and_a_commit_id(tmp_path, bakery):
    ready = prepare(tmp_path, bakery, runs=2, repo=str(bakery.repo), commit=bakery.sha[:12])
    assert ready["commit"] == bakery.sha


@pytest.mark.parametrize("change, error", [
    ({"runs": 1}, "runs must be 2 to 100"),
    ({"runs": 101}, "runs must be 2 to 100"),
    ({"runs": "x"}, "runs must be a whole number"),
    ({"parallel": 9}, "parallel must be 1 to 8"),
    ({"parallel": 0}, "parallel must be 1 to 8"),
    ({"commit": "main; rm -rf /"}, "commit must be a commit id or a branch name"),
    ({"commit": "--upload-pack=x"}, "commit must be a commit id or a branch name"),
    ({"commit": "no-such-branch"}, "the repository has no commit or branch no-such-branch"),
    ({"out": "relative/out"}, "out must be an absolute folder"),
    ({"repo": "/nowhere/bakery.bundle"}, "no repository at /nowhere/bakery.bundle"),
], ids=lambda x: str(x)[:30])
def test_prepare_fails_loud_and_leaves_nothing(tmp_path, bakery, change, error):
    values = {"repo": str(bakery.bundle), "commit": "main", "runs": 3, "parallel": 2,
              "out": str(tmp_path / "out"), "work_root": str(tmp_path / "work"), **change}
    code, answer, log = run_step("qa_flaky_prepare", tmp_path, **values)
    assert code == 1 and answer["status"] == "failed", log
    assert error in answer["error"]
    assert not list((tmp_path / "work").glob("qa-flaky.*")), "no copies left behind"
    assert not (tmp_path / "out" / "runs").exists(), "out is left as it was, so it can simply start again"


def test_prepare_will_not_write_over_a_report(tmp_path, bakery):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "report.json").write_text("{}")
    code, answer, _ = run_step("qa_flaky_prepare", tmp_path, repo=str(bakery.bundle), commit="main", runs=3,
                               parallel=2, out=str(tmp_path / "out"), work_root=str(tmp_path / "work"))
    assert code == 1 and "out already holds a report" in answer["error"]


# ---- keep and the tally step ----------------------------------------------------------------------


def test_keep_removes_only_a_copy_prepare_made(tmp_path):
    (tmp_path / "out" / "runs").mkdir(parents=True)
    elsewhere = tmp_path / "mine" / "run_0"
    elsewhere.mkdir(parents=True)
    code, answer, log = run_step("qa_flaky_keep", tmp_path, index="0", result='{"verdict": "pass"}',
                                 step_status="completed", step_error=None, tree=str(elsewhere),
                                 out=str(tmp_path / "out"))
    assert code == 0 and answer["removed"] is False and elsewhere.is_dir(), log
    assert (tmp_path / "out" / "runs" / "run_0" / "output.txt").read_text() == '{"verdict": "pass"}'


def test_keep_fails_without_a_runs_folder(tmp_path):
    code, answer, _ = run_step("qa_flaky_keep", tmp_path, index="0", result="", step_status="failed",
                               step_error="x", tree="", out=str(tmp_path / "nowhere"))
    assert code == 1 and "no runs folder" in answer["error"]


@pytest.mark.parametrize("error, said", [
    ("the repository has no commit or branch nope", "no report: the repository has no commit or branch nope"),
    (None, "no report: prepare did not finish"),
])
def test_no_report_when_prepare_failed(tmp_path, error, said):
    code, answer, _ = run_step("qa_flaky_tally", tmp_path, prepare_status="failed" if error else None,
                               prepare_error=error, out=str(tmp_path / "out"), runs=3, commit="abc",
                               repo="r", subject="s", parallel=1, work_root=None, history=False,
                               history_api=None, history_workflows=None)
    assert code == 1 and answer == {"status": "failed", "error": said}
    assert not (tmp_path / "out").exists()


# ---- reading task_test's answers ------------------------------------------------------------------


@pytest.mark.parametrize("line, kind, test_id, error", [
    ("FAILED tests/test_a.py::test_b - AssertionError: no", "test", "tests/test_a.py::test_b", "AssertionError: no"),
    ("FAILED tests/test_a.py::TestOven::test_heat - assert 1 == 2", "test",
     "tests/test_a.py::TestOven::test_heat", "assert 1 == 2"),
    ("FAILED tests/test_a.py::test_b[sugar - salt] - ValueError: x - y", "test",
     "tests/test_a.py::test_b[sugar - salt]", "ValueError: x - y"),
    ("FAILED tests/test_a.py::test_b", "test", "tests/test_a.py::test_b", "FAILED"),
    ("ERROR tests/test_a.py - ImportError: no", "file", "tests/test_a.py", "ImportError: no"),
    ("FAILED tests/test_a.py::test_b - boom (could not be checked on the base)", "test",
     "tests/test_a.py::test_b", "boom"),
    ("\u2716 the oven heats (1.2ms)", "test", "the oven heats", "\u2716 the oven heats (1.2ms)"),
    ("basket > total -- expected 12, got 8", "test", "basket > total", "expected 12, got 8"),
    ("exited 2: npm ERR! code ECONNRESET", "exit", None, "exited 2: npm ERR! code ECONNRESET"),
    ("did not finish in 2700 s (stopped)", "timeout", None, "did not finish in 2700 s (stopped)"),
    ("src/a.ts(3,5): error TS2322: Type 'x' is not assignable", "line",
     "src/a.ts(3,5): error TS2322: Type 'x' is not assignable", "src/a.ts(3,5): error TS2322: Type 'x' is not assignable"),
])
def test_each_failure_line_names_its_test(line, kind, test_id, error):
    assert tally.parse_item(line) == {"kind": kind, "id": test_id, "error": error}


def answer(preexisting=(), checks=(), total=None, **more) -> str:
    return "log line\n" + json.dumps({
        "verdict": "fail" if preexisting else "pass", "summary": "s",
        "failures": [], "failures_total": 0,
        "preexisting": [{"check": c, "failure": f} for c, f in preexisting][:20],
        "preexisting_total": len(preexisting) if total is None else total,
        "nonblocking": [], "checks": [{"check": c, "result": r} for c, r in checks], **more}) + "\n"


def write_rep(out: Path, i: int, output: str, tests_md: str | None = None) -> None:
    folder = out / "runs" / f"run_{i}"
    folder.mkdir(parents=True)
    (folder / "output.txt").write_text(output)
    (folder / "step.json").write_text('{"status": "completed", "error": null}')
    if tests_md is not None:
        (folder / "tests.md").write_text(tests_md)


def test_a_list_cut_short_is_read_whole_from_the_report_or_not_counted(tmp_path):
    out = tmp_path / "out"
    many = [("backend · Tests", f"FAILED tests/test_t.py::test_{k} - boom") for k in range(25)]
    md = ("# Tests: abc1234 (base abc1234)\n\n## Failures that are on abc1234 too (not this change's) (25)\n\n"
          + "".join(f"- {c} \u2014 {f}\n" for c, f in many))
    write_rep(out, 0, answer(many, [("backend · Tests", "failed")]), md)
    write_rep(out, 1, answer(many, [("backend · Tests", "failed")]), md.replace("(25)", "(26)"))
    write_rep(out, 2, answer(many, [("backend · Tests", "failed")]))
    reps = [tally.read_repetition(out / "runs" / f"run_{i}") for i in range(3)]
    assert len(reps[0]["checks"]["backend · Tests"]["items"]) == 25
    assert reps[1]["checks"]["backend · Tests"]["state"] == "cut short", "a short report is not trusted"
    assert reps[2]["checks"]["backend · Tests"]["state"] == "cut short"
    result = tally.tally(reps)
    assert len(result["tests"]) == 25 and all(t["completed"] == 1 for t in result["tests"])
    assert result["checks"][0]["cut_short"] == 2


def test_a_check_that_timed_out_or_never_ran_says_nothing_about_its_tests(tmp_path):
    out = tmp_path / "out"
    write_rep(out, 0, answer([("backend · Tests", "FAILED tests/test_t.py::test_a - boom")],
                             [("backend · Tests", "failed"), ("backend · Lint", "passed")]))
    write_rep(out, 1, answer([("backend · Tests", "did not finish in 2700 s (stopped)")],
                             [("backend · Tests", "timed out"), ("backend · Lint", "not run")]))
    write_rep(out, 2, answer([], [("backend · Tests", "passed"), ("backend · Lint", "passed")]))
    result = tally.tally([tally.read_repetition(out / "runs" / f"run_{i}") for i in range(3)])
    test = result["tests"][0]
    assert (test["class"], test["failures"], test["completed"]) == ("flaky", 1, 2)
    checks = {c["check"]: c for c in result["checks"]}
    assert checks["backend · Tests"]["class"] == "infrastructure flake"
    assert checks["backend · Tests"]["timed_out_in"] == [1]
    assert (checks["backend · Lint"]["class"], checks["backend · Lint"]["not_run"]) == ("stable", 1)


def test_a_failure_in_a_step_ci_lets_fail_is_marked(tmp_path):
    out = tmp_path / "out"
    soft = [{"check": "e2e · Smoke", "failure": "FAILED tests/test_e2e.py::test_smoke - timeout"}]
    write_rep(out, 0, answer([], [("e2e · Smoke", "failed")], nonblocking=soft))
    write_rep(out, 1, answer([], [("e2e · Smoke", "passed")]))
    result = tally.tally([tally.read_repetition(out / "runs" / f"run_{i}") for i in range(2)])
    assert result["tests"][0]["class"] == "flaky" and result["tests"][0]["nonblocking"] is True


def test_a_framed_message_is_named_by_its_error_line(tmp_path):
    out = tmp_path / "out"
    write_rep(out, 0, answer([("qa · Walk", "exited 1: \u255a\u2550\u2550\u2550\u255d")], [("qa · Walk", "failed")]))
    answer_json = json.loads((out / "runs" / "run_0" / "output.txt").read_text().splitlines()[-1])
    answer_json["checks"][0]["log"] = "/tmp/qa-flaky.x/run_0/.epd/tests/head-200-qa-Walk.log"
    (out / "runs" / "run_0" / "output.txt").write_text(json.dumps(answer_json) + "\n")
    (out / "runs" / "run_0" / "logs").mkdir()
    (out / "runs" / "run_0" / "logs" / "head-200-qa-Walk.log").write_text(
        "Traceback\n  File \"walk.py\", line 3, in go\nError: BrowserType.launch: Executable doesn't exist\n"
        "\u2554\u2550\u2550\u2557\n\u2551 Looks like Playwright was just installed \u2551\n\u255a\u2550\u2550\u255d\n")
    rep = tally.read_repetition(out / "runs" / "run_0")
    assert rep["checks"]["qa · Walk"]["said"] == "exited 1: Error: BrowserType.launch: Executable doesn't exist"


def test_an_answer_without_checks_is_no_answer(tmp_path):
    out = tmp_path / "out"
    write_rep(out, 0, json.dumps({"verdict": "skipped", "summary": "no worktree at /x", "checks": []}))
    rep = tally.read_repetition(out / "runs" / "run_0")
    assert rep["answered"] is False and "no worktree at /x" in rep["why"]


# ---- history: the live builds, read with GETs only ------------------------------------------------


def live_answer(failures=(), preexisting=()) -> str:
    return "starting\n" + json.dumps({"verdict": "fail", "summary": "s",
                                      "failures": [{"check": "backend · Tests", "failure": f} for f in failures],
                                      "preexisting": [{"check": "backend · Tests", "failure": f} for f in preexisting],
                                      "checks": [{"check": "backend · Tests", "result": "failed"}]}) + "\n"


class FakeRuns(BaseHTTPRequestHandler):
    """temper's runs API, as much of it as the history reads."""

    seen: list = []
    pages = {
        "/api/workflows?limit=500&offset=0": {"runs": [
            {"id": "live-1", "workflow_name": "epd_loop"}, {"id": "qa-1", "workflow_name": "epd_qa_case"},
            {"id": "live-2", "workflow_name": "epd_loop"}, {"id": "live-3", "workflow_name": "epd_loop"}],
            "total": 4},
        "/api/workflows/live-1/agents": {"agents": [{"id": "a1", "agent_name": "task_test"},
                                                    {"id": "a2", "agent_name": "task_code"}]},
        "/api/workflows/live-2/agents": {"agents": [{"id": "b1", "agent_name": "task_test"},
                                                    {"id": "b2", "agent_name": "task_test"}]},
        "/api/runs/live-1/agents/a1/log?max_bytes=4000000": {"rows": [{"entries": [
            {"stream": "stderr", "text": "noise\n"},
            {"stream": "stdout", "text": live_answer(
                failures=[f"FAILED {CRUST} - AssertionError: 62 s (could not be checked on the base)"])}]}]},
        "/api/runs/live-2/agents/b1/log?max_bytes=4000000": {"rows": [{"entries": [
            {"stream": "stdout", "text": live_answer(failures=[f"FAILED {CRUST} - AssertionError: 64 s"],
                                                     preexisting=[f"FAILED {OVEN} - assert 200 == 220"])}]}]},
    }

    def do_GET(self):  # noqa: N802 - http.server's name
        type(self).seen.append(("GET", self.path))
        page = self.pages.get(self.path)
        body = json.dumps(page).encode() if page is not None else b'{"detail": "not found"}'
        self.send_response(200 if page is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def runs_api():
    FakeRuns.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRuns)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_history_counts_how_often_the_live_build_was_sent_back(runs_api):
    wanted = [{"check": "backend · Tests", "id": CRUST}, {"check": "backend · Tests", "id": OVEN}]
    h = tally.history(runs_api, ["epd_loop"], wanted, 300)
    assert h["status"] == "read"
    counts = {t["id"]: t for t in h["tests"]}
    assert (counts[CRUST]["as_new"], counts[CRUST]["as_old"], counts[CRUST]["new_in_runs"]) == (2, 0, ["live-1", "live-2"])
    assert (counts[OVEN]["as_new"], counts[OVEN]["as_old"]) == (0, 1)
    assert (h["runs_read"], h["runs_unreadable"], h["test_steps_read"], h["test_steps_without_saved_answer"]) == (3, 1, 3, 1)
    assert {m for m, _ in FakeRuns.seen} == {"GET"}
    assert not any("qa-1" in p for _, p in FakeRuns.seen), "QA's own runs are not the live build"


def test_the_report_carries_the_history(tmp_path, runs_api):
    out = tmp_path / "out"
    write_rep(out, 0, answer([("backend · Tests", f"FAILED {CRUST} - boom")], [("backend · Tests", "failed")]))
    write_rep(out, 1, answer([], [("backend · Tests", "passed")]))
    tally.main(["--out", str(out), "--runs", "2", "--commit", "abc", "--history-api", runs_api])
    report = json.loads((out / "report.json").read_text())
    assert report["tests"][0]["live"] == {"as_new": 2, "as_old": 0, "new_in_runs": ["live-1", "live-2"]}
    assert "counted new (sent a build back)" in (out / "report.md").read_text()


def test_a_history_that_cannot_be_read_costs_the_report_nothing(tmp_path):
    out = tmp_path / "out"
    write_rep(out, 0, answer([("backend · Tests", f"FAILED {CRUST} - boom")], [("backend · Tests", "failed")]))
    write_rep(out, 1, answer([], [("backend · Tests", "passed")]))
    assert tally.main(["--out", str(out), "--runs", "2", "--commit", "abc", "--history-api", "http://127.0.0.1:9"]) == 0
    report = json.loads((out / "report.json").read_text())
    assert report["history"]["status"] == "unavailable" and report["tests"][0]["class"] == "flaky"
    assert "Not read:" in (out / "report.md").read_text()


# ---- the workflow ---------------------------------------------------------------------------------


def laid_out(**inputs) -> dict:
    """The workflow's steps as a run start lays them out: defaults filled, templates expanded."""
    wf = served(WORKFLOW)["workflow"]
    given = {"repo": "/w/r.bundle", "commit": "main", "out": "/w/out", **inputs}
    expanded = expand_templates(wf, fill_input_defaults(wf.get("inputs"), given))
    WorkflowConfig.from_dict(expanded)
    return expanded


def ancestors(nodes: dict, name: str) -> set:
    seen, todo = set(), list(nodes[name].get("depends_on") or [])
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo += nodes[n].get("depends_on") or []
    return seen


def test_the_repetitions_run_parallel_at_a_time():
    nodes = {n["name"]: n for n in laid_out(runs=5, parallel=2)["nodes"]}
    assert set(nodes) == {"prepare", "tally", *(f"run_{i}" for i in range(5)), *(f"keep_{i}" for i in range(5))}
    assert [nodes[f"run_{i}"]["depends_on"] for i in range(5)] == [
        ["prepare"], ["prepare"], ["keep_0"], ["keep_1"], ["keep_2"]]
    assert all(nodes[f"keep_{i}"]["depends_on"] == [f"run_{i}"] for i in range(5))
    assert nodes["tally"]["depends_on"] == ["prepare", *(f"keep_{i}" for i in range(5))]
    assert all(nodes[n].get("run_after_failure") for n in nodes if n != "prepare"), \
        "a repetition that fails is a result: the rest and the tally still run"


def test_by_default_twenty_repetitions_three_at_a_time():
    nodes = {n["name"]: n for n in laid_out()["nodes"]}
    assert sum(1 for n in nodes if n.startswith("run_")) == 20
    assert nodes["run_2"]["depends_on"] == ["prepare"] and nodes["run_3"]["depends_on"] == ["keep_0"]
    assert nodes["keep_19"]["input_map"]["index"] == "19"


def test_each_repetition_is_the_live_task_test_unchanged():
    wf = laid_out(runs=3, parallel=1)
    nodes = {n["name"]: n for n in wf["nodes"]}
    for i in range(3):
        assert nodes[f"run_{i}"]["agent"] == "task_test"
        assert nodes[f"run_{i}"]["input_map"] == {"workspace_path": f"prepare.structured.slot_{i}",
                                                  "base_branch": "prepare.structured.commit"}
    assert {n["agent"] for n in wf["nodes"]} == {"qa_flaky_prepare", "task_test", "qa_flaky_keep", "qa_flaky_tally"}
    assert "notify" not in wf, "it only reports: it messages nobody"


def test_every_step_reads_only_what_runs_before_it():
    wf = laid_out(runs=4, parallel=2)
    nodes = {n["name"]: n for n in wf["nodes"]}
    inputs = set(wf["inputs"])
    for name, node in nodes.items():
        assert (EPD / "agents" / f"{node['agent']}.yaml").is_file(), f"{name}: no agent {node['agent']}"
        sources = list((node.get("input_map") or {}).values())
        if node.get("condition"):
            sources.append(node["condition"]["source"])
        for src in sources:
            head, _, rest = src.partition(".")
            if not rest:
                assert src.isdigit(), f"{name}: {src} is neither a source nor a repetition's number"
                continue
            if head == "input":
                assert rest in inputs, f"{name} reads input {rest}, which the workflow does not take"
                continue
            assert head in ancestors(nodes, name), f"{name} reads {head}, which does not run before it"
            kind, _, field = rest.partition(".")
            if kind == "structured":
                field = re.sub(r"_\d+$", "_", field)
                text = (EPD / "agents" / f"{nodes[head]['agent']}.yaml").read_text()
                assert re.search(rf"\b{re.escape(field)}\b", text), \
                    f"{name} reads {src}, a field {nodes[head]['agent']} never prints"
            else:
                assert kind in ("output", "status", "error"), f"{name} reads {src}"
    printed = TALLY.read_text()
    for out, src in wf["outputs"].items():
        step, _, field = src.partition(".structured.")
        assert step in nodes, f"output {out} names no step"
        if step == "tally":
            assert f'"{field}"' in printed, f"output {out}: the tally never prints {field}"


def test_departments_names_the_report_and_its_parts():
    text = (ROOT / "docs" / "departments.md").read_text()
    for name in ("qa_flaky_report", "qa_flaky_prepare", "qa_flaky_keep", "qa_flaky_tally", "qa_flaky_tally.py"):
        assert name in text, f"docs/departments.md does not list {name}"
