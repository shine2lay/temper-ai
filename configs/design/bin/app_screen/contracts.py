"""What each app-screen stage must leave in the workspace, and validate(step, workspace).

One JSON schema per stage output file, plus the files that must exist (captures, pages, specs) and the
few rules a schema cannot say (a capture an audit names exists, a review's verdict follows its Must
findings, a gate picks a direction that exists). validate() raises ContractError listing every problem
as "<file>: <field>: <reason>"; it returns the files it checked. Model-free.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .workspace import FOLDERS, Workspace

VERSION = 1


class ContractError(ValueError):
    """A stage's output breaks its contract; the message names each file, field and reason."""


# ---------------------------------------------------------------- shared pieces
TEXT = {"type": "string", "minLength": 1}
ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.@-]{0,79}$"}
WIDTH = {"type": "integer", "minimum": 200, "maximum": 4000}
STATE = {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,39}$"}
REL_PATH = {"type": "string", "minLength": 1, "pattern": r"^(?!/)(?!.*\.\./)[^\\]+$"}


def obj(required: dict, optional: dict | None = None, extra: bool = False) -> dict:
    return {"type": "object", "required": list(required), "properties": {**required, **(optional or {})},
            "additionalProperties": extra}


def items(schema: dict, least: int = 1) -> dict:
    return {"type": "array", "items": schema, "minItems": least}


# A measured check (directions and the checks stage): what was measured, on which element, where, and the proof.
# Stage 6a adds where it was measured and what class of finding it is for the review (6b), all optional so an
# older checks.json stays valid: severity blocker (a Must input) or should, and the view it was measured in.
CHECK = obj({"id": ID, "value": {}, "result": {"enum": ["pass", "fail", "skipped"]}, "evidence": TEXT,
             "element": TEXT, "location": TEXT},
            {"severity": {"enum": ["blocker", "should"]}, "screen": ID, "state": STATE, "width": WIDTH,
             "view": TEXT, "count": {"type": "integer", "minimum": 0}, "summary": {"type": "boolean"}})
CHECKS = obj({"checks": items(CHECK)}, {"round": {"type": "integer", "minimum": 1}, "tool": TEXT,
                                        "views": {"type": "integer", "minimum": 0},
                                        "blockers": {"type": "integer", "minimum": 0},
                                        "shoulds": {"type": "integer", "minimum": 0}})

# 01-request: a source item (the owner's words, one request, comment or answer), and what intake makes of it.
SOURCE_ID = {"type": "string", "pattern": "^S[0-9]{1,3}$"}
REQ_ID = {"type": "string", "pattern": "^R[0-9]{1,3}$"}
QUESTION_ID = {"type": "string", "pattern": "^Q[0-9]{1,3}$"}
KINDS = ["goal", "feature", "change", "constraint", "taste"]
SOURCE_KINDS = ["request", "comment", "answer", "history"]
CHOICES = {"type": "array", "items": TEXT, "minItems": 2, "maxItems": 4}
ANSWERED = {"if": {"properties": {"status": {"const": "answered"}}, "required": ["status"]},
            "then": {"required": ["answer", "answer_source"], "properties": {"answer": TEXT, "answer_source": TEXT}}}

# A script check of a model's draft (intake_check, existing_check): the verdict and every problem found.
STEP_CHECK = obj({"verdict": {"enum": ["ok", "retry"]}, "pass": {"enum": ["draft", "final"]},
                  "counts": {"type": "object"}, "problems": items(obj(
                      {"check": TEXT, "where": TEXT, "problem": TEXT}), least=0)})

# 02-existing: a journey, a problem in it (observation, Nielsen severity 0-4, kind) and the evidence it rests on.
# A ref points at one capture's measure (its value exactly as audit.json has it), at text visible in one
# capture (texts.json), or at a per-width total (audit.json totals).
JOURNEY_ID = {"type": "string", "pattern": "^J[0-9]{1,2}$"}
PROBLEM_ID = {"type": "string", "pattern": "^P[0-9]{1,2}$"}
SEVERITY = {"type": "integer", "minimum": 0, "maximum": 4}
MEASURED_KINDS = ["layout-width", "text-size", "tap-target", "truncation", "buried", "error-recovery"]
PROBLEM_KINDS = MEASURED_KINDS + ["overload", "navigation", "wording", "feedback", "state", "other"]
REF = {"oneOf": [obj({"capture": ID, "measure": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,60}$"},
                       "value": {}}),
                  obj({"capture": ID, "text": TEXT}),
                  obj({"total": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,60}@[0-9]{3,4}$"},
                       "value": {"type": "integer", "minimum": 0}}, {"of": {"type": "integer", "minimum": 1}})]}
KEEP = obj({"what": TEXT, "evidence": items(REF)})

# 03-ground: a source item's id says what it is: page:<route>, api:<METHOD path>, note:<file>#L<n>,
# screen:<stage 2 screen>, req:<requirement>, journey:<stage 2 journey>.
GROUND_KINDS = ["page", "api", "note", "screen", "seen", "req", "journey"]
SHA256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
GROUND_REF = {"type": "string", "pattern": "^(page|api|note|screen|seen|req|journey):[^\\s].{0,200}$"}
GROUND_STATE = obj({"name": STATE}, {"sources": items(GROUND_REF, least=0)})
GROUND_SHOW = obj({"what": TEXT, "sources": items(GROUND_REF)})
GROUND_ACTION = obj({"id": ID, "what": TEXT, "states": items(STATE), "sources": items(GROUND_REF)})
GROUND_EXCLUDED = obj({"source": GROUND_REF, "reason": TEXT})
CAPABILITY = obj({"kind": {"enum": ["http", "page", "cli"]}, "key": TEXT, "group": {"type": "string"},
                  "intent": {"type": "string"}}, {"where": TEXT})

# 05-build, the prototype contract: one view of the build, and how the checks step opens it. A hash
# (#<screen>/<state>) or steps to click through, for a build that cannot route by hash.
STEP = {"anyOf": [obj({"click": TEXT}), obj({"goto": TEXT}), obj({"wait": {"type": "integer", "minimum": 0,
                                                                          "maximum": 10000}})]}
OPEN = {"anyOf": [obj({"hash": {"type": "string", "pattern": "^#"}}), obj({"steps": items(STEP)})]}
VIEW = obj({"screen": ID, "state": STATE, "open": OPEN}, {"widths": items(WIDTH, least=0), "what": TEXT})
BUILD_LAYOUTS = ["ledger", "board", "split", "stack", "detail", "form"]
BUILD_SHOW = obj({"ref": {"type": "string", "pattern": "^S[1-9][0-9]*$"}, "heading": TEXT, "copy": TEXT,
                  "fields": items(TEXT, least=1)}, {"reqs": items(REQ_ID, least=0)})
BUILD_ACTION = obj({"id": ID, "label": TEXT, "kind": {"enum": ["primary", "secondary"]},
                    "states": items(STATE), "feedback": TEXT})
BUILD_STATE = obj({"headline": TEXT, "summary": TEXT}, {"badge": TEXT})
BUILD_SCREEN_DRAFT = obj(
    {"id": ID, "title": TEXT, "layout": {"enum": BUILD_LAYOUTS}, "lead": TEXT,
     "shows": items(BUILD_SHOW, least=0), "actions": items(BUILD_ACTION, least=0),
     "states": {"type": "object", "minProperties": 1, "propertyNames": STATE,
                "additionalProperties": BUILD_STATE}},
    {"notes": {"anyOf": [TEXT, items(TEXT, least=0)]}})
DIRECTION_DRAFT = obj(
    {"id": {"type": "string", "pattern": "^[a-z]$"}, "name": TEXT, "idea": TEXT,
     "screens": items(BUILD_SCREEN_DRAFT, least=1)},
    {"notes": {"anyOf": [TEXT, items(TEXT, least=0)]}})

SCHEMAS: dict[str, dict] = {
    # 01-request
    "sources": obj({"product": ID, "description": TEXT, "items": items(obj(
        {"id": SOURCE_ID, "kind": {"enum": SOURCE_KINDS}, "text": TEXT, "source": TEXT},
        {"context": TEXT, "ref": {"type": "object"}}))}),
    # The model's draft (intake_read / intake_revise): requirements tied to one source item each, questions
    # about one or more items. The script fills each source line from the item, never the model.
    "intake_draft": obj({"requirements": items(obj(
        {"id": REQ_ID, "item": SOURCE_ID, "owner_words": TEXT, "kind": {"enum": KINDS}, "means": TEXT,
         "maps_to": items(TEXT)},
        {"open_questions": items(QUESTION_ID, least=0)})),
        "questions": items(obj(
            {"id": QUESTION_ID, "about": items(SOURCE_ID), "question": TEXT, "why": TEXT,
             "status": {"enum": ["open", "answered"]}},
            {"choices": CHOICES, "answer": {"type": ["string", "null"]},
             "answer_source": {"anyOf": [SOURCE_ID, {"type": "null"}]}}) | ANSWERED, least=0)}),
    "requirements": obj({"product": ID, "items": items(obj(
        {"id": REQ_ID, "owner_words": TEXT, "source": TEXT, "kind": {"enum": KINDS},
         "maps_to": items({"type": "string", "minLength": 1})},
        {"item": SOURCE_ID, "means": TEXT, "open_questions": items(QUESTION_ID, least=0)}))}),
    "questions": obj({"questions": items(obj(
        {"id": QUESTION_ID, "question": TEXT, "status": {"enum": ["open", "answered"]}},
        {"answer": {"type": ["string", "null"]}, "answer_source": {"type": ["string", "null"]},
         "about": items(SOURCE_ID), "why": TEXT, "choices": CHOICES}) | ANSWERED, least=0)}),
    "intake_check": STEP_CHECK,
    # 02-existing
    "audit": obj({"source": TEXT, "screens": items(obj(
        {"id": ID, "width": WIDTH, "state": STATE, "capture": REL_PATH,
         "measures": {"type": "object", "minProperties": 1}},
        {"what": TEXT, "screen": ID, "name": TEXT, "height": {"type": "integer", "minimum": 1},
         "account": {"type": ["string", "null"]}, "commit": TEXT}))},
        {"notes": {"type": "object"}, "product": ID, "totals": {"type": "object"},
         "base_url": TEXT, "commit": TEXT, "version": TEXT}),
    # The model's draft (existing_read / existing_revise): journeys naming the problems they hit, each problem
    # observed and tied to captures by refs the script checks against audit.json and texts.json.
    "existing_draft": obj({"journeys": items(obj(
        {"id": JOURNEY_ID, "name": TEXT, "goal": TEXT, "screens": items(ID),
         "problems": items(PROBLEM_ID, least=0), "keep": items(KEEP, least=0)},
        {"steps": items(TEXT, least=0), "requirements": items(REQ_ID, least=0)})),
        "problems": items(obj(
            {"id": PROBLEM_ID, "claim": TEXT, "severity": SEVERITY, "kind": {"enum": PROBLEM_KINDS},
             "evidence": items(REF)}), least=0)}, {"notes": TEXT}),
    "existing_check": STEP_CHECK,
    "journeys": obj({"journeys": items(obj(
        {"id": JOURNEY_ID, "name": TEXT, "goal": TEXT,
         "problems": items(obj({"claim": TEXT, "evidence": items(TEXT)},
                               {"id": PROBLEM_ID, "severity": SEVERITY, "kind": {"enum": PROBLEM_KINDS},
                                "refs": items(REF)}), least=0)},
        {"screens": items(ID, least=0), "keep": items(TEXT, least=0), "keep_refs": items(KEEP, least=0),
         "steps": items(TEXT, least=0), "requirements": items(REQ_ID, least=0)}))}, {"source": TEXT}),
    # 03-ground
    "fixture": {"type": "object", "minProperties": 1},
    # The host's ground-prep record: where the stage's sources came from (ground_host.py).
    "ground_prep": obj({"product": ID, "capabilities": obj({"from": TEXT, "items": items(CAPABILITY, least=0)}),
                        "notes": items(obj({"name": ID, "from": TEXT, "file": REL_PATH}), least=0),
                        "fixture": obj({"from": TEXT, "sha256": SHA256},
                                       {"invariants": {"type": "object"}, "parts_from": TEXT,
                                        "parts": {"type": "object", "minProperties": 1,
                                                  "propertyNames": {"pattern": "^[A-Za-z0-9_][A-Za-z0-9_.-]*$"},
                                                  "additionalProperties": SHA256}}),
                        "design_files": obj({"registered": {"type": "boolean"}}, {"from": TEXT})},
                       {"commit": TEXT}),
    # Every source item the model must place, with its id (ground_sources.py).
    "ground_sources": obj({"product": ID, "items": items(obj(
        {"id": GROUND_REF, "kind": {"enum": GROUND_KINDS}, "text": TEXT},
        {"group": TEXT, "where": TEXT}))}),
    "fixture_check": obj({"verdict": {"enum": ["pass", "fail"]}, "checks": {"type": "integer", "minimum": 0},
                          "problems": items(obj({"check": TEXT, "where": TEXT, "problem": TEXT}), least=0)}),
    # The model's draft (ground_read / ground_revise): screens with what they show, their states and actions,
    # each citing source ids from 03-ground/sources.json; sources left out sit in excluded[] with a reason.
    "ground_draft": obj({"screens": items(obj(
        {"id": ID, "name": TEXT, "sources": items(GROUND_REF), "states": items(GROUND_STATE)},
        {"shows": items(GROUND_SHOW, least=0), "actions": items(GROUND_ACTION, least=0)})),
        "excluded": items(GROUND_EXCLUDED, least=0)}, {"notes": TEXT}),
    # A delta reply (step 4, ground_delta.py): the same shape, holding only what the unplaced items add; an entry
    # with a stored screen's id adds to it, so its sources and states may be empty. Merged by script, then the
    # merged draft is held to ground_draft and every check.
    "ground_additions": obj({"screens": items(obj(
        {"id": ID, "name": TEXT, "sources": items(GROUND_REF, least=0), "states": items(GROUND_STATE, least=0)},
        {"shows": items(GROUND_SHOW, least=0), "actions": items(GROUND_ACTION, least=0)}), least=0),
        "excluded": items(GROUND_EXCLUDED, least=0)}, {"notes": TEXT}),
    "ground_check": STEP_CHECK,
    "inventory": obj({"design_files": {"enum": ["defined", "partial", "none"]}, "screens": items(obj(
        {"id": ID, "name": TEXT, "states": items(STATE), "widths": items(WIDTH)},
        {"spec": REL_PATH, "sources": items(GROUND_REF, least=0), "shows": items(GROUND_SHOW, least=0),
         "actions": items(GROUND_ACTION, least=0), "data_needed": items(TEXT, least=0),
         "state_sources": {"type": "object", "propertyNames": STATE,
                           "additionalProperties": items(GROUND_REF)}}))},
        {"source": obj({"product": ID}, {"commit": TEXT, "capabilities": TEXT, "notes": items(TEXT, least=0),
                                         "fixture": TEXT}),
         "excluded": items(GROUND_EXCLUDED, least=0)}),
    "tokens": {"type": "object", "minProperties": 1},
    # 04-directions
    "directions_draft": obj({"directions": items(DIRECTION_DRAFT, least=2)},
                            {"recommended": {"type": "string", "pattern": "^[a-z]$"},
                             "notes": {"anyOf": [TEXT, items(TEXT, least=0)]}}),
    "directions_check": obj({"verdict": {"enum": ["ok", "retry"]}, "counts": {"type": "object"},
                             "problems": items(obj({"check": TEXT, "where": TEXT, "problem": TEXT}), least=0)},
                            {"pass": {"enum": ["draft", "final"]}, "checks": items(TEXT, least=0)}),
    "directions": obj({"directions": items(obj(
        {"id": {"type": "string", "pattern": "^[a-z]$"}, "name": TEXT, "idea": TEXT, "page": REL_PATH},
        {"source": TEXT, "layout": {"enum": BUILD_LAYOUTS}, "screens": items(ID, least=1)}), least=2)},
        {"recommended": {"type": "string", "pattern": "^[a-z]$"}, "source": TEXT}),
    "direction_checks": CHECKS,
    # 05-build. views[] is the compatible extension of the prototype contract: the views to open, when the
    # build cannot follow the #<screen>/<state> hash convention. Without it they come from the inventory.
    "build_draft": obj({"screens": items(BUILD_SCREEN_DRAFT)},
                       {"notes": {"anyOf": [TEXT, items(TEXT, least=0)]}}),
    "build_check": obj({"verdict": {"enum": ["ok", "retry"]}, "counts": {"type": "object"},
                        "problems": items(obj({"check": TEXT, "where": TEXT, "problem": TEXT}), least=0)},
                       {"pass": {"enum": ["draft", "final"]}, "checks": items(TEXT, least=0)}),
    "build": obj({"direction": {"type": "string", "pattern": "^[a-z]$"}, "round": {"type": "integer", "minimum": 1},
                  "page": REL_PATH, "widths": items(WIDTH), "screens": items(obj(
                      {"id": ID, "file": REL_PATH}, {"states": items(STATE, least=0)}))},
                 {"source": TEXT, "views": items(VIEW, least=0), "main": TEXT, "placeholder": {"type": "boolean"},
                  "areas": {"type": "object", "additionalProperties": TEXT}}),
    # 06-checks/round-<n>
    "checks": CHECKS,
    "measured_items": obj({"round": {"type": "integer", "minimum": 1},
                           "blockers": {"type": "integer", "minimum": 0},
                           "shoulds": {"type": "integer", "minimum": 0},
                           "items": items(obj(
                               {"id": {"type": "string", "pattern": "^M[1-9][0-9]*$"},
                                "check": ID, "severity": {"enum": ["blocker", "should"]},
                                "screen": ID, "element": TEXT, "location": TEXT, "evidence": TEXT,
                                "count": {"type": "integer", "minimum": 1}},
                               {"states": items(STATE, least=0), "views": items(TEXT, least=0)}), least=0)}),
    "review_draft": obj({"measured": items(obj(
        {"id": {"type": "string", "pattern": "^M[1-9][0-9]*$"}, "severity": SEVERITY,
         "priority": {"enum": ["must", "should", "could", "wont"]}},
        {"suggestion": {"type": "string"}, "reason": {"type": "string"}}), least=0),
        "findings": items(obj(
            {"element": TEXT, "location": TEXT, "evidence": TEXT, "severity": SEVERITY,
             "priority": {"enum": ["must", "should", "could", "wont"]}},
            {"id": ID, "suggestion": {"type": "string"}, "reason": {"type": "string"}}), least=0)},
        {"notes": {"type": "string"}, "summary": {"type": "string"}}),
    "review_check": obj({"verdict": {"enum": ["ok", "retry"]}, "pass": {"enum": ["draft", "final"]},
                         "counts": {"type": "object"},
                         "problems": items(obj({"check": TEXT, "where": TEXT, "problem": TEXT}), least=0)},
                        {"stage": TEXT, "checked_at": TEXT, "checks": items(TEXT, least=0)}),
    "review": obj({"round": {"type": "integer", "minimum": 1}, "verdict": {"enum": ["revise", "done"]},
                   "findings": items(obj(
                       {"id": ID, "element": TEXT, "location": TEXT, "evidence": TEXT,
                        "severity": {"type": "integer", "minimum": 0, "maximum": 4},
                        "priority": {"enum": ["must", "should", "could", "wont"]}},
                       {"reason": TEXT, "check": ID, "suggestion": TEXT}) | {
                       "if": {"properties": {"priority": {"const": "wont"}}}, "then": {"required": ["reason"]}},
                       least=0)}, {"source": TEXT}),
    # 07-show
    "showtell": obj({"doc_id": {"type": "string", "pattern": "^d_[a-z0-9]{6,20}$"},
                     "version": {"type": "integer", "minimum": 1},
                     "url": {"type": "string", "pattern": "^/showtell/#/d/d_[a-z0-9]{6,20}$"}},
                    {"title": TEXT, "bundle": REL_PATH,
                     "kept_lines": {"type": "integer", "minimum": 0},
                     "prev_non_blank_lines": {"type": "integer", "minimum": 0},
                     "kept_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                     "change_note": TEXT}),
    "comments": obj({"doc_id": {"type": "string", "pattern": "^d_[a-z0-9]{6,20}$"}, "comments": items(obj(
        {"number": {"type": "integer", "minimum": 1}, "version": {"type": "integer", "minimum": 1},
         "body": TEXT, "element": {"type": "string"}, "state": TEXT},
        {"id": TEXT, "replies": items(obj({"outcome": TEXT, "version": {"type": ["integer", "null"]}, "body": TEXT}), least=0)}),
        least=0)}),
    "show_check": obj({"stage": {"const": "show"}, "round": {"type": "integer", "minimum": 1},
                       "passed": {"type": "boolean"}, "rules": {"type": "object"},
                       "problems": items(TEXT, least=0)}),
    # 08-handoff
    "design_file": obj({"kind": {"enum": ["penpot", "html-prototype"]}, "location": TEXT, "editable": {"type": "boolean"}},
                       {"note": TEXT}),
    "followup": obj({"items": items(obj(
        {"id": ID, "what": TEXT, "owner_role": ID, "source": TEXT},
        {"screen": ID, "detail": TEXT}), least=0)}),
    "handoff_check": obj({"stage": {"const": "handoff"}, "round": {"type": "integer", "minimum": 1},
                          "passed": {"type": "boolean"}, "rules": {"type": "object"},
                          "problems": items(TEXT, least=0)}),
    # gates
    "gate": obj({"gate": {"enum": ["direction", "final"]}, "choice": TEXT, "decided_by": {"enum": ["owner", "design"]},
                 "owner_words": {"type": "string"}, "source": TEXT, "reason": TEXT,
                 "prediction": {"type": ["object", "null"]}, "taste": {"enum": ["pending-w5", "saved", "not-taste"]}},
                {"comments": items({"type": "integer", "minimum": 1}, least=0), "at": TEXT}) | {
        "if": {"properties": {"decided_by": {"const": "owner"}}},
        "then": {"properties": {"owner_words": TEXT}}},
}
SCHEMAS["gate"]["allOf"] = [{"if": {"properties": {"gate": {"const": "final"}}},
                             "then": {"properties": {"choice": {"enum": ["approve", "changes"]}}}}]

# What each step must leave: (path relative to the workspace, schema name or file kind, least matches).
# "<round>" becomes round-<n> of the checks stage.
FILES: dict[str, list[tuple[str, str, int]]] = {
    # sources.json and check.json come from intake_collect and intake_check.
    "intake_collect": [("01-request/sources.json", "sources", 0)],
    "intake_check": [("01-request/check.json", "intake_check", 0)],
    "intake": [("01-request/requirements.json", "requirements", 1), ("01-request/questions.json", "questions", 1),
               ("01-request/check-final.json", "intake_check", 0)],
    # audit.json and sheet.png come from the host's capture and existing_sheet.
    "existing_collect": [("02-existing/audit.json", "audit", 0), ("02-existing/task.md", "md", 0)],
    "existing_sheet": [("02-existing/sheet.png", "png", 0)],
    "existing_check": [("02-existing/check.json", "existing_check", 0)],
    "existing": [("02-existing/captures/*.png", "png", 1), ("02-existing/audit.json", "audit", 1),
                 ("02-existing/journeys.json", "journeys", 1), ("02-existing/check-final.json", "existing_check", 0)],
    # prep.json and fixture.json come from the host's ground-prep.
    "ground_collect": [("03-ground/source/prep.json", "ground_prep", 0), ("03-ground/sources.json", "ground_sources", 0),
                       ("03-ground/task.md", "md", 0), ("03-ground/fixture-check.json", "fixture_check", 0)],
    "ground_check": [("03-ground/check.json", "ground_check", 0)],
    "ground": [("03-ground/fixture.json", "fixture", 1), ("03-ground/inventory.json", "inventory", 1),
               ("03-ground/design-files/tokens.json", "tokens", 0), ("03-ground/design-files/DESIGN.md", "md", 0),
               ("03-ground/check-final.json", "ground_check", 0)],
    "directions_collect": [("04-directions/task.md", "md", 0)],
    "directions_check": [("04-directions/check.json", "directions_check", 0)],
    "directions": [("04-directions/directions.json", "directions", 1), ("04-directions/*/index.html", "html", 2),
                   ("04-directions/*/checks.json", "direction_checks", 2),
                   ("04-directions/check-final.json", "directions_check", 0)],
    "gate_direction": [("04-directions/gate_direction.json", "gate", 1)],
    "build": [("05-build/index.html", "html", 1), ("05-build/build.json", "build", 1),
              ("05-build/shell/*", "any", 1), ("05-build/screens/*", "any", 1),
              ("05-build/task.md", "md", 0)],
    "build_check": [("05-build/check.json", "build_check", 0)],
    "build_finish": [("05-build/index.html", "html", 1), ("05-build/build.json", "build", 1),
                     ("05-build/shell/*", "any", 1), ("05-build/screens/*", "any", 1),
                     ("05-build/check-final.json", "build_check", 0)],
    "checks": [("06-checks/<round>/checks.json", "checks", 1), ("06-checks/<round>/views/*.png", "png", 0)],
    "review_collect": [("06-checks/<round>/measured_items.json", "measured_items", 0),
                       ("06-checks/<round>/sheet.png", "png", 0),
                       ("06-checks/<round>/task.md", "md", 0)],
    "review_check": [("06-checks/<round>/check.json", "review_check", 0)],
    "review": [("06-checks/<round>/review.json", "review", 1),
               ("06-checks/<round>/check-final.json", "review_check", 0)],
    "show": [("07-show/showtell.json", "showtell", 1), ("07-show/comments.json", "comments", 1),
             ("07-show/bundle.html", "html", 0), ("07-show/check.json", "show_check", 0)],
    "gate_final": [("07-show/gate_final.json", "gate", 1)],
    "gate_final_next": [],
    "handoff": [("08-handoff/spec/*.md", "md", 1), ("08-handoff/design-file.json", "design_file", 1),
                ("08-handoff/followup.json", "followup", 1), ("08-handoff/check.json", "handoff_check", 0)],
}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _where(error) -> str:
    return "/".join(str(p) for p in error.absolute_path) or "(top)"


def check_json(name: str, data: Any, label: str) -> list[str]:
    """Schema problems of one parsed file, each "<label>: <field>: <reason>"."""
    validator = Draft202012Validator(SCHEMAS[name])
    return [f"{label}: {_where(e)}: {e.message}" for e in sorted(validator.iter_errors(data), key=lambda e: list(e.path))]


def _load(path: Path, label: str, problems: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        problems.append(f"{label}: (file): not readable JSON ({exc.__class__.__name__}: {exc})")
        return None


def _file_kind(path: Path, kind: str, label: str) -> list[str]:
    if not path.is_file() or path.stat().st_size == 0:
        return [f"{label}: (file): empty or not a file"]
    head = path.read_bytes()[:512]
    if kind == "png" and not head.startswith(PNG_MAGIC):
        return [f"{label}: (file): not a PNG"]
    if kind == "html" and b"<" not in head:
        return [f"{label}: (file): not HTML"]
    return []


def _rules(step: str, ws: Workspace, data: dict[str, Any]) -> list[str]:
    """The cross-file rules a schema cannot say."""
    problems: list[str] = []
    root = ws.path
    if step == "existing" and isinstance(data.get("02-existing/audit.json"), dict):
        for i, s in enumerate(data["02-existing/audit.json"].get("screens") or []):
            cap = s.get("capture") if isinstance(s, dict) else None
            if isinstance(cap, str) and not (root / FOLDERS["existing"] / cap).is_file():
                problems.append(f"02-existing/audit.json: screens/{i}/capture: {cap} is not in 02-existing/")
    if step == "directions" and isinstance(data.get("04-directions/directions.json"), dict):
        for i, d in enumerate(data["04-directions/directions.json"].get("directions") or []):
            page = d.get("page") if isinstance(d, dict) else None
            if isinstance(page, str) and not (root / FOLDERS["directions"] / page).is_file():
                problems.append(f"04-directions/directions.json: directions/{i}/page: {page} is not in 04-directions/")
    if step == "gate_direction" and isinstance(data.get("04-directions/gate_direction.json"), dict):
        problems += gate_choice_problems(ws, data["04-directions/gate_direction.json"], "04-directions/gate_direction.json")
    if step in ("build", "build_finish") and isinstance(data.get("05-build/build.json"), dict):
        for i, s in enumerate(data["05-build/build.json"].get("screens") or []):
            f = s.get("file") if isinstance(s, dict) else None
            if isinstance(f, str) and not (root / FOLDERS["build"] / f).is_file():
                problems.append(f"05-build/build.json: screens/{i}/file: {f} is not in 05-build/")
    if step == "review":
        rel = f"06-checks/round-{ws.round}/review.json"
        review = data.get(rel)
        if isinstance(review, dict) and isinstance(review.get("findings"), list):
            must = any(isinstance(f, dict) and f.get("priority") == "must" for f in review["findings"])
            want = "revise" if must else "done"
            if review.get("verdict") != want:
                problems.append(f"{rel}: verdict: is {review.get('verdict')!r} but must be {want!r} "
                                f"({'a Must finding is open' if must else 'no Must finding is open'})")
    return problems


def gate_choice_problems(ws: Workspace, gate: dict, label: str) -> list[str]:
    path = ws.folder("directions") / "directions.json"
    try:
        ids = [d["id"] for d in json.loads(path.read_text())["directions"]]
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{label}: choice: 04-directions/directions.json is missing or broken, so the choice cannot be checked"]
    if gate.get("choice") not in ids:
        return [f"{label}: choice: {gate.get('choice')!r} is not a direction ({', '.join(ids)})"]
    return []


def validate(step: str, workspace: Workspace | Path | str) -> list[str]:
    """Check one step's output in the workspace; raise ContractError with every problem, else return the files."""
    ws = workspace if isinstance(workspace, Workspace) else Workspace(workspace)
    if step not in FILES:
        raise ContractError(f"no contract for step {step!r}; steps are {', '.join(FILES)}")
    problems: list[str] = []
    checked: list[str] = []
    data: dict[str, Any] = {}
    for pattern, kind, least in FILES[step]:
        if "<round>" in pattern:
            pattern = pattern.replace("<round>", f"round-{ws.round}")
        found = sorted(p for p in ws.path.glob(pattern) if p.is_file())
        if len(found) < least:
            problems.append(f"{pattern}: (file): needs at least {least}, found {len(found)}")
        for path in found:
            label = path.relative_to(ws.path).as_posix()
            checked.append(label)
            if kind in SCHEMAS:
                parsed = _load(path, label, problems)
                if parsed is not None:
                    data[label] = parsed
                    problems += check_json(kind, parsed, label)
            elif kind != "any":
                problems += _file_kind(path, kind, label)
    problems += _rules(step, ws, data)
    if problems:
        raise ContractError(f"{step}: {len(problems)} problem(s): " + "; ".join(problems))
    return checked
