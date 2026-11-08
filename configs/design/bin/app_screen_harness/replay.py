"""Model-boundary draft replay and deterministic browser-boundary measurement for `design_app_screen_v1`.

Supplies recorded or deterministically synthesized model drafts at the fenced model steps
(`intake`, `existing`, `ground`, `directions`, `build`, `review`) so the production stage code
(`collect`, `check`, `finish`) runs in `mode="real"` with zero live model calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RECORDED_ROOT = HERE / "recorded"


class HarnessReplayError(ValueError):
    """Raised when recorded inputs or workspace state cannot produce a valid model-boundary draft."""


def recorded_dir(case_name: str = "rollcall-20261104") -> Path:
    folder = RECORDED_ROOT / case_name
    if not folder.is_dir():
        raise HarnessReplayError(f"recorded case folder {folder} does not exist")
    return folder


def load_recorded_json(filename: str, case_name: str = "rollcall-20261104") -> Any:
    path = recorded_dir(case_name) / filename
    if not path.is_file():
        raise HarnessReplayError(f"recorded file {path} is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def expand_ground_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Expand compact `ground_spec.json` into a full `ground_draft` contract object."""
    base_states = ("normal", "loading", "empty", "error", "partial")
    screens: list[dict[str, Any]] = []
    for s in spec.get("screens", []):
        sources = list(s.get("sources") or [])
        if not sources:
            raise HarnessReplayError(f"ground_spec screen {s.get('id')!r} has no sources")
        src0 = sources[0]
        states = [{"name": n} for n in base_states]
        states += [{"name": n, "sources": [src0]} for n in s.get("states", []) if n not in base_states]
        actions = [
            {
                "id": a["id"],
                "what": a["what"],
                "sources": [src0],
                "states": ["pending", "done", "error", *a.get("extra", [])],
            }
            for a in s.get("actions", [])
        ]
        screens.append({
            "id": s["id"],
            "name": s["name"],
            "sources": sources,
            "shows": [{"what": s["what"], "sources": [src0]}],
            "states": states,
            "actions": actions,
        })
    return {
        "screens": screens,
        "excluded": [{"source": src, "reason": "n/a"} for src in spec.get("excluded", [])],
        "notes": "Recorded ground draft for deterministic real-mode harness replay.",
    }


def _read_ws_json(ws_path: Path, rel: str) -> dict[str, Any]:
    p = ws_path / rel
    if not p.is_file():
        raise HarnessReplayError(f"workspace file {p} is missing (needed by harness replay)")
    return json.loads(p.read_text(encoding="utf-8"))


def _synthesize_screen_draft(s: dict[str, Any], did: str, layout: str) -> dict[str, Any]:
    sid = s["id"]
    title = s.get("name", sid)
    raw_states = s.get("states", ["normal", "loading", "empty", "error", "partial"])
    state_names = [st["name"] if isinstance(st, dict) else str(st) for st in raw_states]
    states_map = {
        st: {
            "badge": st.upper(),
            "headline": f"{title} ({st.replace('-', ' ')} view, direction {did})",
            "summary": f"Displays {title} in {st.replace('-', ' ')} state with clear hierarchy and live account figures.",
        }
        for st in state_names
    }
    raw_shows = s.get("shows") or [{"what": title}]
    shows_list = []
    for idx, sh in enumerate(raw_shows, 1):
        what = sh.get("what", title) if isinstance(sh, dict) else str(sh)
        clean_what = what.replace("0", "zero").replace("1", "one").replace("2", "two")
        shows_list.append({
            "ref": f"S{idx}",
            "heading": clean_what[:60] or title[:60],
            "copy": f"Grounded view for {clean_what[:80]} bound to live account fixture data.",
            "fields": ["account.name", "today"],
        })
    raw_actions = s.get("actions") or [{"id": "open-primary", "what": "Open primary action", "states": ["pending", "done", "error"]}]
    actions_list = []
    for idx, a in enumerate(raw_actions):
        aid = a["id"] if isinstance(a, dict) else str(a)
        awhat = a.get("what", aid) if isinstance(a, dict) else aid
        clean_label = awhat.replace("0", "zero").replace("1", "one").replace("2", "two")[:40] or aid
        actions_list.append({
            "id": aid,
            "label": clean_label,
            "kind": "primary" if idx == 0 else "secondary",
            "feedback": f"Action {aid.replace('-', ' ')} recorded and confirmed.",
            "states": ["normal", "loading", "empty", "error", "partial"],
        })
    return {
        "id": sid,
        "title": title,
        "lead": f"Grounded {did.upper()} layout for {title} with progressive disclosure.",
        "layout": layout,
        "states": states_map,
        "shows": shows_list,
        "actions": actions_list,
    }


def synthesize_directions_draft(ws_path: Path) -> dict[str, Any]:
    """Build a valid Stage 4 (`directions_draft`) response for whatever screen inventory is in `03-ground/inventory.json`."""
    import sys
    design_bin = HERE.parent
    if str(design_bin) not in sys.path:
        sys.path.insert(0, str(design_bin))
    from app_screen import build_scaffold

    inv = _read_ws_json(ws_path, "03-ground/inventory.json")
    entry_screens = build_scaffold.select_entry_screens(inv)
    if not entry_screens:
        raise HarnessReplayError("03-ground/inventory.json has no entry screens")

    return {
        "directions": [
            {
                "id": "a",
                "name": "Action-First Ledger",
                "idea": "High-contrast ledger hierarchy surfacing urgent actions first with progressive detail.",
                "screens": [_synthesize_screen_draft(s, "a", "ledger") for s in entry_screens],
            },
            {
                "id": "b",
                "name": "Split Rail Workbench",
                "idea": "Two-column split workbench pairing account posture with inline strike cards.",
                "screens": [_synthesize_screen_draft(s, "b", "split") for s in entry_screens],
            },
        ]
    }


def synthesize_build_draft(ws_path: Path) -> dict[str, Any]:
    """Build a valid Stage 5 (`build_draft`) response for whatever screen inventory is in `03-ground/inventory.json`."""
    inv = _read_ws_json(ws_path, "03-ground/inventory.json")
    screens = inv.get("screens", [])
    if not screens:
        raise HarnessReplayError("03-ground/inventory.json has no screens")
    return {
        "notes": ["All grounded screens built with full state and action coverage."],
        "screens": [_synthesize_screen_draft(s, "a", "ledger") for s in screens],
    }


def synthesize_measures_for_workspace(ws: Any, plan: dict[str, Any], thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic browser-boundary DOM measurement for Stage 6 (`checks.measure`), writing view PNGs and returning `measured`."""
    from .cases import PNG_1X1

    inv = _read_ws_json(ws.path, "03-ground/inventory.json")
    req_doc = _read_ws_json(ws.path, "01-request/requirements.json")
    req_items = req_doc.get("items", req_doc.get("requirements", []))
    req_ids = [r["id"] for r in req_items]

    screens_by_id = {s["id"]: s for s in inv.get("screens", [])}
    out_dir = ws.round_folder()
    views_dir = out_dir / "views"
    views_dir.mkdir(parents=True, exist_ok=True)

    measured: dict[str, Any] = {}
    for v in plan.get("views", []):
        vid = v["id"]
        sid = v["screen"]
        st = v["state"]
        w = v["width"]
        h = 900 if w >= 1024 else (844 if w == 390 else 568)
        rel_cap = f"views/{vid}.png"
        (out_dir / rel_cap).write_bytes(PNG_1X1)

        inv_scr = screens_by_id.get(sid, {})
        actions = inv_scr.get("actions", [])
        cm_actions = []
        fb_actions = []
        for a in actions:
            aid = a["id"] if isinstance(a, dict) else str(a)
            awhat = a.get("what", aid) if isinstance(a, dict) else aid
            cm_actions.append({
                "action": aid,
                "sel": f"button[data-action='{aid}']",
                "label": awhat,
                "visible": True,
                "tag": "button",
            })
            fb_actions.append({
                "action": aid,
                "sel": f"button[data-action='{aid}']",
                "label": awhat,
                "found": True,
                "clicked": True,
                "feedback": True,
                "why": "",
            })

        measured[vid] = {
            "view": vid,
            "screen": sid,
            "state": st,
            "width": w,
            "opened": True,
            "why": "",
            "console": [],
            "failed_requests": [],
            "capture": rel_cap,
            "dm": {
                "viewport": [w, h],
                "page_width": {"scroll": w, "overflows": False},
                "overflowing": [],
                "contrast_failures": [],
                "weak_boundaries": [],
                "small_targets": [],
                "controls": [{"sel": "button.btn"}],
            },
            "mp": {
                "viewport": {"w": w, "h": h},
                "horizontalScroll": 0,
                "type": {
                    "smallest": [{"size": 16, "cls": "p", "text": "Grounded view"}],
                    "bodyLikeUnder16": 0,
                },
                "overflow": {"outside": []},
                "truncated": {"items": []},
                "runs": [],
                "fontsLoaded": True,
                "errors": [],
            },
            "cm": {
                "contract": {
                    "marked": True,
                    "screens": [sid],
                    "shown": [sid],
                    "states": [st],
                    "banned_state_attr": [],
                },
                "actions": cm_actions,
                "reqs": {rid: {"visible": True} for rid in req_ids},
                "figures": [],
                "used": {
                    "colours": [{"value": "rgb(23,69,143)", "count": 3, "sel": "button.btn"}],
                    "fonts": [{"value": "Inter", "count": 9, "sel": "body"}],
                    "sizes": [{"value": "16", "count": 9, "sel": "p"}],
                },
                "hierarchy": {
                    "text_sizes": [24, 16],
                    "text_levels": [{"level": "strongest", "runs": 9, "colours": ["rgb(23,69,143)"]}],
                    "text_colours": [{"colour": "rgb(23,69,143)", "runs": 9}],
                },
                "solid_fills": [
                    {"colour": "rgb(23,69,143)", "count": 1, "sel": "button.btn.primary", "label": "Primary"}
                ],
                "wrapped_labels": [],
                "duplicate_ids": [],
                "dead_links": [],
            },
            "axe": [],
            "tab_stops": [
                {"sel": "button.btn", "name": "Primary", "ring": True, "outline": "solid 3px", "box_shadow": "none"}
            ],
            "action_feedback": fb_actions,
        }

    return measured


def draft_for_step(step: str, ws_path: str | Path, case_name: str = "rollcall-20261104") -> dict[str, Any]:
    """Return the recorded or deterministically synthesized model-boundary JSON object for `step`."""
    ws_p = Path(ws_path).expanduser().resolve()
    key = step.removesuffix("_collect").removesuffix("_check").removesuffix("_finish")
    if key == "intake":
        return load_recorded_json("intake_draft.json", case_name)
    if key == "existing":
        return load_recorded_json("existing_draft.json", case_name)
    if key == "ground":
        spec = load_recorded_json("ground_spec.json", case_name)
        return expand_ground_spec(spec)
    if key == "directions":
        return synthesize_directions_draft(ws_p)
    if key == "build":
        return synthesize_build_draft(ws_p)
    if key == "review":
        return {"measured": [], "findings": []}
    raise HarnessReplayError(f"unknown model-boundary step {step!r}")
