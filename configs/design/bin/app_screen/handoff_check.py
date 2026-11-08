"""Deterministic 6-rule checker for Stage 8 (08-handoff/) of design_app_screen_v1.

Rules:
1. gate_final_approved: 07-show/gate_final.json exists with gate == "final" and choice == "approve".
2. spec_per_inventory_screen: 08-handoff/spec/<screen-id>.md exists and is non-empty for every screen in 03-ground/inventory.json (no missing or extra screen spec files).
3. spec_sections_complete: every 08-handoff/spec/<screen-id>.md contains routes (#<screen>/<state> for every state), layout & widths (1440, 390, 320), mapped requirements (R*), grounded shows (S* + fields), interactive actions (A*), per-state copy table, and Stage 6/7 review & Show&Tell notes.
4. design_file_valid: 08-handoff/design-file.json is valid, editable is True, and the referenced prototype file exists on disk.
5. followup_valid: 08-handoff/followup.json is valid, F1..Fn IDs are well-formed and unique, and every inventory screen has a frontend implementation item.
6. no_open_must_or_unanswered_comment: 06-checks/round-<ws.round>/review.json has verdict == "done" and 0 open Must findings, and 07-show/comments.json has 0 open comments.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contracts import ContractError
from .workspace import Workspace

RULE_NAMES: tuple[str, ...] = (
    "gate_final_approved",
    "spec_per_inventory_screen",
    "spec_sections_complete",
    "design_file_valid",
    "followup_valid",
    "no_open_must_or_unanswered_comment",
)

FOLLOWUP_ID_RE = re.compile(r"^F[0-9]+$")
VALID_OWNER_ROLES = {"frontend", "backend", "design", "qa"}
REQUIRED_SPEC_HEADERS: tuple[str, ...] = (
    "## Routes",
    "## Layout & Widths",
    "## Requirements",
    "## Grounded Data",
    "## Actions",
    "## State Copy",
    "## Review & Show&Tell Notes",
)


def _read_json(ws: Workspace, path: Path) -> tuple[Any, str | None]:
    if not path.is_file():
        return None, f"{path.name}: file is missing"
    ws_step = ws if ws.step else ws.for_step("handoff")
    try:
        return json.loads(ws_step.read_text(path)), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name}: invalid JSON ({exc})"


def _check_gate_final_approved(ws: Workspace) -> list[str]:
    problems: list[str] = []
    gate_path = ws.folder("show") / "gate_final.json"
    gate_doc, err = _read_json(ws, gate_path)
    if err or not isinstance(gate_doc, dict):
        problems.append(f"07-show/gate_final.json: {err or 'must be a JSON object'}")
        return problems

    if gate_doc.get("gate") != "final":
        problems.append(f"07-show/gate_final.json: gate={gate_doc.get('gate')!r} must be 'final'")
    if gate_doc.get("choice") != "approve":
        problems.append(
            f"07-show/gate_final.json: choice must be 'approve' before Stage 8 handoff (got {gate_doc.get('choice')!r})"
        )
    return problems


def _load_inventory_screens(ws: Workspace) -> tuple[list[dict[str, Any]], list[str]]:
    inv_path = ws.folder("ground") / "inventory.json"
    inv_doc, err = _read_json(ws, inv_path)
    if err or not isinstance(inv_doc, dict):
        return [], [f"03-ground/inventory.json: {err or 'must be a JSON object'}"]
    screens = inv_doc.get("screens")
    if not isinstance(screens, list) or not screens:
        return [], ["03-ground/inventory.json: screens must be a non-empty list"]
    valid_screens = [s for s in screens if isinstance(s, dict) and isinstance(s.get("id"), str) and s.get("id")]
    if not valid_screens:
        return [], ["03-ground/inventory.json: screens contains no valid screen objects"]
    return valid_screens, []


def _check_spec_per_inventory_screen(ws: Workspace) -> list[str]:
    ws_step = ws if ws.step else ws.for_step("handoff")
    screens, probs = _load_inventory_screens(ws_step)
    if probs:
        return probs

    spec_dir = ws_step.folder("handoff") / "spec"
    if not spec_dir.is_dir():
        return ["08-handoff/spec/: directory is missing"]

    expected_ids = {str(s["id"]) for s in screens}
    existing_files = {p.stem: p for p in sorted(spec_dir.glob("*.md"))}

    for sid in sorted(expected_ids):
        p = existing_files.get(sid)
        if p is None or not p.is_file():
            probs.append(f"08-handoff/spec/{sid}.md: missing spec file for inventory screen {sid!r}")
        elif not ws_step.read_text(p).strip():
            probs.append(f"08-handoff/spec/{sid}.md: spec file is empty")

    extra_ids = sorted(set(existing_files.keys()) - expected_ids)
    if extra_ids:
        probs.append(
            f"08-handoff/spec/: unexpected spec file(s) not in 03-ground/inventory.json: {', '.join(f'{x}.md' for x in extra_ids)}"
        )

    return probs


def _check_spec_sections_complete(ws: Workspace) -> list[str]:
    ws_step = ws if ws.step else ws.for_step("handoff")
    screens, probs = _load_inventory_screens(ws_step)
    if probs:
        return probs

    spec_dir = ws_step.folder("handoff") / "spec"
    for s in screens:
        sid = str(s["id"])
        spec_path = spec_dir / f"{sid}.md"
        if not spec_path.is_file():
            probs.append(f"08-handoff/spec/{sid}.md: missing spec file")
            continue

        text = ws_step.read_text(spec_path)
        for header in REQUIRED_SPEC_HEADERS:
            if header not in text:
                probs.append(f"08-handoff/spec/{sid}.md: missing required section {header!r}")

        for w in ("1440", "390", "320"):
            if w not in text:
                probs.append(f"08-handoff/spec/{sid}.md: missing required viewport width {w}px")

        states = [str(st) for st in (s.get("states") or []) if st]
        for st in states:
            route = f"#{sid}/{st}"
            if route not in text:
                probs.append(f"08-handoff/spec/{sid}.md: missing route {route!r}")

        for idx, show in enumerate(s.get("shows") or [], start=1):
            if isinstance(show, dict):
                sh_id = str(show.get("id") or show.get("ref") or f"S{idx}")
                sh_what = str(show.get("what") or "")
                if sh_id not in text and (not sh_what or sh_what not in text):
                    probs.append(f"08-handoff/spec/{sid}.md: missing grounded show {sh_id!r}")

    return probs


def _check_design_file_valid(ws: Workspace) -> list[str]:
    ws_step = ws if ws.step else ws.for_step("handoff")
    problems: list[str] = []
    df_path = ws_step.folder("handoff") / "design-file.json"
    df_doc, err = _read_json(ws_step, df_path)
    if err or not isinstance(df_doc, dict):
        return [f"08-handoff/design-file.json: {err or 'must be a JSON object'}"]

    kind = df_doc.get("kind")
    if kind not in ("penpot", "html-prototype"):
        problems.append(
            f"08-handoff/design-file.json: kind={kind!r} must be 'penpot' or 'html-prototype'"
        )

    if df_doc.get("editable") is not True:
        problems.append(
            f"08-handoff/design-file.json: editable must be True (got {df_doc.get('editable')!r})"
        )

    location = str(df_doc.get("location") or "").strip()
    if not location:
        problems.append("08-handoff/design-file.json: location must be non-empty")
    elif kind == "html-prototype":
        target = ws_step.path / location
        if not target.is_file() or not ws_step.read_text(target).strip():
            problems.append(
                f"08-handoff/design-file.json: html-prototype location {location!r} does not exist or is empty"
            )

    note = str(df_doc.get("note") or "").strip()
    if not note:
        problems.append("08-handoff/design-file.json: note must be non-empty")

    return problems


def _check_followup_valid(ws: Workspace) -> list[str]:
    ws_step = ws if ws.step else ws.for_step("handoff")
    problems: list[str] = []
    fu_path = ws_step.folder("handoff") / "followup.json"
    fu_doc, err = _read_json(ws_step, fu_path)
    if err or not isinstance(fu_doc, dict):
        return [f"08-handoff/followup.json: {err or 'must be a JSON object'}"]

    items = fu_doc.get("items")
    if not isinstance(items, list) or not items:
        return ["08-handoff/followup.json: items must be a non-empty list"]

    seen_ids: set[str] = set()
    frontend_text_blobs: list[str] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            problems.append(f"08-handoff/followup.json: items[{idx - 1}] must be an object")
            continue
        fid = str(item.get("id") or "")
        if not FOLLOWUP_ID_RE.match(fid):
            problems.append(
                f"08-handoff/followup.json: items[{idx - 1}].id={fid!r} does not match ^F[0-9]+$"
            )
        elif fid in seen_ids:
            problems.append(f"08-handoff/followup.json: duplicate follow-up id {fid!r}")
        seen_ids.add(fid)

        owner_role = item.get("owner_role")
        if owner_role not in VALID_OWNER_ROLES:
            problems.append(
                f"08-handoff/followup.json: items[{idx - 1}] ({fid}) owner_role={owner_role!r} must be in {sorted(VALID_OWNER_ROLES)}"
            )
        what = str(item.get("what") or "").strip()
        source = str(item.get("source") or "").strip()
        if not what:
            problems.append(f"08-handoff/followup.json: items[{idx - 1}] ({fid}) what must be non-empty")
        if not source:
            problems.append(f"08-handoff/followup.json: items[{idx - 1}] ({fid}) source must be non-empty")
        if owner_role == "frontend":
            frontend_text_blobs.append(f"{item.get('screen') or ''} {what} {source} {item.get('detail') or ''}")

    screens, inv_probs = _load_inventory_screens(ws)
    if not inv_probs:
        combined_frontend = "\n".join(frontend_text_blobs)
        for s in screens:
            sid = str(s["id"])
            if sid not in combined_frontend and f"spec/{sid}.md" not in combined_frontend:
                problems.append(
                    f"08-handoff/followup.json: missing frontend implementation item covering screen {sid!r}"
                )

    return problems


def _check_no_open_must_or_unanswered_comment(ws: Workspace, round_num: int) -> list[str]:
    ws_step = ws if ws.step else ws.for_step("handoff")
    problems: list[str] = []
    review_path = ws_step.round_folder(round_num) / "review.json"
    review_doc, rev_err = _read_json(ws_step, review_path)
    if rev_err or not isinstance(review_doc, dict):
        problems.append(f"06-checks/round-{round_num}/review.json: {rev_err or 'must be a JSON object'}")
    else:
        if review_doc.get("verdict") != "done":
            problems.append(
                f"06-checks/round-{round_num}/review.json: verdict must be 'done' (got {review_doc.get('verdict')!r})"
            )
        open_must = [
            f.get("id", "?")
            for f in (review_doc.get("findings") or [])
            if isinstance(f, dict)
            and f.get("priority") == "must"
            and f.get("status") not in ("fixed", "resolved")
        ]
        if open_must:
            problems.append(
                f"06-checks/round-{round_num}/review.json: has {len(open_must)} open Must finding(s): {', '.join(str(x) for x in open_must)}"
            )

    comments_path = ws_step.folder("show") / "comments.json"
    comments_doc, cm_err = _read_json(ws_step, comments_path)
    if cm_err or not isinstance(comments_doc, dict):
        problems.append(f"07-show/comments.json: {cm_err or 'must be a JSON object'}")
    else:
        open_comments = [
            c.get("id") or f"#{c.get('number', '?')}"
            for c in (comments_doc.get("comments") or [])
            if isinstance(c, dict) and c.get("state") == "open"
        ]
        if open_comments:
            problems.append(
                f"07-show/comments.json: has {len(open_comments)} unanswered open comment(s): {', '.join(str(x) for x in open_comments)}"
            )

    return problems


def check_handoff(ws: Workspace, *, write_report: bool = True) -> dict[str, Any]:
    """Run all 6 deterministic Stage 8 handoff rules and optionally write 08-handoff/check.json."""
    round_num = max(1, ws.round) if ws.run_file.is_file() else 1

    rule_checks = {
        "gate_final_approved": _check_gate_final_approved(ws),
        "spec_per_inventory_screen": _check_spec_per_inventory_screen(ws),
        "spec_sections_complete": _check_spec_sections_complete(ws),
        "design_file_valid": _check_design_file_valid(ws),
        "followup_valid": _check_followup_valid(ws),
        "no_open_must_or_unanswered_comment": _check_no_open_must_or_unanswered_comment(ws, round_num),
    }

    rules_report: dict[str, dict[str, Any]] = {}
    all_problems: list[str] = []
    for rule_name in RULE_NAMES:
        probs = rule_checks[rule_name]
        rules_report[rule_name] = {
            "passed": len(probs) == 0,
            "problems": probs,
        }
        for p in probs:
            all_problems.append(f"[{rule_name}] {p}")

    report = {
        "stage": "handoff",
        "round": round_num,
        "passed": len(all_problems) == 0,
        "rules": rules_report,
        "problems": all_problems,
    }

    if write_report:
        handoff_dir = ws.folder("handoff")
        handoff_dir.mkdir(parents=True, exist_ok=True)
        (handoff_dir / "check.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return report


def assert_handoff_clean(ws: Workspace) -> dict[str, Any]:
    """Run check_handoff(ws) and raise ContractError if any rule failed."""
    report = check_handoff(ws, write_report=True)
    if not report["passed"]:
        raise ContractError(f"handoff: {len(report['problems'])} problem(s): " + "; ".join(report["problems"]))
    return report
