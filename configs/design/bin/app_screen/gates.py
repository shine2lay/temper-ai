"""The two owner gates of design_app_screen_v1: direction (after 04-directions) and final (after 07-show).

The gate's answer arrives as JSON text (temper's gate response):
    {"choice": "a" | "approve" | "changes", "decided_by": "owner" | "design",
     "owner_words": "<his words verbatim, owner only>", "source": "<where he said it>",
     "reason": "<why>", "comments": [<Show&Tell comment numbers to edit for>]}
It is checked, completed with prediction (the judges' guess, filled by W5) and taste (the line W5 appends
to the owner's taste file: pending-w5 for a real answer, not-taste for a fixture run), and written to
gate_<name>.json. Nobody's answer is invented: a missing or broken answer fails the step.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from . import contracts, known_case
from .workspace import Workspace

GATES = {"direction": "directions", "final": "show"}
FIELDS = ("choice", "decided_by", "owner_words", "source", "reason", "comments")


class GateError(ValueError):
    """The gate answer is missing or breaks the gate contract."""


def answer(ws: Workspace, gate: str, raw: str) -> dict:
    if gate not in GATES:
        raise GateError(f"unknown gate {gate!r}; gates are {', '.join(GATES)}")
    if not (raw or "").strip():
        raise GateError(f"gate {gate}: no answer given; answer it with choice, decided_by, source and reason")
    try:
        given = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(f"gate {gate}: the answer is not JSON ({exc.msg})") from None
    if not isinstance(given, dict):
        raise GateError(f"gate {gate}: the answer must be a JSON object")
    unknown = sorted(set(given) - set(FIELDS))
    if unknown:
        raise GateError(f"gate {gate}: unknown answer fields {', '.join(unknown)}")
    record = {"gate": gate, "choice": given.get("choice"), "decided_by": given.get("decided_by"),
              "owner_words": given.get("owner_words", ""), "source": given.get("source"), "reason": given.get("reason"),
              "prediction": None, "taste": "not-taste" if ws.mode == "fixture" else "pending-w5",
              "at": datetime.now(UTC).isoformat(timespec="seconds")}
    if gate == "final":
        record["comments"] = given.get("comments", [])
    if record["decided_by"] == "design" and record["owner_words"]:
        raise GateError(f"gate {gate}: owner_words are for decided_by owner only (his words, verbatim)")
    label = f"gate_{gate}.json"
    problems = contracts.check_json("gate", record, label)
    if gate == "direction":
        problems += contracts.gate_choice_problems(ws, record, label)
    if gate == "final" and record.get("choice") == "changes" and not record.get("comments"):
        problems.append(f"{label}: comments: changes needs the comment numbers the next build answers")
    if problems:
        raise GateError(f"gate {gate}: " + "; ".join(problems))
    path = ws.folder(GATES[gate]) / label
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    out = {"gate": gate, "choice": record["choice"], "decided_by": record["decided_by"], "verdict": record["choice"],
           "file": path.relative_to(ws.path).as_posix()}
    if ws.mode == "fixture":
        out["known_case_choice"] = known_case.gate_answer(ws, gate).get("choice")
    return out


def final_next(ws: Workspace) -> dict:
    """After the final gate: the verdict again, for the workflow's loop back to build on changes."""
    path = ws.folder("show") / "gate_final.json"
    if not path.is_file():
        raise GateError("gate_final.json is missing: the final gate has not been answered")
    record = json.loads(path.read_text())
    return {"verdict": record["choice"], "comments": record.get("comments", [])}
