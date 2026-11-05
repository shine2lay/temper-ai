"""Stage 5, build: the chosen direction built out (shell, one file per screen, index.html, build.json) in
05-build/. Each pass starts a new round; review findings or the owner's final comments bring it back as
targeted edits. Stub: fixture mode only."""
from __future__ import annotations

import json

from .fixture_stage import run_fixture
from .workspace import Workspace


def run(ws: Workspace, data: str) -> dict:
    n = ws.next_round()
    out = run_fixture(ws, "build")
    path = ws.folder("build") / "build.json"
    record = json.loads(path.read_text())
    record["round"] = n
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    return {**out, "round": n}
