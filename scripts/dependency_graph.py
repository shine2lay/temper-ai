#!/usr/bin/env python3
"""Which tracked files of temper-ai depend on which: the map scripts/select_tests.py follows from a
changed file to the tests that can notice the change.

One job: the repository's files and their text -> for every file, the files that depend on it. Only
files that run or load others can depend on anything: Python, shell scripts, and the YAML under
configs/ (a workflow names its stages and agents, an agent its script and prompt). Data (JSON, text,
templates) is depended on but depends on nothing: a recorded page that mentions build.py does not run it.
A file depends on another when it imports it, runs it, or names it:

  imports        absolute and relative; importing a.b.c also runs a/__init__.py and a/b/__init__.py.
                 A name that is no module path of the repository (a script folder put on sys.path,
                 `importlib.import_module("kb_refresh")`) matches the .py files whose dotted path ends
                 with it, when at most FANOUT files do.
  module names   "temper_ai.x.y" in code or config: monkeypatch targets, a config's module line.
  file names     a literal holding a repository path, a basename with its extension, or the stem of a
                 non-Python file (workflow and agent names), when at most FANOUT files match. A test
                 file is depended on only by what imports it: naming one does not run it.
  folders        a literal naming a subfolder ("configs/agents", "docs/reference"), in a test or a
                 test helper: it reads what is in that folder. `ROOT / "configs" / "agents"`,
                 os.path.join(...) and the fixed start of an f-string count as one literal.
  conftest.py    a test depends on every conftest.py and __init__.py in its folder and above.

Hubs are where following stops (scripts/test-selection.toml names them: tests/conftest.py and
tests/pgtier.py). The root conftest imports most of temper_ai for its autouse fixtures, so through it
every module would look like a dependency of every test. A change to a hub itself runs the whole suite.

Reading a file's references (extract_references) is separate from resolving them against one tree
(RepoIndex), so a replay over many commits reads each file version once.
Stdlib only: it runs before `uv sync` and in a bare CI job.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

TEST_ROOT = "tests"
CONFIG_ROOT = "configs"
# Folders whose files are never read for references: nothing in them runs in the Python tests.
UNREAD_FOLDERS = ("frontend/", "docs/")
ENGINE_PACKAGES = {"temper_ai"}
FANOUT = 8  # a name matching more files than this says nothing about which one is meant
MIN_STEM = 6  # shorter bare names ("config", "run") are too common to mean one file
# Calls whose first argument is a module name: importlib.import_module("kb_refresh"), runpy.run_module(...)
IMPORT_CALLS = {"import_module", "__import__", "run_module", "find_spec"}
TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*[A-Za-z0-9_]")
# A config's YAML: keys whose values are prose for a model or a reader, and keys that load another config
PROSE_KEYS = {"system_prompt", "task_template", "description", "why", "about"}
LOAD_KEYS = {"agent", "ref", "workflow"}
YAML_ENTRY = re.compile(r"^(\s*(?:-\s+)?)([A-Za-z_][\w-]*):(?:\s+(.*)|\s*)$")
BLOCK_SCALAR = re.compile(r"[|>][-+]?\d*")
DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")
MODULE_PIECES = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


def module_name(path: str) -> str | None:
    """The dotted name of a .py file's module ("temper_ai/x/__init__.py" -> "temper_ai.x")."""
    if not path.endswith(".py"):
        return None
    name = path[:-3].replace("/", ".")
    return name[: -len(".__init__")] if name.endswith(".__init__") else name


def is_test_file(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return (path.startswith(TEST_ROOT + "/") and base.endswith(".py")
            and (base.startswith("test_") or base.endswith("_test.py")))


def is_config(path: str) -> bool:
    return path.startswith(CONFIG_ROOT + "/") and path.endswith((".yaml", ".yml"))


def is_engine(path: str) -> bool:
    return path.split("/", 1)[0] in ENGINE_PACKAGES


def _nearest(matches: Iterable[str], user: str) -> set[str]:
    """The matches in `user`'s folder or below, else its parent's, ...; none at the repository root."""
    folder = user.rpartition("/")[0]
    while folder:
        near = {m for m in matches if m.startswith(folder + "/")}
        if near:
            return near
        folder = folder.rpartition("/")[0]
    return set()


def _clean_path(literal: str) -> str:
    candidate = literal.strip().rstrip("/")
    while candidate.startswith(("./", "../")):
        candidate = candidate.split("/", 1)[1]
    return candidate


def should_read(path: str) -> bool:
    """Whether `path` runs or loads other files: Python, shell, or YAML under configs/."""
    if path.startswith(UNREAD_FOLDERS):
        return False
    if path.endswith((".py", ".sh")):
        return True
    return path.startswith(CONFIG_ROOT + "/") and path.endswith((".yaml", ".yml"))


# ---------------------------------------------------------------- reading one file


@dataclass(frozen=True)
class Import:
    module: str  # "" for `from . import x`
    level: int  # 0 absolute, 1 for `from .`, 2 for `from ..`
    names: tuple[str, ...]  # what `from module import a, b` takes; empty for `import module`


@dataclass(frozen=True)
class References:
    """What one file's text names, before it is matched against a tree."""

    imports: tuple[Import, ...] = ()
    literals: frozenset[str] = frozenset()  # strings and joined path literals
    imported_by_name: frozenset[str] = frozenset()  # import_module("x") and the like


def extract_references(path: str, text: str) -> References:
    """What `path` names. Python is parsed (a file that does not parse names nothing it imports, only
    its words); a config's YAML is read without its comments and prose; anything else is scanned for
    path-like and dotted words."""
    if path.endswith((".yaml", ".yml")):
        return References(literals=frozenset(config_words(text)))
    if not path.endswith(".py"):
        return References(literals=frozenset(TOKEN.findall(text)))
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return References(literals=frozenset(TOKEN.findall(text)))
    imports: list[Import] = []
    literals: set[str] = set()
    by_name: set[str] = set()
    inner_joins: set[int] = set()  # BinOp nodes that are the left side of a longer constant path join
    # one breadth-first walk: a `/` chain's outer node is met before the inner ones it marks
    for node in ast.walk(tree):
        kind = type(node)
        if kind is ast.Constant:
            if type(node.value) is str:  # type: ignore[attr-defined]
                value = node.value.strip()  # type: ignore[attr-defined]
                if value and "\n" not in value and len(value) <= 300:
                    literals.add(value)
        elif kind is ast.Import:
            imports.extend(Import(alias.name, 0, ()) for alias in node.names)  # type: ignore[attr-defined]
        elif kind is ast.ImportFrom:
            imports.append(Import(node.module or "", node.level,  # type: ignore[attr-defined]
                                  tuple(a.name for a in node.names)))  # type: ignore[attr-defined]
        elif kind is ast.BinOp:
            if type(node.op) is ast.Div and _is_text(node.right):  # type: ignore[attr-defined]
                if type(node.left) is ast.BinOp:  # type: ignore[attr-defined]
                    inner_joins.add(id(node.left))  # type: ignore[attr-defined]
                if id(node) not in inner_joins:
                    joined = _joined_path(node)  # type: ignore[arg-type]
                    if joined:
                        literals.add(joined)
        elif kind is ast.Call:
            name = _call_name(node.func)
            if name in IMPORT_CALLS and node.args and _is_text(node.args[0]):
                by_name.add(node.args[0].value.strip())  # type: ignore[attr-defined]
            if name == "join" and len(node.args) > 1:
                parts = [a.value for a in node.args if _is_text(a)]
                if len(parts) > 1:
                    literals.add("/".join(p.strip("/") for p in parts))
        elif kind is ast.JoinedStr:
            start = _fixed_start(node)  # type: ignore[arg-type]
            if "/" in start:
                literals.add(start.rsplit("/", 1)[0])
    return References(tuple(imports), frozenset(literals), frozenset(by_name))


def config_words(text: str) -> set[str]:
    """The words of a config's YAML that can name another file. Comments and prose (prompts,
    descriptions) are left out: a prompt that mentions docs/testing.md does not load it. A bare word
    counts only as the value of a key that loads another config (`agent: task_verify`); elsewhere a
    word counts when it holds a '/' or a '.' (a path, a file name, a module)."""
    words: set[str] = set()
    skip_deeper_than: int | None = None  # inside a prose block scalar, indented past this
    for line in text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if skip_deeper_than is not None:
            if not stripped or indent > skip_deeper_than:
                continue
            skip_deeper_than = None
        if not stripped or stripped.startswith("#"):
            continue
        code = line.split(" #", 1)[0]
        entry = YAML_ENTRY.match(code)
        if entry:
            key, value = entry.group(2), (entry.group(3) or "").strip()
            if key in PROSE_KEYS:
                if BLOCK_SCALAR.fullmatch(value):
                    skip_deeper_than = len(entry.group(1))
                continue
            if key in LOAD_KEYS:
                words.update(TOKEN.findall(value))
                continue
        words.update(w for w in TOKEN.findall(code) if "/" in w or "." in w)
    return words


def _is_text(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _joined_path(node: ast.BinOp) -> str:
    """`ROOT / "configs" / "agents"` -> "configs/agents": the constant parts at the end of a `/` chain."""
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div) and _is_text(current.right):
        parts.append(current.right.value.strip("/"))  # type: ignore[attr-defined]
        current = current.left
    if _is_text(current):  # "configs" / "agents"
        parts.append(current.value.strip("/"))  # type: ignore[attr-defined]
    return "/".join(reversed([p for p in parts if p]))


def _fixed_start(node: ast.JoinedStr) -> str:
    start = []
    for value in node.values:
        if not _is_text(value):
            break
        start.append(value.value)  # type: ignore[attr-defined]
    return "".join(start)


# ---------------------------------------------------------------- one tree


class RepoIndex:
    """The files of one tree, indexed by every way a reference can name them."""

    def __init__(self, files: Iterable[str]):
        self.files = frozenset(files)
        self.by_base: dict[str, set[str]] = defaultdict(set)
        self.by_stem: dict[str, set[str]] = defaultdict(set)  # configs' YAML only: workflow and agent names
        self.modules: dict[str, str] = {}
        # "bin.x", "x" -> configs/a/bin/x.py: names a folder on sys.path gives a script. temper_ai is
        # always imported by its full name, so its modules are left out (no `import docker` matching
        # some temper_ai/.../docker.py)
        self.module_tails: dict[str, set[str]] = defaultdict(set)
        self.folders: dict[str, list[str]] = defaultdict(list)
        for path in self.files:
            base = path.rsplit("/", 1)[-1]
            self.by_base[base].add(path)
            name = module_name(path)
            if name is None:
                if is_config(path):
                    self.by_stem[base.rsplit(".", 1)[0]].add(path)
            else:
                self.modules[name] = path
                parts = name.split(".")
                if parts[0] not in ENGINE_PACKAGES:
                    for start in range(1, len(parts)):
                        self.module_tails[".".join(parts[start:])].add(path)
            folder = path.rpartition("/")[0]
            while folder:
                self.folders[folder].append(path)
                folder = folder.rpartition("/")[0]
        self.top_folders = {f for f in self.folders if "/" not in f}
        self.top_packages = {name.split(".", 1)[0] for name in self.modules}

    def module_files(self, name: str) -> set[str]:
        """The files importing `name` runs: the module and its parent packages. A name that is no module
        path here (a folder put on sys.path) matches the modules whose dotted path ends with it or with
        one of its parents, each at most FANOUT."""
        parts = name.split(".")
        prefixes = [".".join(parts[: k + 1]) for k in range(len(parts))]
        found = {self.modules[p] for p in prefixes if p in self.modules}
        if found:
            return found
        if parts[0] in sys.stdlib_module_names:
            return found
        for prefix in prefixes:
            tails = self.module_tails.get(prefix, set())
            if len(tails) <= FANOUT:
                found |= tails
        return found

    def named_files(self, literal: str, user: str = "") -> set[str]:
        """Files a literal in `user` names: by path, by basename with extension, or by a config's stem.
        A bare basename that several files share means the ones nearest to `user` (in its folder, else
        its parent's, ...); with only the repository root in common it means none of them."""
        candidate = _clean_path(literal)
        if not candidate or " " in candidate:
            return set()
        if candidate in self.files:
            return {candidate}
        base = candidate.rsplit("/", 1)[-1]
        if "." in base:
            matches = self.by_base.get(base, set())
        elif len(base) >= MIN_STEM:
            matches = self.by_stem.get(base, set())
        else:
            return set()
        if "/" in candidate:  # a path that is not in the tree names only files ending with it
            matches = {m for m in matches if m.endswith("/" + candidate) or m == candidate}
        elif "." in base and len(matches) > 1:
            matches = _nearest(matches, user)
        return set(matches) if len(matches) <= FANOUT else set()

    def package_tests(self, module: str) -> list[str]:
        """The tests written for an engine module's package: tests/test_<package>/ for temper_ai/<package>/."""
        parts = module.split("/")
        if len(parts) < 3:
            return []
        return [p for p in self.folders.get(f"{TEST_ROOT}/test_{parts[1]}", []) if is_test_file(p)]

    def named_folder(self, literal: str) -> str | None:
        candidate = _clean_path(literal)
        return candidate if candidate in self.folders else None


@dataclass
class DependencyGraph:
    """For every file of one tree, the files that depend on it, and the tests among them."""

    index: RepoIndex
    depends_on: dict[str, set[str]] = field(default_factory=dict)
    folder_readers: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # folder -> files
    dependents: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # what each file asks for, matched or not: module names it imports, the words it holds
    wanted_modules: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    literals: dict[str, frozenset[str]] = field(default_factory=dict)
    # a file outside the engine -> the engine modules that name it (a default config, a doc they point
    # at). It reaches those modules' package tests, not everything that imports them: the engine is
    # generic code, and a test that runs a particular config names it itself.
    engine_reads: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @property
    def tests(self) -> set[str]:
        return {p for p in self.index.files if is_test_file(p)}

    def direct_dependents(self, path: str) -> set[str]:
        """Files that import, run or name `path`, or read a folder holding it."""
        found = set(self.dependents.get(path, ()))
        folder = path.rpartition("/")[0]
        while folder:
            found |= self.folder_readers.get(folder, set())
            folder = folder.rpartition("/")[0]
        found.discard(path)
        return found

    def files_still_naming(self, path: str) -> set[str]:
        """Files of this tree that still ask for `path`, which is not in it: they import its module, name
        it, or read a folder that held it. They break, or change what they do, now that it is gone."""
        name = module_name(path)
        base = path.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0]
        exact = {path, "./" + path}
        if is_config(path) and len(stem) >= MIN_STEM:
            exact.add(stem)
        others = self.index.by_base.get(base, set())  # files still there with the same basename
        found = set()
        for user, literals in self.literals.items():
            cleaned = {_clean_path(w) for w in literals}
            if exact & cleaned or any(w.endswith("/" + path) for w in cleaned if "/" in w) or (
                    base in cleaned and (not others or path in _nearest(others | {path}, user))):
                found.add(user)
        if name:
            for user, wanted in self.wanted_modules.items():
                for want in wanted:
                    if want == name or want.startswith(name + ".") or (
                            name.endswith("." + want) and not self.index.module_files(want)):
                        found.add(user)
                        break
        folder = path.rpartition("/")[0]
        while folder:
            found |= self.folder_readers.get(folder, set())
            folder = folder.rpartition("/")[0]
        found.discard(path)
        if not is_engine(path):  # an engine module that named it stands for its package tests
            for user in [u for u in found if is_engine(u)]:
                found.discard(user)
                found.update(self.index.package_tests(user))
        return found

    def tests_reaching(self, changed: Iterable[str], hubs: Iterable[str] = ()) -> dict[str, list[str]]:
        """Each test that depends on a changed file, directly or through other files, with one chain
        from the changed file to it. Following stops at hubs: their own dependents are not reached."""
        stop = set(hubs)
        via: dict[str, list[str]] = {}
        queue: deque[str] = deque()
        for path in changed:
            if path not in via:
                via[path] = [path]
                queue.append(path)
        while queue:
            path = queue.popleft()
            if path in stop and via[path] != [path]:
                continue
            for dependent in self.direct_dependents(path):
                if dependent not in via:
                    via[dependent] = [*via[path], dependent]
                    queue.append(dependent)
            for module in sorted(self.engine_reads.get(path, ())):
                for test in self.index.package_tests(module):
                    if test not in via:
                        via[test] = [*via[path], module, test]
                        queue.append(test)
        return {p: chain for p, chain in via.items() if is_test_file(p)}


def build_graph(files: Iterable[str], references: Mapping[str, References]) -> DependencyGraph:
    """The graph of one tree: `files` are its tracked paths, `references` what each read file names."""
    index = RepoIndex(files)
    graph = DependencyGraph(index)
    # pytest runs every conftest.py and package __init__.py above a test before the test itself
    loaded_first = [p for p in index.files if p.startswith(TEST_ROOT + "/")
                    and p.rsplit("/", 1)[-1] in ("conftest.py", "__init__.py")]
    for path in index.files:
        refs = references.get(path)
        depends = _resolve(path, refs, index, graph) if refs else set()
        if refs:
            graph.literals[path] = refs.literals
        if is_test_file(path):
            depends |= {c for c in loaded_first if path.startswith(c.rpartition("/")[0] + "/")}
        depends.discard(path)
        graph.depends_on[path] = depends
        for target in depends:
            graph.dependents[target].add(path)
    return graph


def _resolve(path: str, refs: References, index: RepoIndex, graph: DependencyGraph) -> set[str]:
    depends: set[str] = set()
    me = module_name(path)
    package = (me if path.endswith("/__init__.py") else me.rpartition(".")[0]) if me else ""
    for imp in refs.imports:
        base = imp.module
        if imp.level:
            parts = package.split(".") if package else []
            parts = parts[: len(parts) - (imp.level - 1)] if imp.level > 1 else parts
            base = ".".join([*parts, imp.module] if imp.module else parts)
        wanted = [base] if base else []
        wanted += [f"{base}.{name}" if base else name for name in imp.names if name != "*"]
        for name in wanted:
            graph.wanted_modules[path].add(name)
            depends |= index.module_files(name)
    for name in refs.imported_by_name:
        graph.wanted_modules[path].add(name)
        depends |= index.module_files(name)
    reads_folders = path.startswith(TEST_ROOT + "/") and path.endswith(".py")  # tests and their helpers
    engine = is_engine(path)
    for literal in refs.literals:
        for named in index.named_files(literal, path):
            if is_test_file(named):
                continue
            if engine and not is_engine(named):
                graph.engine_reads[named].add(path)
            else:
                depends.add(named)
        for piece in MODULE_PIECES.findall(literal):  # "temper_ai.tools.x:Tool", a monkeypatch target
            if DOTTED.fullmatch(piece) and piece.split(".", 1)[0] in index.top_packages:
                graph.wanted_modules[path].add(piece)
                depends |= index.module_files(piece)
        if reads_folders and "/" in literal:
            folder = index.named_folder(literal)
            if folder:
                graph.folder_readers[folder].add(path)
    return depends


# ---------------------------------------------------------------- reading a tree


def read_references(paths: Iterable[str], read: Callable[[str], str | None]) -> dict[str, References]:
    """References of every file among `paths` that can use others; `read` gives a file's text or None."""
    out = {}
    for path in paths:
        if should_read(path):
            text = read(path)
            if text is not None:
                out[path] = extract_references(path, text)
    return out
