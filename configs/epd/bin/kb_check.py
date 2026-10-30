#!/usr/bin/env python3
"""Check a repository's .temper/ knowledge folder against the code it describes.

.temper/ is what temper's agents read about a repo before they design, plan or test a change
(its README says who reads what). A fact in it that has quietly gone false is worse than no fact:
it is read with the same confidence as a true one. The retro keeps it true after every merge;
this is the part of that job a script can do:

  REFS     every backticked `path` or `path::symbol` in the written files still resolves. A path is
           tried from the repo root, then backend/rollcall/, then frontend/src/; a symbol must
           appear in that file as a whole word. Git checkouts resolve tracked paths only; a missing
           working file is read from the index. Plain folders use disk lookup. Line numbers are
           never used: they drift every merge.
  BUDGET   core/ is read by every agent on every run, so it has a token budget (estimated as
           characters / 3.5). Over budget means prune, not raise the budget.
  DERIVED  topics/capabilities.md agrees with the code (capabilities.py --check).

Stdlib only, like capabilities.py: it runs inside any checkout, with nothing installed.

    kb_check.py --repo PATH            exit 1 when anything is wrong, printing each problem
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

CORE_BUDGET_TOKENS = 4000
CHARS_PER_TOKEN = 3.5
BASES = ("", "backend/rollcall/", "frontend/src/")
DERIVED = "topics/capabilities.md"
# A backticked span is a ref when it looks like a repo path: it has a slash or a source suffix,
# no spaces, and is not a URL or a route (/api/..., /positions/...) or a glob.
REF = re.compile(r"`([^`\s]+)`")
SUFFIX = re.compile(r"\.(py|tsx?|mjs|ya?ml|md|json|toml|css|sh)(::|$)")


def looks_like_ref(span: str) -> bool:
    if span.startswith(("/", "http", "~", "$", "-")) or "*" in span or "<" in span:
        return False
    return bool(SUFFIX.search(span)) or span.endswith("/")


class ReferenceResolver:
    """One reference check's file boundary, shared with knowledge-folder repair tools.

    Git's index supplies membership and fallback blobs, not HEAD: staged additions
    count, staged deletions do not. Present files keep their working content so a
    deleted symbol in an edit is still caught. Recreate after changing the index.
    Use read_text/is_dir on resolved paths; they may be absent from the filesystem.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._entries: dict[Path, tuple[str, str]] | None = None
        self._directories: set[Path] = set()
        try:
            probe = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True,
            )
        except FileNotFoundError:  # git is optional for plain-folder checks
            return
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return
        # Once Git recognizes the checkout, an index error must not turn into
        # permissive disk lookup. -z also preserves names Git would otherwise quote.
        index = subprocess.run(
            ["git", "-C", str(self.root), "ls-files", "--stage", "-z"],
            capture_output=True, check=True,
        )
        self._entries = {}
        for entry in index.stdout.split(b"\0"):
            if not entry:
                continue
            metadata, name = entry.split(b"\t", 1)
            mode, blob, stage = metadata.decode("ascii").split()
            if stage != "0" or mode == "160000":  # no merged blob / submodule, not a file
                continue
            target = self.root / os.fsdecode(name)
            self._entries[target] = (mode, blob)
            self._directories.update(p for p in target.parents if p.is_relative_to(self.root))

    @property
    def tracked_files(self) -> frozenset[Path] | None:
        """Indexed files (including symlinks), or None for a plain directory."""
        return frozenset(self._entries) if self._entries is not None else None

    def _index_text(self, target: Path) -> str:
        assert self._entries is not None
        return subprocess.run(
            ["git", "-C", str(self.root), "cat-file", "blob", self._entries[target][1]],
            capture_output=True, text=True, errors="replace", check=True,
        ).stdout

    def _tracked_target(self, target: Path) -> Path | None:
        """Follow only tracked symlink targets, including links missing from disk."""
        assert self._entries is not None
        seen: set[Path] = set()
        while target not in seen:
            seen.add(target)
            if target in self._directories:
                return target
            entry = self._entries.get(target)
            if entry is None:
                return None
            if target.is_symlink():
                link = os.readlink(target)
            elif entry[0] == "120000" and not target.exists():
                link = self._index_text(target)
            else:
                return target
            target = Path(os.path.abspath(target.parent / link))
        return None

    def resolve(self, path: str) -> Path | None:
        for base in BASES:
            target = self.root / base / path
            if self._entries is None:
                if target.exists():
                    return target
            else:
                # Normalize . and .. without following on-disk symlink shadows.
                target = Path(os.path.abspath(target))
                if self._tracked_target(target) is not None:
                    return target
        return None

    def is_dir(self, target: Path) -> bool:
        if self._entries is None:
            return target.is_dir()
        return self._tracked_target(target) in self._directories

    def read_text(self, target: Path) -> str:
        """Read a resolved file, falling back to its indexed blob only if absent."""
        if self._entries is None:
            return target.read_text(errors="replace")
        tracked = self._tracked_target(target)
        if tracked is None:
            raise FileNotFoundError(target)
        try:
            return tracked.read_text(errors="replace")
        except FileNotFoundError:
            return self._index_text(tracked)


def resolve(root: Path, path: str) -> Path | None:
    """Resolve one path; reuse ReferenceResolver for a batch or content reads."""
    return ReferenceResolver(root).resolve(path)


def iter_refs(kb: Path) -> Iterator[tuple[str, int, str]]:
    """Yield (knowledge-relative file, line, span) in the checker's existing order."""
    for md in sorted(kb.rglob("*.md")):
        rel = md.relative_to(kb).as_posix()
        if rel == DERIVED:
            continue
        for n, line in enumerate(md.read_text().splitlines(), 1):
            for span in REF.findall(line):
                if looks_like_ref(span):
                    yield rel, n, span


def contains_symbol(text: str, symbol: str) -> bool:
    """A whole-word occurrence, not proof of a definition or a true sentence."""
    name = symbol.split("(")[0]
    return bool(re.search(rf"\b{re.escape(name)}\b", text))


def has_symbol(resolver: ReferenceResolver, target: Path, symbol: str) -> bool:
    """Use the same tracked/index content boundary as path resolution."""
    return not resolver.is_dir(target) and contains_symbol(resolver.read_text(target), symbol)


def check_refs(root: Path, kb: Path) -> tuple[list[str], int]:
    problems, checked = [], 0
    resolver = ReferenceResolver(root)
    for rel, n, span in iter_refs(kb):
        checked += 1
        path, _, symbol = span.partition("::")
        target = resolver.resolve(path)
        if target is None:
            problems.append(f"{rel}:{n}: `{span}`: no such path")
        elif symbol and not has_symbol(resolver, target, symbol):
            name = symbol.split("(")[0]
            problems.append(f"{rel}:{n}: `{span}`: {name} not found in {path}")
    return problems, checked


def check_budget(kb: Path) -> tuple[list[str], int]:
    core = kb / "core"
    chars = sum(len(p.read_text()) for p in core.glob("*.md")) if core.is_dir() else 0
    tokens = round(chars / CHARS_PER_TOKEN)
    problems = []
    if tokens > CORE_BUDGET_TOKENS:
        problems.append(f"core/: ~{tokens} tokens, over the {CORE_BUDGET_TOKENS} budget: prune it")
    return problems, tokens


def check_derived(root: Path, kb: Path) -> list[str]:
    script = Path(__file__).with_name("capabilities.py")
    out = kb.relative_to(root) / DERIVED
    r = subprocess.run([sys.executable, str(script), "--repo", str(root), "--check", "--strict", "--out", str(out)],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return []
    return [f"{DERIVED}: {line}" for line in (r.stdout + r.stderr).splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="repository root (holds .temper/)")
    args = ap.parse_args()
    root = Path(args.repo).resolve()
    kb = root / ".temper"
    if not kb.is_dir():
        print(f"no .temper/ in {root}")
        return 1
    budget, tokens = check_budget(kb)
    refs, checked = check_refs(root, kb)
    problems = refs + budget + check_derived(root, kb)
    for p in problems:
        print(p)
    if not problems:
        print(f"ok: {checked} refs resolve, core/ ~{tokens}/{CORE_BUDGET_TOKENS} tokens, capabilities agree")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
