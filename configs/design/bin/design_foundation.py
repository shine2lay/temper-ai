#!/usr/bin/env python3
"""Design's foundation workflow CLI (design_foundation_v1): run one step on a workspace and validate contracts.

    design_foundation.py <step> --workspace W [--product P] [--brief PATH] [--render-surface S]

Steps: brief, directions_collect, directions_check, directions, proof, gate_direction,
build_collect, build_check, build, checks, gate_final, handoff.
Gate response or draft text comes via --data or env FOUNDATION_DATA.
Every step reads strictly through foundation.workspace.Workspace (enforcing STEP_INPUTS) and validates
every written artifact against foundation.contracts (closed DTCG tokens.json schema, DESIGN.md section
contract, and 7-section brief contract). Prints one JSON line (the step's structured output).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from app_screen.gates import GateError  # noqa: E402
from foundation import brief, contracts, gates, proof, stubs  # noqa: E402
from foundation.workspace import STEPS, Workspace, WorkspaceError  # noqa: E402

FAILURES = (
    WorkspaceError,
    contracts.ContractError,
    brief.BriefError,
    GateError,
    OSError,
    ValueError,
    KeyError,
    RuntimeError,
)


def _as_bool(raw: str | bool | None) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in ("1", "true", "yes")


def run_step(
    step: str,
    *,
    workspace: str,
    product: str | None = None,
    brief_path: str | None = None,
    render_surface: str | None = None,
    raw_data: str = "",
    base_url: str | None = None,
    stack_commit: str | None = None,
    stack_ref: str | None = None,
    allow_red_commit: bool = False,
) -> dict[str, Any]:
    if step not in STEPS:
        raise WorkspaceError(f"unknown foundation step {step!r}; declared steps: {', '.join(STEPS)}")

    ws = Workspace(workspace)
    try:
        if step == "brief":
            if not product:
                raise WorkspaceError("brief step requires --product")
            return brief.run(
                ws,
                product=product,
                brief_path=brief_path,
                render_surface=render_surface or "app",
            )

        if product and not ws.run_file.is_file():
            ws.start(product)

        ws.mark(step, "running")
        if step == "directions_collect":
            return stubs.directions_collect(ws)
        if step == "directions_check":
            return stubs.directions_check(ws, draft=raw_data)
        if step == "directions":
            return stubs.directions_finish(ws)
        if step == "proof":
            return proof.run(
                ws,
                base_url=base_url,
                commit=stack_commit,
                ref=stack_ref,
                allow_red_commit=allow_red_commit,
            )
        if step == "gate_direction":
            return gates.answer(ws, "direction", raw_data)
        if step == "build_collect":
            return stubs.build_collect(ws)
        if step == "build_check":
            return stubs.build_check(ws, draft=raw_data)
        if step == "build":
            return stubs.build_finish(ws)
        if step == "checks":
            return stubs.checks_run(
                ws,
                base_url=base_url,
                commit=stack_commit,
                ref=stack_ref,
                allow_red_commit=allow_red_commit,
            )
        if step == "gate_final":
            return gates.answer(ws, "final", raw_data)
        if step == "handoff":
            return stubs.handoff_run(ws)
        raise WorkspaceError(f"unhandled foundation step {step!r}")
    except FAILURES as exc:
        if ws.run_file.is_file() and step in STEPS:
            ws.mark(step, "failed", reason=str(exc)[:500])
        raise


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="design_foundation.py", description=__doc__)
    p.add_argument("step", choices=STEPS, help="Foundation step to execute")
    p.add_argument("--workspace", required=True, help="Foundation workspace path (<repo>/.temper/design)")
    p.add_argument("--product", default="", help="Product slug (required for Stage 1 brief)")
    p.add_argument("--brief", default="", help="Product brief path relative to repo root (default .temper/product/brief.md)")
    p.add_argument("--render-surface", default="", help="Render surface mode: app | sample | none")
    p.add_argument("--data", default="", help="Gate answer JSON or model draft JSON (overrides FOUNDATION_DATA)")
    p.add_argument("--base-url", default="", help="Provisioned app instance base URL from stack_up_ref")
    p.add_argument("--stack-commit", default="", help="Provisioned app commit SHA from stack_up_ref")
    p.add_argument("--stack-ref", default="", help="Git ref passed to stack_up_ref")
    p.add_argument("--allow-red-commit", default="", help="Whether red CI commits are explicitly permitted")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_data = args.data or os.environ.get("FOUNDATION_DATA", "")
    base_url = args.base_url or os.environ.get("FOUNDATION_BASE_URL", "")
    stack_commit = args.stack_commit or os.environ.get("FOUNDATION_STACK_COMMIT", "")
    stack_ref = args.stack_ref or os.environ.get("FOUNDATION_STACK_REF", "")
    allow_red_raw = args.allow_red_commit or os.environ.get("FOUNDATION_ALLOW_RED_COMMIT", "")

    try:
        result = run_step(
            args.step,
            workspace=args.workspace,
            product=args.product.strip() or None,
            brief_path=args.brief.strip() or None,
            render_surface=args.render_surface.strip() or None,
            raw_data=raw_data,
            base_url=base_url.strip() or None,
            stack_commit=stack_commit.strip() or None,
            stack_ref=stack_ref.strip() or None,
            allow_red_commit=_as_bool(allow_red_raw),
        )
    except FAILURES as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
