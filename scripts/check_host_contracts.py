#!/usr/bin/env python3
"""Locked checks for the explicitly selected host-contract leaf, never an alternate hook.

The ordinary hook and CI call this after locked sync. Reclassify the real diff, then copy only
tracked supplier blobs to a temporary check tree. No application, parent conftest, private adapter,
untracked helper or editable-project import path accompanies it. This is not a hostile-code sandbox
or runtime qualification: supplier code is still reviewed code running as the test user.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from select_tests import (
    HOST_CONTRACTS,
    HOST_PACKAGE,
    HOST_TESTS,
    Git,
    SelectionError,
    _parse,
    host_contract_path,
    run,
)


def check(command: list[str], root: Path, env: dict[str, str]) -> None:
    # Stream normal test/tool diagnostics, but never reprint argv/output in an exception.
    code = subprocess.call(command, cwd=root, env=env)
    if code:
        raise SystemExit(code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--phase", choices=("all", "lint", "type", "test"), default="all")
    parser.add_argument("--junitxml", type=Path)
    args = parser.parse_args(argv)
    repo = Path.cwd()
    selector_args = ["--repo", str(repo), "--head", args.head]
    if args.base is not None:
        selector_args += ["--base", args.base]
    try:
        selection, _ = run(_parse(selector_args))
        if selection.route != HOST_CONTRACTS:
            raise SelectionError("change requires ordinary checks, not the host-contract route")
        git = Git(repo)
        paths = {p for p in git.files(selection.head) if host_contract_path(p)}
        paths.update(("pyproject.toml", "uv.lock"))
        blobs = git.blobs(selection.head, sorted(paths))
        if set(blobs) != paths:
            raise SelectionError("checked tree is incomplete")
    except (SelectionError, OSError, ValueError):
        print("Host-contract check refused: cannot establish a complete exact leaf tree.", file=sys.stderr)
        return 2

    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "TEMPER_TEST_DATABASE_URL"):
        env.pop(name, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    with tempfile.TemporaryDirectory(prefix="host-contract-check-") as folder:
        root = Path(folder)
        for relative, body in blobs.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        checks = root / "_checks"
        checks.mkdir()
        for source in ("scripts/host_contract_pytest.py", "tests/machine_slot.py", "scripts/show_versions.py"):
            (checks / Path(source).name).write_bytes((repo / source).read_bytes())
        # This conftest is check infrastructure, not the application's tests/conftest.py.
        (root / "conftest.py").write_text("from _checks.host_contract_pytest import pytest_configure\n")
        (root / "pytest.ini").write_text("[pytest]\ntimeout = 120\n")
        # A dedicated type configuration: the application's ignore_missing_imports=True
        # is deliberately inapplicable here. mypy has no inverse CLI flag for it.
        (root / "mypy.ini").write_text("[mypy]\nignore_missing_imports = False\nfollow_imports = error\nno_site_packages = True\n")
        python = [sys.executable, "-I"]
        check([*python, str(checks / "show_versions.py"), "--check", "--tools", "--lock", str(root / "uv.lock")], root, env)
        if args.phase in ("all", "lint"):
            print("Host contracts: locked lint", flush=True)
            check([*python, "-m", "ruff", "check", HOST_PACKAGE, HOST_TESTS], root, env)
        if args.phase in ("all", "type"):
            print("Host contracts: locked type check", flush=True)
            check([*python, "-m", "mypy", "--config-file", "mypy.ini", HOST_PACKAGE], root, env)
        if args.phase in ("all", "test"):
            print("Host contracts: locked tests (isolated tree)", flush=True)
            command = [*python, str(checks / "host_contract_pytest.py")]
            if args.junitxml:
                command += ["--junitxml", str(args.junitxml.resolve())]
            check(command, root, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
