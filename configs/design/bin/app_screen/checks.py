"""Stage 6, checks and review of this round's build, in 06-checks/round-<n>/.

checks: measured checks by script (checks.json: id, value, pass/fail, evidence, element, location).
review: findings (element, location, evidence, severity 0-4, must|should|could|wont) and the verdict:
revise while a Must finding is open (the workflow loops back to build, at most twice), else done.
Stub: fixture mode only.
"""
from __future__ import annotations

import json

from .fixture_stage import run_fixture
from .workspace import Workspace


def run(ws: Workspace, data: str) -> dict:
    return {**run_fixture(ws, "checks"), "round": ws.round}


def review(ws: Workspace, data: str) -> dict:
    out = run_fixture(ws, "review")
    record = json.loads((ws.round_folder() / "review.json").read_text())
    must = sum(1 for f in record["findings"] if f.get("priority") == "must")
    return {**out, "round": ws.round, "verdict": record["verdict"], "must": must}
