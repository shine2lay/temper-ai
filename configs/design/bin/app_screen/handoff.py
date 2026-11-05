"""Stage 8, handoff: the spec per screen for Frontend (spec/*.md), where the design file lives
(design-file.json) and the follow-up work (followup.json), in 08-handoff/. Stub: fixture mode only."""
from __future__ import annotations

from .fixture_stage import run_fixture
from .workspace import Workspace


def run(ws: Workspace, data: str) -> dict:
    return run_fixture(ws, "handoff")
