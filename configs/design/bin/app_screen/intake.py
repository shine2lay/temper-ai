"""Stage 1, intake: the owner's request as requirements (his words verbatim, source, kind, what each maps to)
and the open clarification questions (rule 33), in 01-request/. Stub: fixture mode only."""
from __future__ import annotations

from .fixture_stage import run_fixture
from .workspace import Workspace


def run(ws: Workspace, data: str) -> dict:
    return run_fixture(ws, "intake")
