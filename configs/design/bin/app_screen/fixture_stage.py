"""What a stage does until its real version is built: in fixture mode, copy the known case's output.

A real-mode call of an unbuilt stage fails loud instead of pretending; the stage's own task (W1-W5)
replaces its stub module's run() and keeps the same contract.
"""
from __future__ import annotations

from . import known_case
from .workspace import Workspace


class NotBuiltError(RuntimeError):
    """The real stage is not built yet."""


def run_fixture(ws: Workspace, step: str) -> dict:
    if ws.mode != "fixture":
        raise NotBuiltError(f"{step}: the real stage is not built yet; only fixture mode runs it "
                            "(docs/design-app-screen.md, 'Stage status')")
    files = known_case.copy_stage(ws, step)
    return {"source": "known case", "files": len(files)}
