#!/usr/bin/env python3
"""Print the versions the tests are about to run against.

Three places ran temper's tests and all three installed something different:
GitHub took the newest of everything, the pre-commit hook took whatever was
in the user's site-packages, and the server took uv.lock. Nobody noticed
until master had been red for eight days, because nothing ever said which
versions it had used.

Now every place prints this line first, so the answer is in the log:

    python 3.12.3 · sqlmodel 0.0.37 · fastapi 0.135.1 · sqlalchemy 2.0.44 …

With ``--check`` it also compares what is imported against uv.lock and exits
1 on a difference, which is how the hook proves it used the locked set.
"""

from __future__ import annotations

import argparse
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# The ones whose differences have actually broken temper.
WATCHED = ("sqlmodel", "sqlalchemy", "fastapi", "pydantic", "pytest", "alembic", "psycopg2-binary")


def installed() -> dict[str, str]:
    found = {}
    for name in WATCHED:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            continue
    return found


def locked(lock: Path) -> dict[str, str]:
    """Versions from uv.lock, read without a TOML parser for 3.10 and below."""
    if not lock.exists():
        return {}
    out: dict[str, str] = {}
    name = None
    for line in lock.read_text(encoding="utf-8").splitlines():
        if match := re.match(r'^name = "([^"]+)"', line):
            name = match.group(1)
        elif match := re.match(r'^version = "([^"]+)"', line):
            if name in WATCHED:
                out[name] = match.group(1)
            name = None
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when a version is not the locked one")
    parser.add_argument("--lock", type=Path, default=Path(__file__).resolve().parent.parent / "uv.lock")
    args = parser.parse_args()

    have = installed()
    line = " · ".join([f"python {sys.version.split()[0]}"] + [f"{k} {v}" for k, v in have.items()])
    print(line)

    if not args.check:
        return 0

    want = locked(args.lock)
    wrong = {k: (v, want[k]) for k, v in have.items() if k in want and v != want[k]}
    if wrong:
        print("\nNot the locked versions:", file=sys.stderr)
        for name, (got, expected) in sorted(wrong.items()):
            print(f"  {name}: running {got}, uv.lock says {expected}", file=sys.stderr)
        print("\n  Run `uv sync --frozen --extra dev` and test through `uv run`.", file=sys.stderr)
        return 1
    print(f"(matches uv.lock: {len(want)} packages checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
