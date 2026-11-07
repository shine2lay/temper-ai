"""Stage 4 deterministic checks on a directions draft in 04-directions/draft.json (rule 17: script first).

Reuses build_check.py validators for screen/state/show/field/action/copy rules (rule 36) plus Stage 4
direction-level rules:
- directions_draft_schema    valid JSON matching directions_draft (>= 2 directions with distinct ids a, b, ...)
- distinct_directions        each direction has a distinct name, distinct idea, and differs in primary screen
                             layout and normal-state headline
- entry_screen_coverage      every direction covers the target entry screen(s) and all required states
- show_and_field_grounding   every shows[] ref and fields[] path resolves in inventory.json and fixture.json
- state_and_action_quality   distinct state headlines/summaries, primary action present, error recovery action
                             present, no hardcoded figures, and no banned filler copy (BANNED_COPY_RE)
"""
from __future__ import annotations

import json
from typing import Any

from . import build_check, contracts
from .build_scaffold import select_entry_screens
from .workspace import Workspace

CHECKS = (
    "directions_draft_schema",
    "distinct_directions",
    "entry_screen_coverage",
    "show_and_field_grounding",
    "state_and_action_quality",
)


def _prob(check_name: str, where: str, problem: str) -> dict[str, str]:
    return {"check": check_name, "where": where, "problem": problem}


def check(
    draft: Any,
    inventory: dict[str, Any],
    fixture: dict[str, Any],
    pass_name: str = "draft",
) -> dict[str, Any]:
    """Run all deterministic Stage 4 checks on a directions draft."""
    problems: list[dict[str, str]] = []
    entry_screens = select_entry_screens(inventory)
    inv_screens = [
        s for s in (inventory.get("screens") or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    ]
    inv_by_id = {s["id"]: s for s in inv_screens}

    if not isinstance(draft, dict):
        problems.append(_prob(
            "directions_draft_schema",
            "04-directions/draft.json",
            "draft is missing or not a JSON object",
        ))
        return {
            "verdict": "retry",
            "pass": pass_name,
            "counts": {"directions": 0, "entry_screens": len(entry_screens), "problems": len(problems)},
            "checks": list(CHECKS),
            "problems": problems,
        }

    raw_directions = draft.get("directions")
    directions = [d for d in raw_directions if isinstance(d, dict)] if isinstance(raw_directions, list) else []

    if len(directions) < 2:
        problems.append(_prob(
            "directions_draft_schema",
            "04-directions/draft.json:directions",
            f"directions[] has {len(directions)} direction(s); at least 2 distinct directions are required",
        ))

    schema_errs = contracts.check_json("directions_draft", draft, "04-directions/draft.json")
    for err in schema_errs[:12]:
        problems.append(_prob(
            "directions_draft_schema",
            "04-directions/draft.json",
            err,
        ))

    seen_ids: set[str] = set()
    seen_names: dict[str, str] = {}
    seen_ideas: dict[str, str] = {}
    seen_layouts: dict[str, str] = {}
    seen_headlines: dict[str, str] = {}

    primary_sid = entry_screens[0]["id"] if entry_screens else ""

    for d_idx, d in enumerate(directions):
        did = str(d.get("id") or f"idx-{d_idx}").strip()
        d_where = f"04-directions/draft.json:directions[{did}]"
        if did in seen_ids:
            problems.append(_prob(
                "directions_draft_schema",
                f"{d_where}.id",
                f"duplicate direction id {did!r}; each direction must have a distinct id ('a', 'b', 'c', ...)",
            ))
        seen_ids.add(did)

        dname = str(d.get("name") or "").strip()
        didea = str(d.get("idea") or "").strip()
        if not dname:
            problems.append(_prob("distinct_directions", f"{d_where}.name", f"direction {did!r} has an empty name"))
        else:
            norm_name = dname.lower()
            if norm_name in seen_names:
                problems.append(_prob(
                    "distinct_directions",
                    f"{d_where}.name",
                    f"direction {did!r} repeats name {dname!r} of direction {seen_names[norm_name]!r}",
                ))
            else:
                seen_names[norm_name] = did
            m_ban = build_check.has_banned_copy(dname)
            if m_ban:
                problems.append(_prob(
                    "state_and_action_quality",
                    f"{d_where}.name",
                    f"banned filler copy {m_ban.group(0)!r} in {d_where}.name",
                ))

        if not didea:
            problems.append(_prob("distinct_directions", f"{d_where}.idea", f"direction {did!r} has an empty idea"))
        else:
            norm_idea = didea.lower()
            if norm_idea in seen_ideas:
                problems.append(_prob(
                    "distinct_directions",
                    f"{d_where}.idea",
                    f"direction {did!r} repeats idea of direction {seen_ideas[norm_idea]!r}",
                ))
            else:
                seen_ideas[norm_idea] = did
            m_ban = build_check.has_banned_copy(didea)
            if m_ban:
                problems.append(_prob(
                    "state_and_action_quality",
                    f"{d_where}.idea",
                    f"banned filler copy {m_ban.group(0)!r} in {d_where}.idea",
                ))

        d_screens = [s for s in (d.get("screens") or []) if isinstance(s, dict)]
        d_by_id = {str(s.get("id")): s for s in d_screens if isinstance(s.get("id"), str)}

        primary_ds = d_by_id.get(primary_sid) or (d_screens[0] if d_screens else None)
        if isinstance(primary_ds, dict):
            layout = str(primary_ds.get("layout") or "").strip()
            if layout:
                if layout in seen_layouts:
                    problems.append(_prob(
                        "distinct_directions",
                        f"{d_where}.screens[{primary_ds.get('id')}].layout",
                        f"direction {did!r} primary screen layout {layout!r} duplicates direction {seen_layouts[layout]!r}; directions must use different layouts",
                    ))
                else:
                    seen_layouts[layout] = did
            normal_st = ((primary_ds.get("states") or {}).get("normal") or {}) if isinstance(primary_ds.get("states"), dict) else {}
            normal_hl = str(normal_st.get("headline") or "").strip() if isinstance(normal_st, dict) else ""
            if normal_hl:
                norm_hl = normal_hl.lower()
                if norm_hl in seen_headlines:
                    problems.append(_prob(
                        "distinct_directions",
                        f"{d_where}.screens[{primary_ds.get('id')}].states.normal.headline",
                        f"direction {did!r} normal-state headline {normal_hl!r} duplicates direction {seen_headlines[norm_hl]!r}",
                    ))
                else:
                    seen_headlines[norm_hl] = did

        for es in entry_screens:
            es_id = es["id"]
            if es_id not in d_by_id:
                problems.append(_prob(
                    "entry_screen_coverage",
                    f"{d_where}.screens",
                    f"direction {did!r} is missing target entry screen {es_id!r}",
                ))

        for ds in d_screens:
            sid = str(ds.get("id") or "")
            s_where = f"{d_where}.screens[{sid}]"
            inv_s = inv_by_id.get(sid)
            if not inv_s:
                problems.append(_prob(
                    "entry_screen_coverage",
                    s_where,
                    f"direction {did!r} screen {sid!r} is not in 03-ground/inventory.json",
                ))
                continue
            problems.extend(
                build_check.validate_screen_draft_spec(
                    inv_s,
                    ds,
                    fixture,
                    s_where,
                    state_check="entry_screen_coverage",
                    show_check="show_and_field_grounding",
                    field_check="show_and_field_grounding",
                    quality_check="state_and_action_quality",
                    require_error_recovery=True,
                )
            )

    return {
        "verdict": "ok" if not problems else "retry",
        "pass": pass_name,
        "counts": {
            "directions": len(directions),
            "entry_screens": len(entry_screens),
            "problems": len(problems),
        },
        "checks": list(CHECKS),
        "problems": problems,
    }


def check_workspace(
    ws: Workspace,
    pass_name: str = "draft",
    draft: Any | None = None,
) -> dict[str, Any]:
    """Load ground inputs and run Stage 4 directions_check against 04-directions/draft.json."""
    ground_dir = ws.folder("ground")
    inv_path = ground_dir / "inventory.json"
    fx_path = ground_dir / "fixture.json"
    inventory = json.loads(inv_path.read_text(encoding="utf-8")) if inv_path.is_file() else {}
    fixture = json.loads(fx_path.read_text(encoding="utf-8")) if fx_path.is_file() else {}

    active_draft = draft
    if active_draft is None:
        draft_path = ws.folder("directions") / "draft.json"
        if draft_path.is_file():
            try:
                active_draft = json.loads(draft_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                active_draft = None

    return check(active_draft, inventory, fixture, pass_name=pass_name)
