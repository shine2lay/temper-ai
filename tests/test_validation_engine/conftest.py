"""Shared set-up for the validation engine's tests (configs/validation, docs/validation_engine.md).

The engine's steps are plain scripts in configs/validation/bin, run by the workflow's script agents as
`python3 ve.py <step>`. The tests run the same command line, in a temporary state folder, with the
HTTP crowd (no browser) and an empty rails file: nothing here reaches a real service.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "configs" / "validation"
BIN = ENGINE / "bin"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

IDEA = (
    "Hourly-hire screening for blue-collar employers: an assistant that screens every applicant for a shift "
    "within minutes and books the qualified ones into interviews."
)


def run_ve(*args: str, ok_codes: tuple[int, ...] = (0,)) -> dict[str, Any]:
    """One engine step, as the workflow runs it; returns the JSON it prints on its last line."""
    done = subprocess.run([sys.executable, str(BIN / "ve.py"), *args], capture_output=True, text=True, timeout=120)
    assert done.returncode in ok_codes, f"ve.py {args[0]} exited {done.returncode}: {done.stderr[-2000:]}"
    last = done.stdout.strip().splitlines()[-1]
    out = json.loads(last)
    out["_stdout"], out["_stderr"] = done.stdout, done.stderr
    return out


@pytest.fixture(scope="session")
def copy_hourly() -> dict[str, Any]:
    return json.loads((FIXTURES / "copy_hourly.json").read_text())


@pytest.fixture(scope="session")
def dry_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """A whole dry run, step by step: setup, the page (from a fixed copy), deploy, the synthetic crowd,
    collect, decide. Interviews are asked for, so the Rung 4 hand-off is decided too."""
    root = tmp_path_factory.mktemp("ve-dry-run")
    rails = root / "no-rails.env"
    rails.write_text("")
    setup = run_ve("setup", "--workspace", str(root), "--idea", IDEA, "--idea-id", "hourly-screening",
                   "--rails-file", str(rails), "--interviews", "yes", "--segment", "US multi-site hourly employers")
    d = Path(setup["idea_dir"])
    (d / "page").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "copy_hourly.json", d / "page" / "copy.json")
    check = run_ve("check-copy", "--dir", str(d))
    deploy = run_ve("deploy", "--dir", str(d))
    simulate = run_ve("simulate", "--dir", str(d), "--engine", "http", "--screenshots", "no")
    collect = run_ve("collect", "--dir", str(d))
    decide = run_ve("decide", "--dir", str(d))
    return {"root": root, "dir": d, "rails": rails, "setup": setup, "check": check, "deploy": deploy,
            "simulate": simulate, "collect": collect, "decide": decide}
