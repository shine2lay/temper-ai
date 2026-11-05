#!/usr/bin/env python3
"""Design's app-screen workflow (design_app_screen_v1): run one step on a workspace, or pack a known case.

    design_app_screen.py <step> --workspace W [--product P --mode real|fixture]   (the workflow's script agent)
    design_app_screen.py pack --case DIR --workspace W                          (host, before a fixture run)
    design_app_screen.py freeze --case DIR --product P --source TEXT            (host, once per known case)
    design_app_screen.py verify --case DIR                                      (host)

Steps: intake, existing, ground, directions, gate_direction, build, checks, review, show, gate_final,
gate_final_next, handoff. A step's text input (a gate's answer) comes in env APP_SCREEN_DATA. After each
step its output is validated against its contract (app_screen/contracts.py); a broken output fails the
step with every file, field and reason. Prints one JSON line (the step's structured output).
Stages, workspace and contracts: docs/design-app-screen.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from app_screen import (  # noqa: E402
    build,
    checks,
    contracts,
    directions,
    existing,
    gates,
    ground,
    handoff,
    intake,
    known_case,
    show,
)
from app_screen.fixture_stage import NotBuiltError  # noqa: E402
from app_screen.workspace import MODES, STEPS, Workspace, WorkspaceError  # noqa: E402

HOST_COMMANDS = ("pack", "freeze", "verify")
RUNS = {"intake": intake.run, "existing": existing.run, "ground": ground.run, "directions": directions.run,
        "gate_direction": lambda ws, raw: gates.answer(ws, "direction", raw), "build": build.run,
        "checks": checks.run, "review": checks.review, "show": show.run,
        "gate_final": lambda ws, raw: gates.answer(ws, "final", raw),
        "gate_final_next": lambda ws, raw: gates.final_next(ws), "handoff": handoff.run}
FAILURES = (WorkspaceError, contracts.ContractError, known_case.KnownCaseError, gates.GateError, NotBuiltError,
            OSError, ValueError, KeyError)


def run_step(step: str, workspace: str, product: str | None, mode: str, raw: str) -> dict:
    ws = Workspace(workspace)
    if product:
        ws.start(product, mode)
    elif ws.mode != mode:
        raise WorkspaceError(f"run.json says mode {ws.mode}, the step was called with {mode}")
    ws.mark(step, "running")
    try:
        result = RUNS[step](ws, raw)
        files = contracts.validate(step, ws)
    except FAILURES as exc:
        ws.mark(step, "failed", reason=str(exc)[:500])
        raise
    ws.mark(step, "done")
    return {"step": step, "mode": ws.mode, "valid": True, "checked": len(files), **result}


def host(command: str, args: argparse.Namespace) -> dict:
    if not args.case:
        raise WorkspaceError(f"{command} needs --case DIR")
    if command == "freeze":
        if not args.product or not args.source:
            raise WorkspaceError("freeze needs --product and --source")
        record = known_case.freeze(args.case, args.product, args.source)
        return {"case": record["case"], "files": len(record["files"])}
    if command == "verify":
        record = known_case.verify(args.case)
        return {"case": record["case"], "files": len(record["files"]), "verified": True}
    if not args.workspace:
        raise WorkspaceError("pack needs --workspace W")
    return known_case.pack(args.case, args.workspace)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("step", choices=STEPS + HOST_COMMANDS)
    parser.add_argument("--workspace")
    parser.add_argument("--product")
    parser.add_argument("--mode", choices=MODES, default="real")
    parser.add_argument("--case")
    parser.add_argument("--source")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        if args.step in HOST_COMMANDS:
            result = host(args.step, args)
        else:
            if not args.workspace:
                raise WorkspaceError(f"{args.step} needs --workspace W")
            result = run_step(args.step, args.workspace, args.product, args.mode, os.environ.get("APP_SCREEN_DATA", ""))
    except FAILURES as exc:
        # Our own messages only; never environment or session data.
        raise SystemExit(f"{args.step}: {exc}") from None
    result["seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
