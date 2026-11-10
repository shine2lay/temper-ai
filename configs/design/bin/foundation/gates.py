"""Two owner gates for design_foundation_v1: gate_direction (after 03-proof) and gate_final (after 05-checks).

Follows owner rule (2026-11-04): workflows keep two owner gates (direction + final) and encode every owner gate
answer + reason + taste anchors into ~/design-lab/taste/owner.md (overridable via DESIGN_TASTE_FILE in tests).
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app_screen.gates import GateError

from . import contracts
from .workspace import Workspace

GATES = {
    "direction": "directions",
    "final": "checks",
}
ALLOWED_FIELDS = {
    "choice",
    "decided_by",
    "owner_words",
    "taste_anchors",
    "source",
    "reason",
    "comments",
    "at",
}
DEFAULT_TASTE_FILE = Path("~/design-lab/taste/owner.md")


def compute_direction_prediction(ws: Workspace, actual_choice: str | None) -> dict[str, Any]:
    step_ws = ws if ws.step else ws.for_step("gate_direction")
    directions = step_ws.read_json("02-directions/directions.json")
    rec = str(directions.get("recommended") or "a")
    return {
        "choice": rec,
        "matched": bool(actual_choice is not None and actual_choice == rec),
        "basis": f"02-directions/directions.json recommended={rec!r}",
    }


def compute_final_prediction(ws: Workspace, actual_choice: str | None) -> dict[str, Any]:
    step_ws = ws if ws.step else ws.for_step("gate_final")
    round_num = max(1, step_ws.round) if step_ws.run_file.is_file() else 1
    checks_rel = f"05-checks/round-{round_num}/checks.json"
    checks_verdict = "missing"
    if (step_ws.path / checks_rel).is_file():
        checks_doc = step_ws.read_json(checks_rel)
        checks_verdict = str(checks_doc.get("verdict") or "unknown")
    pred_choice = "approve" if checks_verdict == "done" else "changes"
    return {
        "choice": pred_choice,
        "matched": bool(actual_choice is not None and actual_choice == pred_choice),
        "basis": f"{checks_rel} verdict={checks_verdict!r}",
    }


def _append_owner_taste(ws: Workspace, record: dict[str, Any]) -> str:
    step_name = f"gate_{record['gate']}"
    step_ws = ws if ws.step else ws.for_step(step_name)
    product = str(step_ws.run().get("product") or "unknown") if step_ws.run_file.is_file() else "unknown"
    pred = record["prediction"]
    ts = str(record["at"])
    owner_words = str(record.get("owner_words") or "").replace("\n", " ").strip()
    source = str(record.get("source") or "").replace("\n", " ").strip()
    reason = str(record.get("reason") or "").replace("\n", " ").strip()
    anchors = record.get("taste_anchors") or []
    anchors_part = f" | taste_anchors={json.dumps(anchors, ensure_ascii=False)}" if anchors else ""

    line = (
        f"- {ts} | workflow=design_foundation_v1 | product={product} | gate={record['gate']} "
        f"| choice={record['choice']} | prediction={pred['choice']} (matched={pred['matched']}) "
        f'| owner_words="{owner_words}"{anchors_part} | source={source} | reason={reason}\n'
    )

    ws_taste = step_ws.path / "taste-owner.md"
    existing = (
        step_ws.read_text("taste-owner.md")
        if ws_taste.is_file()
        else "# Owner Taste Log (design_foundation_v1)\n\n"
    )
    ws_taste.write_text(existing + line, encoding="utf-8")

    env_override = os.environ.get("DESIGN_TASTE_FILE")
    target = Path(env_override).expanduser() if env_override is not None else DEFAULT_TASTE_FILE.expanduser()
    if str(target).strip():
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            target.write_text("# Owner Taste Log\n\n" + line, encoding="utf-8")
        else:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line)

    return line


def answer(ws: Workspace, gate: str, raw: str) -> dict[str, Any]:
    if gate not in GATES:
        raise GateError(f"unknown foundation gate {gate!r}; gates are {', '.join(GATES)}")
    step_name = f"gate_{gate}"
    step_ws = ws.for_step(step_name)

    if not (raw or "").strip():
        raise GateError(f"gate {gate}: empty gate response; expected JSON with choice, decided_by, source, reason")
    try:
        given = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(f"gate {gate}: response is not valid JSON ({exc.msg})") from None
    if not isinstance(given, dict):
        raise GateError(f"gate {gate}: response must be a JSON object")

    unknown = sorted(set(given) - ALLOWED_FIELDS)
    if unknown:
        raise GateError(f"gate {gate}: unknown response fields: {', '.join(unknown)}")

    choice = given.get("choice")
    decided_by = given.get("decided_by")
    owner_words = str(given.get("owner_words") or "").strip()
    if decided_by == "design" and owner_words:
        raise GateError(f"gate {gate}: owner_words is only allowed when decided_by == 'owner'")
    if decided_by == "owner" and not owner_words:
        raise GateError(f"gate {gate}: decided_by == 'owner' requires verbatim owner_words")

    if gate == "direction":
        directions = step_ws.read_json("02-directions/directions.json")
        valid_ids = [d["id"] for d in directions.get("directions") or []]
        if choice not in valid_ids:
            raise GateError(
                f"gate direction: choice {choice!r} is not in 02-directions/directions.json ({valid_ids})"
            )
        prediction = compute_direction_prediction(step_ws, str(choice))
    else:
        prediction = compute_final_prediction(step_ws, str(choice) if isinstance(choice, str) else None)

    encode_taste = decided_by == "owner"
    taste_status = "saved" if encode_taste else "not-taste"
    at_ts = str(given.get("at") or datetime.now(UTC).isoformat(timespec="seconds"))

    record: dict[str, Any] = {
        "gate": gate,
        "choice": choice,
        "decided_by": decided_by,
        "source": given.get("source"),
        "taste": taste_status,
        "prediction": prediction,
        "at": at_ts,
    }
    if given.get("reason"):
        record["reason"] = str(given["reason"])
    if owner_words:
        record["owner_words"] = owner_words

    if gate == "direction":
        if "taste_anchors" in given and given["taste_anchors"] is not None:
            record["taste_anchors"] = list(given["taste_anchors"])
        contracts.validate("gate_direction", record, step="gate_direction")
        out_path = step_ws.folder("directions") / "gate_direction.json"
    else:
        round_num = max(1, step_ws.round) if step_ws.run_file.is_file() else 1
        if choice == "changes" and not given.get("comments"):
            raise GateError("gate final: choice 'changes' requires non-empty comments[]")
        record["round"] = round_num
        record["verdict"] = choice
        record["comments"] = list(given.get("comments") or [])
        contracts.validate("gate_final", record, step="gate_final")
        out_path = step_ws.folder("checks") / "gate_final.json"
        if choice == "changes":
            step_ws.next_round()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if encode_taste:
        _append_owner_taste(step_ws, record)

    step_ws.mark(step_name, "done", choice=record["choice"], decided_by=record["decided_by"])
    return {
        "ok": True,
        "gate": gate,
        "choice": record["choice"],
        "verdict": record["choice"],
        "decided_by": record["decided_by"],
        "taste": record["taste"],
        "prediction": record["prediction"],
        "file": out_path.relative_to(step_ws.path).as_posix(),
    }
