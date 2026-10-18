"""Tests for the weekly trim's host side: scripts/systemd/*.service|timer and scripts/temper-trim.

The trim timer once named docker.service as a hard dependency. It is a user unit, the user's
systemd can't see system units, so the timer failed with "Unit docker.service not found" and no
weekly pass ever ran. The wrapper now waits for the database itself.

Covers:
- every unit in scripts/systemd (all installed as user units) hard-depends only on units the
  user's systemd has: its own units and the user manager's standard targets
- temper-trim runs the trim once the database answers
- temper-trim stops with exit 75, and runs nothing, when the database never answers
"""

from __future__ import annotations

import re
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "scripts" / "systemd"
WRAPPER = ROOT / "scripts" / "temper-trim"

# Units every user's systemd has, whatever is installed.
USER_MANAGER_UNITS = {"default.target", "timers.target", "basic.target", "sockets.target",
                      "paths.target", "shutdown.target", "exit.target"}
HARD_DEPENDENCY = re.compile(r"^(Requires|Requisite|BindsTo)=(.*)$")


def test_user_units_hard_depend_only_on_units_the_user_manager_has():
    shipped = {p.name for p in UNITS.iterdir() if p.suffix in (".service", ".timer")}
    unknown = []
    for unit in sorted(UNITS.iterdir()):
        if unit.suffix not in (".service", ".timer"):
            continue
        for line in unit.read_text().splitlines():
            found = HARD_DEPENDENCY.match(line.strip())
            if found:
                unknown += [f"{unit.name}: {found.group(1)}={name}"
                            for name in found.group(2).split()
                            if name not in shipped | USER_MANAGER_UNITS]
    assert unknown == []


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_wrapper(tmp_path: Path, port: int) -> tuple[subprocess.CompletedProcess, Path]:
    """Run scripts/temper-trim against a made-up checkout whose .env names ``port``, with a
    stand-in ``uv`` that only records its arguments."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text(f"POSTGRES_PORT={port}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    called = tmp_path / "uv-args.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{called}'\n")
    fake_uv.chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path),
           "TEMPER_REPO": str(repo), "TEMPER_TRIM_WAIT_S": "0"}
    done = subprocess.run(["bash", str(WRAPPER), "--dry-run"], env=env, capture_output=True,
                          text=True, timeout=60)
    return done, called


def test_wrapper_runs_the_trim_once_the_database_answers(tmp_path):
    with socket.socket() as database:
        database.bind(("127.0.0.1", 0))
        database.listen()
        done, called = _run_wrapper(tmp_path, database.getsockname()[1])
    assert done.returncode == 0, done.stderr
    assert called.read_text().split() == ["run", "--quiet", "python", "-m",
                                          "temper_ai.cli.main", "trim", "--dry-run"]


def test_wrapper_stops_with_exit_75_when_the_database_never_answers(tmp_path):
    port = _free_port()
    done, called = _run_wrapper(tmp_path, port)
    assert done.returncode == 75
    assert f"the database at localhost:{port} did not answer within 0 s" in done.stderr
    assert "nothing was trimmed" in done.stderr
    assert not called.exists()
