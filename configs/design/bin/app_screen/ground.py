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

Step 4 (reuse): when the host's prepare copied a stored ground to 03-ground/stored/ (decision pending),
ground_collect settles it by script (ground_delta.py): nothing new or changed -> reused (the stored inventory
and final check copied, the model skipped, every check run again); else delta: the stored inventory, less
stale citations, is the base; the model gets only the unplaced and changed items with an added "Already
placed, keep" section and replies with additions; the merged draft is held to every check, coverage over all
items, plus the kept check (no stored entry changed).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import (
    contracts,
    ground_check,
    ground_delta,
    ground_fixture,
    ground_sources,
    ground_task,
    model_step,
    stored_copy,
    tools_registry,
)
from .workspace import Workspace

PREP, SOURCES, TASK, DRAFT, FIRST_DRAFT, CHECK, CHECK_FINAL, INVENTORY, FIXTURE, FIXTURE_CHECK = (
    "source/prep.json", "sources.json", "task.md", "draft.json", "draft-first.json", "check.json",
    "check-final.json", "inventory.json", "fixture.json", "fixture-check.json")
DELTA, FIRST_ADDITIONS = "delta.json", "additions-first.json"
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
    decision = ws.decision("ground")
    if decision and decision["decision"] == "pending":
        return _settle(ws, items, app, status, questions, fixture_check["verdict"])
    text = ground_task.task(app, status, items, questions, tools=tools_registry.task_section("ground"))
    _write(folder / TASK, text)
    kinds = {k: sum(1 for i in items if i["kind"] == k) for k in ground_sources.PLACED + ("seen", "journey")}
    return {"model": "yes", "design_files": status, "fixture": fixture_check["verdict"], **kinds,
            "task_chars": len(text), "task": text}


def _settle(ws: Workspace, items: list[dict], app: dict, status: str, questions: list[dict], fixture: str) -> dict:
    """Reuse or delta over the stored ground prepare copied in (decision pending), by script."""
    folder, record = ws.folder("ground"), stored_copy.verify(ws, "ground")
    stored = f"{ground_delta.STORED}/"
    inventory = _read(ws, "ground", stored + INVENTORY, "prepare copies the stored version", "inventory")
    old = _read(ws, "ground", stored + SOURCES, "prepare copies the stored version", "ground_sources")["items"]
    stale = ground_delta.stale_ids(old, items)
    base, gone = ground_delta.base(ground_check.draft_from(inventory), stale)
    unplaced = ground_delta.unplaced(base, items)
    changed = ground_delta.changed_context(old, items)
    prep = ground_delta.prep_changes(_read(ws, "ground", stored + PREP, "prepare copies the stored version"),
                                     _prep(ws))
    where = f"stored v{record['version']} (run {record['source_run']})"
    _write(folder / ground_delta.BASE, base)
    summary = {"version": record["version"], "stale": sorted(stale), "left": gone, "prep_changed": prep,
               "unplaced": [i["id"] for i in unplaced], "changed": [i["id"] for i in changed]}
    if not (stale or unplaced or changed or prep):
        for name in (INVENTORY, CHECK_FINAL):
            shutil.copyfile(folder / stored / name, folder / name)
        _write(folder / DRAFT, base)
        _write(folder / DELTA, {**summary, "model": False})
        ws.decide("ground", "reuse", f"{where}: no source item new, changed or gone",
                  source_run=record["source_run"], store_version=record["version"])
        return {"model": "no", "source": where, "design_files": status, "fixture": fixture}
    model = bool(unplaced or changed)
    _write(folder / DELTA, {**summary, "model": model})
    reason = (f"{where}: {len(unplaced)} unplaced item(s), {len(changed)} changed context item(s), "
              f"{len(stale)} stale citation id(s)" + (f", changed {', '.join(prep)}" if prep else ""))
    ws.decide("ground", "delta", reason, source_run=record["source_run"], store_version=record["version"])
    if not model:
        _write(folder / DRAFT, base)
        return {"model": "no", "source": where, "stale": len(stale), "design_files": status, "fixture": fixture}
    text = ground_task.task(app, status, unplaced + changed, questions,
                            placed=ground_delta.placed_section(base, record["version"]),
                            tools=tools_registry.task_section("ground"))
    _write(folder / TASK, text)
    return {"model": "yes", "design_files": status, "fixture": fixture, "unplaced": len(unplaced),
            "changed": len(changed), "stale": len(stale), "task_chars": len(text), "task": text}


def _delta(ws: Workspace) -> dict | None:
    """ground_collect's delta record when this run settled reuse or delta over a stored ground."""
    decision = ws.decision("ground")
    if not decision or decision["decision"] not in ("reuse", "delta"):
        return None
    return _read(ws, "ground", DELTA, "ground_collect writes it")


def _merged(ws: Workspace, raw: str, keep_first: bool = False) -> dict:
    """A delta reply (additions) checked against its contract and merged into the base -> draft.json."""
    folder = ws.folder("ground")
    additions = _parse(raw)
    problems = contracts.check_json("ground_additions", additions, "the reply")
    if problems:
        raise GroundError("the delta reply is not a ground_additions object: " + "; ".join(problems[:SHOWN_PROBLEMS]))
    if keep_first and (folder / ground_delta.ADDITIONS).is_file():
        shutil.copyfile(folder / ground_delta.ADDITIONS, folder / FIRST_ADDITIONS)
    _write(folder / ground_delta.ADDITIONS, additions)
    base = _read(ws, "ground", ground_delta.BASE, "ground_collect writes it")
    merged = ground_delta.merge(base, additions)
    _write(folder / DRAFT, merged)
    return merged


def _check(ws: Workspace, ctx: ground_check.Context, draft: dict, delta: dict | None) -> dict:
    """Every ground check; over a stored base also the kept check (no stored entry changed)."""
    found = ground_check.check_draft(ctx, draft)
    if delta is None:
        return found
    kept = ground_delta.kept(_read(ws, "ground", ground_delta.BASE, "ground_collect writes it"), draft)
    problems = found["problems"] + kept
    return {**found, "verdict": "retry" if problems else found["verdict"], "problems": problems,
            "counts": {**found["counts"], "kept": len(kept)}}


def check(ws: Workspace, raw: str) -> dict:
    """The draft pass: the model's reply -> draft.json and check.json; on retry the revision text."""
    folder = ws.folder("ground")
    delta = _delta(ws)
    if delta is not None and not delta["model"]:
        return {"verdict": "ok", "source": f"stored v{delta['version']}, no model step"}
    if delta is not None:
        draft = _merged(ws, raw)
        reply = (folder / ground_delta.ADDITIONS).read_text(encoding="utf-8")
    else:
        draft = _parse(raw)
        _write(folder / DRAFT, draft)
        reply = json.dumps(draft, ensure_ascii=False, indent=1)
    found = _check(ws, context(ws), draft, delta)
    _write(folder / CHECK, _result(found, "draft"))
    out = {"verdict": found["verdict"], "problems": len(found["problems"]), **found["counts"]}
    if found["verdict"] == "retry":
        shutil.copyfile(folder / DRAFT, folder / FIRST_DRAFT)
        task_text = (folder / TASK).read_text(encoding="utf-8")
        out["revise_task"] = ground_task.revise(task_text, reply, found["problems"])
    return out


def _source(prep: dict) -> dict:
    out = {"product": prep["product"], "capabilities": prep["capabilities"]["from"],
           "notes": [n["from"] for n in prep["notes"]], "fixture": prep["fixture"]["from"]}
    if prep.get("commit"):
        out["commit"] = prep["commit"]
    return out


def run(ws: Workspace, raw: str) -> dict:
    """The final pass: the revised reply (if there was one) is the draft; clean -> inventory.json, else fail loud."""
    folder = ws.folder("ground")
    delta = _delta(ws)
    revised = bool((raw or "").strip())
    if revised and delta is not None:
        _merged(ws, raw, keep_first=True)
    elif revised:
        _write(folder / DRAFT, _parse(raw))
    elif not (folder / DRAFT).is_file():
        raise GroundError("03-ground/draft.json is missing: the model step wrote no draft")
    draft = json.loads((folder / DRAFT).read_text(encoding="utf-8"))
    ctx = context(ws)
    if delta is not None and ws.decision("ground")["decision"] == "reuse":
        return _reused(ws, ctx, draft, delta)
    found = _check(ws, ctx, draft, delta)
    _write(folder / CHECK_FINAL, _result(found, "final"))
    if found["problems"]:
        raise GroundError(model_step.failure(found["problems"], f"03-ground/{CHECK_FINAL}"))
    prep = _prep(ws)
    inventory = ground_check.outputs(ctx, draft, _status(ws), _source(prep))
    _write(folder / INVENTORY, inventory)
    _fixture_holds(ws)
    return {"revised": revised, "screens": len(inventory["screens"]),
            "data_needed": sum(len(s.get("data_needed", [])) for s in inventory["screens"]), **found["counts"],
            **({"stage_status": "delta"} if delta is not None else {})}


def _fixture_holds(ws: Workspace) -> None:
    fixture_check = _read(ws, "ground", FIXTURE_CHECK, "ground_collect writes it", "fixture_check")
    if fixture_check["verdict"] != "pass":
        raise GroundError(f"03-ground/{FIXTURE} breaks {len(fixture_check['problems'])} invariant(s): "
                          + "; ".join(f"{p['check']} {p['where']}: {p['problem']}"
                                      for p in fixture_check["problems"][:SHOWN_PROBLEMS]))


def _reused(ws: Workspace, ctx: ground_check.Context, draft: dict, delta: dict) -> dict:
    """The stored inventory and final check, copied in by ground_collect: still byte-identical to the store,
    within contract, and the stored draft still passes every check against today's sources."""
    folder = ws.folder("ground")
    stored_copy.verify(ws, "ground")
    for name in (INVENTORY, CHECK_FINAL):
        if (folder / name).read_bytes() != (folder / ground_delta.STORED / name).read_bytes():
            raise GroundError(f"03-ground/{name} differs from the stored copy it was reused from")
    inventory = _read(ws, "ground", INVENTORY, "ground_collect copies it", "inventory")
    found = ground_check.check_draft(ctx, draft)
    if found["problems"]:
        raise GroundError("the reused inventory no longer passes: "
                          + model_step.failure(found["problems"], "03-ground/check.json"))
    _fixture_holds(ws)
    return {"revised": False, "screens": len(inventory["screens"]), "stage_status": "reused",
            "source": f"stored v{delta['version']}", **found["counts"]}
