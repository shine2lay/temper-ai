#!/usr/bin/env python3
"""rollcall_cd_verdict: once a RollCall commit is live, its ci run on master decides what happens next.

One job: read the finished ci runs of shine2lay/rollcall's master (gh is the only GitHub client) and decide,
once per run id:
  green                       nothing
  red, no money test          tell the department that landed the commits the run is first to check; it fixes
                              forward, and the next land deploys as usual
  red in a money test         put the newest fully green commit back live (rollcall_cd_deploy.py deploy --kind
                              undo) and add the commits taken off to state.json undone_shas, so the deployer
                              does not put them back
  money, migration between    refuse the undo: log it, ask RollCall, tell the owner
Owner 2026-11-05, relayed by RollCall rm-ff184438: "Fix forward; undo if money tests fail". No model (AGENTS.md
rule 17); which tests are money is rollcall_cd_money.py's answer from RollCall's scripts/money-tests.toml.

    python3 rollcall_cd_verdict.py --repo DIR [--state-dir DIR] [--fetch]
    python3 rollcall_cd_verdict.py --repo DIR --dry-run [--assume-deployed] [--runs N] [--money-list FILE]

Terms:
  fully green  the commit's own non-PR ci run on master finished with conclusion success. A push run checks
               what changed since the last such run, so a green run covers every commit before it. Cancelled,
               skipped, missing or still running is not green; a commit GitHub replaced while pending has no
               run of its own, and the next run covers it.
  red          conclusion failure, timed_out or startup_failure; also a cancelled run one of whose jobs had
               started (stopped by its time limit or by hand), since its tests never finished.
  deployed     a commit some deploy put live: deploys.jsonl holds a record with result ok whose sha is that
               commit or, with a from_sha, a descendant of it that from_sha is not. A red run waits until its
               head is deployed. Commits already live before CD's first deploy are never acted on.
  new commits  the commits a run is the first to finish checking: those after the head of the newest earlier
               run that finished (cancelled ones did not). Their trailers name the landers.
  lander       the role in the subject's final "(... <Role> #N)" group, the last known role there wins
               ("(Frontend #194)" -> frontend); none -> rollcall.
  target       for a money red: the head of the newest fully green run before it on an ancestor of its head.
               No undo when a green run on a commit between the red head and live already proves live fixed.
  failing tests  from `gh run view --log-failed`: pytest's "FAILED|ERROR backend/tests/...::..." lines. ci.yml
               writes no JUnit (its one artifact is qa-agree-findings, the qa walk's shots), so the log is
               the only source. money: unknown (RollCall asked, no undo) when the money tests could not be
               read: a backend pytest step failed with no test line, a backend or qa job ran no step or
               only GitHub's set-up, or a qa job was stopped part way.

State (--state-dir, default ~/.local/state/rollcall-cd). RollCall CD 1's deployer owns state.json and
deploys.jsonl; this script takes state.lock to change them:
  state.json     reads deployed_sha; adds to undone_shas before it asks for an undo
  deploys.jsonl  reads deploy records {ts, kind, sha, from_sha, reason, result, unit}; appends kind refusal
  verdict.json   this script's own: each run id it decided, its steps and which are done; the undo in flight
Each step is marked done the moment it is done, so a rerun of the same tick changes nothing and a step that
failed (an undo the deployer refused) is retried at the next tick, the rest of the run's steps not repeated.

Output: one JSON line per decision, then {"summary": ...}. Exit 0 when every step is done or waiting; 1 when a
step failed or a run could not be read (both retried at the next tick); 2 when the runs, the repository or the
state cannot be read at all. --dry-run writes nothing and sends nothing: each action is printed instead.
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

BIN = Path(__file__).resolve().parent
if str(BIN) not in sys.path:  # run as a script it is sys.path[0] already; loaded by path (the tests) it is not
    sys.path.insert(0, str(BIN))

import rollcall_cd_money  # noqa: E402  -- a plain import, so temper-ai's test selector can follow it

GH_REPO = "shine2lay/rollcall"
WORKFLOW = "ci.yml"
BRANCH = "master"
RUN_LIST_LIMIT = 100
RUN_FIELDS = "databaseId,headSha,event,status,conclusion,createdAt,url,displayTitle"
DEFAULT_STATE_DIR = os.environ.get("ROLLCALL_CD_STATE", "~/.local/state/rollcall-cd")  # as rollcall_cd_notify
GREEN = "success"
RED = frozenset({"failure", "timed_out", "startup_failure"})
SHIPPED_RESULTS = frozenset({"ok", "success"})
BACKEND_JOB = "backend"
QA_JOB = "qa"
MAX_TESTS_IN_MESSAGE = 20
FALLBACK_ROLE = "rollcall"
ROLE_IDS = frozenset({"architecture", "backend", "coo", "data", "design", "docs", "frontend", "marketing", "ops",
                      "product", "qa", "rollcall", "security", "systems", "temper"})
FINAL_GROUP = re.compile(r"\(([^()]*)\)\s*$")
ROLE_REF = re.compile(r"([A-Za-z]+) #\d+")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ?")
TEST_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+)")
STEP_ERROR = "##[error]Process completed with exit code"


class VerdictError(Exception):
    """Nothing safe can be decided this tick: the runs, the repository or the state cannot be read."""


class ReadError(Exception):
    """One run or one action could not be read or done; it is tried again at the next tick."""


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def parse_ts(text: str) -> dt.datetime:
    value = dt.datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def short(sha: str | None) -> str:
    return (sha or "none")[:12]


def run_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False)


# ---------------------------------------------------------------- GitHub, through gh


@dataclass(frozen=True)
class Run:
    id: int
    head: str
    event: str
    status: str
    conclusion: str
    created: dt.datetime
    url: str
    title: str

    @classmethod
    def from_gh(cls, item: dict) -> Run:
        return cls(int(item["databaseId"]), item["headSha"], item["event"], item["status"],
                   item.get("conclusion") or "", parse_ts(item["createdAt"]), item["url"],
                   item.get("displayTitle") or "")


class GitHub:
    """The three reads this script makes, each one gh call."""

    def __init__(self, repo: str = GH_REPO, runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_command):
        self.repo = repo
        self.runner = runner

    def _gh(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.runner(["gh", *args, "--repo", self.repo])

    def runs(self) -> list[Run]:
        """Master's non-PR ci runs, newest first."""
        done = self._gh("run", "list", "--workflow", WORKFLOW, "--branch", BRANCH, "--limit", str(RUN_LIST_LIMIT),
                        "--json", RUN_FIELDS)
        if done.returncode != 0:
            raise VerdictError(f"gh run list failed: {done.stderr.strip()[:300]}")
        return [Run.from_gh(item) for item in json.loads(done.stdout) if item["event"] != "pull_request"]

    def jobs(self, run_id: int) -> list[dict]:
        done = self._gh("run", "view", str(run_id), "--json", "jobs")
        if done.returncode != 0:
            raise ReadError(f"gh run view {run_id} --json jobs failed: {done.stderr.strip()[:300]}")
        return json.loads(done.stdout)["jobs"]

    def failed_log(self, run_id: int) -> str:
        """The failed steps' logs; "" when GitHub has none (jobs that never ran a step)."""
        done = self._gh("run", "view", str(run_id), "--log-failed")
        if done.returncode != 0:
            if "log not found" in done.stderr:
                return ""
            raise ReadError(f"gh run view {run_id} --log-failed failed: {done.stderr.strip()[:300]}")
        return done.stdout


# ---------------------------------------------------------------- the rollcall repository, read-only


class Repo:
    def __init__(self, path: Path, runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_command):
        self.path = Path(path)
        self.runner = runner

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.runner(["git", "-C", str(self.path), *args])

    def out(self, *args: str) -> str:
        done = self._git(*args)
        if done.returncode != 0:
            raise ReadError(f"git {' '.join(args)}: {done.stderr.strip()[:300]}")
        return done.stdout

    def has(self, sha: str) -> bool:
        return self._git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0

    def is_ancestor(self, older: str, newer: str) -> bool:
        """older == newer counts."""
        done = self._git("merge-base", "--is-ancestor", older, newer)
        if done.returncode not in (0, 1):
            raise ReadError(f"git merge-base --is-ancestor {short(older)} {short(newer)}: {done.stderr.strip()[:300]}")
        return done.returncode == 0

    def commits(self, base: str | None, head: str) -> list[tuple[str, str]]:
        """(sha, subject) of base..head, oldest first; just head when base is None."""
        spec = [f"{base}..{head}"] if base else ["-1", head]
        text = self.out("log", "--reverse" if base else "--no-walk", "--format=%H%x00%s", *spec)
        return [tuple(line.split("\0", 1)) for line in text.splitlines() if line]

    def parent(self, sha: str) -> str | None:
        done = self._git("rev-parse", "--verify", "--quiet", f"{sha}^")
        return done.stdout.strip() or None if done.returncode == 0 else None

    def changed(self, base: str, head: str) -> list[str]:
        return [p for p in self.out("diff", "--name-only", base, head).splitlines() if p]

    def migrations_dir(self, sha: str) -> str:
        """Where the migrations live at `sha`: alembic.ini's script_location + /versions/."""
        ini = configparser.ConfigParser(interpolation=None)
        ini.read_string(self.out("show", f"{sha}:alembic.ini"))
        location = ini.get("alembic", "script_location", fallback="").strip().strip("/")
        if not location:
            raise ReadError(f"alembic.ini at {short(sha)} has no [alembic] script_location")
        return location + "/versions/"


# ---------------------------------------------------------------- what failed, from gh's answers


@dataclass
class Failure:
    job: str
    step: str
    command: str = ""
    tests: list[str] = field(default_factory=list)
    stopped: bool = False


@dataclass
class JobLog:
    commands: dict[str, str] = field(default_factory=dict)  # step column -> its first "Run ..." command
    failing_command: str = ""  # the command open when "Process completed with exit code" was logged
    tests: list[str] = field(default_factory=list)


def parse_failed_log(text: str) -> dict[str, JobLog]:
    """gh run view --log-failed: lines "job<TAB>step<TAB>stamp content". Old runs log "UNKNOWN STEP" as the step."""
    logs: dict[str, JobLog] = {}
    current: dict[str, str] = {}
    for raw in text.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            continue
        job, step, rest = parts
        content = ANSI.sub("", STAMP.sub("", rest.lstrip("\ufeff")))
        log = logs.setdefault(job, JobLog())
        if content.startswith("##[group]Run "):
            command = content[len("##[group]Run "):].strip()
            current[job] = command
            log.commands.setdefault(step, command)
        elif content.startswith(STEP_ERROR):
            log.failing_command = current.get(job, "")
        else:
            match = TEST_LINE.match(content)
            if match and match.group(1) not in log.tests:
                log.tests.append(match.group(1))
    return logs


def job_started(job: dict) -> bool:
    return any(s.get("conclusion") not in (None, "", "skipped") for s in job.get("steps") or [])


def failures_of(jobs: Sequence[dict], log_text: str) -> list[Failure]:
    """One Failure per failing (or stopped) step; a failed job with no step that ran is one Failure too."""
    logs = parse_failed_log(log_text)
    out = []
    for job in jobs:
        if job.get("conclusion") in ("success", "skipped", None, ""):
            continue
        name = job["name"]
        log = logs.get(name, JobLog())
        steps = job.get("steps") or []
        failed = [s for s in steps if s.get("conclusion") == "failure"]
        stopped = not failed and job.get("conclusion") == "cancelled"
        if stopped:
            failed = [s for s in steps if s.get("conclusion") == "cancelled"]
        if not failed:
            why = "no step ran" if not steps else f"job {job.get('conclusion')}"
            out.append(Failure(name, f"({why})", stopped=stopped))
            continue
        for step in failed:
            command = log.commands.get(step["name"]) or (log.failing_command if len(failed) == 1 else "")
            tests = list(log.tests) if name == BACKEND_JOB else []
            out.append(Failure(name, step["name"], command, tests, stopped))
    return out


# ---------------------------------------------------------------- who landed it


def lander_of(subject: str) -> str:
    group = FINAL_GROUP.search(subject)
    if group:
        for name in reversed(ROLE_REF.findall(group.group(1))):
            if name.lower() in ROLE_IDS:
                return name.lower()
    return FALLBACK_ROLE


# ---------------------------------------------------------------- money


@dataclass
class Money:
    state: str  # yes, no, unknown
    why: str
    ids: list[str] = field(default_factory=list)


def money_of(failures: Sequence[Failure], head: str, check, money_list_text: str | None) -> Money:
    """Whether the run failed in a money test. `check` is a rollcall_cd_money.MoneyCheck."""
    try:
        listed = (rollcall_cd_money.parse_money_list(money_list_text) if money_list_text is not None
                  else check.read_list(head))
    except rollcall_cd_money.MoneyListError as err:
        return Money("unknown", str(err))
    yes, unknown, plain = [], [], []
    for failure in failures:
        if failure.job == BACKEND_JOB:
            if failure.tests:
                try:
                    answer = check.backend(head, listed, failure.tests)
                except rollcall_cd_money.MoneyListError as err:
                    unknown.append(f"backend tests: {err}")
                    continue
                yes += [f"{t} (imports {', '.join(m[:2])})" for t, m in answer.money.items()]
                unknown += [f"{t}: {why}" for t, why in answer.unknown.items()]
                plain += answer.plain
            elif failure.stopped or "pytest" in failure.command or not failure.command:
                unknown.append(f"backend / {failure.step}: no FAILED or ERROR test line in the log")
        elif failure.job == QA_JOB:
            walk = check.walk(listed, failure.step, failure.command)
            if failure.stopped:
                unknown.append(f"qa / {failure.step} was stopped before the walks finished")
            elif walk:
                yes.append(f"qa walk {walk} ({failure.step})")
            elif not failure.command:
                unknown.append(f"qa / {failure.step}: no walk ran")
    if yes:
        return Money("yes", "; ".join(yes[:3]), yes)
    if unknown:
        return Money("unknown", "; ".join(unknown[:3]), unknown)
    return Money("no", f"{len(plain)} failing tests, none on the money list" if plain else "no money test failed")


# ---------------------------------------------------------------- state


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as out:
            out.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


class Store:
    """The state dir. dry_run: reads as usual, writes nothing."""

    def __init__(self, path: Path, dry_run: bool = False):
        self.path = Path(path).expanduser()
        self.dry_run = dry_run

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        self.path.mkdir(parents=True, exist_ok=True)
        with open(self.path / "state.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _json(self, name: str, empty: dict) -> dict:
        try:
            return json.loads((self.path / name).read_text())
        except FileNotFoundError:
            return empty
        except json.JSONDecodeError as err:
            raise VerdictError(f"{self.path / name} is not JSON: {err}") from None

    def state(self) -> dict:
        return self._json("state.json", {})

    def records(self) -> list[dict]:
        try:
            lines = (self.path / "deploys.jsonl").read_text().splitlines()
        except FileNotFoundError:
            return []
        out = []
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                record["_ts"] = parse_ts(record["ts"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as err:
                raise VerdictError(f"{self.path / 'deploys.jsonl'} line {number} is not a deploy record: {err}") from None
            out.append(record)
        return out

    def verdict(self) -> dict:
        data = self._json("verdict.json", {"version": 1, "runs": {}, "pending_undo": None})
        if data.get("version") != 1:
            raise VerdictError(f"{self.path / 'verdict.json'}: version must be 1")
        return data

    def save_verdict(self, data: dict) -> None:
        if not self.dry_run:
            self.path.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path / "verdict.json", json.dumps(data, indent=1, sort_keys=True) + "\n")

    def add_undone(self, shas: Sequence[str]) -> None:
        if self.dry_run:
            return
        with self.locked():
            state = self.state()
            state["undone_shas"] = sorted(set(state.get("undone_shas") or []) | set(shas))
            write_atomic(self.path / "state.json", json.dumps(state, indent=1, sort_keys=True) + "\n")

    def append_record(self, record: dict) -> None:
        if self.dry_run:
            return
        with self.locked(), open(self.path / "deploys.jsonl", "a") as out:
            out.write(json.dumps(record, sort_keys=True) + "\n")


# ---------------------------------------------------------------- actions (the seam RollCall CD 1 provides)


class Actions:
    """deploy_undo: rollcall_cd_deploy.py deploy --kind undo; notify: rollcall_cd_notify.role / .owner."""

    def deploy_undo(self, sha: str, reason: str) -> None:
        done = run_command([sys.executable, str(BIN / "rollcall_cd_deploy.py"), "deploy", "--sha", sha,
                            "--kind", "undo", "--reason", reason])
        if done.returncode != 0:
            raise ReadError(f"rollcall_cd_deploy.py deploy --kind undo exit {done.returncode}: "
                            f"{(done.stderr or done.stdout).strip()[-300:]}")

    def notify_role(self, role: str, kind: str, text: str) -> bool:
        import rollcall_cd_notify  # RollCall CD 1's; imported when first used

        return rollcall_cd_notify.role(role, kind, text)

    def notify_owner(self, text: str) -> bool:
        import rollcall_cd_notify

        return rollcall_cd_notify.owner(text)


class PrintedActions(Actions):
    """--dry-run: each action printed as one JSON line, nothing done."""

    def __init__(self, out=sys.stdout):
        self.out = out

    def _print(self, **action: str) -> None:
        print(json.dumps({"dry_run_action": action}), file=self.out)

    def deploy_undo(self, sha: str, reason: str) -> None:
        self._print(do="undo", sha=sha, reason=reason)

    def notify_role(self, role: str, kind: str, text: str) -> bool:
        self._print(do="role", role=role, kind=kind, text=text)
        return False

    def notify_owner(self, text: str) -> bool:
        self._print(do="owner", text=text)
        return False


# ---------------------------------------------------------------- deciding


@dataclass
class Decision:
    run: Run
    action: str  # green, ignored, before_cd, notify, undo, refuse
    why: str
    money: str = ""
    landers: list[str] = field(default_factory=list)
    target: str | None = None
    steps: list[dict] = field(default_factory=list)

    def record(self, now: dt.datetime) -> dict:
        return {"head": self.run.head, "event": self.run.event, "conclusion": self.run.conclusion,
                "url": self.run.url, "action": self.action, "why": self.why, "money": self.money,
                "landers": self.landers, "target": self.target, "decided_at": now.isoformat(),
                "steps": [dict(s, done=False) for s in self.steps], "done": not self.steps}


class Tick:
    def __init__(self, runs: Sequence[Run], repo: Repo, github: GitHub, check, verdict: dict,
                 records: Sequence[dict], live: str | None, now: dt.datetime, money_list_text: str | None = None):
        self.runs = sorted(runs, key=lambda r: r.created)
        self.repo, self.github, self.check = repo, github, check
        self.verdict, self.now, self.money_list_text = verdict, now, money_list_text
        self.shipped_records = sorted((r for r in records if r.get("result") in SHIPPED_RESULTS and r.get("sha")),
                                      key=lambda r: r["_ts"])
        self.live = live

    # -- what was deployed

    def shipped(self, head: str) -> str:
        """yes, wait (not deployed yet) or before (live before CD's first deploy)."""
        if not self.shipped_records:
            return "wait"
        first = self.shipped_records[0]
        if first.get("from_sha"):
            if self.repo.is_ancestor(head, first["from_sha"]):
                return "before"
        elif head != first["sha"] and self.repo.is_ancestor(head, first["sha"]):
            return "before"
        for record in self.shipped_records:
            if head == record["sha"]:
                return "yes"
            base = record.get("from_sha")
            if base and self.repo.is_ancestor(head, record["sha"]) and not self.repo.is_ancestor(head, base):
                return "yes"
        return "wait"

    # -- runs around a run

    def _earlier(self, run: Run) -> list[Run]:
        return [r for r in reversed(self.runs) if r.created < run.created and r.status == "completed"]

    def green_since(self, head: str, live: str) -> Run | None:
        """A green run on a commit after `head` that live holds: live already has a proven fix."""
        for r in reversed(self.runs):
            if r.conclusion == GREEN and r.head != head and self.repo.has(r.head) \
                    and self.repo.is_ancestor(head, r.head) and self.repo.is_ancestor(r.head, live):
                return r
        return None

    def last_green_before(self, run: Run) -> str | None:
        for r in self._earlier(run):
            if r.conclusion == GREEN and r.head != run.head and self.repo.has(r.head) \
                    and self.repo.is_ancestor(r.head, run.head):
                return r.head
        return None

    def new_commits(self, run: Run) -> tuple[list[tuple[str, str]], Run | None]:
        previous = next((r for r in self._earlier(run) if r.conclusion not in ("cancelled", "skipped", "")
                         and self.repo.has(r.head) and self.repo.is_ancestor(r.head, run.head)), None)
        commits = self.repo.commits(previous.head, run.head) if previous and previous.head != run.head else []
        return commits or self.repo.commits(None, run.head), previous

    def undo_planned(self, target: str) -> str | None:
        for run_id, record in self.verdict["runs"].items():
            if not record.get("done") and any(s["do"] == "undo" and s["sha"] == target and not s.get("done")
                                              for s in record["steps"]):
                return run_id
        return None

    # -- one run

    def decide(self, run: Run) -> Decision | None:
        """The decision for a finished run, or None while it has to wait (still running, not deployed yet)."""
        if run.status != "completed":
            return None
        if run.conclusion == GREEN:
            return Decision(run, "green", "ci passed")
        jobs = None
        if run.conclusion == "cancelled":
            jobs = self.github.jobs(run.id)
            if not any(job_started(j) for j in jobs):
                return Decision(run, "ignored", "cancelled before any job ran (replaced by a newer push, or by hand)")
        elif run.conclusion not in RED:
            return Decision(run, "ignored", f"conclusion {run.conclusion or 'none'}: not green, not red")
        if not self.repo.has(run.head):
            raise ReadError(f"commit {short(run.head)} of run {run.id} is not in {self.repo.path}; fetch it")
        shipped = self.shipped(run.head)
        if shipped == "before":
            return Decision(run, "before_cd", "its commit was live before continuous deploy's first deploy")
        if shipped == "wait":
            return None
        jobs = jobs if jobs is not None else self.github.jobs(run.id)
        failures = failures_of(jobs, self.github.failed_log(run.id))
        money = money_of(failures, run.head, self.check, self.money_list_text)
        commits, previous = self.new_commits(run)
        by_role: dict[str, list[tuple[str, str]]] = {}
        for sha, subject in commits:
            by_role.setdefault(lander_of(subject), []).append((sha, subject))

        action, why, target, outcome = "notify", f"red; money test: {money.state}", None, ""
        extra: dict[str, list[str]] = {}
        steps: list[dict] = []
        if money.state == "unknown":
            outcome = "money test unknown: no undo; RollCall asked to look"
            extra.setdefault(FALLBACK_ROLE, []).append(unknown_text(run, money))
        elif money.state == "yes":
            action, why, target, outcome, steps, extra = self.plan_money(run, money)
        decision = Decision(run, action, why, money=f"{money.state}: {money.why}", landers=sorted(by_role),
                            target=target)
        decision.steps = steps
        for role in sorted(set(by_role) | set(extra)):
            sections = [lander_text(run, failures, money, commits, by_role[role], outcome, previous, self.live)] \
                if role in by_role else []
            sections += extra.get(role, [])
            decision.steps.append({"do": "role", "role": role, "kind": "request", "text": "\n\n".join(sections)})
        if action == "refuse":
            decision.steps.append({"do": "owner", "text": owner_refusal_text(run)})
        return decision

    def plan_money(self, run: Run, money: Money):
        live = self.live
        if not live or not self.repo.has(live) or not self.repo.is_ancestor(run.head, live):
            return ("notify", f"money test red, but {short(run.head)} is not in the live commit {short(live)}",
                    None, f"no undo: live {short(live)} does not hold {short(run.head)}", [], {})
        fixed = self.green_since(run.head, live)
        if fixed is not None:
            return ("notify", f"money test red, but run {fixed.id} on {short(fixed.head)} (live holds it) is green",
                    None, f"no undo: run {fixed.id} on {short(fixed.head)}, which live holds, is green", [], {})
        target = self.last_green_before(run)
        if target is None:
            reason = f"no fully green commit before run {run.id} among the last {RUN_LIST_LIMIT} runs"
            return self._refusal(run, money, live, None, reason)
        migrations = [p for p in self.repo.changed(target, live) if p.startswith(self.repo.migrations_dir(live))]
        if migrations:
            reason = (f"migration between last fully green {short(target)} and live {short(live)}: "
                      + ", ".join(migrations[:5]))
            return self._refusal(run, money, live, target, reason)
        planned = self.undo_planned(target)
        if planned:
            return ("notify", f"money test red; undo to {short(target)} already planned by run {planned}", target,
                    f"undo to {short(target)} already asked for by run {planned}", [], {})
        undone = [sha for sha, _ in self.repo.commits(target, live)]
        reason = (f"money test red in ci run {run.id} ({run.url}) on {short(run.head)}: {money.why[:300]}; "
                  f"last fully green {short(target)}")
        steps = [{"do": "undone_shas", "shas": undone},
                 {"do": "undo", "sha": target, "from_sha": live, "reason": reason}]
        outcome = (f"undo: {short(target)} (last fully green) goes back live over {short(live)}; the {len(undone)} "
                   f"commits taken off won't redeploy; the next land deploys as usual")
        self.live = target
        return "undo", f"money test red; undo to {short(target)}", target, outcome, steps, {}

    def _refusal(self, run: Run, money: Money, live: str, target: str | None, reason: str):
        record = {"ts": self.now.isoformat(), "kind": "refusal", "sha": target, "from_sha": live,
                  "reason": f"run {run.id}: {reason}", "result": "refused", "unit": None}
        steps = [{"do": "log", "record": record}]
        extra = {FALLBACK_ROLE: [refusal_text(run, money, live, target, reason)]}
        return ("refuse", f"money test red; undo refused: {reason}", target,
                f"undo refused ({reason}); live stays; RollCall and the owner told", steps, extra)


# ---------------------------------------------------------------- messages (AI readers; the owner's is plain)


def lander_text(run: Run, failures: Sequence[Failure], money: Money, commits: Sequence[tuple[str, str]],
                yours: Sequence[tuple[str, str]], outcome: str, previous: Run | None, live: str | None) -> str:
    lines = [f"rollcall ci red on master after deploy: run {run.id} ({run.event}, {run.conclusion}) head {short(run.head)}",
             f"url {run.url}",
             f"commits this run is first to check: {len(commits)}; yours:"]
    lines += [f"  {short(sha)} {subject[:140]}" for sha, subject in yours]
    tests: list[str] = []
    for failure in failures:
        command = f" ({failure.command[:120]})" if failure.command else ""
        lines.append(f"failing: {failure.job} / {failure.step}{command}{' [stopped]' if failure.stopped else ''}")
        tests += [t for t in failure.tests if t not in tests]
    if tests:
        shown = tests[:MAX_TESTS_IN_MESSAGE]
        lines.append(f"tests ({len(shown)} of {len(tests)}): " + " ".join(shown))
    lines.append(f"money test: {money.state}: {money.why[:400]}")
    if outcome:
        lines.append(outcome)
    if previous is not None and previous.conclusion in RED:
        lines.append(f"note: previous master run {previous.id} ({short(previous.head)}) was red too")
    lines.append(f"live {short(live)}; next: fix forward (land a fix; continuous deploy ships it)")
    return "\n".join(lines)


def unknown_text(run: Run, money: Money) -> str:
    return (f"rollcall cd: money test status unknown for red run {run.id} head {short(run.head)}: {money.why[:400]}\n"
            f"url {run.url}\nno undo done; look and decide (hand undo or fix forward)")


def refusal_text(run: Run, money: Money, live: str, target: str | None, reason: str) -> str:
    return (f"rollcall cd: undo refused, run {run.id} head {short(run.head)}: money test red ({money.why[:300]})\n"
            f"url {run.url}\nlive {short(live)}; last fully green {short(target)}; {reason}\n"
            f"nothing undone; live stays. decide: hand undo (with alembic downgrade) or fix forward")


def owner_refusal_text(run: Run) -> str:
    return ("RollCall: a money test failed on the live app after a deploy, and it was not put back automatically, "
            "because the database changed since the last good version (or no good version was found). The live "
            f"version stays up, and RollCall has been asked to decide. Run: {run.url}")


# ---------------------------------------------------------------- doing


def execute(run_id: str, record: dict, store: Store, actions: Actions, verdict: dict, now: dt.datetime) -> list[str]:
    """Do the record's steps not done yet, saving after each; the errors of steps that failed."""
    errors = []
    for step in record["steps"]:
        if step.get("done"):
            continue
        try:
            if step["do"] == "undone_shas":
                store.add_undone(step["shas"])
            elif step["do"] == "undo":
                actions.deploy_undo(step["sha"], step["reason"])
                verdict["pending_undo"] = {"sha": step["sha"], "from_sha": step["from_sha"], "at": now.isoformat(),
                                           "run": run_id}
            elif step["do"] == "log":
                store.append_record(step["record"])
            elif step["do"] == "role":  # False: not delivered, kept in rollcall_cd_notify's outbox; not resent
                step["delivered"] = bool(actions.notify_role(step["role"], step["kind"], step["text"]))
            elif step["do"] == "owner":
                step["delivered"] = bool(actions.notify_owner(step["text"]))
            else:
                raise ReadError(f"unknown step {step['do']!r}")
        except Exception as err:  # noqa: BLE001 -- any failure of one step is recorded and retried, never success
            step["tries"] = step.get("tries", 0) + 1
            step["error"] = f"{err.__class__.__name__}: {str(err)[:300]}"
            errors.append(f"run {run_id} step {step['do']}: {step['error']}")
            if step["do"] == "undo" and step["tries"] == 1:
                record["steps"].append({"do": "role", "role": FALLBACK_ROLE, "kind": "request", "done": False,
                                        "text": f"rollcall cd: undo to {short(step['sha'])} for run {run_id} failed: "
                                                f"{step['error']}\nretried every tick; live is still {short(step['from_sha'])}"})
            store.save_verdict(verdict)
            continue
        step["done"] = True
        step["at"] = now.isoformat()
        store.save_verdict(verdict)
    record["done"] = all(s.get("done") for s in record["steps"])
    store.save_verdict(verdict)
    return errors


def effective_live(state: dict, records: Sequence[dict], verdict: dict) -> str | None:
    """state.json's deployed_sha, or the undo this script asked for while no deploy record has come in since."""
    pending = verdict.get("pending_undo")
    if pending:
        at = parse_ts(pending["at"])
        if any(r["_ts"] >= at for r in records):
            verdict["pending_undo"] = None
        else:
            return pending["sha"]
    return state.get("deployed_sha")


def tick(github: GitHub, repo: Repo, store: Store, actions: Actions, check, *, runs_limit: int | None = None,
         assume_deployed: bool = False, money_list_text: str | None = None, now: dt.datetime | None = None,
         out=sys.stdout) -> int:
    now = now or utcnow()
    runs = github.runs()
    window = runs[:runs_limit] if runs_limit else runs
    verdict = store.verdict()
    state, records = store.state(), store.records()
    if assume_deployed:
        if not window:
            raise VerdictError("--assume-deployed: no runs to assume deployed")
        live = window[0].head
        base = repo.parent(window[-1].head)
        records = [{"kind": "deploy", "sha": live, "from_sha": base, "result": "ok", "_ts": now}]
    else:
        pending = verdict.get("pending_undo")
        live = effective_live(state, records, verdict)
        if verdict.get("pending_undo") != pending:
            store.save_verdict(verdict)
    errors: list[str] = []
    for run_id, record in list(verdict["runs"].items()):  # unfinished steps first, even of runs out of the list
        if not record.get("done"):
            errors += execute(run_id, record, store, actions, verdict, now)
    current = Tick(window, repo, github, check, verdict, records, live, now, money_list_text)
    waiting = decided = 0
    for run in current.runs:
        run_id = str(run.id)
        if run_id in verdict["runs"]:
            continue
        try:
            decision = current.decide(run)
        except ReadError as err:
            errors.append(f"run {run.id}: {err}")
            continue
        if decision is None:
            waiting += 1
            continue
        decided += 1
        record = decision.record(now)
        verdict["runs"][run_id] = record
        store.save_verdict(verdict)
        errors += execute(run_id, record, store, actions, verdict, now)
        print(json.dumps({"run": run.id, "head": short(run.head), "event": run.event, "conclusion": run.conclusion,
                          "action": decision.action, "why": decision.why, "money": decision.money,
                          "landers": decision.landers, "target": short(decision.target) if decision.target else None,
                          "steps": [s["do"] + ("" if s.get("done") else " (not done)") for s in record["steps"]]}),
              file=out)
    print(json.dumps({"summary": {"runs": len(window), "decided": decided, "waiting": waiting, "live": short(live),
                                  "dry_run": store.dry_run, "errors": errors}}), file=out)
    return 1 if errors else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decide, once per ci run on RollCall's master: notify, undo or refuse.")
    parser.add_argument("--repo", type=Path, required=True, help="a rollcall checkout (read-only; holds the run heads)")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR, help=f"default {DEFAULT_STATE_DIR}")
    parser.add_argument("--gh-repo", default=GH_REPO)
    parser.add_argument("--fetch", action="store_true", help="git fetch origin in --repo first")
    parser.add_argument("--dry-run", action="store_true", help="write nothing, send nothing; print each action")
    parser.add_argument("--assume-deployed", action="store_true",
                        help="with --dry-run: take the newest run's head as live and every run in the window as deployed")
    parser.add_argument("--runs", type=int, help="only the newest N runs")
    parser.add_argument("--money-list", type=Path, help="read the money list from this file, not from each run's head")
    args = parser.parse_args(argv)
    if args.assume_deployed and not args.dry_run:
        parser.error("--assume-deployed needs --dry-run")
    repo = Repo(args.repo.expanduser())
    if not (repo.path / ".git").exists():
        print(f"rollcall_cd_verdict: {repo.path} is not a git checkout", file=sys.stderr)
        return 2
    try:
        if args.fetch:
            repo.out("fetch", "--quiet", "origin")
        check = rollcall_cd_money.MoneyCheck(repo.path)
        store = Store(Path(args.state_dir), dry_run=args.dry_run)
        actions = PrintedActions() if args.dry_run else Actions()
        text = args.money_list.read_text() if args.money_list else None
        return tick(GitHub(args.gh_repo), repo, store, actions, check, runs_limit=args.runs,
                    assume_deployed=args.assume_deployed, money_list_text=text)
    except (VerdictError, ReadError) as err:
        print(f"rollcall_cd_verdict: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
