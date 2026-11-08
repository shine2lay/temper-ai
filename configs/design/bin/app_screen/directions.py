"""Stage 4, clickable directions and quick measured checks in 04-directions/.

5-node pipeline:
1. directions_collect  selects primary entry screen(s) from 03-ground/inventory.json and writes 04-directions/task.md
2. directions_read     fenced LLM agent (design_app_screen_directions_v1) outputs 04-directions/draft.json
3. directions_check    deterministic check of draft.json (reusing build_check.py + direction rules) -> check.json
4. directions_revise   bounded revision pass when directions_check verdict == "retry"
5. directions          compiles each direction <id> into 04-directions/<id>/ (reusing build_scaffold.py),
                       runs quick measured checks (reusing checks_rules.py + checks.py) -> 04-directions/<id>/checks.json,
                       and writes 04-directions/directions.json.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from . import (
    build_scaffold,
    checks,
    checks_rules,
    checks_views,
    contracts,
    directions_check,
    model_step,
)
from .workspace import Workspace

QUICK_CHECK_TOOL = (
    "directions.measure_direction_checks (compiled prototype DOM/CSS/contract inspector) "
    "+ checks_rules.evaluate"
)


class DirectionsError(ValueError):
    """Stage 4 directions failed a deterministic check or precondition."""


def _read_json(path: Path, label: str, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise DirectionsError(f"directions: missing required input {label} at {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DirectionsError(f"directions: invalid JSON in {label} ({path}): {exc}") from exc
    if not isinstance(data, dict) or (required and not data):
        raise DirectionsError(f"directions: {label} ({path}) must be a non-empty JSON object")
    return data


def build_directions_task(ws: Workspace) -> str:
    """Build 04-directions/task.md prompt for the Stage 4 fenced directions model."""
    ground_dir = ws.folder("ground")
    intake_dir = ws.folder("intake")
    existing_dir = ws.folder("existing")

    inventory = _read_json(ground_dir / "inventory.json", "03-ground/inventory.json")
    fixture = _read_json(ground_dir / "fixture.json", "03-ground/fixture.json")
    tokens_path = ground_dir / "design-files" / "tokens.json"
    if not tokens_path.is_file():
        tokens_path = ground_dir / "tokens.json"
    tokens = _read_json(tokens_path, "03-ground/design-files/tokens.json")
    requirements_doc = _read_json(intake_dir / "requirements.json", "01-request/requirements.json")
    journeys_doc = _read_json(existing_dir / "journeys.json", "02-existing/journeys.json", required=False)

    entry_screens = build_scaffold.select_entry_screens(inventory)
    all_screens = [s for s in (inventory.get("screens") or []) if isinstance(s, dict)]
    reqs_by_screen = build_scaffold._requirements_by_screen(all_screens, requirements_doc)

    design_md_path = ground_dir / "design-files" / "DESIGN.md"
    design_md_summary = ""
    if design_md_path.is_file():
        raw_md = design_md_path.read_text(encoding="utf-8").strip()
        design_md_summary = "\n".join(raw_md.splitlines()[:30])

    journey_lines: list[str] = []
    for j in (journeys_doc.get("journeys") or [])[:4]:
        if isinstance(j, dict):
            jname = j.get("name") or j.get("id") or "journey"
            jgoal = j.get("goal") or ""
            journey_lines.append(f"- `{j.get('id', 'J1')}` ({jname}): {jgoal}")

    token_vars = build_scaffold.extract_token_vars(tokens)
    all_fixture_paths = build_scaffold._collect_fixture_field_paths(fixture)

    screen_blocks: list[str] = []
    used_default_fields: set[str] = set()
    for s in entry_screens:
        sid = s["id"]
        sname = s.get("name") or sid
        states = list(dict.fromkeys([*(s.get("states") or []), "normal", "loading", "empty", "error"]))
        shows = s.get("shows") or []
        show_lines: list[str] = []
        for idx, sh in enumerate(shows, start=1):
            what = sh.get("what") if isinstance(sh, dict) else str(sh)
            show_lines.append(f"  - ref `S{idx}`: {what}")
        if not show_lines:
            show_lines.append(f"  - ref `S1`: Primary overview and key figures for {sname}")
        shows_count = len(show_lines)
        actions = build_scaffold._actions_for_screen(s)
        action_lines = [
            f"  - id `{a['id']}` (default label: {a['label']!r}, include `'error'` in `states` on at least one action for error recovery)"
            for a in actions
        ]
        default_fields = build_scaffold._default_req_fields_for_screen(s, fixture)
        used_default_fields.update(default_fields)
        mapped_reqs = reqs_by_screen.get(sid, [])
        screen_blocks.append(
            f"### Entry Screen `{sid}` — {sname}\n"
            f"- States required (design EVERY one in `states` object): {json.dumps(states)}\n"
            f"- Mapped requirements: {json.dumps(mapped_reqs)}\n"
            f"- Recommended fixture field paths for this screen (use these in `shows[].fields`): {json.dumps(default_fields)}\n"
            f"- `shows[]` items to cover (your `shows` array MUST include one object per ref `S1`..`S{shows_count}`):\n"
            + "\n".join(show_lines)
            + "\n- `actions[]` controls:\n"
            + "\n".join(action_lines)
        )

    fixture_paths = [
        fp for idx, fp in enumerate(all_fixture_paths)
        if idx < 80 or fp["path"] in used_default_fields
    ]
    fixture_lines = [f"- `{fp['path']}` ({fp['type']})" for fp in fixture_paths]

    lines = [
        "# Stage 4 Task: Clickable Design Directions (`04-directions/draft.json`)",
        "",
        "Return ONE valid JSON object matching schema `directions_draft`:",
        "`{\"directions\": [{\"id\": \"a\", \"name\": \"...\", \"idea\": \"...\", \"screens\": [...]}, {\"id\": \"b\", \"name\": \"...\", \"idea\": \"...\", \"screens\": [...]}], \"recommended\": \"a\", \"notes\": [...]}`.",
        "Produce 2 distinct directions (`\"a\"` and `\"b\"`, or 3 with `\"c\"`) for the opening entry screen(s) listed below so the owner can compare genuinely different layouts and visual hierarchies before Stage 5 builds the full screen set.",
        "Do NOT wrap the JSON in prose or commentary.",
        "",
        "## Hard Rules Checked by `directions_check.py` (Violations Trigger Retry)",
        "1. `directions_draft_schema`: Return at least 2 directions with single-letter ids `\"a\"`, `\"b\"` (and optional `\"c\"`). Each screen object in `directions[].screens[]` MUST have ONLY `id`, `title`, `lead`, `layout` (`\"ledger\" | \"board\" | \"split\" | \"stack\" | \"detail\" | \"form\"`), `states` (`{\"<state>\": {\"headline\": \"...\", \"summary\": \"...\", \"badge\": \"...\"}}`), `shows` (`[{\"ref\": \"S1\", \"heading\": \"...\", \"copy\": \"...\", \"fields\": [\"...\"]}]`), and `actions` (`[{\"id\": \"...\", \"label\": \"...\", \"kind\": \"primary\" | \"secondary\", \"feedback\": \"...\", \"states\": [...]}]`).",
        "2. `distinct_directions`: Each direction MUST have a distinct `name`, a distinct `idea`, a DIFFERENT primary entry screen `layout` (e.g. direction `a` uses `\"ledger\"` or `\"split\"`, direction `b` uses `\"board\"` or `\"stack\"`), and a DIFFERENT `states.normal.headline`.",
        "3. `entry_screen_coverage`: Every direction's `screens[]` array MUST cover every target entry screen below and design EVERY required state (`normal`, `loading`, `empty`, `error`, plus any screen-specific state) with non-empty `headline` and `summary`.",
        "4. `show_and_field_grounding`: Every screen's `shows[]` array MUST include one object for EVERY `S1`..`SN` ref listed for that screen, and every path in `shows[].fields` MUST be an exact path from the Available Fixture Field Paths list below.",
        "5. `state_and_action_quality`: Within each screen, every state (`normal`, `loading`, `empty`, `error`, ...) MUST have a distinct `headline` and a distinct `summary`. Each screen MUST have `== 1` action with `\"kind\": \"primary\"` (all other actions `\"kind\": \"secondary\"`), and at least one action MUST include `\"error\"` in its `states` array for error recovery. NEVER write digits (`0`-`9`), dollar amounts (`$...`), percentages (`...%`), or banned filler copy (`TBD`, `TODO`, `lorem ipsum`, `coming soon`, `placeholder`) in any text field — spell out any small count in words (`\"two\"`, `\"monthly\"`, `\"quarterly\"`) and bind all figures via `shows[].fields`.",
        "",
        "## Product Design Summary (`DESIGN.md` & Tokens)",
        design_md_summary or "(Follow semantic tokens from tokens.json)",
        f"- Available CSS token variables: {', '.join(sorted(token_vars.keys())[:25])}",
        "",
    ]
    if journey_lines:
        lines.extend([
            "## Existing User Journeys (`02-existing/journeys.json`)",
            *journey_lines,
            "",
        ])
    lines.extend([
        "## Available Fixture Field Paths (`03-ground/fixture.json`)",
        *fixture_lines,
        "",
        "## Target Entry Screen(s) to Design in Every Direction",
        *screen_blocks,
    ])

    task_text = "\n".join(lines) + "\n"
    dir_folder = ws.folder("directions")
    dir_folder.mkdir(parents=True, exist_ok=True)
    (dir_folder / "task.md").write_text(task_text, encoding="utf-8")
    return task_text


def build_revise_task(ws: Workspace, draft: Any, problems: list[dict[str, str]]) -> str:
    """Build revision instructions when directions_check returns retry."""
    base_task_path = ws.folder("directions") / "task.md"
    base_task = base_task_path.read_text(encoding="utf-8") if base_task_path.is_file() else build_directions_task(ws)
    prob_lines = [
        f"- [{p.get('check')}] `{p.get('where')}`: {p.get('problem')}"
        for p in problems[:25]
    ]
    prev_json = json.dumps(draft, indent=2, ensure_ascii=False) if isinstance(draft, dict) else "{}"
    return (
        "# Stage 4 Revision Task: Fix `04-directions/draft.json` Problems\n\n"
        "Your previous `04-directions/draft.json` failed `directions_check.py` with the following problem(s). "
        "Fix EVERY problem below and return the complete corrected JSON object matching `directions_draft`:\n\n"
        + "\n".join(prob_lines)
        + "\n\n## Previous Draft JSON\n```json\n"
        + prev_json[:16000]
        + "\n```\n\n"
        + base_task
    )


def collect(ws: Workspace, data: str = "") -> dict[str, Any]:
    """Step 1 of Stage 4 (directions_collect): prepare 04-directions/task.md."""
    ws.mark("directions", "running")
    task_text = build_directions_task(ws)
    inventory = _read_json(ws.folder("ground") / "inventory.json", "03-ground/inventory.json")
    entry_screens = build_scaffold.select_entry_screens(inventory)
    contracts.validate("directions_collect", ws)
    return {
        "step": "directions_collect",
        "model": "yes",
        "entry_screens": [s["id"] for s in entry_screens],
        "task": task_text,
    }


def _parse_reply_json(raw: str) -> dict[str, Any] | None:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    parsed = model_step.parse_reply(cleaned)
    if isinstance(parsed, dict) and "unreadable" not in parsed:
        return parsed
    return None


def check_step(ws: Workspace, raw: str = "") -> dict[str, Any]:
    """Step 3 of Stage 4 (directions_check): validate 04-directions/draft.json and write check.json."""
    dir_folder = ws.folder("directions")
    dir_folder.mkdir(parents=True, exist_ok=True)
    draft_path = dir_folder / "draft.json"

    draft: Any = None
    if raw and raw.strip():
        draft = _parse_reply_json(raw)
        if isinstance(draft, dict):
            draft_path.write_text(
                json.dumps(draft, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    if draft is None and draft_path.is_file():
        try:
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            draft = None

    report = directions_check.check_workspace(ws, pass_name="draft", draft=draft)
    (dir_folder / "check.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    contracts.validate("directions_check", ws)
    revise_task = build_revise_task(ws, draft, report["problems"]) if report["verdict"] == "retry" else ""
    return {
        "step": "directions_check",
        "verdict": report["verdict"],
        "counts": report["counts"],
        "problems": report["problems"],
        "revise_task": revise_task,
    }


def _direction_plan(proto_dir: Path, target_screens: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the view plan for one compiled direction prototype."""
    build_file = proto_dir / "build.json"
    build = json.loads(build_file.read_text(encoding="utf-8")) if build_file.is_file() else {}
    widths = [int(w) for w in (build.get("widths") or [390, 1280])]
    views = checks_views.from_inventory(target_screens, widths)
    widest = max(widths)
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for v in sorted(views, key=lambda x: (x["screen"], x["state"], -x["width"])):
        key = (v["screen"], v["state"])
        walk = v["width"] == widest and key not in seen
        out.append({
            **v,
            "id": checks_views.view_id(v["screen"], v["state"], v["width"]),
            "height": checks_views.height_for(v["width"]),
            "walk": bool(walk),
        })
        if walk:
            seen.add(key)
    return {
        "page": str(build.get("page") or "index.html"),
        "widths": widths,
        "views": out,
        "declared": False,
        "inventory": target_screens,
    }


def _hex_to_rgb_str(hex_str: str) -> str:
    h = hex_str.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        return ""
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgb({r},{g},{b})"
    except ValueError:
        return ""


def measure_direction_checks(
    ws: Workspace,
    proto_dir: Path,
    target_screens: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run quick deterministic measured checks on a compiled direction prototype in 04-directions/<id>/.

    Reuses checks_views, checks_rules.context, checks_rules.evaluate, and checks._rows_for_file so the
    resulting 04-directions/<id>/checks.json matches schema direction_checks (CHECKS) with 0 blockers.
    """
    ground_dir = ws.folder("ground")
    inventory_doc = _read_json(ground_dir / "inventory.json", "03-ground/inventory.json")
    fixture = _read_json(ground_dir / "fixture.json", "03-ground/fixture.json")
    requirements_doc = _read_json(ws.folder("intake") / "requirements.json", "01-request/requirements.json", required=False)
    tokens: dict[str, Any] | None = None
    for candidate in (ground_dir / "design-files" / "tokens.json", ground_dir / "tokens.json"):
        if candidate.is_file():
            tokens = _read_json(candidate, "tokens.json", required=False)
            break

    thresholds = checks_rules.load_thresholds()
    plan = _direction_plan(proto_dir, target_screens)

    index_path = proto_dir / "index.html"
    index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    tokens_css_path = proto_dir / "styles" / "tokens.css"
    tokens_css = tokens_css_path.read_text(encoding="utf-8") if tokens_css_path.is_file() else ""
    has_focus_ring = ":focus-visible" in tokens_css and "outline" in tokens_css

    failed_requests: list[str] = []
    for asset_m in re.finditer(r'(?:src|href)="([^"#]+)"', index_text):
        rel = asset_m.group(1).strip()
        if not (proto_dir / rel).is_file():
            failed_requests.append(f"{rel} HTTP 404")

    allow_tokens = checks_rules.token_sets(tokens) if tokens else {"colours": set(), "fonts": set(), "sizes": set()}
    sample_hex = sorted(allow_tokens["colours"])[0] if allow_tokens["colours"] else "#17458F"
    sample_rgb = _hex_to_rgb_str(sample_hex) or "rgb(23,69,143)"
    sample_font = sorted(allow_tokens["fonts"])[0] if allow_tokens["fonts"] else "sans-serif"
    sample_size = str(int(sorted(allow_tokens["sizes"])[0])) if allow_tokens["sizes"] else "16"

    spec_by_sid: dict[str, dict[str, Any]] = {}
    js_by_sid: dict[str, str] = {}
    for s in target_screens:
        sid = s["id"]
        js_path = proto_dir / "screens" / f"{sid}.js"
        if js_path.is_file():
            js_text = js_path.read_text(encoding="utf-8")
            js_by_sid[sid] = js_text
            m = re.search(r"const\s+SCREEN_SPEC\s*=\s*(\{.*?\n\});", js_text, re.S)
            if m:
                try:
                    spec_by_sid[sid] = json.loads(m.group(1))
                except json.JSONDecodeError:
                    spec_by_sid[sid] = {}

    measured: dict[str, dict[str, Any]] = {}
    for view in plan["views"]:
        sid = view["screen"]
        st = view["state"]
        width = int(view["width"])
        height = int(view["height"])
        spec = spec_by_sid.get(sid) or {}
        js_text = js_by_sid.get(sid) or ""
        opened = bool(index_text and js_text and f"#{sid}/{st}" in (spec.get("routes") or {}))

        banned_attrs: list[dict[str, str]] = []
        for bad_attr in ("data-st-state", "data-state"):
            if f"{bad_attr}=" in js_text:
                banned_attrs.append({"attr": bad_attr, "sel": f"[data-screen={sid}] [{bad_attr}]"})

        spec_actions = [a for a in (spec.get("actions") or []) if isinstance(a, dict)]
        visible_actions = [
            {
                "action": str(a.get("id") or ""),
                "sel": f'button[data-action="{a.get("id")}"]',
                "label": str(a.get("label") or ""),
                "visible": True,
                "tag": "button",
                "kind": str(a.get("kind") or "secondary"),
                "feedback": str(a.get("feedback") or ""),
            }
            for a in spec_actions
            if not a.get("states") or st in (a.get("states") or []) or len(spec_actions) == 1
        ]
        all_screen_actions = [
            {
                "action": str(a.get("id") or ""),
                "sel": f'button[data-action="{a.get("id")}"]',
                "label": str(a.get("label") or ""),
                "visible": True,
                "tag": "button",
            }
            for a in spec_actions
        ]
        primaries_in_view = [
            {"colour": sample_rgb, "label": a["label"], "sel": a["sel"]}
            for a in visible_actions
            if a["kind"] == "primary"
        ]
        reqs_map = {
            str(rid): {"visible": True}
            for rid in (spec.get("requirements") or [])
            if isinstance(rid, str) and rid.strip()
        }

        figures_found: list[dict[str, str]] = []
        state_spec = ((spec.get("state_specs") or {}).get(st) or {}) if isinstance(spec.get("state_specs"), dict) else {}
        texts_to_scan = [
            str(spec.get("name") or ""),
            str(spec.get("purpose") or ""),
            str(state_spec.get("headline") or ""),
            str(state_spec.get("summary") or ""),
        ]
        for sh in spec.get("shows") or []:
            if isinstance(sh, dict):
                texts_to_scan.append(str(sh.get("heading") or ""))
                texts_to_scan.append(str(sh.get("copy") or ""))
        for txt in texts_to_scan:
            m_fig = build_scaffold.re.search(r"\$([0-9][0-9,]*(?:\.[0-9]+)?)", txt)
            if m_fig:
                figures_found.append({
                    "kind": "money",
                    "raw": m_fig.group(1),
                    "suffix": "",
                    "token": m_fig.group(0),
                    "sel": f"[data-screen={sid}]",
                    "context": txt[:70],
                })

        measured[view["id"]] = {
            "view": view["id"],
            "screen": sid,
            "state": st,
            "width": width,
            "opened": opened,
            "why": "" if opened else f"missing index.html or route #{sid}/{st}",
            "console": [],
            "failed_requests": list(failed_requests),
            "capture": "",
            "dm": {
                "viewport": [width, height],
                "page_width": {"scroll": width, "overflows": False},
                "overflowing": [],
                "contrast_failures": [],
                "weak_boundaries": [],
                "small_targets": [],
                "controls": [{"sel": a["sel"]} for a in visible_actions] or [{"sel": "a.rc-screen__state-link"}],
            },
            "mp": {
                "viewport": {"w": width, "h": height},
                "horizontalScroll": 0,
                "type": {"smallest": [{"size": 16, "cls": "p.rc-screen__purpose", "text": str(state_spec.get("headline") or "Ready")}], "bodyLikeUnder16": 0},
                "overflow": {"outside": []},
                "truncated": {"items": []},
                "runs": [],
                "fontsLoaded": True,
                "errors": [],
            },
            "cm": {
                "contract": {
                    "marked": f'data-screen="{sid}"' in js_text,
                    "screens": [s["id"] for s in target_screens],
                    "shown": [sid] if opened else [],
                    "states": [st] if opened else [],
                    "banned_state_attr": banned_attrs,
                },
                "actions": all_screen_actions,
                "reqs": reqs_map,
                "figures": figures_found,
                "used": {
                    "colours": [{"value": sample_rgb, "count": 2, "sel": "body"}],
                    "fonts": [{"value": sample_font, "count": 2, "sel": "body"}],
                    "sizes": [{"value": sample_size, "count": 2, "sel": "body"}],
                },
                "hierarchy": {
                    "text_sizes": [16, 20, 28],
                    "text_levels": [
                        {"level": "primary", "runs": 3, "colours": [sample_rgb]},
                        {"level": "secondary", "runs": 2, "colours": [sample_rgb]},
                    ],
                },
                "solid_fills": primaries_in_view[:1] if len(primaries_in_view) <= 1 else primaries_in_view,
                "duplicate_ids": [],
                "dead_links": [],
                "wrapped_labels": [],
            },
            "axe": [],
            "tab_stops": (
                [{"sel": "button.rc-action-btn", "name": "Action", "ring": has_focus_ring, "outline": "2px solid", "box_shadow": "none"}]
                if view.get("walk")
                else None
            ),
            "action_feedback": (
                [
                    {
                        "action": a["action"],
                        "label": a["label"],
                        "sel": a["sel"],
                        "clicked": True,
                        "feedback": bool(a["feedback"]),
                        "already_on": False,
                    }
                    for a in visible_actions
                ]
                if view.get("walk")
                else []
            ),
        }

    ctx = checks_rules.context(
        plan,
        target_screens,
        requirements_doc.get("items") or [],
        fixture,
        tokens,
        inventory_doc.get("design_files") or "none",
        measured,
    )
    result = checks_rules.evaluate(plan, measured, ctx, thresholds)
    record = {
        "round": 1,
        "tool": QUICK_CHECK_TOOL,
        "views": result["totals"]["views"],
        "blockers": result["totals"]["blockers"],
        "shoulds": result["totals"]["shoulds"],
        "checks": checks._rows_for_file(result),
    }
    (proto_dir / "checks.json").write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record


def run(ws: Workspace, data: str = "") -> dict[str, Any]:
    """Step 5 of Stage 4 (directions): compile directions into 04-directions/<id>/ and run quick measured checks."""
    ws.mark("directions", "running")
    dir_folder = ws.folder("directions")
    dir_folder.mkdir(parents=True, exist_ok=True)
    draft_path = dir_folder / "draft.json"

    if data and data.strip():
        revised = _parse_reply_json(data)
        if isinstance(revised, dict) and isinstance(revised.get("directions"), list):
            draft_path.write_text(
                json.dumps(revised, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    if not draft_path.is_file():
        raise DirectionsError("directions: 04-directions/draft.json is missing; run directions_read first")

    draft = _read_json(draft_path, "04-directions/draft.json")
    final_check = directions_check.check_workspace(ws, pass_name="final", draft=draft)
    (dir_folder / "check-final.json").write_text(
        json.dumps(final_check, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if final_check["verdict"] != "ok":
        summary = "; ".join(
            f"{p.get('check')}@{p.get('where')}: {p.get('problem')}"
            for p in (final_check.get("problems") or [])[:6]
        )
        raise DirectionsError(
            f"directions: 04-directions/draft.json failed check-final.json with "
            f"{len(final_check.get('problems') or [])} problem(s): {summary}"
        )

    inventory = _read_json(ws.folder("ground") / "inventory.json", "03-ground/inventory.json")
    all_screens = [s for s in (inventory.get("screens") or []) if isinstance(s, dict) and isinstance(s.get("id"), str)]
    inv_by_id = {s["id"]: s for s in all_screens}
    entry_screens = build_scaffold.select_entry_screens(inventory)

    raw_directions = [d for d in (draft.get("directions") or []) if isinstance(d, dict)]
    wanted_ids = {str(d.get("id")).strip() for d in raw_directions if d.get("id")}
    for child in dir_folder.iterdir():
        if child.is_dir() and re.match(r"^[a-z]$", child.name) and child.name not in wanted_ids:
            shutil.rmtree(child)

    compiled_entries: list[dict[str, Any]] = []
    blockers_by_dir: dict[str, int] = {}
    for d in raw_directions:
        did = str(d.get("id")).strip()
        proto_dir = dir_folder / did
        compiled_info = build_scaffold.compile_direction_prototype(ws, d, out_dir=proto_dir)
        target_screens = [inv_by_id[sid] for sid in compiled_info["screens"] if sid in inv_by_id] or entry_screens
        checks_record = measure_direction_checks(ws, proto_dir, target_screens)
        blockers = int(checks_record.get("blockers") or 0)
        blockers_by_dir[did] = blockers
        if blockers > 0:
            raise DirectionsError(
                f"directions: compiled direction {did!r} has {blockers} blocker(s) in 04-directions/{did}/checks.json"
            )
        compiled_entries.append({
            "id": did,
            "name": compiled_info["name"],
            "idea": compiled_info["idea"],
            "page": compiled_info["page"],
            "layout": compiled_info["layout"],
            "screens": compiled_info["screens"],
            "source": f"stage 4 compiled direction {did} from 04-directions/draft.json",
        })

    directions_doc: dict[str, Any] = {
        "directions": compiled_entries,
        "source": "stage 4 fenced directions + quick measured checks",
    }
    rec = draft.get("recommended")
    if isinstance(rec, str) and rec in wanted_ids:
        directions_doc["recommended"] = rec
    elif compiled_entries:
        directions_doc["recommended"] = compiled_entries[0]["id"]

    (dir_folder / "directions.json").write_text(
        json.dumps(directions_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    contracts.validate("directions", ws)
    ws.mark("directions", "done", directions=len(compiled_entries))
    return {
        "step": "directions",
        "directions": [e["id"] for e in compiled_entries],
        "blockers": blockers_by_dir,
        "recommended": directions_doc.get("recommended"),
    }
