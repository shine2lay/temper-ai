#!/usr/bin/env python3
"""design_review_verify_next (design role): the critics' claims checked against the measured facts.

Candidate step of workflows/design_review_next.yaml (queue #7, review precision); no model. It runs
after the critics and before the merge. For every critic finding (review/critic/*.json) it:

  - checks target-size failure claims (WCAG 2.5.8, "too small to tap"): an element the facts
    measure as passing (through its label, or by the spacing exception) contradicts the claim on
    that page and viewport; an element the facts list as failing supports it;
  - checks contrast failure claims (WCAG 1.4.3, 1.4.11) about an inactive (disabled) control:
    its text and borders have no contrast requirement, so the claim is contradicted unless the
    finding also names a failing text or boundary from the facts;
  - says whether the finding cites checkable evidence: the element, a page, and a screenshot tile
    that exists or a value the facts hold (a selector, a measured element, a size or ratio).

A claim is contradicted only by a measured pass, never by the absence of a measurement, and a
finding that itself grants the pass ("meets 2.5.8 by spacing", "exempt") makes no failure claim.
The verdict is about the size or contrast claim only: a finding may state other problems too.
Writes review/verify.json and prints a one-line JSON summary. design_merge_next drops the claims
the facts contradict and keeps a one-critic finding only when it is checkable.

    design_review_verify_next.py --review review
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

TARGET_RE = re.compile(
    r"2\.5\.8|2\.5\.5|target size|touch target|tap target|click target|hit (?:area|target)"
    r"|small target|too small to (?:tap|click|hit|press|touch)|hard to (?:tap|hit|click)"
    r"|(?:below|under|smaller than|less than) (?:the )?24|24\s*[x×]\s*24",
    re.I,
)
# A finding that itself says the target meets 2.5.8 is a usability point, not a failure claim.
TARGET_PASS_RE = re.compile(
    r"(?:meets|passes|satisf\w+|met)\b[^.;]{0,40}2\.5\.8|spacing exception|by (?:its |the )?spacing"
    r"|through (?:its|the) label",
    re.I,
)
CONTRAST_RE = re.compile(r"1\.4\.3|1\.4\.6|1\.4\.11|contrast", re.I)
# A finding that grants the exemption itself ("disabled controls are exempt") is a legibility point.
CONTRAST_PASS_RE = re.compile(
    r"\bexempt\b|exemption|technically (?:passes|allowed|fine)", re.I
)
TICK_RE = re.compile(r"`([^`]{2,200})`")
TILE_RE = re.compile(r"[\w./-]+\.png")
VALUE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*:\s*1\b|\d+\s*[x×]\s*\d+\s*(?:px)?|\d+(?:\.\d+)?\s*px", re.I
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def norm_sel(s: str) -> str:
    s = re.sub(r":nth-(?:of-type|child)\([^)]*\)|\[[^\]]*\]", "", s or "")
    return re.sub(r"\s*>\s*", " > ", norm(s))


def segs(s: str) -> list[str]:
    """A selector's compound parts, combinators dropped: 'main > div.a b' -> ['main', 'div.a', 'b']."""
    return [x for x in re.split(r"\s*>\s*|\s+", norm_sel(s)) if x]


def seg_match(t: str, f: str) -> bool:
    """Does the finding's compound selector t describe the facts' compound selector f?"""
    if t == f:
        return True
    t_tag, *t_cls = t.split(".")
    f_tag, *f_cls = f.split(".")
    if t_tag.startswith("#") or f_tag.startswith("#"):
        return t_tag == f_tag
    return (not t_tag or t_tag == f_tag) and set(t_cls) <= set(f_cls)


def selector_named(sel: str, ticks: list[str]) -> bool:
    """A backticked selector in the finding that describes the facts' selector: its last part
    matches the element, its earlier parts match ancestors in order (child or descendant)."""
    fs = segs(sel)
    for t in ticks:
        ts = segs(t)
        if not ts or not fs or (len(ts) == 1 and not re.search(r"[.#]", ts[0])):
            continue
        if not seg_match(ts[-1], fs[-1]):
            continue
        rest = iter(fs[:-1])
        if all(any(seg_match(a, b) for b in rest) for a in ts[:-1]):
            return True
    return False


def finding_text(f: dict) -> str:
    return " ".join(
        str(f.get(k) or "")
        for k in ("element", "problem", "evidence", "criterion", "suggestion")
    )


def claim_text(f: dict) -> str:
    """What the finding claims (the suggestion is a fix, not a claim)."""
    return " ".join(
        str(f.get(k) or "") for k in ("element", "problem", "evidence", "criterion")
    )


def pages_of(field: str, pages: list[str]) -> list[str]:
    s = norm(field)
    if s in ("all", "all pages", "every page", "*") or s.startswith("all "):
        return list(pages)
    hits = [p for p in pages if p.lower() in s]
    for p in pages:
        base = p.lower().rsplit("/", 1)[-1]
        if p not in hits and re.search(r"(?<![\w/-])" + re.escape(base) + r"(?!\w)", s):
            hits.append(p)
    return [p for p in pages if p in hits]


def viewports_of(field: str, available: list[str]) -> list[str]:
    s = norm(field)
    named = [v for v in available if v in s]
    return named if named and "all" not in s else list(available)


def mentions(
    entry: dict, text_l: str, ticks: list[str], name_key: str = "name"
) -> bool:
    """Does the finding name this measured element (selector, id, or its accessible name)?"""
    sel = entry.get("sel") or ""
    if sel and sel.lower() in text_l:
        return True
    ids = re.findall(r"#[\w-]+", sel)
    if any(re.search(re.escape(i.lower()) + r"(?![\w-])", text_l) for i in ids):
        return True
    if sel and selector_named(sel, ticks):
        return True
    name = norm(entry.get(name_key) or "")
    if len(name) >= 3 and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text_l):
        return True
    return False


def text_named(t: dict, subject_l: str, ticks: list[str]) -> bool:
    """Does the finding's subject name this measured text (its selector, or its first words)?"""
    if mentions({"sel": t.get("sel")}, subject_l, ticks):
        return True
    words = norm(t.get("text") or "")[:24].strip()
    return len(words) >= 4 and words in subject_l


def load(review: pathlib.Path) -> tuple[list[str], dict, list[dict]]:
    capture = json.loads((review / "capture.json").read_text(encoding="utf-8"))
    pages = [p["page"] for p in capture.get("pages", [])]
    views: dict[tuple[str, str], dict] = {}
    for p in capture.get("pages", []):
        for v in p.get("views", []):
            views[(p["page"], v["viewport"])] = json.loads(
                (review / v["facts"]).read_text(encoding="utf-8")
            )
    critics = []
    for path in sorted((review / "critic").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            critics.append(
                {
                    "critic": path.stem,
                    "findings": [],
                    "error": f"unreadable: {exc}"[:200],
                }
            )
            continue
        critics.append(
            {
                "critic": str(data.get("critic") or path.stem),
                "findings": data.get("findings") or [],
            }
        )
    return pages, views, critics


def check_targets(f: dict, pages: list[str], vps: list[str], views: dict) -> list[dict]:
    text = claim_text(f)
    if not TARGET_RE.search(text) or TARGET_PASS_RE.search(text):
        return []
    text_l, ticks = text.lower(), TICK_RE.findall(text)
    out = []
    for page in pages:
        for vp in vps:
            facts = views.get((page, vp)) or {}
            for e in facts.get("small_targets") or []:
                if mentions(e, text_l, ticks):
                    out.append(
                        {
                            "claim": "target size (WCAG 2.5.8)",
                            "page": page,
                            "viewport": vp,
                            "element": f'`{e["sel"]}` "{e.get("name", "")}"',
                            "result": "supported",
                            "fact": f"measured {e['box'][2]}x{e['box'][3]} px and too close to another target",
                        }
                    )
            for e in facts.get("targets_pass") or []:
                if mentions(e, text_l, ticks):
                    if e.get("passes") == "label":
                        lb = e.get("label_box") or [0, 0, 0, 0]
                        why = f"meets 2.5.8 through its label: label {lb[2]}x{lb[3]} px"
                    else:
                        n = e.get("nearest") or {}
                        why = (
                            "meets 2.5.8 by the spacing exception: nearest other target "
                            f"{n.get('edge', '?')} px from its centre (needs 12)"
                        )
                    out.append(
                        {
                            "claim": "target size (WCAG 2.5.8)",
                            "page": page,
                            "viewport": vp,
                            "element": f'`{e["sel"]}` "{e.get("name", "")}"',
                            "result": "contradicted",
                            "fact": f"control {e['box'][2]}x{e['box'][3]} px {why}",
                        }
                    )
    return out


def check_contrast(
    f: dict, pages: list[str], vps: list[str], views: dict
) -> list[dict]:
    """Contrast claims about an inactive (disabled) control, which WCAG exempts. Only the finding's
    subject (its element field) counts, so a control quoted as context never decides the check."""
    text = claim_text(f)
    crit = str(f.get("criterion") or "") + " " + str(f.get("problem") or "")
    if not CONTRAST_RE.search(crit) or CONTRAST_PASS_RE.search(text):
        return []
    subject = str(f.get("element") or "")
    subject_l, ticks = subject.lower(), TICK_RE.findall(subject)
    out = []
    for page in pages:
        for vp in vps:
            facts = views.get((page, vp)) or {}
            disabled = [
                c
                for c in facts.get("controls") or []
                if c.get("disabled") and mentions(c, subject_l, ticks)
            ]
            if not disabled:
                continue
            failing = [
                t
                for t in facts.get("contrast_failures") or []
                if text_named(t, subject_l, ticks)
            ]
            failing += [
                b
                for b in facts.get("weak_boundaries") or []
                if mentions(b, subject_l, ticks)
            ]
            for x in failing:
                out.append(
                    {
                        "claim": "contrast (WCAG 1.4.3/1.4.11)",
                        "page": page,
                        "viewport": vp,
                        "element": f"`{x['sel']}`",
                        "result": "supported",
                        "fact": "the facts list it as a contrast failure",
                    }
                )
            if failing:
                continue
            for c in disabled:
                out.append(
                    {
                        "claim": "contrast (WCAG 1.4.3/1.4.11)",
                        "page": page,
                        "viewport": vp,
                        "element": f'`{c["sel"]}` "{c.get("name", "")}"',
                        "result": "contradicted",
                        "fact": "an inactive (disabled) control: its text and borders have no contrast requirement",
                    }
                )
    return out


def checkable(
    f: dict, pages: list[str], checks: list[dict], views: dict, shots: set[str]
) -> tuple[bool, str]:
    text = finding_text(f)
    if len(str(f.get("element") or "").strip()) < 3:
        return False, "no element named"
    if not pages:
        return False, "page not among the reviewed pages"
    tiles = {m.rsplit("/", 1)[-1] for m in TILE_RE.findall(text)}
    # Tiles cited by name, with or without ".png" ("rooms-desktop-1").
    real = sorted(
        {t for t in tiles if t in shots}
        | {
            s
            for s in shots
            if re.search(r"(?<![\w-])" + re.escape(s[:-4]) + r"(?![\w])", text)
        }
    )
    if real:
        return True, "screenshot tile " + ", ".join(real[:4])
    if checks:
        return True, "a measured element"
    text_l, ticks = text.lower(), TICK_RE.findall(text)
    for page in pages:
        for (p, _vp), facts in views.items():
            if p != page:
                continue
            for k in MEASURED_LISTS:
                for e in facts.get(k) or []:
                    if (
                        isinstance(e, dict)
                        and e.get("sel")
                        and (
                            e["sel"].lower() in text_l
                            or selector_named(e["sel"], ticks)
                        )
                    ):
                        return True, f"a selector from the facts ({k})"
    if VALUE_RE.search(str(f.get("evidence") or "")):
        return True, "a measured value"
    if tiles:
        return False, "cited tile(s) not in review/shots: " + ", ".join(
            sorted(tiles)[:4]
        )
    return False, "no screenshot tile or facts value cited"


MEASURED_LISTS = (
    "contrast_failures",
    "contrast_exempt",
    "small_targets",
    "targets_pass",
    "weak_boundaries",
    "unnamed_graphics",
    "long_lines",
    "overflowing",
    "no_focus_ring",
    "tab_stops",
    "fields",
    "controls",
    "largest_text",
)


def verdict(checks: list[dict]) -> tuple[str, list[str], list[str]]:
    """(verdict, pages whose claim the facts contradict, pages they support)."""
    if not checks:
        return "not checked", [], []
    by_page: dict[str, set[str]] = {}
    for c in checks:
        by_page.setdefault(c["page"], set()).add(c["result"])
    contra = sorted(p for p, r in by_page.items() if r == {"contradicted"})
    support = sorted(p for p, r in by_page.items() if "supported" in r)
    if contra and not support:
        return "contradicted", contra, support
    if contra:
        return "partly contradicted", contra, support
    return "supported", contra, support


def verify(review: pathlib.Path) -> dict:
    pages, views, critics = load(review)
    available = sorted({vp for (_p, vp) in views})
    shots = {p.name for p in (review / "shots").glob("*.png")}
    rows = []
    for c in critics:
        for f in c["findings"]:
            if not isinstance(f, dict):
                continue
            fpages = pages_of(str(f.get("page") or ""), pages)
            vps = viewports_of(str(f.get("viewport") or ""), available)
            checks = check_targets(f, fpages, vps, views) + check_contrast(
                f, fpages, vps, views
            )
            v, contra, support = verdict(checks)
            ok, why = checkable(f, fpages, checks, views, shots)
            facts_lines = sorted(
                {
                    f"{x['page']} {x['viewport']}: {x['element']} {x['fact']}"
                    for x in checks
                    if x["result"] == "contradicted"
                }
            )
            rows.append(
                {
                    "source_id": f"{c['critic']}:{f.get('id', '?')}",
                    "page": f.get("page"),
                    "viewport": f.get("viewport"),
                    "kind": f.get("kind"),
                    "claims": sorted({x["claim"] for x in checks}),
                    "verdict": v,
                    "contradicted_pages": contra
                    if v == "partly contradicted"
                    else ([] if v != "contradicted" else contra),
                    "supported_pages": support,
                    "contradicting_facts": facts_lines[:8],
                    "checkable": ok,
                    "checkable_why": why,
                }
            )
    count = lambda key, val: sum(1 for r in rows if r[key] == val)  # noqa: E731
    return {
        "version": 1,
        "method": (
            "claims checked against review/facts (design_measure_next.js): target size (WCAG "
            "2.5.8) against measured failures and passes (label area, spacing exception), and "
            "contrast (1.4.3/1.4.11) claims about inactive (disabled) controls; a claim is "
            "contradicted only by a measured pass or exemption, never by a missing measurement; "
            "the verdict covers that claim only, not other problems the finding states"
        ),
        "critics": [c["critic"] for c in critics],
        "unreadable_critics": [c["critic"] for c in critics if c.get("error")],
        "summary": {
            "findings": len(rows),
            "contradicted": count("verdict", "contradicted"),
            "partly_contradicted": count("verdict", "partly contradicted"),
            "supported": count("verdict", "supported"),
            "not_checked": count("verdict", "not checked"),
            "not_checkable": count("checkable", False),
        },
        "findings": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--review", default="review")
    a = ap.parse_args(argv)
    review = pathlib.Path(a.review)
    result = verify(review)
    (review / "verify.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {"status": "completed", "verify_path": str(review / "verify.json")}
            | result["summary"]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
