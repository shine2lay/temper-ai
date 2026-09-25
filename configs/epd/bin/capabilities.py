#!/usr/bin/env python3
"""Derive a repository's capability surface, and keep a written map of it honest.

An agent asked to change an application should not have to read the whole
application to find out what it does. But a hand-written summary of what it
does starts dying the moment it is written, and a summary that is quietly
wrong is worse than none: it is read with the same confidence as a true one.

So the map is two things with different lifetimes, in one file:

  the SKELETON is derived from the code on every run -- every HTTP route,
  every page, every subcommand. It cannot drift, because it is never
  written down by hand.

  the INTENT is one sentence per entry, written by a person or an agent
  and kept forever. It is the part that costs something, and the only
  part worth reviewing.

Refreshing MERGES: existing sentences are carried over by key, new entries
arrive undescribed, and entries whose code is gone are reported rather than
deleted behind your back. `--check` exits non-zero when the code and the map
disagree, which is what makes the map trustworthy a year from now.

Deliberately stdlib-only and importing nothing from temper: it has to run
inside an arbitrary checkout, against a project whose dependencies are not
installed and whose virtualenv does not exist. Everything here is static
reading -- no imports of the target, no server started, no side effects.

Usage:
    capabilities.py --repo PATH              refresh .temper/topics/capabilities.md (--out elsewhere)
    capabilities.py --repo PATH --check      exit 1 if code and map disagree
    capabilities.py --repo PATH --json       emit the derived surface only
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = "1"
MARKER = f"<!-- temper:capabilities v{VERSION} -->"
UNDESCRIBED = "_(undescribed)_"

# Directories that never hold capability definitions. Skipped for speed and,
# more importantly, for truth: a route defined in a test fixture or vendored
# dependency is not something this application offers.
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".temper",
    ".epd", "migrations", "alembic", ".tox", "htmlcov", "site-packages",
}
# A path containing any of these is test or example code.
SKIP_PARTS = ("test", "tests", "conftest", "fixtures", "examples", "example")


@dataclass
class Capability:
    """One thing the application can do, as found in the code."""
    kind: str      # http | page | cli
    key: str       # stable identity, e.g. "POST /api/orders". The merge key.
    where: str     # "path:line", relative to the repo root
    group: str     # section heading, usually the defining file or router tag
    intent: str = ""   # derived hint (docstring/help=), only ever a SEED


@dataclass
class Surface:
    caps: list[Capability] = field(default_factory=list)
    probes_matched: list[str] = field(default_factory=list)
    probes_tried: list[str] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[Capability]:
        return [c for c in self.caps if c.kind == kind]


def _tracked_files(root: Path) -> list[Path] | None:
    """Files git tracks in THIS repository, or None when that cannot be answered.

    This is the repository boundary, and getting it wrong is not a small error.
    Run against a checkout that contains other checkouts -- a pipeline's
    workspaces directory, a vendored dependency, a submodule -- a plain
    directory walk happily reports another application's routes as this one's.
    It did: temper-ai came back with 431 HTTP routes and 80 pages, all of them
    belonging to repositories cloned underneath it. An agent reading that would
    believe the server offers endpoints it has never had.

    Asking git is the one rule that covers every version of this at once, since
    a nested repository's files are not tracked by the parent, and neither is
    anything ignored, built or vendored.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--exclude-standard"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names = [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]
    return [root / n for n in names]


def _walk(root: Path, suffixes: tuple[str, ...]):
    """Yield candidate source files, skipping vendored, nested and test trees."""
    tracked = _tracked_files(root)

    if tracked is not None:
        candidates = tracked
    else:
        # No git here (a tarball, an export). Fall back to walking, which cannot
        # see ignore rules -- so also refuse to descend into anything carrying
        # its own .git, the most common way another project gets nested inside.
        candidates = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS
                and not d.startswith(".")
                and not (Path(dirpath) / d / ".git").exists()
            ]
            candidates.extend(Path(dirpath) / fn for fn in filenames)

    for p in candidates:
        if not p.name.endswith(suffixes):
            continue
        try:
            rel_parts = p.relative_to(root).parts[:-1]
        except ValueError:
            continue
        if any(part in SKIP_DIRS or part.lower() in SKIP_PARTS for part in rel_parts):
            continue
        if p.name.lower().startswith("test") or "_test" in p.name.lower():
            continue
        if not p.is_file():
            continue
        yield p


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _first_docline(node: ast.AST) -> str:
    """First sentence of a docstring, as a seed for intent."""
    doc = ast.get_docstring(node) if isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)
    ) else None
    if not doc:
        return ""
    line = doc.strip().splitlines()[0].strip()
    return line[:160]


# --------------------------------------------------------------------------
# Probe: FastAPI / APIRouter
# --------------------------------------------------------------------------
def probe_fastapi(root: Path) -> list[Capability]:
    """Every HTTP route, by reading the AST -- never by importing the app.

    Importing would be exact, but it needs the project's dependencies, its
    environment variables and a database it can reach. Static reading works in
    a bare checkout, which is where this has to run.

    Resolution is per-file: `router = APIRouter(prefix="/api")` binds a prefix
    to a name, and `@router.get("/orders")` is then a route at `/api/orders`.
    Routers included from elsewhere with an extra prefix are the one case this
    cannot see; when a router's prefix is not a literal it is reported as `?`
    rather than guessed at.
    """
    caps: list[Capability] = []
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}

    for py in _walk(root, (".py",)):
        try:
            tree = ast.parse(py.read_text(errors="replace"))
        except (SyntaxError, ValueError):
            continue

        # name -> prefix, plus the tag we will group by
        prefixes: dict[str, str] = {}
        tags: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            fn = node.value.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if fname not in ("APIRouter", "FastAPI"):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                prefix, tag = "", ""
                for kw in node.value.keywords:
                    if kw.arg == "prefix":
                        prefix = kw.value.value if isinstance(kw.value, ast.Constant) else "?"
                    elif kw.arg == "tags" and isinstance(kw.value, ast.List) and kw.value.elts:
                        first = kw.value.elts[0]
                        if isinstance(first, ast.Constant):
                            tag = str(first.value)
                prefixes[target.id] = prefix
                tags[target.id] = tag

        if not prefixes:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                verb = dec.func.attr
                obj = dec.func.value
                if verb not in methods or not isinstance(obj, ast.Name):
                    continue
                if obj.id not in prefixes:
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                path = str(dec.args[0].value)
                full = f"{prefixes[obj.id]}{path}" or "/"
                summary = ""
                for kw in dec.keywords:
                    if kw.arg == "summary" and isinstance(kw.value, ast.Constant):
                        summary = str(kw.value.value)
                caps.append(Capability(
                    kind="http",
                    key=f"{verb.upper()} {full}",
                    where=f"{_rel(root, py)}:{node.lineno}",
                    group=tags.get(obj.id) or _rel(root, py),
                    intent=summary or _first_docline(node),
                ))
    return caps


# --------------------------------------------------------------------------
# Probe: React Router
# --------------------------------------------------------------------------
_ROUTE_OPEN = re.compile(r"<Route\b")
_ATTR_PATH = re.compile(r'\bpath\s*=\s*"([^"]*)"')
_ATTR_ELEMENT = re.compile(r"\belement\s*=\s*\{\s*<\s*([A-Za-z0-9_]+)")
_ATTR_INDEX = re.compile(r"\bindex\b(?!\s*=)")


def probe_react_router(root: Path) -> list[Capability]:
    """Every page URL, resolved through nesting.

    JSX is not parseable with `ast`, so this reads `<Route>` elements with a
    small scanner that tracks the nesting stack: a `<Route>` that does not
    self-close pushes its path segment, and its children inherit it. Layout
    routes (`<Route element={<Shell/>}>` with no path) contribute nothing to
    the URL, which is exactly how the router treats them -- getting that wrong
    would invent URLs that do not exist.
    """
    caps: list[Capability] = []
    for src_file in _walk(root, (".tsx", ".jsx")):
        text = src_file.read_text(errors="replace")
        if "<Route" not in text:
            continue

        stack: list[str] = []
        i = 0
        while True:
            m = _ROUTE_OPEN.search(text, i)
            if not m:
                break
            # Find the end of this opening tag, respecting {...} nesting so an
            # `element={<X prop={y}/>}` does not terminate the tag early.
            j, depth = m.end(), 0
            while j < len(text):
                ch = text[j]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                elif ch == ">" and depth == 0:
                    break
                j += 1
            tag = text[m.start():j]
            self_closing = tag.rstrip().endswith("/")
            line = text.count("\n", 0, m.start()) + 1

            pm = _ATTR_PATH.search(tag)
            seg = pm.group(1) if pm else ""
            is_index = bool(_ATTR_INDEX.search(tag)) and not pm
            em = _ATTR_ELEMENT.search(tag)
            component = em.group(1) if em else ""

            parent = "/".join(s for s in stack if s)
            if is_index:
                url = "/" + parent
            elif seg.startswith("/"):
                url = seg
            else:
                url = "/" + "/".join(p for p in (parent, seg) if p)
            url = re.sub(r"/{2,}", "/", url) or "/"

            if (seg or is_index) and component:
                caps.append(Capability(
                    kind="page",
                    key=url,
                    where=f"{_rel(root, src_file)}:{line}",
                    group=component,
                ))

            if not self_closing:
                stack.append(seg)
                # Consume the matching </Route> by scanning forward for balance.
                # Cheap approach: push, and pop when we meet the close tag.
            i = j + 1

            # Pop for every </Route> that appears before the next <Route>.
            nxt = _ROUTE_OPEN.search(text, i)
            window = text[i:nxt.start()] if nxt else text[i:]
            for _ in range(window.count("</Route>")):
                if stack:
                    stack.pop()
    return caps


# --------------------------------------------------------------------------
# Probe: argparse subcommands
# --------------------------------------------------------------------------
def probe_argparse_cli(root: Path) -> list[Capability]:
    """Every subcommand, with its own help text as the seed intent.

    `add_parser("run", help="Run a workflow")` already carries a written
    sentence, so unlike HTTP routes a CLI usually arrives described.
    """
    caps: list[Capability] = []
    for py in _walk(root, (".py",)):
        text = py.read_text(errors="replace")
        if "add_parser(" not in text:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "add_parser" or not node.args:
                continue
            if not isinstance(node.args[0], ast.Constant):
                continue
            name = str(node.args[0].value)
            help_text = ""
            for kw in node.keywords:
                if kw.arg in ("help", "description") and isinstance(kw.value, ast.Constant):
                    help_text = str(kw.value.value).strip().splitlines()[0]
                    break
            caps.append(Capability(
                kind="cli",
                key=name,
                where=f"{_rel(root, py)}:{node.lineno}",
                group=_rel(root, py),
                intent=help_text,
            ))
    return caps


PROBES = {
    "fastapi": probe_fastapi,
    "react-router": probe_react_router,
    "argparse-cli": probe_argparse_cli,
}

KIND_TITLES = {
    "http": "HTTP API",
    "page": "Pages",
    "cli": "Commands",
}


def derive(root: Path) -> Surface:
    surface = Surface()
    for name, probe in PROBES.items():
        surface.probes_tried.append(name)
        try:
            found = probe(root)
        except Exception as exc:  # a broken probe must not hide the others
            print(f"warning: probe {name} failed: {exc}", file=sys.stderr)
            continue
        if found:
            surface.probes_matched.append(name)
            surface.caps.extend(found)

    # Deduplicate on (kind, key): the same route reachable twice is one
    # capability. Keep the first location, which is the earliest definition.
    seen: dict[tuple[str, str], Capability] = {}
    for c in surface.caps:
        seen.setdefault((c.kind, c.key), c)
    surface.caps = sorted(seen.values(), key=lambda c: (c.kind, c.group, c.key))
    return surface


# --------------------------------------------------------------------------
# The map file: parse, merge, render
# --------------------------------------------------------------------------
_ENTRY = re.compile(r"^- `([^`]+)`\s*(?:—\s*)?(.*?)\s*(?:·\s*`([^`]+)`)?\s*$")


def parse_map(path: Path) -> tuple[dict[str, str], str]:
    """Return {key: intent} for described entries, plus the free-text preamble.

    The preamble is everything under `## What this is`, written by a human and
    never generated. Parsing by key is what lets a refresh keep sentences that
    were paid for.
    """
    if not path.exists():
        return {}, ""
    text = path.read_text(errors="replace")
    intents: dict[str, str] = {}
    for line in text.splitlines():
        m = _ENTRY.match(line.strip())
        if m:
            key, intent = m.group(1), (m.group(2) or "").strip()
            if intent and intent != UNDESCRIBED:
                intents[key] = intent
    preamble = ""
    pm = re.search(r"## What this is\n(.*?)(?=\n## |\Z)", text, re.S)
    if pm:
        preamble = pm.group(1).strip()
    return intents, preamble


def render(root: Path, surface: Surface, intents: dict[str, str], preamble: str) -> str:
    name = root.resolve().name
    described = sum(1 for c in surface.caps if intents.get(c.key))
    total = len(surface.caps)

    out: list[str] = []
    out.append(f"# What {name} can do")
    out.append("")
    out.append(MARKER)
    out.append("<!-- The list of capabilities is DERIVED from the code: do not edit it by hand, -->")
    out.append("<!-- it is rewritten on every refresh. The sentence after each entry is WRITTEN, -->")
    out.append("<!-- and is kept across refreshes. Refresh/verify with capabilities.py. -->")
    out.append("")
    out.append(f"{total} capabilities, {described} described"
               f"{'' if total == described else f', {total - described} still undescribed'}."
               f" Probes matched: {', '.join(surface.probes_matched) or 'none'}.")
    out.append("")
    out.append("## What this is")
    out.append("")
    out.append(preamble or "_(write one paragraph here: what this application is for, and for whom. "
                           "This section is never generated.)_")
    out.append("")

    for kind in ("http", "page", "cli"):
        caps = surface.by_kind(kind)
        if not caps:
            continue
        out.append(f"## {KIND_TITLES[kind]} ({len(caps)})")
        out.append("")
        current = None
        for c in caps:
            if c.group != current:
                if current is not None:
                    out.append("")
                current = c.group
                out.append(f"### {current}")
                out.append("")
            intent = intents.get(c.key) or c.intent or UNDESCRIBED
            out.append(f"- `{c.key}` — {intent} · `{c.where}`")
        out.append("")

    if not surface.probes_matched:
        out.append("## Nothing was recognised")
        out.append("")
        out.append(
            "No probe matched this repository, so this file describes nothing. "
            f"Probes available: {', '.join(surface.probes_tried)}. "
            "An empty map is not evidence that the application has no surface — "
            "it means the surface is expressed in a way this tool cannot yet read."
        )
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def check(surface: Surface, path: Path) -> tuple[list[str], list[str], list[str]]:
    """Compare code against the committed map. Returns (added, removed, undescribed)."""
    if not path.exists():
        return [c.key for c in surface.caps], [], []
    text = path.read_text(errors="replace")
    mapped: dict[str, str] = {}
    for line in text.splitlines():
        m = _ENTRY.match(line.strip())
        if m:
            mapped[m.group(1)] = (m.group(2) or "").strip()

    derived_keys = {c.key for c in surface.caps}
    added = sorted(derived_keys - set(mapped))
    removed = sorted(set(mapped) - derived_keys)
    undescribed = sorted(
        k for k in derived_keys & set(mapped)
        if not mapped[k] or mapped[k] == UNDESCRIBED
    )
    return added, removed, undescribed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="repository root")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the code and the map disagree; write nothing")
    ap.add_argument("--json", action="store_true", help="print the derived surface and exit")
    ap.add_argument("--strict", action="store_true",
                    help="with --check, also fail on undescribed entries")
    ap.add_argument("--out", default=".temper/topics/capabilities.md",
                    help="the map, relative to --repo (default: .temper/topics/capabilities.md, "
                         "the place .temper/README.md gives it)")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    surface = derive(root)
    out_path = root / args.out

    if args.json:
        print(json.dumps({
            "probes_matched": surface.probes_matched,
            "counts": {k: len(surface.by_kind(k)) for k in ("http", "page", "cli")},
            "capabilities": [asdict(c) for c in surface.caps],
        }, indent=2))
        return 0

    if args.check:
        added, removed, undescribed = check(surface, out_path)
        if not out_path.exists():
            print(f"drift: {out_path.relative_to(root)} does not exist "
                  f"({len(surface.caps)} capabilities found in code)")
            return 1
        for k in added:
            print(f"drift: in code, missing from map: {k}")
        for k in removed:
            print(f"drift: in map, gone from code: {k}")
        if args.strict:
            for k in undescribed:
                print(f"undescribed: {k}")
        bad = bool(added or removed) or (args.strict and bool(undescribed))
        if not bad:
            print(f"ok: {len(surface.caps)} capabilities, map agrees"
                  + (f" ({len(undescribed)} undescribed)" if undescribed else ""))
        return 1 if bad else 0

    first_time = not out_path.exists()
    intents, preamble = parse_map(out_path)
    added, removed, _ = check(surface, out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(root, surface, intents, preamble))

    kept = len(intents)
    if first_time:
        print(f"created {out_path.relative_to(root)}: {len(surface.caps)} capabilities, "
              f"none described yet")
        return 0

    print(f"wrote {out_path.relative_to(root)}: {len(surface.caps)} capabilities "
          f"({kept} sentences kept, {len(added)} new, {len(removed)} dropped)")
    # Only the delta is worth printing on a refresh: an unchanged surface should
    # be silent, so that anything printed here is something to look at.
    for k in added:
        print(f"  new:     {k}")
    for k in removed:
        print(f"  dropped: {k}   <- code is gone; its sentence was discarded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
