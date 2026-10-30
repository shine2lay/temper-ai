#!/usr/bin/env python3
"""Classify broken .temper/ references and suggest candidates without changing files.

    kb_refresh.py --repo PATH [--write]

REPORT-ONLY: --write is accepted for CLI compatibility but cannot write. The
initial history had no eligible real SHORT/MOVED rewrite answers (H2 missed).
Candidates are review hints, not historically validated repairs; later evidence
never enables writes implicitly. Run kb_check.py for budget and derived-map checks.

Exit 0: all recognized references resolve; 1: findings or missing .temper/;
2: usage or internal error. Plain folders retain the checker's disk lookup but
have no tracked-file candidate or history search. Generated capabilities are
excluded by the shared iterator. No diff is applied or produced in this mode.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Running this CLI inside the inspected repository must not create __pycache__.
if __name__ == "__main__":
    sys.dont_write_bytecode = True

from kb_check import (  # noqa: E402
    BASES,
    REF,
    ReferenceResolver,
    has_symbol,
    iter_refs,
    looks_like_ref,
)
from kb_reference_history import ReferenceHistory, Rename  # noqa: E402

REPORT_ONLY = (
    "REPORT-ONLY: no files changed. Candidates are review hints, not historically validated repairs."
)
WRITE_REFUSAL = (
    "--write not performed: automatic rewriting is disabled; the initial history provided "
    "no eligible real SHORT/MOVED replay answers (H2 miss)."
)


@dataclass(frozen=True)
class Finding:
    category: str
    detail: str
    candidates: tuple[str, ...] = ()
    suggestion: str | None = None
    symbol_hints: tuple[str, ...] = ()
    renames: tuple[Rename, ...] = ()


class ReferenceClassifier:
    """Classify only; the resolver remains the authority for paths and symbols.

    Exact resolution wins over all hints. A local-only shadow is UNTRACKED.
    Otherwise combine suffix and Git-rename alternatives before choosing a
    unique candidate: symbols never break a tie. Ambiguity includes every path
    and rename record, even when one alternative is not usable now.
    """

    def __init__(self, resolver: ReferenceResolver):
        self.resolver = resolver
        self.root = resolver.root
        self.tracked = resolver.tracked_files
        self.paths = tuple(sorted(p.relative_to(self.root).as_posix() for p in self.tracked or ()))
        self.history = ReferenceHistory(self.root) if self.tracked is not None else None
        self._symbols: dict[str, tuple[str, ...]] = {}
        self._findings: dict[str, Finding | None] = {}

    def _usable_file(self, path: str) -> bool:
        target = self.root / path
        return self.resolver.resolve(path) == target and not self.resolver.is_dir(target)

    def _symbol_hints(self, symbol: str, excluded: tuple[str, ...] = ()) -> tuple[str, ...]:
        name = symbol.split("(")[0]
        if name not in self._symbols:
            self._symbols[name] = tuple(
                path for path in self.paths
                # A reference in the knowledge folder is not evidence for itself.
                if ".temper" not in Path(path).parts and self._usable_file(path)
                and has_symbol(self.resolver, self.root / path, symbol)
            )
        return tuple(path for path in self._symbols[name] if path not in excluded)

    def _base_targets(self, path: str) -> tuple[Path, ...]:
        return tuple(dict.fromkeys(
            target for base in BASES
            if (target := Path(os.path.abspath(self.root / base / path))).is_relative_to(self.root)
        ))

    def _shortest_reference(self, path: str, symbol: str) -> str | None:
        forms = {path.removeprefix(base) for base in BASES if path.startswith(base)}
        for form in sorted(forms, key=lambda value: (len(value), value)):
            span = f"{form}::{symbol}" if symbol else form
            if REF.fullmatch(f"`{span}`") and looks_like_ref(span) and self.resolver.resolve(form) == self.root / path:
                return span
        return None  # e.g. a rename to a suffix the checker does not recognize

    def classify(self, span: str) -> Finding | None:
        if span not in self._findings:
            self._findings[span] = self._classify(span)
        return self._findings[span]

    def _classify(self, span: str) -> Finding | None:
        path, _, symbol = span.partition("::")
        target = self.resolver.resolve(path)
        if target is not None:
            if not symbol or has_symbol(self.resolver, target, symbol):
                return None
            excluded = (target.relative_to(self.root).as_posix(),) if target.is_relative_to(self.root) else ()
            hints = self._symbol_hints(symbol, excluded)
            return Finding(
                "SYMBOL_ELSEWHERE" if hints else "SYMBOL_GONE",
                "Symbol absent from the resolved path; occurrences elsewhere are not repair evidence.",
                symbol_hints=hints,
            )

        bases = self._base_targets(path)
        if self.tracked is not None:
            shadows = tuple(sorted(
                p.relative_to(self.root).as_posix() for p in bases
                if p not in self.tracked and (p.exists() or p.is_symlink())
            ))
            if shadows:
                return Finding("UNTRACKED", "Local paths do not satisfy the tracked reference boundary.", shadows)

        # A suffix is a complete path segment, not a basename substring. The
        # tracked inventory contains files, not directories. Do not search disk.
        suffixes = {name for name in self.paths if name.endswith("/" + path)}
        renames = tuple(sorted({
            rename for base in bases for rename in (self.history.renames_from(base) if self.history else ())
        }))
        moved, historical = set(), set()
        for rename in renames:
            assert self.history is not None
            destination = self.history.git_root / rename.new_path
            # Out-of-scope destinations still conflict with a different suffix
            # candidate. Report that history, but never read or suggest it.
            historical.add(Path(os.path.relpath(destination, self.root)).as_posix())
            if destination.is_relative_to(self.root) and destination in (self.tracked or ()):
                moved.add(destination.relative_to(self.root).as_posix())
        alternatives = tuple(sorted(suffixes | historical))
        candidates = tuple(sorted(suffixes | moved))
        if len(alternatives) > 1 or len(renames) > 1:
            return Finding(
                "AMBIGUOUS", "Multiple alternatives; no target selected, even if only one contains the symbol.",
                alternatives, renames=renames,
            )
        if not candidates or not self._usable_file(candidates[0]):
            return Finding(
                "DELETED", "No resolvable tracked candidate; this is not proof of historical deletion.",
                candidates, symbol_hints=self._symbol_hints(symbol) if symbol else (), renames=renames,
            )
        candidate = candidates[0]
        if symbol and not has_symbol(self.resolver, self.root / candidate, symbol):
            return Finding(
                "SYMBOL_NOT_IN_CANDIDATE", "The unique path candidate does not contain the required symbol.",
                candidates, symbol_hints=self._symbol_hints(symbol, candidates), renames=renames,
            )
        suggestion = self._shortest_reference(candidate, symbol)
        category = "MOVED" if moved else "SHORT"
        return Finding(
            category,
            "Unique tracked candidate; review before editing." if suggestion else
            "The target has no checker-recognized reference form; review manually.",
            candidates, suggestion, renames=renames,
        )


def report(root: Path) -> tuple[list[str], int]:
    """Render deterministic diagnostics without opening anything for writing."""
    kb = root / ".temper"
    if not kb.is_dir():
        return [f"no .temper/ in {root}"], 1
    classifier = ReferenceClassifier(ReferenceResolver(root))
    lines = []
    checked = findings = 0
    for file, number, span in iter_refs(kb):
        checked += 1
        finding = classifier.classify(span)
        if finding is None:
            continue
        findings += 1
        lines.append(f"{file}:{number}: `{span}`: {finding.category}: {finding.detail}")
        for candidate in finding.candidates:
            lines.append(f"  path: `{candidate}`")
        for rename in finding.renames:
            lines.append(f"  git rename {rename.commit}: `{rename.old_path}` -> `{rename.new_path}`")
        if finding.suggestion:
            lines.append(f"  candidate reference (review only): `{finding.suggestion}`")
        for hint in finding.symbol_hints:
            lines.append(f"  symbol occurrence (not a definition or repair): `{hint}`")
    lines.append(f"{checked} refs checked; {findings} findings; 0 writes.")
    return lines, 1 if findings else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=".", help="repository root (holds .temper/)")
    parser.add_argument("--write", action="store_true", help="accepted, but never writes in report-only mode")
    args = parser.parse_args()
    root = Path(args.repo).resolve()
    if not root.is_dir():
        parser.error(f"--repo is not a directory: {root}")
    print(REPORT_ONLY)
    if args.write:
        print(WRITE_REFUSAL)
    try:
        lines, status = report(root)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return status


if __name__ == "__main__":
    sys.exit(main())
