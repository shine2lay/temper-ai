"""Stage 2's measures: one capture's in-page measurement -> the audit's measures, and which values show a problem.

measures() turns measure_in_page.js's result into flat measures (numbers, strings, lists of strings) whose keys
the audit, the model and the checks share; generalized from Design #170's build_measurements.py (left as it was).
PROBLEM_WHEN says, for each measure that can show a problem, on which side of its line a value is a problem;
shows_problem() applies it. totals() counts per width how many captures each rule flags. Model-free.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

# measure key -> (rule in words, test(value, capture) -> True when the value shows a problem)
Rule = tuple[str, Callable[[Any, dict], bool]]


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


PROBLEM_WHEN: dict[str, Rule] = {
    "wider_than_screen_px": ("above 0: the page is wider than the screen", lambda v, c: _num(v) and v > 0),
    "layout_width_px": ("above the capture width", lambda v, c: _num(v) and v > c["width"]),
    "text_runs_under_12px": ("above 0", lambda v, c: _num(v) and v > 0),
    "body_text_runs_under_16px": ("above 0: sentence-length text in main under 16 px", lambda v, c: _num(v) and v > 0),
    "smallest_text_px": ("under 12", lambda v, c: _num(v) and v < 12),
    "distinct_text_sizes": ("above 5", lambda v, c: _num(v) and v > 5),
    "targets_under_24px": ("above 0: tap targets under 24x24 px, inline links excluded",
                           lambda v, c: _num(v) and v > 0),
    "truncated_count": ("above 0: text cut by ellipsis, clamp or clipping", lambda v, c: _num(v) and v > 0),
    "truncated_text": ("not empty", lambda v, c: isinstance(v, list) and len(v) > 0),
    "side_scrolling_boxes": ("not empty: boxes that scroll sideways", lambda v, c: isinstance(v, list) and len(v) > 0),
    "side_scroll_content_px": ("above side_scroll_visible_px", lambda v, c: _num(v) and v > 0),
    "screens_tall": ("4 or more screens", lambda v, c: _num(v) and v >= 4),
    "content_px_in_first_view": ("under half the screen height", lambda v, c: _num(v) and v < c["height"] / 2),
    "tabbar_rows": ("above 1", lambda v, c: _num(v) and v > 1),
    "always_open_blocks": ("above 5: open blocks over 40 px tall in main", lambda v, c: _num(v) and v > 5),
    "error_messages_without_action": ("above 0: an error with no button or link beside it",
                                      lambda v, c: _num(v) and v > 0),
    "page_errors": ("above 0: script errors on the page", lambda v, c: _num(v) and v > 0),
}
REGION_RULE: Rule = ("1 or more: the region starts below the first screen", lambda v, c: _num(v) and v >= 1)


def rule(key: str) -> Rule | None:
    if key in PROBLEM_WHEN:
        return PROBLEM_WHEN[key]
    if key.endswith("_screens_down"):
        return REGION_RULE
    return None


def shows_problem(key: str, value: Any, capture: dict) -> bool | None:
    """True/False when the measure has a rule, None when it is context only (no problem side)."""
    r = rule(key)
    if r is None or value is None:
        return None
    return bool(r[1](value, capture))


def measures(raw: dict[str, Any], width: int) -> dict[str, Any]:
    """Flat measures of one capture (keys as Design #170's measurements.json rows, plus side-scroll widths,
    key regions and error messages)."""
    vh = raw["viewport"]["h"]
    t = raw["type"]
    side = raw["overflow"]["sideScrollers"]
    in_main = [s for s in side if s.get("area") == "main"]
    widest = max(in_main or side, key=lambda s: s["scrollW"], default=None)
    errors = raw.get("errors") or []
    out: dict[str, Any] = {
        "layout_width_px": raw["viewport"]["w"],
        "wider_than_screen_px": max(0, raw["viewport"]["w"] - width),
        "page_height_px": raw["pageHeight"],
        "screens_tall": raw["screensTall"],
        "tabbar_px": raw["chrome"]["tabbar"],
        "tabbar_rows": raw["chrome"]["tabbarRows"],
        "content_px_in_first_view": raw["chrome"]["contentLeftInFirstView"],
        "text_runs": t["total"],
        "text_runs_under_12px": t["under12"],
        "text_runs_under_16px": t["under16"],
        "body_text_runs": t["bodyLikeRuns"],
        "body_text_runs_under_16px": t["bodyLikeUnder16"],
        "distinct_text_sizes": t["distinctSizes"],
        "smallest_text_px": t["smallestPx"],
        "targets_under_24px": raw["targets"]["under24NotInline"],
        "side_scrolling_boxes": [f'{s["cls"].strip()} ({s.get("area", "?")}): {s["scrollW"]} px of content '
                                 f'in a {s["clientW"]} px box' for s in side],
        "side_scroll_content_px": widest["scrollW"] if widest else 0,
        "side_scroll_visible_px": widest["clientW"] if widest else 0,
        "truncated_count": raw["truncated"]["count"],
        "truncated_text": [f'{i["cls"].strip()}: {i.get("how", "cut")}, shows {i["shown"]} of {i["needs"]} px'
                           f'{" in height" if i.get("axis") == "height" else ""} ("{i["text"][:40]}")'
                           for i in raw["truncated"]["items"]][:5],
        "always_open_blocks": raw["blocks"]["alwaysOpen"],
        "error_messages": len(errors),
        "error_messages_without_action": sum(1 for e in errors if not e["actions"]),
        "page_errors": len(raw.get("pageErrors") or []),
    }
    for name, region in (raw.get("keyRegions") or {}).items():
        out[f"{name}_top_px"] = region["top"] if region else None
        out[f"{name}_screens_down"] = round(region["top"] / vh, 1) if region else None
    return out


def text_runs(raw: dict[str, Any]) -> list[str]:
    """The capture's visible text, one run each, in page order, duplicates dropped."""
    seen: dict[str, None] = {}
    for r in raw.get("runs") or []:
        seen.setdefault(r["text"], None)
    return list(seen)


def first_view_text(raw: dict[str, Any]) -> list[str]:
    seen: dict[str, None] = {}
    for r in raw.get("runs") or []:
        if r.get("first"):
            seen.setdefault(r["text"], None)
    return list(seen)


def totals(screens: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Per width, how many captures each rule flags: "<measure>@<width>" -> {value, of}."""
    out: dict[str, dict[str, int]] = {}
    for width in sorted({s["width"] for s in screens}):
        group = [s for s in screens if s["width"] == width]
        keys = sorted({k for s in group for k in s["measures"] if rule(k)})
        for key in keys:
            flagged = sum(1 for s in group if shows_problem(key, s["measures"].get(key), s))
            out[f"{key}@{width}"] = {"value": flagged, "of": len(group)}
    return out


NOTES = {
    "layout_width_px": "window.innerWidth after load; above the capture width means the page is wider than the phone, "
                       "so it zooms out or slides sideways",
    "targets_under_24px": "tappable elements under 24x24 px, inline text links excluded (WCAG 2.2 2.5.8)",
    "text_runs_under_16px": "visible text runs whose computed font-size is under 16 px (whole page)",
    "body_text_runs_under_16px": "sentence-length runs (40+ characters) in main under 16 px, of body_text_runs",
    "<region>_screens_down": "a key region's distance from the page top, in screen heights (key regions: app file)",
    "side_scroll_content_px": "the widest sideways-scrolling box in main (else anywhere): its content width; "
                              "side_scroll_visible_px its box; side_scrolling_boxes lists every one with its area",
    "error_messages_without_action": "error messages (page.error_selector) with no button or link in their parent",
    "totals": "per width, how many captures each rule flags (problem side in existing_measures.PROBLEM_WHEN)",
}
