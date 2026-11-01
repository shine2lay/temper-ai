"""Execute the CI selection entry against fixed event contexts, without GitHub."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("event,ref,base,expected", [
    ("push", "refs/heads/master", "", ["--full", "--head", "HEAD"]),
    ("push", "refs/heads/feature", "", ["--base", "origin/master", "--head", "HEAD"]),
    ("pull_request", "refs/pull/7/merge", "master", ["--base", "origin/master", "--head", "HEAD"]),
    ("pull_request", "refs/heads/master", "release", ["--base", "origin/release", "--head", "HEAD"]),
])
def test_master_backstop_and_branch_selection_are_distinct(tmp_path, event, ref, base, expected):
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    step = next(s for s in workflow["jobs"]["select"]["steps"] if s.get("id") == "pick")
    assert step["env"]["REF"] == "${{ github.ref }}"
    assert step["env"]["EVENT"] == "${{ github.event_name }}"
    assert step["env"]["PR_BASE"] == "${{ github.base_ref }}"
    # Capture the invoked argv, not a substring assertion on the workflow source.
    program = tmp_path / "python3"
    program.write_text(f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
                       "Path(os.environ['PICK_ARGV']).write_text(json.dumps(sys.argv[1:]))\n")
    program.chmod(0o755)
    output = tmp_path / "outputs"
    argv_file = tmp_path / "argv.json"
    env = dict(os.environ, EVENT=event, REF=ref, PR_BASE=base, BEFORE="previous-commit",
               GITHUB_OUTPUT=str(output), PICK_ARGV=str(argv_file),
               PATH=f"{tmp_path}:{os.environ['PATH']}")
    try:
        exit_code = subprocess.run(["bash", "-euo", "pipefail", "-c", step["run"]],
                                   cwd=tmp_path, env=env, capture_output=True,
                                   timeout=10, check=False).returncode
    except (OSError, subprocess.SubprocessError):
        pytest.fail("CI selection entry did not finish", pytrace=False)
    assert exit_code == 0
    assert json.loads(argv_file.read_text()) == ["scripts/select_tests.py", *expected,
                                                "--explain", "--github-output", str(output)]
