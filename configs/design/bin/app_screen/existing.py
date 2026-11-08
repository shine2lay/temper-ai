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

Step 4 (reuse, reuse_host.py): when the host's prepare decided reuse, the stored 02-existing is already here;
every step checks it is byte-identical to the store (stored_copy.py) and holds to the contracts, and the model
is skipped (the stage ends reused). A delta (only changed screens captured again) runs as a full read over
the merged captures, because journeys span screens, and ends delta.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
from typing import Any

from . import (
    app_instance,
    contracts,
    existing_check,
    existing_host,
    existing_task,
    model_step,
    stored_copy,
    tools_registry,
)
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


def _reused(ws: Workspace) -> dict | None:
    """prepare's record when it reused the stored stage 2, checked byte-identical and against the contracts."""
    decision = ws.decision("existing")
    if not decision or decision["decision"] != "reuse":
        return None
    record = stored_copy.verify(ws, "existing")
    contracts.validate("existing", ws)
    return {"model": "no", "source": f"stored v{record['version']} (run {record['source_run']})",
            "files": len(record["files"])}


def _status(ws: Workspace) -> dict:
    decision = ws.decision("existing")
    return {"stage_status": "delta"} if decision and decision["decision"] == "delta" else {}


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


def collect(
    ws: Workspace,
    raw: str = "",
    *,
    base_url: str | None = None,
    stack_commit: str | None = None,
    credentials: dict[str, str] | str | None = None,
    health_opener: Any = None,
    instance: app_instance.AppInstance | None = None,
) -> dict[str, Any]:
    eff_url = (base_url if base_url is not None else os.environ.get("APP_SCREEN_BASE_URL", "")).strip()
    eff_commit = (stack_commit if stack_commit is not None else os.environ.get("APP_SCREEN_STACK_COMMIT", "")).strip()
    eff_creds = (
        credentials
        if credentials is not None
        else (os.environ.get("APP_SCREEN_CREDENTIALS") or os.environ.get("ROLLCALL_QA_PASSWORD"))
    )
    folder = ws.folder("existing")
    has_prepared_capture = (
        (folder / AUDIT).is_file()
        and (folder / TEXTS).is_file()
        and (folder / APP).is_file()
        and (folder / SHEET).is_file()
    )

    if reused := _reused(ws):
        if eff_commit:
            audit_doc = _read(ws, "existing", AUDIT, _capture_hint(ws))
            recorded_commit = str(audit_doc.get("commit") or "").strip()
            if eff_url and (health_opener is not None or instance is not None or not recorded_commit):
                try:
                    health = (
                        instance.read_health()
                        if instance is not None
                        else app_instance.fetch_health(eff_url, stack_commit=eff_commit, opener=health_opener)
                    )
                    recorded_commit = health["commit"]
                except app_instance.AppInstanceError as exc:
                    raise ExistingError(str(exc)) from None
            if recorded_commit:
                try:
                    app_instance.verify_stack_commit(eff_commit, recorded_commit, base_url=eff_url)
                except app_instance.AppInstanceError as exc:
                    raise ExistingError(str(exc)) from None
        return reused

    if (eff_url or instance is not None) and not has_prepared_capture:
        product = ws.run()["product"]
        try:
            existing_host.capture(
                product,
                ws.path,
                base_url=eff_url or None,
                credentials=eff_creds,
                stack_commit=eff_commit or None,
                health_opener=health_opener,
                instance=instance,
            )
        except (existing_host.CaptureError, app_instance.AppInstanceError) as exc:
            raise ExistingError(str(exc)) from None

    ctx = context(ws)
    if eff_commit:
        recorded_commit = str(ctx.audit.get("commit") or ctx.app.get("commit") or "").strip()
        if eff_url and (health_opener is not None or instance is not None):
            try:
                health = (
                    instance.read_health()
                    if instance is not None
                    else app_instance.fetch_health(eff_url, stack_commit=eff_commit, opener=health_opener)
                )
                recorded_commit = health["commit"]
            except app_instance.AppInstanceError as exc:
                raise ExistingError(str(exc)) from None
        if recorded_commit:
            try:
                app_instance.verify_stack_commit(
                    eff_commit,
                    recorded_commit,
                    base_url=eff_url or str(ctx.audit.get("base_url") or ""),
                )
            except app_instance.AppInstanceError as exc:
                raise ExistingError(str(exc)) from None
    if not (ws.folder("existing") / SHEET).is_file():
        raise ExistingError(f"02-existing/{SHEET} is missing ({_capture_hint(ws)})")
    requirements = _read(ws, "intake", "requirements.json", "stage 1 (intake) writes it")
    text = existing_task.task(ctx.audit, json.loads((ws.folder("existing") / TEXTS).read_text(encoding="utf-8")),
                              ctx.app, requirements, tools=tools_registry.task_section("existing"))
    _write(ws.folder("existing") / TASK, text)
    out: dict[str, Any] = {
        "model": "yes",
        "captures": len(ctx.captures),
        "screens": len(ctx.screen_ids),
        "requirements": len(requirements.get("items", [])),
        "task_chars": len(text),
        "task": text,
    }
    if ctx.audit.get("commit"):
        out["commit"] = ctx.audit["commit"]
    base = ctx.audit.get("base_url") or ctx.app.get("base_url") or eff_url
    if base:
        out["base_url"] = base
    return out


def sheet(ws: Workspace, raw: str) -> dict:
    if reused := _reused(ws):
        return reused
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
    if reused := _reused(ws):
        return {"verdict": "ok", "source": reused["source"]}
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
    if reused := _reused(ws):
        return {"stage_status": "reused", "source": reused["source"], "files": reused["files"]}
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
    return {"revised": revised, **found["counts"], **_status(ws)}
