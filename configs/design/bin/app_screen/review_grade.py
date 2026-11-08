"""Stage 6b trial preparation and deterministic grader (review_grade.py).

Supports the 3 Stage 6b known trial cases + the 2-round loop proof on temper-dev:
- clean-parcelly: Stage 5b clean build + Stage 6a checks (0 blockers, 0 shoulds) -> verdict "done", must == 0.
- measured-inkflow: Stage 6a c-inkflow-onboarding (44 blocker rows, 76 should rows -> 20 M* items) ->
  verdict "revise", 100% M* items covered, 0 invented measurements.
- taste-planted: Stage 5b parcelly build that passes all 24 Stage 6a measured checks (0 blockers, 0 shoulds)
  but has 3 planted UX/language flaws in 05-build/ -> verdict "revise", 3/3 planted flaws caught, must >= 1.
- loop-round-2: Round 2 after review(revise) -> build -> checks -> review -> verdict "done", must == 0.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import build_scaffold, checks, checks_host, contracts, review_check
from .workspace import Workspace

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]

PLANTED_TASTE_FAULTS: list[dict[str, Any]] = [
    {
        "id": "T1",
        "name": "raw_error_secret_leak",
        "screen": "home",
        "state": "error",
        "what": "Raw SQL error trace and live auth_token secret leaked in error state summary with no human recovery explanation",
        "keywords": ["fatal", "auth_token", "sk_live", "select * from", "carrier_manifests", "hub_id"],
    },
    {
        "id": "T2",
        "name": "robotic_placeholder_label",
        "screen": "home",
        "state": "done",
        "what": "Robotic snake_case placeholder button label 'Submit action_btn_1' on action control",
        "keywords": ["action_btn_1", "submit action_btn_1"],
    },
    {
        "id": "T3",
        "name": "reassurance_fluff",
        "screen": "home",
        "state": "done",
        "what": "Reassurance fluff 'Everything is fine, relax and trust the system...' replacing concrete parcel status/figures",
        "keywords": ["relax and trust", "everything is fine", "behind the scenes"],
    },
]

CASES: dict[str, dict[str, Any]] = {
    "clean-parcelly": {
        "case": "clean-parcelly",
        "product": "parcelly",
        "verdict": "done",
        "max_must": 0,
        "min_must": 0,
        "planted": [],
    },
    "measured-inkflow": {
        "case": "measured-inkflow",
        "product": "inkflow",
        "verdict": "revise",
        "min_must": 1,
        "planted": [],
    },
    "taste-planted": {
        "case": "taste-planted",
        "product": "parcelly",
        "verdict": "revise",
        "min_must": 1,
        "planted": PLANTED_TASTE_FAULTS,
    },
    "loop-round-2": {
        "case": "loop-round-2",
        "product": "parcelly",
        "verdict": "done",
        "max_must": 0,
        "min_must": 0,
        "planted": [],
    },
}


def _clean_parcelly_draft() -> dict[str, Any]:
    return {
        "screens": [
            {
                "id": "home",
                "title": "Evening Dispatch Ledger",
                "lead": "Track active courier handoffs, hub holds, and route exceptions before cutoff.",
                "layout": "ledger",
                "states": {
                    "done": {
                        "badge": "On schedule",
                        "headline": "Evening dispatch ledger is balanced",
                        "summary": "All scheduled courier manifests and hub handoffs are reconciled for tonight.",
                    },
                    "empty": {
                        "badge": "No dispatches",
                        "headline": "No parcels queued for tonight",
                        "summary": "Import a carrier manifest or assign a courier route to begin dispatch tracking.",
                    },
                    "loading": {
                        "badge": "Syncing",
                        "headline": "Refreshing live carrier manifests",
                        "summary": "Pulling latest scan events and bay assignments from regional hubs.",
                    },
                    "error": {
                        "badge": "Sync interrupted",
                        "headline": "Carrier manifest feed could not be reached",
                        "summary": "Check your hub network connection and select Retry manifest sync to reload.",
                    },
                    "partial": {
                        "badge": "Partial feed",
                        "headline": "Regional hub telemetry is still arriving",
                        "summary": "Local bay scans are shown below while northern depot manifests finish syncing.",
                    },
                },
                "shows": [
                    {
                        "ref": "S1",
                        "heading": "Active Parcel Queue",
                        "copy": "Live parcel count and priority bay breakdown across active courier lanes.",
                        "fields": ["summary.active_parcels", "summary.on_time_rate"],
                    },
                    {
                        "ref": "S2",
                        "heading": "Courier Route Exceptions",
                        "copy": "Delayed handoffs and customs holds requiring dispatcher review before departure.",
                        "fields": ["summary.exceptions_open", "summary.next_cutoff"],
                    },
                ],
                "actions": [
                    {
                        "id": "action_assign",
                        "label": "Assign courier route",
                        "kind": "primary",
                        "states": ["done", "empty", "partial"],
                        "feedback": "Route assignment saved and sent to bay dispatch.",
                    },
                    {
                        "id": "action_retry",
                        "label": "Retry manifest sync",
                        "kind": "secondary",
                        "states": ["error", "partial"],
                        "feedback": "Reconnecting to regional hub manifest service.",
                    },
                ],
            }
        ],
        "notes": ["Clean ledger layout with progressive disclosure and explicit error recovery."],
    }


def _taste_planted_draft() -> dict[str, Any]:
    draft = _clean_parcelly_draft()
    screen = draft["screens"][0]
    # T1: Raw SQL/secret leak in error state summary
    screen["states"]["error"]["summary"] = (
        "FATAL auth_token=sk_live_9981_parcelly: SELECT * FROM carrier_manifests WHERE hub_id=NULL failed"
    )
    # T2: Robotic placeholder button label
    screen["actions"][0]["label"] = "Submit action_btn_1"
    # T3: Reassurance fluff replacing requested parcel status/figures on home
    screen["states"]["done"]["summary"] = (
        "Everything is fine, relax and trust the system while we handle things behind the scenes."
    )
    screen["shows"][0]["copy"] = (
        "Everything is fine, relax and trust the system while we handle things behind the scenes."
    )
    return draft


def _setup_parcelly_inputs(ws: Workspace) -> None:
    ws.start("parcelly")
    req_dir = ws.folder("intake")
    ground_dir = ws.folder("ground")
    design_dir = ground_dir / "design-files"
    dir_dir = ws.folder("directions")
    req_dir.mkdir(parents=True, exist_ok=True)
    design_dir.mkdir(parents=True, exist_ok=True)
    dir_dir.mkdir(parents=True, exist_ok=True)

    (req_dir / "requirements.json").write_text(
        json.dumps(
            {
                "product": "parcelly",
                "items": [
                    {
                        "id": "R1",
                        "owner_words": "Show active parcel queue and on-time rate clearly at a glance.",
                        "source": "owner request",
                        "kind": "feature",
                        "means": "Display active parcel count, on-time rate, and open route exceptions on home.",
                        "maps_to": ["home"],
                    },
                    {
                        "id": "R2",
                        "owner_words": "Let dispatchers assign a courier route or retry manifest sync.",
                        "source": "owner request",
                        "kind": "feature",
                        "means": "Provide clear human actions to assign a courier route and recover from sync errors.",
                        "maps_to": ["home"],
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (ground_dir / "fixture.json").write_text(
        json.dumps(
            {
                "product": "parcelly",
                "summary": {
                    "active_parcels": 42,
                    "on_time_rate": "98.4%",
                    "exceptions_open": 2,
                    "next_cutoff": "19:30 local",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (ground_dir / "inventory.json").write_text(
        json.dumps(
            {
                "design_files": "defined",
                "source": {"product": "parcelly"},
                "screens": [
                    {
                        "id": "home",
                        "name": "Evening Dispatch Ledger",
                        "states": ["done", "empty", "loading", "error", "partial"],
                        "widths": [390, 1440],
                        "shows": [
                            {"what": "Active parcel queue and on-time delivery rate", "sources": ["req:R1"]},
                            {"what": "Open courier route exceptions and next hub cutoff", "sources": ["req:R1"]},
                        ],
                        "actions": [
                            {
                                "id": "action_assign",
                                "what": "Assign courier route",
                                "states": ["done", "empty", "partial"],
                                "sources": ["req:R2"],
                            },
                            {
                                "id": "action_retry",
                                "what": "Retry manifest sync",
                                "states": ["error", "partial"],
                                "sources": ["req:R2"],
                            },
                        ],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (design_dir / "tokens.json").write_text(
        json.dumps(
            {
                "color": {
                    "bg": "#FAF8F5",
                    "surface": "#FFFFFF",
                    "text": "#18181B",
                    "muted": "#3F3F46",
                    "primary": "#1E3A8A",
                    "on-primary": "#FFFFFF",
                    "border": "#52525B",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (design_dir / "DESIGN.md").write_text(
        "# Parcelly Design Direction\nCalm high-contrast dispatch ledger with progressive disclosure.\n",
        encoding="utf-8",
    )

    (dir_dir / "directions.json").write_text(
        json.dumps(
            {
                "directions": [
                    {"id": "a", "name": "Dispatch Ledger", "idea": "High-contrast ledger", "page": "a/index.html"},
                    {"id": "b", "name": "Hub Board", "idea": "Dense operational board", "page": "b/index.html"},
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (dir_dir / "gate_direction.json").write_text(
        json.dumps(
            {
                "gate": "direction",
                "choice": "a",
                "decided_by": "design",
                "owner_words": "",
                "source": "trial",
                "reason": "Clean ledger hierarchy",
                "prediction": None,
                "taste": "not-taste",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def prepare_trial_workspace(case_name: str, workspace: Path | str, run_browser_checks: bool = True) -> dict[str, Any]:
    """Prepare a workspace for one of the 3 Stage 6b trial cases (clean-parcelly, measured-inkflow, taste-planted)."""
    if case_name not in ("clean-parcelly", "measured-inkflow", "taste-planted"):
        raise ValueError(f"unknown review trial case {case_name!r}; expected clean-parcelly, measured-inkflow, or taste-planted")

    ws_path = Path(workspace)
    if ws_path.exists():
        shutil.rmtree(ws_path)
    ws_path.mkdir(parents=True, exist_ok=True)
    ws = Workspace(ws_path)

    if case_name == "measured-inkflow":
        case_dir = REPO_ROOT / "tests/design_app_screen_case/checks_cases/c-inkflow-onboarding"
        checks_host.prepare_case(case_dir, ws_path)
        req_dir = ws.folder("intake")
        req_dir.mkdir(parents=True, exist_ok=True)
        (req_dir / "requirements.json").write_text(
            json.dumps(
                {
                    "product": "inkflow",
                    "items": [
                        {
                            "id": "R1",
                            "owner_words": "Walk new creators through studio setup, queue, and payout ledger with WCAG AA contrast and >= 16px body text.",
                            "source": "owner request",
                            "kind": "goal",
                            "means": "All onboarding and dashboard screens meet WCAG 2.2 AA contrast, 16px type floor, and first-view fit.",
                            "maps_to": ["welcome", "profile", "connect", "dashboard", "queue", "settings"],
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if run_browser_checks:
            checks.run(ws)
        return {"case": case_name, "workspace": str(ws_path), "product": "inkflow", "round": ws.round}

    _setup_parcelly_inputs(ws)
    build_scaffold.write_scaffold(ws)
    draft = _clean_parcelly_draft() if case_name == "clean-parcelly" else _taste_planted_draft()
    (ws.folder("build") / "draft.json").write_text(
        json.dumps(draft, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    build_scaffold.render_draft(ws, draft)
    if run_browser_checks:
        checks.run(ws)
    return {"case": case_name, "workspace": str(ws_path), "product": "parcelly-clean", "round": ws.round}


def _matches_planted_taste(finding: dict[str, Any], fault: dict[str, Any]) -> bool:
    if finding.get("priority") not in ("must", "should"):
        return False
    hay = " ".join(
        str(finding.get(k) or "")
        for k in ("element", "location", "evidence", "suggestion", "reason")
    ).lower()
    return any(kw.lower() in hay for kw in (fault.get("keywords") or []))


def grade(case_spec: str | Path, workspace: Path | str, round_num: int | None = None) -> dict[str, Any]:
    """Grade a Stage 6b review run in workspace against case_spec."""
    ws = Workspace(workspace)
    r = round_num if round_num is not None else (ws.round or 1)
    round_dir = ws.round_folder(r)

    if isinstance(case_spec, str) and case_spec in CASES:
        expected = CASES[case_spec]
    else:
        spec_path = Path(case_spec)
        if spec_path.is_dir():
            spec_path = spec_path / "case.json"
        if spec_path.is_file():
            expected = json.loads(spec_path.read_text(encoding="utf-8"))
        elif isinstance(case_spec, str) and Path(case_spec).name in CASES:
            expected = CASES[Path(case_spec).name]
        else:
            raise ValueError(f"unknown review case {case_spec!r}")

    misses: list[str] = []
    notes: list[str] = []

    review_path = round_dir / "review.json"
    if not review_path.is_file():
        return {
            "case": expected["case"],
            "round": r,
            "pass": False,
            "misses": [f"{review_path} is missing"],
        }

    try:
        contracts.validate("review", ws)
    except contracts.ContractError as exc:
        misses.append(f"contract validation failed: {exc}")

    check_final_path = round_dir / "check-final.json"
    if check_final_path.is_file():
        cf = json.loads(check_final_path.read_text(encoding="utf-8"))
        if cf.get("verdict") != "ok" or cf.get("problems"):
            misses.append(f"check-final.json verdict is {cf.get('verdict')!r} with {len(cf.get('problems') or [])} problem(s)")
    else:
        misses.append(f"{check_final_path} is missing")

    review_doc = json.loads(review_path.read_text(encoding="utf-8"))
    findings = [f for f in (review_doc.get("findings") or []) if isinstance(f, dict)]
    must_findings = [f for f in findings if f.get("priority") == "must"]

    want_verdict = expected.get("verdict")
    if want_verdict and review_doc.get("verdict") != want_verdict:
        misses.append(f"verdict is {review_doc.get('verdict')!r}, expected {want_verdict!r}")

    min_must = expected.get("min_must")
    if min_must is not None and len(must_findings) < int(min_must):
        misses.append(f"must count is {len(must_findings)}, expected >= {min_must}")

    max_must = expected.get("max_must")
    if max_must is not None and len(must_findings) > int(max_must):
        misses.append(
            f"must count is {len(must_findings)}, expected <= {max_must} "
            f"(false Musts: {[f.get('evidence', '')[:80] for f in must_findings]})"
        )

    # Check M1..Mk coverage
    measured_items = review_check.load_measured_items(ws)
    draft_path = round_dir / "draft.json"
    draft_measured_ids: set[str] = set()
    if draft_path.is_file():
        ddoc = json.loads(draft_path.read_text(encoding="utf-8"))
        for m in ddoc.get("measured") or []:
            if isinstance(m, dict) and "id" in m:
                draft_measured_ids.add(str(m["id"]))
    expected_m_ids = {str(it["id"]) for it in measured_items}
    missing_m = sorted(expected_m_ids - draft_measured_ids)
    if missing_m:
        misses.append(f"missing measured items in draft.json: {', '.join(missing_m)}")

    # Check planted UX/taste/language faults
    planted = expected.get("planted") or []
    caught = 0
    for fault in planted:
        hits = [f for f in findings if _matches_planted_taste(f, fault)]
        if hits:
            caught += 1
            notes.append(f"{fault['id']} ({fault['name']}) caught by {hits[0]['id']} ({hits[0]['priority']}): {hits[0]['evidence'][:100]}")
        else:
            misses.append(f"planted fault {fault['id']} ({fault['name']}) not caught: {fault['what']}")

    recall = round(caught / len(planted), 3) if planted else 1.0

    return {
        "case": expected["case"],
        "round": r,
        "pass": len(misses) == 0,
        "verdict": review_doc.get("verdict"),
        "measures": {
            "findings": len(findings),
            "must": len(must_findings),
            "measured_items": len(measured_items),
            "measured_covered": len(expected_m_ids & draft_measured_ids),
            "planted": len(planted),
            "caught": caught,
            "recall": recall,
        },
        "misses": misses,
        "notes": notes,
    }
