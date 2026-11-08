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
    ws_step = ws if ws.step else ws.for_step("existing_collect")
    try:
        return json.loads(ws_step.read_text(path))
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


def _save_stack_meta(ws: Workspace, meta: dict[str, Any], *, write_capture_record: bool = False) -> None:
    ws_step = ws if ws.step else ws.for_step("existing_collect")
    if ws.run_file.is_file():
        try:
            run_doc = json.loads(ws_step.read_text(ws.run_file))
            if isinstance(run_doc, dict):
                merged = dict(run_doc.get("stack") or {})
                for k, v in meta.items():
                    if v is not None:
                        merged[k] = v
                run_doc["stack"] = merged
                _write(ws.run_file, run_doc)
        except Exception:
            pass
    if write_capture_record:
        cap_path = ws.folder("existing") / "capture.json"
        existing_cap: dict[str, Any] = {}
        if cap_path.is_file():
            try:
                loaded = json.loads(ws_step.read_text(cap_path))
                if isinstance(loaded, dict):
                    existing_cap = loaded
            except Exception:
                existing_cap = {}
        for k, v in meta.items():
            if v is not None:
                existing_cap[k] = v
        _write(cap_path, existing_cap)


def _load_stack_meta(ws: Workspace) -> dict[str, Any]:
    ws_step = ws if ws.step else ws.for_step("existing")
    out: dict[str, Any] = {}
    if ws.run_file.is_file():
        try:
            run_doc = json.loads(ws_step.read_text(ws.run_file))
            if isinstance(run_doc, dict) and isinstance(run_doc.get("stack"), dict):
                out.update(run_doc["stack"])
        except Exception:
            pass
    for rel in ("02-existing/capture.json", "02-existing/audit.json"):
        p = ws.path / rel
        if p.is_file():
            try:
                doc = json.loads(ws_step.read_text(p))
                if isinstance(doc, dict):
                    for k in ("commit", "short_commit", "ref", "reused", "ci_conclusion", "allow_red_commit", "ci_failing_check", "base_url"):
                        if k not in out and doc.get(k) is not None:
                            out[k] = doc[k]
            except Exception:
                pass
    return out


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
    stack_short_commit: str | None = None,
    stack_ref: str | None = None,
    stack_env_name: str | None = None,
    stack_reused: bool | str | None = None,
    allow_red_commit: bool | str | None = None,
    credentials: dict[str, str] | str | None = None,
    health_opener: Any = None,
    ci_runner: Any = None,
    instance: app_instance.AppInstance | None = None,
) -> dict[str, Any]:
    ws = ws.for_step("existing_collect")
    eff_url = (base_url if base_url is not None else os.environ.get("APP_SCREEN_BASE_URL", "")).strip()
    eff_commit = (stack_commit if stack_commit is not None else os.environ.get("APP_SCREEN_STACK_COMMIT", "")).strip()
    eff_short_commit = (
        stack_short_commit if stack_short_commit is not None else os.environ.get("APP_SCREEN_STACK_SHORT_COMMIT", "")
    ).strip()
    eff_ref = (stack_ref if stack_ref is not None else os.environ.get("APP_SCREEN_STACK_REF", "")).strip() or "origin/master"
    eff_env_name = (
        stack_env_name if stack_env_name is not None else os.environ.get("APP_SCREEN_STACK_ENV_NAME", "")
    ).strip()
    raw_reused = stack_reused if stack_reused is not None else os.environ.get("APP_SCREEN_STACK_REUSED")
    eff_reused = app_instance.parse_bool(raw_reused) if raw_reused is not None and str(raw_reused).strip() != "" else False
    raw_allow_red = allow_red_commit if allow_red_commit is not None else os.environ.get("APP_SCREEN_ALLOW_RED_COMMIT")
    eff_allow_red = app_instance.parse_bool(raw_allow_red)
    has_ci_input = bool(
        eff_commit
        or allow_red_commit is not None
        or ci_runner is not None
        or os.environ.get("APP_SCREEN_ALLOW_RED_COMMIT", "").strip()
    )
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
        product = ws.run()["product"]
        audit_doc = _read(ws, "existing", AUDIT, _capture_hint(ws))
        recorded_commit = str(audit_doc.get("commit") or "").strip()
        if eff_commit:
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
        target_sha = eff_commit or recorded_commit
        if has_ci_input and target_sha:
            try:
                ci_info = app_instance.verify_commit_ci_status(
                    target_sha,
                    product=product,
                    allow_red_commit=eff_allow_red,
                    runner=ci_runner,
                )
            except app_instance.AppInstanceError as exc:
                raise ExistingError(str(exc)) from None
            meta = {
                "commit": ci_info["commit"],
                "short_commit": eff_short_commit or ci_info["short_commit"],
                "ref": eff_ref,
                "reused": True,
                "ci_conclusion": ci_info["ci_conclusion"],
                "allow_red_commit": ci_info["allow_red_commit"],
                "ci_failing_check": ci_info.get("ci_failing_check"),
                "base_url": eff_url or audit_doc.get("base_url"),
                "env_name": eff_env_name or None,
            }
            _save_stack_meta(ws, meta, write_capture_record=False)
            return {**reused, **{k: v for k, v in meta.items() if v is not None}}
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
                stack_ref=eff_ref,
                stack_reused=eff_reused,
                allow_red_commit=eff_allow_red if has_ci_input else None,
                health_opener=health_opener,
                ci_runner=ci_runner,
                instance=instance,
            )
        except (existing_host.CaptureError, app_instance.AppInstanceError) as exc:
            raise ExistingError(str(exc)) from None

    ctx = context(ws)
    recorded_commit = str(ctx.audit.get("commit") or ctx.app.get("commit") or "").strip()
    if eff_commit:
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

    stack_meta: dict[str, Any] = {}
    target_sha = eff_commit or recorded_commit
    if has_ci_input and target_sha:
        product = ws.run()["product"]
        try:
            ci_info = app_instance.verify_commit_ci_status(
                target_sha,
                product=product,
                allow_red_commit=eff_allow_red,
                runner=ci_runner,
            )
        except app_instance.AppInstanceError as exc:
            raise ExistingError(str(exc)) from None
        stack_meta = {
            "commit": ci_info["commit"],
            "short_commit": eff_short_commit or ci_info["short_commit"],
            "ref": eff_ref,
            "reused": eff_reused,
            "ci_conclusion": ci_info["ci_conclusion"],
            "allow_red_commit": ci_info["allow_red_commit"],
            "ci_failing_check": ci_info.get("ci_failing_check"),
            "base_url": eff_url or ctx.audit.get("base_url") or ctx.app.get("base_url"),
            "env_name": eff_env_name or None,
        }
        _save_stack_meta(
            ws,
            stack_meta,
            write_capture_record=(folder / "capture.json").is_file() or not (ws.path / "known-case").is_dir(),
        )
    elif recorded_commit:
        stack_meta = {
            "commit": recorded_commit,
            "short_commit": eff_short_commit or recorded_commit[:12],
            "ref": eff_ref,
            "reused": eff_reused,
        }
        _save_stack_meta(ws, stack_meta, write_capture_record=False)

    if not (ws.folder("existing") / SHEET).is_file():
        raise ExistingError(f"02-existing/{SHEET} is missing ({_capture_hint(ws)})")
    requirements = _read(ws, "intake", "requirements.json", "stage 1 (intake) writes it")
    text = existing_task.task(ctx.audit, json.loads(ws.read_text(ws.folder("existing") / TEXTS)),
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
    if stack_meta.get("commit") or ctx.audit.get("commit"):
        out["commit"] = stack_meta.get("commit") or ctx.audit["commit"]
    for k in ("short_commit", "ref", "reused", "ci_conclusion", "allow_red_commit"):
        if k in stack_meta and stack_meta[k] is not None:
            out[k] = stack_meta[k]
    base = ctx.audit.get("base_url") or ctx.app.get("base_url") or eff_url
    if base:
        out["base_url"] = base
    return out


def sheet(ws: Workspace, raw: str) -> dict:
    ws = ws.for_step("existing_sheet")
    if reused := _reused(ws):
        return reused
    path = ws.folder("existing") / SHEET
    if not path.is_file():
        raise ExistingError(f"02-existing/{SHEET} is missing ({_capture_hint(ws)})")
    data = ws.read_bytes(path)
    if not data.startswith(contracts.PNG_MAGIC):
        raise ExistingError(f"02-existing/{SHEET} is not a PNG")
    encoded = base64.b64encode(data).decode("ascii")
    if len(encoded) > SHEET_LIMIT:
        raise ExistingError(f"02-existing/{SHEET} is {len(encoded)} base64 characters, over {SHEET_LIMIT}: "
                            "re-run the capture (existing_sheet.BUDGET keeps it under)")
    return {"sheet": encoded, "bytes": len(data)}


def check(ws: Workspace, raw: str) -> dict:
    """The draft pass: the model's reply -> draft.json and check.json; on retry the revision text."""
    ws = ws.for_step("existing_check")
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
        task_text = ws.read_text(folder / TASK)
        out["revise_task"] = existing_task.revise(task_text, json.dumps(draft, ensure_ascii=False, indent=1),
                                                  found["problems"])
    return out


def run(ws: Workspace, raw: str) -> dict:
    """The final pass: the revised reply (if there was one) is the draft; clean -> journeys.json, else fail loud."""
    ws = ws.for_step("existing")
    meta = _load_stack_meta(ws)
    carry = {k: meta[k] for k in ("commit", "short_commit", "ref", "reused", "ci_conclusion", "allow_red_commit") if k in meta and meta[k] is not None}
    if reused := _reused(ws):
        return {"stage_status": "reused", "source": reused["source"], "files": reused["files"], **carry}
    folder = ws.folder("existing")
    revised = bool((raw or "").strip())
    if revised:
        _write(folder / DRAFT, _parse(raw))
    elif not (folder / DRAFT).is_file():
        raise ExistingError("02-existing/draft.json is missing: the model step wrote no draft")
    draft = json.loads(ws.read_text(folder / DRAFT))
    ctx = context(ws)
    found = existing_check.check_draft(ctx, draft)
    _write(folder / CHECK_FINAL, _result(found, "final"))
    if found["problems"]:
        raise ExistingError(model_step.failure(found["problems"], f"02-existing/{CHECK_FINAL}"))
    _write(folder / JOURNEYS, existing_check.outputs(ctx, draft))
    return {"revised": revised, **found["counts"], **carry, **_status(ws)}
