"""The two owner gates of design_app_screen_v1: direction (after 04-directions) and final (after 07-show).

The gate's answer arrives as JSON text (temper's gate response):
    {"choice": "a" | "approve" | "changes", "decided_by": "owner" | "design",
     "owner_words": "<his words verbatim, owner only>", "source": "<where he said it>",
     "reason": "<why>", "comments": [<Show&Tell comment numbers to edit for>]}

W5 responsibilities (100% deterministic, $0.00 model cost):
1. Computes deterministic `prediction` before recording the gate answer:
   - For `gate == "direction"`: reads `04-directions/directions.json` (`recommended`, else the direction with
     the fewest `should` rows in `04-directions/<id>/checks.json`, tie-breaking to the first direction id) and
     records `prediction = {"choice": pred_choice, "matched": pred_choice == record["choice"], "basis": "..."}`.
   - For `gate == "final"`: reads `06-checks/round-<ws.round>/review.json` and `07-show/comments.json`;
     predicts `"approve"` when `review.verdict == "done"` and no comment has `state == "open"`, else `"changes"`,
     and records `prediction = {"choice": pred_choice, "matched": pred_choice == record["choice"], "basis": "..."}`.
2. Encodes owner taste (`taste` field in `gate_<name>.json`):
   - When `record["decided_by"] == "design"`, sets `"taste": "not-taste"`.
   - When `record["decided_by"] == "owner"`, appends a structured taste line
     (timestamp, product, gate, choice, `owner_words` verbatim, `source`, `reason`, `prediction.choice`,
     `prediction.matched`) to `ws.path / "taste-owner.md"` (and to `DESIGN_TASTE_FILE` when set in env)
     and sets `"taste": "saved"`.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import contracts
from .show import default_comment_id, default_doc_id
from .workspace import Workspace

GATES = {"direction": "directions", "final": "show"}
FIELDS = ("choice", "decided_by", "owner_words", "source", "reason", "comments", "at")


class GateError(ValueError):
    """The gate answer is missing or breaks the gate contract."""


def _count_should_rows(ws: Workspace, checks_path: Path) -> int:
    if not checks_path.is_file():
        return 999999
    ws_step = ws if ws.step else ws.for_step("gate_direction")
    try:
        doc = json.loads(ws_step.read_text(checks_path))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read {checks_path}: {exc}") from exc
    rows = doc.get("checks") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return 999999
    count = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        tier = str(r.get("tier") or r.get("severity") or r.get("priority") or "").lower()
        res = str(r.get("result") or r.get("status") or "").lower()
        if tier == "should" and res not in ("pass", "passed", "ok", "skipped"):
            count += 1
        elif res in ("warn", "warning", "should", "fail"):
            count += 1
    return count


def compute_direction_prediction(ws: Workspace, actual_choice: str | None) -> dict[str, Any]:
    """Deterministically predict the direction gate choice from 04-directions/directions.json and checks.json."""
    ws = ws if ws.step else ws.for_step("gate_direction")
    dir_folder = ws.folder("directions")
    dir_file = dir_folder / "directions.json"
    pred_choice = "a"
    basis = "fallback default direction 'a' (04-directions/directions.json not present)"

    if dir_file.is_file():
        try:
            doc = json.loads(ws.read_text(dir_file))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateError(f"cannot read {dir_file}: {exc}") from exc
        if isinstance(doc, dict):
            dirs = [d for d in (doc.get("directions") or []) if isinstance(d, dict) and d.get("id")]
            dir_ids = [str(d["id"]) for d in dirs]
            rec = doc.get("recommended")
            if isinstance(rec, str) and rec and (not dir_ids or rec in dir_ids):
                pred_choice = rec
                rec_why = str(doc.get("recommendation_reason") or doc.get("why") or "recommended in directions.json")
                basis = f"04-directions/directions.json recommended={rec!r} ({rec_why})"
            elif dir_ids:
                scored: list[tuple[int, int, str]] = []
                for idx, did in enumerate(dir_ids):
                    c_path = dir_folder / did / "checks.json"
                    should_cnt = _count_should_rows(ws, c_path)
                    scored.append((should_cnt, idx, did))
                scored.sort()
                best_cnt, _, best_id = scored[0]
                pred_choice = best_id
                basis = (
                    f"direction {best_id!r} selected by fewest should/non-pass rows "
                    f"({best_cnt}) in 04-directions/<id>/checks.json"
                )

    return {
        "choice": pred_choice,
        "matched": bool(actual_choice is not None and pred_choice == actual_choice),
        "basis": basis,
    }


def compute_final_prediction(ws: Workspace, actual_choice: str | None) -> dict[str, Any]:
    """Deterministically predict the final gate choice from 06-checks/round-<n>/review.json and 07-show/comments.json."""
    ws = ws if ws.step else ws.for_step("gate_final")
    round_num = max(1, ws.round) if ws.run_file.is_file() else 1
    review_path = ws.round_folder(round_num) / "review.json"
    comments_path = ws.folder("show") / "comments.json"

    review_verdict = "missing"
    if review_path.is_file():
        try:
            rev_doc = json.loads(ws.read_text(review_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateError(f"cannot read {review_path}: {exc}") from exc
        if isinstance(rev_doc, dict):
            review_verdict = str(rev_doc.get("verdict") or "unknown")

    open_comments = 0
    if comments_path.is_file():
        try:
            cm_doc = json.loads(ws.read_text(comments_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateError(f"cannot read {comments_path}: {exc}") from exc
        if isinstance(cm_doc, dict):
            for c in cm_doc.get("comments") or []:
                if isinstance(c, dict) and c.get("state") == "open":
                    open_comments += 1

    if review_verdict == "done" and open_comments == 0:
        pred_choice = "approve"
    else:
        pred_choice = "changes"

    basis = (
        f"06-checks/round-{round_num}/review.json verdict={review_verdict!r}, "
        f"07-show/comments.json open_comments={open_comments}"
    )
    return {
        "choice": pred_choice,
        "matched": bool(actual_choice is not None and pred_choice == actual_choice),
        "basis": basis,
    }


def compute_prediction(ws: Workspace, gate: str, actual_choice: str | None) -> dict[str, Any]:
    if gate == "direction":
        return compute_direction_prediction(ws, actual_choice)
    if gate == "final":
        return compute_final_prediction(ws, actual_choice)
    raise GateError(f"unknown gate {gate!r}")


def _append_owner_taste(ws: Workspace, record: dict[str, Any]) -> str:
    """Append a structured owner taste line to ws.path / 'taste-owner.md' (and DESIGN_TASTE_FILE if set)."""
    step_name = f"gate_{record.get('gate') or 'direction'}"
    ws_step = ws if ws.step else ws.for_step(step_name)
    product = "unknown"
    if ws.run_file.is_file():
        product = str(ws.run().get("product") or "unknown")

    pred = record.get("prediction") or {}
    pred_choice = pred.get("choice", "?")
    pred_matched = pred.get("matched", False)
    ts = str(record.get("at") or datetime.now(UTC).isoformat(timespec="seconds"))
    gate = str(record.get("gate") or "")
    choice = str(record.get("choice") or "")
    owner_words = str(record.get("owner_words") or "").replace("\n", " ").strip()
    source = str(record.get("source") or "").replace("\n", " ").strip()
    reason = str(record.get("reason") or "").replace("\n", " ").strip()

    line = (
        f"- {ts} | product={product} | gate={gate} | choice={choice} "
        f"| prediction={pred_choice} (matched={pred_matched}) "
        f'| owner_words="{owner_words}" | source={source} | reason={reason}\n'
    )

    ws_taste_path = ws.path / "taste-owner.md"
    existing_taste = ws_step.read_text(ws_taste_path) if ws_taste_path.is_file() else "# Owner Taste Log (design_app_screen_v1)\n\n"
    ws_taste_path.write_text(existing_taste + line, encoding="utf-8")

    env_taste = os.environ.get("DESIGN_TASTE_FILE", "").strip()
    if env_taste:
        env_path = Path(env_taste)
        env_path.parent.mkdir(parents=True, exist_ok=True)
        if not env_path.is_file():
            env_path.write_text("# Owner Taste Log\n\n" + line, encoding="utf-8")
        else:
            with env_path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    return line


def _ensure_targeted_comments_recorded(ws: Workspace, record: dict[str, Any]) -> None:
    """When gate_final is 'changes' with comment numbers, ensure those comments exist in 07-show/comments.json."""
    if record.get("gate") != "final" or record.get("choice") != "changes":
        return
    targeted = record.get("comments") or []
    if not isinstance(targeted, list) or not targeted:
        return

    ws_step = ws if ws.step else ws.for_step("gate_final")
    show_dir = ws_step.folder("show")
    cm_path = show_dir / "comments.json"
    st_path = show_dir / "showtell.json"
    round_num = max(1, ws_step.round) if ws_step.run_file.is_file() else 1

    doc_id = default_doc_id("app", ws_step.path.name or "run")
    if st_path.is_file():
        try:
            st_doc = json.loads(ws_step.read_text(st_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateError(f"cannot read {st_path}: {exc}") from exc
        if isinstance(st_doc, dict) and st_doc.get("doc_id"):
            doc_id = str(st_doc["doc_id"])

    comments_list: list[dict[str, Any]] = []
    if cm_path.is_file():
        try:
            cm_doc = json.loads(ws_step.read_text(cm_path))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateError(f"cannot read {cm_path}: {exc}") from exc
        if isinstance(cm_doc, dict) and isinstance(cm_doc.get("comments"), list):
            comments_list = [c for c in cm_doc["comments"] if isinstance(c, dict)]

    by_number: dict[int, dict[str, Any]] = {}
    for idx, c in enumerate(comments_list, start=1):
        num = c.get("number") if isinstance(c.get("number"), int) else idx
        c["number"] = num
        by_number[num] = c

    owner_words = str(record.get("owner_words") or record.get("reason") or "Requested prototype change").strip()
    changed = False
    for t in targeted:
        if isinstance(t, int) and not isinstance(t, bool) and t >= 1:
            for idx in range(1, t + 1):
                if idx not in by_number:
                    entry = {
                        "id": default_comment_id(doc_id, idx, round_num),
                        "number": idx,
                        "version": round_num,
                        "body": owner_words if idx == t else f"Owner comment {idx}",
                        "element": "prototype",
                        "state": "open",
                    }
                    comments_list.append(entry)
                    by_number[idx] = entry
                    changed = True
            target_entry = by_number[t]
            if target_entry.get("state") != "open":
                target_entry["state"] = "open"
                changed = True

    if changed or not cm_path.is_file():
        show_dir.mkdir(parents=True, exist_ok=True)
        cm_path.write_text(
            json.dumps({"doc_id": doc_id, "comments": comments_list}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def answer(ws: Workspace, gate: str, raw: str) -> dict[str, Any]:
    if gate not in GATES:
        raise GateError(f"unknown gate {gate!r}; gates are {', '.join(GATES)}")
    ws = ws if ws.step else ws.for_step(f"gate_{gate}")
    if not (raw or "").strip():
        raise GateError(f"gate {gate}: no answer given; answer it with choice, decided_by, source and reason")
    try:
        given = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(f"gate {gate}: the answer is not JSON ({exc.msg})") from None
    if not isinstance(given, dict):
        raise GateError(f"gate {gate}: the answer must be a JSON object")
    if gate == "final" and ws.run_file.is_file() and ws.round > 1:
        round_override = ws.folder("show") / f"gate_final_round_{ws.round}.json"
        if round_override.is_file():
            try:
                override_doc = json.loads(ws.read_text(round_override))
            except (OSError, json.JSONDecodeError) as exc:
                raise GateError(f"cannot read {round_override}: {exc}") from exc
            if isinstance(override_doc, dict):
                given = override_doc
    unknown = sorted(set(given) - set(FIELDS))
    if unknown:
        raise GateError(f"gate {gate}: unknown answer fields {', '.join(unknown)}")

    choice = given.get("choice")
    decided_by = given.get("decided_by")
    owner_words = given.get("owner_words", "")
    if decided_by == "design" and owner_words:
        raise GateError(f"gate {gate}: owner_words are for decided_by owner only (his words, verbatim)")

    prediction = compute_prediction(ws, gate, choice if isinstance(choice, str) else None)
    encode_taste = bool(decided_by == "owner")
    taste_status = "saved" if encode_taste else "not-taste"

    record: dict[str, Any] = {
        "gate": gate,
        "choice": choice,
        "decided_by": decided_by,
        "owner_words": owner_words,
        "source": given.get("source"),
        "reason": given.get("reason"),
        "prediction": prediction,
        "taste": taste_status,
        "at": given.get("at") or datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if gate == "final":
        record["comments"] = given.get("comments", [])

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
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    if encode_taste:
        _append_owner_taste(ws, record)

    if gate == "final" and record.get("choice") == "changes":
        _ensure_targeted_comments_recorded(ws, record)

    out: dict[str, Any] = {
        "gate": gate,
        "choice": record["choice"],
        "decided_by": record["decided_by"],
        "verdict": record["choice"],
        "prediction": record["prediction"],
        "taste": record["taste"],
        "file": path.relative_to(ws.path).as_posix(),
    }
    return out


def record_gate(ws: Workspace, gate: str, given: dict[str, Any] | str) -> dict[str, Any]:
    """Convenience wrapper accepting either a dict or JSON string."""
    raw = given if isinstance(given, str) else json.dumps(given, ensure_ascii=False)
    return answer(ws, gate, raw)


def final_next(ws: Workspace) -> dict[str, Any]:
    """After the final gate: the verdict again, for the workflow's loop back to build on changes."""
    ws = ws if ws.step else ws.for_step("gate_final")
    path = ws.folder("show") / "gate_final.json"
    if not path.is_file():
        raise GateError("gate_final.json is missing: the final gate has not been answered")
    record = json.loads(ws.read_text(path))
    return {"verdict": record["choice"], "comments": record.get("comments", [])}
