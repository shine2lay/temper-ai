"""The Pi lane's run process, in a process of its own as pi-worker starts it (run_child.py).

H2 (SW-76): the run process imports every temper module before its first turn, so code that
changes on disk during a run (the lane mounts temper_ai/ from the host) can't be half old,
half new inside one run. During its one model-free turn the run reaches every module of the
Pi agent and runner packages, as a long run's later steps would; afterwards no temper module
was first imported after the first turn began. With the eager import switched off, some
were (the control: the check can see a late import).

The secret key: pi-worker holds no TEMPER_SECRET_KEY, and a Pi run never reads the key nor
makes ~/.temper/secret.key (its only reader is MCP's OAuth, and the Pi-only rule refuses MCP
servers).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_pi_agent import support as sup

pytestmark = pytest.mark.timeout(180)


def _run_child(tmp_path: Path, *, eager: bool) -> dict:
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    box_json = sup.make_box_config(tmp_path / "box")
    url = f"sqlite:///{tmp_path / 'lane.db'}"
    env = {k: v for k, v in os.environ.items()
           if k not in sup._DROP_ENV and not k.startswith("TEMPER_DOCKER_")
           and k not in ("TEMPER_SECRET_KEY", "TEMPER_DATABASE_URL", "DATABASE_URL")}
    env.update({"PYTHONPATH": str(sup.WORKTREE), "HOME": str(home),
                "TEMPER_DATABASE_URL": url, "TEMPER_LOG_DIR": str(tmp_path / "logs"),
                "TEMPER_LANE": "pi", "TEMPER_PI_AGENT": "1", "TEMPER_SPAWNER": "subprocess",
                "TEMPER_PI_BOX_CONFIG": str(box_json), "TEMPER_PICK_UP_INTERRUPTED": "0",
                "TEMPER_PI_DRAIN_MARK": str(tmp_path / "drain" / "draining")})
    args = {"db_url": url, "workspace": str(workspace), "eager": eager}
    proc = subprocess.run(
        [sys.executable, "-m", "tests.test_runner.pi_lane.run_child", json.dumps(args)],
        cwd=sup.WORKTREE, env=env, capture_output=True, text=True, timeout=150)
    lines = [json.loads(x) for x in proc.stdout.splitlines() if x.startswith("{")]
    ran = next((x for x in lines if x.get("event") == "ran"), None)
    assert proc.returncode == 0 and ran, (proc.returncode, lines, proc.stderr[-3000:])
    # One turn, then the step asks the owner and the run parks: its process leaves the row
    # running for the watcher's reaper to let go (C7).
    assert ran["exit"] == 0 and ran["turned"] and ran["turns"] == ["completed"], ran
    assert ran["status"] in ("running", "waiting", "completed"), ran
    assert ran["net_attempts"] == [], ran
    return {**ran, "home": home}


def test_after_a_one_turn_run_no_temper_module_was_first_imported_after_the_turn_began(
        tmp_path):
    ran = _run_child(tmp_path, eager=True)
    assert ran["late"] == []


def test_without_the_eager_import_some_modules_come_after_the_turn_began(tmp_path):
    """The control: the check above can see a late import."""
    ran = _run_child(tmp_path, eager=False)
    assert ran["late"], "no temper module came after the first turn even without the " \
                        "eager import: the check above proves nothing"


def test_a_pi_run_never_reads_the_secret_key_nor_makes_one(tmp_path):
    ran = _run_child(tmp_path, eager=True)
    assert ran["key_loads"] == 0
    assert ran["key_opens"] == []
    assert not (ran["home"] / ".temper").exists()
