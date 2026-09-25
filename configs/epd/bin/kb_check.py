#!/usr/bin/env python3
"""Check a repository's .temper/ knowledge folder against the code it describes.

.temper/ is what temper's agents read about a repo before they design, plan or test a change
(its README says who reads what). A fact in it that has quietly gone false is worse than no fact:
it is read with the same confidence as a true one. The retro keeps it true after every merge;
this is the part of that job a script can do:

  REFS     every backticked `path` or `path::symbol` in the written files still resolves. A path is
           tried from the repo root, then backend/rollcall/, then frontend/src/; a symbol must
           appear in that file as a whole word. Line numbers are never used: they drift every merge.
  BUDGET   core/ is read by every agent on every run, so it has a token budget (estimated as
           characters / 3.5). Over budget means prune, not raise the budget.
  DERIVED  topics/capabilities.md agrees with the code (capabilities.py --check).

Stdlib only, like capabilities.py: it runs inside any checkout, with nothing installed.

    kb_check.py --repo PATH            exit 1 when anything is wrong, printing each problem
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
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


def resolve(root: Path, path: str) -> Path | None:
    for base in BASES:
        p = root / base / path
        if p.exists():
            return p
    return None


def check_refs(root: Path, kb: Path) -> tuple[list[str], int]:
    problems, checked = [], 0
    for md in sorted(kb.rglob("*.md")):
        rel = md.relative_to(kb).as_posix()
        if rel == DERIVED:
            continue
        for n, line in enumerate(md.read_text().splitlines(), 1):
            for span in REF.findall(line):
                if not looks_like_ref(span):
                    continue
                checked += 1
                path, _, symbol = span.partition("::")
                target = resolve(root, path)
                if target is None:
                    problems.append(f"{rel}:{n}: `{span}`: no such path")
                elif symbol:
                    name = symbol.split("(")[0]
                    if target.is_dir() or not re.search(rf"\b{re.escape(name)}\b", target.read_text(errors="replace")):
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
