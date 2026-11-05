#!/usr/bin/env python3
"""Design's app-screen workflow (design_app_screen_v1): run one step on a workspace, or pack a known case.

    design_app_screen.py <step> --workspace W [--product P --mode real|fixture]   (the workflow's script agent)
    design_app_screen.py pack --case DIR --workspace W                          (host, before a fixture run)
    design_app_screen.py freeze --case DIR --product P --source TEXT            (host, once per known case)
    design_app_screen.py verify --case DIR                                      (host)
    design_app_screen.py collect --product P --description TEXT [--request TEXT --request-source TEXT]
        [--doc d_x[@2,3]] [--record dr-x[:q1,q2]] [--history] (--out FILE | --workspace W)   (host, intake)
    design_app_screen.py grade-intake --case DIR --workspace W                  (host, intake trials)

Steps: intake_collect, intake_check, intake, existing, ground, directions, gate_direction, build, checks, review, show, gate_final,
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
    intake_grade,
    intake_sources,
    known_case,
    show,
)
from app_screen.fixture_stage import NotBuiltError  # noqa: E402
from app_screen.workspace import MODES, STEPS, Workspace, WorkspaceError  # noqa: E402

HOST_COMMANDS = ("pack", "freeze", "verify", "collect", "grade-intake")
RUNS = {"intake_collect": intake.collect, "intake_check": intake.check, "intake": intake.run, "existing": existing.run, "ground": ground.run, "directions": directions.run,
        "gate_direction": lambda ws, raw: gates.answer(ws, "direction", raw), "build": build.run,
        "checks": checks.run, "review": checks.review, "show": show.run,
        "gate_final": lambda ws, raw: gates.answer(ws, "final", raw),
        "gate_final_next": lambda ws, raw: gates.final_next(ws), "handoff": handoff.run}
FAILURES = (WorkspaceError, contracts.ContractError, known_case.KnownCaseError, gates.GateError, NotBuiltError,
            intake.IntakeError, intake_sources.SourcesError, OSError, ValueError, KeyError)


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


def _ids(spec: str, sep: str) -> tuple[str, list[str] | None]:
    head, _, tail = spec.partition(sep)
    return head, [t for t in tail.split(",") if t] or None


def collect(args: argparse.Namespace) -> dict:
    """Host: the sources document for intake, from a request, Show&Tell docs, dialog records, history."""
    if not args.product or not args.description:
        raise WorkspaceError("collect needs --product and --description (the product in one line)")
    if bool(args.out) == bool(args.workspace):
        raise WorkspaceError("collect needs one of --out FILE or --workspace W")
    parts = []
    if args.request:
        parts.append(intake_sources.request_item(args.request, args.request_source or ""))
    parts += intake_sources.history_items(args.product) if args.history else []
    for spec in args.doc or []:
        doc_id, versions = _ids(spec, "@")
        parts += intake_sources.showtell_items(doc_id, [int(v) for v in versions] if versions else None)
    for spec in args.record or []:
        record_id, questions = _ids(spec, ":")
        parts += intake_sources.record_items(record_id, question_ids=questions)
    if not parts:
        raise WorkspaceError("collect found nothing: give --request, --doc, --record or --history")
    doc = intake_sources.build(args.product, args.description, parts)
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if args.out:
        out = Path(args.out)
    else:
        ws = Workspace(args.workspace)
        ws.start(args.product, "real")
        out = ws.folder("intake") / intake.SOURCES
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return {"items": len(doc["items"]), "kinds": sorted({i["kind"] for i in doc["items"]}), "written": str(out)}


def host(command: str, args: argparse.Namespace) -> dict:
    if command == "collect":
        return collect(args)
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
        raise WorkspaceError(f"{command} needs --workspace W")
    if command == "grade-intake":
        return intake_grade.grade(args.case, args.workspace)
    return known_case.pack(args.case, args.workspace)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("step", choices=STEPS + HOST_COMMANDS)
    parser.add_argument("--workspace")
    parser.add_argument("--product")
    parser.add_argument("--mode", choices=MODES, default="real")
    parser.add_argument("--case")
    parser.add_argument("--source")
    parser.add_argument("--description")
    parser.add_argument("--request")
    parser.add_argument("--request-source")
    parser.add_argument("--doc", action="append")
    parser.add_argument("--record", action="append")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--out")
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
