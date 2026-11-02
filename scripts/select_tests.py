#!/usr/bin/env python3
"""Which tests a temper-ai change has to run: scripts/test-selection.toml applied to the files it changes.

One job: a change -> the tests and checks to run. The pre-commit hook (scripts/git-hooks/pre-commit,
which `wt land` also runs as temper-ai's check) and GitHub CI (.github/workflows/ci.yml) both call it,
so they pick the same tests. docs/test-selection.md explains the rules. Stdlib only (Python 3.11+ for
tomllib), so it runs before `uv sync` and in a bare CI job.

What the change is:
  --staged           the files staged for commit (index against HEAD); everything is read from the
                     index, which is what is being committed. The hook uses it when anything is staged.
  --base B --head H  the files that differ between `git merge-base B H` and H (default master and HEAD):
                     a branch's own commits. A batched land checks a candidate built from several
                     branches on top of master, so the diff is their union. Everything is read from H.
  --files A B ...    these paths, read from --head (dry runs and tests)

Fail safe: a file no rule matches, a diff it cannot take, or an empty change runs everything.

    python3 scripts/select_tests.py [--staged | --base refs/heads/master --head HEAD] [--explain]
    python3 scripts/select_tests.py --files temper_ai/tools/web_fetch.py docs/x.md --explain

Prints, one per line:

    python all | python none | python <test file> ...   which Python tests run
    frontend                                            the dashboard's checks
    e2e                                                 the browser tests

--format pytest prints only pytest's targets instead (tests/ for all, nothing for none), one per line.
--explain writes why to stderr. --github-output FILE appends python=all|some|none, python_tests (the
files, space-separated), frontend=true|false and e2e=true|false for ci.yml. Exit 0 with a selection;
exit 2 when the rules or the change cannot be read.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dependency_graph import (  # noqa: E402
    TEST_ROOT,
    DependencyGraph,
    build_graph,
    is_test_file,
    read_references,
    should_read,
)

RULES_PATH = "scripts/test-selection.toml"
HOST_CONTRACTS = "host-contracts"
HOST_PACKAGE = "p3_host_contracts"
HOST_TESTS = "tests/test_p3_host_contracts"
HOST_DOC = "docs/p3-host-contracts.md"
SIMPLE_PARTS = ("full", "graph", "package-tests", "folder-tests", "frontend", "e2e", HOST_CONTRACTS)
SAFE_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")


def safe_path(path: str) -> bool:
    return bool(SAFE_PATH.fullmatch(path)) and not ({".", ".."} & set(path.split("/")))


def host_contract_path(path: str) -> bool:
    """Exact supplier boundary, not a general source-only exemption."""
    return safe_path(path) and (path == HOST_DOC or path.startswith((HOST_PACKAGE + "/", HOST_TESTS + "/")))
NAMED_TESTS = re.compile(r"^tests:(tests(?:/[\w.-]+)*/?)$")
INDEX = ":index"  # --head value meaning "the index", for --staged


class SelectionError(Exception):
    """The rules or the change cannot be read: the selector cannot say anything safe."""


# ---------------------------------------------------------------- rules


@dataclass(frozen=True)
class Rule:
    name: str
    why: str
    paths: tuple[str, ...]
    parts: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]

    def matches(self, path: str) -> bool:
        return any(p.fullmatch(path) for p in self.patterns)


@dataclass(frozen=True)
class Rules:
    hubs: tuple[str, ...]
    rules: tuple[Rule, ...]

    def rule_for(self, path: str) -> Rule | None:
        """The first rule whose paths match `path`, or None (which runs everything)."""
        return next((r for r in self.rules if r.matches(path)), None)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """`*` and `?` stay inside one folder, `**` crosses folders, `**/` may also match nothing."""
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def _check_part(part: object, where: str) -> str:
    if not isinstance(part, str) or not (part in SIMPLE_PARTS or NAMED_TESTS.match(part)):
        raise SelectionError(f"{where}: unknown part {part!r}")
    return part


def load_rules(text: str) -> Rules:
    """Parse and check test-selection.toml; anything unexpected is an error, never a silent default."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise SelectionError(f"{RULES_PATH} is not valid TOML: {err}") from err
    if data.get("version") != 1:
        raise SelectionError(f"{RULES_PATH}: version must be 1")
    unknown = set(data) - {"version", "hubs", "rule"}
    if unknown:
        raise SelectionError(f"{RULES_PATH}: unknown keys {sorted(unknown)}")
    hubs = data.get("hubs", [])
    if not isinstance(hubs, list) or not all(isinstance(h, str) and h for h in hubs):
        raise SelectionError(f"{RULES_PATH}: hubs must be a list of paths")
    rules = []
    for index, raw in enumerate(data.get("rule", []), start=1):
        where = f"{RULES_PATH} rule {index}"
        if not isinstance(raw, dict) or set(raw) != {"name", "why", "paths", "parts"}:
            raise SelectionError(f"{where}: needs exactly name, why, paths and parts")
        name, why, paths, parts = raw["name"], raw["why"], raw["paths"], raw["parts"]
        if not isinstance(name, str) or not name or not isinstance(why, str) or not why:
            raise SelectionError(f"{where}: name and why must be non-empty text")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
            raise SelectionError(f"{where} ({name}): paths must be a non-empty list of patterns")
        if not isinstance(parts, list):
            raise SelectionError(f"{where} ({name}): parts must be a list")
        checked = tuple(_check_part(p, f"{where} ({name})") for p in parts)
        rules.append(Rule(name, why, tuple(paths), checked, tuple(glob_to_regex(p) for p in paths)))
    if not rules:
        raise SelectionError(f"{RULES_PATH}: no rules")
    return Rules(tuple(hubs), tuple(rules))


# ---------------------------------------------------------------- selection


@dataclass(frozen=True)
class Change:
    path: str
    deleted: bool = False


@dataclass
class Selection:
    everything: bool = False
    tests: set[str] = field(default_factory=set)  # Python test files
    frontend: bool = False
    e2e: bool = False
    reasons: list[str] = field(default_factory=list)
    route: str = "ordinary"
    head: str = "HEAD"  # checked tree; INDEX during a staged check
    base: str = ""  # resolved merge-base, for CI to repeat the same classification

    def run_everything(self, why: str) -> None:
        self.route = "ordinary"
        self.everything = self.frontend = self.e2e = True
        self.reasons.append(f"everything: {why}")

    @property
    def python(self) -> str:
        """"all", "some" (then `tests` says which) or "none"."""
        if self.everything:
            return "all"
        return "some" if self.tests else "none"

    def pytest_targets(self) -> list[str]:
        return {"all": [TEST_ROOT + "/"], "none": []}.get(self.python, sorted(self.tests))

    def lines(self) -> list[str]:
        python = "python " + (" ".join(sorted(self.tests)) if self.python == "some" else self.python)
        return [f"route {self.route}", python] + [part for part, wanted in (("frontend", self.frontend), ("e2e", self.e2e)) if wanted]

    def as_json(self) -> dict[str, object]:
        return {"route": self.route, "python": self.python, "python_tests": sorted(self.tests) if self.python == "some" else [],
                "frontend": self.frontend, "e2e": self.e2e, "reasons": self.reasons}

    def github_output(self) -> str:
        tests = " ".join(sorted(self.tests)) if self.python == "some" else ""
        flags = {"frontend": self.frontend, "e2e": self.e2e}
        lines = [f"route={self.route}", f"base={self.base}", f"python={self.python}", f"python_tests={tests}"]
        lines += [f"{key}={'true' if value else 'false'}" for key, value in flags.items()]
        return "\n".join(lines) + "\n"


def select(changes: Sequence[Change], rules: Rules, files: Iterable[str],
           graph: Callable[[], DependencyGraph]) -> Selection:
    """The tests and checks `changes` need. `files` are the paths of the tree being checked; `graph`
    builds its dependency graph (called at most once, only if a rule needs it)."""
    selection = Selection()
    if not changes:
        selection.run_everything("nothing changed, so nothing narrows the check")
        return selection
    if not all(safe_path(c.path) for c in changes):
        selection.run_everything("unsafe changed path")
        return selection
    tree = frozenset(files)
    tests_in_tree = sorted(p for p in tree if is_test_file(p))
    host_changes = [c for c in changes if host_contract_path(c.path)]
    if host_changes:
        if len(host_changes) != len(changes):
            selection.run_everything("host contracts mixed with other changes")
        elif not all((r := rules.rule_for(c.path)) and r.parts == (HOST_CONTRACTS,) for c in changes):
            selection.run_everything("host contracts lack their explicit rule")
        elif (HOST_PACKAGE + "/__init__.py" not in tree
              or not any(p.startswith(HOST_TESTS + "/") for p in tests_in_tree)):
            selection.run_everything("host contract package or tests missing")
        elif not all(safe_path(p) for p in tree if p.startswith((HOST_PACKAGE + "/", HOST_TESTS + "/"))):
            selection.run_everything("unsafe host contract tree path")
        else:
            selection.route = HOST_CONTRACTS
            selection.tests = {p for p in tests_in_tree if p.startswith(HOST_TESTS + "/")}
            selection.reasons.append("exact host-contract-only change; always check the whole leaf, including docs-only")
        return selection
    starts: dict[str, str] = {}  # where the graph starts -> the changed path it stands for
    for change in changes:
        rule = rules.rule_for(change.path)
        if rule is None:
            selection.run_everything(f"no rule matches {change.path} (unknown means everything)")
            return selection
        if "full" in rule.parts or HOST_CONTRACTS in rule.parts:
            selection.run_everything(f"{change.path} matches {rule.name!r}: {rule.why}")
            return selection
        gone = " (deleted)" if change.deleted else ""
        selection.reasons.append(f"{change.path}{gone}: rule {rule.name!r} -> {', '.join(rule.parts) or 'nothing'}")
        for part in rule.parts:
            if part == "graph":
                starts.setdefault(change.path, change.path)
            elif part == "package-tests":
                _add_folder(selection, tests_in_tree, _package_tests_folder(change.path, tree), part)
            elif part == "folder-tests":
                _add_folder(selection, tests_in_tree, _top_test_folder(change.path), part)
            elif part.startswith("tests:"):
                _add_folder(selection, tests_in_tree, part.split(":", 1)[1].rstrip("/"), part)
            elif part == "frontend":
                selection.frontend = True
            elif part == "e2e":
                selection.e2e = True
    if starts:
        _follow_graph(selection, graph(), starts, {c.path for c in changes if c.deleted}, rules.hubs)
    return selection


def _package_tests_folder(path: str, tree: frozenset[str]) -> str | None:
    """tests/test_<name> for temper_ai/<name>/... or configs/<name>/..., when it has files."""
    parts = path.split("/")
    if len(parts) < 3:
        return None
    folder = f"{TEST_ROOT}/test_{parts[1]}"
    return folder if any(p.startswith(folder + "/") for p in tree) else None


def _top_test_folder(path: str) -> str | None:
    """tests/<folder> for a file inside one; None for a file directly in tests/."""
    parts = path.split("/")
    return "/".join(parts[:2]) if parts[0] == TEST_ROOT and len(parts) > 2 else None


def _add_folder(selection: Selection, tests: list[str], folder: str | None, part: str) -> None:
    if folder is None:
        return
    found = [t for t in tests if t == folder or t.startswith(folder + "/")]
    selection.tests.update(found)
    selection.reasons.append(f"  {part}: {len(found)} test files under {folder}")


def _follow_graph(selection: Selection, graph: DependencyGraph, starts: dict[str, str],
                  deleted: set[str], hubs: Iterable[str]) -> None:
    hubs = set(hubs)
    origins: dict[str, str] = {}
    for path in starts:
        if path in deleted:
            namers = graph.files_still_naming(path)
            selection.reasons.append(f"  {path} is gone: {len(namers)} files still name it or read its folder")
            for namer in namers:
                origins.setdefault(namer, path)
        else:
            origins.setdefault(path, path)
    hub_namers = sorted(set(origins) & hubs - set(starts))
    if hub_namers:
        selection.run_everything(f"{', '.join(hub_namers)} names the deleted {origins[hub_namers[0]]}")
        return
    reached = graph.tests_reaching(origins, hubs)
    selection.tests.update(reached)
    by_origin: dict[str, list[str]] = {}
    for test, chain in reached.items():
        by_origin.setdefault(starts.get(chain[0], origins.get(chain[0], chain[0])), []).append(test)
    for path in starts:
        found = sorted(by_origin.get(path, []))
        example = f", e.g. {' -> '.join(reached[found[0]])}" if found and len(reached[found[0]]) > 1 else ""
        selection.reasons.append(f"  graph: {len(found)} test files depend on {path}{example}")


# ---------------------------------------------------------------- git


class Git:
    """Read-only questions about one repository's commits and index."""

    def __init__(self, repo: Path):
        self.repo = repo

    def _run(self, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(["git", "-C", str(self.repo), *args], input=input_bytes,
                              capture_output=True, check=False)

    def _text(self, *args: str) -> str | None:
        done = self._run(*args)
        if done.returncode != 0:
            return None
        return done.stdout.decode().strip() or None

    def commit(self, ref: str) -> str | None:
        return self._text("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")

    def merge_base(self, base: str, head: str) -> str | None:
        return self._text("merge-base", base, head)

    def changes(self, *diff_args: str) -> list[Change] | None:
        done = self._run("diff", "--name-status", "--no-renames", "-z", *diff_args)
        if done.returncode != 0:
            return None
        fields = done.stdout.decode().split("\0")
        if fields.pop() != "" or len(fields) % 2:
            raise SelectionError("malformed changed-path list")
        pairs = list(zip(fields[0::2], fields[1::2], strict=True))
        if any(status not in ("A", "M", "D", "T") or not path for status, path in pairs):
            raise SelectionError("unsupported changed-path status")
        return [Change(path, deleted=status == "D") for status, path in pairs]

    def files(self, head: str) -> set[str]:
        """Tracked paths of a commit, or of the index for INDEX."""
        args = ("ls-files", "-z") if head == INDEX else ("ls-tree", "-r", "--name-only", "-z", head)
        done = self._run(*args)
        if done.returncode != 0:
            raise SelectionError(f"cannot list the files of {head}: {done.stderr.decode().strip()}")
        return {p for p in done.stdout.decode().split("\0") if p}

    def regular_files(self, head: str, paths: Iterable[str]) -> bool:
        """No symlinks, submodules or unresolved index stages in a checked leaf."""
        args = ("ls-files", "--stage", "-z") if head == INDEX else ("ls-tree", "-r", "-z", head)
        done = self._run(*args, "--", *paths)
        if done.returncode:
            raise SelectionError("cannot read checked file modes")
        for row in done.stdout.split(b"\0"):
            if not row:
                continue
            mode, _, stage = row.split(b"\t", 1)[0].split()
            if mode not in (b"100644", b"100755") or (head == INDEX and stage != b"0"):
                return False
        return True

    def read(self, head: str, paths: Iterable[str]) -> dict[str, str]:
        return {p: value.decode("utf-8", errors="replace") for p, value in self.blobs(head, paths).items()}

    def blobs(self, head: str, paths: Iterable[str]) -> dict[str, bytes]:
        """Contents of `paths` at `head` (or in the index), read through one `git cat-file --batch`.
        A path that is not there (a submodule, say) is left out."""
        paths = list(paths)
        prefix = ":" if head == INDEX else f"{head}:"
        request = "".join(f"{prefix}{p}\n" for p in paths).encode()
        done = self._run("cat-file", "--batch", input_bytes=request)
        if done.returncode != 0:
            raise SelectionError(f"cannot read files of {head}: {done.stderr.decode().strip()}")
        out, data, pos = {}, done.stdout, 0
        for path in paths:
            header_end = data.index(b"\n", pos)
            header = data[pos:header_end].split()
            if len(header) != 3:  # "<name> missing"
                pos = header_end + 1
                continue
            size = int(header[2])
            if header[1] == b"blob":
                out[path] = data[header_end + 1 : header_end + 1 + size]
            pos = header_end + 1 + size + 1
        return out


def graph_of(git: Git, head: str, files: set[str]) -> DependencyGraph:
    readable = sorted(p for p in files if should_read(p))
    texts = git.read(head, readable)
    return build_graph(files, read_references(readable, texts.get))


# ---------------------------------------------------------------- command line


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pick the temper-ai tests and checks a change needs.")
    parser.add_argument("--staged", action="store_true", help="the staged files, read from the index")
    parser.add_argument("--base", default=None, help="what the change goes onto (default master)")
    parser.add_argument("--head", default="HEAD", help="the change (default HEAD)")
    parser.add_argument("--files", nargs="+", help="use these changed paths instead of a diff")
    parser.add_argument("--rules", type=Path, help=f"rules file (default: {RULES_PATH} at head)")
    parser.add_argument("--repo", type=Path, help="repository (default: the one around this directory)")
    parser.add_argument("--explain", action="store_true", help="write why to stderr")
    parser.add_argument("--format", choices=("lines", "json", "pytest"), default="lines")
    parser.add_argument("--github-output", type=Path, help="append ci.yml's outputs to this file")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> tuple[Selection, str]:
    """(selection, header line for --explain). Raises SelectionError when nothing safe can be said."""
    repo = args.repo
    if repo is None:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
        if top.returncode != 0:
            raise SelectionError("not inside a git repository; pass --repo")
        repo = Path(top.stdout.strip())
    git = Git(repo)
    staged_changes = (
        git.changes("--cached", "HEAD")
        if not args.files and args.base is None and args.head == "HEAD"
        else None
    )
    use_staged = bool(args.staged or staged_changes)
    if use_staged:
        head, label = INDEX, "the index"
    else:
        head = git.commit(args.head)
        if head is None:
            raise SelectionError(f"head {args.head!r} is not a commit")
        label = head[:12]
    if args.rules:
        rules_text = args.rules.read_text()
    else:
        rules_text = git.read(head, [RULES_PATH]).get(RULES_PATH)
        if rules_text is None and (repo / RULES_PATH).is_file():
            rules_text = (repo / RULES_PATH).read_text()
        if rules_text is None:
            raise SelectionError(f"{RULES_PATH} is not in {label}")
    rules = load_rules(rules_text)
    files = git.files(head)
    fork = ""
    if args.files:
        changes: list[Change] | None = [Change(p, deleted=p not in files) for p in args.files]
        header = f"select_tests: {label}, {len(args.files)} files given"
    elif use_staged:
        changes = staged_changes if staged_changes is not None else git.changes("--cached", "HEAD")
        header = f"select_tests: staged changes, {len(changes or [])} files"
    else:
        base_spec = args.base or "refs/heads/master"
        base = git.commit(base_spec)
        if base is None and args.base is None:
            base = git.commit("origin/master")
        fork = git.merge_base(base, head) if base else None
        changes = git.changes(fork, head) if fork else None
        header = (f"select_tests: base {fork[:12]} (merge-base of {base_spec} and {args.head}), head {label}, "
                  f"{len(changes or [])} files changed") if fork else f"select_tests: head {label}"
    if changes is None:
        selection = Selection()
        selection.run_everything(f"cannot diff {(args.base or 'refs/heads/master')!r} against {label}")
        return selection, header
    selection = select(changes, rules, files, lambda: graph_of(git, head, files))
    if selection.route == HOST_CONTRACTS and not git.regular_files(head, (HOST_PACKAGE, HOST_TESTS, HOST_DOC)):
        selection.run_everything("non-regular host contract files")
    selection.head, selection.base = head, fork or ""
    return selection, header


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        selection, header = run(args)
    except SelectionError as err:
        print(f"select_tests: {err}", file=sys.stderr)
        return 2
    if args.explain:
        print(header, file=sys.stderr)
        for line in selection.reasons:
            print(f"  {line}", file=sys.stderr)
        summary = {"all": "every Python test", "none": "no Python test"}.get(
            selection.python, f"{len(selection.tests)} Python test files")
        extra = [part for part, wanted in (("frontend", selection.frontend), ("e2e", selection.e2e)) if wanted]
        print(f"  -> {summary}" + "".join(f", {part}" for part in extra), file=sys.stderr)
    if args.github_output:
        with args.github_output.open("a") as out:
            out.write(selection.github_output())
    if args.format == "json":
        print(json.dumps(selection.as_json(), indent=1))
    elif args.format == "pytest":
        for target in selection.pytest_targets():
            print(target)
    else:
        for line in selection.lines():
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
