"""Stage 6, checks and review of this round's build, in 06-checks/round-<n>/.

checks (6a, built): model-free. It opens every view of the build the prototype contract names (screen x
state x width), measures it in a real browser and writes 06-checks/round-<n>/checks.json: one row per
failing element and one summary row per check, each with id, value, result, evidence, element and
location, and the class 6b reads (blocker = a Must input, should). The measures it judged are kept beside
it in measures.json, and a screenshot of every view in views/.

review (6b, stub): findings (element, location, evidence, severity 0-4, must|should|could|wont) and the
verdict: revise while a Must finding is open (the workflow loops back to build, at most twice), else done.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import checks_rules, checks_views, contracts
from .fixture_stage import run_fixture
from .workspace import Workspace

TOOL = "checks_render.mjs (playwright-mcp) + design_measure.js, measure_in_page.js, checks_measure.js, axe 4.13.0"


class ChecksError(ValueError):
    """The checks step cannot run on this workspace; the message says which file is missing or wrong."""


def _read(path: Path, what: str, required: bool = True):
    if not path.is_file():
        if required:
            raise ChecksError(f"checks: {path} is missing: {what}")
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ChecksError(f"checks: {path} is not JSON: {exc}") from exc


def _context(ws: Workspace, plan: dict, measured: dict) -> dict:
    ground = ws.folder("ground")
    inventory_file = ground / "inventory.json"
    inventory = _read(inventory_file, "the ground stage's inventory names the screens the build must have")
    requirements = _read(ws.folder("intake") / "requirements.json",
                         "the intake stage's requirements say what the build must show", required=False) or {}
    fixture = _read(ground / "fixture.json", "the run's figures", required=False)
    tokens = None
    for candidate in (ground / "design-files" / "tokens.json", ground / "tokens.json"):
        if candidate.is_file():
            tokens = _read(candidate, "the product's design tokens")
            break
    return checks_rules.context(plan, inventory.get("screens") or [], requirements.get("items") or [],
                                fixture, tokens, inventory.get("design_files") or "none", measured)


def _rows_for_file(result: dict) -> list[dict]:
    """The rows as checks.json holds them: the summary row of each check first, then the failures."""
    out = []
    for entry in result["summary"]:
        out.append({"id": entry["id"], "value": entry["value"], "result": entry["result"],
                    "evidence": entry["evidence"], "element": entry["element"] or "every view",
                    "location": entry["location"], "severity": entry["severity"], "summary": True,
                    "count": entry["value"]["failures"]})
    for row in result["rows"]:
        item = {"id": row["id"], "value": row["value"], "result": row["result"], "evidence": row["evidence"],
                "element": row["element"] or "the view", "location": row["location"],
                "severity": row["severity"]}
        if row["screen"]:
            item["screen"] = row["screen"]
        if row["state"]:
            item["state"] = row["state"]
        if row["width"]:
            item["width"] = row["width"]
        out.append(item)
    return out


def measure(ws: Workspace, plan: dict, thresholds: dict) -> dict:
    """Open and measure every view (the browser half, kept apart so the rules can be tested without one)."""
    from . import checks_render  # noqa: PLC0415 - needs the worker's browser

    return checks_render.render(ws.folder("build"), plan, ws.round_folder(), thresholds)


def run(ws: Workspace, data: str) -> dict:
    if ws.mode == "fixture":
        return {**run_fixture(ws, "checks"), "round": ws.round}
    started = time.time()
    if ws.round < 1:
        raise ChecksError("checks: the run has no round yet: the build step runs before the checks step")
    ws.mark("checks", "running", round=ws.round)
    thresholds = checks_rules.load_thresholds()
    plan = checks_views.plan(ws)
    out = ws.round_folder()
    out.mkdir(parents=True, exist_ok=True)
    measured = measure(ws, plan, thresholds)
    (out / "measures.json").write_text(json.dumps(
        {"round": ws.round, "page": plan["page"], "widths": plan["widths"],
         "views": [{k: v for k, v in view.items()} for view in plan["views"]],
         "measured": measured}, indent=1, ensure_ascii=False) + "\n")
    ctx = _context(ws, plan, measured)
    result = checks_rules.evaluate(plan, measured, ctx, thresholds)
    record = {"round": ws.round, "tool": TOOL, "views": result["totals"]["views"],
              "blockers": result["totals"]["blockers"], "shoulds": result["totals"]["shoulds"],
              "checks": _rows_for_file(result)}
    (out / "checks.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    contracts.validate("checks", ws)
    ws.mark("checks", "done", round=ws.round, verdict=result["verdict"],
            blockers=result["totals"]["blockers"], rows=result["totals"]["rows"])
    return {"round": ws.round, "verdict": result["verdict"], "views": result["totals"]["views"],
            "rows": result["totals"]["rows"], "blockers": result["totals"]["blockers"],
            "shoulds": result["totals"]["shoulds"], "checks_failed": result["totals"]["checks_failed"],
            "checks_skipped": result["totals"]["checks_skipped"], "seconds": round(time.time() - started, 1)}


def review(ws: Workspace, data: str) -> dict:
    out = run_fixture(ws, "review")
    record = json.loads((ws.round_folder() / "review.json").read_text())
    must = sum(1 for f in record["findings"] if f.get("priority") == "must")
    return {**out, "round": ws.round, "verdict": record["verdict"], "must": must}
