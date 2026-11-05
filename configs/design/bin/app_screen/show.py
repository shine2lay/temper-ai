"""Stage 7, show: the checked build shared once on Show&Tell (showtell.json: doc_id, version, url) and the
owner's comments on it (comments.json), in 07-show/; the owner's final gate follows. Stub: fixture mode
only (it never shares)."""
from __future__ import annotations

from .fixture_stage import run_fixture
from .workspace import Workspace


def run(ws: Workspace, data: str) -> dict:
    return run_fixture(ws, "show")
