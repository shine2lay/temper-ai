"""Stage 4, directions: two or more quick clickable directions (04-directions/<id>/index.html), each with its
measured checks, and directions.json; the owner's direction gate follows. Stub: fixture mode only."""
from __future__ import annotations

from .fixture_stage import run_fixture
from .workspace import Workspace


def run(ws: Workspace, data: str) -> dict:
    return run_fixture(ws, "directions")
