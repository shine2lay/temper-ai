"""Stage 2, existing: the product as it is today: captures and measures (from the host), then the user
journeys and the problems in them, each problem tied to the captures and measures that show it, in 02-existing/.

The host captures first (design_app_screen.py capture, existing_host.py: workers reach neither the app nor a
browser). Then four script steps around one fenced model step (agents/design_app_screen_existing_v1.yaml):

    existing_collect  real: the host's audit.json, texts.json, app.json and sheet.png, and stage 1's
                      requirements.json, checked; the model's task text written to 02-existing/task.md and
                      passed on; says model yes
    existing_sheet    real: the contact sheet as base64 for the model's one image (its own step: a step's
                      output is capped at 256,000 characters, too little for the sheet and the task together)
    (existing_read)   the model looks at the sheet and the task and replies with the draft journeys (JSON)
    existing_check    the reply written to draft.json and held to the captures (existing_check.py) ->
                      check.json; verdict retry passes the revision text to the model once (existing_revise)
    existing          the revised reply (if any) becomes draft.json; the same checks -> check-final.json;
                      clean: journeys.json; any problem left fails the stage loud

Fixture mode: collect, sheet and check pass through (model no) and existing copies the known case's output.
"""
from __future__ import annotations

import base64
import json
import shutil

from . import contracts, existing_check, existing_task, model_step
from .fixture_stage import run_fixture
from .workspace import Workspace

AUDIT, TEXTS, APP, SHEET, TASK = "audit.json", "texts.json", "app.json", "sheet.png", "task.md"
DRAFT, FIRST_DRAFT, CHECK, CHECK_FINAL, JOURNEYS = (
    "draft.json", "draft-first.json", "check.json", "check-final.json", "journeys.json")
SHEET_LIMIT = 240_000      # base64 characters: the step's output stays under the 256,000-character cap
SHOWN_PROBLEMS = 12
HOST = "design_app_screen.py capture --product {product} --workspace {workspace}"


class ExistingError(ValueError):
    """Stage 2 cannot go on: the capture is missing, or the final draft still breaks a check."""


_write = model_step.write_json
_parse = model_step.parse_reply
_result = model_step.check_record


def _read(ws: Workspace, stage: str, name: str, what: str):
    path = ws.folder(stage) / name
    if not path.is_file():
        raise ExistingError(f"{path.relative_to(ws.path).as_posix()} is missing ({what})")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ExistingError(f"{path.relative_to(ws.path).as_posix()}: not readable JSON ({exc})") from None


def _capture_hint(ws: Workspace) -> str:
    return "the host's capture writes it: " + HOST.format(product=ws.run()["product"], workspace=ws.path)


def context(ws: Workspace) -> existing_check.Context:
    hint = _capture_hint(ws)
    audit = _read(ws, "existing", AUDIT, hint)
    problems = contracts.check_json("audit", audit, "02-existing/audit.json")
    if problems:
        raise ExistingError("; ".join(problems[:SHOWN_PROBLEMS]))
    texts = _read(ws, "existing", TEXTS, hint)
    app = _read(ws, "existing", APP, hint)
    requirements = _read(ws, "intake", "requirements.json", "stage 1 (intake) writes it")
    return existing_check.Context(audit, texts, app, {r["id"] for r in requirements.get("items", [])})


def collect(ws: Workspace, raw: str) -> dict:
    if ws.mode == "fixture":
        return {"model": "no", "source": "known case"}
    ctx = context(ws)
    if not (ws.folder("existing") / SHEET).is_file():
        raise ExistingError(f"02-existing/{SHEET} is missing ({_capture_hint(ws)})")
    requirements = _read(ws, "intake", "requirements.json", "stage 1 (intake) writes it")
    text = existing_task.task(ctx.audit, json.loads((ws.folder("existing") / TEXTS).read_text(encoding="utf-8")),
                              ctx.app, requirements)
    _write(ws.folder("existing") / TASK, text)
    return {"model": "yes", "captures": len(ctx.captures), "screens": len(ctx.screen_ids),
            "requirements": len(requirements.get("items", [])), "task_chars": len(text), "task": text}


def sheet(ws: Workspace, raw: str) -> dict:
    if ws.mode == "fixture":
        return {"model": "no", "source": "known case"}
    path = ws.folder("existing") / SHEET
    if not path.is_file():
        raise ExistingError(f"02-existing/{SHEET} is missing ({_capture_hint(ws)})")
    data = path.read_bytes()
    if not data.startswith(contracts.PNG_MAGIC):
        raise ExistingError(f"02-existing/{SHEET} is not a PNG")
    encoded = base64.b64encode(data).decode("ascii")
    if len(encoded) > SHEET_LIMIT:
        raise ExistingError(f"02-existing/{SHEET} is {len(encoded)} base64 characters, over {SHEET_LIMIT}: "
                            "re-run the capture (existing_sheet.BUDGET keeps it under)")
    return {"sheet": encoded, "bytes": len(data)}


def check(ws: Workspace, raw: str) -> dict:
    """The draft pass: the model's reply -> draft.json and check.json; on retry the revision text."""
    if ws.mode == "fixture":
        return {"verdict": "ok", "source": "known case"}
    folder = ws.folder("existing")
    draft = _parse(raw)
    _write(folder / DRAFT, draft)
    found = existing_check.check_draft(context(ws), draft)
    _write(folder / CHECK, _result(found, "draft"))
    out = {"verdict": found["verdict"], "problems": len(found["problems"]), **found["counts"]}
    if found["verdict"] == "retry":
        shutil.copyfile(folder / DRAFT, folder / FIRST_DRAFT)
        task_text = (folder / TASK).read_text(encoding="utf-8")
        out["revise_task"] = existing_task.revise(task_text, json.dumps(draft, ensure_ascii=False, indent=1),
                                                  found["problems"])
    return out


def run(ws: Workspace, raw: str) -> dict:
    """The final pass: the revised reply (if there was one) is the draft; clean -> journeys.json, else fail loud."""
    if ws.mode == "fixture":
        return run_fixture(ws, "existing")
    folder = ws.folder("existing")
    revised = bool((raw or "").strip())
    if revised:
        _write(folder / DRAFT, _parse(raw))
    elif not (folder / DRAFT).is_file():
        raise ExistingError("02-existing/draft.json is missing: the model step wrote no draft")
    draft = json.loads((folder / DRAFT).read_text(encoding="utf-8"))
    ctx = context(ws)
    found = existing_check.check_draft(ctx, draft)
    _write(folder / CHECK_FINAL, _result(found, "final"))
    if found["problems"]:
        raise ExistingError(model_step.failure(found["problems"], f"02-existing/{CHECK_FINAL}"))
    _write(folder / JOURNEYS, existing_check.outputs(ctx, draft))
    return {"revised": revised, **found["counts"]}
