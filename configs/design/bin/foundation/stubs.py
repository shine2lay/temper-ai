"""Skeleton stub implementations for Stages 2-6 of design_foundation_v1.

Task 1 establishes the workflow skeleton, closed schemas, brief contract, workspace layout, and per-step
STEP_INPUTS contracts that Tasks 2-5 code against:
  - No colour maths, ramp generation, contrast calculation, or colour-blind simulation (Task 2).
  - No model prompt or LLM agent (Task 4).
  - No product-repo landing mechanism (Task 5; Stage 6 writes 06-handoff/ contract artifacts only).
Every stub reads strictly through Workspace.for_step(...) and validates every written artifact against
foundation.contracts so contract regressions fail immediately.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
from typing import Any

import design_files

from . import build, contracts, proof
from .contracts import EXT, TOKEN_PARTS, ContractError
from .workspace import Workspace

# ---------------------------------------------------------------- Stage 3: proof (with sample-screen fallback)

def _render_sample_screen_html(brief_doc: dict[str, Any], directions_doc: dict[str, Any]) -> str:
    product = html.escape(brief_doc["product"])
    sec_by_id = {s["id"]: s["body"] for s in brief_doc["sections"]}
    what_it_is = html.escape(sec_by_id.get("what_it_is") or "")
    who_for = html.escape(sec_by_id.get("who_for") or "")
    constraints_html = "".join(
        f"<li>{html.escape(item['text'])} <small>({html.escape(item['source_ref'])})</small></li>"
        for item in brief_doc["constraints"]
    ) or "<li>No fixed constraints listed.</li>"
    cards_html = "".join(
        f"<article data-direction='{html.escape(d['id'])}'>"
        f"<h2>{html.escape(d['name'])}</h2><p>{html.escape(d['summary'])}</p></article>"
        for d in directions_doc["directions"]
    )
    return (
        "<!doctype html>\n"
        "<html lang='en'>\n"
        "<head><meta charset='utf-8'><title>"
        f"{product} — Representative Foundation Sample Screen</title></head>\n"
        f"<body data-surface='sample_screen' data-product='{product}'>\n"
        f"<main><h1>{product}</h1><p>{what_it_is}</p><p>{who_for}</p>"
        f"<section><h2>Brief Constraints</h2><ul>{constraints_html}</ul></section>"
        f"<section><h2>Candidate Directions</h2>{cards_html}</section></main>\n"
        "</body>\n</html>\n"
    )


def _resolve_surface_record(
    brief_doc: dict[str, Any],
    *,
    base_url: str | None,
    commit: str | None,
    ref: str | None,
    allow_red_commit: bool,
    sample_rel: str,
) -> dict[str, Any]:
    clean_url = (base_url or "").strip()
    requested = brief_doc.get("render_surface", "app")
    if requested == "app" and clean_url:
        return {
            "kind": "app",
            "fallback": False,
            "reason": f"live app render surface at {clean_url}",
            "base_url": clean_url,
            "commit": (commit or "").strip() or None,
            "ref": (ref or "").strip() or None,
            "allow_red_commit": bool(allow_red_commit),
            "sample_screen": None,
        }
    return {
        "kind": "sample_screen",
        "fallback": True,
        "reason": "no live app render surface; using representative sample screen built from 01-brief/brief.json",
        "base_url": None,
        "commit": None,
        "ref": (ref or "").strip() or None,
        "allow_red_commit": bool(allow_red_commit),
        "sample_screen": sample_rel,
    }


def proof_run(
    ws: Workspace,
    *,
    base_url: str | None = None,
    commit: str | None = None,
    ref: str | None = None,
    allow_red_commit: bool = False,
) -> dict[str, Any]:
    return proof.run(
        ws,
        base_url=base_url,
        commit=commit,
        ref=ref,
        allow_red_commit=allow_red_commit,
    )


# ---------------------------------------------------------------- Stage 5: checks (with sample-screen fallback)

def checks_run(
    ws: Workspace,
    *,
    base_url: str | None = None,
    commit: str | None = None,
    ref: str | None = None,
    allow_red_commit: bool = False,
) -> dict[str, Any]:
    step_ws = ws.for_step("checks")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    proof_doc = step_ws.read_json("03-proof/proof.json")
    build_doc = step_ws.read_json("04-build/build.json")
    tok = step_ws.read_json("04-build/tokens.json")
    md = step_ws.read_text("04-build/DESIGN.md")

    contracts.validate_tokens(tok, label="04-build/tokens.json", step="checks")
    contracts.validate_design_md(md, label="04-build/DESIGN.md", step="checks")

    surface = _resolve_surface_record(
        brief_doc,
        base_url=base_url or proof_doc["surface"].get("base_url"),
        commit=commit or proof_doc["surface"].get("commit"),
        ref=ref or proof_doc["surface"].get("ref"),
        allow_red_commit=allow_red_commit or bool(proof_doc["surface"].get("allow_red_commit")),
        sample_rel="03-proof/sample-screen.html",
    )
    if surface["kind"] == "sample_screen":
        sample_body = step_ws.read_text("03-proof/sample-screen.html")
        if not sample_body.strip():
            raise ContractError("checks: 03-proof/sample-screen.html is empty")

    rows = [
        {
            "id": "schema.tokens_closed",
            "result": "pass",
            "severity": "blocker",
            "evidence": f"all {len(TOKEN_PARTS)} DTCG token parts valid under closed TOKENS_SCHEMA",
            "location": "04-build/tokens.json",
        },
        {
            "id": "schema.design_md_sections",
            "result": "pass",
            "severity": "blocker",
            "evidence": "DESIGN.md header, 6 top-level sections, and 4 Direction subsections valid",
            "location": "04-build/DESIGN.md",
        },
        {
            "id": "surface.render_target",
            "result": "pass",
            "severity": "info",
            "evidence": f"validated against {surface['kind']} surface (fallback={surface['fallback']})",
            "location": surface["base_url"] or str(surface["sample_screen"]),
        },
    ]

    round_num = int(build_doc["round"])
    round_dir = step_ws.folder("checks") / f"round-{round_num}"
    round_dir.mkdir(parents=True, exist_ok=True)
    checks_doc = {
        "round": round_num,
        "verdict": "done",
        "surface": surface,
        "summary": {
            "total": len(rows),
            "passed": len(rows),
            "failed": 0,
            "blockers": 0,
        },
        "checks": rows,
    }
    contracts.validate("checks", checks_doc, step="checks")
    (round_dir / "checks.json").write_text(json.dumps(checks_doc, indent=2, ensure_ascii=False) + "\n")
    step_ws.mark("checks", "done", round=round_num, verdict="done", surface_kind=surface["kind"])
    return {
        "ok": True,
        "step": "checks",
        "round": round_num,
        "verdict": "done",
        "surface_kind": surface["kind"],
        "fallback": surface["fallback"],
    }


# ---------------------------------------------------------------- Stage 6: handoff (contract only; landing is Task 5)

def handoff_run(ws: Workspace) -> dict[str, Any]:
    step_ws = ws.for_step("handoff")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    build_doc = step_ws.read_json("04-build/build.json")
    gate_final = step_ws.read_json("05-checks/gate_final.json")

    if gate_final.get("choice") != "approve":
        raise ContractError(
            f"handoff: 05-checks/gate_final.json choice must be 'approve', got {gate_final.get('choice')!r}"
        )

    round_num = int(build_doc["round"])
    checks_doc = step_ws.read_json(f"05-checks/round-{round_num}/checks.json")
    if checks_doc.get("verdict") != "done":
        raise ContractError(
            f"handoff: 05-checks/round-{round_num}/checks.json verdict must be 'done', got {checks_doc.get('verdict')!r}"
        )

    raw_tok = step_ws.read_json("04-build/tokens.json")
    raw_md = step_ws.read_text("04-build/DESIGN.md")
    contracts.validate_design_md(raw_md, label="04-build/DESIGN.md", step="handoff")

    approved_by = str(gate_final["decided_by"])
    approved_date = str(gate_final["at"])[:10]
    if not design_files._valid_date(approved_date):
        approved_date = design_files.today()

    approved_tok = copy.deepcopy(raw_tok)
    for part in TOKEN_PARTS:
        approved_tok[part]["$extensions"][EXT] = {
            "part": part,
            "status": "approved",
            "approved_by": approved_by,
            "date": approved_date,
        }
    contracts.validate_tokens(approved_tok, label="06-handoff/tokens.json", step="handoff")

    approved_md = build.promote_design_md_to_approved(
        raw_md,
        approved_by=approved_by,
        date=approved_date,
        owner_words=gate_final.get("owner_words"),
        source=gate_final.get("source"),
    )
    contracts.validate_design_md(approved_md, label="06-handoff/DESIGN.md", step="handoff")

    out_dir = step_ws.folder("handoff")
    out_dir.mkdir(parents=True, exist_ok=True)
    tok_text = json.dumps(approved_tok, indent=2, ensure_ascii=False) + "\n"
    (out_dir / "tokens.json").write_text(tok_text, encoding="utf-8")
    (out_dir / "DESIGN.md").write_text(approved_md, encoding="utf-8")

    handoff_doc = {
        "product": brief_doc["product"],
        "round": round_num,
        "direction": build_doc["direction"],
        "approved_by": approved_by,
        "approved_at": gate_final["at"],
        "landing_status": "ready_to_land",
        "files": [
            {
                "source": "06-handoff/DESIGN.md",
                "target": ".temper/design/DESIGN.md",
                "sha256": hashlib.sha256(approved_md.encode("utf-8")).hexdigest(),
            },
            {
                "source": "06-handoff/tokens.json",
                "target": ".temper/design/tokens.json",
                "sha256": hashlib.sha256(tok_text.encode("utf-8")).hexdigest(),
            },
        ],
    }
    contracts.validate("handoff", handoff_doc, step="handoff")
    (out_dir / "handoff.json").write_text(json.dumps(handoff_doc, indent=2, ensure_ascii=False) + "\n")
    step_ws.mark("handoff", "done", round=round_num, landing_status="ready_to_land")
    return {
        "ok": True,
        "step": "handoff",
        "product": brief_doc["product"],
        "round": round_num,
        "direction": build_doc["direction"],
        "landing_status": "ready_to_land",
        "targets": [".temper/design/DESIGN.md", ".temper/design/tokens.json"],
    }
