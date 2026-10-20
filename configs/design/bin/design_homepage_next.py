#!/usr/bin/env python3
"""Candidate homepage stages that leave the counting to scripts (Design, W4e: H4-H7).

    design_homepage_next.py STAGE --workspace W [--fixture|--pilot|--bench] [--site DIR] [--page NAME]

The candidate workflow design_homepage_v2_next and its test twins run these stages beside the live
stages of design_homepage_v2.py, which this file imports and never changes; the live workflow never
calls it (tests/test_design_homepage_next.py checks both). No model here: each stage reads files that a
script or a critic wrote and writes files the next step reads.

  measure           the live measure stage, with the spacing share counted from 4 px up (hairline
                    borders of 1-3 px left out: the W4e screen's one false spacing alarm), and
                    craft-facts.md saying which values it counts
  measured          review/measured.json: every measured problem of the capture, levelled by the rules
                    (design_measured_findings, H5); outside review/critic/, which the merge reads as critics
  craft_anchors     review/anchors.json: the settled craft numbers and the empty-column candidates
                    (design_craft_anchors, H6); outside review/craft/, which combine reads as critics
  deck_words        homepage/copy/words.json: the countable word checks on the draft deck (H7)
  page_words        review/words.json: the same checks on the built page's text (H7)
  merge_join        review/findings.json + review/report.md: the measured findings, one per problem,
                    beside the merge's judged ones (review/merge.json); refuses without review/verify.json,
                    so the merge never does the facts check itself (H4)
  craft_join        review/craft/craft.json: anchors + confirmed empty columns + the craft critic's findings
  content_join      review/content/content.json: the page's word findings + the content critic's
  copy_review_join  homepage/copy/review.json: the deck's word findings + the content critic's, less the
                    ones copy_contract already lists in check.json (one finding per problem)
  bench_prepare     the craft benchmark's prepare with page checks and the candidate spacing share (W10)
  bench_collect     the craft benchmark's collect, plus the measured findings' counts (W10)
  copy_seed         a given deck (data) as homepage/copy/copy.json (W11's decks)
  page_prepare      a given built page (--site) into homepage/site, captured, with its text read (W11's pages)
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import design_craft_anchors as ca  # noqa: E402 - the scripts sit next to this file
import design_craft_bench as cb  # noqa: E402
import design_homepage_v2 as v2  # noqa: E402
import design_measured_findings as mf  # noqa: E402
import design_runtime_checks as rtc  # noqa: E402
import design_word_checks as wc  # noqa: E402

VERSION = 1
JOINED_BY = "design_homepage_next.py"
STAGES = ("measure", "measured", "craft_anchors", "deck_words", "page_words", "merge_join", "craft_join",
          "content_join", "copy_review_join", "bench_prepare", "bench_collect", "copy_seed", "page_prepare")


def _require(root: Path, *names: str, why: str = "") -> None:
    for name in names:
        if not (root / name).is_file():
            raise ValueError(f"{name} missing" + (f": {why}" if why else ""))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    v2.save(path, value)


# --------------------------------------------------------------------------- spacing share from 4 px up

# The W4e screen's one false craft alarm: the live share counts 1-3 px values (hairline borders and
# gaps) as spacing, so a page whose every spacing value of 4 px or more sits on the grid scored 0.89
# (a level-2 finding). The candidate keeps the live measurement and adds the browser's histogram of
# spacing values; the share is then counted over the values from 4 px up.
SPACING_FROM_PX = 4
SPACING_LINE = "spacing_values: new Set(spacing).size, spacing_on_4px: Math.round(onScale * 100) / 100,"
HISTOGRAM = " spacing_histogram: spacing.reduce((h, v) => { h[v] = (h[v] || 0) + 1; return h; }, {}),"
LIVE_CRAFT_METRICS = v2.craft_metrics
SPACING_FACT = re.compile(r"^- spacing values (\S+), share on a 4 px grid (\S+)(?: \(.*\))?$")
WIDTH_HEAD = re.compile(r"^## (\d+) px\b")


def spacing_code(code: str) -> str:
    """The live CRAFT_CODE, also returning the histogram of spacing values."""
    if code.count(SPACING_LINE) != 1:
        raise RuntimeError("CRAFT_CODE's spacing line changed: re-check the candidate spacing share")
    return code.replace(SPACING_LINE, SPACING_LINE + HISTOGRAM)


def js_round2(x: float) -> int | float:
    """Math.round(x * 100) / 100 as the browser computes it (halves up), a whole number as an int."""
    v = math.floor(x * 100 + 0.5) / 100
    return int(v) if v == int(v) else v


def spacing_from(entry: dict) -> dict:
    """One width's metrics with spacing_on_4px counted over the values from 4 px up."""
    hist = entry.pop("spacing_histogram", None)
    if not isinstance(hist, dict):
        return entry
    counts: dict[int, int] = {}
    for key, n in hist.items():
        counts[int(float(key))] = counts.get(int(float(key)), 0) + int(n)
    kept = {v: n for v, n in counts.items() if v >= SPACING_FROM_PX}
    total = sum(kept.values())
    entry["spacing_on_4px_all"] = entry.get("spacing_on_4px")
    entry["spacing_on_4px"] = js_round2(sum(n for v, n in kept.items() if v % 4 == 0) / total) if total else 1
    entry["spacing_hairlines"] = sum(n for v, n in counts.items() if 0 < v < SPACING_FROM_PX)
    entry["spacing_from_px"] = SPACING_FROM_PX
    entry["spacing_histogram"] = {str(v): counts[v] for v in sorted(counts)}
    return entry


def craft_metrics(site: Path) -> dict:
    """design_homepage_v2.craft_metrics with the candidate spacing share."""
    live = v2.CRAFT_CODE
    v2.CRAFT_CODE = spacing_code(live)
    try:
        metrics = LIVE_CRAFT_METRICS(site)
    finally:
        v2.CRAFT_CODE = live
    return {w: spacing_from(dict(m)) if isinstance(m, dict) else m for w, m in metrics.items()}


@contextlib.contextmanager
def candidate_metrics() -> Iterator[None]:
    """Inside: the live stages (measure, the craft benchmark's prepare) measure with craft_metrics above."""
    live = v2.craft_metrics
    v2.craft_metrics = craft_metrics
    try:
        yield
    finally:
        v2.craft_metrics = live


@contextlib.contextmanager
def vacancy_pass() -> Iterator[None]:
    """Only the candidate capture asks for H12's vacancy answer. Restore even on failure/nesting."""
    env = mf.pc.VACANCY_ENV
    previous = os.environ.get(env)
    os.environ[env] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = previous


def note_spacing(review: Path) -> int:
    """Say on craft-facts.md's spacing lines which values the share counts (idempotent). Lines changed."""
    facts, metrics_path = review / "craft-facts.md", review / "craft-metrics.json"
    if not facts.is_file() or not metrics_path.is_file():
        return 0
    metrics = v2.load(metrics_path)
    width, changed, out = None, 0, []
    for line in facts.read_text(encoding="utf-8").split("\n"):
        head = WIDTH_HEAD.match(line)
        if head:
            width = head.group(1)
        entry = metrics.get(width) if isinstance(metrics, dict) and width else None
        if SPACING_FACT.match(line) and isinstance(entry, dict) and "spacing_from_px" in entry:
            new = (f"- spacing values {entry.get('spacing_values')}, share on a 4 px grid {entry.get('spacing_on_4px')} "
                   f"(values from {entry['spacing_from_px']} px up; {entry.get('spacing_hairlines')} hairline values "
                   f"of 1-3 px left out; all values {entry.get('spacing_on_4px_all')})")
            changed += new != line
            line = new
        out.append(line)
    facts.write_text("\n".join(out), encoding="utf-8")
    return changed


def measure(job: v2.Job, review: Path) -> dict:
    with candidate_metrics(), vacancy_pass():
        result = job.measure()
    return {**result, "spacing_from_px": SPACING_FROM_PX, "spacing_lines_noted": note_spacing(review)}


def bench_prepare(root: Path, site: str, page: str) -> dict:
    if not site or not page:
        raise ValueError("bench_prepare needs --site and --page")
    with candidate_metrics(), vacancy_pass():
        result = cb.prepare(root, Path(site), page, page_checks=True)
    return {**result, "spacing_from_px": SPACING_FROM_PX, "spacing_lines_noted": note_spacing(root / "review")}


# --------------------------------------------------------------------------- the scripts' own files


def measured(review: Path) -> dict:
    _require(review, "capture.json", why="the capture (measure) runs first")
    res = v2.load(mf.write(review))
    return {"status": "completed", "measured_path": "review/measured.json", "findings": len(res["findings"]),
            "counts": res["counts"], "asks": sum("ask" in f for f in res["findings"]),
            "primary_action": res["primary_action"], "viewports": res["viewports"]}


def craft_anchors(review: Path) -> dict:
    _require(review, "craft-metrics.json", why="measure (or bench_prepare) runs first")
    path = ca.write(review)
    res = v2.load(path)
    candidates = res.pop("candidates", [])
    # H12: the critic gets anchors, not empty-column questions or measured answers. The join reads the capture.
    _write_json(path, res)
    return {"status": "completed", "anchors_path": "review/anchors.json", "findings": len(res["findings"]),
            "severity_counts": res["counts"], "candidates": len(candidates)}


def deck_words(root: Path) -> dict:
    _require(root, "homepage/copy/copy.json", "homepage/brief.json", why="the deck is checked after copy_check_draft")
    report = wc.check_deck(v2.load(root / "homepage/copy/copy.json"), v2.load(root / "homepage/brief.json"))
    (root / "homepage/copy/words.json").write_text(wc.dump(report), encoding="utf-8")
    return {"status": "completed", "words_path": "homepage/copy/words.json", "findings": len(report["findings"]),
            "counts": report["counts"]}


def page_words(root: Path) -> dict:
    _require(root, "review/page-text.md", "homepage/copy/copy.json", "homepage/brief.json",
             why="the page is checked after runtime (or page_prepare)")
    lines = wc.read_page_text(root / "review/page-text.md")
    report = wc.check_page(lines, v2.load(root / "homepage/copy/copy.json"), v2.load(root / "homepage/brief.json"))
    (root / "review/words.json").write_text(wc.dump(report), encoding="utf-8")
    return {"status": "completed", "words_path": "review/words.json", "findings": len(report["findings"]),
            "counts": report["counts"]}


# --------------------------------------------------------------------------- merge_join (H4, H5)

# What each measured check means for a visitor, and the fix; the numbers stay in evidence.
PROBLEMS: dict[str, tuple[str, str]] = {
    "text-contrast": ("Text contrast is below the WCAG 2.2 AA minimum (4.5:1, or 3:1 for large text).",
                      "Darken the text or lighten its background until every listed pair meets the minimum."),
    "text-over-image": ("Text over a picture has too little contrast with what is behind it.",
                        "Put a solid or dimmed backdrop behind the text, or move it off the picture."),
    "non-text-contrast": ("A control's boundary or fill has less than 3:1 contrast with what is around it.",
                          "Give the control a boundary or fill with at least 3:1 contrast."),
    "reflow": ("The page scrolls sideways at this width: content does not reflow.",
               "Let the listed elements wrap or shrink so nothing runs past the screen."),
    "target-size": ("A click or tap target is under 24 by 24 px and too close to its neighbours.",
                    "Make the target at least 24 by 24 px, or space it so a 24 px circle around it clears the next."),
    "labels": ("A control has no accessible name or label.",
               "Give each listed control a visible label tied to it, or an accessible name."),
    "text-alt": ("A picture that carries meaning has no text alternative.",
                 "Add alt text saying what the picture shows, or mark it decorative if it carries nothing."),
    "focus-visible": ("Keyboard focus is not visible on these controls.",
                      "Give every focusable control a visible focus style (an outline or ring) with 3:1 contrast."),
    "long-lines": ("Lines of body text run past 90 characters.",
                   "Cap the text column so lines stay between 45 and 90 characters."),
    "nav-fit": ("The navigation does not fit on one line at phone width.",
                "Put the navigation behind a menu button, or shorten it, so the header stays one row."),
    "first-screen-action": ("The primary action is not in the first screen.",
                            "Move the primary action, or a copy of it, into the first screen."),
    "signifier": ("Links or buttons show no cue that they can be clicked.",
                  "Give clickable text a cue: an underline, a button shape or an arrow."),
    "dark-small-text": ("Small light text on a dark background is hard to read.",
                        "Raise the small text's size or weight, or its contrast."),
    "repeated-copy": ("The same copy repeats across sections.",
                      "Say each thing once, where it does its job; cut or rewrite the repeats."),
}
AXE = ("axe-core: {help}.", "Fix each listed element as the axe rule explains.")
SHOWN = 6  # members or elements written out in one finding; the rest are counted


def _short(value: Any) -> str | None:
    if value is None or isinstance(value, dict):
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = " ".join(value.split())
        return text if len(text) <= 80 else text[:77] + "..."
    if isinstance(value, list) and value and len(value) <= 6 and all(
            isinstance(x, (int, float, str)) and not isinstance(x, bool) for x in value):
        if all(isinstance(x, (int, float)) for x in value):
            return "x".join(str(x) for x in value)
        return ", ".join(str(x) for x in value)
    return None


def _member_evidence(f: dict) -> str:
    ev = f.get("evidence") if isinstance(f.get("evidence"), dict) else {}
    parts = [f"{k} {s}" for k, v in ev.items() if (s := _short(v)) is not None]
    return f"[{f.get('viewport')}] {f.get('element') or 'the page'}: " + "; ".join(parts)


def _listed(items: list[str], what: str) -> str:
    shown = "; ".join(items[:SHOWN])
    return f"{len(items)} {what}: {shown}" + (f"; and {len(items) - SHOWN} more" if len(items) > SHOWN else "")


def _captured(review: Path) -> dict[str, list[str]]:
    cap = v2.load(review / "capture.json") if (review / "capture.json").is_file() else {}
    return {p.get("page"): [v.get("viewport") for v in p.get("views") or []] for p in cap.get("pages") or []}


def _answers(rows: Any, key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        answer = str(row.get("answer", "")).strip().lower()
        if row.get(key) and answer in ("yes", "no"):
            out[str(row[key])] = {"answer": answer, "evidence": str(row.get("evidence", ""))}
    return out


def apply_asks(findings: list[dict], answers: dict[str, dict]) -> list[dict]:
    """The merge's yes/no on 'is this the page's primary action?': a yes sets the level the script named."""
    rows = []
    for f in findings:
        ask = f.get("ask")
        if not isinstance(ask, dict):
            continue
        got = answers.get(f["id"])
        row = {"finding": f["id"], "question": ask.get("question"), "if_yes": ask.get("if_yes"),
               "level_before": f["severity"], "answer": got["answer"] if got else None,
               "evidence": got["evidence"] if got else ""}
        if got and got["answer"] == "yes" and isinstance(ask.get("if_yes"), int):
            f["severity"] = ask["if_yes"]
            f["grade"] = mf.grade(f["check"], f["severity"], f["evidence"], f.get("criterion", ""))
        row["level"] = f["severity"]
        rows.append(row)
    return rows


def group_measured(findings: list[dict], captured: dict[str, list[str]]) -> list[dict]:
    """One finding per problem: the same check on the same page at the same level, every element listed."""
    groups: dict[tuple, list[dict]] = {}
    for f in findings:
        groups.setdefault((f["page"], f["check"], f["severity"]), []).append(f)

    def rank(key: tuple) -> tuple:
        page, check, severity = key
        order = mf.CHECK_ORDER.index(check) if check in mf.CHECK_ORDER else len(mf.CHECK_ORDER)
        return (-severity, order, check, list(captured).index(page) if page in captured else len(captured), page)

    out = []
    for n, key in enumerate(sorted(groups, key=rank), 1):
        page, check, severity = key
        members = groups[key]
        vps = list(dict.fromkeys(f["viewport"] for f in members))
        views = captured.get(page) or []
        viewport = "all" if len(views) > 1 and set(vps) == set(views) else ", ".join(vps)
        elements = [e for e in dict.fromkeys(f.get("element") or "" for f in members) if e]
        element = elements[0] if len(elements) == 1 else (_listed(elements, "elements") if elements else
                                                            f"the page ({check})")
        if check.startswith("axe:"):
            help_text = (members[0].get("evidence") or {}).get("help") or check[4:]
            problem, suggestion = AXE[0].format(help=str(help_text).rstrip(".")), AXE[1]
        else:
            problem, suggestion = PROBLEMS.get(check, (f"Measured problem: {check}.", "Fix each listed element."))
        grades = {f.get("grade") for f in members}
        out.append({
            "id": f"M{n}", "status": "confirmed", "page": page, "viewport": viewport, "element": element,
            "problem": problem,
            "evidence": "measured.json: " + _listed([_member_evidence(f) for f in members], "measured"),
            "criterion": members[0].get("criterion", ""), "kind": "measured", "severity": severity,
            "found_by": ["script"], "source_ids": [f"measured:{f['id']}" for f in members],
            "suggestion": suggestion, "check": check, "evidence_ids": [],
            "grade": next((g for g in ("Must", "Should", "Could") if g in grades), "Could"),
            "rules": sorted({f.get("rule", "") for f in members} - {""}),
            "measured_ids": [f["id"] for f in members],
            **({"raised": members[0]["raised"]} if members[0].get("raised") else {}),
        })
    return out


def _cover(groups: list[dict], covered: Any) -> list[dict]:
    """Critic findings the merge says restate a measured one: credited on that finding, never repeated."""
    by_id = {mid: g for g in groups for mid in g["measured_ids"]}
    by_id.update({g["id"]: g for g in groups})
    unknown = []
    for row in covered if isinstance(covered, list) else []:
        if not isinstance(row, dict):
            continue
        group = by_id.get(str(row.get("measured_id", "")))
        if group is None:
            unknown.append(row)
            continue
        for sid in row.get("source_ids") or []:
            if sid not in group["source_ids"]:
                group["source_ids"].append(sid)
            critic = str(sid).split(":")[0]
            if critic and critic not in group["found_by"]:
                group["found_by"].append(critic)
    return unknown


def _severity_counts(findings: list[dict]) -> dict[str, int]:
    return {str(s): sum(f.get("severity") == s for f in findings) for s in (4, 3, 2, 1)}


def _cell(text: Any) -> str:
    return " ".join(str(text or "").split()).replace("|", "/")


def merge_join(review: Path) -> dict:
    _require(review, "verify.json",
             why="review_verify runs before the merge (H4: the merge never does the facts check itself)")
    _require(review, "measured.json", why="the measured step runs before the merge")
    _require(review, "merge.json", why="the merge wrote nothing")
    measured_res, merge, verify = (v2.load(review / n) for n in ("measured.json", "merge.json", "verify.json"))
    judged = merge.get("findings")
    if not isinstance(judged, list):
        raise ValueError("review/merge.json has no findings list")
    asks = apply_asks(measured_res["findings"], _answers(merge.get("answers"), "finding"))
    asked = {r["finding"] for r in asks}
    stray = [a for a in _answers(merge.get("answers"), "finding") if a not in asked]
    captured = _captured(review)
    groups = group_measured(measured_res["findings"], captured)
    unknown = _cover(groups, merge.get("covered"))
    findings = sorted(groups + [f for f in judged if isinstance(f, dict)],
                      key=lambda f: (f.get("status") != "confirmed", -int(f.get("severity") or 0),
                                     f.get("kind") != "measured"))
    rejected = merge.get("rejected") if isinstance(merge.get("rejected"), list) else []
    # Empty columns stay with craft, never usability findings here. H12 settles the answer when captured
    # on the candidate path; old captures without a vacancy measurement remain unanswered.
    candidates = [{"id": c["id"], "page": c["page"], "viewport": c["viewport"], "element": c["element"],
                   "if_yes": c["if_yes"], "answer": c.get("answer"), "reason": c.get("reason")}
                  for c in mf.craft_candidates(review, measured_res.get("primary_action"))]
    summary = {
        "version": measured_res.get("version"), "primary_action": measured_res.get("primary_action"),
        "findings": len(measured_res["findings"]), "groups": len(groups),
        "counts": {g: sum(f["grade"] == g for f in measured_res["findings"]) for g in ("Must", "Should", "Could")},
        "asks": asks, "stray_answers": stray, "left_to_craft_review": candidates,
    }
    result = {**{k: v for k, v in merge.items() if k not in ("findings", "answers")},
              "findings": findings, "rejected": rejected, "measured": summary,
              "covered": merge.get("covered") or [], "covered_unknown": unknown,
              "verify": verify.get("summary", {}), "judged_by_merge_as_measured":
                  [f.get("id") for f in judged if isinstance(f, dict) and f.get("kind") == "measured"],
              "joined_by": f"{JOINED_BY} merge_join"}
    _write_json(review / "findings.json", result)

    lines = ["# Review report", "",
             "Measured problems come from the script (review/measured.json): one finding per problem, at the level "
             "its rules set. The reviewers' judged findings follow, as the merge wrote them.", "",
             "## Measured by the script", ""]
    if groups:
        lines += ["| id | level | page | viewport | check | element | problem |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {g['id']} | {g['severity']} | {_cell(g['page'])} | {_cell(g['viewport'])} | {_cell(g['check'])} "
                  f"| {_cell(g['element'])} | {_cell(g['problem'])} |" for g in groups]
    else:
        lines.append("Nothing measured failed.")
    if asks:
        lines += ["", "Is it the page's primary action? (the brief names none; the merge answered, the script set the level)", ""]
        lines += [f"- {r['finding']}: {r['answer'] or 'not answered'} -> level {r['level']}"
                  + (f" ({_cell(r['evidence'])})" if r["evidence"] else "") for r in asks]
    if merge.get("covered"):
        lines += ["", "Reviewer findings that restate a measured problem (kept once, under it):", ""]
        lines += [f"- {', '.join(map(str, c.get('source_ids') or []))} -> {c.get('measured_id')}"
                  for c in merge["covered"] if isinstance(c, dict)]
    if candidates:
        lines += ["", "Left to the craft review (empty columns: the page check's measured vacancy answer; "
                  "not findings here):", ""]
        lines += [f"- {c['id']}: [{c['viewport']}] {_cell(c['element'])} (level {c['if_yes']} if confirmed); "
                  f"{c['answer'] or 'not measured'} ({c['reason'] or 'no vacancy measurement'})" for c in candidates]
    judged_md = review / "report-judged.md"
    lines += ["", "---", "", judged_md.read_text(encoding="utf-8") if judged_md.is_file()
              else "(The merge wrote no report-judged.md.)"]
    (review / "report.md").write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return {"status": "completed", "report_path": "review/report.md", "findings_path": "review/findings.json",
            "critics": merge.get("critics", []),
            "confirmed": sum(f.get("status") == "confirmed" for f in findings),
            "single": sum(f.get("status") == "single" for f in findings),
            "rejected": len(rejected), "dropped_by_facts": sum(bool(r.get("by_facts")) for r in rejected
                                                              if isinstance(r, dict)),
            "severity_counts": _severity_counts(findings), "measured": len(measured_res["findings"]),
            "measured_groups": len(groups), "asks_answered": sum(r["answer"] is not None for r in asks),
            "asks_unanswered": sum(r["answer"] is None for r in asks), "covered": len(merge.get("covered") or []),
            "covered_unknown": len(unknown), "left_to_craft_review": len(candidates)}


# --------------------------------------------------------------------------- craft_join (H5, H6)

ANCHOR_TEXT: dict[str, tuple[str, str]] = {
    "spacing-grid": ("Spacing is off one scale: too few spacing values sit on a 4 px grid",
                     "Put margins, padding and gaps on one 4 px (or 8 px) spacing scale."),
    "scale-ratio": ("The type scale is flat: the largest text is not clearly bigger than body text",
                    "Raise the display size (about 3x body) or calm the body size, so the first read is clear."),
    "text-sizes": ("Too many distinct text sizes for one page",
                   "Collapse near-duplicate sizes onto one type scale of a few steps."),
    "font-loading": ("A font the page names did not load, so a fallback shows",
                     "Ship the font files the page names, or name a font that loads."),
}


def _percent(share: Any) -> str:
    return f"{round(share * 100)}%" if isinstance(share, (int, float)) and share <= 1 else str(share)


def craft_join(review: Path) -> dict:
    _require(review, "anchors.json", why="craft_anchors runs before the craft critic")
    _require(review, "craft-critic.json", why="the craft critic wrote nothing")
    anchors, critic = v2.load(review / "anchors.json"), v2.load(review / "craft-critic.json")
    if not isinstance(critic.get("findings"), list):
        raise ValueError("review/craft-critic.json has no findings list")
    findings = []
    for f in anchors.get("findings") or []:
        lead, suggestion = ANCHOR_TEXT.get(f.get("rule"), ("Measured craft problem", "Fix it."))
        findings.append({"id": f["id"], "check": f["check"], "viewport": f["viewport"], "element": f["element"],
                         "problem": f"{lead} ({f['evidence']}).", "evidence": f["evidence"],
                         "severity": f["severity"], "confidence": "high", "suggestion": suggestion,
                         "kind": "anchored", "rule": f["rule"], "metric": f.get("metric"), "value": f.get("value"),
                         "threshold": f.get("threshold"), "width": f.get("width"), "page": f.get("page")})
    rows, n = [], 0
    for c in mf.craft_candidates(review):
        v = c.get("vacancy") or {}
        answer = v.get("answer") if v.get("answer") in ("yes", "no") else None
        evidence = mf.vacancy_text(v) if v else "No vacancy measurement; re-capture on the candidate path."
        rows.append({"candidate": c["id"], "element": c["element"], "viewport": c["viewport"],
                     "if_yes": c["if_yes"], "answer": answer, "reason": v.get("reason"), "evidence": evidence})
        if answer != "yes":
            continue
        n += 1
        ev = c.get("evidence") or {}
        findings.append({
            "id": f"craft-empty-column-{n}", "check": "space", "viewport": c["viewport"], "element": c["element"],
            "problem": (f"Dead empty column: {ev.get('width')} px ({_percent(ev.get('share'))} of the content width), "
                        f"{ev.get('height')} px tall, on the {ev.get('side')} of {ev.get('section')}."),
            "evidence": f"facts.md empty-column (measured, {c['id']}); the page check's vacancy: {evidence}",
            "severity": c["if_yes"], "confidence": "high",
            "suggestion": "Give the column content that earns its place, or let the content use the width.",
            "kind": "candidate", "rule": c.get("rule", "craft-empty-column"), "measured_id": c["id"],
            "page": c.get("page")})
    critic_findings = [f for f in critic["findings"] if isinstance(f, dict)]
    findings += critic_findings
    result = {**{k: v for k, v in critic.items() if k not in ("findings", "candidate_answers", "severity_counts")},
              "critic": critic.get("critic") or "craft", "findings": findings,
              "severity_counts": _severity_counts(findings),
              "anchors": {"version": anchors.get("version"), "findings": len(anchors.get("findings") or []),
                          "checks": anchors.get("checks") or []},
              "candidates": rows, "joined_by": f"{JOINED_BY} craft_join"}
    _write_json(review / "craft" / "craft.json", result)
    return {"status": "completed", "findings_path": "review/craft/craft.json", "findings": len(findings),
            "severity_counts": result["severity_counts"], "anchored": len(anchors.get("findings") or []),
            "candidates_confirmed": n, "candidates_declined": sum(r["answer"] == "no" for r in rows),
            "candidates_unanswered": sum(r["answer"] is None for r in rows), "critic_findings": len(critic_findings)}


# --------------------------------------------------------------------------- word joins (H7)


def word_text(f: dict) -> tuple[str, str]:
    """problem, suggestion for one word finding; its numbers stay in evidence."""
    text, rule = str(f.get("text") or ""), f.get("rule")
    if rule == "cta_length":
        return (f"The call to action \"{text}\" is too long for a button ({f.get('evidence')}).",
                "Cut it to a short verb phrase, 40 characters or fewer, that says what happens.")
    if rule == "cta_verb":
        return (f"The call to action \"{text}\" does not start with an action verb, so it does not say what happens.",
                "Start it with a verb that names what happens next.")
    if rule == "unsourced_name":
        return (f"\"{text}\" names something no brief fact, product name or deck text holds.",
                "Use the name the brief gives, or drop the name.")
    if rule == "long_paragraph":
        return (f"This paragraph runs past three lines at 1440 px ({f.get('evidence')}).",
                "Split it, lead with the key fact, or turn it into a short list.")
    if rule == "renamed_term" and f.get("field"):  # deck mode: the brief's name renamed in the deck
        return (f"The brief's name \"{f.get('term')}\" appears in the deck as \"{text}\".",
                f"Use the brief's name \"{f.get('term')}\" wherever the deck means it.")
    if rule == "renamed_term":
        return (f"The deck's term \"{f.get('term')}\" appears on the page as \"{text}\".",
                f"Use the deck's term \"{f.get('term')}\" wherever the page means it.")
    return (str(f.get("evidence") or rule), "Fix it as the word check explains.")


def _word_finding(f: dict, element: str, quote: str) -> dict:
    problem, suggestion = word_text(f)
    return {"id": f["id"], "check": f["check"], "severity": f["severity"], "element": element, "quote": quote,
            "problem": problem, "suggestion": suggestion, "evidence": f.get("evidence", ""), "kind": "word",
            "rule": f["rule"], "grade": f.get("grade")}


def page_quote(f: dict, lines: list[dict], page_text: str) -> str:
    """Text that is on the page as one piece (combine keeps a content finding only when its quote is)."""
    text = str(f.get("text") or "")
    if text and v2.norm_text(text) in v2.norm_text(page_text):
        return text
    n = f.get("line")
    if isinstance(n, int) and 1 <= n <= len(lines):
        return lines[n - 1]["text"]
    return text


def content_join(review: Path) -> dict:
    _require(review, "words.json", why="page_words runs before the content critic")
    _require(review, "content-critic.json", why="the content critic wrote nothing")
    _require(review, "page-text.md")
    words, critic = v2.load(review / "words.json"), v2.load(review / "content-critic.json")
    if not isinstance(critic.get("findings"), list):
        raise ValueError("review/content-critic.json has no findings list")
    page_text = (review / "page-text.md").read_text(encoding="utf-8")
    lines = wc.read_page_text(review / "page-text.md")
    found = [_word_finding(f, f.get("element") or "page", page_quote(f, lines, page_text))
             for f in words.get("findings") or []]
    critic_findings = [f for f in critic["findings"] if isinstance(f, dict)]
    result = {**{k: v for k, v in critic.items() if k != "findings"}, "findings": found + critic_findings,
              "words": {"version": words.get("version"), "findings": len(found), "counts": words.get("counts")},
              "joined_by": f"{JOINED_BY} content_join"}
    _write_json(review / "content" / "content.json", result)
    return {"status": "completed", "findings_path": "review/content/content.json",
            "findings": len(result["findings"]), "words": len(found), "critic_findings": len(critic_findings)}


CONTRACT = {"cta_verb": "does not say what happens", "cta_length": "; say the action in 5 or fewer"}


def contract_covers(f: dict, problems: list[str]) -> str | None:
    """The copy_contract problem (check.json) that already names this word finding's problem, if any."""
    marker, field = CONTRACT.get(f.get("rule", "")), str(f.get("field") or "")
    if not marker or not field.startswith("ctas."):
        return None
    return next((p for p in problems if isinstance(p, str) and p.startswith(f"{field}: ") and marker in p), None)


def copy_review_join(root: Path) -> dict:
    copy = root / "homepage" / "copy"
    _require(copy, "words.json", why="deck_words runs before the content critic")
    _require(copy, "review-critic.json", why="the content critic wrote nothing")
    words, critic = v2.load(copy / "words.json"), v2.load(copy / "review-critic.json")
    if not isinstance(critic.get("findings"), list):
        raise ValueError("homepage/copy/review-critic.json has no findings list")
    check = v2.load(copy / "check.json") if (copy / "check.json").is_file() else {}
    problems = check.get("problems") if isinstance(check.get("problems"), list) else []
    found, covered = [], []
    for f in words.get("findings") or []:
        by = contract_covers(f, problems)
        if by:
            covered.append({"finding": f["id"], "covered_by": by})
            continue
        found.append(_word_finding(f, str(f.get("field") or "deck"), str(f.get("text") or "")))
    critic_findings = [f for f in critic["findings"] if isinstance(f, dict)]
    result = {**{k: v for k, v in critic.items() if k != "findings"}, "findings": found + critic_findings,
              "words": {"version": words.get("version"), "findings": len(found), "counts": words.get("counts"),
                        "covered_by_contract": covered},
              "joined_by": f"{JOINED_BY} copy_review_join"}
    _write_json(copy / "review.json", result)
    return {"status": "completed", "review_path": "homepage/copy/review.json", "findings": len(result["findings"]),
            "words": len(found), "covered_by_contract": len(covered), "critic_findings": len(critic_findings)}


# --------------------------------------------------------------------------- benchmark twins (W10, W11)


def bench_collect(root: Path) -> dict:
    result = cb.collect(root)
    path = root / "review" / "measured.json"
    if path.is_file():
        res = v2.load(path)
        checks: dict[str, int] = {}
        for f in res["findings"]:
            checks[f["check"]] = checks.get(f["check"], 0) + 1
        result.update(measured_path="review/measured.json", measured=len(res["findings"]), measured_checks=checks)
    return result


def _deck(raw: str) -> dict:
    try:
        deck = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"the deck (data) is not JSON: {exc}") from exc
    if not isinstance(deck, dict) or not deck:
        raise ValueError("the deck (data) must be a JSON object")
    return deck


def _seed_deck(root: Path, deck: dict) -> Path:
    target = root / "homepage" / "copy" / "copy.json"
    if target.exists() and v2.load(target) != deck:
        raise ValueError("homepage/copy/copy.json already holds another deck; use a fresh workspace")
    _write_json(target, deck)
    return target


def copy_seed(root: Path, raw: str) -> dict:
    _require(root, "homepage/brief.json", why="the brief stage runs first")
    target = _seed_deck(root, _deck(raw))
    return {"status": "completed", "copy_path": "homepage/copy/copy.json",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "fields": len(v2.deck_fields(v2.load(target)))}


def page_prepare(root: Path, site: str, raw: str) -> dict:
    _require(root, "homepage/brief.json", why="the brief stage runs first")
    src = Path(site) if site else None
    if src is None or not (src / "index.html").is_file():
        raise ValueError("page_prepare needs --site, a folder holding index.html")
    target, review = root / "homepage" / "site", root / "review"
    if target.exists() or review.exists():
        raise ValueError("this workspace already holds a page; use a fresh workspace per run")
    brief = v2.load(root / "homepage/brief.json")
    if raw:
        _seed_deck(root, _deck(raw))
    _require(root, "homepage/copy/copy.json", why="give the approved deck as data")
    deck = v2.load(root / "homepage/copy/copy.json")
    (root / "homepage/copy/COPY.md").write_text(v2.render_copy(deck, brief, "Copy deck (approved)"), encoding="utf-8")
    shutil.copytree(src, target)
    cmd = [sys.executable, str(HERE / "design_capture.py"), "--out", str(review), "--site", str(target),
           "--pages", "index.html", "--viewports", "desktop,mobile", "--browser", v2.BROWSER]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if done.returncode != 0:
        raise ValueError("capture failed: " + (done.stderr or done.stdout)[-600:])
    rtc.write_outputs(rtc.measure(target, "index.html", v2.BROWSER, v2.SERVE_HOST), review / "runtime")
    shutil.copyfile(review / "runtime" / "page-text.md", review / "page-text.md")
    for name in ("critic", "craft", "content"):
        (review / name).mkdir(exist_ok=True)
    return {"status": "completed", "site": "homepage/site", "page_text": "review/page-text.md",
            "shots": len(list((review / "shots").glob("*.png"))), "copy_path": "homepage/copy/copy.json"}


# --------------------------------------------------------------------------- command line


def run(stage: str, root: Path, args: argparse.Namespace, raw: str) -> dict:
    review = root / "review"
    if stage == "measure":
        return measure(v2.Job(root, args.fixture, pilot=args.pilot, bench=args.bench), review)
    simple = {"measured": lambda: measured(review), "craft_anchors": lambda: craft_anchors(review),
              "deck_words": lambda: deck_words(root), "page_words": lambda: page_words(root),
              "merge_join": lambda: merge_join(review), "craft_join": lambda: craft_join(review),
              "content_join": lambda: content_join(review), "copy_review_join": lambda: copy_review_join(root),
              "bench_prepare": lambda: bench_prepare(root, args.site, args.page),
              "bench_collect": lambda: bench_collect(root), "copy_seed": lambda: copy_seed(root, raw),
              "page_prepare": lambda: page_prepare(root, args.site, raw)}
    return simple[stage]()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stage", choices=STAGES)
    ap.add_argument("--workspace", required=True)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fixture", action="store_true")
    mode.add_argument("--pilot", action="store_true")
    mode.add_argument("--bench", action="store_true")
    ap.add_argument("--site", default="", help="bench_prepare: the test site; page_prepare: the built page's folder")
    ap.add_argument("--page", default="", help="bench_prepare: the test page")
    ap.add_argument("--browser", default=None)
    ap.add_argument("--serve-host", default=None)
    args = ap.parse_args(argv)
    if args.browser:
        v2.BROWSER = args.browser
    if args.serve_host:
        v2.SERVE_HOST = args.serve_host
    started = time.monotonic()
    root = Path(args.workspace).resolve()
    try:
        result = run(args.stage, root, args, os.environ.get("HOMEPAGE_DATA", ""))
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        raise SystemExit(f"{args.stage}: {exc}") from exc
    result["seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
