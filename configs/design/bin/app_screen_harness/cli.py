#!/usr/bin/env python3
"""CLI entry point for `app_screen_harness` (outside fixture wrapper for `design_app_screen_v1`)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESIGN_BIN = HERE.parent
if str(DESIGN_BIN) not in sys.path:
    sys.path.insert(0, str(DESIGN_BIN))

from app_screen_harness.cases import DEFAULT_CASE_DIR, prepare_workspace  # noqa: E402, I001
from app_screen_harness.parity import compare_parity, grade_workspace  # noqa: E402
from app_screen_harness.replay import (  # noqa: E402
    MODEL_STEPS,
    STACK_STEPS,
    WORKSPACE_STEPS,
    draft_for_step,
    replay_stack_step,
    replay_workspace_step,
)
from app_screen_harness.runner import answer_gate, run_all, run_stage, run_step  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outside real-mode harness for design_app_screen_v1.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare", help="Prepare a real-mode workspace from a frozen known case.")
    p_prep.add_argument("--case", default=str(DEFAULT_CASE_DIR))
    p_prep.add_argument("--workspace", required=True)
    p_prep.add_argument("--product", default="rollcall")

    p_replay = sub.add_parser("replay", help="Emit the recorded/synthesized model draft for a fenced model step.")
    p_replay.add_argument("--step", required=True)
    p_replay.add_argument("--workspace", required=True)
    p_replay.add_argument("--case", default=str(DEFAULT_CASE_DIR))
    p_replay.add_argument("--product", default="rollcall")
    p_replay.add_argument("--ref", default="origin/master")

    p_step = sub.add_parser("step", help="Run one real-mode step or stage via the harness.")
    p_step.add_argument("--step", required=True)
    p_step.add_argument("--workspace", required=True)
    p_step.add_argument("--product", default="rollcall")
    p_step.add_argument("--raw", default="")

    p_run = sub.add_parser("run", help="Run all 8 stages + 2 gates in real mode on the frozen known case.")
    p_run.add_argument("--case", default=str(DEFAULT_CASE_DIR))
    p_run.add_argument("--workspace", required=True)
    p_run.add_argument("--product", default="rollcall")

    p_grade = sub.add_parser("grade", help="Run all 5 grade-* commands on a completed workspace.")
    p_grade.add_argument("--workspace", required=True)

    p_parity = sub.add_parser("parity", help="Compare legacy fixture run vs real-mode harness run side by side.")
    p_parity.add_argument("--case", default=str(DEFAULT_CASE_DIR))

    args = parser.parse_args(argv)

    if args.cmd == "prepare":
        ws = prepare_workspace(args.case, args.workspace, product=args.product)
        print(json.dumps({"ok": True, "workspace": str(ws), "mode": "real"}, ensure_ascii=False))
        return 0

    if args.cmd == "replay":
        if args.step in MODEL_STEPS:
            draft = draft_for_step(args.step, args.workspace)
            text = json.dumps(draft, ensure_ascii=False)
            if args.step == "intake":
                draft_path = Path(args.workspace).expanduser().resolve() / "01-request/draft.json"
                draft_path.parent.mkdir(parents=True, exist_ok=True)
                draft_path.write_text(text + "\n", encoding="utf-8")
            print(text)
        elif args.step in STACK_STEPS:
            res = replay_stack_step(args.step, args.workspace, product=args.product, ref=args.ref)
            print(json.dumps(res, ensure_ascii=False))
        elif args.step in WORKSPACE_STEPS:
            res = replay_workspace_step(args.step, args.workspace, product=args.product)
            print(json.dumps(res, ensure_ascii=False))
        else:
            res = run_step(args.step, args.workspace, product=args.product)
            print(json.dumps(res, ensure_ascii=False))
        return 0

    if args.cmd == "step":
        if args.step in ("gate_direction", "gate_final"):
            gate_name = args.step.removeprefix("gate_")
            res = answer_gate(gate_name, args.workspace, answer=args.raw or None)
        elif args.step in ("intake", "existing", "ground", "directions", "build", "review", "checks", "show", "handoff", "gate_final_next"):
            res = run_stage(args.step, args.workspace, product=args.product, raw=args.raw)
        else:
            res = run_step(args.step, args.workspace, product=args.product, raw=args.raw)
        print(json.dumps(res, ensure_ascii=False))
        return 0

    if args.cmd == "run":
        res = run_all(args.case, args.workspace, product=args.product)
        print(json.dumps(res, ensure_ascii=False))
        return 0

    if args.cmd == "grade":
        res = grade_workspace(args.workspace)
        print(json.dumps(res, ensure_ascii=False))
        return 0

    if args.cmd == "parity":
        res = compare_parity(args.case)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("parity") else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
