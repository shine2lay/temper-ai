"""Stage 3, ground: what the design must cover, decided before any direction is drawn, in 03-ground/: the
product's design-file status, every screen with what it shows, its states and its actions (inventory.json),
and the one shared sample-data fixture every screen uses (fixture.json), checked for its invariants.

The host prepares first (design_app_screen.py ground-prep, ground_host.py: workers reach neither the design lab
nor the product repo). Then three script steps around one fenced model step (agents/design_app_screen_ground_v1):

    ground_collect  real: the host's prep.json and pack checked; the design-file status (design_files.inventory);
                    every source item with its id -> sources.json; the fixture's invariants -> fixture-check.json;
                    the model's task text -> task.md, passed on; says model yes
    (ground_read)   the model maps every source item to a screen, a shown fact, a state or an action, or
                    excludes it with a reason (JSON)
    ground_check    the reply -> draft.json, held to the sources (ground_check.py) -> check.json; verdict retry
                    passes the revision text to the model once (ground_revise)
    ground          the revised reply (if any) becomes draft.json; the same checks -> check-final.json; clean:
                    inventory.json (widths from the product file, data_needed from the fixture); then a broken
                    fixture invariant, or any problem left, fails the stage loud

Fixture mode: collect and check pass through (model no) and ground copies the known case's output.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import (
    contracts,
    ground_check,
    ground_fixture,
    ground_sources,
    ground_task,
    model_step,
)
from .fixture_stage import run_fixture
from .workspace import Workspace

PREP, SOURCES, TASK, DRAFT, FIRST_DRAFT, CHECK, CHECK_FINAL, INVENTORY, FIXTURE, FIXTURE_CHECK = (
    "source/prep.json", "sources.json", "task.md", "draft.json", "draft-first.json", "check.json",
    "check-final.json", "inventory.json", "fixture.json", "fixture-check.json")
SHOWN_PROBLEMS = 12
HOST = "design_app_screen.py ground-prep --product {product} --workspace {workspace}"

_write = model_step.write_json
_parse = model_step.parse_reply
_result = model_step.check_record


class GroundError(ValueError):
    """Stage 3 cannot go on: the host's prep is missing, the fixture breaks an invariant, or the final draft
    still breaks a check."""


def _read(ws: Workspace, stage: str, name: str, what: str, schema: str | None = None):
    path = ws.folder(stage) / name
    label = path.relative_to(ws.path).as_posix()
    if not path.is_file():
        raise GroundError(f"{label} is missing ({what})")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise GroundError(f"{label}: not readable JSON ({exc})") from None
    problems = contracts.check_json(schema, data, label) if schema else []
    if problems:
        raise GroundError("; ".join(problems[:SHOWN_PROBLEMS]))
    return data


def _host_hint(ws: Workspace) -> str:
    return "the host's ground-prep writes it: " + HOST.format(product=ws.run()["product"], workspace=ws.path)


def _prep(ws: Workspace) -> dict:
    return _read(ws, "ground", PREP, _host_hint(ws), "ground_prep")


def _same_as_prep(path: Path, label: str, sha: str, where: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise GroundError(f"03-ground/{label} differs from the copy ground-prep made of {where}")


def _fixture(ws: Workspace, prep: dict) -> dict:
    """The shared fixture as one object: fixture.json, each part file added under its name (as ground-prep copied)."""
    folder, spec = ws.folder("ground"), prep["fixture"]
    fixture = _read(ws, "ground", FIXTURE, _host_hint(ws), "fixture")
    _same_as_prep(folder / FIXTURE, FIXTURE, spec["sha256"], spec["from"])
    for name, sha in spec.get("parts", {}).items():
        part = folder / "fixtures" / f"{name}.json"
        if not part.is_file():
            raise GroundError(f"03-ground/fixtures/{name}.json is missing ({_host_hint(ws)})")
        _same_as_prep(part, f"fixtures/{name}.json", sha, spec.get("parts_from", "the fixture parts"))
        fixture[name] = json.loads(part.read_text(encoding="utf-8"))
    return fixture


def _status(ws: Workspace) -> str:
    try:
        return ground_sources.design_status(ws.folder("ground"))
    except ground_sources.SourcesError as exc:
        raise GroundError(f"{exc} ({_host_hint(ws)})") from None


def context(ws: Workspace) -> ground_check.Context:
    prep = _prep(ws)
    sources = _read(ws, "ground", SOURCES, "ground_collect writes it", "ground_sources")
    app = _read(ws, "existing", "app.json", "stage 2's capture writes it")
    widths = sorted((int(w) for w in app.get("sizes", {})), reverse=True)
    if not widths:
        raise GroundError("02-existing/app.json: sizes is empty; the product file names the widths")
    return ground_check.Context({i["id"]: i for i in sources["items"]}, widths,
                                ground_fixture.states(_fixture(ws, prep)))


def collect(ws: Workspace, raw: str) -> dict:
    if ws.mode == "fixture":
        return {"model": "no", "source": "known case"}
    folder = ws.folder("ground")
    prep = _prep(ws)
    status = _status(ws)
    try:
        items = ground_sources.items(ws, prep)
    except ground_sources.SourcesError as exc:
        raise GroundError(str(exc)) from None
    _write(folder / SOURCES, {"product": prep["product"], "items": items})
    fixture_check = ground_fixture.check(_fixture(ws, prep), prep["fixture"].get("invariants", {}))
    _write(folder / FIXTURE_CHECK, fixture_check)
    app = _read(ws, "existing", "app.json", "stage 2's capture writes it")
    questions = _read(ws, "intake", "questions.json", "stage 1 (intake) writes it").get("questions", [])
    text = ground_task.task(app, status, items, questions)
    _write(folder / TASK, text)
    kinds = {k: sum(1 for i in items if i["kind"] == k) for k in ground_sources.PLACED + ("seen", "journey")}
    return {"model": "yes", "design_files": status, "fixture": fixture_check["verdict"], **kinds,
            "task_chars": len(text), "task": text}


def check(ws: Workspace, raw: str) -> dict:
    """The draft pass: the model's reply -> draft.json and check.json; on retry the revision text."""
    if ws.mode == "fixture":
        return {"verdict": "ok", "source": "known case"}
    folder = ws.folder("ground")
    draft = _parse(raw)
    _write(folder / DRAFT, draft)
    found = ground_check.check_draft(context(ws), draft)
    _write(folder / CHECK, _result(found, "draft"))
    out = {"verdict": found["verdict"], "problems": len(found["problems"]), **found["counts"]}
    if found["verdict"] == "retry":
        shutil.copyfile(folder / DRAFT, folder / FIRST_DRAFT)
        task_text = (folder / TASK).read_text(encoding="utf-8")
        out["revise_task"] = ground_task.revise(task_text, json.dumps(draft, ensure_ascii=False, indent=1),
                                                found["problems"])
    return out


def _source(prep: dict) -> dict:
    out = {"product": prep["product"], "capabilities": prep["capabilities"]["from"],
           "notes": [n["from"] for n in prep["notes"]], "fixture": prep["fixture"]["from"]}
    if prep.get("commit"):
        out["commit"] = prep["commit"]
    return out


def run(ws: Workspace, raw: str) -> dict:
    """The final pass: the revised reply (if there was one) is the draft; clean -> inventory.json, else fail loud."""
    if ws.mode == "fixture":
        return run_fixture(ws, "ground")
    folder = ws.folder("ground")
    revised = bool((raw or "").strip())
    if revised:
        _write(folder / DRAFT, _parse(raw))
    elif not (folder / DRAFT).is_file():
        raise GroundError("03-ground/draft.json is missing: the model step wrote no draft")
    draft = json.loads((folder / DRAFT).read_text(encoding="utf-8"))
    ctx = context(ws)
    found = ground_check.check_draft(ctx, draft)
    _write(folder / CHECK_FINAL, _result(found, "final"))
    if found["problems"]:
        raise GroundError(model_step.failure(found["problems"], f"03-ground/{CHECK_FINAL}"))
    prep = _prep(ws)
    inventory = ground_check.outputs(ctx, draft, _status(ws), _source(prep))
    _write(folder / INVENTORY, inventory)
    fixture_check = _read(ws, "ground", FIXTURE_CHECK, "ground_collect writes it", "fixture_check")
    if fixture_check["verdict"] != "pass":
        raise GroundError(f"03-ground/{FIXTURE} breaks {len(fixture_check['problems'])} invariant(s): "
                          + "; ".join(f"{p['check']} {p['where']}: {p['problem']}"
                                      for p in fixture_check["problems"][:SHOWN_PROBLEMS]))
    return {"revised": revised, "screens": len(inventory["screens"]),
            "data_needed": sum(len(s.get("data_needed", [])) for s in inventory["screens"]), **found["counts"]}
