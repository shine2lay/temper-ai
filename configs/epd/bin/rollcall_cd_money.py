#!/usr/bin/env python3
"""rollcall_cd_money: which failing RollCall ci tests are money tests, by RollCall's scripts/money-tests.toml.

One job: given a commit, the backend test ids and the qa step that failed in its ci run, say which are on the
money list and why. rollcall_cd_verdict.py asks it after a red run on a deployed commit. No model; python3
stdlib only; reads the rollcall repository and never changes it.

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

import importlib.util
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

LIST_PATH = "scripts/money-tests.toml"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
TESTS_PACKAGE = "tests"
CONFTEST_LEAF = "conftest"


class MoneyListError(ValueError):
    """The money list is missing or does not say what this module needs: no safe answer is possible."""


@dataclass(frozen=True)
class MoneyList:
    modules: tuple[str, ...]
    walks: tuple[str, ...]


def parse_money_list(text: str) -> MoneyList:
    """The list from the text of scripts/money-tests.toml; MoneyListError when it is malformed."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise MoneyListError(f"{LIST_PATH} is not TOML: {err}") from None
    if data.get("version") != 1:
        raise MoneyListError(f"{LIST_PATH}: version must be 1, found {data.get('version')!r}")
    modules = (data.get("backend") or {}).get("modules")
    walks = (data.get("qa") or {}).get("walks")
    for where, value in (("[backend] modules", modules), ("[qa] walks", walks)):
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise MoneyListError(f"{LIST_PATH}: {where} must be a list of non-empty strings")
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

    def read_list(self, head: str) -> MoneyList:
        """The list as it is at `head`."""
        if LIST_PATH not in self._files(head, "scripts/"):
            raise MoneyListError(f"no {LIST_PATH} at {head[:12]}")
        return parse_money_list(self._read(head, [LIST_PATH])[LIST_PATH])

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


def main(argv: Sequence[str] | None = None) -> int:
    """By hand: rollcall_cd_money.py REPO HEAD [TEST_ID ...] prints the money modules and each test's answer."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: rollcall_cd_money.py REPO HEAD [TEST_ID ...]", file=sys.stderr)
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
