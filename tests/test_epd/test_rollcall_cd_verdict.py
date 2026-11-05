"""rollcall_cd_verdict (configs/epd/bin/rollcall_cd_verdict.py): a RollCall commit's ci run on master, once the
commit is live, decides what happens. Owner 2026-11-05, relayed by RollCall rm-ff184438: "Fix forward; undo if
money tests fail".

One small world per test in tmp_path: a real git repository standing in for rollcall (its commits are the run
heads, its alembic.ini says where migrations live), a state dir with RollCall CD 1's state.json and
deploys.jsonl, and fakes for the three things outside: GitHub (answers from runs, jobs and logs recorded from
gh, rollcall_cd_verdict_recorded.json), the money check (RollCall's import graph, tested apart below) and the
deployer/notify seam (RollCall CD 1's `rollcall_cd_deploy.py deploy --kind undo` and rollcall_cd_notify).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "epd" / "bin"
RECORDED = json.loads((Path(__file__).parent / "rollcall_cd_verdict_recorded.json").read_text())
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=master",
       "-c", "commit.gpgsign=false"]
T0 = dt.datetime(2026, 11, 5, 12, 0, tzinfo=dt.UTC)


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V = load("rollcall_cd_verdict")
MONEY = V.rollcall_cd_money  # the module the verdict catches errors of

LIST_TEXT = """version = 1
[backend]
modules = ["backend/rollcall/adapters/orders*", "backend/rollcall/engine/entry/**"]
[qa]
walks = ["entry_journey", "positions_journey", "roll walk"]
"""


# ---------------------------------------------------------------- the world


class FakeGitHub:
    def __init__(self):
        self.all_runs: list = []
        self.job_answers: dict[int, list] = {}
        self.log_answers: dict[int, str] = {}
        self.calls: list = []

    def runs(self):
        return sorted(self.all_runs, key=lambda r: r.created, reverse=True)

    def jobs(self, run_id):
        self.calls.append(("jobs", run_id))
        return self.job_answers.get(run_id, [])

    def failed_log(self, run_id):
        self.calls.append(("log", run_id))
        return self.log_answers.get(run_id, "")


class FakeCheck:
    """Money by test file: files in `money` import a money module, files in `unknown` are not modules."""

    def __init__(self, money=("backend/tests/test_entry.py",), unknown=()):
        self.money, self.unknown = set(money), set(unknown)

    def read_list(self, head):
        return MONEY.parse_money_list(LIST_TEXT)

    def backend(self, head, listed, test_ids):
        answer = MONEY.BackendAnswer()
        for test_id in test_ids:
            path = test_id.split("::", 1)[0]
            if path in self.unknown:
                answer.unknown[test_id] = f"{path} is not a backend module"
            elif path in self.money:
                answer.money[test_id] = ["rollcall.adapters.orders_entry"]
            else:
                answer.plain.append(test_id)
        return answer

    walk = staticmethod(MONEY.MoneyCheck.walk)


class FakeActions:
    def __init__(self, fail_undo: int = 0):
        self.calls: list = []
        self.fail_undo = fail_undo

    def deploy_undo(self, sha, reason):
        self.calls.append(("undo", sha, reason))
        if self.fail_undo:
            self.fail_undo -= 1
            raise V.ReadError("rollcall_cd_deploy.py deploy --kind undo exit 1: health check failed")

    def notify_role(self, role, kind, text):
        self.calls.append(("role", role, kind, text))
        return False  # as rollcall_cd_notify today: kept in its outbox

    def notify_owner(self, text):
        self.calls.append(("owner", text))
        return True

    def of(self, what):
        return [c for c in self.calls if c[0] == what]


class World:
    def __init__(self, tmp_path: Path, script_location: str = "backend/alembic", check: FakeCheck | None = None):
        self.dir = tmp_path / "rollcall"
        self.dir.mkdir()
        self.state_dir = tmp_path / "state"
        self.state_dir.mkdir()
        self.gh = FakeGitHub()
        self.check = check or FakeCheck()
        self.actions = FakeActions()
        self.sha: dict[str, str] = {}
        self.clock = T0
        self.runs = 0
        self.git("init", "-q")
        self.commit("c0", "init", {"alembic.ini": f"[alembic]\nscript_location = {script_location}\n",
                                   f"{script_location}/versions/0001_first.py": "revision = '0001'\n"})

    def git(self, *args: str) -> str:
        return subprocess.run([*GIT, "-C", str(self.dir), *args], check=True, capture_output=True, text=True).stdout

    def tick_clock(self, minutes: int = 1) -> dt.datetime:
        self.clock += dt.timedelta(minutes=minutes)
        return self.clock

    def commit(self, name: str, subject: str, files: dict[str, str] | None = None) -> str:
        for path, text in (files or {f"{name}.txt": name}).items():
            (self.dir / path).parent.mkdir(parents=True, exist_ok=True)
            (self.dir / path).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", subject)
        self.sha[name] = self.git("rev-parse", "HEAD").strip()
        return self.sha[name]

    def run(self, name: str, conclusion: str, *, status: str = "completed", recorded: int | None = None,
            jobs: list | None = None, log: str = "", event: str = "push") -> int:
        self.runs += 1
        run_id = 1000 + self.runs
        created = self.tick_clock()
        self.gh.all_runs.append(V.Run(run_id, self.sha[name], event, status, conclusion, created,
                                      f"https://github.com/shine2lay/rollcall/actions/runs/{run_id}", name))
        if recorded is not None:
            jobs, log = RECORDED["jobs"][str(recorded)], RECORDED["logs"].get(str(recorded), "")
        self.gh.job_answers[run_id] = jobs if jobs is not None else []
        self.gh.log_answers[run_id] = log
        return run_id

    def finish(self, run_id: int, conclusion: str, *, recorded: int | None = None) -> None:
        old = next(r for r in self.gh.all_runs if r.id == run_id)
        self.gh.all_runs[self.gh.all_runs.index(old)] = V.Run(old.id, old.head, old.event, "completed", conclusion,
                                                              old.created, old.url, old.title)
        if recorded is not None:
            self.gh.job_answers[run_id] = RECORDED["jobs"][str(recorded)]
            self.gh.log_answers[run_id] = RECORDED["logs"].get(str(recorded), "")

    def deployed(self, name: str, from_name: str | None = None, kind: str = "deploy") -> None:
        record = {"ts": self.tick_clock().isoformat(), "kind": kind, "sha": self.sha[name],
                  "from_sha": self.sha[from_name] if from_name else None, "reason": "land", "result": "ok",
                  "unit": "rollcall-deploy-1"}
        with open(self.state_dir / "deploys.jsonl", "a") as out:
            out.write(json.dumps(record) + "\n")
        state = self.state()
        state["deployed_sha"] = self.sha[name]
        state.setdefault("undone_shas", [])
        (self.state_dir / "state.json").write_text(json.dumps(state))

    def state(self) -> dict:
        path = self.state_dir / "state.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def records(self) -> list[dict]:
        path = self.state_dir / "deploys.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def verdict(self) -> dict:
        return json.loads((self.state_dir / "verdict.json").read_text())

    def tick(self, *, dry_run: bool = False, actions=None) -> tuple[int, dict[int, dict], dict]:
        out = io.StringIO()
        code = V.tick(self.gh, V.Repo(self.dir), V.Store(self.state_dir, dry_run=dry_run), actions or self.actions,
                      self.check, now=self.tick_clock(), out=out)
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        decisions = {line["run"]: line for line in lines if "run" in line}
        return code, decisions, lines[-1]["summary"]


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def backend_red(tests: list[str], command: str = "uv run pytest -q -p no:cacheprovider") -> tuple[list, str]:
    jobs = [{"name": "backend", "status": "completed", "conclusion": "failure", "steps": [
        {"name": "Set up job", "conclusion": "success"}, {"name": "Tests (pytest)", "conclusion": "failure"}]}]
    prefix = "backend\tTests (pytest)\t2026-11-05T09:55:24.1276511Z "
    log = prefix + f"##[group]Run {command}\n" + "".join(f"{prefix}FAILED {t} - AssertionError\n" for t in tests)
    return jobs, log + prefix + "##[error]Process completed with exit code 1.\n"


# ---------------------------------------------------------------- green


def test_a_green_run_is_recorded_and_does_nothing(world):
    world.commit("c1", "backend: a (Backend #10)")
    run = world.run("c1", "success")
    world.deployed("c1")

    code, decisions, summary = world.tick()

    assert code == 0
    assert decisions[run]["action"] == "green"
    assert world.actions.calls == [] and world.gh.calls == []
    assert world.verdict()["runs"][str(run)]["done"] is True
    assert summary["errors"] == []


# ---------------------------------------------------------------- red, not money: the lander fixes forward


def test_a_red_run_without_a_money_test_tells_each_lander_to_fix_forward(world):
    world.commit("c1", "backend: green base (Backend #10)")
    world.run("c1", "success")
    world.commit("c2", "frontend: tips (Frontend #194)")  # GitHub replaced its run while pending: none of its own
    world.commit("c3", "backend: seed clone (Backend #91)")
    red = world.run("c3", "failure", recorded=42004004262)
    world.deployed("c1")
    world.deployed("c3", "c1")

    code, decisions, _ = world.tick()

    assert code == 0
    assert decisions[red]["action"] == "notify"
    assert decisions[red]["landers"] == ["backend", "frontend"]
    assert world.actions.of("undo") == [] and world.actions.of("owner") == []
    texts = {role: text for _, role, kind, text in world.actions.of("role") if kind == "request"}
    assert sorted(texts) == ["backend", "frontend"]
    for role, text in texts.items():
        assert f"https://github.com/shine2lay/rollcall/actions/runs/{red}" in text
        assert "failing: backend / Tests (pytest) (uv run pytest" in text
        assert "backend/tests/test_dev_seed_clone.py::test_a_screens_wall_clock_elapsed_is_not_seeded_state_but_its_counts_are" in text
        assert "money test: no" in text and "fix forward" in text
    yours = {role: [line.split()[0] for line in text.splitlines() if line.startswith("  ")]
             for role, text in texts.items()}
    assert yours == {"frontend": [world.sha["c2"][:12]], "backend": [world.sha["c3"][:12]]}
    assert "commits this run is first to check: 2; yours:" in texts["frontend"]
    assert world.state()["undone_shas"] == []


def test_a_message_names_at_most_20_failing_tests(world):
    world.commit("c1", "frontend: x (Frontend #1)")
    tests = [f"backend/tests/test_plain.py::test_{n}" for n in range(25)]
    jobs, log = backend_red(tests)
    world.run("c1", "failure", jobs=jobs, log=log)
    world.deployed("c1")

    world.tick()

    (_, role, _, text), = world.actions.of("role")
    assert role == "frontend"
    line, = [line for line in text.splitlines() if line.startswith("tests (")]
    assert line.split(": ", 1)[1].split() == tests[:20]
    assert line.startswith("tests (20 of 25): ")


# ---------------------------------------------------------------- red money: undo to the last fully green commit


def test_a_red_money_test_puts_the_last_fully_green_commit_back_live(world):
    world.commit("c1", "backend: base (Backend #10)")
    world.run("c1", "success")
    world.commit("c2", "backend: entry preview (Backend #11)")
    world.commit("c3", "frontend: entry ticket (Frontend #12)")
    red = world.run("c3", "failure", recorded=36080431059)
    world.deployed("c1")
    world.deployed("c3", "c1")

    code, decisions, summary = world.tick()

    assert code == 0
    decision = decisions[red]
    assert decision["action"] == "undo" and decision["target"] == world.sha["c1"][:12]
    assert decision["money"].startswith("yes: backend/tests/test_entry.py::test_preview_prices")
    (_, sha, reason), = world.actions.of("undo")
    assert sha == world.sha["c1"]
    assert f"ci run {red}" in reason and "money test red" in reason
    assert world.state()["undone_shas"] == sorted([world.sha["c2"], world.sha["c3"]])
    assert [r["kind"] for r in world.records()] == ["deploy", "deploy"]  # no refusal; the deployer logs the undo
    texts = {role: text for _, role, _, text in world.actions.of("role")}
    assert sorted(texts) == ["backend", "frontend"]
    assert f"undo: {world.sha['c1'][:12]} (last fully green) goes back live" in texts["backend"]
    assert world.verdict()["pending_undo"]["sha"] == world.sha["c1"]
    assert summary["live"] == world.sha["c3"][:12]
    # The undo's place is taken: the deployer's own record of it ends the pending undo.
    world.deployed("c1", "c3", kind="undo")
    _, _, summary = world.tick()
    assert world.verdict()["pending_undo"] is None and summary["live"] == world.sha["c1"][:12]


def test_a_red_money_qa_walk_undoes_too(world):
    world.commit("c1", "frontend: base (Frontend #1)")
    world.run("c1", "success")
    world.commit("c2", "frontend: positions row bar (Frontend #194)")
    red = world.run("c2", "failure", recorded=42081259790, event="schedule")
    world.deployed("c2", "c1")

    _, decisions, _ = world.tick()

    assert decisions[red]["action"] == "undo"
    assert decisions[red]["money"] == "yes: qa walk positions_journey (The Positions tab's happy path)"
    assert [c[1] for c in world.actions.of("undo")] == [world.sha["c1"]]


def test_no_undo_when_live_already_holds_a_green_fix(world):
    world.commit("c1", "backend: base (Backend #10)")
    world.run("c1", "success")
    world.commit("c2", "backend: entry (Backend #11)")
    red = world.run("c2", "failure", recorded=36080431059)
    world.commit("c3", "backend: entry fixed (Backend #12)")
    world.run("c3", "success")
    world.deployed("c3", "c1")

    _, decisions, _ = world.tick()

    assert decisions[red]["action"] == "notify" and "is green" in decisions[red]["why"]
    assert world.actions.of("undo") == [] and world.state()["undone_shas"] == []


# ---------------------------------------------------------------- red money with a migration between: refuse


@pytest.mark.parametrize("script_location, migration, refused", [
    ("backend/alembic", "backend/alembic/versions/0002_add_fill.py", True),
    ("db/migrations", "db/migrations/versions/0002_add_fill.py", True),
    ("db/migrations", "backend/alembic/versions/0002_add_fill.py", False),  # not where alembic.ini points
])
def test_a_migration_between_refuses_the_undo(tmp_path, script_location, migration, refused):
    world = World(tmp_path, script_location)
    world.commit("c1", "backend: base (Backend #10)")
    world.run("c1", "success")
    world.commit("c2", "backend: fills table (Backend #11)", {migration: "revision = '0002'\n"})
    red = world.run("c2", "failure", recorded=36080431059)
    world.deployed("c2", "c1")

    code, decisions, _ = world.tick()

    assert code == 0
    if not refused:
        assert decisions[red]["action"] == "undo"
        return
    assert decisions[red]["action"] == "refuse" and migration in decisions[red]["why"]
    assert world.actions.of("undo") == [] and world.state()["undone_shas"] == []
    refusal = world.records()[-1]
    assert refusal["kind"] == "refusal" and refusal["result"] == "refused"
    assert refusal["sha"] == world.sha["c1"] and refusal["from_sha"] == world.sha["c2"]
    assert f"run {red}: migration between" in refusal["reason"]
    texts = {role: text for _, role, _, text in world.actions.of("role")}
    assert sorted(texts) == ["backend", "rollcall"]
    assert "undo refused" in texts["rollcall"] and migration in texts["rollcall"]
    assert f"actions/runs/{red}" in texts["rollcall"]
    (_, owner), = world.actions.of("owner")
    assert f"actions/runs/{red}" in owner and "database changed" in owner
    assert not re.search(r"\b[0-9a-f]{12,}\b", owner)  # plain words for the owner: no commit ids


def test_no_fully_green_commit_to_go_back_to_is_a_refusal(world):
    world.commit("c1", "backend: entry (Backend #11)")
    red = world.run("c1", "failure", recorded=36080431059)
    world.deployed("c1", "c0")

    _, decisions, _ = world.tick()

    assert decisions[red]["action"] == "refuse" and "no fully green commit" in decisions[red]["why"]
    assert world.records()[-1]["sha"] is None
    assert len(world.actions.of("owner")) == 1 and world.actions.of("undo") == []


# ---------------------------------------------------------------- what counts as green


def test_cancelled_skipped_and_missing_runs_are_not_green(world):
    world.commit("c1", "backend: base (Backend #10)")
    world.run("c1", "success")
    world.commit("c2", "frontend: a (Frontend #2)")
    cancelled = world.run("c2", "cancelled")  # replaced by a newer push before any job ran
    world.commit("c3", "frontend: b (Frontend #3)")  # no run at all
    world.commit("c4", "frontend: c (Frontend #4)")
    skipped = world.run("c4", "skipped")
    world.commit("c5", "backend: entry (Backend #5)")
    red = world.run("c5", "failure", recorded=36080431059)
    world.deployed("c5", "c1")

    _, decisions, _ = world.tick()

    assert decisions[cancelled]["action"] == "ignored" and decisions[skipped]["action"] == "ignored"
    assert decisions[red]["target"] == world.sha["c1"][:12]
    assert world.state()["undone_shas"] == sorted(world.sha[n] for n in ("c2", "c3", "c4", "c5"))
    # The run before c5's that finished is c1's (cancelled and skipped runs checked nothing): all four are new.
    assert sorted(decisions[red]["landers"]) == ["backend", "frontend"]


def test_a_run_still_going_waits_and_is_decided_once_it_ends(world):
    world.commit("c1", "backend: base (Backend #10)")
    run = world.run("c1", "", status="in_progress")
    world.deployed("c1", "c0")

    _, decisions, summary = world.tick()
    assert decisions == {} and summary["waiting"] == 1
    assert not (world.state_dir / "verdict.json").exists()

    world.finish(run, "failure", recorded=42004004262)
    _, decisions, _ = world.tick()
    assert decisions[run]["action"] == "notify"


def test_a_cancelled_run_whose_tests_had_started_is_red_with_money_unknown(world):
    world.commit("c1", "backend: base (Backend #10)")
    world.run("c1", "success")
    world.commit("c2", "backend: slow (Backend #11)")
    jobs = [{"name": "backend", "status": "completed", "conclusion": "cancelled", "steps": [
        {"name": "Set up job", "conclusion": "success"}, {"name": "Tests (pytest)", "conclusion": "cancelled"}]}]
    stopped = world.run("c2", "cancelled", jobs=jobs)
    world.deployed("c2", "c1")

    _, decisions, _ = world.tick()

    assert decisions[stopped]["action"] == "notify" and decisions[stopped]["money"].startswith("unknown")
    assert world.actions.of("undo") == []
    roles = [c[1] for c in world.actions.of("role")]
    assert roles == ["backend", "rollcall"]


def test_unknown_money_asks_rollcall_and_undoes_nothing(world):
    world.commit("c1", "frontend: base (Frontend #1)")
    world.run("c1", "success")
    world.commit("c2", "frontend: a (Frontend #2)")
    red = world.run("c2", "failure", recorded=36763096407)  # every job failed before any step ran
    world.deployed("c2", "c1")

    _, decisions, _ = world.tick()

    assert decisions[red]["money"].startswith("unknown: backend / (no step ran)")
    texts = {role: text for _, role, _, text in world.actions.of("role")}
    assert sorted(texts) == ["frontend", "rollcall"]
    assert "money test unknown: no undo" in texts["frontend"]
    assert "no undo done" in texts["rollcall"]
    assert world.actions.of("undo") == []


# ---------------------------------------------------------------- deployed or not


def test_a_red_run_waits_until_its_commit_is_deployed_and_a_covering_deploy_counts(world):
    world.commit("c1", "backend: base (Backend #10)")
    world.run("c1", "success")
    world.deployed("c1")
    world.commit("c2", "frontend: a (Frontend #2)")
    red = world.run("c2", "failure", recorded=42004004262)

    _, decisions, summary = world.tick()
    assert red not in decisions and summary["waiting"] == 1 and world.actions.calls == []

    world.commit("c3", "frontend: b (Frontend #3)")
    world.deployed("c3", "c1")  # c2 is not the deployed commit, but this deploy put it live
    _, decisions, _ = world.tick()
    assert decisions[red]["action"] == "notify" and decisions[red]["landers"] == ["frontend"]


def test_a_red_run_on_a_commit_live_before_continuous_deploy_is_left_alone(world):
    world.commit("c1", "frontend: old (Frontend #1)")
    red = world.run("c1", "failure", recorded=36080431059)
    world.commit("c2", "frontend: new (Frontend #2)")
    world.deployed("c2", "c1")  # CD's first deploy: c1 was live already

    _, decisions, _ = world.tick()

    assert decisions[red]["action"] == "before_cd"
    assert world.actions.calls == []


# ---------------------------------------------------------------- once per run id


def test_each_run_id_is_acted_on_once(world):
    world.commit("c1", "backend: base (Backend #10)")
    world.run("c1", "success")
    world.commit("c2", "backend: entry (Backend #11)")
    world.run("c2", "failure", recorded=36080431059)
    world.commit("c3", "frontend: plain (Frontend #12)")
    world.run("c3", "failure", recorded=42004004262)
    world.deployed("c3", "c1")

    world.tick()
    files = {p.name: p.read_bytes() for p in world.state_dir.iterdir()}
    calls, gh_calls = list(world.actions.calls), list(world.gh.calls)

    code, decisions, summary = world.tick()

    assert code == 0 and decisions == {} and summary["decided"] == 0
    assert world.actions.calls == calls and world.gh.calls == gh_calls
    assert {p.name: p.read_bytes() for p in world.state_dir.iterdir()} == files


def test_a_failed_undo_is_retried_at_the_next_tick_and_nothing_else_repeats(world):
    world.commit("c1", "backend: base (Backend #10)")
    world.run("c1", "success")
    world.commit("c2", "backend: entry (Backend #11)")
    red = world.run("c2", "failure", recorded=36080431059)
    world.deployed("c2", "c1")
    world.actions.fail_undo = 1

    code, _, summary = world.tick()
    assert code == 1 and "health check failed" in summary["errors"][0]
    assert world.verdict()["pending_undo"] is None

    code, decisions, summary = world.tick()
    assert code == 0 and decisions == {} and summary["errors"] == []
    assert [c[1] for c in world.actions.of("undo")] == [world.sha["c1"], world.sha["c1"]]
    roles = [c[1] for c in world.actions.of("role")]
    assert roles == ["backend", "rollcall"]  # the lander once, RollCall once about the failed undo
    assert world.verdict()["runs"][str(red)]["done"] is True

    world.tick()
    assert len(world.actions.of("undo")) == 2


def test_a_dry_run_writes_nothing_and_prints_each_action(world):
    world.commit("c1", "backend: base (Backend #10)")
    world.run("c1", "success")
    world.commit("c2", "backend: entry (Backend #11)")
    world.run("c2", "failure", recorded=36080431059)
    world.deployed("c2", "c1")
    before = {p.name: p.read_bytes() for p in world.state_dir.iterdir()}
    out = io.StringIO()

    world.tick(dry_run=True, actions=V.PrintedActions(out))

    assert {p.name: p.read_bytes() for p in world.state_dir.iterdir()} == before
    printed = [json.loads(line)["dry_run_action"] for line in out.getvalue().splitlines()]
    assert [a["do"] for a in printed] == ["undo", "role"]
    assert printed[0]["sha"] == world.sha["c1"]


# ---------------------------------------------------------------- who landed it


@pytest.mark.parametrize("subject, role", [
    ("frontend: Positions row bar (Frontend #194)", "frontend"),
    ("backend: /api/health reports the commit (Backend #91)", "backend"),
    ("qa: journeys find the ticket (Frontend #189, RollCall rm-da08a1ec)", "frontend"),
    ("design: stage 2 meets its bar (Design #207)", "design"),
    ("ci: shard the walks (QA #31)", "qa"),
    ("test selection (Systems #88)", "systems"),
    ("two roles (Frontend #3, Backend #4)", "backend"),
    ("docs: a fix (rm-ff184438)", "rollcall"),
    ("no trailer at all", "rollcall"),
    ("someone new (Marketingops #3)", "rollcall"),
    ("a fix (Backend #3) in the middle", "rollcall"),
])
def test_the_lander_comes_from_the_subjects_trailer(subject, role):
    assert V.lander_of(subject) == role


# ---------------------------------------------------------------- reading gh's answers


def test_the_failed_log_gives_each_step_its_command_and_the_failing_tests():
    old = V.failures_of(RECORDED["jobs"]["36080431059"], RECORDED["logs"]["36080431059"])
    assert [(f.job, f.step) for f in old] == [("backend", "Tests (pytest)")]
    assert old[0].command.startswith("uv run pytest")  # "UNKNOWN STEP" logs: the command open at the error
    assert len(old[0].tests) == 4 and old[0].tests[0].startswith("backend/tests/test_entry.py::test_preview_")

    qa, = V.failures_of(RECORDED["jobs"]["42081259790"], RECORDED["logs"]["42081259790"])
    assert (qa.job, qa.step, qa.command) == ("qa", "The Positions tab's happy path",
                                             "uv run python qa/positions_journey.py")
    assert qa.tests == []

    none_ran = V.failures_of(RECORDED["jobs"]["36763096407"], "")
    assert [(f.job, f.step) for f in none_ran] == [("frontend", "(no step ran)"), ("backend", "(no step ran)"),
                                                   ("qa", "(no step ran)")]


def test_gh_is_the_only_github_client():
    answers = {
        "list": [{"databaseId": 2, "headSha": "b" * 40, "event": "push", "status": "completed",
                  "conclusion": "failure", "createdAt": "2026-11-05T18:06:59Z", "url": "u2", "displayTitle": "t"},
                 {"databaseId": 1, "headSha": "a" * 40, "event": "pull_request", "status": "completed",
                  "conclusion": "success", "createdAt": "2026-11-05T18:00:00Z", "url": "u1", "displayTitle": "t"}],
    }
    seen = []

    def runner(args):
        seen.append(list(args))
        if args[1:3] == ["run", "list"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(answers["list"]), "")
        if "--log-failed" in args:
            return subprocess.CompletedProcess(args, 1, "", "log not found: 110050360965\n")
        return subprocess.CompletedProcess(args, 1, "", "HTTP 502\n")

    github = V.GitHub("shine2lay/rollcall", runner)
    runs = github.runs()
    assert [r.id for r in runs] == [2] and runs[0].created == dt.datetime(2026, 11, 5, 18, 6, 59, tzinfo=dt.UTC)
    assert github.failed_log(2) == ""
    with pytest.raises(V.ReadError, match="HTTP 502"):
        github.jobs(2)
    assert all(a[0] == "gh" and a[-2:] == ["--repo", "shine2lay/rollcall"] for a in seen)
    assert seen[0][:9] == ["gh", "run", "list", "--workflow", "ci.yml", "--branch", "master", "--limit", "100"]

    def down(args):
        return subprocess.CompletedProcess(args, 1, "", "gh: not logged in\n")

    with pytest.raises(V.VerdictError, match="not logged in"):
        V.GitHub("shine2lay/rollcall", down).runs()


# ---------------------------------------------------------------- rollcall_cd_money, on a stand-in selector


class StandInGraph:
    """The shape of rollcall's scripts/backend_import_graph.py that rollcall_cd_money uses; edges from
    "import x" lines. It records the bounds it was built with."""

    built_with: dict = {}

    @staticmethod
    def module_name(path):
        if not path.startswith("backend/") or not path.endswith(".py"):
            return None
        return path[len("backend/"):-3].replace("/", ".").removesuffix(".__init__")

    @classmethod
    def build_graph(cls, sources, bounds):
        cls.built_with = dict(bounds)
        modules = {cls.module_name(p): p for p in sources}
        edges = {cls.module_name(p): set(re.findall(r"^import (\S+)$", text, re.MULTILINE))
                 for p, text in sources.items()}
        return type("Graph", (), {"modules": modules, "edges": edges})()


class StandInSelect:
    class SelectionError(Exception):
        pass

    files_at: dict[str, str] = {}

    class Git:
        def __init__(self, repo):
            pass

        def files(self, head, prefix=""):
            return {p for p in StandInSelect.files_at if p.startswith(prefix)}

        def read(self, head, paths):
            return {p: StandInSelect.files_at[p] for p in paths}

    @staticmethod
    def glob_to_regex(pattern):
        out = re.escape(pattern).replace(r"\*\*", "\0").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        return re.compile(out.replace("\0", ".*"))


def test_money_check_follows_test_helpers_but_not_conftest():
    StandInSelect.files_at = {
        MONEY.LIST_PATH: LIST_TEXT,
        "backend/rollcall/adapters/orders_entry.py": "",
        "backend/rollcall/engine/entry/size.py": "",
        "backend/rollcall/settings.py": "",
        "backend/tests/conftest.py": "import rollcall.adapters.orders_entry\n",
        "backend/tests/helpers.py": "import rollcall.engine.entry.size\n",
        "backend/tests/test_direct.py": "import rollcall.adapters.orders_entry\n",
        "backend/tests/test_through_helper.py": "import tests.helpers\n",
        "backend/tests/test_plain.py": "import tests.conftest\nimport rollcall.settings\n",
        ".github/workflows/ci.yml": "jobs:\n  qa:\n    steps:\n      - name: The Positions tab's happy path\n",
        "qa/entry_journey.py": "",
        "qa/positions_journey.py": "",
    }
    selector = MONEY.RollcallSelector(StandInGraph, StandInSelect)
    check = MONEY.MoneyCheck(Path("/nowhere"), selector)
    listed = check.read_list("head")

    answer = check.backend("head", listed, ["backend/tests/test_direct.py::a", "backend/tests/test_through_helper.py::b",
                                            "backend/tests/test_plain.py::c", "backend/tests/gone.py::d"])

    assert answer.money == {"backend/tests/test_direct.py::a": ["rollcall.adapters.orders_entry"],
                            "backend/tests/test_through_helper.py::b": ["rollcall.engine.entry.size"]}
    assert answer.plain == ["backend/tests/test_plain.py::c"]
    assert list(answer.unknown) == ["backend/tests/gone.py::d"]
    assert all(name.startswith("tests") for name in StandInGraph.built_with)  # only test modules are bounded
    assert set(StandInGraph.built_with.values()) == {()}
    assert check.unmatched("head", listed) == ["[qa] 'roll walk' names no qa/roll walk.py and no ci.yml step at head"]


def test_money_list_must_say_what_it_means():
    assert MONEY.parse_money_list(LIST_TEXT).walks == ("entry_journey", "positions_journey", "roll walk")
    for bad in ("version = 2\n", "version = 1\n[backend]\nmodules = []\n", "not toml = \n",
                'version = 1\n[backend]\nmodules = [""]\n[qa]\nwalks = []\n'):
        with pytest.raises(MONEY.MoneyListError):
            MONEY.parse_money_list(bad)
    listed = MONEY.parse_money_list(LIST_TEXT)
    assert MONEY.MoneyCheck.walk(listed, "Any step", "uv run python qa/entry_journey.py") == "entry_journey"
    assert MONEY.MoneyCheck.walk(listed, "The ROLL WALK on a phone", "uv run python qa/x.py") == "roll walk"
    assert MONEY.MoneyCheck.walk(listed, "Ideas' happy path", "uv run python qa/ideas_journey.py") is None
