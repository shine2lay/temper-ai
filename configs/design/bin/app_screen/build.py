"""Stage 5, build: the clickable prototype for the chosen direction (05-build/index.html, shell/, screens/,
styles/tokens.css, fixture.json, build.json), one file per screen and every state.

Stage 5a (deterministic half, rule 17):
- Validates 03-ground/ and 04-directions/ inputs at the boundary (build_scaffold.validate_inputs).
- Writes the contract-valid prototype skeleton with data-build-placeholder="<screen-id>" per screen
  (build_scaffold.write_scaffold).
- Verifies the written build with deterministic checks (build_check.check_workspace).

Fixture mode: copies the known case's 05-build/ output (run_fixture).
"""
from __future__ import annotations

import json

from . import build_check, build_scaffold, model_step
from .build_scaffold import BuildInputError
from .fixture_stage import run_fixture
from .workspace import Workspace


class BuildError(BuildInputError):
    """Stage 5 build failed input validation or deterministic build checks."""


def check(ws: Workspace, raw: str = "") -> dict:
    """Run deterministic Stage 5a checks on 05-build/."""
    if ws.mode == "fixture":
        return {"verdict": "ok", "source": "known case"}
    return build_check.check_workspace(ws, pass_name="final")


def run(ws: Workspace, data: str = "") -> dict:
    """Run Stage 5 build: fixture mode copies known case; real mode writes and checks the Stage 5a skeleton."""
    if ws.mode == "fixture":
        r = ws.next_round()
        out = run_fixture(ws, "build")
        path = ws.folder("build") / "build.json"
        doc = json.loads(path.read_text())
        doc["round"] = r
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        return {**out, "round": r}
    scaffold = build_scaffold.write_scaffold(ws)
    found = build_check.check_workspace(ws, pass_name="final")
    if found["problems"]:
        raise BuildError(model_step.failure(found["problems"], "05-build/build.json"))
    return {
        "direction": scaffold["chosen_direction"],
        "round": scaffold["round"],
        "placeholder": True,
        "verdict": found["verdict"],
        **found["counts"],
    }
