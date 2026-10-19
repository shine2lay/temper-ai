#!/usr/bin/env python3
"""Measured problems in a homepage review folder become findings with a level, by script (H5, W4b).

design_capture.py writes review/capture.json and review/facts/<page>-<viewport>.json: axe-core
violations, text contrast, target size, control boundaries, graphics without a text alternative,
long lines, focus rings, sideways scrolling, form-field names, and the page checks of
design_page_checks.py (nav-fit, first-screen-action, empty-column, signifier, text-over-image,
dark-small-text, repeated-copy). The critic and merge prompts (design_critic.yaml,
design_merge.yaml) give each of those a level by rules A to E, written as prose; a model applying
the prose gives the same measured problem different levels from run to run. This script applies
the same rules as code, so a measured problem gets the same finding and level every time, and the
critics are left to judge what no tool measures.

Output: review/measured.json, {"version", "primary_action", "pages", "viewports", "counts", "findings"}
(W4e moved it out of review/critic/, where the merge reads every file as a critic's run). Each finding:
id, page, viewport, width, element (a selector), check, criterion, evidence (the measured numbers),
rule (a key of RULES), severity 0-4 (W4e: the same field name the critics and the merge use) and
grade (Must, Should or Could, handbook section 4.5), and a note where a reviewer could still weigh
something the rule leaves to judgment. Where the brief names no primary action and a finding's level
would rise on it, the finding carries an "ask": a fenced yes/no the merge answers and a script
applies. Empty columns are not findings but craft_candidates() for the craft critic's yes/no.
Findings come only for the pages and viewports in the review's own capture.json. The same review
folder always gives byte-identical output.

RULES below is the rules table: each rule quotes the prompt lines it comes from (the quote is
checked against the prompt files by tests/test_design_measured_findings.py) and says what the
script does where the rule needs judgment: it uses a fixed, measurable stand-in, and when the
facts can't settle between two levels it takes the lower one, as the prompts say (critic line
244). Rule D (a target that passes 2.5.8) is left to the critics: a listed pass is never a
measured problem.

Usage: design_measured_findings.py REVIEW_DIR [--out PATH] [--primary-action TEXT]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import design_page_checks as pc  # noqa: E402 - sits next to this script

VERSION = 1
CRITIC = "configs/design/agents/design_critic.yaml"
MERGE = "configs/design/agents/design_merge.yaml"  # the same SEVERITY RULES text, 35 lines earlier
CRAFT = "configs/design/agents/design_homepage_craft_critic_v2.yaml"

# The rules table. cites: (file, first line, last line) holding `says`, word for word apart from
# line breaks and indentation. script: what the code below does with it.
RULES: dict[str, dict] = {
    "A-text-contrast": {
        "cites": [(CRITIC, 152, 156), (MERGE, 117, 121)],
        "says": "Text contrast (1.4.3; 4.5:1, or 3:1 for large text): from 3:1 up to just under 4.5:1 is 2 "
        "(low-vision users strain; most people read it). Under 3:1, which fails even the large-text minimum, "
        "is 3 on text people read to decide or act (body text, descriptions, prices, instructions, labels) "
        "and 2 on incidental text (credits, legal small print). Large text: 2 from 2:1 up to 3:1, 3 under 2:1.",
        "script": "level from the measured ratio against its need (4.5, or 3 for large text). Under 3:1 on normal "
        "text is 3 unless the text is incidental: a small, figcaption or cite element, inside a footer, 12 px or "
        "smaller (small print), or credit or legal words.",
    },
    "A-non-text-contrast": {
        "cites": [(CRITIC, 157, 160), (MERGE, 122, 125)],
        "says": "Non-text contrast (1.4.11; 3:1 for a control's boundary, its state and needed graphics): from "
        "2:1 up to just under 3:1 is 2. Under 2:1 the part is close to invisible: 3 when people need that "
        "control or its state to do the task, 2 when something else on the screen shows the same thing.",
        "script": "the facts measure form fields and switches, controls people need to use: from 2:1 to under "
        "3:1 is 2, under 2:1 is 3. Whether something else shows the same thing is left to a reviewer (note).",
    },
    "A-reflow": {
        "cites": [(CRITIC, 161, 164), (MERGE, 126, 129)],
        "says": "Reflow (1.4.10; the page scrolls sideways at a phone width): a page up to about a fifth wider "
        "than the screen is 2 (a small sideways shift; the text still reads). A fixed width of about one and "
        "a half screens or more, so a section can only be read by scrolling back and forth on every line, is 3.",
        "script": "scroll width over viewport width: 1.5 or more is 3; below that 2 (up to 1.2 the rule says 2; "
        "between 1.2 and 1.5 no level is named, so the lower one).",
    },
    "A-target-size": {
        "cites": [(CRITIC, 165, 165), (MERGE, 130, 130)],
        "says": "Target size (2.5.8): a target the facts list as failing is 2.",
        "script": "every target in small_targets (under 24x24 px and not saved by the spacing exception, as "
        "design_measure.js decides on the unrounded size) is 2. Listed passes are not findings (rule D).",
    },
    "A-labels": {
        "cites": [(CRITIC, 166, 169), (MERGE, 131, 134)],
        "says": "Labels and names (1.3.1, 3.3.2, 4.1.2): a field whose visible label is only not tied to it in "
        "code is 2 (sighted users are fine; screen readers get a weaker name). Fields with no visible label at "
        "all (placeholder only) in the page's main form are 3.",
        "script": "a field named only by its placeholder, a title or nothing is 3 when the view has two or more "
        "text fields and none of them takes its name from a label (the form leans on placeholders); otherwise "
        "2 (the view labels its other fields, so this one's visible label is likely only not tied in code; or "
        "it is a lone field, not a main form).",
    },
    "A-text-alt": {
        "cites": [(CRITIC, 170, 173), (MERGE, 135, 138)],
        "says": "Text alternatives (1.1.1): missing on pictures that add names or mood but nothing the task "
        "needs (logos, photos, decoration) is 2. Missing where the picture or icon is the only carrier of "
        "information the task needs (a status icon, a mark that stands for a word, a chart's values) is 3: "
        "screen-reader users get nothing.",
        "script": "a graphic inside a table cell (td or th) stands for a value in the table (a check mark, a "
        "status icon): 3. Any other graphic: 2, with a note that it is 3 if it is the only carrier of "
        "information the task needs.",
    },
    "B-focus-visible": {
        "cites": [(CRITIC, 175, 177), (MERGE, 140, 142)],
        "says": "Keyboard focus not visible (2.4.7): on the main navigation or the page's primary action it is "
        "3 (keyboard users lose their place on the path every visit takes); on one secondary link or control "
        "it is 2.",
        "script": "3 on a link inside the main navigation (the header nav the page checks found, matched by "
        "its own selector part; without page checks, any nav element outside the footer) or on the control "
        "named like the brief's primary action; otherwise 2, with a note naming the brief's primary action or "
        "saying it names none.",
    },
    "C-pages": {
        "cites": [(CRITIC, 194, 197), (MERGE, 159, 162)],
        "says": "C. How many pages: a problem the facts or tiles show on most of the reviewed pages, or in a part "
        "every page shares (header, main navigation, footer), reaches nearly every user: one level up, at most "
        "to 3. On one or two pages: no change. Count only the pages where the facts or a tile show it.",
        "script": "the same check on the same element measured on more than half of the reviewed pages, and on "
        "three or more: one level up, at most 3. A part every page shares shows on every page when it really "
        "is shared, so the count covers it.",
    },
    "D-target-pass": {
        "cites": [(CRITIC, 198, 201), (MERGE, 163, 166)],
        "says": "D. A target that meets 2.5.8 (a listed pass) is never a WCAG failure. As its own usability "
        'finding (criterion "usability: target size (Fitts)", saying AA is met) it is 2 when people use it '
        "again and again in the page's main task and it is 16 px or smaller; otherwise 1.",
        "script": "not scripted: a listed pass is never a measured problem; whether to report it as a usability "
        "finding is the critics' judgment.",
    },
    "E-text-over-image": {
        "cites": [(CRITIC, 203, 204), (MERGE, 168, 169)],
        "says": "text-over-image: rule A's text contrast levels, on the ratio measured from the pixels.",
        "script": "rule A-text-contrast on the ratio measured from the screenshot pixels behind the letters.",
    },
    "E-signifier": {
        "cites": [(CRITIC, 205, 206), (MERGE, 170, 171)],
        "says": "signifier: controls with no visible cue are 2; 3 when the page's primary action, or every "
        "control of its main task, has none.",
        "script": "one finding per view: 3 when every checked control lacks a cue, or one named like the brief's "
        "primary action does; otherwise 2.",
    },
    "E-repeated-copy": {
        "cites": [(CRITIC, 207, 208), (MERGE, 172, 173)],
        "says": "repeated-copy: 2 when a phrase repeats in three or more sections or several phrases repeat; 1 "
        "for one phrase in two sections.",
        "script": "two or more phrases, or one in three or more sections: 2; one phrase in two sections: 1.",
    },
    "E-first-screen-action": {
        "cites": [(CRITIC, 209, 210), (MERGE, 174, 175)],
        "says": "first-screen-action: 2; 3 when nothing in the first phone screen says what the product is either.",
        "script": "3 when no heading starts inside the first phone screen; otherwise 2, with a note that a "
        "reviewer judges whether that heading says what the product is.",
    },
    "E-nav-fit": {
        "cites": [(CRITIC, 211, 211), (MERGE, 176, 176)],
        "says": "nav-fit: 2.",
        "script": "2.",
    },
    "E-dark-small-text": {
        "cites": [(CRITIC, 211, 211), (MERGE, 176, 176)],
        "says": "dark-small-text: 2.",
        "script": "2, one finding per view (the page check groups its blocks).",
    },
    "craft-empty-column": {
        "cites": [(CRAFT, 111, 112)],
        "says": "an empty column measured by facts.md (empty-column): 2 (space); 3 when it is in the first "
        "screen or beside the primary action.",
        "script": "3 when the column starts inside the first screen (above the viewport height) or sits beside "
        "text naming the brief's primary action; otherwise 2. The critic and merge rules name no level for it; "
        "this is the craft critic's rule.",
    },
    "long-lines": {
        "cites": [(CRAFT, 58, 58), (CRITIC, 144, 145), (CRITIC, 244, 244)],
        "says": "measure 45-90 characters, comfortable leading. | 1 cosmetic: polish (alignment, spacing, styling "
        "consistency) that changes neither whether nor how fast users succeed. | When torn between two levels "
        "after these rules, choose the lower.",
        "script": "lines over 90 characters (design_measure.js) are 1: no rule names a level, line length is no "
        "WCAG AA criterion (1.4.8 is AAA), and between minor and cosmetic the prompts take the lower; the "
        "handbook grades a wrapping nit Could.",
    },
    "axe-other": {
        "cites": [(CRITIC, 141, 143), (CRITIC, 244, 244)],
        "says": "2 minor: users are slowed, confused or have to double-check, but most notice and recover by "
        "themselves; or a WCAG failure that makes something harder but still usable, or one on a secondary "
        "element. | When torn between two levels after these rules, choose the lower.",
        "script": "an axe violation that no measure above already covers in the same view: 2, with a note that "
        "it is 3 if it makes an important element unusable.",
    },
}

# Says parts joined by " | " are separate quotes; each must appear in at least one cited range.

# Grades, the design handbook's section 4.5 (design-handbook skill, outside this repo; owner direction
# 2026-10-09): "Must: ... a measured hard-rule failure
# (WCAG 2.2 AA contrast, keyboard, visible focus, 24 px targets; text clipped or overlapping; content
# past a required first screen; broken layout at a required width) ... usability severity 3-4."
# "Should: ... severity 2". "Could: polish, severity 1: a few px out of line, a spacing or wrapping
# nit". "A measurement can always make a finding Must and can't be argued down."
HARD_RULE = {"text-contrast", "non-text-contrast", "reflow", "target-size", "labels", "text-alt",
             "focus-visible", "text-over-image", "first-screen-action"}

WCAG = {
    "text-contrast": "WCAG 1.4.3",
    "text-over-image": "WCAG 1.4.3",
    "non-text-contrast": "WCAG 1.4.11",
    "reflow": "WCAG 1.4.10",
    "target-size": "WCAG 2.5.8",
    "labels": "WCAG 1.3.1, 3.3.2, 4.1.2",
    "text-alt": "WCAG 1.1.1",
    "focus-visible": "WCAG 2.4.7",
    "long-lines": "readability: line length (measure 45-90 characters)",
    "nav-fit": "page check: nav-fit",
    "first-screen-action": "page check: first-screen-action",
    "empty-column": "page check: empty-column",
    "signifier": "page check: signifier",
    "dark-small-text": "page check: dark-small-text",
    "repeated-copy": "page check: repeated-copy",
}

# Finding order inside one view (axe violations last, by rule id).
CHECK_ORDER = ["text-contrast", "text-over-image", "non-text-contrast", "reflow", "target-size", "labels",
               "text-alt", "focus-visible", "long-lines", "nav-fit", "first-screen-action", "empty-column",
               "signifier", "dark-small-text", "repeated-copy"]

# axe rules a direct measure of design_measure.js already covers: skipped in a view where that measure
# lists anything, so one problem is not reported twice.
AXE_COVERED = {
    "color-contrast": "contrast_failures",
    "image-alt": "unnamed_graphics",
    "svg-img-alt": "unnamed_graphics",
    "role-img-alt": "unnamed_graphics",
    "input-image-alt": "unnamed_graphics",
    "area-alt": "unnamed_graphics",
    "object-alt": "unnamed_graphics",
    "target-size": "small_targets",
    "label": "fields",
    "select-name": "fields",
}

UNNAMED = ("none", "placeholder only", "title")  # field names design_capture lists as problems
NOT_TEXT_ENTRY = {"checkbox", "radio", "hidden", "submit", "button", "image", "reset", "range", "color", "file"}
INCIDENTAL_TAGS = {"small", "figcaption", "cite"}
INCIDENTAL_WORDS = re.compile(
    r"\u00a9|\(c\)|copyright|all rights reserved|terms of (service|use)|"
    r"photo(graph)?s? (by|credit)|illustrations? by|image credit|credits?:", re.I)
SMALL_PRINT_PX = 12


def _tags(sel: str) -> list[str]:
    """The element names along a design_measure.js selector ("#id" parts give "")."""
    out = []
    for part in (sel or "").split(">"):
        m = re.match(r"\s*([a-zA-Z][a-zA-Z0-9-]*)", part)
        out.append(m.group(1).lower() if m else "")
    return out


def _same(a: str, b: str) -> bool:
    """Two labels name the same action (case, spacing and punctuation aside)."""
    norm = lambda s: " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))  # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)


def _short(text: str, n: int = 80) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "\u2026"


def _incidental(t: dict) -> str:
    """Why a text block counts as incidental (credits, legal small print), or ""."""
    if (t.get("tag") or "").lower() in INCIDENTAL_TAGS:
        return f"a {t['tag']} element"
    if "footer" in _tags(t.get("sel", "")):
        return "inside a footer"
    if t.get("size") is not None and float(t["size"]) <= SMALL_PRINT_PX:
        return f"{t['size']} px small print"
    if INCIDENTAL_WORDS.search(t.get("text") or ""):
        return "credit or legal words"
    return ""


def text_contrast_level(ratio: float, large: bool, incidental: str) -> tuple[int, str]:
    """Rule A, text contrast: (level, note) for a ratio below its need."""
    if large:
        return (2, "") if ratio >= 2 else (3, "")
    if ratio >= 3:
        return 2, ""
    if incidental:
        return 2, f"under 3:1 on incidental text ({incidental}): 2"
    return 3, ""


def reflow_level(scroll: float, viewport: float) -> int:
    """Rule A, reflow: 3 from about one and a half screens; 2 below (named up to a fifth wider)."""
    return 3 if viewport and scroll / viewport >= 1.5 else 2


def boundary_level(ratio: float) -> int:
    """Rule A, non-text contrast: 2 from 2:1 up to just under 3:1, 3 under 2:1."""
    return 2 if ratio >= 2 else 3


def grade(check: str, level: int, evidence: dict, criterion: str = "") -> str:
    if level >= 3 or check in HARD_RULE or (check.startswith("axe:") and criterion.startswith("WCAG")):
        return "Must"
    if check == "nav-fit" and evidence.get("overflow"):
        return "Must"  # "broken layout at a required width": links past the screen edge
    return "Should" if level == 2 else "Could"


def _finding(view: dict, check: str, element: str, evidence: dict, rule: str, level: int,
             note: str = "", criterion: str = "") -> dict:
    f = {"page": view["page"], "viewport": view["viewport"], "width": view["width"], "element": element,
         "check": check, "criterion": criterion or WCAG[check], "evidence": evidence, "rule": rule,
         "severity": level, "kind": "measured"}
    if note:
        f["note"] = note
    return f


def view_findings(view: dict, facts: dict, primary: str, t: dict) -> list[dict]:
    """The findings of one page at one viewport, before rule C and ids."""
    out: list[dict] = []
    add = out.append
    raw = facts.get("page_checks") if isinstance(facts.get("page_checks"), dict) else None

    for c in facts.get("contrast_failures") or []:
        if c.get("inactive") or float(c["contrast"]) >= float(c["needs"]):
            continue  # disabled controls are exempt; a ratio at or above its need passes
        large = float(c["needs"]) < 4.5
        level, note = text_contrast_level(float(c["contrast"]), large, "" if large else _incidental(c))
        add(_finding(view, "text-contrast", c["sel"], {
            "contrast": c["contrast"], "needs": c["needs"], "size": c.get("size"), "weight": c.get("weight"),
            "color": c.get("color"), "background": c.get("background"), "text": _short(c.get("text"))},
            "A-text-contrast", level, note))

    for b in facts.get("weak_boundaries") or []:
        ratio = float(b["boundary_contrast"])
        if ratio >= 3:
            continue
        level = boundary_level(ratio)
        add(_finding(view, "non-text-contrast", b["sel"], {"boundary_contrast": b["boundary_contrast"],
                                                           "needs": 3, "name": _short(b.get("name"))},
                     "A-non-text-contrast", level,
                     "2 if something else on the screen shows the same state" if level == 3 else ""))

    pw = facts.get("page_width") or {}
    if pw.get("overflows"):
        over = facts.get("overflowing") or []
        add(_finding(view, "reflow", over[0]["sel"] if over else "html", {
            "scroll": pw.get("scroll"), "viewport": pw.get("viewport"),
            "ratio": round(pw["scroll"] / pw["viewport"], 2) if pw.get("viewport") else None,
            "elements": [{"sel": o["sel"], "right": o["box"][0] + o["box"][2]} for o in over]},
            "A-reflow", reflow_level(pw.get("scroll") or 0, pw.get("viewport") or 0)))

    for s in facts.get("small_targets") or []:
        ev = {"size": [s["box"][2], s["box"][3]], "name": _short(s.get("name")), "hit": s.get("hit")}
        n = s.get("too_close_to")
        if n:
            ev["too_close_to"] = {"sel": n.get("sel"), "edge": n.get("edge"), "centre": n.get("centre")}
        add(_finding(view, "target-size", s["sel"], ev, "A-target-size", 2))

    fields = facts.get("fields") or []
    text_fields = [f for f in fields if (f.get("type") or "text").lower() not in NOT_TEXT_ENTRY]
    labelled = [f for f in text_fields if f.get("name_from") == "label"]
    for f in fields:
        if f.get("name_from") not in UNNAMED:
            continue
        main_form = len(text_fields) >= 2 and not labelled
        add(_finding(view, "labels", f["sel"], {
            "name_from": f["name_from"], "type": f.get("type"), "name": _short(f.get("name")),
            "text_fields": len(text_fields), "labelled_text_fields": len(labelled)},
            "A-labels", 3 if main_form else 2,
            "" if main_form else "3 if the field shows no visible label at all and sits in the page's main form"))

    for g in facts.get("unnamed_graphics") or []:
        in_cell = bool({"td", "th"} & set(_tags(g["sel"])))
        add(_finding(view, "text-alt", g["sel"], {"tag": g.get("tag"), "src": g.get("src") or "",
                                                 "in_table_cell": in_cell},
                     "A-text-alt", 3 if in_cell else 2,
                     "" if in_cell else "3 if this picture is the only carrier of information the task needs"))

    # design_measure.js names an element by itself and up to three ancestors, so a link's selector holds
    # its nav's own part (the last part of the nav's selector) but may have lost the header above it.
    nav = (raw or {}).get("nav") or {}
    nav_part = nav["sel"].split(" > ")[-1].strip() if nav.get("found") and nav.get("sel") else ""
    for r in facts.get("no_focus_ring") or []:
        tags = _tags(r["sel"])
        if "footer" in tags:
            in_nav = False
        elif nav_part:
            in_nav = nav_part in [s.strip() for s in r["sel"].split(">")]
        else:
            in_nav = "nav" in tags
        is_primary = _same(r.get("name"), primary)
        level = 3 if in_nav or is_primary else 2
        note = ""
        if level == 2:
            note = ("3 if this is the page's primary action (the brief names none)" if not primary
                    else f'3 if this is the page\'s primary action (the brief names "{primary}")')
        f = _finding(view, "focus-visible", r["sel"], {
            "name": _short(r.get("name")), "outline": r.get("outline"), "box_shadow": r.get("box_shadow"),
            "main_navigation": in_nav, "primary_action": is_primary}, "B-focus-visible", level, note)
        if level == 2 and not primary:
            f["ask"] = ask(f'Is "{_short(r.get("name"))}" ({r["sel"]}) the page\'s primary action?', 3)
        add(f)

    for ln in facts.get("long_lines") or []:
        add(_finding(view, "long-lines", ln["sel"], {"chars_per_line": ln["chars_per_line"],
                                                     "lines": ln.get("lines"), "width": ln.get("width"),
                                                     "text": _short(ln.get("text"), 60)}, "long-lines", 1))

    for v in facts.get("axe") or []:
        covered = AXE_COVERED.get(v["id"])
        if covered and facts.get(covered):
            continue
        nums = sorted({f"{m.group(1)}.{m.group(2)}.{m.group(3)}" for w in v.get("wcag") or []
                       for m in [re.fullmatch(r"wcag(\d)(\d)(\d+)", w)] if m})
        targets = [n["target"] if isinstance(n["target"], str) else " ".join(map(str, n["target"]))
                   for n in v.get("nodes") or []]
        add(_finding(view, "axe:" + v["id"], targets[0] if targets else "", {
            "impact": v.get("impact"), "help": v.get("help"), "nodes": len(targets), "targets": targets[:6]},
            "axe-other", 2, "3 if it makes an important element unusable",
            criterion=("WCAG " + ", ".join(nums)) if nums else "axe " + v["id"]))

    if raw is not None:
        out += page_check_findings(view, facts, raw, primary, t)
    return out


def page_check_findings(view: dict, facts: dict, raw: dict, primary: str, t: dict) -> list[dict]:
    """design_page_checks.judge() decides which page checks fail, exactly as facts.md lists them;
    the findings take their elements and numbers from the same raw data."""
    out: list[dict] = []
    vp = view["viewport"]
    problems, _ = pc.judge(vp, raw, t, raw.get("pixels"))
    fired = {c for c, _ in problems}

    if "nav-fit" in fired:
        nav = raw.get("nav") or {}
        out.append(_finding(view, "nav-fit", nav.get("sel", ""), {
            "lines": nav.get("lines"), "max_lines": t["nav_fit"]["max_lines"], "rows": nav.get("rows") or [],
            "wrapped": nav.get("wrapped") or [], "overflow": nav.get("overflow") or [],
            "header_height": nav.get("header_height")}, "E-nav-fit", 2))

    if "first-screen-action" in fired:
        act = raw.get("action") or {}
        first = act.get("first") or {}
        screen = t["first_screen_action"]["screen_height"]
        headed = [h for h in facts.get("headings") or [] if h.get("box") and h["box"][1] < screen]
        ev = {"label": act.get("label"), "screen_height": screen, "found": bool(first),
              "top": first.get("top"), "bottom": first.get("bottom"), "text": _short(first.get("text")),
              "section": first.get("section"), "headings_in_first_screen": len(headed)}
        out.append(_finding(view, "first-screen-action", first.get("sel", ""), ev, "E-first-screen-action",
                            2 if headed else 3,
                            "3 if the heading in the first phone screen doesn't say what the product is"
                            if headed else ""))

    if "empty-column" in fired:
        frame = raw.get("frame") or [0, 0]
        height = (facts.get("viewport") or raw.get("viewport") or [0, 0])[1]
        for c in raw.get("columns") or []:
            first_screen = c["top"] < height
            beside_primary = bool(primary) and _same(c.get("beside"), primary)
            out.append(_finding(view, "empty-column", f'{c["section"]}: {c["side"]} column beside "{c["beside"]}"', {
                "width": c["width"], "share": c["share"], "content_width": frame[1] - frame[0], "side": c["side"],
                "height": c["height"], "top": c["top"], "beside": c["beside"], "section": c["section"],
                "first_screen": first_screen, "beside_primary_action": beside_primary},
                "craft-empty-column", 3 if first_screen or beside_primary else 2))

    if "signifier" in fired:
        cues = raw.get("cues") or {}
        without = cues.get("without") or []
        all_bare = cues.get("without_count") == cues.get("checked")
        primary_bare = bool(primary) and any(_same(x.get("text"), primary) for x in without)
        f = _finding(view, "signifier", without[0]["sel"] if without else "", {
            "without_count": cues.get("without_count"), "checked": cues.get("checked"),
            "elements": [{"sel": x["sel"], "text": _short(x.get("text"), 40), "section": x.get("section")}
                         for x in without[:12]],
            "primary_action_without_cue": primary_bare},
            "E-signifier", 3 if all_bare or primary_bare else 2)
        if f["severity"] == 2 and not primary:
            f["ask"] = ask("Is one of the elements in evidence.elements the page's primary action?", 3)
        out.append(f)

    if "text-over-image" in fired:
        pixels = raw.get("pixels") or {}
        for c in raw.get("overlays") or []:
            px = pixels.get(str(c["id"])) or pixels.get(c["id"])
            if not px or not px["ratio"] < c["needs"]:
                continue
            large = float(c["needs"]) < 4.5
            level, note = text_contrast_level(float(px["ratio"]), large, "" if large else _incidental(c))
            out.append(_finding(view, "text-over-image", c["sel"], {
                "ratio": px["ratio"], "needs": c["needs"], "behind": px.get("bg"), "declared": c.get("declared"),
                "size": c.get("size"), "weight": c.get("weight"), "over": c.get("kind"),
                "section": c.get("section"), "text": _short(c.get("text"))}, "E-text-over-image", level, note))

    if "dark-small-text" in fired:
        small = raw.get("small_dark") or []
        out.append(_finding(view, "dark-small-text", small[0]["sel"] if small else "", {
            "blocks": len(small), "max_px": t["dark_small_text"]["max_px"],
            "sizes": sorted({c["size"] for c in small}),
            "examples": [{"sel": c["sel"], "size": c["size"], "words": c.get("words"), "color": c.get("color"),
                          "background": c.get("background")} for c in small[:3]]}, "E-dark-small-text", 2))
    return out


def copy_findings(view: dict, raw: dict, t: dict) -> list[dict]:
    """repeated-copy, from the desktop view (design_page_checks.copy_problems)."""
    if not pc.copy_problems(raw, t)[0]:
        return []
    found = pc.repeated_copy(raw.get("copy") or [], t)
    level = 2 if len(found) >= 2 or any(len(p["sections"]) >= 3 for p in found) else 1
    return [_finding(view, "repeated-copy", "", {
        "phrases": [{"phrase": p["phrase"], "sections": p["sections"]} for p in found]},
        "E-repeated-copy", level)]


def _order(f: dict, pages: list[str], views: dict[str, list[str]]) -> tuple:
    check = f["check"]
    rank = CHECK_ORDER.index(check) if check in CHECK_ORDER else len(CHECK_ORDER)
    vps = views[f["page"]]
    return (pages.index(f["page"]), vps.index(f["viewport"]) if f["viewport"] in vps else len(vps), rank,
            check, f["element"], json.dumps(f["evidence"], sort_keys=True))


def ask(question: str, if_yes: int) -> dict:
    """A fenced yes/no for the merge when the brief names no primary action (H5, W4e): the script, not the
    model, applies the level (design_homepage_next.merge_join)."""
    return {"question": question, "answers": ["yes", "no"], "if_yes": if_yes}


# W4e (H5, home's decision): an empty column is never a measured Must. The page check still finds it, and the
# craft critic answers a fenced yes/no (dead space, or purposeful layout?); only a confirmed one becomes a
# finding, at the level the craft critic's rule gives (CRAFT lines 111-112). The W4b screen's three false
# alarms were all purposeful layouts: morrow rooms and settings, fernway signup.
CANDIDATE_CHECKS = ("empty-column",)
CANDIDATE_QUESTION = ("Is this column dead space (an empty area that looks unfinished or wastes the screen) "
                      "rather than purposeful layout (a deliberate two-column split, an image or artifact column, "
                      "a short label column)?")


def measured_findings(review: pathlib.Path, primary_action: str | None = None) -> dict:
    """All measured findings of one review folder (capture.json + facts/), without the craft candidates."""
    result = _measure(review, primary_action)
    found = [f for f in result.pop("all") if f["check"] not in CANDIDATE_CHECKS]
    counts = {g: sum(f["grade"] == g for f in found) for g in ("Must", "Should", "Could")}
    return {**result, "counts": counts, "findings": found}


def craft_candidates(review: pathlib.Path, primary_action: str | None = None) -> list[dict]:
    """The empty columns the page check measured, as candidates for the craft critic's yes/no."""
    return [{**f, "question": CANDIDATE_QUESTION, "answers": ["yes", "no"], "if_yes": f["severity"]}
            for f in _measure(review, primary_action)["all"] if f["check"] in CANDIDATE_CHECKS]


def _measure(review: pathlib.Path, primary_action: str | None = None) -> dict:
    review = pathlib.Path(review)
    cap = json.loads((review / "capture.json").read_text(encoding="utf-8"))
    primary = primary_action if primary_action is not None else ((cap.get("page_checks") or {}).get("primary_action") or "")
    t = pc.thresholds()
    found: list[dict] = []
    pages, views, names = [], {}, {}
    for p in cap.get("pages") or []:
        pages.append(p["page"])
        names[p["page"]] = p.get("name") or re.sub(r"[^a-z0-9]+", "-", p["page"].lower()).strip("-")
        views[p["page"]] = [v["viewport"] for v in p.get("views") or []]
        for v in p.get("views") or []:
            facts = json.loads((review / v["facts"]).read_text(encoding="utf-8"))
            size = facts.get("viewport") or v.get("size") or [None, None]
            view = {"page": p["page"], "viewport": v["viewport"], "width": size[0]}
            found += view_findings(view, facts, primary, t)
            if v["viewport"] == "desktop" and isinstance(facts.get("page_checks"), dict):
                found += copy_findings(view, facts["page_checks"], t)

    # Rule C: the same problem on most of the reviewed pages.
    # The same problem: the same check on the same element (on a page-wide finding, the same evidence).
    same = lambda f: (f["check"], f["element"] or json.dumps(f["evidence"], sort_keys=True))  # noqa: E731
    on_pages: dict[tuple, set] = {}
    for f in found:
        on_pages.setdefault(same(f), set()).add(f["page"])
    for f in found:
        n = len(on_pages[same(f)])
        if n >= 3 and n * 2 > len(pages) and f["severity"] < 3:
            f["severity"] += 1
            f["raised"] = f"C-pages: measured on {n} of {len(pages)} reviewed pages"
        if "ask" in f and f["severity"] >= f["ask"]["if_yes"]:
            del f["ask"]  # already at the level a yes would give: nothing left to ask

    found.sort(key=lambda f: _order(f, pages, views))
    seen: dict[tuple, int] = {}
    for f in found:
        key = (f["page"], f["viewport"], f["check"])
        seen[key] = seen.get(key, 0) + 1
        f["id"] = f"{names[f['page']]}-{f['viewport']}-{f['check'].replace(':', '-')}-{seen[key]}"
        f["grade"] = grade(f["check"], f["severity"], f["evidence"], f["criterion"])
    return {"version": VERSION, "primary_action": primary, "pages": len(pages),
            "viewports": {names[p]: views[p] for p in pages}, "all": found}


def dumps(result: dict) -> str:
    return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write(review: pathlib.Path, out: pathlib.Path | None = None, primary_action: str | None = None) -> pathlib.Path:
    """Write review/measured.json (or out) and return its path. Never inside review/critic/: the merge and
    design_review_verify read every file there as a critic's run (W4e)."""
    review = pathlib.Path(review)
    out = pathlib.Path(out) if out else review / "measured.json"
    result = measured_findings(review, primary_action)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps(result), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("review", type=pathlib.Path, help="review folder holding capture.json and facts/")
    ap.add_argument("--out", type=pathlib.Path, help="output file (default REVIEW/measured.json)")
    ap.add_argument("--primary-action", default=None,
                    help="the page's primary action label (default: capture.json page_checks.primary_action)")
    args = ap.parse_args(argv)
    if not (args.review / "capture.json").is_file():
        print(f"no capture.json in {args.review}", file=sys.stderr)
        return 2
    out = write(args.review, args.out, args.primary_action)
    res = json.loads(out.read_text(encoding="utf-8"))
    c = res["counts"]
    print(f"{len(res['findings'])} measured findings (Must {c['Must']}, Should {c['Should']}, "
          f"Could {c['Could']}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
