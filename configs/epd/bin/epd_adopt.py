#!/usr/bin/env python3
"""Record a finished temper run as a stage of a bet, when the driver was not
there to see it finish (it was stopped, or crashed, while the run kept going
in the server).

    epd_adopt.py BET STAGE RUN_ID

Does what the driver's stage function does after `run_workflow` returns:
stores the run's structured outputs under state.stages[STAGE], advances the
status, updates the ledger. Nothing is re-run.
"""

import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import epd_loop as L  # noqa: E402

bet_id, stage, run_id = sys.argv[1:4]
stage = L.stage_named(stage)  # `tasks` is the plan stage's name before epd_loop v13
info = L.get_run(run_id)
if info.get("status") != "completed":
    L.die(f"run {run_id} is {info.get('status')}, not completed")
out = {k: L.unstr(v) for k, v in (info.get("workflow_output") or {}).items()}
out["_run_id"] = run_id
out["_cost_usd"] = info.get("total_cost_usd")
out["_duration_s"] = info.get("duration_seconds")

st = L.load_state(bet_id)
bdir = L.BETS_DIR / bet_id
if stage == "plan":
    if out.get("status") == "BLOCKED":
        L.die(f"plan BLOCKED: {out.get('blocked_because')}")
    if not (bdir / "tasks.json").exists():
        L.die("no tasks.json")
    st["stages"]["plan"] = out
    st["status"] = L.AFTER["plan"]
    L.save_state(st)
    L.log(f"adopted {run_id[:8]} as plan: {out.get('task_count')} tasks, {len(out.get('files') or [])} files")
else:
    L.die(f"adopt is only written for the plan stage so far, not {stage}")
