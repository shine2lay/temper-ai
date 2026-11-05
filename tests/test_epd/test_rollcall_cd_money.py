"""rollcall_cd_money (configs/epd/bin/rollcall_cd_money.py): `critical` CLI subcommand and shared CI log/money
classification used by `wt deploy`'s `ci.critical_check` and configs/epd/bin/rollcall_cd_verdict.py.

Checks:
  1. `critical` returns `"yes"`, `"no"`, and `"unknown"` on fixed job/log fixtures:
     - backend money test failure (direct, 1-hop helper, `engine/confirm/**`, `engine/ladder/**`)
     - qa walk money failure (`positions_journey`, `trade_hub_journey` by command and by step name)
     - non-money failure (plain backend test, non-money qa walk, frontend failure)
     - job not started / log unreadable / missing list / gh error -> `"unknown"`
  2. Replay against tests/test_epd/rollcall_cd_verdict_recorded.json and a 10-run recorded/replay sequence matches
     configs/epd/bin/rollcall_cd_verdict.py's `failures_of` + `money_of` classification run for run.
  3. CLI `rollcall_cd_money.py critical --help`, `rollcall_cd_money.py critical --repo ... --run ... --head ...
     --list ...`, and existing `rollcall_cd_money.py REPO HEAD [TEST_ID ...]` hand mode work end to end.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "epd" / "bin"
MONEY_SCRIPT = ROOT / "configs/epd/bin/rollcall_cd_money.py"
VERDICT_SCRIPT = ROOT / "configs/epd/bin/rollcall_cd_verdict.py"
RECORDED_PATH = ROOT / "tests/test_epd/rollcall_cd_verdict_recorded.json"
RECORDED = json.loads(RECORDED_PATH.read_text())
GIT = [
    "git",
    "-c", "user.name=t",
    "-c", "user.email=t@example.com",
    "-c", "init.defaultBranch=master",
    "-c", "commit.gpgsign=false",
]


def _load_money():
    spec = importlib.util.spec_from_file_location("rollcall_cd_money", MONEY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_verdict():
    spec = importlib.util.spec_from_file_location("rollcall_cd_verdict", VERDICT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


M = _load_money()
V = _load_verdict()

UPDATED_MONEY_TOML = """version = 1

[backend]
modules = [
  "backend/rollcall/adapters/orders*",
  "backend/rollcall/adapters/orders_entry/**",
  "backend/rollcall/api/routes/orders/**",
  "backend/rollcall/engine/margin*",
  "backend/rollcall/engine/entry/**",
  "backend/rollcall/engine/confirm/**",
  "backend/rollcall/engine/ladder/**",
  "backend/rollcall/engine/order_end.py",
  "backend/rollcall/engine/working.py",
  "backend/rollcall/config/rolls.py",
]

[qa]
walks = [
  "entry_journey",
  "ticket_journey",
  "trade_hub_journey",
  "unfinished_journey",
  "positions_journey",
  "today_journey",
]
"""


class StandInGraph:
    """Stand-in for RollCall's scripts/backend_import_graph.py; parses `import <mod>` lines."""

    built_with: dict = {}

    @staticmethod
    def module_name(path: str) -> str | None:
        if not path.startswith("backend/") or not path.endswith(".py"):
            return None
        return path[len("backend/"):-3].replace("/", ".").removesuffix(".__init__")

    @classmethod
    def build_graph(cls, sources: dict[str, str], bounds: dict[str, tuple[str, ...]]):
        cls.built_with = dict(bounds)
        modules = {cls.module_name(p): p for p in sources}
        edges = {
            cls.module_name(p): set(re.findall(r"^import (\S+)$", text, re.MULTILINE))
            for p, text in sources.items()
        }
        return type("Graph", (), {"modules": modules, "edges": edges})()


class StandInSelect:
    class SelectionError(Exception):
        pass

    files_at: dict[str, str] = {}

    class Git:
        def __init__(self, repo: Path):
            self.repo = repo

        def files(self, head: str, prefix: str = "") -> set[str]:
            if head == "bad-sha":
                raise StandInSelect.SelectionError("unknown revision bad-sha")
            return {p for p in StandInSelect.files_at if p.startswith(prefix)}

        def read(self, head: str, paths):
            return {p: StandInSelect.files_at[p] for p in paths}

    @staticmethod
    def glob_to_regex(pattern: str) -> re.Pattern[str]:
        out = re.escape(pattern).replace(r"\*\*", "\0").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        return re.compile(out.replace("\0", ".*"))


@pytest.fixture
def standin_check() -> object:
    StandInSelect.files_at = {
        M.LIST_PATH: UPDATED_MONEY_TOML,
        "backend/rollcall/adapters/orders_alpaca.py": "",
        "backend/rollcall/adapters/orders_entry/submit.py": "",
        "backend/rollcall/api/routes/orders/roll_ticket.py": "",
        "backend/rollcall/engine/margin_rules.py": "",
        "backend/rollcall/engine/entry/preview.py": "",
        "backend/rollcall/engine/confirm/gate.py": "",
        "backend/rollcall/engine/ladder/rung.py": "",
        "backend/rollcall/engine/order_end.py": "",
        "backend/rollcall/engine/working.py": "",
        "backend/rollcall/config/rolls.py": "",
        "backend/rollcall/engine/seed_clone.py": "",
        "backend/tests/conftest.py": "import rollcall.adapters.orders_alpaca\n",
        "backend/tests/entry_helper.py": "import rollcall.engine.entry.preview\n",
        "backend/tests/test_entry.py": "import tests.entry_helper\n",
        "backend/tests/test_confirm_gate.py": "import rollcall.engine.confirm.gate\n",
        "backend/tests/test_ladder_rung.py": "import rollcall.engine.ladder.rung\n",
        "backend/tests/test_dev_seed_clone.py": "import tests.conftest\nimport rollcall.engine.seed_clone\n",
        "backend/tests/test_select_tests.py": "import rollcall.engine.seed_clone\n",
        ".github/workflows/ci.yml": (
            "jobs:\n"
            "  qa:\n"
            "    steps:\n"
            "      - name: The Positions tab's happy path\n"
            "      - name: Trade hub journey walk\n"
        ),
        "qa/entry_journey.py": "",
        "qa/ticket_journey.py": "",
        "qa/trade_hub_journey.py": "",
        "qa/unfinished_journey.py": "",
        "qa/positions_journey.py": "",
        "qa/today_journey.py": "",
        "qa/ideas_journey.py": "",
    }
    selector = M.RollcallSelector(StandInGraph, StandInSelect)
    return M.MoneyCheck(Path("/nowhere"), selector)


def _backend_run(tests: list[str], command: str = "uv run pytest -q -p no:cacheprovider") -> tuple[list[dict], str]:
    jobs = [{
        "name": "backend",
        "status": "completed",
        "conclusion": "failure",
        "steps": [
            {"name": "Set up job", "conclusion": "success"},
            {"name": "Tests (pytest)", "conclusion": "failure"},
        ],
    }]
    prefix = "backend\tTests (pytest)\t2026-11-05T09:55:24.1276511Z "
    lines = [prefix + f"##[group]Run {command}"]
    lines += [f"{prefix}FAILED {tid} - AssertionError" for tid in tests]
    lines.append(prefix + "##[error]Process completed with exit code 1.")
    return jobs, "\n".join(lines) + "\n"


def _qa_run(step_name: str, command: str, *, stopped: bool = False) -> tuple[list[dict], str]:
    conclusion = "cancelled" if stopped else "failure"
    jobs = [{
        "name": "qa",
        "status": "completed",
        "conclusion": conclusion,
        "steps": [
            {"name": "Set up job", "conclusion": "success"},
            {"name": step_name, "conclusion": conclusion},
        ],
    }]
    prefix = f"qa\t{step_name}\t2026-11-05T18:26:11.9260733Z "
    log = ""
    if command:
        log = prefix + f"##[group]Run {command}\n" + prefix + "##[error]Process completed with exit code 1.\n"
    return jobs, log


def _frontend_run(step_name: str = "Typecheck (tsc)") -> tuple[list[dict], str]:
    jobs = [{
        "name": "frontend",
        "status": "completed",
        "conclusion": "failure",
        "steps": [
            {"name": "Set up job", "conclusion": "success"},
            {"name": step_name, "conclusion": "failure"},
        ],
    }]
    prefix = f"frontend\t{step_name}\t2026-11-05T18:20:00.0000000Z "
    log = prefix + "##[group]Run npm run typecheck\n" + prefix + "##[error]Process completed with exit code 1.\n"
    return jobs, log


# ---------------------------------------------------------------- updated money-tests.toml globs and walks


def test_updated_confirm_and_ladder_globs_and_trade_hub_journey_are_money(standin_check):
    listed = standin_check.read_list("head")
    assert "backend/rollcall/engine/confirm/**" in listed.modules
    assert "backend/rollcall/engine/ladder/**" in listed.modules
    assert "trade_hub_journey" in listed.walks
    assert standin_check.unmatched("head", listed) == []

    answer = standin_check.backend(
        "head",
        listed,
        [
            "backend/tests/test_confirm_gate.py::test_confirm_requires_arm",
            "backend/tests/test_ladder_rung.py::test_ladder_rung_step",
            "backend/tests/test_dev_seed_clone.py::test_seed_clone_plain",
        ],
    )
    assert answer.money == {
        "backend/tests/test_confirm_gate.py::test_confirm_requires_arm": ["rollcall.engine.confirm.gate"],
        "backend/tests/test_ladder_rung.py::test_ladder_rung_step": ["rollcall.engine.ladder.rung"],
    }
    assert answer.plain == ["backend/tests/test_dev_seed_clone.py::test_seed_clone_plain"]
    assert answer.unknown == {}

    assert standin_check.walk(listed, "Any step", "uv run python qa/trade_hub_journey.py") == "trade_hub_journey"
    assert standin_check.walk(listed, "trade_hub_journey smoke", "uv run python qa/other.py") == "trade_hub_journey"
    assert standin_check.walk(listed, "Ideas tab", "uv run python qa/ideas_journey.py") is None


# ---------------------------------------------------------------- critical_of: yes, no, unknown


def test_critical_returns_yes_for_backend_and_qa_money_failures(standin_check):
    jobs, log = _backend_run(["backend/tests/test_confirm_gate.py::test_confirm_requires_arm"])
    res = M.critical_of("/nowhere", 101, "head", check=standin_check, jobs=jobs, log_text=log)
    assert res["critical"] == "yes"
    assert res["tests"] == [
        "backend/tests/test_confirm_gate.py::test_confirm_requires_arm (imports rollcall.engine.confirm.gate)"
    ]
    assert "rollcall.engine.confirm.gate" in str(res["why"])

    jobs_l, log_l = _backend_run(["backend/tests/test_ladder_rung.py::test_ladder_rung_step"])
    res_l = M.critical_of("/nowhere", 102, "head", check=standin_check, jobs=jobs_l, log_text=log_l)
    assert res_l["critical"] == "yes"
    assert "rollcall.engine.ladder.rung" in str(res_l["why"])

    jobs_q, log_q = _qa_run("The Trade Hub journey", "uv run python qa/trade_hub_journey.py")
    res_q = M.critical_of("/nowhere", 103, "head", check=standin_check, jobs=jobs_q, log_text=log_q)
    assert res_q == {
        "critical": "yes",
        "tests": ["qa walk trade_hub_journey (The Trade Hub journey)"],
        "why": "qa walk trade_hub_journey (The Trade Hub journey)",
    }


def test_critical_returns_no_for_non_money_backend_qa_and_frontend_failures(standin_check):
    jobs, log = _backend_run(["backend/tests/test_dev_seed_clone.py::test_seed_clone_plain"])
    res = M.critical_of("/nowhere", 201, "head", check=standin_check, jobs=jobs, log_text=log)
    assert res == {
        "critical": "no",
        "tests": [],
        "why": "1 failing tests, none on the money list",
    }

    jobs_q, log_q = _qa_run("The Ideas tab's happy path", "uv run python qa/ideas_journey.py")
    res_q = M.critical_of("/nowhere", 202, "head", check=standin_check, jobs=jobs_q, log_text=log_q)
    assert res_q == {
        "critical": "no",
        "tests": [],
        "why": "no money test failed",
    }

    jobs_f, log_f = _frontend_run()
    res_f = M.critical_of("/nowhere", 203, "head", check=standin_check, jobs=jobs_f, log_text=log_f)
    assert res_f == {
        "critical": "no",
        "tests": [],
        "why": "no money test failed",
    }


def test_critical_returns_unknown_when_job_not_started_or_log_unreadable(standin_check):
    # 1. All jobs failed before any step ran (recorded 36763096407)
    res_no_step = M.critical_of(
        "/nowhere",
        36763096407,
        "head",
        check=standin_check,
        jobs=RECORDED["jobs"]["36763096407"],
        log_text="",
    )
    assert res_no_step["critical"] == "unknown"
    assert "no FAILED or ERROR test line" in str(res_no_step["why"])

    # 2. Only a non-backend/qa job failed before any step ran
    res_select_lost = M.critical_of(
        "/nowhere",
        302,
        "head",
        check=standin_check,
        jobs=[{"name": "select", "status": "completed", "conclusion": "failure", "steps": []}],
        log_text="",
    )
    assert res_select_lost["critical"] == "unknown"
    assert "no step ran" in str(res_select_lost["why"])

    # 3. Backend pytest failed without a parseable FAILED/ERROR line
    jobs_crash = [{
        "name": "backend",
        "status": "completed",
        "conclusion": "failure",
        "steps": [
            {"name": "Set up job", "conclusion": "success"},
            {"name": "Tests (pytest)", "conclusion": "failure"},
        ],
    }]
    log_crash = (
        "backend\tTests (pytest)\t2026-11-05T09:55:24.1276511Z ##[group]Run uv run pytest -q\n"
        "backend\tTests (pytest)\t2026-11-05T09:55:24.5647522Z ##[error]Process completed with exit code 137.\n"
    )
    res_crash = M.critical_of("/nowhere", 303, "head", check=standin_check, jobs=jobs_crash, log_text=log_crash)
    assert res_crash["critical"] == "unknown"
    assert "no FAILED or ERROR test line" in str(res_crash["why"])

    # 4. QA walk was cancelled/stopped mid-step
    jobs_stopped, log_stopped = _qa_run("Trade hub journey", "uv run python qa/trade_hub_journey.py", stopped=True)
    res_stopped = M.critical_of("/nowhere", 304, "head", check=standin_check, jobs=jobs_stopped, log_text=log_stopped)
    assert res_stopped["critical"] == "unknown"
    assert "stopped before the walks finished" in str(res_stopped["why"])

    # 5. Unknown test module not present in backend graph at head
    jobs_gone, log_gone = _backend_run(["backend/tests/test_removed_file.py::test_gone"])
    res_gone = M.critical_of("/nowhere", 305, "head", check=standin_check, jobs=jobs_gone, log_text=log_gone)
    assert res_gone["critical"] == "unknown"
    assert "is not a backend module" in str(res_gone["why"])

    # 6. Missing money-tests.toml at head
    res_missing_list = M.critical_of(
        "/nowhere",
        306,
        "head",
        list_path="scripts/missing-money.toml",
        check=standin_check,
        jobs=jobs_crash,
        log_text=log_crash,
    )
    assert res_missing_list["critical"] == "unknown"
    assert "no scripts/missing-money.toml" in str(res_missing_list["why"])

    # 7. gh failure returns unknown without raising
    def broken_runner(args):
        return subprocess.CompletedProcess(args, 1, "", "HTTP 502 Bad Gateway\n")

    res_gh_err = M.critical_of("/nowhere", 307, "head", check=standin_check, runner=broken_runner)
    assert res_gh_err["critical"] == "unknown"
    assert "HTTP 502" in str(res_gh_err["why"])


# ---------------------------------------------------------------- replay against recorded fixture & 10-run suite


def test_replay_against_recorded_fixture_and_ten_runs_matches_verdict_run_for_run(standin_check):
    # All 4 recorded runs from tests/test_epd/rollcall_cd_verdict_recorded.json plus 6 additional
    # runs covering the 10-run replay window from #98 (frontend red, plain backend reds, trade_hub_journey,
    # confirm/ladder money red, stopped qa walk).
    ten_runs: list[tuple[int, list[dict], str, str]] = [
        (36080431059, RECORDED["jobs"]["36080431059"], RECORDED["logs"]["36080431059"], "yes"),
        (42004004262, RECORDED["jobs"]["42004004262"], RECORDED["logs"]["42004004262"], "no"),
        (42081259790, RECORDED["jobs"]["42081259790"], RECORDED["logs"]["42081259790"], "yes"),
        (36763096407, RECORDED["jobs"]["36763096407"], RECORDED["logs"].get("36763096407", ""), "unknown"),
        (42066926452, *_frontend_run("Typecheck (tsc)"), "no"),
        (42068974083, *_frontend_run("Unit tests (vitest)"), "no"),
        (42074534942, *_backend_run(["backend/tests/test_select_tests.py::test_selector"]), "no"),
        (42077235740, *_qa_run("The Trade Hub journey", "uv run python qa/trade_hub_journey.py"), "yes"),
        (42081133034, *_backend_run(["backend/tests/test_confirm_gate.py::test_confirm_requires_arm"]), "yes"),
        (42087717050, *_qa_run("The Positions tab's happy path", "uv run python qa/positions_journey.py", stopped=True), "unknown"),
    ]
    assert len(ten_runs) == 10
    assert {run_id for run_id, _, _, _ in ten_runs[:4]} == {int(k) for k in RECORDED["jobs"]}

    for run_id, jobs, log_text, expected_state in ten_runs:
        verdict_failures = V.failures_of(jobs, log_text)
        verdict_money = V.money_of(verdict_failures, "head", standin_check, None)

        money_failures = M.failures_of(jobs, log_text)
        money_direct = M.money_of(money_failures, "head", standin_check, None)
        assert money_direct.state == verdict_money.state == expected_state
        assert money_direct.why == verdict_money.why
        assert money_direct.ids == verdict_money.ids

        def fake_runner(args, _jobs=jobs, _log=log_text):
            if "--json" in args and "jobs" in args:
                return subprocess.CompletedProcess(args, 0, json.dumps({"jobs": _jobs}), "")
            if "--log-failed" in args:
                if not _log:
                    return subprocess.CompletedProcess(args, 1, "", "log not found\n")
                return subprocess.CompletedProcess(args, 0, _log, "")
            raise AssertionError(f"unexpected command: {args}")

        # Verify via critical_of and via _critical_main JSON stdout line
        res = M.critical_of("/nowhere", run_id, "head", check=standin_check, runner=fake_runner)
        assert res == {
            "critical": verdict_money.state,
            "tests": verdict_money.ids,
            "why": verdict_money.why,
        }


# ---------------------------------------------------------------- CLI subprocess & real git repo check


def _make_mini_rollcall_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "rollcall"
    repo.mkdir()
    subprocess.run([*GIT, "-C", str(repo), "init", "-q"], check=True)
    files = {
        "scripts/money-tests.toml": UPDATED_MONEY_TOML,
        "scripts/backend_import_graph.py": (
            "import re\n"
            "def module_name(path):\n"
            "    if not path.startswith('backend/') or not path.endswith('.py'):\n"
            "        return None\n"
            "    return path[len('backend/'):-3].replace('/', '.').removesuffix('.__init__')\n"
            "def build_graph(sources, bounds=None):\n"
            "    modules = {module_name(p): p for p in sources}\n"
            "    edges = {module_name(p): set(re.findall(r'^import (\\S+)$', t, re.M)) for p, t in sources.items()}\n"
            "    return type('Graph', (), {'modules': modules, 'edges': edges})()\n"
        ),
        "scripts/select_tests.py": (
            "import re, subprocess\n"
            "class SelectionError(Exception):\n"
            "    pass\n"
            "class Git:\n"
            "    def __init__(self, repo):\n"
            "        self.repo = repo\n"
            "    def files(self, head, prefix=''):\n"
            "        cmd = ['git', '-C', str(self.repo), 'ls-tree', '-r', '--name-only', head]\n"
            "        if prefix:\n"
            "            cmd += ['--', prefix]\n"
            "        r = subprocess.run(cmd, capture_output=True, text=True)\n"
            "        if r.returncode != 0:\n"
            "            raise SelectionError(r.stderr.strip())\n"
            "        return set(r.stdout.splitlines())\n"
            "    def read(self, head, paths):\n"
            "        out = {}\n"
            "        for p in paths:\n"
            "            r = subprocess.run(['git', '-C', str(self.repo), 'show', f'{head}:{p}'], capture_output=True, text=True)\n"
            "            if r.returncode != 0:\n"
            "                raise SelectionError(r.stderr.strip())\n"
            "            out[p] = r.stdout\n"
            "        return out\n"
            "def glob_to_regex(pattern):\n"
            "    out = re.escape(pattern).replace(r'\\*\\*', '\\0').replace(r'\\*', '[^/]*').replace(r'\\?', '[^/]')\n"
            "    return re.compile(out.replace('\\0', '.*'))\n"
        ),
        "backend/rollcall/engine/entry/preview.py": "",
        "backend/rollcall/engine/confirm/gate.py": "",
        "backend/rollcall/engine/ladder/rung.py": "",
        "backend/rollcall/engine/seed_clone.py": "",
        "backend/tests/test_entry.py": "import rollcall.engine.entry.preview\n",
        "backend/tests/test_dev_seed_clone.py": "import rollcall.engine.seed_clone\n",
        "qa/positions_journey.py": "",
        "qa/trade_hub_journey.py": "",
    }
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    subprocess.run([*GIT, "-C", str(repo), "add", "-A"], check=True)
    subprocess.run([*GIT, "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    head = subprocess.run(
        [*GIT, "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return repo, head


def test_critical_cli_help_and_one_line_json_outputs(tmp_path):
    repo, head = _make_mini_rollcall_repo(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"recorded = json.loads(pathlib.Path({str(RECORDED_PATH)!r}).read_text())\n"
        "args = sys.argv[1:]\n"
        "run_id = args[2]\n"
        "if '--json' in args:\n"
        "    print(json.dumps({'jobs': recorded['jobs'][run_id]}))\n"
        "    sys.exit(0)\n"
        "if '--log-failed' in args:\n"
        "    if run_id not in recorded['logs']:\n"
        "        sys.stderr.write('log not found\\n')\n"
        "        sys.exit(1)\n"
        "    sys.stdout.write(recorded['logs'][run_id])\n"
        "    sys.exit(0)\n"
        "sys.exit(2)\n"
    )
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ.get('PATH', '')}")

    # 1. `critical --help`
    help_proc = subprocess.run(
        [sys.executable, str(MONEY_SCRIPT), "critical", "--help"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert help_proc.returncode == 0
    for flag in ("--repo", "--run", "--head", "--list", "--github"):
        assert flag in help_proc.stdout

    # 2. `critical` on recorded runs: yes (36080431059, 42081259790), no (42004004262), unknown (36763096407)
    for run_id, expected in (
        ("36080431059", "yes"),
        ("42004004262", "no"),
        ("42081259790", "yes"),
        ("36763096407", "unknown"),
    ):
        proc = subprocess.run(
            [
                sys.executable,
                str(MONEY_SCRIPT),
                "critical",
                "--repo", str(repo),
                "--run", run_id,
                "--head", head,
                "--list", "scripts/money-tests.toml",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 0
        lines = proc.stdout.strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert set(payload) == {"critical", "tests", "why"}
        assert payload["critical"] == expected
        assert isinstance(payload["tests"], list)
        assert isinstance(payload["why"], str) and payload["why"]

    # 3. Existing positional hand CLI still works
    hand_proc = subprocess.run(
        [
            sys.executable,
            str(MONEY_SCRIPT),
            str(repo),
            head,
            "backend/tests/test_entry.py::test_a",
            "backend/tests/test_dev_seed_clone.py::test_b",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert hand_proc.returncode == 0
    assert "money    backend/tests/test_entry.py::test_a" in hand_proc.stdout
    assert "plain    backend/tests/test_dev_seed_clone.py::test_b" in hand_proc.stdout
