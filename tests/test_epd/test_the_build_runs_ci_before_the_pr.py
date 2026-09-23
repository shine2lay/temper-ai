"""The build's test step: the repository's own CI checks, run on the candidate before a PR exists.

The reviewer used to run the suites itself. A model waiting on a ten-minute suite pays for its
context the whole time, and b006's reviewer spent its thirty minutes on one run and returned
nothing. The suites now run in a script (configs/epd/agents/task_test.yaml): the `run:` steps of
the workflows the repository runs on a pull request, on the implementer's commit, in a clean
worktree. A failure counts against the change only if the commit the branch was cut from does not
have it too, because no fix round on the branch can make the base branch's tests pass.

These tests run the shipped script through the real ScriptAgent against throwaway repositories
whose CI is a few lines of shell and a fake `pytest` module, so the whole path -- the Jinja, the
environment hop, git worktrees, the base re-run -- is exercised in a second or two.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.config.helpers import substitute_env_vars
from temper_ai.tools.base import ToolResult

ROOT = Path(__file__).resolve().parents[2]
TEST_STEP = ROOT / "configs" / "epd" / "agents" / "task_test.yaml"

# A stand-in for pytest, found by `python3 -m pytest` because the checkout is the working
# directory: it "fails" the node ids listed in failing.txt, narrowed to any files named on the
# command line, and prints them the way pytest's short summary does.
FAKE_PYTEST = '''\
import pathlib, sys
files = [a for a in sys.argv[1:] if not a.startswith("-")]
fails = [l.strip() for l in pathlib.Path("failing.txt").read_text().splitlines() if l.strip()]
if files:
    fails = [f for f in fails if f.split("::")[0] in files]
for f in fails:
    print(f"FAILED {f} - AssertionError: boom")
print(f"{len(fails)} failed" if fails else "all passed")
sys.exit(1 if fails else 0)
'''

CI = {
    "name": "ci",
    "on": {"pull_request": None, "push": {"branches": ["main"]}},
    "jobs": {
        "backend": {
            "runs-on": "ubuntu-latest",
            "env": {"MODE": "ci"},
            "steps": [
                {"uses": "actions/checkout@v4"},
                {"name": "Tests", "run": "python3 -m pytest -q"},
            ],
        },
    },
}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(repo.parent),
                               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return done.stdout.strip()


def write(repo: Path, files: dict) -> None:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            content = yaml.safe_dump(content, sort_keys=False)
        path.write_text(content)
        if name.startswith("bin/"):
            path.chmod(0o755)


def repo_with(tmp_path: Path, base: dict, change: dict | None = None) -> Path:
    """A repository whose `main` holds `base` and whose checked-out branch adds `change`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, {"pytest.py": FAKE_PYTEST, "tests/test_a.py": "", "failing.txt": "", **base})
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-qb", "task")
    if change:
        write(repo, change)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "change")
    return repo


def served_config() -> dict:
    """The agent config as the server hands it out: ConfigStore.get runs every string
    through the loader's env substitution, which rewrites dollar-brace syntax."""
    return substitute_env_vars(yaml.safe_load(TEST_STEP.read_text()))["agent"]


def run_step(repo: Path | str, base_branch="main", secret_env=None) -> dict:
    """The test step's JSON for this worktree: the real agent, the real script, really run."""
    config = served_config()
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", "test", "task_test"
    ctx.workspace_path = str(repo)

    def execute(_tool, args, **_kw):
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(), **(secret_env or {}), **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env,
                              timeout=120)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    result = ScriptAgent(config=config).run(
        {"workspace_path": str(repo), "base_branch": base_branch}, ctx)
    assert result.status.value == "completed", result.error
    return result.structured_output


def failures(out: dict, key="failures") -> list[str]:
    return [f"{x['check']}: {x['failure']}" for x in out[key]]


def prints(path: str) -> str:
    """A check whose output is the file at `path`, failing when the file has anything in it.

    The base re-run runs the same command on the base commit, so a check that failed
    whatever the code said would be the base's failure too, never the change's. Steps run
    under `bash -e`, as on GitHub, so a missing file must not end the step early."""
    return f"cat {path} 2>/dev/null || true; test ! -s {path}"


class TestWhatTheChangeBrokeSendsItBack:

    def test_a_clean_change_passes(self, tmp_path):
        out = run_step(repo_with(tmp_path, {".github/workflows/ci.yml": CI}, {"tests/test_a.py": "# more"}))
        assert out["verdict"] == "pass", out["summary"]
        assert out["failures"] == []
        assert [c["result"] for c in out["checks"]] == ["passed"]
        assert out["summary"].startswith("CI's checks pass on ")

    def test_a_test_the_change_breaks_fails_it(self, tmp_path):
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": CI},
                         {"failing.txt": "tests/test_a.py::test_changed\n"})
        out = run_step(repo)
        assert out["verdict"] == "fail"
        assert failures(out) == [
            "backend · Tests: FAILED tests/test_a.py::test_changed - AssertionError: boom"]
        assert "1 failure(s) this change introduced" in out["summary"]

    def test_a_failure_the_base_has_too_is_not_the_changes(self, tmp_path):
        """No fix round on this branch can make master's tests pass."""
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": CI,
                                    "failing.txt": "tests/test_a.py::test_legacy\n"},
                         {"tests/test_a.py": "# touched"})
        out = run_step(repo)
        assert out["verdict"] == "pass", out["summary"]
        assert failures(out, "preexisting") == [
            "backend · Tests: FAILED tests/test_a.py::test_legacy - AssertionError: boom"]
        assert "also fail on main at " in out["summary"]

    def test_new_and_old_failures_are_told_apart(self, tmp_path):
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": CI,
                                    "failing.txt": "tests/test_a.py::test_legacy\n"},
                         {"failing.txt": "tests/test_a.py::test_legacy\ntests/test_a.py::test_changed\n"})
        out = run_step(repo)
        assert out["verdict"] == "fail"
        assert [x["failure"].split(" - ")[0] for x in out["failures"]] == ["FAILED tests/test_a.py::test_changed"]
        assert [x["failure"].split(" - ")[0] for x in out["preexisting"]] == ["FAILED tests/test_a.py::test_legacy"]

    def test_the_base_rerun_is_narrowed_to_the_failing_files(self, tmp_path):
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": CI, "tests/test_b.py": ""},
                         {"failing.txt": "tests/test_b.py::test_x\n"})
        run_step(repo)
        base_logs = sorted((repo / ".epd" / "tests").glob("base-*.log"))
        assert len(base_logs) == 1
        assert base_logs[0].read_text().splitlines()[0] == "$ python3 -m pytest -q tests/test_b.py"

    def test_a_failure_in_a_file_the_base_lacks_is_the_changes_without_a_rerun(self, tmp_path):
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": CI},
                         {"tests/test_new.py": "", "failing.txt": "tests/test_new.py::test_feature\n"})
        out = run_step(repo)
        assert out["verdict"] == "fail"
        assert not list((repo / ".epd" / "tests").glob("base-*.log"))

    def test_the_report_holds_the_output_behind_each_failure(self, tmp_path):
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": CI},
                         {"failing.txt": "tests/test_a.py::test_changed\n"})
        out = run_step(repo)
        report = Path(out["report"]).read_text()
        assert report.startswith("# Tests: ")
        assert "## Failures this change introduced (1)" in report
        assert "FAILED tests/test_a.py::test_changed - AssertionError: boom" in report
        assert "Command (in `.`): `python3 -m pytest -q`" in report

    def test_no_worktree_of_its_own_is_left_behind(self, tmp_path):
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": CI},
                         {"failing.txt": "tests/test_a.py::test_changed\n"})
        run_step(repo)
        assert git(repo, "worktree", "list").count("\n") == 0  # the repository's own, only


class TestItRunsWhatCiRunsTheWayCiRunsIt:

    def test_jobs_run_side_by_side_and_every_check_is_reported(self, tmp_path):
        ci = {"on": ["pull_request"], "jobs": {
            "lint": {"steps": [{"name": "Lint", "run": prints("lint.txt")}]},
            "types": {"defaults": {"run": {"working-directory": "web"}},
                      "steps": [{"name": "tsc", "run": prints("tsc.txt")}]},
        }}
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": ci, "web/tsc.txt": ""}, {
            "lint.txt": "x.py:3:1: E501 Line too long (120 > 100)\n",
            "web/tsc.txt": "src/a.ts(9,19): error TS2580: Cannot find name 'process'.\n"})
        out = run_step(repo)
        assert out["verdict"] == "fail"
        assert sorted(failures(out)) == [
            "lint · Lint: x.py:3:1: E501 Line too long (120 > 100)",
            "types · tsc: src/a.ts(9,19): error TS2580: Cannot find name 'process'.",
        ]

    def test_a_failing_install_stops_its_job_and_nothing_else(self, tmp_path):
        ci = {"on": {"pull_request": {}}, "jobs": {"web": {"steps": [
            {"name": "Install", "run": "npm ci", "env": {"PATH": "bin:/usr/bin:/bin"}},
            {"name": "Tests", "run": "echo never"},
        ]}}}
        npm_ok = "#!/bin/sh\nexit 0\n"
        npm_broken = "#!/bin/sh\necho 'npm ERR! lockfile out of date'\nexit 1\n"
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": ci, "bin/npm": npm_ok}, {"bin/npm": npm_broken})
        out = run_step(repo)
        assert out["verdict"] == "fail"
        assert failures(out) == ["web · Install: exited 1: npm ERR! lockfile out of date"]
        assert [(c["check"], c["result"]) for c in out["checks"]] == [
            ("web · Install", "failed"), ("web · Tests", "not run")]

    def test_a_failing_check_does_not_stop_the_ones_after_it(self, tmp_path):
        """CI stops a job at its first failure; the implementer is better served by all of them."""
        ci = {"on": ["pull_request"], "jobs": {"web": {"steps": [
            {"name": "One", "run": prints("one.txt")}, {"name": "Two", "run": prints("two.txt")}]}}}
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": ci}, {"one.txt": "bad\n", "two.txt": "bad\n"})
        out = run_step(repo)
        assert [c["result"] for c in out["checks"]] == ["failed", "failed"]
        assert out["failures_total"] == 2

    def test_a_check_that_fails_on_the_base_too_is_the_bases(self, tmp_path):
        ci = {"on": ["pull_request"], "jobs": {"web": {"steps": [{"name": "Always", "run": "exit 1"}]}}}
        out = run_step(repo_with(tmp_path, {".github/workflows/ci.yml": ci}, {"x.txt": ""}))
        assert out["verdict"] == "pass"
        assert failures(out, "preexisting") == ["web · Always: exited 1: (no output)"]

    def test_the_workflows_env_reaches_the_step_and_the_servers_does_not(self, tmp_path):
        ci = {"on": ["pull_request"], "env": {"FROM_WORKFLOW": "1"}, "jobs": {"env": {
            "env": {"FROZEN": True}, "steps": [{"name": "Env", "run": (
                'test "$FROM_WORKFLOW$FROZEN$CI" = 1truetrue || { echo "wrong: $FROM_WORKFLOW$FROZEN$CI"; exit 1; }; '
                'test -z "${ANTHROPIC_API_KEY:-}" || { echo leaked; exit 1; }')}]}}}
        out = run_step(repo_with(tmp_path, {}, {".github/workflows/ci.yml": ci}),
                       secret_env={"ANTHROPIC_API_KEY": "sk-not-for-the-repo"})
        assert out["verdict"] == "pass", out["summary"]

    def test_what_it_cannot_evaluate_is_named_not_guessed(self, tmp_path):
        expr = "$" + "{{ matrix.python }}"
        ci = {"on": ["pull_request"], "jobs": {
            "a": {"steps": [{"name": "Expr", "run": f"echo {expr}"},
                            {"name": "Cond", "if": "github.event_name == 'push'", "run": "exit 1"},
                            {"name": "Plain", "run": "true"}]},
            "db": {"services": {"postgres": {"image": "postgres"}}, "steps": [{"run": "true"}]},
        }}
        out = run_step(repo_with(tmp_path, {}, {".github/workflows/ci.yml": ci}))
        assert out["verdict"] == "pass"
        assert [c["check"] for c in out["checks"]] == ["a · Plain"]
        assert out["not_run"] == [
            "a · Expr: uses a GitHub expression",
            "a · Cond: the step has an `if:` this script cannot evaluate",
            "db: needs service containers (postgres)",
        ]
        assert "3 step(s) not run here" in out["summary"]

    def test_only_workflows_that_run_on_a_pull_request_count(self, tmp_path):
        deploy = {"on": {"push": {"branches": ["main"]}}, "jobs": {"ship": {"steps": [{"run": "exit 1"}]}}}
        out = run_step(repo_with(tmp_path, {}, {".github/workflows/deploy.yml": deploy}))
        assert out["verdict"] == "skipped"
        assert "no workflow in .github/workflows runs on pull_request" in out["summary"]

    def test_a_step_that_hangs_is_stopped_and_counted(self, tmp_path):
        ci = {"on": ["pull_request"], "jobs": {"slow": {"steps": [
            {"name": "Hang", "run": "sleep 30", "timeout-minutes": 0.02}]}}}
        out = run_step(repo_with(tmp_path, {}, {".github/workflows/ci.yml": ci}))
        assert out["verdict"] == "fail"
        assert failures(out) == ["slow · Hang: did not finish in 1 s (stopped)"]
        assert out["checks"][0]["result"] == "timed out"


class TestReadingFailures:
    """Each failure is named the way a person would look for it; line numbers stay out of the
    comparison with the base, because they move between two commits."""

    def test_node_test_tap_names_the_failing_leaf_by_its_chain(self, tmp_path):
        tap = "\n".join([
            "TAP version 13",
            "# Subtest: /tmp/node_modules/.rollcall-fe-tests-x/ladder.test.js",
            "    # Subtest: the ladder",
            "        # Subtest: explains a refusal",
            "        not ok 1 - explains a refusal",
            "          ---",
            "          duration_ms: 1.2",
            "          error: |-",
            "            Expected values to be strictly equal:",
            "          ...",
            "        # Subtest: passes",
            "        ok 2 - passes",
            "        1..2",
            "    not ok 1 - the ladder",
            "not ok 1 - /tmp/node_modules/.rollcall-fe-tests-x/ladder.test.js",
        ])
        ci = {"on": ["pull_request"], "jobs": {"fe": {"steps": [{"name": "Tests", "run": prints("tap.txt")}]}}}
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": ci}, {"tap.txt": tap})
        out = run_step(repo)
        assert failures(out) == [
            "fe · Tests: ladder.test.js > the ladder > explains a refusal -- Expected values to be strictly equal:"]

    def test_ruffs_full_format_is_read(self, tmp_path):
        ruff = "F401 [*] `os` imported but unused\n --> backend/x.py:1:8\n  |\nFound 1 error.\n"
        ci = {"on": ["pull_request"], "jobs": {"lint": {"steps": [{"name": "ruff", "run": prints("ruff.txt")}]}}}
        out = run_step(repo_with(tmp_path, {".github/workflows/ci.yml": ci}, {"ruff.txt": ruff}))
        assert failures(out) == ["lint · ruff: backend/x.py:1:8: F401 `os` imported but unused"]


class TestItFailsOpenAndSaysSo:
    """A harness fault must not be what sends a build back or throws one away."""

    def test_no_worktree(self, tmp_path):
        out = run_step(tmp_path / "missing")
        assert out["verdict"] == "skipped"
        assert out["summary"].startswith("the test step could not run: no worktree at ")

    def test_not_a_git_repository(self, tmp_path):
        out = run_step(tmp_path)
        assert out["verdict"] == "skipped"
        assert out["summary"].startswith("the test step could not run: RuntimeError: git rev-parse HEAD")

    def test_an_unknown_base_branch_counts_every_failure_as_the_changes(self, tmp_path):
        repo = repo_with(tmp_path, {".github/workflows/ci.yml": CI},
                         {"failing.txt": "tests/test_a.py::test_changed\n"})
        out = run_step(repo, base_branch="nope")
        assert out["verdict"] == "fail"
        assert "no base commit to compare with" in out["summary"]


class TestTheScriptRunsOnTemperOwnPython:

    def test_it_asks_for_the_interpreter_the_script_agent_names(self):
        script = served_config()["script_template"]
        assert script.startswith('PY=python3\n[ -n "$TEMPER_PYTHON" ] && PY="$TEMPER_PYTHON"\n"$PY" - <<\'PYEOF\'')

    def test_the_loader_leaves_the_script_as_written(self):
        raw = yaml.safe_load(TEST_STEP.read_text())["agent"]["script_template"]
        assert served_config()["script_template"] == raw

    def test_the_script_agent_names_it(self):
        ctx = MagicMock()
        ctx.run_id, ctx.node_path, ctx.agent_name, ctx.workspace_path = "t", "n", "a", "/tmp"
        ctx.tool_executor.execute.return_value = ToolResult(success=True, result='{"ok": 1}', error="")
        ScriptAgent(config={"name": "a", "type": "script", "script_template": "echo hi"}).run({}, ctx)
        params = ctx.tool_executor.execute.call_args.args[1]
        assert params["env"]["TEMPER_PYTHON"] == sys.executable
        assert os.access(params["env"]["TEMPER_PYTHON"], os.X_OK)
