"""The measured checks of a built prototype: measures in, rows out. No browser, no model, no files.

One rule per thing that can be wrong, each with the class 6b reads: blocker (a Must input: a failing WCAG
AA rule, overflow, a missing state, action or requirement, an invented figure, a render error) or should
(hierarchy and token drift). Every row says what was measured (value), where (screen, state, width,
element, location) and what proves it (evidence), so a reader can go to the screenshot and see it.

The thresholds are configs/design/bin/app_screen/checks_thresholds.json, frozen before the first trial:
this module never softens them, and a case that fails is a finding, not a reason to change a number.
"""
from __future__ import annotations

import bisect
import json
import math
import re
import sys
from pathlib import Path

DESIGN_BIN = Path(__file__).resolve().parent.parent
if str(DESIGN_BIN) not in sys.path:
    sys.path.insert(0, str(DESIGN_BIN))

from wcag_contrast import (  # noqa: E402, F401
    UI_EXEMPT_ROLES,
    check_text_contrast,
    check_ui_contrast,
    contrast_ratio,
    contrast_ratio_2dp,
    is_large_text,
    parse_color_rgb,
    relative_luminance,
    required_text_contrast,
)

BLOCKER = "blocker"
SHOULD = "should"

# rule id -> (check family, severity, what a failing row means)
RULES: dict[str, tuple[str, str, str]] = {
    "render.open": ("render", BLOCKER, "the view did not open"),
    "render.console": ("render", BLOCKER, "the page logged a console error"),
    "render.request": ("render", BLOCKER, "a request the page made failed"),
    "contract.marks": ("contract", BLOCKER, "no screen root carries data-screen"),
    "contract.screen": ("contract", BLOCKER, "the view's screen is not the visible screen"),
    "contract.state": ("contract", BLOCKER, "the view's state is not marked by data-view-state"),
    "contract.state_attr": ("contract", BLOCKER, "data-state or data-st-state below body hides the element in Show&Tell"),
    "coverage.view": ("coverage", BLOCKER, "an inventory screen and state has no view that opens"),
    "coverage.action": ("coverage", BLOCKER, "an inventory action has no data-action element"),
    "coverage.feedback": ("coverage", BLOCKER, "the action gave no visible answer to the click"),
    "coverage.requirement": ("coverage", BLOCKER, "a requirement mapped to this screen has no visible data-req element"),
    "overflow.layout_width": ("overflow", BLOCKER, "the layout is wider than the screen"),
    "overflow.horizontal": ("overflow", BLOCKER, "the page scrolls sideways"),
    "overflow.element": ("overflow", BLOCKER, "an element sticks out past the viewport"),
    "overflow.truncated": ("overflow", BLOCKER, "text is cut off"),
    # A split label still reads in full, so it is craft, not a blocker: only cut or clamped text blocks.
    "overflow.label": ("overflow", SHOULD, "a control's label splits although its row has room"),
    "type.floor": ("type", BLOCKER, "text below the readable floor"),
    "type.body": ("type", SHOULD, "body text below the product's body size"),
    "contrast.text": ("contrast", BLOCKER, "text contrast below WCAG 2.2 AA"),
    "contrast.ui": ("contrast", BLOCKER, "a field's boundary contrast below 3:1 (WCAG 1.4.11)"),
    "targets.size": ("targets", BLOCKER, "a target under 24x24 with no spacing (WCAG 2.5.8)"),
    "focus.ring": ("focus", BLOCKER, "a focusable stop with no visible focus (WCAG 2.4.11/2.4.7)"),
    "focus.none": ("focus", BLOCKER, "nothing takes focus on this screen"),
    "axe.violation": ("axe", BLOCKER, "axe-core found a WCAG 2.2 AA violation"),
    "hierarchy.sizes": ("hierarchy", SHOULD, "more text sizes in one view than the limit"),
    "hierarchy.levels": ("hierarchy", SHOULD, "more text contrast levels in one view than the limit"),
    "hierarchy.primary": ("hierarchy", SHOULD, "more than one solid primary in one view"),
    "tokens.colour": ("tokens", SHOULD, "a colour that is not in tokens.json"),
    "tokens.font": ("tokens", SHOULD, "a font family that is not in tokens.json"),
    "tokens.size": ("tokens", SHOULD, "a text size that is not in tokens.json"),
    "figures.invented": ("figures", BLOCKER, "a figure that is not in, or derived from, fixture.json"),
    "integration.duplicate_id": ("integration", BLOCKER, "the same element id twice (hash opening and labels break)"),
    "integration.dead_link": ("integration", BLOCKER, "a link to a view the build does not have"),
    "integration.two_screens": ("integration", BLOCKER, "two screens visible at once"),
    "integration.handler": ("integration", BLOCKER, "a data-action control the click could not reach"),
}
FAMILIES = ("render", "contract", "coverage", "overflow", "type", "contrast", "targets", "focus", "axe",
            "hierarchy", "tokens", "figures", "integration")
HASH_VIEW = re.compile(r"^#([A-Za-z0-9_.:-]+)/([A-Za-z0-9_.:-]+)$")


class Skipped(dict):
    """A check that could not run, with the reason; never silently a pass."""


def _row(rule: str, view: dict | None, value, evidence: str, element: str = "", location: str = "") -> dict:
    family, severity, _ = RULES[rule]
    where = location or (f"{view['screen']} / {view['state']} @ {view['width']}px" if view else "the round")
    return {"id": rule, "check": family, "severity": severity, "result": "fail",
            "screen": (view or {}).get("screen", ""), "state": (view or {}).get("state", ""),
            "width": (view or {}).get("width", 0), "value": value, "evidence": evidence[:400],
            "element": element[:200], "location": where}


# ---------------------------------------------------------------- figures: what the fixture says

def _numbers(node, out: list[float], depth: int = 0) -> None:
    if depth > 12 or len(out) > 4000:
        return
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        out.append(float(node))
    elif isinstance(node, str):
        for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", node):
            try:
                out.append(float(m.group(0).replace(",", "")))
            except ValueError:
                pass
    elif isinstance(node, list):
        for item in node:
            _numbers(item, out, depth + 1)
    elif isinstance(node, dict):
        for item in node.values():
            _numbers(item, out, depth + 1)


def _groups(node, out: list[list[float]], depth: int = 0) -> None:
    """Numbers that sit together: a list's items, an object's own numeric fields."""
    if depth > 12 or len(out) > 600:
        return
    if isinstance(node, list):
        same = [float(x) for x in node if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if len(same) > 1:
            out.append(same)
        for item in node:
            _groups(item, out, depth + 1)
    elif isinstance(node, dict):
        own = [float(v) for v in node.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(own) > 1:
            out.append(own)
        for item in node.values():
            _groups(item, out, depth + 1)


def fixture_values(fixture) -> list[float]:
    """Every number the fixture states, plus the ones a screen may show instead: a list's total, a
    difference or a share of two numbers that sit together, and the percent form of a fraction."""
    direct: list[float] = []
    _numbers(fixture, direct)
    values = {0.0, 1.0, 100.0}
    for v in direct:
        values.add(v)
        values.add(abs(v))
        values.add(round(v * 100, 6))                      # a fraction shown as a percent
    groups: list[list[float]] = []
    _groups(fixture, groups)
    for group in groups[:600]:
        values.add(round(math.fsum(group), 6))
        if len(group) <= 24:
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    values.add(round(abs(a - b), 6))
                    values.add(round(a + b, 6))
                    if b:
                        values.add(round(abs(a / b) * 100, 6))
                        values.add(round(abs(a - b) / abs(b) * 100, 6))
                    if a:
                        values.add(round(abs(b / a) * 100, 6))
    return sorted(values)


def _known(value: float, values: list[float], tol: float) -> bool:
    i = bisect.bisect_left(values, value - tol)
    return i < len(values) and values[i] <= value + tol


def figure_matches(figure: dict, values: list[float]) -> bool:
    """Is the figure a number the fixture states (or an obvious form of one)?"""
    raw = (figure.get("raw") or "").replace(",", "")
    try:
        shown = float(raw)
    except ValueError:
        return True                                        # unreadable: not evidence of invention
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    tol = 0.5 * 10 ** -decimals + 1e-9
    forms = [(shown, tol)]
    suffix = (figure.get("suffix") or "").lower()
    if suffix == "k":
        forms.append((shown * 1_000, tol * 1_000))
    if suffix == "m":
        forms.append((shown * 1_000_000, tol * 1_000_000))
    if figure.get("kind") == "percent":
        forms.append((shown / 100, tol / 100))
    return any(_known(v, values, t) for v, t in forms)


# ---------------------------------------------------------------- tokens: what the design files allow

def token_sets(tokens: dict | None) -> dict:
    """The colours (as #RRGGBB), font families and text sizes (px) tokens.json allows."""
    if str(DESIGN_BIN) not in sys.path:
        sys.path.insert(0, str(DESIGN_BIN))
    import design_files  # noqa: PLC0415 - shared with the ground stage

    if not tokens:
        return {"colours": set(), "fonts": set(), "sizes": set()}
    sizes = set()

    def as_px(value) -> float | None:
        """A dimension in either form: DTCG's {value, unit} or the shorthand "16px" / "1rem"."""
        if isinstance(value, dict) and "value" in value:
            try:
                return round(float(value["value"]) * (16 if value.get("unit") == "rem" else 1), 2)
            except (TypeError, ValueError):
                return None
        m = re.match(r"^(\d+(?:\.\d+)?)(px|rem)$", str(value).strip()) if value is not None else None
        return round(float(m.group(1)) * (16 if m.group(2) == "rem" else 1), 2) if m else None

    for _path, kind, value in design_files.token_list({"type": tokens.get("type") or {}}):
        value = design_files.resolve(tokens, value)
        if kind == "dimension":
            px = as_px(value)
            if px is not None:
                sizes.add(px)
        if kind == "typography" and isinstance(value, dict):
            px = as_px(design_files.resolve(tokens, value.get("fontSize")))
            if px is not None:
                sizes.add(px)
    return {"colours": {h.upper() for h in design_files.token_hexes(tokens)},
            "fonts": {f.strip().lower() for f in design_files.token_fonts(tokens)},
            "sizes": sizes}


def _hex(rgb: str) -> str:
    m = re.match(r"rgb\((\d+),(\d+),(\d+)\)", (rgb or "").replace(" ", ""))
    return "#{:02X}{:02X}{:02X}".format(*(int(m.group(i)) for i in (1, 2, 3))) if m else ""


# ---------------------------------------------------------------- the rules

def _has_words(text: str | None) -> bool:
    """True when the run carries something to read: a letter or a digit, not only symbols."""
    return any(ch.isalnum() for ch in (text or ""))


def _view_rows(view: dict, m: dict, ctx: dict, th: dict) -> list[dict]:
    rows: list[dict] = []
    add = rows.append
    cap = th["limits"]["rows_per_check_per_view"]
    dm, mp, cm = m.get("dm") or {}, m.get("mp") or {}, m.get("cm") or {}
    shot = m.get("capture", "")
    place = f"{view['screen']} / {view['state']} @ {view['width']}px" + (f" ({shot})" if shot else "")

    # --- render
    if not m.get("opened"):
        add(_row("render.open", view, "not opened", m.get("why") or "the browser could not open the view",
                 location=place))
        return rows
    for line in (m.get("console") or [])[:cap]:
        add(_row("render.console", view, line[:120], f"console error: {line}", location=place))
    for line in (m.get("failed_requests") or [])[:cap]:
        add(_row("render.request", view, line[:120], f"request failed: {line}", location=place))

    # --- the contract's marks
    contract = cm.get("contract") or {}
    if ctx["marked"]:
        shown = contract.get("shown") or []
        if view["screen"] not in shown:
            add(_row("contract.screen", view, ", ".join(shown[:6]) or "no screen visible",
                     f"opening {view['open']} shows {', '.join(shown[:6]) or 'no screen'}, not {view['screen']}",
                     element=f"[data-screen={view['screen']}]", location=place))
        states = contract.get("states") or []
        if view["state"] not in states:
            add(_row("contract.state", view, ", ".join(states[:6]) or "no state mark",
                     f"the open view marks {', '.join(states[:6]) or 'no state'}, not {view['state']}",
                     element="[data-view-state]", location=place))
    for bad in (contract.get("banned_state_attr") or [])[:cap]:
        add(_row("contract.state_attr", view, bad["attr"],
                 f"{bad['attr']} below body: the Show&Tell helper hides it", element=bad["sel"], location=place))

    # --- overflow and reflow
    vp = (mp.get("viewport") or {}).get("w") or (dm.get("viewport") or [0])[0]
    if vp and vp > view["width"] + th["overflow"]["slack_px"]:
        add(_row("overflow.layout_width", view, vp,
                 f"the layout viewport is {vp}px on a {view['width']}px screen", location=place))
    if mp.get("horizontalScroll") or (dm.get("page_width") or {}).get("overflows"):
        width = mp.get("horizontalScroll") or (dm.get("page_width") or {}).get("scroll")
        add(_row("overflow.horizontal", view, width,
                 f"the page scrolls sideways: {width}px wide in {view['width']}px", location=place))
    for el in (dm.get("overflowing") or [])[:cap]:
        add(_row("overflow.element", view, el.get("box"), f"sticks out past {view['width']}px",
                 element=el.get("sel", ""), location=place))
    for el in ((mp.get("overflow") or {}).get("outside") or [])[:cap]:
        add(_row("overflow.element", view, el.get("right"),
                 f"right edge {el.get('right')}px past {view['width']}px: \"{el.get('text', '')}\"",
                 element=el.get("cls", ""), location=place))
    for el in ((mp.get("truncated") or {}).get("items") or [])[:cap]:
        add(_row("overflow.truncated", view, f"{el.get('shown')} of {el.get('needs')}px",
                 f"{el.get('how')} cuts \"{el.get('text', '')}\"", element=el.get("cls", ""), location=place))
    for el in (cm.get("wrapped_labels") or [])[:cap]:
        add(_row("overflow.label", view, {"lines": el.get("lines"), "width": el.get("width"),
                                          "needed": el.get("needed"), "free": el.get("free")},
                 f"the label \"{el.get('text', '')}\" splits onto {el.get('lines')} lines in a "
                 f"{el.get('width')}px control, though its row has {el.get('free')}px to spare and the "
                 f"label needs {el.get('needed')}px",
                 element=el.get("sel", ""), location=place))

    # --- type
    seen_size = set()
    for run in ((mp.get("type") or {}).get("smallest") or []):
        key = (run.get("size"), run.get("cls"))
        if not _has_words(run.get("text")):      # a row of dots or arrows is decoration, not text to read
            continue
        if run.get("size") is not None and run["size"] < th["type"]["floor_px"] and key not in seen_size:
            seen_size.add(key)
            add(_row("type.floor", view, run["size"],
                     f"{run['size']}px text (floor {th['type']['floor_px']}px): \"{run.get('text', '')}\"",
                     element=run.get("cls", ""), location=place))
    body_small = (mp.get("type") or {}).get("bodyLikeUnder16")
    if body_small:
        example = next((r for r in (mp.get("runs") or []) if (r.get("size") or 99) < th["type"]["body_px"]
                        and len(r.get("text") or "") >= th["type"]["body_run_chars"]), {})
        add(_row("type.body", view, body_small,
                 f"{body_small} sentence-length run(s) below {th['type']['body_px']}px, e.g. "
                 f"{example.get('size')}px \"{(example.get('text') or '')[:60]}\"", location=place))

    # --- contrast (WCAG 2.2 AA), from design_measure.js / shared wcag_contrast formula
    for t in (dm.get("contrast_failures") or [])[:cap]:
        fg_c, bg_c = t.get("color"), t.get("background")
        size_px = t.get("size") if t.get("size") is not None else 16
        weight_num = t.get("weight") if t.get("weight") is not None else 400
        ratio_val = t.get("contrast")
        need_val = t.get("needs")
        if (ratio_val is None or need_val is None) and fg_c and bg_c:
            calc_ratio, calc_need, passed = check_text_contrast(
                fg_c, bg_c, size_px=size_px, weight=weight_num, thresholds=th
            )
            if ratio_val is None:
                ratio_val = calc_ratio
            if need_val is None:
                need_val = calc_need
            if passed and t.get("contrast") is None:
                continue
        add(_row("contrast.text", view, ratio_val,
                 f"{ratio_val}:1 needs {need_val}:1 ({t.get('size')}px {t.get('weight')}, "
                 f"{fg_c} on {bg_c}): \"{t.get('text', '')}\"",
                 element=t.get("sel", ""), location=place))
    for b in (dm.get("weak_boundaries") or [])[:cap]:
        fg_c, bg_c = b.get("color"), b.get("background")
        b_ratio = b.get("boundary_contrast")
        if b_ratio is None and fg_c and bg_c:
            b_ratio, _b_need, b_passed = check_ui_contrast(
                fg_c, bg_c, role=str(b.get("role") or "border"), thresholds=th
            )
            if b_passed:
                continue
        add(_row("contrast.ui", view, b_ratio,
                 f"the field \"{b.get('name', '')}\" has a {b_ratio}:1 boundary "
                 f"(needs {th['contrast']['ui']}:1)", element=b.get("sel", ""), location=place))

    # --- targets
    for t in (dm.get("small_targets") or [])[:cap]:
        box = t.get("box") or [0, 0, 0, 0]
        # the measure says which way the spacing exception fails: "target" = the 24px circle reaches the
        # neighbour itself, "circle" = the two centres are under 24px apart
        neighbour = t.get("too_close_to") or {}
        near, edge = neighbour.get("name") or "", neighbour.get("edge")
        why = {"target": "its 24px circle reaches",
               "circle": "its centre is under 24px from"}.get(t.get("hit"), "it sits beside")
        gap = f", {edge}px away" if isinstance(edge, (int, float)) else ""
        add(_row("targets.size", view, f"{box[2]}x{box[3]}",
                 f"\"{t.get('name', '')}\" is {box[2]}x{box[3]}px (needs {th['targets']['min_px']}px or "
                 f"spacing" + (f"; {why} \"{near}\"{gap})" if near else ")"),
                 element=t.get("sel", ""), location=place))

    # --- focus (the Tab walk runs once per screen and state, at its widest width)
    if view.get("walk"):
        stops = m.get("tab_stops")
        if stops is not None:
            controls = len(dm.get("controls") or [])
            if not stops and controls:
                add(_row("focus.none", view, f"{controls} control(s)",
                         "Tab reached no control on this screen", location=place))
            for stop in [s for s in stops if not s.get("ring")][:cap]:
                add(_row("focus.ring", view, stop.get("outline", ""),
                         f"\"{stop.get('name', '')}\" takes focus with no visible ring "
                         f"(outline {stop.get('outline')}, shadow {stop.get('box_shadow')})",
                         element=stop.get("sel", ""), location=place))

    # --- axe
    for v in (m.get("axe") or [])[:cap]:
        for node in (v.get("nodes") or [])[:3]:
            add(_row("axe.violation", view, v.get("id"),
                     f"{v.get('id')} ({', '.join(v.get('wcag') or [])}): {v.get('help', '')}: "
                     f"{(node.get('summary') or '').splitlines()[0] if node.get('summary') else ''}",
                     element=node.get("target", ""), location=place))

    # --- hierarchy (Should)
    sizes = cm.get("hierarchy", {}).get("text_sizes") or []
    if len(sizes) > th["hierarchy"]["max_text_sizes"]:
        shown = ", ".join(f"{s}px" for s in sizes[:8])
        add(_row("hierarchy.sizes", view, len(sizes),
                 f"{len(sizes)} text sizes in one view (limit {th['hierarchy']['max_text_sizes']}): {shown}",
                 location=place))
    levels = cm.get("hierarchy", {}).get("text_levels") or []
    if len(levels) > th["hierarchy"]["max_contrast_levels"]:
        shown = ", ".join(f"{lv['level']} x{lv['runs']} ({', '.join(lv.get('colours') or [])})"
                          for lv in levels[:6])
        add(_row("hierarchy.levels", view, len(levels),
                 f"{len(levels)} text contrast levels in one view "
                 f"(limit {th['hierarchy']['max_contrast_levels']}): {shown}", location=place))
    fills = cm.get("solid_fills") or []
    if len(fills) > th["hierarchy"]["primary_per_view"]:
        shown = "; ".join(f"{f['colour']} ({f['label'] or f['sel']})" for f in fills[:4])
        add(_row("hierarchy.primary", view, len(fills),
                 f"{len(fills)} solid fills compete as the primary: {shown}",
                 element=fills[1]["sel"] if len(fills) > 1 else "", location=place))

    # --- tokens (only when the product's design files are defined)
    if ctx.get("tokens"):
        allow = ctx["token_sets"]
        for used in (cm.get("used", {}).get("colours") or [])[:60]:
            h = _hex(used["value"])
            if h and h not in allow["colours"]:
                add(_row("tokens.colour", view, h, f"{h} is not in tokens.json (used {used['count']}x)",
                         element=used.get("sel", ""), location=place))
        for used in (cm.get("used", {}).get("fonts") or [])[:20]:
            if used["value"].strip().lower() not in allow["fonts"]:
                add(_row("tokens.font", view, used["value"],
                         f"{used['value']} is not a tokens.json font family", element=used.get("sel", ""),
                         location=place))
        for used in (cm.get("used", {}).get("sizes") or [])[:40]:
            try:
                px = round(float(used["value"]), 2)
            except ValueError:
                continue
            if allow["sizes"] and px not in allow["sizes"]:
                add(_row("tokens.size", view, f"{px}px", f"{px}px is not a tokens.json text size",
                         element=used.get("sel", ""), location=place))

    # --- figures
    if ctx.get("figure_values"):
        seen_fig = set()
        for fig in (cm.get("figures") or []):
            if figure_matches(fig, ctx["figure_values"]):
                continue
            key = (fig.get("token"), fig.get("sel"))
            if key in seen_fig:
                continue
            seen_fig.add(key)
            add(_row("figures.invented", view, fig.get("token"),
                     f"{fig.get('token')} is not in fixture.json: \"{(fig.get('context') or '')[:70]}\"",
                     element=fig.get("sel", ""), location=place))

    # --- integration
    for dup in (cm.get("duplicate_ids") or [])[:cap]:
        add(_row("integration.duplicate_id", view, dup.get("id"),
                 f"id {dup.get('id')} is on {dup.get('count')} elements", element=dup.get("sel", ""),
                 location=place))
    for link in (cm.get("dead_links") or [])[:cap]:
        if link.get("href") not in ctx["known_hashes"]:
            add(_row("integration.dead_link", view, link.get("href"),
                     f"\"{link.get('text', '')}\" opens {link.get('href')}, which is not a view of this build",
                     element=link.get("sel", ""), location=place))
    if ctx["marked"]:
        shown = contract.get("shown") or []
        if len(shown) > 1:
            add(_row("integration.two_screens", view, ", ".join(shown[:6]),
                     f"{len(shown)} screens are visible at once: {', '.join(shown[:6])}", location=place))
    for fb in (m.get("action_feedback") or []):
        if not fb.get("clicked"):
            add(_row("integration.handler", view, fb.get("action"),
                     f"the control for {fb.get('action')} could not be clicked: "
                     f"{fb.get('why') or 'the browser gave no reason'}",
                     element=fb.get("sel", ""), location=place))
        elif not fb.get("feedback") and not fb.get("already_on"):
            # A control the view already shows as the chosen one (aria-pressed, aria-current, .active)
            # has answered the click before it: nothing more should change.
            add(_row("coverage.feedback", view, fb.get("action"),
                     f"clicking \"{fb.get('label') or fb.get('action')}\" changed nothing visible "
                     "(no pressed, busy or loading state)", element=fb.get("sel", ""), location=place))
    return rows


# ---------------------------------------------------------------- coverage over the whole round

def _coverage_rows(plan: dict, measured: dict, ctx: dict) -> list[dict]:
    rows: list[dict] = []
    inventory = ctx["inventory"]
    if not inventory:
        return rows
    opened = {}
    for view in plan["views"]:
        m = measured.get(view["id"]) or {}
        cm = m.get("cm") or {}
        shown = (cm.get("contract") or {}).get("shown") or []
        states = (cm.get("contract") or {}).get("states") or []
        ok = bool(m.get("opened")) and (not ctx["marked"] or (view["screen"] in shown and view["state"] in states))
        opened.setdefault((view["screen"], view["state"]), []).append((view, ok))

    for screen in inventory:
        for state in screen.get("states") or []:
            seen = opened.get((screen["id"], state))
            if not seen:
                rows.append(_row("coverage.view", None, "no view",
                                 f"{screen['id']} / {state} is in 03-ground/inventory.json and the build opens no "
                                 "view for it", element=f"#{screen['id']}/{state}",
                                 location=f"{screen['id']} / {state}"))
            elif not any(ok for _v, ok in seen):
                view = seen[0][0]
                rows.append(_row("coverage.view", view, "did not open",
                                 f"{screen['id']} / {state} did not open at any width "
                                 f"({', '.join(str(v['width']) for v, _ in seen)})",
                                 element=str(view["open"]), location=f"{screen['id']} / {state}"))

    if not ctx["marked"]:
        return rows
    # actions and requirements: a screen's views together, per width
    for screen in inventory:
        views = [v for v in plan["views"] if v["screen"] == screen["id"]]
        if not views:
            continue
        found_actions: set[str] = set()
        reqs_by_width: dict[int, set[str]] = {}
        for view in views:
            cm = (measured.get(view["id"]) or {}).get("cm") or {}
            found_actions |= {a["action"] for a in (cm.get("actions") or []) if a.get("visible")}
            got = reqs_by_width.setdefault(view["width"], set())
            got |= {rid for rid, rec in (cm.get("reqs") or {}).items() if rec.get("visible")}
        for action in screen.get("actions") or []:
            if action["id"] not in found_actions:
                rows.append(_row("coverage.action", None, "missing",
                                 f"the inventory's action {action['id']} ({action.get('what', '')[:60]}) has no "
                                 "visible [data-action] element on this screen",
                                 element=f"[data-action={action['id']}]", location=screen["id"]))
        wanted = ctx["reqs_by_screen"].get(screen["id"], set())
        for width in sorted(reqs_by_width):
            for rid in sorted(wanted - reqs_by_width[width]):
                rows.append(_row("coverage.requirement", None, "missing",
                                 f"requirement {rid} ({ctx['req_text'].get(rid, '')[:60]}) has no visible "
                                 f"[data-req] element on {screen['id']} at {width}px",
                                 element=f"[data-req~={rid}]", location=f"{screen['id']} @ {width}px"))
    return rows


# ---------------------------------------------------------------- the round

def context(plan: dict, inventory: list[dict], requirements: list[dict], fixture, tokens,
            design_files_status: str, measured: dict) -> dict:
    """What the rules need besides the measures: the inventory, the fixture's numbers, the tokens."""
    reqs_by_screen: dict[str, set[str]] = {}
    for screen in inventory:
        ids = set()
        for source in (screen.get("sources") or []):
            if str(source).startswith("req:"):
                ids.add(str(source)[4:])
        for action in screen.get("actions") or []:
            for source in (action.get("sources") or []):
                if str(source).startswith("req:"):
                    ids.add(str(source)[4:])
        if ids:
            reqs_by_screen[screen["id"]] = ids
    known = {f"#{v['screen']}/{v['state']}" for v in plan["views"]}
    for screen in inventory:
        for state in screen.get("states") or []:
            known.add(f"#{screen['id']}/{state}")
    marked = any(((measured.get(v["id"]) or {}).get("cm") or {}).get("contract", {}).get("marked")
                 for v in plan["views"])
    return {"inventory": inventory, "marked": marked,
            "reqs_by_screen": reqs_by_screen,
            "req_text": {r["id"]: (r.get("means") or r.get("owner_words") or r.get("text") or "")
                         for r in requirements},
            "figure_values": fixture_values(fixture) if fixture is not None else [],
            "tokens": tokens if design_files_status == "defined" else None,
            "token_sets": token_sets(tokens) if design_files_status == "defined" else None,
            "known_hashes": known, "design_files": design_files_status}


def evaluate(plan: dict, measured: dict, ctx: dict, thresholds: dict) -> dict:
    """Every row the measures justify, the summary row per check, and the round's verdict."""
    rows: list[dict] = []
    if not ctx["marked"]:
        rows.append(_row("contract.marks", None, "no data-screen",
                         "no view carries a data-screen root, so the screen, state, action and requirement "
                         "checks cannot be read (docs/design-app-screen.md, 'Prototype contract')",
                         element="[data-screen]"))
    for view in plan["views"]:
        rows += _view_rows(view, measured.get(view["id"]) or {}, ctx, thresholds)
    rows += _coverage_rows(plan, measured, ctx)

    rows.sort(key=lambda r: (r["check"], r["id"], r["screen"], r["state"], r["width"], r["element"],
                             r["evidence"]))
    kept, counted = [], {}
    cap = thresholds["limits"].get("rows_per_check", 300)
    capped = set()
    for row in rows:
        n = counted.get(row["check"], 0)
        if n >= cap:
            capped.add(row["check"])
            continue
        counted[row["check"]] = n + 1
        kept.append(row)

    skipped = {}
    if not ctx["marked"]:
        skipped["coverage"] = ("the build carries no data-screen marks, so screens, states, actions and "
                               "requirements could not be matched (contract.marks)")
    if ctx["design_files"] != "defined":
        skipped["tokens"] = f"the product's design files are {ctx['design_files']}, so there are no tokens to hold to"
    if not ctx["figure_values"]:
        skipped["figures"] = "the run has no 03-ground/fixture.json, so no figure could be looked up"

    summary = []
    for family in FAMILIES:
        fails = [r for r in kept if r["check"] == family]
        severity = BLOCKER if any(r["severity"] == BLOCKER for r in fails) else (
            SHOULD if fails else next(s for (f, s, _) in RULES.values() if f == family))
        entry = {"id": family, "check": family, "severity": severity,
                 "result": "fail" if fails else ("skipped" if family in skipped else "pass"),
                 "value": {"failures": len(fails), "views": len(plan["views"]),
                           "screens": len({r["screen"] for r in fails if r["screen"]})},
                 "evidence": (f"{len(fails)} failing row(s) over {len(plan['views'])} view(s)" if fails
                              else f"no failure over {len(plan['views'])} view(s)")
                 + (f"; part of this check did not run: {skipped[family]}" if family in skipped else ""),
                 "element": "", "location": "round"}
        if family in capped:
            entry["evidence"] += f"; rows capped at {cap}"
        summary.append(entry)

    blockers = [r for r in kept if r["severity"] == BLOCKER]
    return {"rows": kept, "summary": summary,
            "totals": {"views": len(plan["views"]), "rows": len(kept), "blockers": len(blockers),
                       "shoulds": len(kept) - len(blockers),
                       "checks_failed": sorted({r["check"] for r in kept}),
                       "checks_skipped": sorted(skipped)},
            "verdict": "fail" if blockers else "pass"}


def load_thresholds(path: Path | str | None = None) -> dict:
    return json.loads(Path(path or (Path(__file__).resolve().parent / "checks_thresholds.json")).read_text())
