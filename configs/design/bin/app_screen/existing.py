"""Stage 2, existing: today's screens captured and measured (audit.json, by script) and the main journeys with
their problems, each claim with evidence (journeys.json), in 02-existing/. Stub: fixture mode only."""
from __future__ import annotations

from .fixture_stage import run_fixture
from .workspace import Workspace


def run(ws: Workspace, data: str) -> dict:
    return run_fixture(ws, "existing")
