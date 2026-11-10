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

from . import contracts
from .contracts import EXT, FORMAT, TOKEN_PARTS, ContractError
from .workspace import Workspace


def stub_tokens(
    product: str,
    *,
    status: str = "draft",
    approved_by: str | None = None,
    date: str | None = None,
    accent_hex: str = "#2E7D4F",
) -> dict[str, Any]:
    """Build a static, math-free DTCG tokens.json document satisfying closed TOKENS_SCHEMA."""
    def part_ext(part: str) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "part": part,
            "status": status,
            "date": date or design_files.today(),
        }
        if status == "approved":
            meta["approved_by"] = approved_by or "design"
        return {EXT: meta}

    return {
        "$description": f"{product} design foundation tokens (skeleton stub).",
        "$extensions": {
            EXT: {
                "product": product,
                "format": FORMAT,
            }
        },
        "colour": {
            "$type": "color",
            "$extensions": part_ext("colour"),
            "ink": design_files.color_token("#1A1A17", "primary foreground ink"),
            "paper": design_files.color_token("#F7F5EF", "primary light surface"),
            "surface": design_files.color_token("#E9E5DA", "elevated light surface"),
            "muted": design_files.color_token("#5E5B53", "secondary foreground ink"),
            "accent": design_files.color_token(accent_hex, "primary brand accent"),
            "accent_on": design_files.color_token("#FFFFFF", "foreground on accent"),
        },
        "type": {
            "$extensions": part_ext("type"),
            "family": {
                "$type": "fontFamily",
                "display": {"$value": ["Fraunces", "Georgia", "serif"]},
                "sans": {"$value": ["Plus Jakarta Sans", "system-ui", "sans-serif"]},
                "mono": {"$value": ["JetBrains Mono", "monospace"]},
            },
            "scale": {
                "$type": "dimension",
                "sm": {"$value": {"value": 14, "unit": "px"}},
                "base": {"$value": {"value": 16, "unit": "px"}},
                "lg": {"$value": {"value": 20, "unit": "px"}},
                "xl": {"$value": {"value": 28, "unit": "px"}},
            },
            "weight": {
                "$type": "fontWeight",
                "regular": {"$value": 400},
                "medium": {"$value": 500},
                "semibold": {"$value": 600},
            },
            "leading": {
                "$type": "number",
                "tight": {"$value": 1.2},
                "body": {"$value": 1.45},
            },
        },
        "spacing": {
            "$type": "dimension",
            "$extensions": part_ext("spacing"),
            "0": {"$value": {"value": 0, "unit": "px"}},
            "1": {"$value": {"value": 4, "unit": "px"}},
            "2": {"$value": {"value": 8, "unit": "px"}},
            "3": {"$value": {"value": 16, "unit": "px"}},
            "4": {"$value": {"value": 24, "unit": "px"}},
            "6": {"$value": {"value": 32, "unit": "px"}},
        },
        "radius": {
            "$type": "dimension",
            "$extensions": part_ext("radius"),
            "sm": {"$value": {"value": 4, "unit": "px"}},
            "md": {"$value": {"value": 8, "unit": "px"}},
            "lg": {"$value": {"value": 12, "unit": "px"}},
            "pill": {"$value": {"value": 999, "unit": "px"}},
        },
        "elevation": {
            "$type": "shadow",
            "$extensions": part_ext("elevation"),
            "card": {
                "$value": {
                    "color": "{colour.ink}",
                    "offsetX": {"value": 0, "unit": "px"},
                    "offsetY": {"value": 2, "unit": "px"},
                    "blur": {"value": 8, "unit": "px"},
                    "spread": {"value": 0, "unit": "px"},
                }
            },
        },
        "motion": {
            "$extensions": part_ext("motion"),
            "fast": {"$type": "duration", "$value": {"value": 150, "unit": "ms"}},
            "normal": {"$type": "duration", "$value": {"value": 220, "unit": "ms"}},
            "out": {"$type": "cubicBezier", "$value": [0.16, 1.0, 0.3, 1.0]},
        },
    }


def stub_design_md(
    product: str,
    *,
    direction_name: str,
    why: str,
    how_to_use: str,
    what_not_to_do: str,
    status: str = "draft",
    approved_by: str | None = None,
    date: str | None = None,
    owner_words: str | None = None,
    source: str | None = None,
    reason: str | None = None,
) -> str:
    """Build a DESIGN.md document satisfying both design_files.parse_design_md and foundation's Direction contract."""
    stamp_date = date or design_files.today()
    if status == "approved":
        by = approved_by or "design"
        status_line = f"Status: approved by {by} on {stamp_date}"
        mirror_suffix = f"approved by {by} on {stamp_date}"
        if by == "owner":
            words = (owner_words or "approved").replace('"', "'")
            src = source or "gate_final"
            approval_tail = f'"{words}" ({src})'
        else:
            approval_tail = reason or "approved at gate_final"
        approvals_lines = [
            f"- {part}: {by} on {stamp_date}: {approval_tail}"
            for part in ("direction", *TOKEN_PARTS)
        ]
        approvals_block = "\n".join(approvals_lines)
    else:
        status_line = "Status: draft"
        mirror_suffix = "draft"
        approvals_block = ""

    mirror_lines = "\n".join(f"- {part}: {mirror_suffix}" for part in TOKEN_PARTS)
    lines = [
        f"# {product.capitalize()} design files",
        "",
        f"Product: {product}",
        f"Updated: {stamp_date}",
        f"Format: {FORMAT}",
        "",
        "## Users",
        "Status: draft",
        "",
        "### Primary users",
        "Grounded from .temper/product/brief.md.",
        "",
        "## Direction",
        status_line,
        "",
        "### Named direction",
        direction_name,
        "",
        "### Why",
        why,
        "",
        "### How to use",
        how_to_use,
        "",
        "### What not to do",
        what_not_to_do,
        "",
        "## Tokens",
        "Values live in tokens.json (DTCG 2025.10); each part's status:",
        mirror_lines,
        "",
        "## Logo",
        "Status: missing",
        "",
        "## Library",
        "Status: missing",
        "",
        "## Approvals",
    ]
    if approvals_block:
        lines.append(approvals_block)
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- Stage 2: directions

def directions_collect(ws: Workspace) -> dict[str, Any]:
    step_ws = ws.for_step("directions_collect")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    product = brief_doc["product"]
    out_dir = step_ws.folder("directions")
    out_dir.mkdir(parents=True, exist_ok=True)
    task = {
        "step": "directions_read",
        "product": product,
        "brief_sha256": brief_doc["sha256"],
        "constraints": brief_doc["constraints"],
        "taste_anchors": brief_doc["taste_anchors"],
    }
    task_text = json.dumps(task, indent=2, ensure_ascii=False)
    (out_dir / "task.md").write_text(f"# Directions task ({product})\n\n```json\n{task_text}\n```\n")
    step_ws.mark("directions_collect", "done")
    return {
        "ok": True,
        "step": "directions_collect",
        "model": "yes",
        "product": product,
        "task": task_text,
    }


def stub_model_read(step: str, *, task: str = "", draft: str = "", problems: str = "") -> dict[str, Any]:
    """Model-free $0.00 stub for directions_read/revise and build_read/revise (no workspace access)."""
    del draft, problems
    parsed_task: dict[str, Any] = {}
    if task.strip():
        try:
            parsed_task = json.loads(task)
        except json.JSONDecodeError:
            parsed_task = {}
    product = str(parsed_task.get("product") or "product")

    if step in ("directions_read", "directions_revise"):
        payload = {
            "product": product,
            "recommended": "a",
            "directions": [
                {
                    "id": "a",
                    "name": "Warm Ledger",
                    "summary": "High-contrast warm paper and deep ink with disciplined forest accent.",
                    "why": "Fits the brief's calm decision-first posture without dashboard clutter.",
                    "how_to_use": "Lead with ink hierarchy on warm paper; reserve accent for the single primary action.",
                    "what_not_to_do": "Never stack competing neon badges or purple-indigo gradients.",
                    "accent_hex": "#2E7D4F",
                },
                {
                    "id": "b",
                    "name": "Crisp Instrument",
                    "summary": "Taut neutral slate ground with sharp mineral blue signal.",
                    "why": "Gives dense workflows clean separation while keeping brief constraints intact.",
                    "how_to_use": "Use 8px spacing multiples and tabular mono figures for every quantitative comparison.",
                    "what_not_to_do": "Never flatten hierarchy into uniform 14px grey lists.",
                    "accent_hex": "#1D5B79",
                },
            ],
        }
        return {"ok": True, "step": step, "draft": payload}

    if step in ("build_read", "build_revise"):
        chosen_id = str(parsed_task.get("direction") or "a")
        accent_hex = "#2E7D4F" if chosen_id == "a" else "#1D5B79"
        dir_name = str(parsed_task.get("direction_name") or "Warm Ledger")
        payload = {
            "product": product,
            "direction": chosen_id,
            "direction_name": dir_name,
            "accent_hex": accent_hex,
            "why": str(parsed_task.get("why") or "Grounded in .temper/product/brief.md."),
            "how_to_use": "Apply colour, type, spacing, radius, elevation, and motion tokens consistently across views.",
            "what_not_to_do": "Never hardcode ad-hoc hex values or off-scale spacing outside tokens.json.",
        }
        return {"ok": True, "step": step, "draft": payload}

    raise ContractError(f"unknown stub model step {step!r}")


def _extract_draft_dict(raw_draft: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw_draft, dict):
        inner = raw_draft.get("draft")
        return dict(inner) if isinstance(inner, dict) else dict(raw_draft)
    text = (raw_draft or "").strip()
    if not text:
        return {}
    parsed = json.loads(text)
    if isinstance(parsed, dict) and isinstance(parsed.get("draft"), dict):
        return dict(parsed["draft"])
    if not isinstance(parsed, dict):
        raise ContractError("draft output must be a JSON object")
    return parsed


def directions_check(ws: Workspace, *, draft: str | dict[str, Any] | None = None) -> dict[str, Any]:
    step_ws = ws.for_step("directions_check")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    try:
        draft_obj = _extract_draft_dict(draft) if draft else stub_model_read(
            "directions_read", task=json.dumps({"product": brief_doc["product"]})
        )["draft"]
    except (json.JSONDecodeError, ContractError) as exc:
        return {"ok": True, "step": "directions_check", "valid": "no", "problems": str(exc)}

    dirs = draft_obj.get("directions")
    if not isinstance(dirs, list) or len(dirs) < 2:
        return {
            "ok": True,
            "step": "directions_check",
            "valid": "no",
            "problems": "directions draft must contain at least 2 candidate directions",
        }
    out_dir = step_ws.folder("directions")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "draft.json").write_text(json.dumps(draft_obj, indent=2, ensure_ascii=False) + "\n")
    step_ws.mark("directions_check", "done")
    return {"ok": True, "step": "directions_check", "valid": "yes", "problems": ""}


def directions_finish(ws: Workspace) -> dict[str, Any]:
    step_ws = ws.for_step("directions")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    product = brief_doc["product"]
    out_dir = step_ws.folder("directions")
    out_dir.mkdir(parents=True, exist_ok=True)

    draft_path = out_dir / "draft.json"
    if draft_path.is_file():
        draft_obj = step_ws.read_json("02-directions/draft.json")
    else:
        draft_obj = stub_model_read("directions_read", task=json.dumps({"product": product}))["draft"]

    entries: list[dict[str, Any]] = []
    for item in draft_obj["directions"]:
        did = str(item["id"])
        d_folder = out_dir / did
        d_folder.mkdir(parents=True, exist_ok=True)
        tok = stub_tokens(product, status="draft", accent_hex=str(item.get("accent_hex") or "#2E7D4F"))
        contracts.validate_tokens(tok, label=f"02-directions/{did}/tokens.json", step="directions")
        md = stub_design_md(
            product,
            direction_name=str(item["name"]),
            why=str(item["why"]),
            how_to_use=str(item["how_to_use"]),
            what_not_to_do=str(item["what_not_to_do"]),
            status="draft",
        )
        contracts.validate_design_md(md, label=f"02-directions/{did}/DESIGN.md", step="directions")
        (d_folder / "tokens.json").write_text(json.dumps(tok, indent=2, ensure_ascii=False) + "\n")
        (d_folder / "DESIGN.md").write_text(md)
        entries.append(
            {
                "id": did,
                "name": str(item["name"]),
                "summary": str(item["summary"]),
                "why": str(item["why"]),
                "tokens_file": f"02-directions/{did}/tokens.json",
                "design_md_file": f"02-directions/{did}/DESIGN.md",
            }
        )

    directions_doc = {
        "product": product,
        "brief_sha256": brief_doc["sha256"],
        "recommended": str(draft_obj.get("recommended") or entries[0]["id"]),
        "directions": entries,
    }
    contracts.validate("directions", directions_doc, step="directions")
    (out_dir / "directions.json").write_text(json.dumps(directions_doc, indent=2, ensure_ascii=False) + "\n")
    step_ws.mark("directions", "done")
    return {
        "ok": True,
        "step": "directions",
        "product": product,
        "recommended": directions_doc["recommended"],
        "count": len(entries),
    }


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
    step_ws = ws.for_step("proof")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    directions_doc = step_ws.read_json("02-directions/directions.json")

    for entry in directions_doc["directions"]:
        tok = step_ws.read_json(entry["tokens_file"])
        contracts.validate_tokens(tok, label=entry["tokens_file"], step="proof")
        md = step_ws.read_text(entry["design_md_file"])
        contracts.validate_design_md(md, label=entry["design_md_file"], step="proof")

    out_dir = step_ws.folder("proof")
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_rel = "03-proof/sample-screen.html"
    surface = _resolve_surface_record(
        brief_doc,
        base_url=base_url,
        commit=commit,
        ref=ref,
        allow_red_commit=allow_red_commit,
        sample_rel=sample_rel,
    )

    if surface["kind"] == "sample_screen":
        sample_html = _render_sample_screen_html(brief_doc, directions_doc)
        (out_dir / "sample-screen.html").write_text(sample_html, encoding="utf-8")

    previews = []
    for entry in directions_doc["directions"]:
        did = entry["id"]
        preview_rel = f"03-proof/preview-{did}.html"
        (out_dir / f"preview-{did}.html").write_text(
            f"<!doctype html><html lang='en'><body data-direction='{html.escape(did)}' "
            f"data-surface='{surface['kind']}'><h1>{html.escape(entry['name'])}</h1></body></html>\n",
            encoding="utf-8",
        )
        previews.append(
            {
                "direction": did,
                "surface_kind": surface["kind"],
                "artifact": preview_rel,
                "status": "ready",
            }
        )

    proof_doc = {
        "product": brief_doc["product"],
        "surface": surface,
        "previews": previews,
    }
    contracts.validate("proof", proof_doc, step="proof")
    (out_dir / "proof.json").write_text(json.dumps(proof_doc, indent=2, ensure_ascii=False) + "\n")
    step_ws.mark("proof", "done", surface_kind=surface["kind"])
    return {
        "ok": True,
        "step": "proof",
        "product": brief_doc["product"],
        "surface_kind": surface["kind"],
        "fallback": surface["fallback"],
        "previews_count": len(previews),
    }


# ---------------------------------------------------------------- Stage 4: build

def build_collect(ws: Workspace) -> dict[str, Any]:
    step_ws = ws.for_step("build_collect")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    directions_doc = step_ws.read_json("02-directions/directions.json")
    gate_dir = step_ws.read_json("02-directions/gate_direction.json")
    chosen_id = gate_dir["choice"]
    chosen = next((d for d in directions_doc["directions"] if d["id"] == chosen_id), directions_doc["directions"][0])
    chosen_tokens_rel = f"02-directions/{chosen['id']}/tokens.json"
    chosen_design_rel = f"02-directions/{chosen['id']}/DESIGN.md"
    chosen_tokens = step_ws.read_json(chosen_tokens_rel)
    chosen_design_md = step_ws.read_text(chosen_design_rel)
    contracts.validate_tokens(chosen_tokens, step="build_collect", file=chosen_tokens_rel)
    contracts.validate_design_md(chosen_design_md, step="build_collect", file=chosen_design_rel, product=brief_doc["product"])

    out_dir = step_ws.folder("build")
    out_dir.mkdir(parents=True, exist_ok=True)
    round_num = max(1, step_ws.round) if step_ws.run_file.is_file() else 1

    task = {
        "step": "build_read",
        "product": brief_doc["product"],
        "round": round_num,
        "direction": chosen["id"],
        "direction_name": chosen["name"],
        "why": chosen["why"],
    }
    task_text = json.dumps(task, indent=2, ensure_ascii=False)
    (out_dir / "task.md").write_text(f"# Build task ({brief_doc['product']} round {round_num})\n\n```json\n{task_text}\n```\n")
    step_ws.mark("build_collect", "done", round=round_num)
    return {
        "ok": True,
        "step": "build_collect",
        "model": "yes",
        "product": brief_doc["product"],
        "round": round_num,
        "direction": chosen["id"],
        "task": task_text,
    }


def build_check(ws: Workspace, *, draft: str | dict[str, Any] | None = None) -> dict[str, Any]:
    step_ws = ws.for_step("build_check")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    gate_dir = step_ws.read_json("02-directions/gate_direction.json")
    try:
        draft_obj = _extract_draft_dict(draft) if draft else stub_model_read(
            "build_read",
            task=json.dumps({"product": brief_doc["product"], "direction": gate_dir["choice"]}),
        )["draft"]
    except (json.JSONDecodeError, ContractError) as exc:
        return {"ok": True, "step": "build_check", "valid": "no", "problems": str(exc)}

    if not draft_obj.get("direction"):
        return {"ok": True, "step": "build_check", "valid": "no", "problems": "build draft missing direction id"}

    out_dir = step_ws.folder("build")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "draft.json").write_text(json.dumps(draft_obj, indent=2, ensure_ascii=False) + "\n")
    step_ws.mark("build_check", "done")
    return {"ok": True, "step": "build_check", "valid": "yes", "problems": ""}


def build_finish(ws: Workspace) -> dict[str, Any]:
    step_ws = ws.for_step("build")
    brief_doc = step_ws.read_json("01-brief/brief.json")
    directions_doc = step_ws.read_json("02-directions/directions.json")
    gate_dir = step_ws.read_json("02-directions/gate_direction.json")
    product = brief_doc["product"]
    chosen_id = gate_dir["choice"]
    chosen = next((d for d in directions_doc["directions"] if d["id"] == chosen_id), directions_doc["directions"][0])

    tok = step_ws.read_json(chosen["tokens_file"])
    md = step_ws.read_text(chosen["design_md_file"])

    contracts.validate_tokens(tok, label="04-build/tokens.json", step="build")
    contracts.validate_design_md(md, label="04-build/DESIGN.md", step="build")

    out_dir = step_ws.folder("build")
    out_dir.mkdir(parents=True, exist_ok=True)
    tok_text = json.dumps(tok, indent=2, ensure_ascii=False) + "\n"
    (out_dir / "tokens.json").write_text(tok_text, encoding="utf-8")
    (out_dir / "DESIGN.md").write_text(md, encoding="utf-8")

    round_num = max(1, step_ws.round) if step_ws.run_file.is_file() else 1
    build_doc = {
        "product": product,
        "round": round_num,
        "direction": chosen["id"],
        "tokens_file": "04-build/tokens.json",
        "design_md_file": "04-build/DESIGN.md",
        "tokens_sha256": hashlib.sha256(tok_text.encode("utf-8")).hexdigest(),
        "design_md_sha256": hashlib.sha256(md.encode("utf-8")).hexdigest(),
        "parts": list(TOKEN_PARTS),
    }
    contracts.validate("build", build_doc, step="build")
    (out_dir / "build.json").write_text(json.dumps(build_doc, indent=2, ensure_ascii=False) + "\n")
    step_ws.mark("build", "done", round=round_num, direction=chosen["id"])
    return {
        "ok": True,
        "step": "build",
        "product": product,
        "round": round_num,
        "direction": chosen["id"],
    }


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
    parsed_md = contracts.validate_design_md(raw_md, label="04-build/DESIGN.md", step="handoff")

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

    dir_subs = parsed_md["direction_subsections"]
    approved_md = stub_design_md(
        brief_doc["product"],
        direction_name=dir_subs["Named direction"],
        why=dir_subs["Why"],
        how_to_use=dir_subs["How to use"],
        what_not_to_do=dir_subs["What not to do"],
        status="approved",
        approved_by=approved_by,
        date=approved_date,
        owner_words=gate_final.get("owner_words"),
        source=gate_final.get("source"),
        reason=gate_final.get("reason"),
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
