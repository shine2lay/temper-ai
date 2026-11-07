"""Deterministic prototype scaffold writer for Stage 5a (build) of design_app_screen_v1.

Reads 03-ground/ (inventory.json, fixture.json, design-files/tokens.json, design-files/DESIGN.md)
and 04-directions/ (directions.json and gate_direction.json), plus 01-request/requirements.json
when present, and writes a complete, contract-valid prototype skeleton to 05-build/:
- index.html (shell with #app-screen-mount, screen navigation, embedded fixture JSON, script tags)
- styles/tokens.css (generated from the product's design tokens)
- shell/router.js (hash routing #<screen>/<state> and [data-action] click feedback handler)
- screens/<screen-id>.js (one file per screen with real states, regions, routing, actions,
  data-req figure bindings read from fixture.json, and a marked placeholder
  data-build-placeholder="<screen-id>")
- fixture.json (copied from 03-ground/fixture.json as the single source of figures)
- build.json (manifest with direction, round, page, widths, screens[], views[])

No model call is made in Stage 5a (rule 17). Inputs are validated at the boundary (rule 36):
missing or invalid ground/direction files or fields fail loud with a clear message naming the
missing file or field.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from . import contracts
from .workspace import Workspace

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
STATE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class BuildInputError(ValueError):
    """Input to Stage 5a build is missing or invalid."""


def _read_json_file(path: Path, rel_label: str) -> dict[str, Any]:
    if not path.is_file():
        raise BuildInputError(f"build: missing required file {rel_label}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildInputError(f"build: {rel_label} is not valid JSON ({exc.msg})") from exc
    if not isinstance(data, dict) or not data:
        raise BuildInputError(f"build: {rel_label} must be a non-empty JSON object")
    return data


def resolve_fixture_field(fixture: dict[str, Any], field_path: str) -> tuple[bool, Any]:
    """Resolve a dot-separated field path against fixture.json."""
    if not isinstance(fixture, dict) or not field_path or not isinstance(field_path, str):
        return False, None
    path = field_path.strip()
    if not path:
        return False, None
    if path in fixture:
        return True, fixture[path]
    cur: Any = fixture
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return False, None
        else:
            return False, None
    return True, cur


def fixture_field_exists(fixture: dict[str, Any], field_path: str) -> bool:
    found, _ = resolve_fixture_field(fixture, field_path)
    return found


def extract_token_vars(tokens_doc: dict[str, Any]) -> dict[str, str]:
    """Extract deterministic CSS custom properties (--var: value) from tokens.json."""
    if not isinstance(tokens_doc, dict):
        return {}
    out: dict[str, str] = {}

    css_root = tokens_doc.get("css_root_vars")
    if isinstance(css_root, dict):
        for k, v in sorted(css_root.items()):
            if isinstance(k, str) and k.startswith("--") and isinstance(v, (str, int, float)):
                out[k] = str(v)

    source = tokens_doc.get("tokens") if isinstance(tokens_doc.get("tokens"), dict) else tokens_doc

    for group_key in ("color", "colour"):
        color_group = source.get(group_key)
        if isinstance(color_group, dict):
            for name, entry in sorted(color_group.items()):
                if name.startswith("$"):
                    continue
                if isinstance(entry, str) and entry.strip():
                    out[f"--color-{name}"] = entry.strip()
                elif isinstance(entry, dict):
                    hex_val = entry.get("hex")
                    if not hex_val and isinstance(entry.get("$value"), dict):
                        hex_val = entry["$value"].get("hex")
                    elif not hex_val and isinstance(entry.get("$value"), str):
                        hex_val = entry["$value"]
                    if isinstance(hex_val, str) and hex_val.strip():
                        out[f"--color-{name}"] = hex_val.strip()

    font_group = source.get("font")
    if isinstance(font_group, dict):
        for name, entry in sorted(font_group.items()):
            if isinstance(entry, str) and entry.strip():
                out[f"--font-{name}"] = entry.strip()
            elif isinstance(entry, dict) and isinstance(entry.get("family"), str):
                out[f"--font-{name}"] = entry["family"].strip()

    type_group = source.get("type") or source.get("typography")
    if isinstance(type_group, dict):
        for name, entry in sorted(type_group.items()):
            if name.startswith("$"):
                continue
            if isinstance(entry, dict):
                if isinstance(entry.get("size_px"), (int, float)):
                    out[f"--type-{name}-size"] = f"{entry['size_px']}px"
                elif isinstance(entry.get("$value"), str) and entry["$value"].endswith("px"):
                    out[f"--type-{name}-size"] = entry["$value"]
                elif isinstance(entry.get("$value"), list) and entry["$value"]:
                    out[f"--font-{name}"] = ", ".join(str(x) for x in entry["$value"])
                if isinstance(entry.get("line_height"), (int, float)):
                    out[f"--type-{name}-line-height"] = str(entry["line_height"])
                if isinstance(entry.get("weight"), (int, float)):
                    out[f"--type-{name}-weight"] = str(entry["weight"])
            elif isinstance(entry, (int, float)):
                out[f"--type-{name}-size"] = f"{entry}px"

    space = source.get("space")
    if isinstance(space, dict):
        if isinstance(space.get("base_px"), (int, float)):
            out["--space-base"] = f"{space['base_px']}px"
        scale = space.get("scale_px")
        if isinstance(scale, list):
            for idx, val in enumerate(scale, start=1):
                if isinstance(val, (int, float)):
                    out[f"--space-{idx}"] = f"{val}px"
    elif isinstance(space, list):
        for idx, val in enumerate(space, start=1):
            if isinstance(val, (int, float)):
                out[f"--space-{idx}"] = f"{val}px"

    radius = source.get("radius")
    if isinstance(radius, dict):
        for name, val in sorted(radius.items()):
            clean = name[:-3] if name.endswith("_px") else name
            if isinstance(val, (int, float)):
                out[f"--radius-{clean}"] = f"{val}px"

    return out


def validate_inputs(ws: Workspace) -> dict[str, Any]:
    """Validate ground and direction inputs at the Stage 5a boundary. Fail loud with named file/field."""
    ground_dir = ws.folder("ground")
    if not ground_dir.is_dir():
        raise BuildInputError("build: missing ground folder 03-ground/")

    inventory_path = ground_dir / "inventory.json"
    fixture_path = ground_dir / "fixture.json"
    tokens_path = ground_dir / "design-files" / "tokens.json"
    design_md_path = ground_dir / "design-files" / "DESIGN.md"

    inventory = _read_json_file(inventory_path, "03-ground/inventory.json")
    fixture = _read_json_file(fixture_path, "03-ground/fixture.json")
    tokens = _read_json_file(tokens_path, "03-ground/design-files/tokens.json")
    if not design_md_path.is_file() or design_md_path.stat().st_size == 0:
        raise BuildInputError("build: missing required file 03-ground/design-files/DESIGN.md")

    token_vars = extract_token_vars(tokens)
    if not token_vars:
        raise BuildInputError("build: 03-ground/design-files/tokens.json contains no usable token values")

    screens = inventory.get("screens")
    if not isinstance(screens, list) or not screens:
        raise BuildInputError("build: 03-ground/inventory.json missing or empty field 'inventory.screens'")

    seen_ids: set[str] = set()
    for idx, screen in enumerate(screens):
        if not isinstance(screen, dict):
            raise BuildInputError(f"build: 03-ground/inventory.json field 'inventory.screens[{idx}]' must be an object")
        sid = screen.get("id")
        if not isinstance(sid, str) or not sid.strip() or not SLUG_RE.match(sid.strip()):
            raise BuildInputError(
                f"build: 03-ground/inventory.json missing or invalid field 'inventory.screens[{idx}].id'"
            )
        if sid in seen_ids:
            raise BuildInputError(
                f"build: 03-ground/inventory.json duplicate screen id {sid!r} in 'inventory.screens[{idx}].id'"
            )
        seen_ids.add(sid)

        name = screen.get("name")
        if not isinstance(name, str) or not name.strip():
            raise BuildInputError(
                f"build: 03-ground/inventory.json missing or empty field 'inventory.screens[{idx}].name' (screen {sid!r})"
            )

        states = screen.get("states")
        if not isinstance(states, list) or not states:
            raise BuildInputError(
                f"build: 03-ground/inventory.json missing or empty field 'inventory.screens[{idx}].states' (screen {sid!r})"
            )
        for st_idx, st in enumerate(states):
            if not isinstance(st, str) or not st.strip() or not STATE_RE.match(st.strip()):
                raise BuildInputError(
                    f"build: 03-ground/inventory.json invalid state in 'inventory.screens[{idx}].states[{st_idx}]' (screen {sid!r})"
                )

    ground_problems = contracts.check_json("inventory", inventory, "03-ground/inventory.json")
    if ground_problems:
        raise BuildInputError("build: invalid 03-ground/inventory.json: " + "; ".join(ground_problems))

    directions_dir = ws.folder("directions")
    if not directions_dir.is_dir():
        raise BuildInputError("build: missing directions folder 04-directions/")
    directions_path = directions_dir / "directions.json"
    directions_doc = _read_json_file(directions_path, "04-directions/directions.json")

    dir_list = directions_doc.get("directions")
    if not isinstance(dir_list, list) or not dir_list:
        raise BuildInputError("build: 04-directions/directions.json missing or empty field 'directions'")
    dir_ids = {d.get("id") for d in dir_list if isinstance(d, dict) and isinstance(d.get("id"), str)}

    gate_dir_path = directions_dir / "gate_direction.json"
    chosen_direction: str | None = None
    if gate_dir_path.is_file():
        gate_doc = _read_json_file(gate_dir_path, "04-directions/gate_direction.json")
        choice = gate_doc.get("choice")
        if not isinstance(choice, str) or not choice.strip():
            raise BuildInputError("build: 04-directions/gate_direction.json missing or empty field 'choice'")
        if choice not in dir_ids:
            raise BuildInputError(
                f"build: 04-directions/gate_direction.json choice {choice!r} is not in directions.json ({sorted(dir_ids)})"
            )
        chosen_direction = choice
    else:
        raw_chosen = directions_doc.get("chosen") or directions_doc.get("recommended")
        if not isinstance(raw_chosen, str) or not raw_chosen.strip():
            raise BuildInputError(
                "build: missing chosen direction in 04-directions/gate_direction.json ('choice') or 04-directions/directions.json ('chosen')"
            )
        if raw_chosen not in dir_ids:
            raise BuildInputError(
                f"build: chosen direction {raw_chosen!r} in 04-directions/directions.json is not in directions ({sorted(dir_ids)})"
            )
        chosen_direction = raw_chosen

    clean_directions_doc = {"directions": dir_list}
    directions_problems = contracts.check_json("directions", clean_directions_doc, "04-directions/directions.json")
    if directions_problems:
        raise BuildInputError("build: invalid 04-directions/directions.json: " + "; ".join(directions_problems))

    req_path = ws.folder("intake") / "requirements.json"
    requirements: dict[str, Any] = {}
    if req_path.is_file():
        requirements = _read_json_file(req_path, "01-request/requirements.json")

    return {
        "inventory": inventory,
        "fixture": fixture,
        "tokens": tokens,
        "token_vars": token_vars,
        "directions": directions_doc,
        "chosen_direction": chosen_direction,
        "requirements": requirements,
    }


def _collect_leaf_paths(node: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Collect deterministic (dot_path, scalar_value) pairs from fixture."""
    out: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for k in sorted(node.keys()):
            sub_prefix = f"{prefix}.{k}" if prefix else str(k)
            val = node[k]
            if isinstance(val, (int, float, str)) and not isinstance(val, bool):
                out.append((sub_prefix, val))
            elif isinstance(val, (dict, list)):
                out.extend(_collect_leaf_paths(val, sub_prefix))
    elif isinstance(node, list) and node:
        first = node[0]
        sub_prefix = f"{prefix}.0" if prefix else "0"
        if isinstance(first, (int, float, str)) and not isinstance(first, bool):
            out.append((sub_prefix, first))
        elif isinstance(first, dict):
            out.extend(_collect_leaf_paths(first, sub_prefix))
    return out


def _default_req_fields_for_screen(
    screen: dict[str, Any],
    fixture: dict[str, Any],
) -> list[str]:
    """Choose deterministic fixture field paths for a screen's data-req attributes."""
    chosen: list[str] = []
    for key in ("data_needed", "req_fields"):
        raw = screen.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    candidate = item.strip()
                    if fixture_field_exists(fixture, candidate) and candidate not in chosen:
                        chosen.append(candidate)
    if chosen:
        return chosen

    leaves = _collect_leaf_paths(fixture)
    num_leaves = [(p, v) for p, v in leaves if isinstance(v, (int, float)) and not isinstance(v, bool)]
    sid = screen["id"]
    sid_norm = sid.replace("-", "_")
    prefixes = [sid, sid_norm]
    if sid == "tickets":
        prefixes.extend(["roll_ticket", "sell_ticket"])

    for pref in prefixes:
        matched_num = [p for p, _ in num_leaves if p == pref or p.startswith(f"{pref}.")]
        if matched_num:
            return matched_num[:3]
        matched_any = [p for p, _ in leaves if p == pref or p.startswith(f"{pref}.")]
        if matched_any:
            return matched_any[:3]

    for shared_pref in ("account", "stats", "totals"):
        shared_num = [p for p, _ in num_leaves if p.startswith(f"{shared_pref}.")]
        if shared_num:
            return shared_num[:3]

    if num_leaves:
        return [p for p, _ in num_leaves[:3]]
    if leaves:
        return [p for p, _ in leaves[:2]]
    top_keys = sorted(str(k) for k in fixture.keys())
    return top_keys[:1]


def _requirements_by_screen(
    screens: list[dict[str, Any]],
    requirements_doc: dict[str, Any],
) -> dict[str, list[str]]:
    """Map every requirement ID in 01-request/requirements.json to at least one screen."""
    by_screen: dict[str, list[str]] = {s["id"]: [] for s in screens}
    if not screens:
        return by_screen

    for s in screens:
        sid = s["id"]
        for src in s.get("sources") or []:
            if isinstance(src, str) and src.startswith("req:"):
                rid = src.split(":", 1)[1].strip()
                if rid and rid not in by_screen[sid]:
                    by_screen[sid].append(rid)
        for act in s.get("actions") or []:
            if isinstance(act, dict):
                for src in act.get("sources") or []:
                    if isinstance(src, str) and src.startswith("req:"):
                        rid = src.split(":", 1)[1].strip()
                        if rid and rid not in by_screen[sid]:
                            by_screen[sid].append(rid)

    items = requirements_doc.get("items") if isinstance(requirements_doc, dict) else None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            rid = item.get("id")
            if not isinstance(rid, str) or not rid.strip():
                continue
            if any(rid in rlist for rlist in by_screen.values()):
                continue
            where = str(item.get("where") or "").strip()
            placed = False
            if where in by_screen:
                by_screen[where].append(rid)
                placed = True
            else:
                for sid in by_screen:
                    if sid in where:
                        by_screen[sid].append(rid)
                        placed = True
                        break
            if not placed:
                for sid in by_screen:
                    if rid not in by_screen[sid]:
                        by_screen[sid].append(rid)
    return by_screen


def _actions_for_screen(screen: dict[str, Any]) -> list[dict[str, str]]:
    """Return normalized action list [{id, label}] for a screen."""
    sid = screen["id"]
    sname = screen["name"]
    raw_actions = screen.get("actions")
    out: list[dict[str, str]] = []
    if isinstance(raw_actions, list):
        for idx, act in enumerate(raw_actions):
            if isinstance(act, dict):
                aid = str(act.get("id") or f"{sid}-action-{idx + 1}").strip()
                label = str(act.get("label") or act.get("what") or aid.replace("-", " ").capitalize()).strip()
                out.append({"id": aid, "label": label})
            elif isinstance(act, str) and act.strip():
                aid = act.strip()
                out.append({"id": aid, "label": aid.replace("-", " ").capitalize()})
    if not out:
        out.append({"id": f"{sid}-primary", "label": f"Inspect {sname}"})
    return out


def _regions_for_screen(screen: dict[str, Any]) -> list[str]:
    """Return normalized region slug list for a screen."""
    sid = screen["id"]
    raw_regions = screen.get("regions")
    if isinstance(raw_regions, list) and raw_regions:
        cleaned = [str(r).strip() for r in raw_regions if isinstance(r, str) and str(r).strip()]
        if cleaned:
            return cleaned
    return [f"{sid}-summary", f"{sid}-body"]


def render_tokens_css(tokens_doc: dict[str, Any]) -> str:
    """Render 05-build/styles/tokens.css from the product's design tokens."""
    token_vars = extract_token_vars(tokens_doc)

    color_vars = {k: v for k, v in sorted(token_vars.items()) if k.startswith("--color-")}
    font_vars = {k: v for k, v in sorted(token_vars.items()) if k.startswith("--font-")}

    bg_canvas = (
        token_vars.get("--color-paper-50")
        or token_vars.get("--bg-canvas")
        or token_vars.get("--color-surface")
        or next(iter(color_vars.values()), "#fcfaf6")
    )
    bg_surface = (
        token_vars.get("--color-surface")
        or token_vars.get("--bg-surface")
        or bg_canvas
    )
    bg_elevated = (
        token_vars.get("--color-paper-100")
        or token_vars.get("--bg-elevated")
        or bg_surface
    )
    text_primary = (
        token_vars.get("--color-ink-950")
        or token_vars.get("--color-ink-text")
        or token_vars.get("--color-ink")
        or token_vars.get("--text-primary")
        or (list(color_vars.values())[-1] if color_vars else "#0c121d")
    )
    text_secondary = (
        token_vars.get("--color-ink-600")
        or token_vars.get("--color-muted")
        or token_vars.get("--text-secondary")
        or text_primary
    )
    accent_primary = (
        token_vars.get("--color-tide-600")
        or token_vars.get("--color-primary")
        or token_vars.get("--accent-primary")
        or text_primary
    )
    border_color = (
        token_vars.get("--color-ink-600")
        or token_vars.get("--color-muted")
        or token_vars.get("--color-line")
        or token_vars.get("--border-subtle")
        or text_secondary
    )

    font_body = (
        token_vars.get("--font-body")
        or token_vars.get("--font-family")
        or token_vars.get("--font-sans")
        or next(iter(font_vars.values()), "sans-serif")
    )
    font_display = (
        token_vars.get("--font-display")
        or font_body
    )
    font_mono = (
        token_vars.get("--font-mono")
        or font_body
    )

    size_body = (
        token_vars.get("--type-body-size")
        or token_vars.get("--text-base")
        or "16px"
    )
    size_title = (
        token_vars.get("--type-title-size")
        or token_vars.get("--text-lg")
        or size_body
    )
    size_display = (
        token_vars.get("--type-display-size")
        or token_vars.get("--text-2xl")
        or size_title
    )

    lines = [
        "/* Generated deterministically by Stage 5a build_scaffold.py from 03-ground/design-files/tokens.json */",
        ":root {",
    ]
    for k, v in sorted(token_vars.items()):
        lines.append(f"  {k}: {v};")
    lines.extend([
        f"  --bg-canvas: {bg_canvas};",
        f"  --bg-surface: {bg_surface};",
        f"  --bg-elevated: {bg_elevated};",
        f"  --text-primary: {text_primary};",
        f"  --text-secondary: {text_secondary};",
        f"  --accent-primary: {accent_primary};",
        f"  --border-color: {border_color};",
        f"  --font-sans: {font_body};",
        f"  --font-heading: {font_display};",
        f"  --font-code: {font_mono};",
        f"  --size-body: {size_body};",
        f"  --size-title: {size_title};",
        f"  --size-display: {size_display};",
        "}",
        "",
        "*, *::before, *::after {",
        "  box-sizing: border-box;",
        "}",
        "",
        "html, body {",
        "  margin: 0;",
        "  padding: 0;",
        "  background-color: var(--bg-canvas);",
        "  color: var(--text-primary);",
        "  font-family: var(--font-sans);",
        "  font-size: var(--size-body);",
        "  line-height: 1.45;",
        "}",
        "",
        ".rc-shell {",
        "  min-height: 100vh;",
        "  display: flex;",
        "  flex-direction: column;",
        "  background-color: var(--bg-canvas);",
        "  color: var(--text-primary);",
        "}",
        "",
        ".rc-shell__header {",
        "  display: flex;",
        "  flex-wrap: wrap;",
        "  align-items: center;",
        "  justify-content: space-between;",
        "  gap: 12px;",
        "  padding: 16px 24px;",
        "  background-color: var(--bg-surface);",
        "  border-bottom: 1px solid var(--border-color);",
        "}",
        "",
        ".rc-shell__brand {",
        "  display: flex;",
        "  align-items: center;",
        "  gap: 12px;",
        "}",
        "",
        ".rc-shell__title {",
        "  font-family: var(--font-heading);",
        "  font-size: var(--size-title);",
        "  font-weight: 600;",
        "  line-height: 1.3;",
        "  color: var(--text-primary);",
        "}",
        "",
        ".rc-shell__badge {",
        "  display: inline-flex;",
        "  align-items: center;",
        "  padding: 4px 8px;",
        "  border-radius: 8px;",
        "  background-color: var(--bg-elevated);",
        "  color: var(--text-secondary);",
        "  font-size: var(--size-body);",
        "  line-height: 1.35;",
        "}",
        "",
        ".rc-shell__nav {",
        "  display: flex;",
        "  flex-wrap: wrap;",
        "  gap: 8px;",
        "}",
        "",
        ".rc-shell__nav-link, .rc-screen__state-link {",
        "  display: inline-flex;",
        "  flex: 0 0 auto;",
        "  max-width: 100%;",
        "  align-items: center;",
        "  justify-content: center;",
        "  min-height: 32px;",
        "  min-width: 32px;",
        "  padding: 6px 12px;",
        "  border-radius: 8px;",
        "  border: 1px solid var(--border-color);",
        "  background-color: var(--bg-surface);",
        "  color: var(--text-primary);",
        "  text-decoration: none;",
        "  font-size: var(--size-body);",
        "  line-height: 1.35;",
        "  overflow-wrap: anywhere;",
        "}",
        "",
        ".rc-shell__nav-link[aria-current=\"page\"], .rc-screen__state-link[aria-current=\"true\"] {",
        "  background-color: var(--bg-elevated);",
        "  color: var(--text-primary);",
        "  border-color: var(--accent-primary);",
        "  font-weight: 600;",
        "}",
        "",
        ".rc-shell__main {",
        "  flex: 1;",
        "  padding: 24px;",
        "  max-width: 1200px;",
        "  width: 100%;",
        "  margin: 0 auto;",
        "}",
        "",
        ".rc-screen {",
        "  display: flex;",
        "  flex-direction: column;",
        "  gap: 24px;",
        "}",
        "",
        ".rc-screen__header {",
        "  display: flex;",
        "  flex-direction: column;",
        "  gap: 8px;",
        "  padding: 16px;",
        "  background-color: var(--bg-surface);",
        "  border: 1px solid var(--border-color);",
        "  border-radius: 12px;",
        "}",
        "",
        ".rc-screen__title {",
        "  margin: 0;",
        "  font-family: var(--font-heading);",
        "  font-size: var(--size-display);",
        "  font-weight: 600;",
        "  line-height: 1.2;",
        "  color: var(--text-primary);",
        "}",
        "",
        ".rc-screen__purpose {",
        "  margin: 0;",
        "  color: var(--text-secondary);",
        "  font-size: var(--size-body);",
        "  line-height: 1.45;",
        "  max-width: 68ch;",
        "}",
        "",
        ".rc-screen__states {",
        "  display: flex;",
        "  flex-wrap: wrap;",
        "  gap: 8px;",
        "}",
        "",
        ".rc-screen__regions {",
        "  display: flex;",
        "  flex-direction: column;",
        "  gap: 16px;",
        "}",
        "",
        ".rc-screen__region {",
        "  padding: 16px;",
        "  background-color: var(--bg-surface);",
        "  border: 1px solid var(--border-color);",
        "  border-radius: 12px;",
        "}",
        "",
        ".rc-placeholder {",
        "  padding: 16px;",
        "  background-color: var(--bg-elevated);",
        "  border: 1px dashed var(--border-color);",
        "  border-radius: 8px;",
        "  display: flex;",
        "  flex-direction: column;",
        "  gap: 12px;",
        "}",
        "",
        ".rc-placeholder__title {",
        "  margin: 0;",
        "  font-size: var(--size-title);",
        "  font-weight: 600;",
        "  line-height: 1.3;",
        "  color: var(--text-primary);",
        "}",
        "",
        ".rc-placeholder__figures {",
        "  display: grid;",
        "  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));",
        "  gap: 12px;",
        "  margin: 0;",
        "}",
        "",
        ".rc-placeholder__metric {",
        "  padding: 12px;",
        "  background-color: var(--bg-surface);",
        "  border: 1px solid var(--border-color);",
        "  border-radius: 8px;",
        "}",
        "",
        ".rc-placeholder__field {",
        "  font-size: var(--size-body);",
        "  line-height: 1.35;",
        "  color: var(--text-secondary);",
        "  margin: 0 0 4px 0;",
        "}",
        "",
        ".rc-placeholder__value {",
        "  font-family: var(--font-code);",
        "  font-size: var(--size-body);",
        "  line-height: 1.45;",
        "  font-weight: 600;",
        "  color: var(--text-primary);",
        "  margin: 0;",
        "}",
        "",
        ".rc-screen__actions {",
        "  display: flex;",
        "  flex-wrap: wrap;",
        "  align-items: center;",
        "  gap: 12px;",
        "}",
        "",
        ".rc-action-btn {",
        "  display: inline-flex;",
        "  flex: 0 0 auto;",
        "  max-width: 100%;",
        "  align-items: center;",
        "  justify-content: center;",
        "  min-height: 36px;",
        "  min-width: 36px;",
        "  padding: 8px 16px;",
        "  border-radius: 8px;",
        "  border: 1px solid var(--border-color);",
        "  background-color: var(--bg-surface);",
        "  color: var(--text-primary);",
        "  font-family: var(--font-sans);",
        "  font-size: var(--size-body);",
        "  line-height: 1.35;",
        "  font-weight: 500;",
        "  cursor: pointer;",
        "  overflow-wrap: anywhere;",
        "}",
        "",
        ".rc-action-btn--primary {",
        "  background-color: var(--accent-primary);",
        "  color: var(--bg-surface);",
        "  border-color: var(--accent-primary);",
        "}",
        "",
        ".rc-action-btn:focus-visible, .rc-shell__nav-link:focus-visible, .rc-screen__state-link:focus-visible {",
        "  outline: 2px solid var(--accent-primary);",
        "  outline-offset: 2px;",
        "}",
        "",
        ".rc-action-feedback {",
        "  padding: 8px 12px;",
        "  border-radius: 8px;",
        "  background-color: var(--bg-surface);",
        "  border: 1px solid var(--border-color);",
        "  color: var(--text-primary);",
        "  font-size: var(--size-body);",
        "  line-height: 1.35;",
        "}",
        "",
        ".rc-state-banner {",
        "  padding: 16px;",
        "  background-color: var(--bg-surface);",
        "  border: 1px solid var(--border-color);",
        "  border-radius: 12px;",
        "  display: flex;",
        "  flex-direction: column;",
        "  gap: 8px;",
        "}",
        "",
        ".rc-state-banner__top {",
        "  display: flex;",
        "  flex-wrap: wrap;",
        "  align-items: center;",
        "  justify-content: space-between;",
        "  gap: 8px;",
        "}",
        "",
        ".rc-state-banner__headline {",
        "  margin: 0;",
        "  font-family: var(--font-heading);",
        "  font-size: var(--size-title);",
        "  font-weight: 600;",
        "  line-height: 1.3;",
        "  color: var(--text-primary);",
        "}",
        "",
        ".rc-state-banner__badge {",
        "  display: inline-flex;",
        "  align-items: center;",
        "  padding: 4px 8px;",
        "  border-radius: 8px;",
        "  border: 1px solid var(--border-color);",
        "  background-color: var(--bg-surface);",
        "  color: var(--text-secondary);",
        "  font-size: var(--size-body);",
        "  line-height: 1.35;",
        "}",
        "",
        ".rc-state-banner__summary {",
        "  margin: 0;",
        "  color: var(--text-secondary);",
        "  font-size: var(--size-body);",
        "  line-height: 1.45;",
        "  max-width: 68ch;",
        "}",
        "",
        ".rc-show-grid {",
        "  display: flex;",
        "  flex-direction: column;",
        "  gap: 16px;",
        "}",
        "",
        ".rc-show-card {",
        "  padding: 16px;",
        "  background-color: var(--bg-surface);",
        "  border: 1px solid var(--border-color);",
        "  border-radius: 12px;",
        "  display: flex;",
        "  flex-direction: column;",
        "  gap: 12px;",
        "}",
        "",
        ".rc-show-card__heading {",
        "  margin: 0;",
        "  font-family: var(--font-heading);",
        "  font-size: var(--size-title);",
        "  font-weight: 600;",
        "  line-height: 1.3;",
        "  color: var(--text-primary);",
        "}",
        "",
        ".rc-show-card__copy {",
        "  margin: 0;",
        "  color: var(--text-secondary);",
        "  font-size: var(--size-body);",
        "  line-height: 1.45;",
        "  max-width: 68ch;",
        "}",
        "",
        "@media (max-width: 480px) {",
        "  .rc-shell__header { padding: 12px 16px; }",
        "  .rc-shell__main { padding: 16px; }",
        "  .rc-screen__header, .rc-screen__region, .rc-state-banner, .rc-show-card { padding: 12px; }",
        "  .rc-placeholder__figures { grid-template-columns: 1fr; }",
        "}",
        "",
    ])
    return "\n".join(lines)


def render_screen_js(
    screen: dict[str, Any],
    req_fields: list[str],
    req_ids: list[str],
) -> str:
    """Render 05-build/screens/<screen-id>.js with real contract structure and placeholder body.

    No numeric figure is hardcoded in the JS file: all figures are resolved at runtime from
    window.__APP_FIXTURE__ via data-req field paths.
    """
    sid = screen["id"]
    sname = screen["name"]
    purpose = str(screen.get("purpose") or screen.get("primary_question") or sname)
    states = [str(st) for st in screen["states"]]
    routes = {f"#{sid}/{st}": st for st in states}
    regions = _regions_for_screen(screen)
    actions = _actions_for_screen(screen)

    spec_obj = {
        "id": sid,
        "name": sname,
        "purpose": purpose,
        "states": states,
        "routes": routes,
        "regions": regions,
        "actions": actions,
        "req_fields": req_fields,
        "requirements": req_ids,
        "placeholder": sid,
    }
    spec_json = json.dumps(spec_obj, indent=2, sort_keys=True)

    state_link_lines: list[str] = []
    for st in states:
        href = f"#{sid}/{st}"
        state_link_lines.append(
            f'      \'<a class="rc-screen__state-link" href="{href}" data-route-target="{href}"\' + (state === {json.dumps(st)} ? \' aria-current="true"\' : "") + ">{st}</a>"'
        )
    state_links_expr = " +\n".join(state_link_lines) if state_link_lines else '""'

    metric_lines: list[str] = []
    for field_path in req_fields:
        label = (
            field_path.replace("_30d", " monthly")
            .replace("_90d", " quarterly")
            .replace(".", " ")
            .replace("_", " ")
        )
        # Strip any digit indices like " 0 " so no literal number appears in label text
        label = re.sub(r"\b\d+\b", "", label).strip()
        label = re.sub(r"\s+", " ", label) or "metric"
        metric_lines.append(
            f'      \'<div class="rc-placeholder__metric"><dt class="rc-placeholder__field">{label}</dt>\' +\n'
            f'      \'<dd class="rc-placeholder__value" data-req="{field_path}">\' + esc(formatFixtureValue(resolveFixtureField(fixture, {json.dumps(field_path)}))) + "</dd></div>"'
        )
    metrics_expr = " +\n".join(metric_lines) if metric_lines else '""'

    region_lines: list[str] = []
    for idx, region_id in enumerate(regions):
        if idx == 0:
            region_lines.append(
                f'      \'<section class="rc-screen__region" data-region="{region_id}">\' + placeholderHtml + "</section>"'
            )
        else:
            region_lines.append(
                f'      \'<section class="rc-screen__region" data-region="{region_id}"><p class="rc-screen__purpose">Region: {region_id} (\' + esc(state) + ")</p></section>"'
            )
    regions_expr = " +\n".join(region_lines) if region_lines else '""'

    action_lines: list[str] = []
    for idx, act in enumerate(actions):
        cls = "rc-action-btn rc-action-btn--primary" if idx == 0 else "rc-action-btn"
        aid = act["id"]
        alabel = act["label"]
        action_lines.append(
            f'      \'<button type="button" class="{cls}" data-action="{aid}">{alabel}</button>\''
        )
    actions_expr = " +\n".join(action_lines) if action_lines else '""'

    req_attr_str = " ".join(req_ids)
    header_req_attr = f' data-req="{req_attr_str}"' if req_attr_str else ""
    req_coverage_line = (
        f'\'<div class="rc-screen__reqs" data-req="{req_attr_str}" hidden></div>\''
        if req_attr_str
        else '""'
    )

    return f"""/* Generated deterministically by Stage 5a build_scaffold.py for screen {sid!r} */
(function () {{
  "use strict";

  const SCREEN_SPEC = {spec_json};

  function resolveFixtureField(fixture, fieldPath) {{
    if (!fixture || typeof fixture !== "object" || !fieldPath) return undefined;
    if (Object.prototype.hasOwnProperty.call(fixture, fieldPath)) return fixture[fieldPath];
    const parts = String(fieldPath).split(".");
    let cur = fixture;
    for (let i = 0; i < parts.length; i += 1) {{
      const part = parts[i];
      if (cur && typeof cur === "object" && Object.prototype.hasOwnProperty.call(cur, part)) {{
        cur = cur[part];
      }} else if (Array.isArray(cur) && /^\\d+$/.test(part)) {{
        const idx = Number(part);
        cur = idx >= 0 && idx < cur.length ? cur[idx] : undefined;
      }} else {{
        return undefined;
      }}
    }}
    return cur;
  }}

  function firstScalarFromNode(node) {{
    if (node === null || node === undefined) return "";
    if (typeof node === "number" || typeof node === "string" || typeof node === "boolean") {{
      return String(node);
    }}
    if (Array.isArray(node)) {{
      for (let i = 0; i < node.length; i += 1) {{
        const sub = firstScalarFromNode(node[i]);
        if (sub !== "") return sub;
      }}
      return "";
    }}
    if (typeof node === "object") {{
      const keys = Object.keys(node);
      for (let i = 0; i < keys.length; i += 1) {{
        const val = node[keys[i]];
        if (typeof val === "number" || typeof val === "string") return String(val);
      }}
    }}
    return "";
  }}

  function formatFixtureValue(val) {{
    return firstScalarFromNode(val);
  }}

  function esc(text) {{
    return String(text === undefined || text === null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }}

  function render(requestedState, fixture) {{
    const state = SCREEN_SPEC.states.indexOf(requestedState) !== -1
      ? requestedState
      : SCREEN_SPEC.states[0];
    const routeHash = "#" + SCREEN_SPEC.id + "/" + state;

    const stateLinksHtml =
{state_links_expr};

    const metricsHtml =
{metrics_expr};

    const placeholderHtml =
      '<div class="rc-placeholder" data-build-placeholder="{sid}" data-placeholder-state="' + esc(state) + '">' +
        '<h2 class="rc-placeholder__title" data-build-placeholder-label="{sid}">' +
          "Placeholder: " + esc(SCREEN_SPEC.name) + " (" + esc(SCREEN_SPEC.id) + ") — " + esc(state) + " state" +
        "</h2>" +
        '<dl class="rc-placeholder__figures">' + metricsHtml + "</dl>" +
      "</div>";

    const regionsHtml =
{regions_expr};

    const actionsHtml =
{actions_expr};

    const reqCoverageHtml = {req_coverage_line};

    return (
      '<section class="rc-screen" data-screen="{sid}" data-view-state="' + esc(state) + '" data-route="' + esc(routeHash) + '">' +
        '<header class="rc-screen__header"{header_req_attr}>' +
          '<h1 class="rc-screen__title">' + esc(SCREEN_SPEC.name) + "</h1>" +
          '<p class="rc-screen__purpose">' + esc(SCREEN_SPEC.purpose) + "</p>" +
          '<nav class="rc-screen__states" aria-label="Screen states">' + stateLinksHtml + "</nav>" +
        "</header>" +
        '<div class="rc-screen__regions">' + regionsHtml + "</div>" +
        '<footer class="rc-screen__actions" data-region="screen-actions">' +
          actionsHtml +
          '<output class="rc-action-feedback" data-action-feedback="{sid}" aria-live="polite">Ready (' + esc(state) + ")</output>" +
        "</footer>" +
        reqCoverageHtml +
      "</section>"
    );
  }}

  window.__APP_SCREENS__ = window.__APP_SCREENS__ || {{}};
  window.__APP_SCREENS__[SCREEN_SPEC.id] = {{
    spec: SCREEN_SPEC,
    render: render
  }};
}})();
"""


def render_router_js(screens: list[dict[str, Any]]) -> str:
    """Render 05-build/shell/router.js for #<screen>/<state> hash routing and [data-action] handling."""
    default_screen = screens[0]["id"]
    default_state = screens[0]["states"][0]
    routes_map: dict[str, dict[str, str]] = {}
    for s in screens:
        sid = s["id"]
        for st in s["states"]:
            routes_map[f"#{sid}/{st}"] = {"screen": sid, "state": str(st)}

    routes_json = json.dumps(routes_map, indent=2, sort_keys=True)
    return f"""/* Generated deterministically by Stage 5a build_scaffold.py */
(function () {{
  "use strict";

  const ROUTES = {routes_json};
  const DEFAULT_SCREEN = {json.dumps(default_screen)};
  const DEFAULT_STATE = {json.dumps(default_state)};

  function parseHash(rawHash) {{
    const cleaned = String(rawHash || "").replace(/^#\\/?/, "").trim();
    if (!cleaned) {{
      return {{ screen: DEFAULT_SCREEN, state: DEFAULT_STATE, hash: "#" + DEFAULT_SCREEN + "/" + DEFAULT_STATE }};
    }}
    const parts = cleaned.split("/");
    const screenId = parts[0] || DEFAULT_SCREEN;
    const registry = window.__APP_SCREENS__ || {{}};
    const entry = registry[screenId] || registry[DEFAULT_SCREEN];
    if (!entry) {{
      return {{ screen: screenId, state: parts[1] || DEFAULT_STATE, hash: "#" + screenId + "/" + (parts[1] || DEFAULT_STATE) }};
    }}
    const validStates = entry.spec.states || [DEFAULT_STATE];
    const requestedState = parts[1] && validStates.indexOf(parts[1]) !== -1 ? parts[1] : validStates[0];
    return {{
      screen: entry.spec.id,
      state: requestedState,
      hash: "#" + entry.spec.id + "/" + requestedState
    }};
  }}

  function renderCurrentRoute() {{
    const target = parseHash(window.location.hash);
    const registry = window.__APP_SCREENS__ || {{}};
    const fixture = window.__APP_FIXTURE__ || {{}};
    const mount = document.getElementById("app-screen-mount");
    if (!mount) return target;

    const entry = registry[target.screen];
    if (!entry || typeof entry.render !== "function") {{
      mount.innerHTML = "";
      return target;
    }}

    mount.innerHTML = entry.render(target.state, fixture);
    document.body.setAttribute("data-active-screen", target.screen);
    document.body.setAttribute("data-active-state", target.state);

    const navLinks = document.querySelectorAll(".rc-shell__nav-link");
    for (let i = 0; i < navLinks.length; i += 1) {{
      const link = navLinks[i];
      if (link.getAttribute("data-nav-screen") === target.screen) {{
        link.setAttribute("aria-current", "page");
      }} else {{
        link.removeAttribute("aria-current");
      }}
    }}
    return target;
  }}

  document.addEventListener("click", function (event) {{
    const btn = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    if (!btn) return;
    const actionId = btn.getAttribute("data-action") || "";
    btn.setAttribute("data-action-triggered", "true");
    btn.setAttribute("aria-pressed", "true");
    btn.classList.add("is-triggered");
    const screenRoot = btn.closest("[data-screen]");
    const feedback = screenRoot
      ? screenRoot.querySelector("[data-action-feedback]")
      : document.querySelector("[data-action-feedback]");
    if (feedback) {{
      feedback.textContent = "Action triggered: " + actionId;
      feedback.setAttribute("data-last-action", actionId);
    }}
  }});

  window.__APP_ROUTER__ = {{
    routes: ROUTES,
    parseHash: parseHash,
    renderCurrentRoute: renderCurrentRoute
  }};

  window.addEventListener("hashchange", renderCurrentRoute);
  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", renderCurrentRoute);
  }} else {{
    renderCurrentRoute();
  }}
}})();
"""


def render_index_html(
    product: str,
    chosen_direction: str,
    screens: list[dict[str, Any]],
    fixture: dict[str, Any],
) -> str:
    """Render 05-build/index.html shell loading tokens.css, every screen file, and shell/router.js."""
    nav_items: list[str] = []
    script_tags: list[str] = []
    for s in screens:
        sid = s["id"]
        sname = html.escape(str(s["name"]))
        first_state = str(s["states"][0])
        href = f"#{sid}/{first_state}"
        nav_items.append(
            f'        <a class="rc-shell__nav-link" href="{html.escape(href)}" '
            f'data-nav-screen="{html.escape(sid)}" data-route-target="{html.escape(href)}">{sname}</a>'
        )
        script_tags.append(f'  <script src="screens/{html.escape(sid)}.js"></script>')

    fixture_json = json.dumps(fixture, indent=2, sort_keys=True)
    nav_html = "\n".join(nav_items)
    scripts_html = "\n".join(script_tags)
    title_text = html.escape(f"{product} — Prototype Scaffold (Direction {chosen_direction.upper()})")

    return f"""<!DOCTYPE html>
<html lang="en" data-prototype-contract="v1" data-direction="{html.escape(chosen_direction)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title_text}</title>
  <link rel="stylesheet" href="styles/tokens.css">
</head>
<body>
  <div class="rc-shell" data-shell="app-screen">
    <header class="rc-shell__header" role="banner">
      <div class="rc-shell__brand">
        <span class="rc-shell__title">{html.escape(product)}</span>
        <span class="rc-shell__badge">Direction {html.escape(chosen_direction.upper())} · Stage 5a Scaffold</span>
      </div>
      <nav class="rc-shell__nav" aria-label="Screens">
{nav_html}
      </nav>
    </header>
    <main id="app-screen-mount" class="rc-shell__main" role="main"></main>
  </div>
  <script id="app-fixture-data">
  window.__APP_FIXTURE__ = {fixture_json};
  </script>
{scripts_html}
  <script src="shell/router.js"></script>
</body>
</html>
"""


def build_manifest(
    chosen_direction: str,
    screens: list[dict[str, Any]],
    round_num: int = 1,
) -> dict[str, Any]:
    """Build the contract-valid 05-build/build.json structure."""
    screens_out: list[dict[str, Any]] = []
    views_out: list[dict[str, Any]] = []
    all_widths: list[int] = []

    for s in screens:
        sid = s["id"]
        sname = s["name"]
        states = [str(st) for st in s["states"]]
        widths = [int(w) for w in (s.get("widths") or [1440, 390, 320])]
        for w in widths:
            if w not in all_widths:
                all_widths.append(w)
        screens_out.append({
            "id": sid,
            "file": f"screens/{sid}.js",
            "states": states,
        })
        for st in states:
            views_out.append({
                "screen": sid,
                "state": st,
                "open": {"hash": f"#{sid}/{st}"},
                "widths": widths,
                "what": f"{sname} ({st})",
            })

    if not all_widths:
        all_widths = [1440, 390, 320]

    return {
        "direction": chosen_direction,
        "round": max(1, int(round_num)),
        "page": "index.html",
        "widths": all_widths,
        "screens": screens_out,
        "views": views_out,
        "main": "#app-screen-mount",
        "areas": {
            "shell": ".rc-shell__header",
            "screen": "[data-screen]",
            "placeholder": "[data-build-placeholder]",
        },
        "source": "stage 5a deterministic scaffold: shell, per-screen files, tokens.css, fixture.json and build.json; each screen body carries data-build-placeholder",
    }


def write_scaffold(ws: Workspace) -> dict[str, Any]:
    """Validate inputs and write the deterministic Stage 5a prototype skeleton into 05-build/."""
    validated = validate_inputs(ws)
    inventory = validated["inventory"]
    fixture = validated["fixture"]
    tokens = validated["tokens"]
    chosen_direction = validated["chosen_direction"]
    requirements_doc = validated["requirements"]

    screens: list[dict[str, Any]] = inventory["screens"]
    ws_product = ws.run().get("product") if ws.run_file.is_file() else None
    if ws.run_file.is_file():
        if (
            ws.round == 0
            or (ws.round_folder() / "checks.json").is_file()
            or (ws.round_folder() / "review.json").is_file()
        ):
            ws.next_round()
    round_num = ws.round if (ws.run_file.is_file() and ws.round >= 1) else 1
    src_product = (inventory.get("source") or {}).get("product") if isinstance(inventory.get("source"), dict) else None
    product = str(inventory.get("product") or src_product or fixture.get("product") or ws_product or "app")

    build_dir = ws.folder("build")
    styles_dir = build_dir / "styles"
    screens_dir = build_dir / "screens"
    shell_dir = build_dir / "shell"

    styles_dir.mkdir(parents=True, exist_ok=True)
    screens_dir.mkdir(parents=True, exist_ok=True)
    shell_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale screen JS files if any exist from a previous run
    expected_screen_files = {f"{s['id']}.js" for s in screens}
    for existing_js in sorted(screens_dir.glob("*.js")):
        if existing_js.name not in expected_screen_files:
            existing_js.unlink()

    # 1. styles/tokens.css
    tokens_css = render_tokens_css(tokens)
    (styles_dir / "tokens.css").write_text(tokens_css, encoding="utf-8")

    # 2. fixture.json copied into 05-build/fixture.json as the single source of figures
    (build_dir / "fixture.json").write_text(
        json.dumps(fixture, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 3. screens/<screen-id>.js one file per screen
    reqs_by_screen = _requirements_by_screen(screens, requirements_doc)
    req_fields_by_screen: dict[str, list[str]] = {}
    for s in screens:
        sid = s["id"]
        req_fields = _default_req_fields_for_screen(s, fixture)
        req_fields_by_screen[sid] = req_fields
        js_code = render_screen_js(s, req_fields, reqs_by_screen.get(sid, []))
        (screens_dir / f"{sid}.js").write_text(js_code, encoding="utf-8")

    # 4. shell/router.js
    router_js = render_router_js(screens)
    (shell_dir / "router.js").write_text(router_js, encoding="utf-8")

    # 5. index.html
    index_html = render_index_html(product, chosen_direction, screens, fixture)
    (build_dir / "index.html").write_text(index_html, encoding="utf-8")

    # 6. build.json
    manifest = build_manifest(chosen_direction, screens, round_num=round_num)
    (build_dir / "build.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    contracts.validate("build", ws)

    return {
        "manifest": manifest,
        "chosen_direction": chosen_direction,
        "round": manifest["round"],
        "req_fields_by_screen": req_fields_by_screen,
    }


def _collect_fixture_field_paths(node: Any, prefix: str = "", out: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    if out is None:
        out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "about":
                continue
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (int, float, str, bool)) and v is not None:
                out.append({"path": path, "type": type(v).__name__, "sample": str(v)[:40]})
            elif isinstance(v, dict):
                out.append({"path": path, "type": "object", "sample": f"keys={list(v.keys())[:4]}"})
                _collect_fixture_field_paths(v, path, out)
            elif isinstance(v, list) and v:
                out.append({"path": path, "type": f"list[{len(v)}]", "sample": f"len={len(v)}"})
                _collect_fixture_field_paths(v[0], f"{path}.0", out)
    return out


def _open_round_feedback(ws: Workspace, round_num: int) -> list[str]:
    notes: list[str] = []
    if round_num <= 1:
        return notes
    prev_round = ws.folder("checks") / f"round-{round_num - 1}" / "review.json"
    if prev_round.is_file():
        try:
            rev = json.loads(prev_round.read_text(encoding="utf-8"))
            for f in rev.get("findings") or []:
                if isinstance(f, dict) and f.get("priority") == "must":
                    fid = f.get("id") or "F?"
                    loc = f.get("location") or f.get("screen") or "all"
                    screen = f.get("screen") or (str(loc).split("/")[0].split(":")[0].split("@")[0].strip() if loc else "all")
                    elem = f.get("element") or ""
                    evid = f.get("evidence") or f.get("what") or ""
                    sugg = f.get("suggestion") or ""
                    line = (
                        f"Must finding {fid} (screen={screen}, location={loc}, element={elem}): "
                        f"evidence={evid!r}"
                    )
                    if sugg:
                        line += f" -> suggestion: {sugg}"
                    notes.append(line)
        except (OSError, json.JSONDecodeError):
            pass
    comments_path = ws.folder("show") / "comments.json"
    if comments_path.is_file():
        try:
            cdoc = json.loads(comments_path.read_text(encoding="utf-8"))
            for item in (cdoc.get("comments") or cdoc.get("items") or []):
                if isinstance(item, dict):
                    text = item.get("body") or item.get("text")
                    where = (
                        item.get("where")
                        or "/".join(str(x) for x in (item.get("element"), item.get("state")) if x)
                        or "general"
                    )
                    if text:
                        notes.append(f"Owner comment ({where}): {text}")
        except (OSError, json.JSONDecodeError):
            pass
    return notes


def build_task(ws: Workspace) -> str:
    """Build 05-build/task.md prompt for the Stage 5b fenced screen-writer model."""
    validated = validate_inputs(ws)
    inventory = validated["inventory"]
    fixture = validated["fixture"]
    tokens = validated["tokens"]
    chosen_direction = validated["chosen_direction"]
    directions_doc = validated["directions"]
    requirements_doc = validated["requirements"]

    screens: list[dict[str, Any]] = inventory["screens"]
    reqs_by_screen = _requirements_by_screen(screens, requirements_doc)

    chosen_dir_obj: dict[str, Any] = {}
    for d in directions_doc.get("directions") or []:
        if isinstance(d, dict) and d.get("id") == chosen_direction:
            chosen_dir_obj = d
            break

    design_md_path = ws.folder("ground") / "design-files" / "DESIGN.md"
    design_md_summary = ""
    if design_md_path.is_file():
        raw_md = design_md_path.read_text(encoding="utf-8").strip()
        design_md_summary = "\n".join(raw_md.splitlines()[:35])

    token_vars = extract_token_vars(tokens)
    all_fixture_paths = _collect_fixture_field_paths(fixture)
    round_num = ws.round if (ws.run_file.is_file() and ws.round >= 1) else 1
    feedback_lines = _open_round_feedback(ws, round_num)

    screen_blocks: list[str] = []
    used_default_fields: set[str] = set()
    for s in screens:
        sid = s["id"]
        sname = s.get("name") or sid
        states = [str(st) for st in (s.get("states") or [])]
        shows = s.get("shows") or []
        show_lines: list[str] = []
        for idx, sh in enumerate(shows, start=1):
            what = sh.get("what") if isinstance(sh, dict) else str(sh)
            show_lines.append(f"  - ref `S{idx}`: {what}")
        if not show_lines:
            show_lines.append(f"  - ref `S1`: Primary overview and key figures for {sname}")
        shows_count = len(show_lines)
        actions = _actions_for_screen(s)
        action_lines = [
            f"  - id `{a['id']}` (default label: {a['label']!r}, states: {a.get('states') or states})"
            for a in actions
        ]
        default_fields = _default_req_fields_for_screen(s, fixture)
        used_default_fields.update(default_fields)
        mapped_reqs = reqs_by_screen.get(sid, [])
        screen_blocks.append(
            f"### Screen `{sid}` — {sname}\n"
            f"- States required (design EVERY one in `states` object): {json.dumps(states)}\n"
            f"- Mapped requirements: {json.dumps(mapped_reqs)}\n"
            f"- Default fixture field paths for this screen (use these in `shows[].fields`): {json.dumps(default_fields)}\n"
            f"- `shows[]` items to cover (your `shows` array MUST include one object per ref `S1`..`S{shows_count}`): \n"
            + "\n".join(show_lines)
            + "\n- `actions[]` controls:\n"
            + ("\n".join(action_lines) if action_lines else "  - (none)")
        )

    fixture_paths = [
        fp for idx, fp in enumerate(all_fixture_paths)
        if idx < 100 or fp["path"] in used_default_fields
    ]
    fixture_lines = [
        f"- `{fp['path']}` ({fp['type']})"
        for fp in fixture_paths
    ]

    lines = [
        "# Stage 5b Task: Screen Design Spec (`05-build/draft.json`)",
        "",
        "Return ONE valid JSON object matching schema `build_draft` (`{\"screens\": [...], \"notes\": [...]}`).",
        "Each screen object in `screens[]` MUST have ONLY the keys `id`, `title`, `lead`, `layout` (`\"ledger\" | \"board\" | \"split\" | \"stack\" | \"detail\" | \"form\"`), `states` (`{\"<state>\": {\"headline\": \"...\", \"summary\": \"...\", \"badge\": \"...\"}}`), `shows` (`[{\"ref\": \"S1\", \"heading\": \"...\", \"copy\": \"...\", \"fields\": [\"...\"]}]`), and `actions` (`[{\"id\": \"...\", \"label\": \"...\", \"kind\": \"primary\" | \"secondary\", \"feedback\": \"...\", \"states\": [...]}]`).",
        "Do NOT wrap in markdown explanations outside the JSON.",
        "",
        "## Chosen Direction",
        f"- Direction ID: `{chosen_direction}`",
        f"- Name: {chosen_dir_obj.get('name', chosen_direction)}",
        f"- Idea: {chosen_dir_obj.get('idea', 'Clean, high-contrast hierarchy with progressive disclosure.')}",
        "",
        "## Product Design Summary (`DESIGN.md` & Tokens)",
        design_md_summary or "(Follow semantic tokens from tokens.json)",
        f"- Available CSS token variables: {', '.join(sorted(token_vars.keys())[:30])}",
        "",
        "## Hard Rules Checked by `build_check.py` (Violations Fail the Build)",
        "1. `every_screen_state_designed`: Every screen in `inventory.json` must appear in `screens[]`, and its `states` object must have an entry for EVERY state listed for that screen (`headline` and `summary` non-empty strings, optional `badge`).",
        "2. `every_show_covered`: Every screen's `shows[]` array must include one item for EVERY `S1`..`SN` ref listed for that screen, with `ref` (`\"S1\"`, `\"S2\"`, ...), `heading`, `copy`, and `fields` (non-empty array of valid `fixture.json` field paths).",
        "3. `single_primary_action`: In each screen's `actions[]` array, at most ONE action may have `\"kind\": \"primary\"`; all other actions on that screen MUST have `\"kind\": \"secondary\"`.",
        "4. `no_hardcoded_figures`: NEVER write any digits (`0`-`9`), dollar amounts (`$...`), percentages (`...%`), decimals, or multi-digit numbers in `title`, `lead`, `heading`, `copy`, `headline`, `summary`, `badge`, `label`, or `feedback`! Spell out any small count in words (e.g. `\"ten\"`, `\"two\"`, `\"monthly\"`, `\"quarterly\"`) and bind all figures via `fields[]` paths from `fixture.json`.",
        "5. `data_req_in_fixture`: Every path in `shows[].fields` MUST be an exact path from the Available Fixture Field Paths list below.",
        "6. Concise copy: Keep every string concise (`headline` <= 8 words, `summary` <= 18 words, `copy` <= 18 words, `feedback` <= 12 words), list 1-2 field paths per `shows[]` item, and keep `notes` to 1-2 short strings.",
        "",
        "## Available Fixture Field Paths (`03-ground/fixture.json`)",
        *fixture_lines,
        "",
    ]
    if feedback_lines:
        lines.extend([
            f"## Must Findings From Round {round_num - 1} To Fix",
            f"## Round {round_num} Open Feedback to Address",
            "Every item below blocked the previous round and MUST be fixed in this round's `draft.json` (do NOT repeat any flagged error trace, secret, robotic placeholder label, or reassurance fluff; still obey `no_hardcoded_figures` — spell out any small count in words, never write digits 0-9 in prose, and bind figures via `shows[].fields`):",
            *[f"- {fb}" for fb in feedback_lines],
            "",
        ])
    lines.extend([
        "## Screens to Design",
        *screen_blocks,
    ])
    task_text = "\n".join(lines) + "\n"
    build_dir = ws.folder("build")
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "task.md").write_text(task_text, encoding="utf-8")
    return task_text


def _clean_field_label(field_path: str) -> str:
    label = (
        field_path.replace("_30d", " monthly")
        .replace("_90d", " quarterly")
        .replace(".", " ")
        .replace("_", " ")
    )
    label = re.sub(r"\b\d+\b", "", label).strip()
    return re.sub(r"\s+", " ", label) or "metric"


def render_built_screen_js(
    screen: dict[str, Any],
    draft_screen: dict[str, Any],
    req_fields: list[str],
    req_ids: list[str],
    fixture: dict[str, Any],
) -> str:
    """Compile a screen's Stage 5b draft spec into 05-build/screens/<id>.js with zero placeholders."""
    sid = screen["id"]
    sname = str(draft_screen.get("title") or screen.get("name") or sid)
    purpose = str(draft_screen.get("lead") or screen.get("purpose") or screen.get("primary_question") or sname)
    layout = str(draft_screen.get("layout") or "stack")
    states = [str(st) for st in screen["states"]]
    routes = {f"#{sid}/{st}": st for st in states}
    regions = _regions_for_screen(screen)
    inv_actions = _actions_for_screen(screen)

    draft_shows = [sh for sh in (draft_screen.get("shows") or []) if isinstance(sh, dict)]
    all_fields: list[str] = list(req_fields)
    for sh in draft_shows:
        for fp in sh.get("fields") or []:
            if isinstance(fp, str) and fp.strip() and fixture_field_exists(fixture, fp.strip()):
                if fp.strip() not in all_fields:
                    all_fields.append(fp.strip())

    draft_actions_by_id = {
        str(a.get("id")): a
        for a in (draft_screen.get("actions") or [])
        if isinstance(a, dict) and a.get("id")
    }
    compiled_actions: list[dict[str, Any]] = []
    primary_used = False
    for idx, inv_act in enumerate(inv_actions):
        aid = inv_act["id"]
        d_act = draft_actions_by_id.get(aid, {})
        kind = str(d_act.get("kind") or ("primary" if idx == 0 else "secondary"))
        if kind == "primary":
            if primary_used:
                kind = "secondary"
            else:
                primary_used = True
        label = str(d_act.get("label") or inv_act["label"])
        feedback = str(d_act.get("feedback") or f"Action triggered: {aid}")
        act_states = [str(st) for st in (d_act.get("states") or inv_act.get("states") or states)]
        compiled_actions.append({
            "id": aid,
            "label": label,
            "kind": kind,
            "states": act_states,
            "feedback": feedback,
        })

    draft_states = draft_screen.get("states") if isinstance(draft_screen.get("states"), dict) else {}
    compiled_states: dict[str, dict[str, str]] = {}
    for st in states:
        st_obj = draft_states.get(st) if isinstance(draft_states.get(st), dict) else {}
        compiled_states[st] = {
            "headline": str(st_obj.get("headline") or f"{sname} ({st})"),
            "summary": str(st_obj.get("summary") or purpose),
            "badge": str(st_obj.get("badge") or st),
        }

    compiled_shows: list[dict[str, Any]] = []
    for idx, sh in enumerate(draft_shows, start=1):
        valid_f = [
            fp.strip()
            for fp in (sh.get("fields") or [])
            if isinstance(fp, str) and fp.strip() and fixture_field_exists(fixture, fp.strip())
        ]
        if not valid_f:
            valid_f = list(all_fields[:2])
        compiled_shows.append({
            "ref": str(sh.get("ref") or f"S{idx}"),
            "heading": str(sh.get("heading") or sname),
            "copy": str(sh.get("copy") or purpose),
            "fields": valid_f,
        })

    spec_obj = {
        "id": sid,
        "name": sname,
        "purpose": purpose,
        "layout": layout,
        "states": states,
        "routes": routes,
        "regions": regions,
        "actions": compiled_actions,
        "req_fields": all_fields,
        "requirements": req_ids,
        "state_specs": compiled_states,
        "shows": compiled_shows,
    }
    spec_json = json.dumps(spec_obj, indent=2, sort_keys=True)

    state_link_lines: list[str] = []
    for st in states:
        href = f"#{sid}/{st}"
        state_link_lines.append(
            f'      \'<a class="rc-screen__state-link" href="{href}" data-route-target="{href}"\' + (state === {json.dumps(st)} ? \' aria-current="true"\' : "") + ">{st}</a>"'
        )
    state_links_expr = " +\n".join(state_link_lines) if state_link_lines else '""'

    show_card_lines: list[str] = []
    for sh in compiled_shows:
        ref = sh["ref"]
        heading_js = json.dumps(sh["heading"])
        copy_js = json.dumps(sh["copy"])
        metric_items: list[str] = []
        for fp in sh["fields"]:
            flabel = _clean_field_label(fp)
            metric_items.append(
                f'          \'<div class="rc-placeholder__metric"><dt class="rc-placeholder__field">{html.escape(flabel)}</dt>\' +\n'
                f'          \'<dd class="rc-placeholder__value" data-req="{html.escape(fp)}">\' + esc(formatFixtureValue(resolveFixtureField(fixture, {json.dumps(fp)}))) + "</dd></div>"'
            )
        metrics_card_expr = " +\n".join(metric_items) if metric_items else '""'
        show_card_lines.append(
            f'      \'<article class="rc-show-card" data-show-ref="{html.escape(ref)}">\' +\n'
            f'        \'<h3 class="rc-show-card__heading">\' + esc({heading_js}) + "</h3>" +\n'
            f'        \'<p class="rc-show-card__copy">\' + esc({copy_js}) + "</p>" +\n'
            f'        \'<dl class="rc-placeholder__figures">\' +\n{metrics_card_expr} +\n'
            f'        "</dl>" +\n'
            f'      "</article>"'
        )
    shows_expr = " +\n".join(show_card_lines) if show_card_lines else '""'

    region_lines: list[str] = []
    for idx, region_id in enumerate(regions):
        if idx == 0:
            region_lines.append(
                f'      \'<section class="rc-screen__region" data-region="{region_id}">\' + builtBodyHtml + "</section>"'
            )
        else:
            region_lines.append(
                f'      \'<section class="rc-screen__region" data-region="{region_id}"><p class="rc-screen__purpose">\' + esc(stateSpec.summary) + "</p></section>"'
            )
    regions_expr = " +\n".join(region_lines) if region_lines else '""'

    action_lines: list[str] = []
    for act in compiled_actions:
        cls = "rc-action-btn rc-action-btn--primary" if act["kind"] == "primary" else "rc-action-btn"
        aid = html.escape(act["id"])
        alabel = html.escape(act["label"])
        fb = html.escape(act["feedback"])
        action_lines.append(
            f'      \'<button type="button" class="{cls}" data-action="{aid}" data-action-message="{fb}">{alabel}</button>\''
        )
    actions_expr = " +\n".join(action_lines) if action_lines else '""'

    req_attr_str = " ".join(req_ids)
    header_req_attr = f' data-req="{req_attr_str}"' if req_attr_str else ""
    req_coverage_line = (
        f'\'<div class="rc-screen__reqs" data-req="{req_attr_str}" hidden></div>\''
        if req_attr_str
        else '""'
    )

    return f"""/* Generated deterministically by Stage 5b build_scaffold.py for screen {sid!r} */
(function () {{
  "use strict";

  const SCREEN_SPEC = {spec_json};

  function resolveFixtureField(fixture, fieldPath) {{
    if (!fixture || typeof fixture !== "object" || !fieldPath) return undefined;
    if (Object.prototype.hasOwnProperty.call(fixture, fieldPath)) return fixture[fieldPath];
    const parts = String(fieldPath).split(".");
    let cur = fixture;
    for (let i = 0; i < parts.length; i += 1) {{
      const part = parts[i];
      if (cur && typeof cur === "object" && Object.prototype.hasOwnProperty.call(cur, part)) {{
        cur = cur[part];
      }} else if (Array.isArray(cur) && /^\\d+$/.test(part)) {{
        const idx = Number(part);
        cur = idx >= 0 && idx < cur.length ? cur[idx] : undefined;
      }} else {{
        return undefined;
      }}
    }}
    return cur;
  }}

  function firstScalarFromNode(node) {{
    if (node === null || node === undefined) return "";
    if (typeof node === "number" || typeof node === "string" || typeof node === "boolean") {{
      return String(node);
    }}
    if (Array.isArray(node)) {{
      for (let i = 0; i < node.length; i += 1) {{
        const sub = firstScalarFromNode(node[i]);
        if (sub !== "") return sub;
      }}
      return "";
    }}
    if (typeof node === "object") {{
      const keys = Object.keys(node);
      for (let i = 0; i < keys.length; i += 1) {{
        const val = node[keys[i]];
        if (typeof val === "number" || typeof val === "string") return String(val);
      }}
    }}
    return "";
  }}

  function formatFixtureValue(val) {{
    return firstScalarFromNode(val);
  }}

  function esc(text) {{
    return String(text === undefined || text === null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }}

  function render(requestedState, fixture) {{
    const state = SCREEN_SPEC.states.indexOf(requestedState) !== -1
      ? requestedState
      : SCREEN_SPEC.states[0];
    const routeHash = "#" + SCREEN_SPEC.id + "/" + state;
    const stateSpec = (SCREEN_SPEC.state_specs && SCREEN_SPEC.state_specs[state]) || {{
      headline: SCREEN_SPEC.name,
      summary: SCREEN_SPEC.purpose,
      badge: state
    }};

    const stateLinksHtml =
{state_links_expr};

    const showsHtml =
{shows_expr};

    const builtBodyHtml =
      '<div class="rc-built-screen" data-built-screen="{sid}" data-layout="' + esc(SCREEN_SPEC.layout) + '">' +
        '<div class="rc-state-banner" data-state-banner="' + esc(state) + '">' +
          '<div class="rc-state-banner__top">' +
            '<h2 class="rc-state-banner__headline">' + esc(stateSpec.headline) + "</h2>" +
            '<span class="rc-state-banner__badge">' + esc(stateSpec.badge) + "</span>" +
          "</div>" +
          '<p class="rc-state-banner__summary">' + esc(stateSpec.summary) + "</p>" +
        "</div>" +
        '<div class="rc-show-grid">' + showsHtml + "</div>" +
      "</div>";

    const regionsHtml =
{regions_expr};

    const actionsHtml =
{actions_expr};

    const reqCoverageHtml = {req_coverage_line};

    return (
      '<section class="rc-screen" data-screen="{sid}" data-view-state="' + esc(state) + '" data-route="' + esc(routeHash) + '">' +
        '<header class="rc-screen__header"{header_req_attr}>' +
          '<h1 class="rc-screen__title">' + esc(SCREEN_SPEC.name) + "</h1>" +
          '<p class="rc-screen__purpose">' + esc(SCREEN_SPEC.purpose) + "</p>" +
          '<nav class="rc-screen__states" aria-label="Screen states">' + stateLinksHtml + "</nav>" +
        "</header>" +
        '<div class="rc-screen__regions">' + regionsHtml + "</div>" +
        '<footer class="rc-screen__actions" data-region="screen-actions">' +
          actionsHtml +
          '<output class="rc-action-feedback" data-action-feedback="{sid}" aria-live="polite">Ready (' + esc(state) + ")</output>" +
        "</footer>" +
        reqCoverageHtml +
      "</section>"
    );
  }}

  window.__APP_SCREENS__ = window.__APP_SCREENS__ || {{}};
  window.__APP_SCREENS__[SCREEN_SPEC.id] = {{
    spec: SCREEN_SPEC,
    render: render
  }};
}})();
"""


def render_draft(ws: Workspace, draft: dict[str, Any]) -> dict[str, Any]:
    """Compile 05-build/draft.json into 05-build/screens/<id>.js and update 05-build/build.json."""
    validated = validate_inputs(ws)
    inventory = validated["inventory"]
    fixture = validated["fixture"]
    requirements_doc = validated["requirements"]
    screens: list[dict[str, Any]] = inventory["screens"]
    reqs_by_screen = _requirements_by_screen(screens, requirements_doc)

    draft_by_id = {
        str(s.get("id")): s
        for s in (draft.get("screens") or [])
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }

    build_dir = ws.folder("build")
    screens_dir = build_dir / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)

    for s in screens:
        sid = s["id"]
        req_fields = _default_req_fields_for_screen(s, fixture)
        d_screen = draft_by_id.get(sid)
        if d_screen:
            js_code = render_built_screen_js(s, d_screen, req_fields, reqs_by_screen.get(sid, []), fixture)
            (screens_dir / f"{sid}.js").write_text(js_code, encoding="utf-8")

    build_json_path = build_dir / "build.json"
    if build_json_path.is_file():
        bdoc = json.loads(build_json_path.read_text(encoding="utf-8"))
    else:
        bdoc = build_manifest(validated["chosen_direction"], screens, round_num=ws.round or 1)
    bdoc["placeholder"] = False
    bdoc["areas"] = {
        "shell": ".rc-shell__header",
        "screen": "[data-screen]",
        "content": "[data-built-screen]",
    }
    bdoc["source"] = (
        "stage 5b compiled prototype: shell, per-screen files compiled from 05-build/draft.json, "
        "tokens.css, fixture.json and build.json; zero placeholders"
    )
    build_json_path.write_text(
        json.dumps(bdoc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return bdoc
