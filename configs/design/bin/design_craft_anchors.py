#!/usr/bin/env python3
"""Measured craft numbers in a homepage review folder become craft findings at fixed levels, by script (H6, W4c).

The measure stage (design_homepage_v2.write_review_inputs) writes review/craft-metrics.json: for each
width (1440 and 390) the rendered page's text sizes, scale ratio, spacing, font loading and more, which
it also prints in review/craft-facts.md for the craft critic (design_homepage_craft_critic_v2.yaml).
The critic's prompt sets a fixed level for some of those numbers (its SEVERITY ANCHORS); a model
applying them itself can give the same number a different finding or level from run to run. This
script applies those anchors as code, so a measured craft problem gets the same finding and level
every time, and the critic is left to judge what no number settles.

Output: review/craft/anchors.json, {"version", "page", "widths", "counts", "checks", "findings"}.
checks: every rule below with its number at each width and the level that number gives (0: it sets
no level; null: not measured). Each finding: id, page, width (the width whose number sets the
level), viewport (desktop, mobile, or all when the number crosses a line at both widths), element,
check (the critic's check: space, scale or type), metric (the craft-metrics.json key), value (its
number at that width), threshold (the band the value falls in, in the prompt's words), level (2 or
3), rule (a key of RULES) and evidence (the numbers at every width). counts has the critic's
severity_counts form. The same review folder always gives byte-identical output.

RULES below is the rules table: each rule quotes the prompt lines it comes from (the quote is
checked against the prompt by tests/test_design_craft_anchors.py) and says what the script does
with it. Every band is an exact line on a number, so the script never has to choose between two
levels. Left to the critic: the anchors the prompt sets on facts.md (an empty column) and on visual
purpose, which are not craft-metrics.json numbers, and the numbers it measures but gives no level
(back-to-back section repeats, animated elements, line length). Nothing here names a plant, its page
or its level.

Usage: design_craft_anchors.py REVIEW_DIR [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

VERSION = 1
CRAFT = "configs/design/agents/design_homepage_craft_critic_v2.yaml"
PAGE = "index.html"  # craft_metrics (design_homepage_v2.py) measures the homepage, index.html, only
VIEWPORTS = {1440: "desktop", 390: "mobile"}  # craft_metrics' widths, named as the critic names them

# The rules table. cites: (file, first line, last line) holding `says`, word for word apart from line
# breaks, indentation and a list item's leading dash; parts of `says` are joined with " | ".
# script: what the code below does with it.
RULES: dict[str, dict] = {
    "worse-width": {
        "cites": [(CRAFT, 102, 104)],
        "says": "Report a problem at most once; group repeats. | SEVERITY ANCHORS. Where a measured number in "
        "craft-facts.md or facts.md sets the level, use it (at the worse of the two widths):",
        "script": "each rule below reads its number at every width in craft-metrics.json and gives at most one "
        "finding: the highest level any width reaches, with the worse number as its value and that width as its "
        "width (equal numbers: the wider width). viewport is all when the number crosses a line at every width.",
    },
    "spacing-grid": {
        "cites": [(CRAFT, 105, 107)],
        "says": "spacing share on a 4 px grid below 0.6: most spacing sits off any scale and the rhythm drifts "
        "visibly: 3 (space). From 0.6 to below 0.9: 2. From 0.9 up, don't report off-scale spacing from the "
        "number alone.",
        "script": "spacing_on_4px (craft-facts.md's share on a 4 px grid) below 0.6 is 3; from 0.6 to below 0.9 "
        "is 2; from 0.9 up, no finding.",
        "check": "space",
        "metric": "spacing_on_4px",
        "worse": "low",
        "element": "spacing across the whole page: margins, padding and the gaps between and inside sections",
    },
    "scale-ratio": {
        "cites": [(CRAFT, 108, 108)],
        "says": "scale ratio below 2x: the headline has no clear lead over body text: 3 (scale).",
        "script": "scale_ratio (largest text over body text) below 2 is 3; from 2 up the prompt sets no level, "
        "so no finding.",
        "check": "scale",
        "metric": "scale_ratio",
        "worse": "low",
        "element": "the largest text, the headline, against the body text",
    },
    "text-sizes": {
        "cites": [(CRAFT, 109, 110)],
        "says": "more than 8 distinct text sizes in one view: the type has no system: 3 (type); 7 or 8: 2.",
        "script": "text_sizes (distinct rounded px sizes of visible text at that width) above 8 is 3; 7 or 8 is "
        "2; 6 or fewer, no finding.",
        "check": "type",
        "metric": "text_sizes",
        "worse": "high",
        "element": "text sizes across the whole page",
    },
    "font-loading": {
        "cites": [(CRAFT, 110, 110)],
        "says": "A font family that failed to load: 3 (type).",
        "script": "unloaded_families not empty at a width is 3; one finding names every family that failed at "
        "any width (a problem is reported once).",
        "check": "type",
        "metric": "unloaded_families",
        "worse": "high",
        "element": "text set in a font family that failed to load",
    },
}
ANCHORS = [name for name, rule in RULES.items() if "metric" in rule]

# Items of the prompt's SEVERITY ANCHORS list that no rule above applies, by how the item begins, and why
# the critic keeps them. Every item of that list is either cited by a rule or named here (the tests check).
LEFT = {
    "an empty column measured by facts.md": "a facts.md page check, not a craft-metrics.json number",
    "visual-purpose:": "what a section is for and what shows it are judged; no number settles them",
}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def level_of(rule: str, value) -> tuple[int, str]:
    """The level a rule gives one width's number, and the band it falls in (the prompt's words)."""
    if rule == "spacing-grid":
        if value < 0.6:
            return 3, "below 0.6"
        if value < 0.9:
            return 2, "0.6 to below 0.9"
        return 0, "0.9 up"
    if rule == "scale-ratio":
        return (3, "below 2x") if value < 2 else (0, "2x up")
    if rule == "text-sizes":
        if value > 8:
            return 3, "more than 8"
        if value >= 7:
            return 2, "7 or 8"
        return 0, "6 or fewer"
    if rule == "font-loading":
        return (3, "a family failed to load") if value else (0, "every family loaded")
    raise KeyError(rule)


def _value(rule: str, entry: dict):
    """One width's number for a rule, or None when craft-metrics.json has none."""
    value = entry.get(RULES[rule]["metric"])
    if rule == "font-loading":
        if not isinstance(value, list):
            return None
        return sorted({str(f) for f in value})
    return value if _number(value) else None


def _widths(metrics: dict) -> list[tuple[int, dict]]:
    """(width, entry) for each width in craft-metrics.json, widest first."""
    out = []
    for key, entry in metrics.items():
        if not isinstance(entry, dict):
            continue
        width = entry.get("width")
        if not _number(width):
            width = int(key) if str(key).isdigit() else None
        if width is not None:
            out.append((int(width), entry))
    return sorted(out, key=lambda x: -x[0])


def _viewport(width: int) -> str:
    return VIEWPORTS.get(width, f"{width} px")


def _evidence(rule: str, widths: list[tuple[int, dict]], values: dict[int, object]) -> str:
    parts = []
    for width, entry in widths:
        v = values[width]
        if v is None:
            continue
        if rule == "spacing-grid":
            parts.append(f"{v} at {width}")
        elif rule == "scale-ratio":
            parts.append(f"{v}x at {width} (body text {entry.get('body_px')} px, largest text "
                         f"{entry.get('display_px')} px)")
        elif rule == "text-sizes":
            parts.append(f"{v} at {width}")
        else:
            parts.append(f"{', '.join(v) or 'none'} at {width}")
    label = {"spacing-grid": "share on a 4 px grid", "scale-ratio": "scale ratio", "text-sizes": "text sizes",
             "font-loading": "not loaded"}[rule]
    return f"craft-metrics.json: {label} " + " and ".join(parts)


def anchors(metrics: dict) -> dict:
    """The anchored craft findings of one craft-metrics.json (a dict keyed by width)."""
    widths = _widths(metrics)
    checks, findings = [], []
    for rule in ANCHORS:
        r = RULES[rule]
        values = {w: _value(rule, e) for w, e in widths}
        levels = {w: (level_of(rule, v)[0] if v is not None else None) for w, v in values.items()}
        measured = [w for w in values if values[w] is not None]
        top = max((levels[w] for w in measured), default=0)
        checks.append({"rule": rule, "metric": r["metric"], "level": top,
                       "values": {str(w): values[w] for w, _ in widths},
                       "levels": {str(w): levels[w] for w, _ in widths}})
        if top == 0:
            continue
        at = [w for w in measured if levels[w] == top]
        if rule == "font-loading":
            value = sorted({f for w in measured for f in values[w]})
            width = at[0]
        else:
            worst = (min if r["worse"] == "low" else max)(values[w] for w in at)
            width = next(w for w in at if values[w] == worst)  # widths run widest first
            value = values[width]
        crossed = [w for w in measured if levels[w]]
        element = r["element"]
        if rule == "font-loading":
            element = f"text set in {', '.join(value)}: the font family failed to load"
        findings.append({
            "id": f"craft-{rule}",
            "page": PAGE,
            "width": width,
            "viewport": "all" if len(crossed) == len(widths) and len(widths) > 1 else _viewport(width),
            "element": element,
            "check": r["check"],
            "metric": r["metric"],
            "value": value,
            "threshold": level_of(rule, values[width])[1],
            "level": top,
            "rule": rule,
            "evidence": _evidence(rule, widths, values),
        })
    counts = {str(n): sum(f["level"] == n for f in findings) for n in (4, 3, 2, 1)}
    return {"version": VERSION, "page": PAGE, "widths": [w for w, _ in widths], "counts": counts,
            "checks": checks, "findings": findings}


def craft_anchor_findings(review: pathlib.Path) -> dict:
    """The anchored craft findings of one review folder (its craft-metrics.json)."""
    path = pathlib.Path(review) / "craft-metrics.json"
    metrics = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(metrics, dict) or not _widths(metrics):
        raise ValueError(f"{path} holds no measured widths")
    return anchors(metrics)


def dumps(result: dict) -> str:
    return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write(review: pathlib.Path, out: pathlib.Path | None = None) -> pathlib.Path:
    """Write review/craft/anchors.json (or out) and return its path."""
    review = pathlib.Path(review)
    out = pathlib.Path(out) if out else review / "craft" / "anchors.json"
    result = craft_anchor_findings(review)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps(result), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("review", type=pathlib.Path, help="review folder holding craft-metrics.json")
    ap.add_argument("--out", type=pathlib.Path, help="output file (default REVIEW/craft/anchors.json)")
    args = ap.parse_args(argv)
    if not (args.review / "craft-metrics.json").is_file():
        print(f"no craft-metrics.json in {args.review}", file=sys.stderr)
        return 2
    try:
        out = write(args.review, args.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    res = json.loads(out.read_text(encoding="utf-8"))
    c = res["counts"]
    print(f"{len(res['findings'])} craft anchor findings (level 3: {c['3']}, level 2: {c['2']}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
