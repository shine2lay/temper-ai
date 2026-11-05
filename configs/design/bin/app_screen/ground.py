"""Stage 3, ground: the shared fixture every screen uses, the product's design files (DESIGN.md, tokens.json)
when it has them, and the screens x states inventory, in 03-ground/. Stub: fixture mode only."""
from __future__ import annotations

from .fixture_stage import run_fixture
from .workspace import Workspace


def run(ws: Workspace, data: str) -> dict:
    return run_fixture(ws, "ground")
