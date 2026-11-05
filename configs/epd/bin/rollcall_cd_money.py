#!/usr/bin/env python3
"""rollcall_cd_money: which failing RollCall ci tests are money tests, by RollCall's scripts/money-tests.toml.

One job: given a commit, the backend test ids and the qa step that failed in its ci run, say which are on the
money list and why. rollcall_cd_verdict.py and `wt deploy`'s `ci.critical_check` (`rollcall_cd_money.py critical`)
ask it after a red run on a deployed commit. No model; python3 stdlib only; reads the rollcall repository and
never changes it.

The list (RollCall owns it) has two parts:
  [backend] modules  repo paths of app modules; `*` and `?` stay inside one folder, `**` crosses folders (the
                     selector's glob_to_regex); a pattern that names a folder covers every module inside it
  [qa] walks         a failing step of ci.yml's qa job is money when its command runs qa/<walk>.py or its step
                     name contains the entry, whatever the case

How a failing backend test is matched (hypothesis H-CD-MONEY-MATCH-1, Systems #98, 2026-11-05):
  Wrong with the obvious way: rollcall's import graph (scripts/backend_import_graph.py, the one ci.yml's push
  selection uses) answers "which tests can reach this module", and through conftest.py and imports inside
  function bodies every test can: at ca76f3c1 all 322 backend test files reach a money module (317 without the
  opaque ones), so every red backend run would undo.
  Change: the same graph, built by its own build_graph with every module of the tests package bounded to no
  unseen reach (its [[dynamic_imports]] mechanism, within = ()), so a test reaches only what its source spells
  out. A failing test is money when its file, or a tests-package module it imports (followed on through the
  tests package, conftest.py left out because pytest loads it for every test), names a money module.
  Expected and measured at ca76f3c1: 70 of 322 test files are money (60 directly, 10 through another test
  module); test_entry.py (real failure, run 36080431059) is money; test_dev_seed_clone.py (run 42004004262),
  test_select_tests.py and the five opaque test files are not. Wrong if an orders, entry or margin test reads
  as not money, or if more than 40% of the test files read as money.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

LIST_PATH = "scripts/money-tests.toml"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
TESTS_PACKAGE = "tests"
CONFTEST_LEAF = "conftest"
GH_REPO = "shine2lay/rollcall"
BACKEND_JOB = "backend"
QA_JOB = "qa"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ?")
TEST_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+)")
STEP_ERROR = "##[error]Process completed with exit code"


class MoneyListError(ValueError):
    """The money list is missing or does not say what this module needs: no safe answer is possible."""


@dataclass(frozen=True)
class MoneyList:
    modules: tuple[str, ...]
    walks: tuple[str, ...]


def _rel_list_path(repo: Path, list_path: str) -> str:
    p = Path(list_path)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            return p.as_posix().lstrip("/")
    return p.as_posix().lstrip("./") or LIST_PATH


def parse_money_list(text: str, list_path: str = LIST_PATH) -> MoneyList:
    """The list from the text of scripts/money-tests.toml; MoneyListError when it is malformed."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise MoneyListError(f"{list_path} is not TOML: {err}") from None
    if data.get("version") != 1:
        raise MoneyListError(f"{list_path}: version must be 1, found {data.get('version')!r}")
    modules = (data.get("backend") or {}).get("modules")
    walks = (data.get("qa") or {}).get("walks")
    for where, value in (("[backend] modules", modules), ("[qa] walks", walks)):
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise MoneyListError(f"{list_path}: {where} must be a list of non-empty strings")
    return MoneyList(tuple(modules), tuple(walks))


# ---------------------------------------------------------------- rollcall's own selector, loaded from its checkout


@dataclass(frozen=True)
class RollcallSelector:
    """rollcall's scripts/backend_import_graph.py and scripts/select_tests.py, as modules."""

    graph: ModuleType
    select: ModuleType


def _load(spec: importlib.machinery.ModuleSpec) -> ModuleType:
    """Each caller names its module literally, so temper-ai's test selector sees no dynamic import here."""
    if not Path(spec.origin).is_file():
        raise MoneyListError(f"cannot load {spec.origin}: no such file (is --repo a rollcall checkout?)")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_rollcall_selector(scripts_dir: Path) -> RollcallSelector:
    """Load the selector under private names, so the money check reads imports with the graph ci.yml selects by
    (never a copy of it), and leave this process's sys.path and its own select_tests/backend_import_graph alone."""
    saved_path = list(sys.path)
    saved = {n: sys.modules.get(n) for n in ("backend_import_graph", "select_tests")}
    try:
        graph = _load(importlib.util.spec_from_file_location("rollcall_cd_backend_import_graph",
                                                             scripts_dir / "backend_import_graph.py"))
        sys.modules["backend_import_graph"] = graph  # select_tests imports it by that name
        select = _load(importlib.util.spec_from_file_location("rollcall_cd_select_tests",
                                                              scripts_dir / "select_tests.py"))
    finally:
        sys.path[:] = saved_path
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return RollcallSelector(graph, select)


# ---------------------------------------------------------------- answers


@dataclass
class BackendAnswer:
    """money: test id -> the money modules it imports; plain: not money; unknown: test id -> why not known."""

    money: dict[str, list[str]] = field(default_factory=dict)
    plain: list[str] = field(default_factory=list)
    unknown: dict[str, str] = field(default_factory=dict)


def _in_tests_package(name: str) -> bool:
    return name == TESTS_PACKAGE or name.startswith(TESTS_PACKAGE + ".")


def _parents(path: str) -> Iterable[str]:
    parts = path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        yield "/".join(parts[:i])


class MoneyCheck:
    """Answers about one rollcall repository. Every graph is built once per commit."""

    def __init__(self, repo: Path, selector: RollcallSelector | None = None):
        self.repo = Path(repo)
        self._selector = selector
        self._graphs: dict[str, object] = {}

    @property
    def selector(self) -> RollcallSelector:
        if self._selector is None:
            self._selector = load_rollcall_selector(self.repo / "scripts")
        return self._selector

    def _files(self, head: str, prefix: str = "") -> set[str]:
        try:
            return self.selector.select.Git(self.repo).files(head, prefix)
        except self.selector.select.SelectionError as err:
            raise MoneyListError(str(err)) from None

    def _read(self, head: str, paths: Sequence[str]) -> dict[str, str]:
        try:
            return self.selector.select.Git(self.repo).read(head, paths)
        except self.selector.select.SelectionError as err:
            raise MoneyListError(str(err)) from None

    def read_list(self, head: str, list_path: str = LIST_PATH) -> MoneyList:
        """The list as it is at `head`."""
        rel = _rel_list_path(self.repo, list_path)
        prefix = f"{rel.rpartition('/')[0]}/" if "/" in rel else ""
        if rel not in self._files(head, prefix):
            raise MoneyListError(f"no {rel} at {head[:12]}")
        return parse_money_list(self._read(head, [rel])[rel], list_path=rel)

    def _graph(self, head: str) -> object:
        """The selector's graph at `head`, every tests-package module bounded to what its source spells out."""
        if head not in self._graphs:
            graph_module = self.selector.graph
            paths = sorted(p for p in self._files(head, "backend/") if p.endswith(".py"))
            names = (graph_module.module_name(p) for p in paths)
            bounds = {name: () for name in names if name and _in_tests_package(name)}
            self._graphs[head] = graph_module.build_graph(self._read(head, paths), bounds)
        return self._graphs[head]

    def money_modules(self, head: str, money: MoneyList) -> set[str]:
        graph = self._graph(head)
        patterns = [self.selector.select.glob_to_regex(p) for p in money.modules]
        return {name for name, path in graph.modules.items()
                if any(p.fullmatch(path) or any(p.fullmatch(d) for d in _parents(path)) for p in patterns)}

    def imports_of(self, head: str, test_module: str) -> set[str]:
        """App modules a test module names, itself or through the tests-package modules it imports."""
        graph = self._graph(head)
        seen: set[str] = set()
        stack = [test_module]
        found: set[str] = set()
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            for reached in graph.edges.get(name, ()):
                if _in_tests_package(reached):
                    if reached.rpartition(".")[2] != CONFTEST_LEAF:
                        stack.append(reached)
                else:
                    found.add(reached)
        return found

    def backend(self, head: str, money: MoneyList, test_ids: Sequence[str]) -> BackendAnswer:
        """Which of the failing backend test ids (backend/tests/x.py::name) are money tests at `head`."""
        answer = BackendAnswer()
        graph = self._graph(head)
        listed = self.money_modules(head, money)
        for test_id in test_ids:
            path = test_id.split("::", 1)[0]
            name = self.selector.graph.module_name(path)
            if name is None or name not in graph.modules:
                answer.unknown[test_id] = f"{path} is not a backend module at {head[:12]}"
                continue
            hits = sorted(self.imports_of(head, name) & listed)
            if hits:
                answer.money[test_id] = hits
            else:
                answer.plain.append(test_id)
        return answer

    @staticmethod
    def walk(money: MoneyList, step_name: str, command: str) -> str | None:
        """The money walk a failing qa step runs, or None."""
        for walk in money.walks:
            if f"qa/{walk}.py" in command or walk.lower() in step_name.lower():
                return walk
        return None

    def unmatched(self, head: str, money: MoneyList) -> list[str]:
        """Entries of the list that name nothing at `head`: a module pattern matching no module, a walk with no
        qa/<walk>.py and no ci.yml step name holding it. The list still works; the entry is dead weight."""
        out = []
        graph = self._graph(head)
        for pattern in money.modules:
            regex = self.selector.select.glob_to_regex(pattern)
            if not any(regex.fullmatch(p) or any(regex.fullmatch(d) for d in _parents(p)) for p in graph.modules.values()):
                out.append(f"[backend] {pattern!r} names no module at {head[:12]}")
        files = self._files(head)
        ci = self._read(head, [CI_WORKFLOW_PATH])[CI_WORKFLOW_PATH] if CI_WORKFLOW_PATH in files else ""
        step_names = [m.group(1).lower() for m in re.finditer(r"^\s*- name:\s*(.+)$", ci, re.MULTILINE)]
        for walk in money.walks:
            if f"qa/{walk}.py" not in files and not any(walk.lower() in s for s in step_names):
                out.append(f"[qa] {walk!r} names no qa/{walk}.py and no ci.yml step at {head[:12]}")
        return out


# ---------------------------------------------------------------- ci run log parsing and money classification


def run_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False)


def gh_jobs(
    run_id: int | str,
    github_repo: str = GH_REPO,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_command,
) -> list[dict]:
    done = runner(["gh", "run", "view", str(run_id), "--json", "jobs", "--repo", github_repo])
    if done.returncode != 0:
        raise MoneyListError(f"gh run view {run_id} --json jobs failed: {(done.stderr or done.stdout).strip()[:300]}")
    try:
        jobs = json.loads(done.stdout).get("jobs")
    except (json.JSONDecodeError, AttributeError) as err:
        raise MoneyListError(f"gh run view {run_id} --json jobs: bad JSON: {err}") from None
    if not isinstance(jobs, list):
        raise MoneyListError(f"gh run view {run_id} --json jobs: missing jobs list")
    return jobs


def gh_failed_log(
    run_id: int | str,
    github_repo: str = GH_REPO,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_command,
) -> str:
    """The failed steps' logs; "" when GitHub has none (jobs that never ran a step)."""
    done = runner(["gh", "run", "view", str(run_id), "--log-failed", "--repo", github_repo])
    if done.returncode != 0:
        if "log not found" in (done.stderr or ""):
            return ""
        raise MoneyListError(
            f"gh run view {run_id} --log-failed failed: {(done.stderr or done.stdout).strip()[:300]}"
        )
    return done.stdout


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


@dataclass
class Money:
    state: str  # yes, no, unknown
    why: str
    ids: list[str] = field(default_factory=list)


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


def money_of(
    failures: Sequence[Failure],
    head: str,
    check,
    money_list_text: str | None = None,
    *,
    list_path: str = LIST_PATH,
) -> Money:
    """Whether the run failed in a money test. `check` is a rollcall_cd_money.MoneyCheck."""
    try:
        if money_list_text is not None:
            listed = parse_money_list(money_list_text, list_path=list_path)
        elif list_path == LIST_PATH:
            listed = check.read_list(head)
        else:
            listed = check.read_list(head, list_path)
    except MoneyListError as err:
        return Money("unknown", str(err))
    yes, unknown, plain = [], [], []
    for failure in failures:
        if failure.job == BACKEND_JOB:
            if failure.tests:
                try:
                    answer = check.backend(head, listed, failure.tests)
                except MoneyListError as err:
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


def _resolve_list_input(repo: Path, head: str, list_path: str, check) -> tuple[str | None, str]:
    rel = _rel_list_path(repo, list_path)
    candidate = Path(list_path).expanduser()
    if candidate.is_absolute() and candidate.is_file():
        prefix = f"{rel.rpartition('/')[0]}/" if "/" in rel else ""
        try:
            in_head = rel in check._files(head, prefix)
        except Exception:  # noqa: BLE001
            in_head = False
        if not in_head:
            return candidate.read_text(), rel
    return None, rel


def critical_of(
    repo: Path | str,
    run_id: int | str,
    head: str,
    *,
    list_path: str = LIST_PATH,
    github_repo: str = GH_REPO,
    check: MoneyCheck | None = None,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_command,
    jobs: Sequence[dict] | None = None,
    log_text: str | None = None,
    money_list_text: str | None = None,
) -> dict[str, object]:
    """Evaluate a red CI run and return {"critical": "yes"|"no"|"unknown", "tests": [...], "why": "..."}."""
    try:
        repo_path = Path(repo).expanduser()
        active_check = check or MoneyCheck(repo_path)
        if money_list_text is None:
            money_list_text, rel_list = _resolve_list_input(repo_path, head, list_path, active_check)
        else:
            rel_list = _rel_list_path(repo_path, list_path)
        run_jobs_list = list(jobs) if jobs is not None else gh_jobs(run_id, github_repo, runner)
        if not run_jobs_list:
            return {"critical": "unknown", "tests": [], "why": f"run {run_id}: no jobs in run"}
        raw_log = log_text if log_text is not None else gh_failed_log(run_id, github_repo, runner)
        failures = failures_of(run_jobs_list, raw_log)
        if not failures:
            return {"critical": "unknown", "tests": [], "why": f"run {run_id}: no failed or stopped job"}
        money = money_of(failures, head, active_check, money_list_text, list_path=rel_list)
        if money.state == "no" and not any(job_started(j) for j in run_jobs_list):
            why = f"{failures[0].job} / {failures[0].step}: no step ran"
            return {"critical": "unknown", "tests": [why], "why": why}
        return {"critical": money.state, "tests": list(money.ids), "why": money.why}
    except Exception as err:  # noqa: BLE001 -- CLI contract: any unhandled error returns unknown and exits 0
        return {"critical": "unknown", "tests": [], "why": str(err)}


def _critical_main(
    argv: Sequence[str],
    *,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_command,
    out=sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(
        prog="rollcall_cd_money.py critical",
        description="Check whether a red GitHub Actions run failed a critical RollCall money test.",
    )
    parser.add_argument("--repo", required=True, help="a rollcall git checkout (read-only)")
    parser.add_argument("--run", required=True, dest="run_id", help="GitHub Actions workflow run id")
    parser.add_argument("--head", required=True, help="commit sha or ref to evaluate money-tests.toml at")
    parser.add_argument("--list", default=LIST_PATH, dest="list_path", help=f"default {LIST_PATH}")
    parser.add_argument("--github", default=GH_REPO, dest="github_repo", help=f"default {GH_REPO}")
    args = parser.parse_args(list(argv))
    result = critical_of(
        args.repo,
        args.run_id,
        args.head,
        list_path=args.list_path,
        github_repo=args.github_repo,
        runner=runner,
    )
    print(json.dumps(result, sort_keys=True), file=out)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """By hand: rollcall_cd_money.py REPO HEAD [TEST_ID ...] or rollcall_cd_money.py critical ..."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "critical":
        return _critical_main(args[1:])
    if len(args) < 2:
        print("usage: rollcall_cd_money.py REPO HEAD [TEST_ID ...]\n"
              "       rollcall_cd_money.py critical --repo DIR --run ID --head SHA [--list FILE] [--github REPO]",
              file=sys.stderr)
        return 2
    repo, head, test_ids = Path(args[0]), args[1], args[2:]
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", head + "^{commit}"],
                          capture_output=True, text=True, check=True).stdout.strip()
    check = MoneyCheck(repo)
    try:
        money = check.read_list(head)
    except MoneyListError as err:
        print(f"rollcall_cd_money: {err}", file=sys.stderr)
        return 2
    print(f"money modules at {head[:12]}: {len(check.money_modules(head, money))}")
    for line in check.unmatched(head, money):
        print(f"  unmatched: {line}")
    answer = check.backend(head, money, test_ids)
    for test_id, hits in answer.money.items():
        print(f"money    {test_id}  ({', '.join(hits[:3])})")
    for test_id in answer.plain:
        print(f"plain    {test_id}")
    for test_id, why in answer.unknown.items():
        print(f"unknown  {test_id}  ({why})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
