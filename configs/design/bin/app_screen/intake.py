"""Stage 1, intake: the owner's words as requirements (his words verbatim, source, kind, what each maps to)
and the clarification questions (rule 33: ask instead of guessing), in 01-request/.

Three script steps around one fenced model step (configs/design/agents/design_app_screen_intake_v1.yaml):

    intake_collect  real: the sources document (request_json, or 01-request/sources.json put there by the
                    host's collect) checked and written to 01-request/sources.json; says model yes
    (intake_read)   the model reads sources.json and writes 01-request/draft.json
    intake_check    the draft held to the sources (intake_check.py) -> 01-request/check.json; verdict
                    retry sends the problems back to the model once (intake_revise)
    intake          the same checks on the final draft -> check-final.json; clean: requirements.json and
                    questions.json; any problem left fails the stage loud
"""
from __future__ import annotations

import json
import shutil

from . import intake_check, intake_sources, model_step
from .workspace import Workspace

SOURCES = "sources.json"
DRAFT = "draft.json"
FIRST_DRAFT = "draft-first.json"
CHECK = "check.json"
CHECK_FINAL = "check-final.json"


class IntakeError(ValueError):
    """Intake cannot go on: no sources, or the final draft still breaks a check."""


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _read(path, what: str):
    if not path.is_file():
        raise IntakeError(f"{path.relative_to(path.parents[1]).as_posix()} is missing ({what})")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise IntakeError(f"{path.name}: not readable JSON ({exc})") from None


def sources(ws: Workspace) -> dict:
    return intake_sources.load(_read(ws.folder("intake") / SOURCES, "intake_collect writes it"))


def collect(ws: Workspace, raw: str) -> dict:
    path = ws.folder("intake") / SOURCES
    product = ws.run()["product"]
    if raw.strip():
        doc = intake_sources.from_input(raw, product)
        _write(path, doc)
    elif path.is_file():
        doc = intake_sources.from_input(path.read_text(encoding="utf-8"), product)
    else:
        raise IntakeError("no sources: give request_json (a sources document, or request + source + description) "
                          "or collect them into 01-request/sources.json on the host first")
    kinds = sorted({item["kind"] for item in doc["items"]})
    return {"model": "yes", "items": len(doc["items"]), "kinds": kinds}


def _draft(ws: Workspace):
    path = ws.folder("intake") / DRAFT
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"unreadable": True}


_result = model_step.check_record


def check(ws: Workspace, raw: str) -> dict:
    """The draft pass: write check.json; on retry keep the first draft beside the one the model revises."""
    folder = ws.folder("intake")
    draft = _draft(ws)
    found = intake_check.check_draft(sources(ws), draft if draft is not None else {})
    if draft is None:
        found["problems"].insert(0, {"check": "schema", "where": "(file)", "problem": "01-request/draft.json is missing"})
        found["verdict"] = "retry"
    _write(folder / CHECK, _result(found, "draft"))
    if found["verdict"] == "retry" and draft is not None:
        shutil.copyfile(folder / DRAFT, folder / FIRST_DRAFT)
    return {"verdict": found["verdict"], "problems": len(found["problems"]), **found["counts"]}


def run(ws: Workspace, raw: str) -> dict:
    """The final pass: a clean draft becomes requirements.json and questions.json; any problem fails loud."""
    folder = ws.folder("intake")
    src = sources(ws)
    draft = _draft(ws)
    if draft is None:
        raise IntakeError("01-request/draft.json is missing: the model step wrote no draft")
    found = intake_check.check_draft(src, draft)
    _write(folder / CHECK_FINAL, _result(found, "final"))
    if found["problems"]:
        raise IntakeError(model_step.failure(found["problems"], f"01-request/{CHECK_FINAL}"))
    requirements, questions = intake_check.outputs(src, draft)
    _write(folder / "requirements.json", requirements)
    _write(folder / "questions.json", questions)
    return {"revised": (folder / FIRST_DRAFT).is_file(), **found["counts"]}
