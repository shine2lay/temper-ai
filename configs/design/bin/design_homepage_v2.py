#!/usr/bin/env python3
"""Design-owned homepage workflow v2: art-directed HTML/CSS, then editable Penpot.

v1 drew its pages from fixed templates, so it could only ever be tidy. v2 lets
models do what they do well, compose real web pages, and keeps Penpot as the
editable master by converting the rendered page (html_to_penpot.py).

Stages (one CLI, ``design_homepage_v2.py <stage> --workspace W``):

  brief           validate the brief, write homepage/BRIEF.md (+ copy assets)
  taste           the owner's taste file (a run input) -> homepage/TASTE.md
  copy_fixture    (fixture) stand-in copywriter draft, content review, revision
  copy_check      the copy deck's fixed rules (draft), then after the content
                  review: quotes checked, every blocking finding answered,
                  before/after written (final)
  copy_next       the final copy check's verdict, for the workflow's loop
  references      screenshot 8-12 acclaimed homepages, research only
  concepts_fixture  (model-free fixture) three hand-written concepts
  concepts_check  validate the art director's three concepts, fetch their
                  licensed fonts, render each at 1440 and 390, check they are
                  distinct and use the deck's words, and build the contact sheet
  direction       DIRECTION gate decision -> prepare site/, taste entry
  build_fixture   (fixture) the chosen concept becomes the page
  plan_round      round bookkeeping: build, or revise with a fix list
  revise_fixture  (fixture) a tiny scripted revision
  measure         capture + axe + measured facts for the critics, craft metrics
  runtime         keyboard, focus, names, 320 px reflow, 400% zoom, text
                  spacing, reduced motion and hover in a real browser (no model)
  review_fixture  (fixture) stand-in critic/merge/craft files
  content_fixture (fixture) stand-in content review of the page's words
  combine         merge usability/accessibility, craft, runtime and content
                  findings (content quotes checked against the page text),
                  decide revise (at most two automatic revisions) or done
  next_round      the decision, for the workflow's loop
  convert         HTML -> editable Penpot (fonts, colours, typographies, components)
  verify          fresh reopen + fidelity bar; fails visibly
  handoff         packet with manifest
  final           FINAL gate decision (approve or request changes), taste entry

Every completed stage leaves a receipt in homepage/job.json, keyed by its
inputs. Re-entry with the same inputs reuses the receipt (no repeated paid or
Penpot work); changed inputs for a completed stage fail instead of silently
repeating. Gate decisions are saved JSON only. Gates are named for what they
decide (direction, final); every answer records decided_by (design; owner only
for the owner's own words, kept verbatim; fixture-test in the fixture
workflow), the choice and its reasons. The pilot workflow (``--pilot``,
fictional briefs only) runs the real models and checks, but its direction is
the worker's provisional pick (decided_by design, provisional): never an
approval, never a taste entry. The benchmark workflow (``--bench``, fictional
briefs only; queue #10) runs the same models and checks with no gates: it
builds the art director's recommended concept (concepts.json "recommended")
and records the final as "benchmark_skipped", not approved; its pages are
judged blind on Design's scoreboard. Never a taste entry. Records written
before 2026-10-05 (approval owner-*, owner_* keys) still load: see
upgrade_state and gate_decided_by.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import html.parser
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import design_homepage_v1 as v1  # noqa: E402
import design_runtime_checks as rtc  # noqa: E402
import html_to_penpot as h2p  # noqa: E402

VERSION = 1
CONCEPT_IDS = ("A", "B", "C")
FIXTURE_SITE = HERE.parent / "testpages" / "html-fixtures"
FIXTURE_CONCEPTS = {"A": "atlas.html", "B": "pulse.html", "C": "harbor.html"}
# Overused faces that make AI pages look alike (handbook 2.11). A brand that
# really uses one may list it in brief.brand.fonts.
BANNED_FONTS = {"inter", "roboto", "open sans", "lato", "space grotesk", "arial", "helvetica",
                "helvetica neue", "system-ui", "-apple-system", "segoe ui", "times new roman",
                "georgia", "verdana", "montserrat", "poppins", "sans-serif", "serif", "monospace"}
# Type pairings earlier runs and the fixtures used (queue #34): a concept whose display + text pairing is
# recorded must pick a fresh one unless the brand owns both faces. The tracked seed is read-only at run
# time (configs are mounted read-only), so runs append to a shared log beside the workspaces.
PAIRING_SEED = HERE.parent / "knowledge" / "type-pairings.json"
# axe-core on every concept render (queue #34), with the same rules as the page measure (design_capture.py).
# Measured with reduced motion and, separately, with motion once the page's animations have ended:
# mid-animation measures gave 2-5 false contrast failures per page (#5).
AXE_SRC = HERE / "vendor" / "axe-4.13.0.min.js"
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
AXE_SETTLE_MS = 8000  # longest wait for a concept's load animations to end
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com", "raw.githubusercontent.com"}
LICENCE_URLS = (("ofl", "OFL.txt"), ("apache", "LICENSE.txt"), ("ufl", "UFL.txt"))
MAX_AUTO_REVISIONS = 2
MAX_CHANGE_ROUNDS = 2  # final-gate request_changes rounds per run
# Distinctness bars, fixed before any run: a pair of concepts must differ on all.
EXTERNAL_TIMEOUT = 90  # seconds per outside page (load + scroll + screenshot)
DISTINCT = {"min_dominant_delta_e": 0.10, "max_signature_jaccard": 0.5, "min_thumbnail_diff": 0.06}
BROWSER = os.environ.get("DESIGN_BROWSER", "http://playwright-mcp:8931/mcp")
SERVE_HOST = os.environ.get("DESIGN_SERVE_HOST") or None
EXTERNAL = re.compile(r"""(?:(?:src|href|action|poster|data)\s*=\s*["']?\s*(?:https?:)?//)|(?:url\(\s*["']?\s*(?:https?:)?//)|@import""", re.I)
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Written to homepage/PAGE_RULES.md by the brief stage: the one rule sheet the art
# director, designer and reviser follow, so the page converts faithfully to Penpot.
PAGE_RULES = """# Page rules (HTML/CSS that becomes an editable Penpot file)

Files
- One page: index.html (+ optional styles.css) in its folder; everything local. Link the
  generated font sheet with <link rel="stylesheet" href="fonts/fonts.css"> and use exactly its
  family names and weights. Images only from images/ (supplied, sanitized) or drawn in code
  (inline SVG, CSS gradients, patterns). No external URLs, CDNs, web fonts from elsewhere,
  stock photos, AI-generated images, iframes or <script>.

Structure the converter reads
- Every top-level block is <header>, <section> or <footer> with data-section="Name"
  (Header, Hero, ...). Give meaningful elements data-name="...".
- Repeated items with the same structure (cards, stats, steps, buttons) carry
  data-component="Name"; each becomes a Penpot component, the copies its instances.
- The concept's signature element (the one its signature move names) carries
  data-signature="Name" on its outermost element. The review measures how much of it
  the first screen shows at 390x844 and 1440x900.
- Text styles may carry data-typography="Display" / "Body" ...
- Colours are CSS custom properties on :root (--dominant, --accent, --ink, --surface, ...);
  use var(--...) everywhere so they become shared Penpot colours.

What converts faithfully: solid, linear and radial gradient backgrounds; background images
(cover/contain); borders; border radius; drop shadows; images; inline SVG paths, shapes and
lines with solid fills and strokes; text in any loaded font, size, weight, line height,
letter spacing, case and colour; grid and flex layout.
Avoid (the converter can only approximate them, and lists each one): ::before/::after with
content (draw decoration as real elements or inline SVG), transforms on content (rotate,
skew), filters, backdrop-filter, blend modes, clip-path and masks, text shadows,
background-clip:text, inset shadows, SVG <text>/<use>/filters/gradient strokes, form controls.

Motion
- One orchestrated load animation (a staggered reveal) in CSS @keyframes, inside
  @media (prefers-reduced-motion: no-preference). Animate from an offset to the element's
  natural style, so the page is complete when motion is off (renders use reduced motion).

Quality bar
- Widths 390, 768 and 1440 without sideways scrolling (fluid grid, clamp()).
- WCAG 2.2 AA: text contrast 4.5:1 (3:1 large text), one h1, headings in order, landmarks,
  alt text, visible :focus-visible styles, targets at least 44x44 px, body text >= 16 px.
- Claims only from the brief's facts. No invented customers, logos, quotes, ratings or numbers.

Words
- Use the copy deck's words (homepage/copy/COPY.md): its headline options, subhead, proof points,
  CTA labels, FAQ and terms. Show each required notice ONCE, where the deck places it (header or
  footer); never sprinkle disclaimers or hedges ("in the proposed demo") through the page. Where a
  price or rule appears, show the deck's worked example next to it.

Use (runtime checks run on the built page)
- Every link and button has a visible :hover and :focus-visible state; Tab order follows the page.
- Nothing scrolls sideways at 320 px; nothing fixed or sticky covers much of a short screen.
- Text boxes grow with their text (min-height, never a fixed height on text), so larger line,
  letter and word spacing never clips text.
- Icon-only controls get an aria-label; an aria-label starts with the visible label.
"""
FIXTURE_BRIEF = {
    "product": "Fixture Studio", "fictional": True, "fixture": True,
    "category": "converter fixture pages",
    "audience": "Design department engineers proving the v2 workflow at no model cost.",
    "purpose": "Exercise gates, measure, review loop, conversion and handoff with hand-written pages.",
    "cta": "Read the fixture", "disclosure": "Fixture pages for workflow tests; nothing here is a product.",
    "facts": ["Three hand-written pages stand in for model concepts.",
              "Fonts are vendored OFL files.", "Images are made in code."],
}


def now() -> str:
    return v1.now()


def save(path: Path, value: Any) -> None:
    """Write JSON in one step: a stage loading the file meanwhile sees the old version or the new one, never half."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def load(path: Path) -> Any:
    return v1.load(path)


def digest(value: Any) -> str:
    return v1.digest(value)


def tree_digest(root: Path) -> str:
    """Hash of every file under root (relative names + content)."""
    items = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            items.append([str(f.relative_to(root)), hashlib.sha256(f.read_bytes()).hexdigest()])
    return digest(items)


# ---------------------------------------------------------------- contracts


def brief_contract(value: Any) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("fictional"), bool):
        raise ValueError("brief needs an explicit fictional boolean")
    for key in ("product", "category", "audience", "purpose", "cta"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"brief needs {key}")
    facts = value.get("facts")
    if not isinstance(facts, list) or len(facts) < 3 or not all(isinstance(f, str) and f.strip() for f in facts):
        raise ValueError("brief needs at least three facts (the only source for claims on the page)")
    if value["fictional"] and not str(value.get("disclosure", "")).strip():
        raise ValueError("a fictional brief needs a disclosure line")
    if len(value["product"]) > 40 or len(value["cta"]) > 40:
        raise ValueError("product and cta must be short (<=40 characters)")
    for asset in value.get("assets", []):
        if not isinstance(asset, dict) or not asset.get("path") or not asset.get("alt"):
            raise ValueError("each asset needs path and alt")
        if asset.get("kind") not in ("screenshot", "logo", "photo"):
            raise ValueError("asset kind must be screenshot, logo or photo")
    brand = value.get("brand", {})
    if not isinstance(brand, dict):
        raise ValueError("brand must be an object")
    return value


def references_contract(value: Any, fixture: bool) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("references must be a JSON list")
    low, high = (2, 4) if fixture else (8, 12)
    if not low <= len(value) <= high:
        raise ValueError(f"give {low}-{high} references")
    seen = set()
    for ref in value:
        if not isinstance(ref, dict) or not str(ref.get("name", "")).strip() or not str(ref.get("why", "")).strip():
            raise ValueError("each reference needs name and why")
        if fixture:
            if ref.get("fixture") not in FIXTURE_CONCEPTS.values():
                raise ValueError("fixture references name a fixture page")
        else:
            url = urllib.parse.urlparse(str(ref.get("url", "")))
            if url.scheme != "https" or not url.hostname:
                raise ValueError("references need https URLs")
        key = ref.get("url") or ref.get("fixture")
        if key in seen:
            raise ValueError("duplicate reference")
        seen.add(key)
    return value


def font_slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]", "", family.lower())


def oklab(hex_value: str) -> tuple[float, float, float]:
    rgb = [int(hex_value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
    r, g, b = lin
    lv = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    mv = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    sv = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * lv + 0.7936177850 * mv - 0.0040720468 * sv,
            1.9779984951 * lv - 2.4285922050 * mv + 0.4505937099 * sv,
            0.0259040371 * lv + 0.7827717662 * mv - 0.8086757660 * sv)


def delta_e(a: str, b: str) -> float:
    return round(math.dist(oklab(a), oklab(b)), 4)


def jaccard(a: list[str], b: list[str]) -> float:
    sa = {x.strip().lower() for x in a if x.strip()}
    sb = {x.strip().lower() for x in b if x.strip()}
    return round(len(sa & sb) / len(sa | sb), 3) if sa | sb else 1.0


def concept_contract(concept: Any, brand_fonts: set[str]) -> list[str]:
    """Problems with one concept (empty = fine)."""
    problems: list[str] = []
    if not isinstance(concept, dict):
        return ["concept is not an object"]
    cid = concept.get("id")
    where = f"concept {cid}"
    for key in ("name", "brief", "imagery", "signature_move", "motion"):
        if not isinstance(concept.get(key), str) or not concept[key].strip():
            problems.append(f"{where}: needs {key}")
    words = len(str(concept.get("brief", "")).split())
    if not 150 <= words <= 700:
        problems.append(f"{where}: design brief has {words} words; write about 300 (150-700)")
    sig = concept.get("layout_signature")
    if not isinstance(sig, list) or not 3 <= len(sig) <= 8 or not all(isinstance(s, str) and s.strip() for s in sig):
        problems.append(f"{where}: layout_signature needs 3-8 short keywords")
    fonts = concept.get("fonts")
    if not isinstance(fonts, dict):
        problems.append(f"{where}: needs fonts.display and fonts.text")
    else:
        for role in ("display", "text"):
            face = fonts.get(role)
            if not isinstance(face, dict) or not str(face.get("family", "")).strip():
                problems.append(f"{where}: fonts.{role}.family missing")
                continue
            weights = face.get("weights")
            if not isinstance(weights, list) or not weights or not all(isinstance(w, int) and 100 <= w <= 900 and w % 100 == 0 for w in weights) or len(weights) > 3:
                problems.append(f"{where}: fonts.{role}.weights needs 1-3 weights from 100-900")
            if face["family"].strip().lower() in BANNED_FONTS and face["family"].strip().lower() not in brand_fonts:
                problems.append(f"{where}: {face['family']} is on the overused list; choose a face with character")
    palette = concept.get("palette")
    keys = ("dominant", "accent", "ink", "surface", "on_dominant", "on_accent")
    if not isinstance(palette, dict) or any(not HEX.match(str(palette.get(k, ""))) for k in keys):
        problems.append(f"{where}: palette needs #RRGGBB for {', '.join(keys)}")
    else:
        for fg, bg in (("ink", "surface"), ("on_dominant", "dominant"), ("on_accent", "accent")):
            ratio = v1.contrast(palette[fg], palette[bg])
            if ratio < 4.5:
                problems.append(f"{where}: {fg} on {bg} contrast {ratio}:1 is below 4.5:1 (WCAG 1.4.3)")
    return problems


# ---------------------------------------------------------------- type pairings (queue #34)

def pairing_key(display: str, text: str) -> str:
    """One key per pairing, whichever face plays which role."""
    return " + ".join(sorted(face.strip().lower() for face in (display, text)))


def concept_pairing(concept: dict) -> tuple[str, str] | None:
    fonts = concept.get("fonts") if isinstance(concept.get("fonts"), dict) else {}
    faces = [str(fonts[role].get("family", "")).strip() if isinstance(fonts.get(role), dict) else ""
             for role in ("display", "text")]
    return (faces[0], faces[1]) if all(faces) else None


def pairing_log(workspace: Path) -> Path:
    """The shared log every run appends its pairings to, beside the run workspaces."""
    if os.environ.get("DESIGN_PAIRING_LOG"):
        return Path(os.environ["DESIGN_PAIRING_LOG"])
    root = os.environ.get("WORKSPACE_DIR")
    return (Path(root) if root else workspace.parent) / ".design" / "type-pairings.jsonl"


def recorded_pairings(log: Path, workspace: str) -> list[dict]:
    """The seed's pairings plus those logged by other workspaces (a run never blocks its own concepts)."""
    seed = load(PAIRING_SEED).get("pairings", []) if PAIRING_SEED.exists() else []
    out = [{"display": p["display"], "text": p["text"], "source": p.get("source", "recorded")} for p in seed]
    if log.exists():
        for line in log.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (isinstance(event, dict) and event.get("workspace") != workspace
                    and str(event.get("display", "")).strip() and str(event.get("text", "")).strip()):
                out.append({"display": event["display"], "text": event["text"],
                            "source": f"{event.get('kind', 'used')} in run {event.get('workspace', '?')}"})
    return out


def pairing_problems(concepts: list[dict], recorded: list[dict], brand_fonts: set[str]) -> list[str]:
    """A concept that reuses a recorded pairing must pick a fresh one, unless the brand owns both faces."""
    seen: dict[str, str] = {}
    for r in recorded:
        seen.setdefault(pairing_key(r["display"], r["text"]), r["source"])
    problems = []
    for c in concepts:
        pair = concept_pairing(c)
        if not pair or {face.lower() for face in pair} <= brand_fonts:
            continue  # missing faces are the contract's problem; a brand-owned pairing stays
        source = seen.get(pairing_key(*pair))
        if source:
            problems.append(f"concept {c.get('id')}: the type pairing {pair[0]} + {pair[1]} was already used ({source}); "
                            "pick a fresh pairing chosen for this product (homepage/PAIRINGS.md lists the used ones)")
    return problems


def record_pairings(log: Path, workspace: str, kind: str, concepts: list[dict]) -> int:
    rows = [json.dumps({"display": pair[0], "text": pair[1], "kind": kind, "concept": c.get("id"),
                        "workspace": workspace, "recorded_at": now()}, ensure_ascii=False)
            for c in concepts if (pair := concept_pairing(c))]
    if not rows:
        return 0
    log.parent.mkdir(parents=True, exist_ok=True)
    fresh = not log.exists()
    with log.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write("\n".join(rows) + "\n")
    if fresh:  # the server, the workers and the host run as different users: all of them append
        try:
            os.chmod(log, 0o666)
        except OSError:
            pass
    return len(rows)


def pairings_brief(recorded: list[dict], brand_fonts: set[str]) -> str:
    """homepage/PAIRINGS.md: what the art director reads before drafting."""
    pairs: dict[str, dict] = {}
    for r in recorded:
        pairs.setdefault(pairing_key(r["display"], r["text"]), r)
    faces: dict[str, list] = {}
    for r in pairs.values():
        for face in {r["display"].strip(), r["text"].strip()}:
            faces.setdefault(face.lower(), [face, 0])[1] += 1
    common = sorted((v for v in faces.values() if v[1] >= 2), key=lambda v: (-v[1], v[0].lower()))
    lines = ["# Type pairings already used", "",
             "Earlier runs and the test fixtures used these display + text pairings. The concept check rejects a",
             "concept whose pairing is on this list (either way round), unless the brand owns both faces"
             + (f" (this brief's brand fonts: {', '.join(sorted(brand_fonts))})." if brand_fonts else " (this brief lists no brand fonts)."),
             "Pick each pairing for this product's character, not from habit.", "", f"## Used pairings ({len(pairs)})", ""]
    lines += [f"- {r['display']} + {r['text']} ({r['source']})" for r in pairs.values()]
    if common:
        lines += ["", "## Faces earlier runs reached for most", "",
                  "Allowed in a fresh pairing, but they are habits rather than choices: prefer a face that suits this product.", ""]
        lines += [f"- {name}: {count} pairings" for name, count in common]
    return "\n".join(lines) + "\n"


def html_problems(path: Path) -> list[str]:
    if not path.is_file():
        return [f"{path.name} missing"]
    text = path.read_text(errors="replace")
    problems = []
    if len(text) > 400_000:
        problems.append(f"{path.name} is over 400 KB")
    if EXTERNAL.search(text):
        problems.append(f"{path.parent.name}/{path.name} refers to an outside URL; keep every asset and link local (fonts/, images/, #anchors)")
    if re.search(r"<(iframe|object|embed)\b", text, re.I):
        problems.append(f"{path.name} uses iframe/object/embed")
    if re.search(r"<script\b", text, re.I):
        problems.append(f"{path.name} uses <script>; the page is HTML and CSS only")
    return problems


def safe_gate(raw: str) -> dict:
    return v1.safe_gate(raw)


# Gate convention (Design DIRECTIVES 2026-10-04): the chat running a workflow answers as Design;
# "owner" only for the owner's own words (kept verbatim, they outrank); "fixture-test" in fixture runs.
REAL_DECIDERS = ("design", "owner")
FIXTURE_DECIDER = "fixture-test"
# Before 2026-10-05 gate records named the answerer in "approval"; read, never rewritten.
LEGACY_APPROVAL = {"owner-direction": "owner", "owner-final": "owner", "fixture-test": FIXTURE_DECIDER,
                   "provisional-fictional": "design", "benchmark-recommended": "design"}


def gate_answer(raw: str, gate: str, deciders: tuple[str, ...]) -> dict:
    """A direction or final gate answer: decided_by (one of deciders), the choice and its reasons."""
    value = safe_gate(raw)
    if "approval" in value:
        raise ValueError("approval is retired: answer with decided_by (design, owner or fixture-test) and reasons")
    if value.get("decided_by") not in deciders:
        raise ValueError(f"this workflow's {gate} gate needs decided_by {' or '.join(deciders)}")
    reasons = value.get("reasons")
    if not isinstance(reasons, str) or not reasons.strip():
        raise ValueError(f"the {gate} gate answer needs reasons: why this choice")
    if value["decided_by"] == "owner":
        # Only the owner's own words make an owner answer: verbatim in notes, with where he said them.
        if not value.get("notes") or not isinstance(value.get("source"), str) or not value["source"].strip():
            raise ValueError("an owner answer needs his own words in notes and source: where he said them")
    elif "source" in value:
        raise ValueError("source names where the owner said his words; only decided_by owner has one")
    return value


def gate_decided_by(record: dict) -> str | None:
    """Who answered a saved gate record, new (decided_by) or legacy (approval)."""
    return record.get("decided_by") or LEGACY_APPROVAL.get(record.get("approval"))


def taste_words(entry: dict):
    """A taste entry's words, new (words) or legacy (owner_words)."""
    return entry.get("words", entry.get("owner_words", ""))


def upgrade_state(state: dict) -> dict:
    """Read a job.json written before 2026-10-05 (owner_changes, owner_*_approved) under the new names.

    Old keys stay as they are (past records are never rewritten); the new ones are added beside them."""
    if "change_rounds" not in state:
        state["change_rounds"] = state.get("owner_changes", 0)
    if "direction_approved" not in state:
        d = state.get("direction") or {}
        state["direction_approved"] = {"approved": bool(state.get("owner_direction_approved")),
                                       "decided_by": gate_decided_by(d) if d else None}
    if "final_approved" not in state:
        old = bool(state.get("owner_final_approved"))
        state["final_approved"] = {"approved": old, "decided_by": "owner" if old else None}
    return state


# Round verdicts that start a final-gate change round ("owner_changes" in job.json files before 2026-10-05).
CHANGE_VERDICTS = ("gate_changes", "owner_changes")
# Fix-list source of the final gate's change notes ("owner" in rounds saved before 2026-10-05).
GATE_FIX_SOURCE = "final_gate"
GATE_FIX_SOURCES = (GATE_FIX_SOURCE, "owner")


# ---------------------------------------------------------------- words (copy deck)

WORD = re.compile(r"[\w'\u2019-]+")
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w])")
PRICE = re.compile(r"[$\u20ac\u00a3]\s?\d|\d\s?(?:usd|eur|gbp|dollars?)\b|\bper (?:hour|day|week|month|year|seat|room|person|member|user)\b|/\s?(?:hr|hour|mo|month|seat|room)\b", re.I)
# Words that only belong in the single fictional notice (the Morrow run hedged every line).
DISCLAIMER = re.compile(r"\b(fictional|fiction|not a real|isn't real|is not real|hypothetical|made[- ]up|imaginary|proposed|concept study|design study)\b", re.I)
GENERIC_CTAS = {"learn more", "click here", "submit", "read more", "more", "go", "continue", "start", "here"}
COPY_CHECKS = ("clarity", "specificity", "jargon", "terms", "scannability", "cta", "worked_example", "notice", "claims", "drift")
TASTE_ID = re.compile(r"^##\s+(T\d+)\b", re.M)
TASTE_CITE = re.compile(r"\bT\d+\b")
MAX_TASTE_CHARS = 60_000


def words(text: str) -> int:
    return len(WORD.findall(str(text or "")))


def norm_text(text: str) -> str:
    """Whitespace-, case- and quote-insensitive form used to match quoted text."""
    t = str(text or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "-").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", t).strip().lower()


def deck_fields(deck: dict) -> list[tuple[str, str]]:
    """Every visitor-facing text of a copy deck with its path (notices and voice kept apart)."""
    out: list[tuple[str, str]] = []
    if not isinstance(deck, dict):
        return out
    out.append(("promise", str(deck.get("promise", ""))))
    for i, h in enumerate(deck.get("headlines") or []):
        out.append((f"headlines[{i + 1}]", str((h or {}).get("text", "") if isinstance(h, dict) else h)))
    out.append(("subhead", str(deck.get("subhead", ""))))
    for i, p in enumerate(deck.get("proof_points") or []):
        if isinstance(p, dict):
            out += [(f"proof_points[{i + 1}].title", str(p.get("title", ""))), (f"proof_points[{i + 1}].text", str(p.get("text", "")))]
    ctas = deck.get("ctas") or {}
    if isinstance(ctas, dict):
        out += [(f"ctas.{k}", str(v)) for k, v in ctas.items() if isinstance(v, str)]
    for i, f in enumerate(deck.get("faq") or []):
        if isinstance(f, dict):
            out += [(f"faq[{i + 1}].q", str(f.get("q", ""))), (f"faq[{i + 1}].a", str(f.get("a", "")))]
    for i, t in enumerate(deck.get("terms") or []):
        if isinstance(t, dict):
            out.append((f"terms[{i + 1}]", f"{t.get('term', '')}: {t.get('meaning', '')}"))
    for i, w in enumerate(deck.get("worked_examples") or []):
        if isinstance(w, dict):
            out.append((f"worked_examples[{i + 1}]", f"{w.get('topic', '')}: {w.get('example', '')}"))
    return out


def deck_text(deck: dict) -> str:
    parts = [t for _, t in deck_fields(deck)]
    for n in (deck.get("notices") or []) if isinstance(deck, dict) else []:
        if isinstance(n, dict):
            parts.append(str(n.get("text", "")))
    parts += [str(v) for v in (deck.get("voice") or [])] if isinstance(deck, dict) else []
    return "\n".join(parts)


def arithmetic_problems(text: str) -> list[str]:
    """Check written sums like '6 x $12 = $72' or '2 \u00d7 45 min = 90 min' (only what is spelled out)."""
    problems = []
    num = r"[$\u20ac\u00a3]?\s?(\d+(?:\.\d+)?)"
    for m in re.finditer(num + r"(?:\s*[a-z%]+)?\s*([x\u00d7*+\u2212-])\s*" + num + r"(?:\s*[a-z%]+)?(?:\s*([x\u00d7*+\u2212-])\s*" + num
                         + r"(?:\s*[a-z%]+)?)?\s*=\s*" + num, text, re.I):
        a, op1, b, op2, c, result = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
        if op1 == "-" and not re.search(r"\s-\s", m.group(0)):
            continue  # a hyphen inside a range or a word, not a minus

        def apply(x: float, op: str, y: float) -> float:
            return x * y if op in "x\u00d7*" else x + y if op == "+" else x - y
        value = apply(float(a), op1, float(b))
        if op2 and c:
            value = apply(value, op2, float(c))
        if abs(value - float(result)) > 0.011:
            problems.append(f"'{m.group(0).strip()}' does not add up (it makes {round(value, 2):g})")
    return problems


def copy_contract(deck: Any, brief: dict) -> list[str]:
    """Problems with a copy deck (empty = fine). Fixed rules; the content critic judges the rest."""
    if not isinstance(deck, dict):
        return ["copy.json is not an object"]
    problems: list[str] = []
    facts = brief.get("facts") or []
    promise = str(deck.get("promise", "")).strip()
    if not promise:
        problems.append("promise: missing (one sentence)")
    else:
        if len(SENTENCE_END.findall(promise)) > 1:
            problems.append("promise: write one sentence, not several")
        if words(promise) > 25:
            problems.append(f"promise: {words(promise)} words; keep it to 25 or fewer")
    heads = deck.get("headlines")
    if not isinstance(heads, list) or not 3 <= len(heads) <= 5:
        problems.append("headlines: give 3-5 options")
    else:
        seen = set()
        for i, h in enumerate(heads, 1):
            text = str(h.get("text", "") if isinstance(h, dict) else "").strip()
            if not text or not isinstance(h, dict) or not str(h.get("angle", "")).strip():
                problems.append(f"headlines[{i}]: needs text and angle")
                continue
            if words(text) > 10:
                problems.append(f"headlines[{i}]: {words(text)} words; keep headlines to 10 or fewer")
            if norm_text(text) in seen:
                problems.append(f"headlines[{i}]: duplicate option")
            seen.add(norm_text(text))
    subhead = str(deck.get("subhead", "")).strip()
    if not subhead or words(subhead) > 35:
        problems.append(f"subhead: needs 1-35 words (has {words(subhead)})")

    def fact_refs(item: dict, where: str) -> None:
        refs = item.get("facts")
        if not isinstance(refs, list) or not refs or not all(isinstance(r, int) and 1 <= r <= len(facts) for r in refs):
            problems.append(f"{where}: facts must list the brief fact numbers it rests on (1-{len(facts)})")
    proofs = deck.get("proof_points")
    if not isinstance(proofs, list) or len(proofs) != 3:
        problems.append("proof_points: give exactly 3")
    else:
        for i, p in enumerate(proofs, 1):
            if not isinstance(p, dict) or not str(p.get("title", "")).strip() or not str(p.get("text", "")).strip():
                problems.append(f"proof_points[{i}]: needs title and text")
                continue
            if words(p["text"]) > 40:
                problems.append(f"proof_points[{i}]: {words(p['text'])} words; keep to 40 or fewer")
            fact_refs(p, f"proof_points[{i}]")
    ctas = deck.get("ctas")
    if not isinstance(ctas, dict) or not str(ctas.get("primary", "")).strip():
        problems.append("ctas: needs a primary label")
    else:
        for key, label in ctas.items():
            if not isinstance(label, str) or not label.strip():
                continue
            if words(label) > 5:
                problems.append(f"ctas.{key}: '{label}' is {words(label)} words; say the action in 5 or fewer")
            if norm_text(label).strip("!. ") in GENERIC_CTAS:
                problems.append(f"ctas.{key}: '{label}' does not say what happens; name the action")
    faq = deck.get("faq")
    if not isinstance(faq, list) or not 3 <= len(faq) <= 6:
        problems.append("faq: give 3-6 questions")
    else:
        for i, f in enumerate(faq, 1):
            if not isinstance(f, dict) or not str(f.get("q", "")).strip() or not str(f.get("a", "")).strip():
                problems.append(f"faq[{i}]: needs q and a")
                continue
            if words(f["a"]) > 60:
                problems.append(f"faq[{i}].a: {words(f['a'])} words; answer in 60 or fewer")
            fact_refs(f, f"faq[{i}]")
    voice = deck.get("voice")
    if not isinstance(voice, list) or not 3 <= len(voice) <= 6 or not all(isinstance(v, str) and v.strip() for v in voice):
        problems.append("voice: give 3-6 short voice notes")
    terms = deck.get("terms", [])
    if not isinstance(terms, list) or not all(isinstance(t, dict) and str(t.get("term", "")).strip() and str(t.get("meaning", "")).strip() for t in terms):
        problems.append("terms: a list of {term, meaning}")
    else:
        names = [norm_text(t["term"]) for t in terms]
        if len(names) != len(set(names)):
            problems.append("terms: each term is defined once")
    notices = deck.get("notices", [])
    if not isinstance(notices, list) or not all(isinstance(n, dict) and str(n.get("text", "")).strip() for n in notices):
        problems.append("notices: a list of {id, text, placement}")
        notices = []
    ids = [str(n.get("id", "")) for n in notices]
    if len(ids) != len(set(ids)):
        problems.append("notices: each notice is stated once")
    for n in notices:
        if n.get("placement") not in ("header", "footer"):
            problems.append(f"notices.{n.get('id')}: placement is header or footer")
    if brief.get("fictional"):
        if ids.count("fictional") != 1:
            problems.append("notices: a fictional brief needs exactly one notice with id 'fictional' (stated once)")
    elif "fictional" in ids:
        problems.append("notices: this product is real; drop the fictional notice")
    if brief.get("fictional"):  # the Morrow run hedged every line; real products may say "proposed" honestly
        for path, text in deck_fields(deck):
            m = DISCLAIMER.search(text)
            if m and not path.startswith("worked_examples"):
                problems.append(f"{path}: '{m.group(0)}' belongs only in the single notice; say it once there, not here")
    visitor = [(p, t) for p, t in deck_fields(deck) if not p.startswith("worked_examples")]
    examples = [w for w in (deck.get("worked_examples") or []) if isinstance(w, dict)]
    if not isinstance(deck.get("worked_examples", []), list):
        problems.append("worked_examples: a list of {topic, example}")
    priced = [p for p, t in visitor if PRICE.search(t)]
    if priced and not examples:
        problems.append(f"worked_examples: prices or rates appear ({', '.join(priced[:3])}); add a worked example with the maths")
    for i, w in enumerate(examples, 1):
        ex = str(w.get("example", ""))
        if not str(w.get("topic", "")).strip() or len(NUMBER.findall(ex)) < 2:
            problems.append(f"worked_examples[{i}]: needs a topic and an example with its numbers")
        problems += [f"worked_examples[{i}]: {p}" for p in arithmetic_problems(ex)]
    known = {n.replace(",", "") for f in facts for n in NUMBER.findall(str(f))}
    known |= {n.replace(",", "") for w in examples for n in NUMBER.findall(str(w.get("example", "")))}
    known |= {str(i) for i in range(0, 11)}  # small counts ("three steps") need no source
    for path, text in visitor:
        if path.startswith("terms"):
            continue
        for n in NUMBER.findall(text):
            if n.replace(",", "") not in known:
                problems.append(f"{path}: the number {n} is not in the brief's facts or a worked example")
    return problems


def copy_facts(deck: dict, brief: dict) -> dict:
    """Measured facts about the deck for the content critic (numbers, not judgement)."""
    fields = deck_fields(deck)
    sentences = []
    for path, text in fields:
        for s in re.split(r"(?<=[.!?])\s+", text):
            if s.strip():
                sentences.append((words(s), path, s.strip()))
    longest = sorted(sentences, reverse=True)[:3]
    disclaimers = [{"field": p, "word": m.group(0)} for p, t in fields for m in [DISCLAIMER.search(t)] if m
                   and not p.startswith("worked_examples")]
    return {"words": sum(words(t) for _, t in fields), "fields": len(fields),
            "longest_sentences": [{"words": w, "field": p, "text": s[:160]} for w, p, s in longest],
            "priced_fields": [p for p, t in fields if PRICE.search(t)],
            "disclaimer_words_outside_notice": disclaimers,
            "notices": [{"id": n.get("id"), "placement": n.get("placement")} for n in deck.get("notices") or [] if isinstance(n, dict)],
            "facts_in_brief": len(brief.get("facts") or [])}


def render_copy(deck: dict, brief: dict, title: str) -> str:
    facts = brief.get("facts") or []
    lines = [f"# {title} — {brief.get('product', '')}", "",
             "The page's words. Use them as written; change them only through review.", "",
             "## Promise (one sentence)", str(deck.get("promise", "")), "", "## Headline options"]
    for i, h in enumerate(deck.get("headlines") or [], 1):
        if isinstance(h, dict):
            lines.append(f"{i}. {h.get('text', '')}  — angle: {h.get('angle', '')}")
    lines += ["", "## Subhead", str(deck.get("subhead", "")), "", "## Proof points"]
    for i, p in enumerate(deck.get("proof_points") or [], 1):
        if isinstance(p, dict):
            refs = ", ".join(f"fact {r}" for r in p.get("facts") or [])
            lines.append(f"{i}. **{p.get('title', '')}** — {p.get('text', '')} ({refs})")
    ctas = deck.get("ctas") or {}
    lines += ["", "## Calls to action"] + [f"- {k}: {v}" for k, v in ctas.items()] if isinstance(ctas, dict) else []
    lines += ["", "## FAQ"]
    for i, f in enumerate(deck.get("faq") or [], 1):
        if isinstance(f, dict):
            lines += [f"{i}. Q: {f.get('q', '')}", f"   A: {f.get('a', '')}"]
    if deck.get("terms"):
        lines += ["", "## Terms (use exactly these words, the same way everywhere)"]
        lines += [f"- {t.get('term')}: {t.get('meaning')}" for t in deck["terms"] if isinstance(t, dict)]
    if deck.get("worked_examples"):
        lines += ["", "## Worked examples (show next to the price or rule they explain)"]
        lines += [f"- {w.get('topic')}: {w.get('example')}" for w in deck["worked_examples"] if isinstance(w, dict)]
    lines += ["", "## Required notices (each ONCE, in its place; never repeated elsewhere)"]
    lines += [f"- {n.get('id')} ({n.get('placement')}): {n.get('text')}" for n in deck.get("notices") or [] if isinstance(n, dict)] or ["- none"]
    lines += ["", "## Voice"] + [f"- {v}" for v in deck.get("voice") or []]
    lines += ["", "## Brief facts (numbered; proof points and answers cite them)"] + [f"{i}. {f}" for i, f in enumerate(facts, 1)]
    return "\n".join(lines) + "\n"


def verify_quotes(findings: list, haystack: str) -> tuple[list[dict], list[dict]]:
    """Split findings into those whose quote is really in the text and those that are not."""
    hay = norm_text(haystack)
    kept, dropped = [], []
    for f in findings if isinstance(findings, list) else []:
        if not isinstance(f, dict):
            continue
        quote = re.sub(r"^-?\s*\[[a-z0-9]+\]\s*", "", norm_text(f.get("quote", ""))).strip('"')  # page-text.md line prefix
        if quote and quote in hay:
            kept.append({**f, "verified": True})
        else:
            dropped.append({**f, "verified": False, "dropped": "quote not found in the text" if quote else "no quote"})
    return kept, dropped


def taste_ids(text: str) -> list[str]:
    return TASTE_ID.findall(text or "")


class _PageText(html.parser.HTMLParser):
    """Visible words of a static page, roughly as a browser's innerText joins them."""
    BLOCK = {"address", "article", "aside", "blockquote", "br", "button", "dd", "details", "div", "dl", "dt",
             "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "label",
             "li", "main", "nav", "ol", "p", "section", "summary", "table", "td", "th", "tr", "ul"}
    SKIP = {"head", "noscript", "script", "style", "template", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def page_words(html_text: str) -> str:
    parser = _PageText()
    parser.feed(html_text)
    parser.close()
    return re.sub(r"\n\s*", "\n", re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts))).strip()


def page_copy_problems(html_text: str, deck: dict, headline: str | None, fictional: bool, where: str) -> list[str]:
    """A page against its copy deck: each notice exactly once, no hedges outside it, the deck's headline used."""
    text = norm_text(page_words(html_text))
    problems = []
    rest = text
    for n in deck.get("notices") or []:
        if not isinstance(n, dict) or not str(n.get("text", "")).strip():
            continue
        wanted = norm_text(n["text"])
        count = text.count(wanted)
        if count == 0:
            problems.append(f"{where}: the notice '{n.get('id')}' is missing; show the deck's words once ({n.get('placement')})")
        elif count > 1:
            problems.append(f"{where}: the notice '{n.get('id')}' appears {count} times; show it once")
        rest = rest.replace(wanted, " ")
    if fictional:
        hedges = sorted({m.group(0).lower() for m in DISCLAIMER.finditer(rest)})
        if hedges:
            problems.append(f"{where}: {', '.join(repr(h) for h in hedges)} appear outside the single notice; "
                            "say it once in the notice and nowhere else")
    if headline and norm_text(headline) not in text:
        problems.append(f"{where}: the headline '{headline}' is not on the page")
    return problems


def concept_words_problems(concept: dict, deck: dict | None, taste: list[str]) -> list[str]:
    """The words and taste fields every concept carries in v2.1."""
    where = f"concept {concept.get('id')}"
    problems = []
    if deck is not None:
        options = [norm_text(h.get("text", "")) for h in deck.get("headlines") or [] if isinstance(h, dict)]
        head = concept.get("headline")
        if not isinstance(head, str) or norm_text(head) not in options:
            problems.append(f"{where}: headline must be one of the copy deck's headline options, word for word")
    use = concept.get("taste_use")
    if not isinstance(use, str) or len(use.split()) < 8:
        problems.append(f"{where}: taste_use must say in a sentence or two how this concept uses the owner's taste file")
    elif taste:
        cited = set(TASTE_CITE.findall(use))
        if not cited:
            problems.append(f"{where}: taste_use must cite the taste entries it follows or departs from (T1, T2 ...)")
        unknown = cited - set(taste)
        if unknown:
            problems.append(f"{where}: taste_use cites {', '.join(sorted(unknown))}, which the taste file does not have")
    return problems


def describe_concept(c: dict) -> str:
    fonts = c.get("fonts") or {}
    pair = " + ".join(str((fonts.get(r) or {}).get("family", "?")) for r in ("display", "text"))
    pal = c.get("palette") or {}
    text = f"{pair}; dominant {pal.get('dominant', '?')}, accent {pal.get('accent', '?')}; signature: {c.get('signature_move', '')}"
    return text + (f"; headline: \"{c['headline']}\"" if c.get("headline") else "")


def trim_taste(text: str) -> tuple[str, bool]:
    """Keep the newest whole entries when the taste file outgrows MAX_TASTE_CHARS."""
    if len(text) <= MAX_TASTE_CHARS:
        return text, False
    starts = [m.start() for m in TASTE_ID.finditer(text)]
    head = text[:starts[0]] if starts else ""
    for s in starts:
        if len(head) + len(text) - s <= MAX_TASTE_CHARS:
            return head + text[s:], True
    return text[-MAX_TASTE_CHARS:], True


FIXTURE_DECK = {
    "promise": "Fixture Studio proves the homepage workflow end to end without paying for a model.",
    "headlines": [{"text": "Three pages, every gate, no model", "angle": "what it covers"},
                  {"text": "Prove the workflow before you pay", "angle": "why it matters"},
                  {"text": "Hand-written pages, real conversions", "angle": "how it works"}],
    "subhead": "Hand-written pages stand in for the art director, so the gates, reviews and Penpot conversion run for real at no cost.",
    "proof_points": [{"title": "Three stand-in pages", "text": "Three hand-written pages stand in for model concepts.", "facts": [1]},
                     {"title": "Licensed fonts", "text": "Fonts are vendored OFL files, so every export carries its licence.", "facts": [2]},
                     {"title": "Images made in code", "text": "Every image is made in code; nothing is generated or stock.", "facts": [3]}],
    "ctas": {"primary": "Read the fixture"},
    "faq": [{"q": "Does a fixture run cost anything?", "a": "No. Hand-written pages replace every model step.", "facts": [1]},
            {"q": "Where do the fonts come from?", "a": "They are vendored OFL files that travel with the pages.", "facts": [2]},
            {"q": "Are the images real photos?", "a": "No. Every image is drawn in code.", "facts": [3]}],
    "voice": ["Plain words", "Short sentences", "Say what each step proves"],
    "terms": [{"term": "fixture", "meaning": "a hand-written stand-in page used to test the workflow"}],
    "notices": [{"id": "fictional", "text": "Fixture pages for workflow tests; nothing here is a product.", "placement": "footer"}],
    "worked_examples": [],
}
FIXTURE_COPY_REVIEW = [
    {"id": "K1", "check": "specificity", "element": "subhead",
     "quote": "so the gates, reviews and Penpot conversion run for real at no cost",
     "problem": "Fixture finding: 'run for real' is vague about what is proven.",
     "suggestion": "Say which steps are exercised.", "severity": 3},
    {"id": "K2", "check": "clarity", "element": "faq[1].a", "quote": "this sentence is not in the deck",
     "problem": "Fixture finding with a quote that is not in the deck: the check must drop it.",
     "suggestion": "none", "severity": 2},
]
FIXTURE_SUBHEAD_AFTER = ("Hand-written pages stand in for the art director, so every gate, review and Penpot "
                         "conversion is exercised without a model.")


# ---------------------------------------------------------------- fonts


def fetch(url: str, timeout: int = 60) -> bytes:
    host = urllib.parse.urlparse(url).hostname
    if host not in FONT_HOSTS:
        raise ValueError(f"refusing to fetch from {host}")
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - host allow-listed above
        return res.read()


def font_files(family: str, weights: list[int], italic: bool, dest: Path, issues: list[str]) -> list[dict]:
    """Download static TTFs from Google Fonts + licence. Reuses files already present."""
    slug = font_slug(family)
    folder = dest / slug
    folder.mkdir(parents=True, exist_ok=True)
    faces = []
    styles = ["normal", "italic"] if italic else ["normal"]
    for style in styles:
        for weight in weights:
            name = f"{re.sub(r'[^A-Za-z0-9]', '', family)}-{weight}{'italic' if style == 'italic' else ''}.ttf"
            target = folder / name
            if not target.exists():
                axis = f"ital,wght@{1 if style == 'italic' else 0},{weight}"
                url = "https://fonts.googleapis.com/css2?family=" + urllib.parse.quote_plus(family) + ":" + axis
                try:
                    css = fetch(url).decode()
                except (urllib.error.URLError, OSError, ValueError) as exc:
                    issues.append(f"{family} {weight} {style}: not on Google Fonts ({exc.__class__.__name__})")
                    continue
                blocks = re.findall(r"@font-face\s*{([^}]*)}", css)
                chosen = next((b for b in blocks if "unicode-range" not in b), blocks[-1] if blocks else "")
                m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", chosen)
                if not m:
                    issues.append(f"{family} {weight} {style}: no font file in Google Fonts response")
                    continue
                data = fetch(m.group(1))
                if data[:4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
                    issues.append(f"{family} {weight} {style}: not a TTF/OTF file")
                    continue
                target.write_bytes(data)
            faces.append({"family": family, "weight": weight, "style": style, "file": f"{slug}/{name}"})
    if faces and not any((folder / n).exists() for n in h2p.LICENCE_NAMES):
        for kind, fname in LICENCE_URLS:
            try:
                text = fetch(f"https://raw.githubusercontent.com/google/fonts/main/{kind}/{slug}/{fname}")
            except (urllib.error.URLError, OSError):
                continue
            (folder / fname).write_bytes(text)
            break
        else:
            issues.append(f"{family}: no licence file found; font not usable")
            return []
    return faces


def fonts_css(faces: list[dict]) -> str:
    rows = [f'@font-face {{ font-family: "{f["family"]}"; font-weight: {f["weight"]}; font-style: {f["style"]}; '
            f'font-display: block; src: url("{f["file"]}") format("truetype"); }}' for f in faces]
    return "/* Licensed fonts for this page; licence files sit beside each font. */\n" + "\n".join(rows) + "\n"


def copy_fonts(faces: list[dict], src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for slug in sorted({f["file"].split("/")[0] for f in faces}):
        shutil.copytree(src / slug, dest / slug, dirs_exist_ok=True)
    (dest / "fonts.css").write_text(fonts_css(faces))


# ---------------------------------------------------------------- browser work

RENDER_CODE = r"""async (page) => {
  const A = __ARGS__;
  const BLOCKED = /\b(403 forbidden|access denied|security verification|verify (that )?you are (a )?human|just a moment|attention required|are you a robot|captcha|request blocked|not available in your (country|region))\b/i;
  const out = [];
  for (const job of A.jobs) {
    await page.setViewportSize({width: job.width, height: job.height});
    await page.emulateMedia({reducedMotion: 'reduce', colorScheme: 'light'});
    let info = {name: job.name, ok: true};
    try {
      // Outside sites never reach network idle and some never fire load: wait for the DOM, then a fixed pause.
      await page.goto(job.url, {waitUntil: job.external ? 'domcontentloaded' : 'networkidle', timeout: job.external ? 30000 : 20000});
      if (job.freeze) await page.addStyleTag({content: A.css});
      if (job.external) {
        await page.waitForTimeout(2500);
        const total = Math.min(await page.evaluate(() => document.documentElement.scrollHeight), job.maxHeight);
        for (let y = 0; y < total; y += Math.round(job.height * 0.8)) {  // lazy images load only when scrolled to
          await page.evaluate((v) => window.scrollTo(0, v), y);
          await page.waitForTimeout(120);
        }
        await page.evaluate(() => window.scrollTo(0, 0));
      }
      await page.waitForTimeout(job.external ? 1500 : 200);
      info = await page.evaluate(async () => {
        // Bounded: a lazy image that never loads must not hang the job.
        const within = (p, ms) => Promise.race([p, new Promise((r) => setTimeout(r, ms))]);
        await within(document.fonts.ready, 8000);
        await within(Promise.all([...document.images].map((i) => i.complete ? null : new Promise((r) => { i.onload = r; i.onerror = r; }))), 8000);
        const loaded = [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/["']/g, ''));
        const text = (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim();
        return {ok: true, title: document.title, scrollWidth: document.documentElement.scrollWidth,
                height: document.documentElement.scrollHeight, loadedFamilies: [...new Set(loaded)],
                textLength: text.length, head: (document.title + ' | ' + text.slice(0, 400))};
      });
      info.name = job.name;
      // A bot wall or error page is not a reference: fail it visibly instead of counting it as captured.
      if (job.external && (info.textLength < 300 || BLOCKED.test(info.head))) {
        throw new Error('blocked or empty page: ' + info.head.slice(0, 120));
      }
      const h = Math.min(info.height, job.maxHeight);
      const shot = await page.screenshot({fullPage: true, clip: {x: 0, y: 0, width: job.width, height: h}, animations: 'disabled', caret: 'hide', scale: 'css', timeout: 30000});
      const r = await page.request.put(A.base + '/__put/' + job.name + '.png', {data: shot, headers: {'content-type': 'application/octet-stream'}});
      if (!r.ok()) throw new Error('upload failed ' + r.status());
    } catch (e) {
      info = {name: job.name, ok: false, error: String(e).slice(0, 300)};
    }
    out.push(info);
  }
  return out;
}"""

THUMB_CODE = r"""async (page) => {
  const A = __ARGS__;
  await page.goto(A.base + '/__out/' + A.names[0] + '.png');
  return await page.evaluate(async (A) => {
    const load = (u) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('load ' + u)); i.src = u; });
    const pix = [];
    for (const n of A.names) {
      const img = await load(A.base + '/__out/' + n + '.png');
      const c = document.createElement('canvas'); c.width = 64; c.height = 40;
      const g = c.getContext('2d');
      const h = Math.min(img.height, img.width * 900 / 1440);
      g.drawImage(img, 0, 0, img.width, h, 0, 0, 64, 40);
      pix.push(g.getImageData(0, 0, 64, 40).data);
    }
    const res = {};
    for (let i = 0; i < pix.length; i++) for (let j = i + 1; j < pix.length; j++) {
      let s = 0;
      for (let k = 0; k < pix[i].length; k += 4) s += Math.abs(pix[i][k] - pix[j][k]) + Math.abs(pix[i][k + 1] - pix[j][k + 1]) + Math.abs(pix[i][k + 2] - pix[j][k + 2]);
      res[A.names[i] + '|' + A.names[j]] = Math.round(s / (pix[i].length / 4 * 3 * 255) * 10000) / 10000;
    }
    return res;
  }, A);
}"""

CRAFT_CODE = r"""async (page) => {
  const A = __ARGS__;
  const out = {};
  for (const w of A.widths) {
    await page.setViewportSize({width: w, height: w === 390 ? 844 : 900});
    await page.goto(A.url, {waitUntil: 'networkidle'});
    out[w] = await page.evaluate(async (w) => {
      await document.fonts.ready;
      const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0; };
      const sizes = {}, families = {}, colors = {}, weights = {};
      const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = tw.nextNode())) {
        const t = node.textContent.replace(/\s+/g, ' ').trim();
        if (!t || !node.parentElement || !vis(node.parentElement)) continue;
        const cs = getComputedStyle(node.parentElement);
        const size = Math.round(parseFloat(cs.fontSize));
        const fam = cs.fontFamily.split(',')[0].replace(/["']/g, '').trim();
        sizes[size] = (sizes[size] || 0) + t.length;
        families[fam] = (families[fam] || 0) + t.length;
        colors[cs.color] = (colors[cs.color] || 0) + t.length;
        weights[cs.fontWeight] = (weights[cs.fontWeight] || 0) + t.length;
      }
      const bySize = Object.entries(sizes).map(([s, n]) => [+s, n]).sort((a, b) => b[1] - a[1]);
      const body = bySize.length ? bySize[0][0] : 16;
      const display = bySize.length ? Math.max(...bySize.map((x) => x[0])) : 16;
      const bgs = new Set(); let gradients = 0, bgImages = 0;
      const spacing = []; let animated = 0;
      for (const el of document.querySelectorAll('body *')) {
        if (!vis(el)) continue;
        const cs = getComputedStyle(el);
        if (cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent') bgs.add(cs.backgroundColor);
        if (cs.backgroundImage.includes('gradient')) gradients++;
        if (cs.backgroundImage.includes('url(')) bgImages++;
        if (cs.animationName !== 'none' || (cs.transitionDuration && cs.transitionDuration !== '0s')) animated++;
        for (const p of ['paddingTop', 'paddingBottom', 'paddingLeft', 'marginTop', 'marginBottom', 'rowGap', 'columnGap']) {
          const v = parseFloat(cs[p]);
          if (v > 0) spacing.push(Math.round(v));
        }
      }
      let sections = [...document.querySelectorAll('[data-section]')];
      if (!sections.length) sections = [...document.querySelectorAll('body > header, body > main > section, body > main > *, body > section, body > footer')];
      const sig = sections.filter(vis).map((s) => {
        const cs = getComputedStyle(s);
        const inner = s.querySelector('div, ul, ol') || s;
        const ics = getComputedStyle(inner);
        const cols = ics.display.includes('grid') ? ics.gridTemplateColumns.split(' ').filter(Boolean).length : (ics.display.includes('flex') ? 'flex-' + ics.flexDirection : 'flow');
        const bg = cs.backgroundImage !== 'none' ? (cs.backgroundImage.includes('url(') ? 'image' : 'gradient') : cs.backgroundColor;
        const h = s.getBoundingClientRect().height;
        const head = s.querySelector('h1, h2, h3');
        return {name: s.dataset.section || s.dataset.name || s.tagName.toLowerCase(), height: Math.round(h),
                signature: [cols, bg, head ? getComputedStyle(head).textAlign : '-', h > 700 ? 'tall' : h > 350 ? 'mid' : 'short'].join(' | ')};
      });
      const distinct = new Set(sig.map((s) => s.signature)).size;
      let repeats = 0;
      for (let i = 1; i < sig.length; i++) if (sig[i].signature === sig[i - 1].signature) repeats++;
      const onScale = spacing.length ? spacing.filter((v) => v % 4 === 0).length / spacing.length : 1;
      const loaded = [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/["']/g, ''));
      const h1 = document.querySelector('h1');
      return {
        width: w, body_px: body, display_px: display, scale_ratio: Math.round(display / body * 100) / 100,
        text_sizes: bySize.length, families: Object.keys(families), loaded_families: [...new Set(loaded)],
        unloaded_families: Object.keys(families).filter((f) => !loaded.includes(f)),
        weights: Object.keys(weights).length, text_colors: Object.keys(colors).length, background_colors: bgs.size,
        gradients, background_images: bgImages, images: document.images.length,
        svgs: document.querySelectorAll('svg').length, animated_elements: animated,
        sections: sig, section_count: sig.length, distinct_section_layouts: distinct, consecutive_repeats: repeats,
        spacing_values: new Set(spacing).size, spacing_on_4px: Math.round(onScale * 100) / 100,
        h1_px: h1 ? Math.round(parseFloat(getComputedStyle(h1).fontSize)) : null,
        hero_height: sig.length ? sig[0].height : null,
        page_height: document.documentElement.scrollHeight, overflow_x: document.documentElement.scrollWidth > w,
      };
    }, w);
  }
  return out;
}"""


def browser_jobs(root: Path, out: Path, jobs: list[dict]) -> list[dict]:
    """Serve root, run render jobs (screenshots land in out)."""
    out.mkdir(parents=True, exist_ok=True)
    host = SERVE_HOST or urllib.parse.urlparse(BROWSER).hostname or "playwright-mcp"
    base, srv = h2p.serve(root, out, host)
    try:
        for job in jobs:
            if not job.get("external"):
                job["url"] = base + "/" + job["path"].lstrip("/")
        local = [j for j in jobs if not j.get("external")]
        results = []
        if local:
            code = RENDER_CODE.replace("__ARGS__", json.dumps({"base": base, "jobs": local, "css": h2p.FREEZE_CSS}))
            results += h2p.browser_run(BROWSER, [code])[0]
        # Outside sites: one browser session per site with a time limit, so one bad site cannot stall the rest.
        groups: dict[str, list[dict]] = {}
        for job in jobs:
            if job.get("external"):
                groups.setdefault(job["url"], []).append(job)
        for group in groups.values():
            code = RENDER_CODE.replace("__ARGS__", json.dumps({"base": base, "jobs": group, "css": h2p.FREEZE_CSS}))
            try:
                results += h2p.browser_run(BROWSER, [code], timeout=EXTERNAL_TIMEOUT * len(group))[0]
            except Exception as exc:  # noqa: BLE001 - a failed site is recorded, never fatal on its own
                results += [{"name": j["name"], "ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:200]}"} for j in group]
        return results
    finally:
        srv.shutdown()


def thumbnail_diffs(out: Path, names: list[str]) -> dict[str, float]:
    host = SERVE_HOST or urllib.parse.urlparse(BROWSER).hostname or "playwright-mcp"
    base, srv = h2p.serve(out, out, host)
    try:
        return h2p.browser_run(BROWSER, [THUMB_CODE.replace("__ARGS__", json.dumps({"base": base, "names": names}))])[0]
    finally:
        srv.shutdown()


def craft_metrics(site: Path) -> dict:
    host = SERVE_HOST or urllib.parse.urlparse(BROWSER).hostname or "playwright-mcp"
    base, srv = h2p.serve(site, site, host)
    try:
        code = CRAFT_CODE.replace("__ARGS__", json.dumps({"url": base + "/index.html", "widths": [1440, 390]}))
        return h2p.browser_run(BROWSER, [code])[0]
    finally:
        srv.shutdown()


# axe on a concept page as people meet it: "reduced" asks for reduced motion; "settled" allows motion and
# waits until the load animations have ended. Looping animations never end, so they are stopped and the page
# is measured at rest. Never mid-animation: a half-faded line is not a contrast failure (#5).
AXE_CODE = r"""async (page) => {
  const A = __ARGS__;
  const out = [];
  for (const job of A.jobs) {
    let info = {name: job.name, ok: true};
    try {
      await page.setViewportSize({width: job.width, height: job.height});
      await page.emulateMedia({reducedMotion: job.state === 'reduced' ? 'reduce' : 'no-preference', colorScheme: 'light'});
      await page.goto(job.url, {waitUntil: 'networkidle', timeout: 20000});
      info.settle = await page.evaluate(async (cap) => {
        const within = (p, ms) => Promise.race([p, new Promise((r) => setTimeout(r, ms))]);
        await within(document.fonts.ready, 8000);
        const live = () => document.getAnimations().filter((a) => a.playState === 'running' || a.playState === 'pending');
        const ends = (a) => { try { return Number.isFinite(a.effect.getComputedTiming().endTime); } catch (e) { return false; } };
        const t = Date.now();
        let left = live().filter(ends);
        while (left.length && Date.now() - t < cap) {
          await within(Promise.all(left.map((a) => a.finished.catch(() => null))), 500);
          left = live().filter(ends);
        }
        const loops = live().filter((a) => !ends(a));
        loops.forEach((a) => a.cancel());
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        return {ms: Date.now() - t, unfinished: left.length, loops_stopped: loops.length};
      }, A.cap);
      await page.evaluate(A.axe);
      info.violations = await page.evaluate(async (tags) => {
        const r = await axe.run(document, {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']});
        return r.violations.map((v) => ({id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
          wcag: v.tags.filter((t) => /^wcag\d/.test(t)),
          targets: v.nodes.slice(0, 4).map((n) => ({target: n.target.join(' '), summary: (n.failureSummary || '').slice(0, 300)}))}));
      }, A.tags);
    } catch (e) {
      info = {name: job.name, ok: false, error: String(e).slice(0, 300)};
    }
    out.push(info);
  }
  return out;
}"""
AXE_STATES = (("reduced", "reduced motion"), ("settled", "after its animations"))


def concept_axe(root: Path, ids: list[str]) -> dict[str, dict]:
    """axe-core on root/<id>/index.html at 1440 and 390, in both motion states: {"A-1440-reduced": result}."""
    jobs = [{"name": f"{cid}-{width}-{state}", "path": f"{cid}/index.html", "width": width, "height": height, "state": state}
            for cid in ids for width, height in ((1440, 900), (390, 844)) for state, _ in AXE_STATES]
    host = SERVE_HOST or urllib.parse.urlparse(BROWSER).hostname or "playwright-mcp"
    base, srv = h2p.serve(root, root, host)
    try:
        for job in jobs:
            job["url"] = base + "/" + job["path"]
        code = AXE_CODE.replace("__ARGS__", json.dumps({"jobs": jobs, "axe": AXE_SRC.read_text(), "tags": AXE_TAGS,
                                                        "cap": AXE_SETTLE_MS}))
        return {r["name"]: r for r in h2p.browser_run(BROWSER, [code])[0]}
    finally:
        srv.shutdown()


def axe_problems(results: dict[str, dict], ids: list[str]) -> list[str]:
    """One problem per concept and axe rule, with where it failed and an example element."""
    problems = []
    labels = dict(AXE_STATES)
    for cid in ids:
        rules: dict[str, dict] = {}
        for width in (1440, 390):
            for state, label in AXE_STATES:
                r = results.get(f"{cid}-{width}-{state}")
                if not r or not r.get("ok"):
                    problems.append(f"concept {cid}: the accessibility check could not run at {width} with {label}: "
                                    f"{(r or {}).get('error', 'no result')}")
                    continue
                for v in r.get("violations") or []:
                    seen = rules.setdefault(v["id"], {**v, "where": []})
                    seen["where"].append(f"{width} {labels[state]}")
        for rule, v in rules.items():
            example = (v.get("targets") or [{}])[0]
            detail = " ".join(str(example.get("summary", "")).split())
            problems.append(f"concept {cid}: axe {rule} ({v.get('impact')}, {', '.join(v.get('wcag') or []) or 'WCAG'}): "
                            f"{v.get('help')}; {v.get('nodes')} element(s) at {', '.join(v['where'])}; "
                            f"e.g. {example.get('target', '?')}: {detail[:220]}")
    return problems


def write_review_inputs(review: Path, site: Path, brief: dict, number: int, chosen: dict, notes: str,
                        references: Path | None, page_checks: bool = False) -> dict:
    """Capture the page and write what the critics read in review/; return the craft metrics.

    Screenshots and usability facts (design_capture.py), brief.md, craft-metrics.json, craft-facts.md,
    concept.md and references.md. Shared by the measure stage and the craft benchmark
    (design_craft_bench.py), so the benchmark tests the critic on exactly what a live round shows it.
    page_checks (queue #39) adds the model-free page checks to facts.md (design_page_checks.py): empty
    columns, pictures by section, the primary action in the first phone screen and the rest.
    """
    cmd = [sys.executable, str(HERE / "design_capture.py"), "--out", str(review), "--site", str(site),
           "--pages", "index.html", "--viewports", "desktop,mobile", "--browser", BROWSER]
    if page_checks:
        cmd += ["--page-checks", "--primary-action", brief.get("cta", "")]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if done.returncode != 0:
        raise ValueError("capture failed: " + (done.stderr or done.stdout)[-600:])
    for sub in ("critic", "craft", "content"):
        (review / sub).mkdir(exist_ok=True)
    (review / "brief.md").write_text(
        f"# Homepage review — {brief['product']} (round {number})\n\n"
        f"Who it is for: {brief['audience']}\nHomepage job: {brief['purpose']}\nPrimary action: {brief['cta']}\n"
        + (f"Fictional study: {brief['disclosure']}\n" if brief["fictional"] else "")
        + "\nPage: index.html (the homepage), desktop and mobile. A static design built in HTML/CSS; links to other pages"
        " are not part of this review. Report problems only.\n")
    metrics = craft_metrics(site)
    save(review / "craft-metrics.json", metrics)
    lines = [f"# Measured craft facts — round {number}", "",
             "Numbers from the rendered page (computed styles). They are facts; judge what they mean.", ""]
    for w, m in metrics.items():
        lines += [f"## {w} px", f"- body text {m['body_px']} px, largest text {m['display_px']} px, scale ratio {m['scale_ratio']}x (aim >= 3x)",
                  f"- text sizes {m['text_sizes']}, weights {m['weights']}, families {', '.join(m['families'])}; not loaded: {', '.join(m['unloaded_families']) or 'none'}",
                  f"- text colours {m['text_colors']}, background colours {m['background_colors']}, gradients {m['gradients']}, background images {m['background_images']}",
                  f"- images {m['images']}, inline svg {m['svgs']}, animated elements (before reduced motion) {m['animated_elements']}",
                  f"- sections {m['section_count']}, distinct section layouts {m['distinct_section_layouts']}, back-to-back repeats {m['consecutive_repeats']}",
                  f"- spacing values {m['spacing_values']}, share on a 4 px grid {m['spacing_on_4px']}",
                  f"- hero height {m['hero_height']} px, page height {m['page_height']} px, sideways scroll {m['overflow_x']}",
                  "- sections: " + "; ".join(f"{s['name']} [{s['signature']}]" for s in m["sections"]), ""]
    (review / "craft-facts.md").write_text("\n".join(lines) + "\n")
    (review / "concept.md").write_text(
        f"# Chosen direction {chosen.get('id', '?')} — {chosen.get('name', '?')}\n\n{chosen.get('brief', '')}\n\n"
        f"Signature move: {chosen.get('signature_move', '')}\nMotion: {chosen.get('motion', '')}\nImagery: {chosen.get('imagery', '')}\n"
        f"Direction notes: {notes}\n")
    if references is not None and references.exists():
        shutil.copyfile(references, review / "references.md")
    return metrics


# ---------------------------------------------------------------- the signature in the first screen (queue #32)

# The Morrow pilot (#8, run 1dd9858c) raised "the board is not in the first mobile screen" in all three rounds
# and the reviser tweaked it twice. The measure stage now finds the concept's signature element and measures,
# with the browser's bounding box, how much of it the first screen shows; the reviser gets the numbers and
# the next round measures again.
SIGNATURE_SCREENS = ((390, 844), (1440, 900))
SIGNATURE_SHARE = 0.25  # the first screen shows a quarter of its height of the signature, or all of it if shorter
# The concept puts its signature first when its signature move says so.
SIGNATURE_FIRST = re.compile(r"\bhero\b|first (?:mobile |desktop )?(?:screen|view|viewport)|above the fold|on arrival|"
                             r"top of the page|opening (?:screen|view|moment)|\bopens? (?:on|with)\b", re.I)
SIGNATURE_GENERIC = frozenset("the and as with of on in for to its your our this that from into one page hero section top first "
                              "screen fold opening full bleed big large huge giant oversized single main central".split())

SIGNATURE_CODE = r"""async (page) => {
  const A = __ARGS__;
  const out = {screens: {}};
  for (const [w, h] of A.screens) {
    await page.setViewportSize({width: w, height: h});
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.goto(A.url, {waitUntil: 'networkidle'});
    if (A.css) await page.addStyleTag({content: A.css});
    out.screens[w] = await page.evaluate(async ([words, h]) => {
      const within = (p, ms) => Promise.race([p, new Promise((r) => setTimeout(r, ms))]);
      await within(document.fonts.ready, 8000);
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      window.scrollTo(0, 0);
      const stem = (x) => (x.length > 3 && x.endsWith('s') ? x.slice(0, -1) : x);
      const split = (s) => (s || '').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase().split(/[^a-z0-9]+/).filter((x) => x.length > 2).map(stem);
      const want = new Set(words.map(stem));
      const shown = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; };
      let el = document.querySelector('[data-signature]'), how = el ? 'data-signature' : null, matched = [];
      if (!el && want.size) {
        // No mark: the element whose own name shares the most words with the signature move. Ties go to
        // the outermost element (the board, not its rows), then the larger one.
        const fields = [['data-name', 2], ['data-component', 1.5], ['aria-label', 1], ['id', 1], ['data-section', 1]];
        let best = null;
        for (const e of document.querySelectorAll('[data-name], [data-component], [aria-label], [id], [data-section]')) {
          let score = 0; const hits = new Set();
          for (const [attr, weight] of fields) {
            const got = split(e.getAttribute(attr)).filter((x) => want.has(x));
            if (got.length) { score = Math.max(score, new Set(got).size * weight); got.forEach((x) => hits.add(x)); }
          }
          if (!score) continue;
          let depth = 0;
          for (let p = e.parentElement; p; p = p.parentElement) depth++;
          const r = e.getBoundingClientRect();
          const c = {e, score, depth, area: r.width * r.height, hits: [...hits]};
          if (!best || c.score > best.score || (c.score === best.score && (c.depth < best.depth || (c.depth === best.depth && c.area > best.area)))) best = c;
        }
        if (best) { el = best.e; how = 'name words'; matched = best.hits; }
      }
      if (!el) return {found: false};
      const r = el.getBoundingClientRect();
      let cover = 0;  // a fixed or sticky bar over the top of the screen hides what is under it
      for (const e of document.querySelectorAll('body *')) {
        if (e === el || e.contains(el) || el.contains(e)) continue;
        const cs = getComputedStyle(e);
        if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
        const er = e.getBoundingClientRect();
        if (er.top <= 1 && er.bottom > 0 && er.bottom < h * 0.5 && er.width >= window.innerWidth * 0.5 && shown(e)) cover = Math.max(cover, er.bottom);
      }
      const sec = el.closest('[data-section]');
      const content = [...document.querySelectorAll('[data-section]')].filter((s) => shown(s)
        && !/^(site )?(header|nav|navigation|banner|top ?bar|skip|menu)/i.test(s.dataset.section || ''));
      const first = content[0] || null;
      return {found: true, how, matched,
              name: el.dataset.signature || el.dataset.name || el.getAttribute('aria-label') || el.dataset.component || el.id || el.tagName.toLowerCase(),
              section: sec ? sec.dataset.section : null, in_first_section: !!(first && first.contains(el)),
              shown: shown(el), top: Math.round(r.top + window.scrollY), height: Math.round(r.height), cover: Math.round(cover),
              visible_px: Math.max(0, Math.round(Math.min(r.bottom, h) - Math.max(r.top, cover)))};
    }, [A.words, h]);
  }
  return out;
}"""


def signature_words(concept: dict) -> list[str]:
    """Words that name the concept's signature element: the lead phrase of its signature move and its first
    layout signature ("A split-flap departure board as the hero: ..." -> split, flap, departure, board)."""
    move = str(concept.get("signature_move") or "")
    lead = re.split(r":|\s+as\s+|,|;|\s[-\u2013\u2014]\s|\.\s", move, maxsplit=1)[0]
    layout = concept.get("layout_signature") or []
    first = str(layout[0]) if isinstance(layout, list) and layout else ""
    out: list[str] = []
    for w in re.findall(r"[a-z0-9]+", f"{lead} {first}".lower()):
        if len(w) > 2 and w not in SIGNATURE_GENERIC and w not in out:
            out.append(w)
    return out


def measure_signature(site: Path, words: list[str]) -> dict:
    host = SERVE_HOST or urllib.parse.urlparse(BROWSER).hostname or "playwright-mcp"
    base, srv = h2p.serve(site, site, host)
    try:
        code = SIGNATURE_CODE.replace("__ARGS__", json.dumps({"url": base + "/index.html", "words": words, "css": h2p.FREEZE_CSS,
                                                             "screens": [list(s) for s in SIGNATURE_SCREENS]}))
        return h2p.browser_run(BROWSER, [code])[0]
    finally:
        srv.shutdown()


def judge_signature(raw: dict, concept: dict, words: list[str], previous: dict | None = None) -> dict:
    """Where the signature element sits against each first screen, and whether that is a problem (fixed rule)."""
    move = str(concept.get("signature_move") or "").strip()
    screens: dict[str, dict] = {}
    for w, h in SIGNATURE_SCREENS:
        m = (raw.get("screens") or {}).get(str(w)) or (raw.get("screens") or {}).get(w) or {}
        if not m.get("found"):
            screens[f"{w}x{h}"] = {"found": False}
            continue
        needs = min(int(m.get("height") or 0), round(SIGNATURE_SHARE * h)) if m.get("shown") else round(SIGNATURE_SHARE * h)
        visible = int(m.get("visible_px") or 0) if m.get("shown") else 0
        screens[f"{w}x{h}"] = {"found": True, **{k: m.get(k) for k in ("name", "how", "matched", "section", "in_first_section", "shown",
                                                                     "top", "height", "cover")},
                               "visible_px": visible, "needs_px": max(needs, 1), "passes": visible >= max(needs, 1)}
    found = [s for s in screens.values() if s["found"]]
    by_text = bool(SIGNATURE_FIRST.search(move))
    expected = by_text or any(s.get("in_first_section") for s in found)
    if not move:
        status = "no signature move"
    elif not found:
        status = "not found"
    elif not expected:
        status = "not meant for the first screen"
    else:
        status = "pass" if all(s["passes"] for s in found) else "fail"
    first = found[0] if found else {}
    out = {"version": 1, "status": status, "signature_move": move, "words": words, "expected_first_screen": expected,
           "why_expected": "the signature move puts it first" if by_text else "it sits in the first section" if expected else "",
           "name": first.get("name"), "how": first.get("how"), "matched": first.get("matched") or [], "section": first.get("section"),
           "screens": screens}
    if previous and previous.get("screens"):
        out["previous_round"] = {k: {"visible_px": s.get("visible_px"), "needs_px": s.get("needs_px")}
                                 for k, s in previous["screens"].items() if s.get("found")}
    return out


def signature_md(sig: dict, number: int) -> str:
    lines = [f"# The signature in the first screen \u2014 round {number}", "",
             "Measured by the browser (bounding box, reduced motion, page at the top); a fixed rule, no model.",
             f"The first screen must show at least {round(SIGNATURE_SHARE * 100)}% of its height of the signature, or all of it if shorter.",
             "", f"Signature move: {sig.get('signature_move') or '(none)'}",
             f"Element: {sig.get('name') or 'not found'}" + (f" (section {sig['section']}; found by "
                                                            + ("its data-signature mark" if sig.get("how") == "data-signature"
                                                               else "its name words: " + ", ".join(sig.get("matched") or [])) + ")"
                                                            if sig.get("name") else ""),
             f"Result: {sig['status']}" + (f" ({sig['why_expected']})" if sig.get("why_expected") else ""), ""]
    for k, s in sig["screens"].items():
        if not s["found"]:
            lines.append(f"- {k}: not found")
            continue
        before = (sig.get("previous_round") or {}).get(k)
        lines.append(f"- {k}: shows {s['visible_px']} of the {s['needs_px']} px needed; top at {s['top']} px, height {s['height']} px"
                     + (f", under a {s['cover']} px fixed bar" if s.get("cover") else "") + ("" if s["shown"] else ", hidden at this size")
                     + (f" (previous round: {before['visible_px']} of {before['needs_px']} px)" if before else "")
                     + (" \u2014 pass" if s["passes"] else " \u2014 FAIL"))
    return "\n".join(lines) + "\n"


def signature_finding(sig: dict | None) -> dict | None:
    """The measure stage's finding about the signature, as a fix-list item (source measure), or None."""
    if not sig:
        return None
    lead = re.split(r":|\s+as\s+|;", sig.get("signature_move") or "", maxsplit=1)[0].strip()
    if sig.get("status") == "fail":
        bad = {k: s for k, s in sig["screens"].items() if s["found"] and not s["passes"]}
        return {"source": "measure", "id": "M1", "check": "signature", "severity": 3, "section": sig.get("section"),
                "element": f"{sig.get('name')} (the concept's signature: {lead[:80]})",
                "problem": "The concept's signature does not show in the first screen: " + "; ".join(
                    f"at {k} it shows {s['visible_px']} of the {s['needs_px']} px it needs (its top sits at {s['top']} px"
                    + (f", under a {s['cover']} px fixed bar" if s.get("cover") else "") + ")" for k, s in bad.items()) + ".",
                "evidence": "browser bounding box at reduced motion with the page at the top (review/signature.md)"
                            + ("" if sig.get("how") == "data-signature" else f"; found by its name words ({', '.join(sig.get('matched') or [])})"),
                "suggestion": "Bring the signature into the first screen at every size: " + ", ".join(
                    f"at least {s['needs_px']} px of it at {k}" for k, s in bad.items())
                    + ", without scrolling. Rework the order and sizes of what comes before it; never shrink the signature into a token"
                      " or hide it. Mark its outermost element data-signature=\"Name\". The next round measures again.",
                "viewport": ", ".join("mobile" if k.startswith("390") else "desktop" for k in bad),
                "measured": {k: {x: s[x] for x in ("visible_px", "needs_px", "top", "height")} for k, s in sig["screens"].items() if s["found"]}}
    if sig.get("status") == "not found" and sig.get("expected_first_screen"):
        return {"source": "measure", "id": "M1", "check": "signature", "severity": 2, "section": None,
                "element": f"the concept's signature ({lead[:80]})",
                "problem": "The measure stage could not find the signature element on the page, so it cannot check the first screen.",
                "evidence": f"no [data-signature] and no element named with: {', '.join(sig.get('words') or []) or '(no words)'}",
                "suggestion": "Mark the signature's outermost element data-signature=\"Name\".", "viewport": "mobile, desktop"}
    return None


# ---------------------------------------------------------------- the same problem again (queue #32)

# A repeated blocker means the last revision's tweak did not work: that section goes back for a redesign.
# A content finding raised again joins the fix list beyond the cap on minor items, and the reviser fixes it
# or says why the words stay. Matching is a fixed rule over the findings' own words, no model.
FIRST_SCREEN_TOPIC = re.compile(r"first (?:mobile |desktop )?(?:screen|view|viewport|scroll)|above the fold|below the fold|"
                                r"\bthe fold\b|on arrival|without scrolling|initial view", re.I)
MATCH_STOP = frozenset("the and are but for from has have its into not now one only out that the their them then there these "
                       "this those too was what when where which while who why will with you your our page section element "
                       "still more less very just also each every all any some same".split())
CRAFT_MATCH = 0.3  # word overlap (Jaccard) of element + problem that makes two craft or usability findings one problem
CONTENT_MATCH = 0.6  # word overlap of the elements named, for content findings whose quotes differ
REPEAT_LABEL = {"redesign": "REDESIGN", "rewrite": "REWRITE"}


def _bag(text) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9$]+", str(text or "").lower()):
        if (len(w) < 3 and not w.isdigit()) or w in MATCH_STOP:  # numbers stay: step 1 is not step 3
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _quote(item: dict) -> str:
    q = item.get("quote")
    if not q:
        m = re.match(r'quote: "(.*)"$', str(item.get("evidence") or ""), re.S)
        q = m.group(1) if m else ""
    return " ".join(re.findall(r"[a-z0-9$]+", str(q).lower()))


def signature_topic(item: dict, sig_words: set[str]) -> bool:
    """The finding is about the signature missing from the first screen (measured, or raised by any critic)."""
    if item.get("source") == "measure" and item.get("check") == "signature":
        return True
    text = f"{item.get('element', '')} {item.get('problem', '')}"
    return bool(FIRST_SCREEN_TOPIC.search(text)) and (bool(_bag(text) & sig_words) or "signature" in text.lower())


def same_problem(a: dict, b: dict, sig_words: set[str] = frozenset()) -> bool:
    if signature_topic(a, sig_words) and signature_topic(b, sig_words):
        return True
    if a.get("source") != b.get("source"):
        return False
    if a.get("source") in ("measure", "runtime"):
        return a.get("check") == b.get("check") and a.get("criterion") == b.get("criterion")
    if a.get("source") == "content":
        short, long = sorted((_quote(a), _quote(b)), key=len)
        n, m = len(short.split()), len(long.split())
        # the same words: near-identical quotes, or a long quote inside another (a shared 3-word label is not enough)
        if short and n >= 3 and f" {short} " in f" {long} " and (n >= 0.6 * m or n >= 6):
            return True
        ea, eb = _bag(a.get("element")), _bag(b.get("element"))
        na, nb = {w for w in ea if w.isdigit()}, {w for w in eb if w.isdigit()}
        if na and nb and na != nb:  # step 1 and step 3 are different elements
            return False
        return _jaccard(ea, eb) >= CONTENT_MATCH
    if a.get("source") in GATE_FIX_SOURCES:  # the final gate's own change notes never merge
        return False
    if (a.get("check") or a.get("criterion")) != (b.get("check") or b.get("criterion")):
        return False
    return _jaccard(_bag(f"{a.get('element')} {a.get('problem')}"), _bag(f"{b.get('element')} {b.get('problem')}")) >= CRAFT_MATCH


def revision_answers(path: Path) -> dict[str, str]:
    """The reviser's line per fix-list item in a REVISION.md: id -> line."""
    out: dict[str, str] = {}
    if path.exists():
        for m in re.finditer(r"^\s*[-*]\s*\**([A-Z]{1,2}\d+)\b[^\n]*", path.read_text(errors="replace"), re.M):
            out.setdefault(m.group(1), m.group(0).strip().lstrip("-* ")[:300])
    return out


def round_items(merged: dict, craft: list[dict], runtime: dict, content: dict, page_text: str, sig: dict | None,
                fixture: bool) -> dict:
    """One review round's findings as fix-list items, split into blocking and minor (the combine rules)."""
    blocking, minor = [], []
    for f in runtime.get("findings", []):
        item = {"source": "runtime", "id": f.get("id"), "severity": f.get("severity"), "element": f.get("element"),
                "problem": f.get("problem"), "evidence": f.get("evidence"), "suggestion": f.get("suggestion"),
                "criterion": f.get("criterion"), "check": f.get("check"), "viewport": f.get("viewport")}
        sev = f.get("severity") if isinstance(f.get("severity"), int) else 0
        # fixture pages are converter fixtures, not designs: their runtime findings stay advisory
        (blocking if sev >= 3 and not fixture else minor).append(item)
    measured = signature_finding(sig)
    if measured:
        (blocking if measured["severity"] >= 3 and not fixture else minor).append(measured)
    good = [f for f in content.get("findings", []) if isinstance(f, dict) and f.get("check") in COPY_CHECKS
            and isinstance(f.get("severity"), int) and str(f.get("element", "")).strip() and str(f.get("problem", "")).strip()]
    kept, dropped = verify_quotes(good, page_text)
    dropped += [{**f, "verified": False, "dropped": "malformed finding"} for f in content.get("findings", [])
                if isinstance(f, dict) and f not in good]
    for f in kept:
        item = {"source": "content", "id": f.get("id"), "severity": f.get("severity"), "element": f.get("element"),
                "problem": f.get("problem"), "evidence": f"quote: \"{f.get('quote')}\"", "suggestion": f.get("suggestion"),
                "check": f.get("check"), "quote": f.get("quote")}
        (blocking if f["severity"] >= 3 and not fixture else minor).append(item)
    for f in merged.get("findings", []):
        item = {"source": "usability", "id": f.get("id"), "severity": f.get("severity"), "element": f.get("element"),
                "problem": f.get("problem"), "evidence": f.get("evidence"), "suggestion": f.get("suggestion"),
                "criterion": f.get("criterion") or f.get("heuristic")}
        sev = f.get("severity") if isinstance(f.get("severity"), int) else 0
        (blocking if sev >= 4 or (sev >= 3 and f.get("status") == "confirmed") else minor).append(item)
    template = []
    for c in craft:
        for f in c.get("findings", []):
            item = {"source": "craft", "id": f.get("id"), "severity": f.get("severity"), "element": f.get("element"),
                    "problem": f.get("problem"), "evidence": f.get("evidence"), "suggestion": f.get("suggestion"),
                    "check": f.get("check")}
            sev = f.get("severity") if isinstance(f.get("severity"), int) else 0
            (blocking if sev >= 3 else minor).append(item)
        template.append(c.get("template_test", {}))
    return {"blocking": blocking, "minor": minor, "kept": kept, "dropped": dropped, "template": template}


def load_round(review: Path) -> tuple | None:
    """A saved review folder's inputs for round_items, or None when it is incomplete."""
    need = [review / "findings.json", review / "runtime" / "runtime.json", review / "content" / "content.json", review / "page-text.md"]
    if not all(p.exists() for p in need):
        return None
    sig = load(review / "signature.json") if (review / "signature.json").exists() else None
    return (load(need[0]), [load(f) for f in sorted((review / "craft").glob("*.json"))], load(need[1]), load(need[2]),
            need[3].read_text(), sig)


def round_by_round(rounds: Path, number: int) -> list[str]:
    """One handoff line per round from its decision.json: blockers (and repeats), content raised again, the
    signature's first-screen numbers and kept text."""
    lines = []
    for k in range(1, number + 1):
        path = rounds / f"r{k:02d}" / "decision.json"
        if not path.exists():
            continue
        dec = load(path)
        blockers = []
        for b in dec.get("blockers") or []:
            others = [str(r) for r in b.get("seen_in") or [] if r != k]
            blockers.append(f"{b.get('source')} {b.get('id')}" + (f" (also round {', '.join(others)}; {b.get('action')})" if others else ""))
        line = f"- Round {k}: verdict {dec.get('verdict')}; blockers: {', '.join(blockers) or 'none'}"
        repeats = dec.get("content_repeats") or []
        if repeats:
            line += "; content raised again: " + ", ".join(f"{c.get('id')} (rounds {', '.join(map(str, c.get('seen_in') or []))})" for c in repeats)
        sig = dec.get("signature") or {}
        if sig:
            line += f"; signature {sig.get('status')} " + ", ".join(f"{w} {v[0]}/{v[1]} px" for w, v in (sig.get("screens") or {}).items())
        kept = dec.get("kept_text") or {}
        if kept:
            line += f"; kept text {kept.get('status')}" + (f" (lost: {kept['lost']})" if kept.get("lost") else "")
        lines.append(line)
    return lines or ["- no round decisions recorded"]


def recommendation(spec: dict) -> dict | None:
    """The art director's recommended concept from concepts.json, or None when missing or malformed."""
    rec = spec.get("recommended") if isinstance(spec, dict) else None
    if not isinstance(rec, dict) or rec.get("concept") not in CONCEPT_IDS or words(str(rec.get("reason", ""))) < 8:
        return None
    return {"concept": rec["concept"], "reason": str(rec["reason"]).strip()}


# ---------------------------------------------------------------- the job


class Job:
    def __init__(self, workspace: str, fixture: bool, pilot: bool = False, bench: bool = False):
        if fixture + pilot + bench > 1:
            raise ValueError("a run is the fixture or the pilot or the benchmark, not more than one")
        self.root = Path(workspace).resolve()
        self.fixture = fixture
        self.pilot = pilot  # fictional trials: the worker's provisional direction, never an approval
        # Benchmark runs (queue #10): fixed fictional briefs, the art director's recommended concept, no
        # gates; the result is labelled not approved and is judged blind on the scoreboard.
        self.bench = bench
        self.packet = self.root / "homepage"
        self.packet.mkdir(parents=True, exist_ok=True)
        self.state_path = self.packet / "job.json"
        workflow = "design_homepage_v2" + ("_fixture" if fixture else "_pilot" if pilot else "_bench" if bench else "")
        self.state = upgrade_state(load(self.state_path)) if self.state_path.exists() else {
            "version": VERSION, "workflow": workflow,
            "created_at": now(), "stages": {}, "round": 0, "revisions": 0, "change_rounds": 0,
            "decision_seq": 0, "planned_seq": -1,
            "direction_approved": {"approved": False, "decided_by": None},
            "final_approved": {"approved": False, "decided_by": None}}
        if self.state.get("workflow") != workflow:
            raise ValueError(f"workspace belongs to another workflow ({self.state.get('workflow')}, not {workflow}); "
                             "use a fresh workspace")

    def commit(self) -> None:
        """Save the state and keep receipts that stages on parallel branches saved meanwhile.

        taste runs beside references, and in the fixture runtime beside the stand-in review: each
        loads job.json, adds its receipt and saves. Without this merge the last writer dropped the
        other's receipt (fixture run ead8a545 lost taste and review_fixture-1/2; pilot 1dd9858c lost taste).
        """
        with (self.packet / ".job.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.state_path.exists():
                saved = load(self.state_path).get("stages", {})
                self.state["stages"] = {**saved, **self.state["stages"]}
            save(self.state_path, self.state)

    def receipt(self, stage: str, fingerprint: str, output: dict) -> dict:
        self.state["stages"][stage] = {"fingerprint": fingerprint, "completed_at": now(), "output": output}
        self.commit()
        return output

    def cached(self, stage: str, fingerprint: str) -> dict | None:
        receipt = self.state["stages"].get(stage)
        if receipt:
            if receipt["fingerprint"] != fingerprint:
                raise ValueError(f"saved {stage} inputs changed; use a fresh workspace rather than silently repeating work")
            return {**receipt["output"], "reused": True}
        return None

    @property
    def concepts_dir(self) -> Path:
        return self.packet / "concepts"

    @property
    def site(self) -> Path:
        return self.packet / "site"

    @property
    def copy_dir(self) -> Path:
        return self.packet / "copy"

    def deck(self) -> dict | None:
        path = self.copy_dir / "copy.json"
        return load(path) if path.exists() else None

    def taste_list(self) -> list[str]:
        path = self.packet / "taste" / "source.json"
        return list(load(path).get("entries", [])) if path.exists() else []

    def record_taste(self, key: str, entry: dict) -> None:
        """Save one gate answer, with who decided, for the host's taste files (homepage_v2_control.py taste-sync).

        Pilot and benchmark runs record nothing: their direction is a provisional pick, not a gate answer.
        """
        if self.pilot or self.bench:
            return
        path = self.packet / "taste" / "entries.json"
        data = load(path) if path.exists() else {"workflow": self.state["workflow"], "entries": []}
        brief = load(self.packet / "brief.json")
        item = {"key": key, "recorded_at": now(), "product": brief.get("product"), "fixture": self.fixture, **entry}
        data["entries"] = [e for e in data["entries"] if e.get("key") != key] + [item]
        save(path, data)

    # -- brief and research

    def brief(self, raw: str) -> dict:
        value = brief_contract(json.loads(raw) if raw.strip() else dict(FIXTURE_BRIEF) if self.fixture else None)
        if self.fixture and not value.get("fixture"):
            raise ValueError("the fixture workflow refuses real briefs")
        if not self.fixture and value.get("fixture"):
            raise ValueError("the real workflow refuses fixture briefs")
        if (self.pilot or self.bench) and not value["fictional"]:
            raise ValueError(f"the {'pilot' if self.pilot else 'benchmark'} workflow refuses real deliverables; real products go through design_homepage_v2")
        fp = digest(value)
        cached = self.cached("brief", fp)
        if cached:
            return cached
        save(self.packet / "brief.json", value)
        assets = []
        for asset in value.get("assets", []):
            src = Path(asset["path"])
            if not src.is_absolute():
                src = self.root / src
            if not src.is_file() or h2p.image_kind(src.read_bytes()) is None:
                raise ValueError(f"asset {asset['path']} missing or not an image")
            dest = self.packet / "assets" / src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            assets.append({**asset, "file": f"assets/{src.name}"})
        lines = [f"# Homepage brief — {value['product']}", "",
                 f"Category: {value['category']}", f"Audience: {value['audience']}",
                 f"Homepage job: {value['purpose']}", f"Primary action: {value['cta']}",
                 f"Fictional: {value['fictional']}" + (f" — disclosure: {value['disclosure']}" if value['fictional'] else ""),
                 "", "## Facts (the only source for claims on the page; the copy deck cites these numbers)"]
        lines += [f"{i}. {f}" for i, f in enumerate(value["facts"], 1)]
        for key in ("headline", "voice", "sections", "brand", "avoid"):
            if value.get(key):
                lines += ["", f"## {key.title()}", json.dumps(value[key], ensure_ascii=False, indent=1)]
        if assets:
            lines += ["", "## Images supplied (sanitized, usable on the page)"]
            lines += [f"- {a['file']} ({a['kind']}): {a['alt']}" for a in assets]
        lines += ["", "## Constraints",
                  "- Widths 390, 768, 1440. WCAG 2.2 AA. Body text >= 16 px.",
                  "- All assets local: licensed fonts fetched by the workflow, supplied images, code-made SVG/CSS art.",
                  "- No AI-generated images, no stock photos, no invented customers, numbers, logos or quotes.",
                  "- No signup, payment, analytics or tracking. Penpot is the editable master after conversion."]
        (self.packet / "BRIEF.md").write_text("\n".join(lines) + "\n")
        (self.packet / "PAGE_RULES.md").write_text(PAGE_RULES)
        self.state["assets"] = assets
        return self.receipt("brief", fp, {"status": "completed", "brief_path": "homepage/BRIEF.md", "assets": len(assets)})

    def references(self, raw: str) -> dict:
        if self.fixture and not raw.strip():
            raw = json.dumps([{"name": f"Fixture {k}", "fixture": v, "why": "stand-in reference (fixture)"}
                              for k, v in FIXTURE_CONCEPTS.items()])
        refs = references_contract(json.loads(raw or "[]"), self.fixture)
        fp = digest(refs)
        cached = self.cached("references", fp)
        if cached:
            return cached
        out = self.packet / "references"
        if out.exists():
            shutil.rmtree(out)
        jobs = []
        for i, ref in enumerate(refs, 1):
            stem = f"ref-{i:02d}"
            for width, height in ((1440, 900), (390, 844)):
                job = {"name": f"{stem}-{width}", "width": width, "height": height,
                       "maxHeight": 4200 if width == 1440 else 3400, "freeze": False}
                if self.fixture:
                    job["path"] = ref["fixture"]
                else:
                    job.update({"external": True, "url": ref["url"]})
                jobs.append(job)
        root = FIXTURE_SITE if self.fixture else self.packet
        results = browser_jobs(root, out, jobs)
        captured = []
        for i, ref in enumerate(refs, 1):
            stem = f"ref-{i:02d}"
            got = {r["name"]: r for r in results if r["name"].startswith(stem)}
            ok = all(got.get(f"{stem}-{w}", {}).get("ok") for w in (1440, 390))
            captured.append({**ref, "id": stem, "ok": ok, "shots": [f"references/{stem}-1440.png", f"references/{stem}-390.png"] if ok else [],
                             "error": None if ok else "; ".join(str(r.get("error")) for r in got.values() if not r.get("ok"))[:300]})
        good = [c for c in captured if c["ok"]]
        need = 2 if self.fixture else 8
        save(out / "references.json", captured)
        lines = ["# References — research only", "",
                 "Acclaimed homepages in this category, captured to study what makes them memorable.",
                 "Never copy or trace their layouts, illustrations, copy or assets.", ""]
        for c in captured:
            lines.append(f"- {c['id']} {c['name']}: {c['why']}" + (f" — shots {', '.join(c['shots'])}" if c["ok"] else f" — NOT CAPTURED: {c['error']}"))
        (out / "REFERENCES.md").write_text("\n".join(lines) + "\n")
        if len(good) < need:
            raise ValueError(f"only {len(good)} of {len(refs)} references captured; need {need} (see homepage/references/REFERENCES.md)")
        return self.receipt("references", fp, {"status": "completed", "captured": len(good), "failed": len(refs) - len(good),
                                               "references_path": "homepage/references/REFERENCES.md"})

    # -- the taste file and the words

    def taste(self, raw: str) -> dict:
        text, truncated = trim_taste((raw or "").replace("\r\n", "\n"))
        ids = taste_ids(text)
        fp = digest({"taste": text})
        cached = self.cached("taste", fp)
        if cached:
            return cached
        body = text.strip() or "No entries yet: no design gate has been answered since the taste file started."
        (self.packet / "TASTE.md").write_text(
            "# The owner's taste (private; passed into this run)\n\n"
            "What earlier design gates chose, rejected and said; each entry says who decided (design, or owner for his\n"
            "own words, which outrank). Treat it as evidence of the owner's taste:\n"
            "follow what was liked, avoid what was rejected, and say how (concepts cite entry ids such as T3 in\n"
            "taste_use). The brief and its facts still win. Never quote these notes on the page.\n"
            + ("\n(Older entries left out: the file is longer than this run takes.)\n" if truncated else "")
            + "\n---\n\n" + body + "\n")
        save(self.packet / "taste" / "source.json", {"sha256": hashlib.sha256((raw or "").encode()).hexdigest(),
                                                     "chars": len(raw or ""), "entries": ids, "truncated": truncated,
                                                     "received_at": now()})
        return self.receipt("taste", fp, {"status": "completed", "entries": len(ids), "truncated": truncated,
                                          "taste_path": "homepage/TASTE.md"})

    def copy_fixture(self, phase: str) -> dict:
        """Model-free stand-ins for the copywriter (draft, revise) and the content critic (review)."""
        if phase not in ("draft", "review", "revise"):
            raise ValueError("phase is draft, review or revise")
        fp = digest({"phase": phase, "deck": FIXTURE_DECK, "review": FIXTURE_COPY_REVIEW})
        cached = self.cached(f"copy_fixture-{phase}", fp)
        if cached:
            return cached
        cdir = self.copy_dir
        if phase == "draft":
            save(cdir / "copy.json", FIXTURE_DECK)
        elif phase == "review":
            save(cdir / "review.json", {"target": "deck", "fixture": True, "summary": "Fixture content review (no model).",
                                        "findings": FIXTURE_COPY_REVIEW})
        else:
            deck = load(cdir / "copy.json")
            save(cdir / "copy.json", {**deck, "subhead": FIXTURE_SUBHEAD_AFTER})
            (cdir / "CHANGES.md").write_text("# Copy changes (fixture)\n\n- K1: rewrote the subhead to say which steps are exercised.\n"
                                           "- K2: its quote is not in the deck; nothing to change.\n")
        return self.receipt(f"copy_fixture-{phase}", fp, {"status": "completed", "phase": phase})

    def copy_check(self, phase: str) -> dict:
        if phase not in ("draft", "final"):
            raise ValueError("phase is draft or final")
        cdir = self.copy_dir
        path = cdir / "copy.json"
        if not path.exists():
            raise ValueError("homepage/copy/copy.json missing: the copywriter wrote nothing")
        raw_deck = path.read_text()
        review_text = (cdir / "review.json").read_text() if phase == "final" and (cdir / "review.json").exists() else ""
        changes = (cdir / "CHANGES.md").read_text() if phase == "final" and (cdir / "CHANGES.md").exists() else ""
        fp = digest({"phase": phase, "deck": raw_deck, "review": review_text, "changes": changes})
        attempt = self.state.setdefault("copy_checks", {}).get(phase, 0)
        key = f"copy_check-{phase}-{attempt}"
        prior = self.state["stages"].get(key)
        if prior and prior["fingerprint"] == fp:
            return {**prior["output"], "reused": True}
        if prior:  # the copywriter changed the deck since the last check: a new attempt
            attempt += 1
            key = f"copy_check-{phase}-{attempt}"
        self.state["copy_checks"][phase] = attempt
        brief = load(self.packet / "brief.json")
        try:
            deck = json.loads(raw_deck)
        except ValueError as exc:
            deck, problems = {}, [f"copy.json is not valid JSON ({exc.msg} at line {exc.lineno})"]
        else:
            problems = copy_contract(deck, brief)
        out: dict[str, Any] = {"status": "completed", "phase": phase, "attempt": attempt}
        check: dict[str, Any] = {"phase": phase, "attempt": attempt, "checked_at": now(), "problems": problems,
                                 "facts": copy_facts(deck, brief) if isinstance(deck, dict) else {}}
        if phase == "draft":
            if not (cdir / "copy-draft.json").exists():  # the 'before' of the before/after
                (cdir / "copy-draft.json").write_text(raw_deck)
                (cdir / "COPY-draft.md").write_text(render_copy(deck, brief, "Copy deck (draft, before review)"))
            (cdir / "COPY.md").write_text(render_copy(deck, brief, "Copy deck (draft)"))
        else:
            if not review_text:
                raise ValueError("homepage/copy/review.json missing: the content review wrote nothing")
            review = json.loads(review_text)
            draft = load(cdir / "copy-draft.json") if (cdir / "copy-draft.json").exists() else {}
            good, malformed = [], []
            for f in review.get("findings", []) if isinstance(review, dict) else []:
                ok = (isinstance(f, dict) and f.get("check") in COPY_CHECKS and isinstance(f.get("severity"), int)
                      and 0 <= f["severity"] <= 4 and all(str(f.get(k, "")).strip() for k in ("id", "element", "quote", "problem", "suggestion")))
                (good if ok else malformed).append(f)
            kept, dropped = verify_quotes(good, deck_text(draft) if draft else raw_deck)
            dropped += [{**f, "verified": False, "dropped": "malformed finding"} for f in malformed if isinstance(f, dict)]
            final_text = norm_text(deck_text(deck)) if isinstance(deck, dict) else ""
            answers = {}
            for f in kept:
                answer = next((ln.strip() for ln in changes.splitlines() if re.search(rf"\b{re.escape(str(f['id']))}\b", ln)), "")
                gone = norm_text(f["quote"]).strip('"') not in final_text
                answers[f["id"]] = {"quote_gone": gone, "answer": answer}
                if f["severity"] >= 3 and not gone and not answer:
                    problems.append(f"{f['id']} (severity {f['severity']}) still has \"{f['quote'][:80]}\" and CHANGES.md does not answer it")
            save(cdir / "review-checked.json", {"verified": kept, "dropped": dropped, "answers": answers})
            changed = self.copy_diff(draft, deck if isinstance(deck, dict) else {}, kept, dropped, answers)
            (cdir / "COPY.md").write_text(render_copy(deck, brief, "Copy deck (final, after content review)"))
            check.update({"verified_findings": len(kept), "dropped_findings": len(dropped), "changed_fields": changed})
            out.update({"verified_findings": len(kept), "dropped_findings": len(dropped), "changed_fields": changed,
                        "diff_path": "homepage/copy/COPY-DIFF.md"})
        check["verdict"] = "ok" if not problems else "retry"
        save(cdir / "check.json", check)
        save(cdir / f"check-{phase}-{attempt}.json", check)
        out.update({"verdict": check["verdict"], "problems": len(problems), "copy_path": "homepage/copy/COPY.md"})
        return self.receipt(key, fp, out)

    def copy_diff(self, before: dict, after: dict, kept: list, dropped: list, answers: dict) -> int:
        old, new = dict(deck_fields(before)), dict(deck_fields(after))
        for n in before.get("notices") or []:
            if isinstance(n, dict):
                old[f"notice {n.get('id')}"] = f"{n.get('text')} ({n.get('placement')})"
        for n in after.get("notices") or []:
            if isinstance(n, dict):
                new[f"notice {n.get('id')}"] = f"{n.get('text')} ({n.get('placement')})"
        rows = [(k, old.get(k, ""), new.get(k, "")) for k in list(dict.fromkeys([*old, *new])) if old.get(k, "") != new.get(k, "")]
        cell = lambda s: (s or "(none)").replace("|", "\\|").replace("\n", " ")  # noqa: E731
        lines = ["# Copy deck \u2014 before and after the content review", "",
                 "Before: homepage/copy/copy-draft.json (the copywriter's draft). After: homepage/copy/copy.json.",
                 f"Content review: {len(kept)} findings checked against the draft's words, {len(dropped)} dropped "
                 "(quote not in the draft, or malformed).", "", "## Findings and answers", ""]
        for f in kept:
            a = answers.get(f["id"], {})
            lines += [f"- {f['id']} [{f['check']}, severity {f['severity']}] {f['element']}: \"{f['quote']}\"",
                      f"  Problem: {f['problem']}", f"  Suggestion: {f['suggestion']}",
                      f"  Result: {'quote gone from the deck' if a.get('quote_gone') else 'quote still in the deck'}"
                      + (f"; copywriter: {a['answer']}" if a.get("answer") else "")]
        for f in dropped:
            lines.append(f"- DROPPED {f.get('id')} ({f.get('dropped')}): \"{str(f.get('quote', ''))[:120]}\"")
        lines += ["", f"## Changed fields ({len(rows)} of {len(set(old) | set(new))})", "", "| field | before | after |", "|---|---|---|"]
        lines += [f"| {k} | {cell(a)} | {cell(b)} |" for k, a, b in rows] or ["| (none) | | |"]
        (self.copy_dir / "COPY-DIFF.md").write_text("\n".join(lines) + "\n")
        return len(rows)

    def copy_next(self) -> dict:
        """Loop control after the final copy check: report its verdict, change nothing."""
        path = self.copy_dir / "check.json"
        if not path.exists():
            raise ValueError("no copy check to act on")
        check = load(path)
        if check.get("phase") != "final":
            raise ValueError("the last copy check was not the final one")
        return {"status": "completed", "verdict": check["verdict"], "attempt": check.get("attempt"),
                "problems": len(check.get("problems", []))}

    # -- concepts

    def concepts_fixture(self) -> dict:
        deck = self.deck() or FIXTURE_DECK
        heads = [h["text"] for h in deck.get("headlines", [])][:3]
        taste = self.taste_list()
        fp = digest({"fixture": FIXTURE_CONCEPTS, "site": tree_digest(FIXTURE_SITE), "heads": heads, "taste": taste})
        cached = self.cached("concepts_fixture", fp)
        if cached:
            return cached
        specs = {
            "A": ("Ridgeline Atlas", {"display": {"family": "Fraunces", "weights": [600, 800]}, "text": {"family": "Instrument Sans", "weights": [400, 600]}},
                  {"dominant": "#B8482A", "accent": "#3E5B4A", "ink": "#1F1A17", "surface": "#FBF6EE", "on_dominant": "#FFFFFF", "on_accent": "#FFFFFF"},
                  ["gradient-hero", "image-right", "three-card-grid", "serif-display"]),
            "B": ("Pulse Board", {"display": {"family": "Bricolage Grotesque", "weights": [700, 800]}, "text": {"family": "Atkinson Hyperlegible", "weights": [400, 700]}},
                  {"dominant": "#5B4BDB", "accent": "#FF5C48", "ink": "#18163A", "surface": "#FFFFFF", "on_dominant": "#FFFFFF", "on_accent": "#18163A"},
                  ["radial-glow", "dashboard-screenshot", "pricing-table", "chart-svg"]),
            "C": ("Harbor Night", {"display": {"family": "DM Serif Display", "weights": [400]}, "text": {"family": "Figtree", "weights": [400, 600, 800]}},
                  {"dominant": "#0E1626", "accent": "#E2AA5A", "ink": "#F4EFE6", "surface": "#0E1626", "on_dominant": "#F4EFE6", "on_accent": "#0E1626"},
                  ["photo-overlay-hero", "stat-strip", "wave-divider", "menu-list"]),
        }
        concepts = []
        for cid, page in FIXTURE_CONCEPTS.items():
            name, fonts, palette, sig = specs[cid]
            dest = self.concepts_dir / cid
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(FIXTURE_SITE, dest, ignore=shutil.ignore_patterns("*.html"))
            shutil.copyfile(FIXTURE_SITE / page, dest / "index.html")
            words = ("Fixture concept " + name + " stands in for an art director's design brief. ") * 20
            use = (f"Fixture stand-in: it follows {', '.join(taste)} from the owner's taste file." if taste else
                   "Fixture stand-in: the taste file has no entries yet, so there is nothing to follow.")
            concepts.append({"id": cid, "name": name, "brief": words.strip(), "fonts": fonts, "palette": palette,
                             "imagery": "code-made images and inline SVG", "signature_move": sig[0],
                             "motion": "none (fixture)", "layout_signature": sig, "page": f"homepage/concepts/{cid}/index.html",
                             "headline": heads[CONCEPT_IDS.index(cid) % len(heads)] if heads else "", "taste_use": use})
        save(self.concepts_dir / "concepts.json", {"concepts": concepts, "fixture": True})
        return self.receipt("concepts_fixture", fp, {"status": "completed", "concepts": len(concepts)})

    def concepts_check(self, phase: str) -> dict:
        if phase not in ("draft", "final"):
            raise ValueError("phase is draft or final")
        cdir = self.concepts_dir
        spec_path = cdir / "concepts.json"
        if not spec_path.exists():
            raise ValueError("homepage/concepts/concepts.json missing: the art director wrote nothing")
        spec = load(spec_path)
        pages = (tree_digest(cdir / "A") + tree_digest(cdir / "B") + tree_digest(cdir / "C")
                 if all((cdir / c).exists() for c in CONCEPT_IDS) else "")
        fp = digest({"phase": phase, "concepts": pages, "spec": spec})
        attempt = self.state.setdefault("concept_checks", {}).get(phase, 0)
        key = f"concepts_check-{phase}-{attempt}"
        prior = self.state["stages"].get(key)
        if prior and prior["fingerprint"] == fp:
            return {**prior["output"], "reused": True}
        if prior:  # new art-director work since the last check: a new attempt
            attempt += 1
            key = f"concepts_check-{phase}-{attempt}"
        self.state["concept_checks"][phase] = attempt
        passed = self.passed_draft_check(pages, spec) if phase == "final" else None
        if passed is not None:  # refine was skipped (queue #34): these are the drafts that passed, as they were checked
            check = {**passed[1], "phase": "final", "attempt": attempt, "checked_at": now(), "reused_draft_check": passed[0]}
            return self.finish_check(key, fp, check, spec["concepts"], bool(spec.get("fixture")))
        brief = load(self.packet / "brief.json")
        brand_fonts = {f.lower() for f in brief.get("brand", {}).get("fonts", [])}
        concepts = spec.get("concepts") if isinstance(spec, dict) else None
        problems: list[str] = []
        if not isinstance(concepts, list) or sorted(str(c.get("id")) for c in concepts if isinstance(c, dict)) != list(CONCEPT_IDS) or len(concepts) != 3:
            problems.append("concepts.json needs exactly three concept objects with ids A, B and C")
            check = {"phase": phase, "attempt": attempt, "checked_at": now(), "verdict": "retry", "problems": problems}
            save(cdir / "check.json", check)
            save(cdir / f"check-{phase}-{attempt}.json", check)
            return self.receipt(key, fp, {"status": "completed", "phase": phase, "attempt": attempt, "verdict": "retry",
                                          "problems": len(problems), "check_path": "homepage/concepts/check.json"})
        deck = self.deck()
        taste = self.taste_list()
        for c in concepts:
            problems += concept_contract(c, brand_fonts)
            page = cdir / c["id"] / "index.html"
            problems += html_problems(page)
            problems += concept_words_problems(c, deck, taste)
            if deck is not None and not spec.get("fixture") and page.is_file():  # fixture pages predate any deck
                problems += page_copy_problems(page.read_text(errors="replace"), deck, c.get("headline"),
                                               bool(brief.get("fictional")), f"concept {c['id']} page")
        if not spec.get("fixture"):  # the fixture pages are the seed's own pairings
            problems += pairing_problems(concepts, recorded_pairings(pairing_log(self.root), self.root.name), brand_fonts)
        font_issues: list[str] = []
        faces_by_concept: dict[str, list[dict]] = {}
        for c in concepts:
            faces: list[dict] = []
            fonts = c.get("fonts") or {}
            if spec.get("fixture"):
                faces_by_concept[c["id"]] = []
                continue
            for role in ("display", "text"):
                face = fonts.get(role) or {}
                if face.get("family") and isinstance(face.get("weights"), list):
                    got = font_files(face["family"], [w for w in face["weights"] if isinstance(w, int)], bool(face.get("italic")),
                                     self.packet / "fonts", font_issues)
                    if not got:
                        problems.append(f"concept {c['id']}: font {face['family']} unavailable (needs a Google Fonts family with a licence)")
                    faces += got
            faces_by_concept[c["id"]] = faces
            copy_fonts(faces, self.packet / "fonts", cdir / c["id"] / "fonts")
        jobs = []
        for c in concepts:
            for width, height in ((1440, 900), (390, 844)):
                jobs.append({"name": f"{c['id'].lower()}-{width}", "path": f"{c['id']}/index.html", "width": width, "height": height,
                             "maxHeight": 3600 if width == 1440 else 3200, "freeze": True})
        shots = cdir / "shots"
        results = {r["name"]: r for r in browser_jobs(cdir, shots, jobs)}
        renders = {}
        for c in concepts:
            for width in (1440, 390):
                r = results.get(f"{c['id'].lower()}-{width}", {})
                renders[f"{c['id']}-{width}"] = r
                if not r.get("ok"):
                    problems.append(f"concept {c['id']} did not render at {width}: {r.get('error')}")
                    continue
                if r.get("scrollWidth", 0) > width + 1:
                    problems.append(f"concept {c['id']} scrolls sideways at {width} ({r['scrollWidth']} px)")
                loaded = {f.lower() for f in r.get("loadedFamilies", [])}
                for role in ("display", "text"):
                    fam = str((c.get("fonts") or {}).get(role, {}).get("family", "")).lower()
                    if fam and fam not in loaded:
                        problems.append(f"concept {c['id']} at {width}: {role} font {fam} never loaded (link fonts/fonts.css and use the family name)")
        ids = [c["id"] for c in concepts]
        axe = concept_axe(cdir, ids)
        problems += axe_problems(axe, ids)
        thumbs = thumbnail_diffs(shots, [f"{cid.lower()}-1440" for cid in CONCEPT_IDS]) if all(renders.get(f"{cid}-1440", {}).get("ok") for cid in CONCEPT_IDS) else {}
        pairs = []
        by_id = {c["id"]: c for c in concepts}
        for i, a in enumerate(CONCEPT_IDS):
            for b in CONCEPT_IDS[i + 1:]:
                ca, cb = by_id[a], by_id[b]
                fa, fb = ca.get("fonts") or {}, cb.get("fonts") or {}
                pa, pb = ca.get("palette") or {}, cb.get("palette") or {}
                pair = {"pair": f"{a}-{b}",
                        "same_display_font": str(fa.get("display", {}).get("family", "")).lower() == str(fb.get("display", {}).get("family", "")).lower(),
                        "same_type_pairing": [str(fa.get(r, {}).get("family", "")).lower() for r in ("display", "text")] == [str(fb.get(r, {}).get("family", "")).lower() for r in ("display", "text")],
                        "dominant_delta_e": delta_e(pa["dominant"], pb["dominant"]) if HEX.match(str(pa.get("dominant", ""))) and HEX.match(str(pb.get("dominant", ""))) else None,
                        "signature_jaccard": jaccard(ca.get("layout_signature") or [], cb.get("layout_signature") or []),
                        "thumbnail_diff": thumbs.get(f"{a.lower()}-1440|{b.lower()}-1440")}
                why = []
                if pair["same_display_font"] or pair["same_type_pairing"]:
                    why.append("same display face or type pairing")
                if pair["dominant_delta_e"] is not None and pair["dominant_delta_e"] < DISTINCT["min_dominant_delta_e"]:
                    why.append(f"dominant colours too close (OKLab ΔE {pair['dominant_delta_e']})")
                if pair["signature_jaccard"] > DISTINCT["max_signature_jaccard"]:
                    why.append(f"layout signatures overlap ({pair['signature_jaccard']})")
                if pair["thumbnail_diff"] is not None and pair["thumbnail_diff"] < DISTINCT["min_thumbnail_diff"]:
                    why.append(f"first screens look alike (difference {pair['thumbnail_diff']})")
                pair["near_duplicate"] = bool(why)
                pair["why"] = why
                if why:
                    problems.append(f"concepts {a} and {b} are near-duplicates: " + "; ".join(why))
                pairs.append(pair)
        recommended = recommendation(spec)
        if self.bench and recommended is None:
            problems.append('concepts.json needs "recommended": {"concept": "A", "B" or "C", "reason": "why, 8 words or more"}'
                            " (a benchmark run builds the art director's pick)")
        sheet = self.contact_sheet(concepts)
        verdict = "ok" if not problems else "retry"
        check = {"phase": phase, "attempt": attempt, "checked_at": now(), "verdict": verdict, "problems": problems,
                 "font_issues": font_issues, "distinctness_bar": DISTINCT, "pairs": pairs, "renders": renders,
                 "fonts": {cid: [f"{f['family']} {f['weight']} {f['style']}" for f in faces] for cid, faces in faces_by_concept.items()},
                 "pairings": {c["id"]: " + ".join(concept_pairing(c) or ("?", "?")) for c in concepts},
                 "axe": {name: {"ok": r.get("ok"), "settle": r.get("settle"), "error": r.get("error"),
                                "violations": [{k: v.get(k) for k in ("id", "impact", "nodes", "targets")} for v in r.get("violations") or []]}
                         for name, r in sorted(axe.items())},
                 "contact_sheet": sheet, "recommended": recommended}
        return self.finish_check(key, fp, check, concepts, bool(spec.get("fixture")))

    def passed_draft_check(self, pages: str, spec: dict) -> tuple[str, dict] | None:
        """The last draft check (file name, contents) when it passed on exactly these pages and spec, else None.

        Refine runs only when the draft check fails (queue #34: on three benchmark briefs, refined concepts
        beat their drafts on only 5 of the craft critic's 10 checklist items, at a third of the concept
        stage's cost), so a final check after a skipped refine sees the same pages and spec."""
        n = self.state.get("concept_checks", {}).get("draft")
        receipt = self.state["stages"].get(f"concepts_check-draft-{n}") if n is not None else None
        path = self.concepts_dir / f"check-draft-{n}.json"
        if (not receipt or receipt["output"].get("verdict") != "ok" or not path.is_file()
                or receipt["fingerprint"] != digest({"phase": "draft", "concepts": pages, "spec": spec})):
            return None
        return path.name, load(path)

    def finish_check(self, key: str, fp: str, check: dict, concepts: list[dict], fixture: bool) -> dict:
        """Save a concept check, record the pairings a passed final check offers the gate, answer the node."""
        cdir, phase, attempt, verdict = self.concepts_dir, check["phase"], check["attempt"], check["verdict"]
        if verdict == "ok" and phase == "final" and not fixture:  # offered to the gate: later runs pick others
            try:
                check["pairings_recorded"] = record_pairings(pairing_log(self.root), self.root.name, "offered", concepts)
            except OSError as exc:
                check["pairings_recorded"] = f"not recorded: {exc.__class__.__name__}: {exc}"
        save(cdir / "check.json", check)
        save(cdir / f"check-{phase}-{attempt}.json", check)
        if phase == "draft":
            self.keep_drafts()
        recommended = check.get("recommended")
        output = {"status": "completed", "phase": phase, "attempt": attempt, "verdict": verdict, "problems": len(check["problems"]),
                  "contact_sheet": check.get("contact_sheet"), "check_path": "homepage/concepts/check.json",
                  "axe_violations": sum(len(r.get("violations") or []) for r in (check.get("axe") or {}).values()),
                  "recommended": recommended["concept"] if recommended else None}
        if check.get("reused_draft_check"):
            output["reused_draft_check"] = check["reused_draft_check"]
        if phase == "draft":
            output["drafts"] = "homepage/concept-drafts"
        if "pairings_recorded" in check:
            output["pairings_recorded"] = check["pairings_recorded"]
        if verdict == "ok" and not self.bench:  # benchmark runs have no direction gate to ask
            output["questions"] = [{"id": "direction", "question": "Choose one concept (A, B or C) with decided_by (design; owner only for "
                                    "his own words), reasons and optional notes. The pick, the ones passed over and the notes are "
                                    "saved as a taste entry with who decided",
                                    "options": [f"{c['id']}: {c['name']}" for c in concepts]}]
        return self.receipt(key, fp, output)

    def keep_drafts(self) -> None:
        """Keep the drafts as checked (pages, fonts, renders, check) before refine overwrites them (queue #34)."""
        cdir, keep = self.concepts_dir, self.packet / "concept-drafts"
        if keep.exists():
            shutil.rmtree(keep)
        keep.mkdir(parents=True)
        for name in (*CONCEPT_IDS, "shots"):
            if (cdir / name).is_dir():
                shutil.copytree(cdir / name, keep / name)
        for name in ("concepts.json", "check.json", "sheet.html"):
            if (cdir / name).is_file():
                shutil.copyfile(cdir / name, keep / name)

    def pairings(self) -> dict:
        """homepage/PAIRINGS.md before the art director drafts: the type pairings already used (queue #34)."""
        brief = load(self.packet / "brief.json")
        brand_fonts = {f.lower() for f in brief.get("brand", {}).get("fonts", [])}
        recorded = recorded_pairings(pairing_log(self.root), self.root.name)
        (self.packet / "PAIRINGS.md").write_text(pairings_brief(recorded, brand_fonts))
        return {"status": "completed", "path": "homepage/PAIRINGS.md",
                "used_pairings": len({pairing_key(r["display"], r["text"]) for r in recorded})}

    def concepts_next(self) -> dict:
        """Loop control after the final concept check: report its verdict, change nothing.

        A separate node so that a failing check (browser down) fails the run instead of
        sending the art director round again (temper loops on a failed node too)."""
        path = self.concepts_dir / "check.json"
        if not path.exists():
            raise ValueError("no concept check to act on")
        check = load(path)
        if check.get("phase") != "final":
            raise ValueError("the last concept check was not the final one")
        return {"status": "completed", "verdict": check["verdict"], "attempt": check.get("attempt"),
                "problems": len(check.get("problems", []))}

    def contact_sheet(self, concepts: list[dict]) -> str:
        cdir = self.concepts_dir
        cols = []
        for c in concepts:
            pal = c.get("palette") or {}
            sw = "".join(f'<span style="background:{pal[k]}" title="{k} {pal[k]}"></span>' for k in ("dominant", "accent", "ink", "surface") if HEX.match(str(pal.get(k, ""))))
            fonts = c.get("fonts") or {}
            pair = " + ".join(str(fonts.get(r, {}).get("family", "?")) for r in ("display", "text"))
            cols.append(f'<section><h2>{c["id"]} — {_esc(c.get("name", ""))}</h2><p class="m">{_esc(pair)}</p><p class="sw">{sw}</p>'
                        f'<p>{_esc(c.get("signature_move", ""))}</p>'
                        + (f'<p class="h">\u201c{_esc(c["headline"])}\u201d</p>' if c.get("headline") else "")
                        + (f'<p class="t"><b>Your taste:</b> {_esc(c["taste_use"])}</p>' if c.get("taste_use") else "")
                        + f'<div class="shots"><img src="shots/{c["id"].lower()}-1440.png" class="d">'
                        f'<img src="shots/{c["id"].lower()}-390.png" class="p"></div></section>')
        html = ('<!doctype html><meta charset="utf-8"><title>Concepts</title><style>body{margin:0;padding:32px;background:#e9e7e2;'
                'font:16px/1.4 system-ui;color:#222}main{display:grid;grid-template-columns:repeat(3,1fr);gap:28px}h2{font-size:22px;margin:0 0 4px}'
                '.m{color:#555;margin:0 0 6px}.h{font-weight:700;margin:0 0 6px}.t{font-size:14px;color:#333;margin:0 0 10px}.sw span{display:inline-block;width:28px;height:28px;border-radius:4px;margin-right:4px;border:1px solid #0002}'
                '.shots{display:grid;grid-template-columns:3fr 1fr;gap:10px;align-items:start}img{width:100%;border:1px solid #0003}</style>'
                '<h1 style="margin:0 0 20px">Three directions — choose one</h1><main>' + "".join(cols) + "</main>")
        (cdir / "sheet.html").write_text(html)
        try:
            browser_jobs(cdir, cdir / "shots", [{"name": "contact-sheet", "path": "sheet.html", "width": 1800, "height": 1000, "maxHeight": 6000, "freeze": True}])
        except Exception as exc:  # noqa: BLE001 - the sheet is a convenience; the shots stay
            return f"homepage/concepts/sheet.html (png failed: {exc.__class__.__name__})"
        return "homepage/concepts/shots/contact-sheet.png"

    # -- direction gate

    def direction(self, raw: str) -> dict:
        if self.bench:
            if raw.strip():
                raise ValueError("the benchmark workflow has no direction gate: it builds the art director's recommended concept")
            spec_path = self.concepts_dir / "concepts.json"
            picked = recommendation(load(spec_path)) if spec_path.exists() else None
            if picked is None:
                raise ValueError("concepts.json has no valid recommended concept for the benchmark run")
            reason = "Art director's recommendation (benchmark run): " + picked["reason"]
            decision = {"concept": picked["concept"], "decided_by": "design", "benchmark": True,
                        "reasons": reason, "notes": reason}
        else:
            decision = gate_answer(raw, "direction", (FIXTURE_DECIDER,) if self.fixture else ("design",) if self.pilot
                                   else REAL_DECIDERS)
        check = load(self.concepts_dir / "check.json") if (self.concepts_dir / "check.json").exists() else {}
        if check.get("verdict") != "ok":
            raise ValueError("concepts have not passed the final check; no direction can be recorded")
        if decision.get("concept") not in CONCEPT_IDS:
            raise ValueError("direction needs concept A, B or C")
        if self.pilot and words(str(decision.get("reasons", ""))) < 8:
            raise ValueError("a provisional pick needs reasons: why this concept (8 words or more)")
        by = decision["decided_by"]
        flag = {"approved": not self.pilot and not self.bench, "decided_by": by}
        fp = digest(decision)
        cached = self.cached("direction", fp)
        if cached:
            return cached
        spec = load(self.concepts_dir / "concepts.json")
        chosen = next(c for c in spec["concepts"] if c["id"] == decision["concept"])
        site = self.site
        if site.exists():
            raise ValueError("site/ already exists before a direction was recorded; use a fresh workspace")
        site.mkdir(parents=True)
        cdir = self.concepts_dir / chosen["id"]
        if (cdir / "fonts").exists():
            shutil.copytree(cdir / "fonts", site / "fonts")
        if (self.packet / "assets").exists():
            shutil.copytree(self.packet / "assets", site / "images")
        save(self.packet / "direction.json", {**decision, "concept_name": chosen["name"], "saved_at": now(),
                                              "direction_approved": flag, "provisional": self.pilot or self.bench,
                                              "benchmark": self.bench})
        try:  # the picked pairing joins the record (a fixture run's too); the offered ones joined at the final check
            record_pairings(pairing_log(self.root), self.root.name, "chosen", [chosen])
        except OSError:
            pass
        self.record_taste("direction", {
            "gate": "direction", "choice": f"{chosen['id']}: {chosen['name']}", "choice_summary": describe_concept(chosen),
            "rejected": [{"option": f"{c['id']}: {c['name']}", "summary": describe_concept(c)}
                         for c in spec["concepts"] if c["id"] != chosen["id"]],
            "decided_by": by, "reasons": decision["reasons"], "words": decision.get("notes", "")})
        self.state["direction"] = {**decision, "concept_name": chosen["name"]}
        self.state["direction_approved"] = flag
        return self.receipt("direction", fp, {"status": "completed", "concept": chosen["id"], "concept_name": chosen["name"],
                                              "decided_by": by, "direction_approved": flag,
                                              "provisional": self.pilot or self.bench, "benchmark": self.bench})

    def build_fixture(self) -> dict:
        cid = self.state["direction"]["concept"]
        fp = digest({"concept": cid})
        cached = self.cached("build_fixture", fp)
        if cached:
            return cached
        shutil.copytree(self.concepts_dir / cid, self.site, dirs_exist_ok=True)
        return self.receipt("build_fixture", fp, {"status": "completed", "site": "homepage/site/index.html"})

    # -- review rounds

    def plan_round(self) -> dict:
        seq = self.state["decision_seq"]
        if self.state["planned_seq"] == seq and self.state.get("plan"):
            return {**self.state["plan"], "reused": True}
        if not (self.site / "index.html").exists():
            raise ValueError("homepage/site/index.html missing: the designer wrote nothing")
        if self.state["round"] == 0:
            plan = {"status": "completed", "round": 1, "action": "build"}
        else:
            if self.state.get("verdict") not in ("revise", *CHANGE_VERDICTS):
                raise ValueError("no revision was requested; refusing to start another round")
            number = self.state["round"] + 1
            fixes = self.state.get("fix_list", [])
            rdir = self.packet / "rounds" / f"r{number:02d}"
            save(rdir / "fix-list.json", {"round": number, "reason": self.state["verdict"], "fixes": fixes})
            (self.root / "review").mkdir(exist_ok=True)
            save(self.root / "review" / "fix-list.json", {"round": number, "reason": self.state["verdict"], "fixes": fixes})
            if self.state["verdict"] == "revise":
                self.state["revisions"] += 1
            else:
                self.state["change_rounds"] += 1
            plan = {"status": "completed", "round": number, "action": "revise", "fixes": len(fixes),
                    "fix_list": "review/fix-list.json"}
        self.state["round"] = plan["round"]
        self.state["planned_seq"] = seq
        self.state["plan"] = plan
        self.commit()
        return plan

    def revise_fixture(self) -> dict:
        number = self.state["round"]
        fp = digest({"round": number})
        cached = self.cached(f"revise_fixture-{number}", fp)
        if cached:
            return cached
        index = self.site / "index.html"
        text = index.read_text()
        text = text.replace("</title>", f" (fixture revision r{number:02d})</title>", 1)
        index.write_text(text)
        return self.receipt(f"revise_fixture-{number}", fp, {"status": "completed", "round": number, "changed": "title"})

    def measure(self) -> dict:
        number = self.state["round"]
        problems = html_problems(self.site / "index.html")
        for f in self.site.rglob("*.html"):
            problems += [p for p in html_problems(f) if "missing" not in p]
        if problems:
            raise ValueError("site breaks the page contract: " + "; ".join(sorted(set(problems))))
        fp = digest({"round": number, "site": tree_digest(self.site), "signature": 1})
        cached = self.cached(f"measure-{number}", fp)
        review = self.root / "review"
        if cached:
            if not (review / "facts.md").exists() or not (review / "signature.json").exists():
                raise ValueError("saved measurement artifacts missing; refusing a silent repeat")
            return cached
        if review.exists():
            keep = review / "fix-list.json"
            fix = keep.read_text() if keep.exists() else None
            shutil.rmtree(review)
            review.mkdir()
            if fix:
                keep.write_text(fix)
        brief = load(self.packet / "brief.json")
        direction = self.state.get("direction", {})
        spec = load(self.concepts_dir / "concepts.json")
        chosen = next((c for c in spec["concepts"] if c["id"] == direction.get("concept")), {})
        metrics = write_review_inputs(review, self.site, brief, number, chosen, direction.get("notes", ""),
                                      self.packet / "references" / "REFERENCES.md", page_checks=True)
        rdir = self.packet / "rounds" / f"r{number:02d}"
        save(rdir / "craft-metrics.json", metrics)
        # The concept's signature against the first screen; the reviser gets the numbers, the next round measures again.
        words = signature_words(chosen)
        before = self.packet / "rounds" / f"r{number - 1:02d}" / "signature.json"
        sig = judge_signature(measure_signature(self.site, words), chosen, words, load(before) if before.exists() else None)
        save(review / "signature.json", sig)
        (review / "signature.md").write_text(signature_md(sig, number))
        save(rdir / "signature.json", sig)
        # Keep the page as measured (with the reviser's REVISION.md): the next rounds compare with it.
        if (rdir / "site").exists():
            shutil.rmtree(rdir / "site")
        shutil.copytree(self.site, rdir / "site", ignore=shutil.ignore_patterns("fonts"))
        return self.receipt(f"measure-{number}", fp, {"status": "completed", "round": number, "facts_path": "review/facts.md",
                                                      "craft_facts": "review/craft-facts.md",
                                                      "scale_ratio_1440": metrics.get("1440", {}).get("scale_ratio"),
                                                      "signature": sig["status"], "signature_path": "review/signature.md",
                                                      "signature_px": {k: [s.get("visible_px"), s.get("needs_px")]
                                                                       for k, s in sig["screens"].items() if s.get("found")}})

    def runtime(self) -> dict:
        """Use the page for real: keyboard, focus, names, reflow, zoom, text spacing, motion, hover."""
        number = self.state["round"]
        review = self.root / "review"
        out = review / "runtime"
        # Kept text: the previous round's recording, and any earlier round whose lost words are still missing.
        prev, bases, base_rounds = None, [], []
        pdir = self.packet / "rounds" / f"r{number - 1:02d}"
        if number > 1 and (pdir / "review" / "runtime" / "raw.json").exists():
            prev = load(pdir / "review" / "runtime" / "raw.json")
            pkept = (load(pdir / "runtime.json") if (pdir / "runtime.json").exists() else {}).get("kept_text") or {}
            for b in pkept.get("base_rounds") or []:
                braw = self.packet / "rounds" / f"r{int(b):02d}" / "review" / "runtime" / "raw.json"
                if braw.exists():
                    bases.append(load(braw))
                    base_rounds.append(int(b))
        fp = digest({"round": number, "site": tree_digest(self.site), "prev": digest(prev) if prev else None, "bases": base_rounds})
        cached = self.cached(f"runtime-{number}", fp)
        if cached:
            if not (out / "runtime.json").exists() or not (review / "page-text.md").exists():
                raise ValueError("saved runtime results missing; refusing a silent repeat")
            return cached
        if f"measure-{number}" not in self.state["stages"]:
            raise ValueError(f"round {number} has not been measured yet")
        raw = rtc.measure(self.site, "index.html", BROWSER, SERVE_HOST)
        result = rtc.write_outputs(raw, out, prev, bases or None)
        if all(s["status"] == "not run" for s in result["checks"].values()):
            raise ValueError("runtime checks could not run: " + "; ".join(map(str, result.get("errors") or []))[:400])
        kept = result["kept_text"]
        kept["against_round"] = number - 1 if prev is not None else None
        kept["base_rounds"] = [b for b, st in zip(base_rounds, kept.get("vs_bases") or [], strict=False) if st == "fail"] \
            + ([number - 1] if kept.get("vs_previous") == "fail" else [])
        save(out / "runtime.json", result)
        shutil.copyfile(out / "page-text.md", review / "page-text.md")
        save(self.packet / "rounds" / f"r{number:02d}" / "runtime.json", result)
        return self.receipt(f"runtime-{number}", fp, {
            "status": "completed", "round": number, "failures": result["failures"], "findings": len(result["findings"]),
            "kept_text": kept["status"],
            "checks": {c: s["status"] for c, s in result["checks"].items()}, "errors": len(result.get("errors") or []),
            "runtime_path": "review/runtime/RUNTIME.md", "page_text": "review/page-text.md"})

    def content_fixture(self) -> dict:
        """Stand-in content review of the page: one finding quoting the real page text, one that cannot be found."""
        number = self.state["round"]
        review = self.root / "review"
        text = (review / "page-text.md").read_text() if (review / "page-text.md").exists() else ""
        line = next((m.group(1).strip() for m in re.finditer(r"^- \[h[1-3]\] (.+)$", text, re.M)), "")
        if not line:
            raise ValueError("review/page-text.md has no heading to quote; run the runtime stage first")
        fp = digest({"round": number, "line": line})
        cached = self.cached(f"content_fixture-{number}", fp)
        if cached:
            return cached
        save(review / "content" / "content.json", {"target": "page", "fixture": True, "summary": "Fixture content review (no model).", "findings": [
            {"id": "K1", "check": "clarity", "element": "first heading", "quote": line, "problem": "fixture finding on real page text",
             "suggestion": "fixture fix", "severity": 2},
            {"id": "K2", "check": "drift", "element": "nowhere", "quote": "words that are not on this page",
             "problem": "fixture finding whose quote is not on the page: combine must drop it", "suggestion": "none", "severity": 3}]})
        return self.receipt(f"content_fixture-{number}", fp, {"status": "completed", "round": number, "quoted": line[:80]})

    def review_fixture(self) -> dict:
        number = self.state["round"]
        fp = digest({"round": number})
        cached = self.cached(f"review_fixture-{number}", fp)
        if cached:
            return cached
        review = self.root / "review"
        sev = 3 if number == 1 else 1
        save(review / "findings.json", {"fixture": True, "findings": [
            {"id": "D1", "status": "confirmed", "page": "index.html", "viewport": "desktop", "element": "page title",
             "problem": "fixture finding", "evidence": "fixture", "severity": sev, "suggestion": "fixture fix"}]})
        (review / "report.md").write_text(f"# Fixture review round {number}\n\nStand-in merged findings (no model).\n")
        save(review / "craft" / "craft.json", {"critic": "craft", "fixture": True, "findings": [], "template_test": {"verdict": "fixture"}})
        return self.receipt(f"review_fixture-{number}", fp, {"status": "completed", "round": number, "severity": sev})

    def chosen_concept(self) -> dict:
        direction = self.state.get("direction") or {}
        path = self.concepts_dir / "concepts.json"
        spec = load(path) if path.exists() else {}
        return next((c for c in spec.get("concepts") or [] if isinstance(c, dict) and c.get("id") == direction.get("concept")), {})

    def round_history(self, number: int) -> dict[int, dict]:
        """Earlier rounds: what the reviser was asked to fix, every verified content finding, and the reviser's answers."""
        history: dict[int, dict] = {}
        for k in range(1, number):
            rdir = self.packet / "rounds" / f"r{k:02d}"
            asked = load(rdir / "decision.json").get("fixes", []) if (rdir / "decision.json").exists() else []
            saved = load_round(rdir / "review")
            found = round_items(*saved, self.fixture) if saved else {"blocking": [], "minor": []}
            content = [i for i in found["blocking"] + found["minor"] if i["source"] == "content"]
            answer_file = self.packet / "rounds" / f"r{k + 1:02d}" / "site" / "REVISION.md"
            if not answer_file.exists() and k + 1 == number:
                answer_file = self.site / "REVISION.md"
            history[k] = {"asked": [i for i in asked if isinstance(i, dict)], "content": content, "answers": revision_answers(answer_file)}
        return history

    @staticmethod
    def mark_repeat(item: dict, earlier: list, history: dict, number: int, can_revise: bool, action: str) -> None:
        seen = sorted({k for k, _ in earlier} | {number})
        item["repeat"] = {"seen_in": seen, "earlier": [
            {"round": k, "source": e.get("source"), "id": e.get("id"), "problem": str(e.get("problem"))[:200],
             "answer": history[k]["answers"].get(str(e.get("id")))} for k, e in earlier][:6]}
        if not can_revise:
            item["action"] = "no revision left"
            return
        item["action"] = action
        rounds = ", ".join(str(k) for k in seen[:-1])
        before = item.get("suggestion") or ""
        if action == "redesign":
            where = f"the {item['section']} section" if item.get("section") else "the section it sits in"
            item["suggestion"] = (f"REDESIGN, not a tweak: raised in round {rounds} too, and the last revision did not remove it. Rework "
                                  f"{where} (its order, sizes and what comes first) so the problem cannot come back, keeping the "
                                  f"direction's signature, its words and the strengths to keep. {before}").strip()
        elif action == "rewrite":
            item["suggestion"] = (f"REWRITE, not a tweak: raised in round {rounds} too, and the last revision did not remove it. "
                                  f"Rewrite the words named from the reviewed deck so the problem cannot come back. {before}").strip()
        else:
            item["suggestion"] = (f"RAISED BEFORE in round {rounds}: fix it this time, or say in REVISION.md why these words stay "
                                  f"(for example: they are the reviewed deck's words). {before}").strip()

    def combine(self) -> dict:
        number = self.state["round"]
        review = self.root / "review"
        merged = load(review / "findings.json")
        craft_files = sorted((review / "craft").glob("*.json"))
        if not craft_files:
            raise ValueError("no craft review in review/craft/")
        craft = [load(f) for f in craft_files]
        for need in ("runtime/runtime.json", "content/content.json", "page-text.md"):
            if not (review / need).exists():
                raise ValueError(f"review/{need} missing: the runtime checks and the content review run before combine")
        runtime = load(review / "runtime" / "runtime.json")
        content = load(review / "content" / "content.json")
        page_text = (review / "page-text.md").read_text()
        sig = load(review / "signature.json") if (review / "signature.json").exists() else None
        fp = digest({"round": number, "merged": merged, "craft": craft, "runtime": runtime, "content": content, "text": page_text,
                     "signature": sig, "rules": 2})
        cached = self.cached(f"combine-{number}", fp)
        if cached:
            return cached
        items = round_items(merged, craft, runtime, content, page_text, sig, self.fixture)
        blocking, minor, kept, dropped, template = (items[k] for k in ("blocking", "minor", "kept", "dropped", "template"))
        can_revise = self.state["revisions"] < MAX_AUTO_REVISIONS
        history = self.round_history(number)
        sig_words = _bag(" ".join(signature_words(self.chosen_concept())))
        # A blocker the reviser was already asked to fix: that section goes back for a redesign, not a tweak.
        for item in blocking:
            earlier = [(k, e) for k, h in history.items() for e in h["asked"] if same_problem(item, e, sig_words)]
            if earlier:
                self.mark_repeat(item, earlier, history, number, can_revise, "rewrite" if item["source"] == "content" else "redesign")
        # A content finding raised before (fixed or not): it joins the fix list, past the cap on minor items.
        repeats = []
        for item in minor:
            if item["source"] != "content":
                continue
            earlier = [(k, e) for k, h in history.items() for e in h["content"] if same_problem(item, e, sig_words)]
            if earlier:
                self.mark_repeat(item, earlier, history, number, can_revise, "fix or explain")
                repeats.append(item)
        rest = [i for i in minor if i not in repeats]
        verdict = "revise" if blocking and can_revise else "done"
        fixes = blocking + repeats + sorted(rest, key=lambda x: -(x["severity"] or 0))[:6]
        rdir = self.packet / "rounds" / f"r{number:02d}"
        if rdir.joinpath("review").exists():
            shutil.rmtree(rdir / "review")
        shutil.copytree(review, rdir / "review")
        kept_text = runtime.get("kept_text") or {}
        summary = {"round": number, "verdict": verdict, "blocking": len(blocking), "minor": len(minor),
                   "unresolved_blocking": [] if verdict == "revise" else blocking,
                   "template_test": template, "revisions_done": self.state["revisions"], "decided_at": now(),
                   "by_source": {s: sum(1 for i in blocking + minor if i["source"] == s)
                                 for s in ("usability", "craft", "runtime", "content", "measure")},
                   "runtime_checks": {c: s.get("status") for c, s in runtime.get("checks", {}).items()},
                   "runtime_errors": runtime.get("errors") or [],
                   "content_verified": len(kept), "content_dropped": [{k: f.get(k) for k in ("id", "quote", "dropped")} for f in dropped],
                   "blockers": [{"source": i["source"], "id": i["id"], "severity": i["severity"], "problem": str(i.get("problem"))[:200],
                                 "seen_in": (i.get("repeat") or {}).get("seen_in", [number]), "action": i.get("action", "fix")}
                                for i in blocking],
                   "content_repeats": [{"id": i["id"], "seen_in": i["repeat"]["seen_in"], "quote": i.get("quote")} for i in repeats],
                   "signature": {"status": sig["status"], "name": sig.get("name"),
                                 "screens": {k: [s.get("visible_px"), s.get("needs_px")] for k, s in sig["screens"].items() if s.get("found")}}
                   if sig else None,
                   "kept_text": {"status": kept_text.get("status"), "against_round": kept_text.get("against_round"),
                                 "base_rounds": kept_text.get("base_rounds") or [],
                                 "lost": {w: v.get("lost") for w, v in (kept_text.get("viewports") or {}).items() if v.get("lost")}}
                   if kept_text else None}
        save(rdir / "decision.json", {**summary, "fixes": fixes})
        self.state["verdict"] = verdict
        self.state["fix_list"] = fixes
        self.state["decision_seq"] += 1
        self.state["last_round"] = summary
        return self.receipt(f"combine-{number}", fp, {"status": "completed", **{k: summary[k] for k in ("round", "verdict", "blocking", "minor", "by_source")},
                                                      "unresolved_blocking": len(summary["unresolved_blocking"]),
                                                      "content_dropped": len(summary["content_dropped"])})

    def next_round(self) -> dict:
        return {"status": "completed", "verdict": self.state.get("verdict"), "round": self.state["round"]}

    # -- Penpot

    def convert(self) -> dict:
        number = self.state["round"]
        out = self.packet / "penpot" / f"r{number:02d}"
        fp = digest({"round": number, "site": tree_digest(self.site)})
        cached = self.cached(f"convert-{number}", fp)
        if cached:
            if not (out / "conversion.json").exists():
                raise ValueError("saved conversion report missing; refusing a silent repeat")
            return cached
        if (out / "pending.json").exists():
            raise ValueError(f"an earlier conversion of round {number} stopped part-way ({out / 'pending.json'}); inspect that Penpot file before retrying, never duplicate it")
        if out.exists():
            shutil.rmtree(out)
        brief = load(self.packet / "brief.json")
        name = f"{brief['product']} — homepage v2 r{number:02d}" + (" (fixture)" if self.fixture else " (benchmark)" if self.bench else "")
        report = h2p.convert(self.site, "index.html", out, name, browser=BROWSER, serve_host=SERVE_HOST,
                             label=brief["product"])
        summary = {"status": "completed", "round": number, "passed": report["passed"], "file_id": report["file"]["file_id"],
                   "url": report["file"]["url"], "fidelity_passed": report["fidelity_passed"],
                   "verify_passed": report["verify"]["passed"], "issues": report["issue_counts"],
                   "conversion": f"homepage/penpot/r{number:02d}/conversion.json"}
        return self.receipt(f"convert-{number}", fp, summary)

    def verify(self) -> dict:
        number = self.state["round"]
        out = self.packet / "penpot" / f"r{number:02d}"
        report = load(out / "conversion.json")
        client = h2p.penpot_client()
        client.login()
        fresh = client.get(report["file"]["file_id"])
        objects = fresh["data"]["pages-index"][report["file"]["page_id"]]["objects"]
        checks = {
            "conversion_verified": report["verify"]["passed"],
            "fidelity_within_bar": report["fidelity_passed"],
            "unchanged_since_conversion": fresh.get("revn") == report["file"]["revn"],
            "boards_present": all(b["id"] in objects and round(objects[b["id"]]["width"]) == b["width"] for b in report["boards"]),
            "component_mains_present": all(c["root"] in objects for c in report["components"]),
            "text_layers": sum(1 for o in objects.values() if o.get("type") == "text") > 0,
            "exports_saved": all((out / f"penpot-{w}.{k}").exists() for w in report["widths"] for k in ("png", "svg")),
        }
        fidelity = {w: {k: f.get(k) for k in ("overall_pct", "nontext_pct", "text_pct", "tile_max_pct", "tile_mean_max")}
                    for w, f in report["fidelity"].items()}
        result = {"round": number, "checked_at": now(), "checks": checks, "passed": all(checks.values()),
                  "fidelity": fidelity, "fidelity_bar": report["fidelity_bar"], "issues": report["issue_counts"]}
        save(out / "verify.json", result)
        if not result["passed"]:
            raise ValueError("Penpot check failed: " + ", ".join(k for k, v in checks.items() if not v)
                             + f" (see homepage/penpot/r{number:02d}/verify.json and conversion.json)")
        self.state["verified_round"] = number
        self.commit()
        return {"status": "completed", "round": number, "passed": True, "fidelity": fidelity}

    # -- handoff and the final gate

    def handoff(self) -> dict:
        number = self.state["round"]
        if self.state.get("verified_round") != number:
            raise ValueError("this round's Penpot file has not passed verify")
        conv = load(self.packet / "penpot" / f"r{number:02d}" / "conversion.json")
        fp = digest({"round": number, "file": conv["file"]["file_id"], "site": tree_digest(self.site)})
        cached = self.cached(f"handoff-{number}", fp)
        if cached:
            return cached
        dest = self.packet / "packet" / f"r{number:02d}"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.site, dest / "site")
        pen = dest / "penpot"
        pen.mkdir(parents=True)
        src = self.packet / "penpot" / f"r{number:02d}"
        for f in sorted(src.iterdir()):
            if f.suffix in (".png", ".svg") or f.name in ("conversion.json", "verify.json"):
                shutil.copyfile(f, pen / f.name)
        for f in ("BRIEF.md", "brief.json", "direction.json"):
            if (self.packet / f).exists():
                shutil.copyfile(self.packet / f, dest / f)
        shutil.copytree(self.concepts_dir, dest / "concepts", ignore=shutil.ignore_patterns("fonts"))
        if (self.packet / "rounds").exists():
            shutil.copytree(self.packet / "rounds", dest / "rounds")
        if (self.packet / "references" / "REFERENCES.md").exists():
            shutil.copyfile(self.packet / "references" / "REFERENCES.md", dest / "REFERENCES.md")
        if self.copy_dir.exists():  # the words; the taste notes stay out of the packet
            shutil.copytree(self.copy_dir, dest / "copy")
        brief = load(self.packet / "brief.json")
        last = self.state.get("last_round", {})
        fonts = conv.get("fonts", [])
        lines = [f"# Homepage handoff — {brief['product']} (round {number})", "",
                 f"Direction: {self.state['direction']['concept']} — {self.state['direction']['concept_name']}"
                 + (" (fixture-test answer, not an approval by anyone)" if self.fixture
                    else " (provisional fictional pick by the worker, not a direction approval)" if self.pilot
                    else " (the art director's recommended concept; benchmark run, no direction gate)" if self.bench
                    else f" (direction gate, decided by {gate_decided_by(self.state['direction'])})"),
                 f"Editable master: Penpot file {conv['file']['name']} — {conv['file']['url']}",
                 f"Boards: {', '.join(b['name'] for b in conv['boards'])}; components {len(conv['components'])}, instances {len(conv['instances'])},"
                 f" shared colours {len(conv['colors'])}, typographies {len(conv['typographies'])}.",
                 "", "## Fidelity (Penpot export vs browser render, % of pixels differing)"]
        for w, f in conv["fidelity"].items():
            lines.append(f"- {w}: overall {f.get('overall_pct')}%, non-text {f.get('nontext_pct')}%, text {f.get('text_pct')}%, worst tile {f.get('tile_max_pct')}% — {'pass' if f.get('passed') else 'FAIL'}")
        lines += ["", "## Review", f"Rounds: {number}; automatic revisions {self.state['revisions']}, final-gate change rounds {self.state['change_rounds']}.",
                  f"Last round: {last.get('blocking', 0)} blocking, {last.get('minor', 0)} minor; unresolved blocking: {len(last.get('unresolved_blocking', []))}."]
        for item in last.get("unresolved_blocking", []):
            rep = item.get("repeat") or {}
            lines.append(f"- UNRESOLVED {item.get('source')} {item.get('id')}: {item.get('problem')} ({item.get('element')})"
                         + (f"; raised in rounds {', '.join(map(str, rep.get('seen_in', [])))}, earlier answers: "
                            + " | ".join(f"r{e.get('round')} {e.get('id')}: {e.get('answer') or 'no answer recorded'}" for e in rep.get("earlier", []))
                            if rep else ""))
        for t in last.get("template_test", []):
            lines.append(f"- Craft critic 'could this be a template?': {t.get('verdict')} — {t.get('evidence', '')}")
        lines += ["", "## Round by round (blockers, repeats, the signature, kept text)"] + round_by_round(self.packet / "rounds", number)
        deck = self.deck() or {}
        copy_check = load(self.copy_dir / "check.json") if (self.copy_dir / "check.json").exists() else {}
        lines += ["", "## Words",
                  f"Copy deck: copy/COPY.md; before/after the content review: copy/COPY-DIFF.md ({copy_check.get('verified_findings', 0)} findings checked,"
                  f" {copy_check.get('dropped_findings', 0)} dropped, {copy_check.get('changed_fields', 0)} fields changed)."]
        lines += [f"- Notice '{n.get('id')}' ({n.get('placement')}, shown once): {n.get('text')}" for n in deck.get("notices") or [] if isinstance(n, dict)]
        lines.append(f"- Content review of the built page, last round: {last.get('content_verified', 0)} findings checked against the page text,"
                     f" {len(last.get('content_dropped', []))} dropped (quote not on the page).")
        checks = last.get("runtime_checks", {})
        lines += ["", "## Runtime checks (real browser, fixed rules, no model; last round)",
                  ", ".join(f"{c} {s}" for c, s in checks.items()) or "not run"]
        lines += [f"- Could not check: {e}" for e in last.get("runtime_errors", [])]
        lines += ["", "## Fonts (licences travel with the files)"]
        lines += [f"- {f.get('family')} {f.get('weight')} {f.get('style')}: {f.get('licence', {}).get('file') if isinstance(f.get('licence'), dict) else f.get('licence')}" for f in fonts]
        lines += ["", "## Converter notes (approximations, never silent)"]
        lines += [f"- {k}: {v}" for k, v in sorted(conv["issue_counts"].items())] or ["- none"]
        lines += ["", "## Not checked here", "- Real screen-reader, voice and switch use (the runtime checks cover Tab order, focus, names, reflow,",
                  "  400% zoom, text spacing, reduced motion and hover), motion as designed (renders use reduced motion),",
                  "  real content beyond the brief's facts, publication. AI review is advisory; the final gate decides,",
                  "  and the owner's own words outrank every other answer.",
                  "", "Final approval: " + ("not applicable (fixture; its gates are answered fixture-test)." if self.fixture else
                                         "none: not approved (benchmark run; the final gate is skipped and benchmark "
                                         "pages are judged blind on the scoreboard)." if self.bench else
                                         "pending the final gate.")]
        (dest / "HANDOFF.md").write_text("\n".join(lines) + "\n")
        manifest = {"round": number, "created_at": now(), "files": {}}
        for f in sorted(dest.rglob("*")):
            if f.is_file():
                manifest["files"][str(f.relative_to(dest))] = hashlib.sha256(f.read_bytes()).hexdigest()
        save(dest / "manifest.json", manifest)
        rel = f"homepage/packet/r{number:02d}"
        output = {"status": "completed", "round": number, "handoff_path": f"{rel}/HANDOFF.md", "manifest_path": f"{rel}/manifest.json",
                  "penpot_url": conv["file"]["url"], "files": len(manifest["files"])}
        if not self.bench:  # benchmark runs have no final gate to ask
            output["questions"] = [{"id": "final", "question": "Approve this homepage, or request changes with notes; give "
                                    "decided_by (design; owner only for his own words) and reasons",
                                    "options": ["approve", "request changes"]}]
        return self.receipt(f"handoff-{number}", fp, output)

    def final(self, raw: str) -> dict:
        number = self.state["round"]
        if self.bench:
            if raw.strip():
                raise ValueError("the benchmark workflow has no final gate; benchmark pages are judged blind on the scoreboard")
            if f"handoff-{number}" not in self.state["stages"]:
                raise ValueError(f"round {number} has no verified handoff to decide on")
            label = "not approved: benchmark run, the final gate is skipped"
            flag = {"approved": False, "decided_by": None}
            save(self.packet / "final-benchmark.json", {"round": number, "verdict": "benchmark_skipped", "final_approved": flag,
                                                       "label": label, "recorded_at": now()})
            self.state["final_approved"] = flag
            self.commit()
            return {"status": "completed", "round": number, "verdict": "benchmark_skipped",
                    "direction_approved": self.state["direction_approved"], "final_approved": flag, "label": label}
        decision = gate_answer(raw, "final", (FIXTURE_DECIDER,) if self.fixture else REAL_DECIDERS)
        if f"handoff-{number}" not in self.state["stages"]:
            raise ValueError(f"round {number} has no verified handoff to decide on")
        by = decision["decided_by"]
        if decision.get("verdict") == "request_changes":
            notes = decision.get("notes")
            if not isinstance(notes, list) or not notes or not all(isinstance(n, str) and n.strip() for n in notes):
                raise ValueError("request_changes needs notes: a list of concrete changes")
            if self.state["change_rounds"] >= MAX_CHANGE_ROUNDS:
                raise ValueError("two final-gate change rounds used; start a new run for further work")
            key = f"final-{number}"
            fp = digest(decision)
            cached = self.cached(key, fp)
            if cached:
                return cached
            save(self.packet / f"final-r{number:02d}.json", {**decision, "recorded_at": now()})
            self.record_taste(f"final-r{number:02d}", {"gate": "final", "round": number, "about": self.final_about(),
                                                        "choice": "request changes", "rejected": [{"option": "approve as it is"}],
                                                        "decided_by": by, "reasons": decision["reasons"], "words": notes})
            self.state["verdict"] = "gate_changes"
            self.state["fix_list"] = [{"source": GATE_FIX_SOURCE, "id": f"G{i}", "severity": 4, "problem": n, "decided_by": by}
                                      for i, n in enumerate(notes, 1)]
            self.state["decision_seq"] += 1
            return self.receipt(key, fp, {"status": "completed", "round": number, "verdict": "request_changes", "decided_by": by,
                                          "direction_approved": self.state["direction_approved"],
                                          "final_approved": {"approved": False, "decided_by": by}})
        if decision.get("verdict") != "approve":
            raise ValueError("the final gate needs verdict approve or request_changes")
        flag = {"approved": True, "decided_by": by}
        save(self.packet / "final.json", {**decision, "round": number, "recorded_at": now(), "final_approved": flag})
        self.record_taste(f"final-r{number:02d}", {"gate": "final", "round": number, "about": self.final_about(),
                                                    "choice": "approve", "rejected": [{"option": "request changes"}],
                                                    "decided_by": by, "reasons": decision["reasons"],
                                                    "words": decision.get("notes") or decision.get("comment") or ""})
        self.state["final_approved"] = flag
        self.commit()
        return {"status": "completed", "round": number, "verdict": "approved", "decided_by": by,
                "direction_approved": self.state["direction_approved"], "final_approved": flag}


    def final_about(self) -> str:
        d = self.state.get("direction", {})
        return f"the built homepage, direction {d.get('concept', '?')}: {d.get('concept_name', '?')}, round {self.state['round']}"


def _esc(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


STAGES = ("brief", "taste", "copy_fixture", "copy_check", "copy_next", "references", "pairings", "concepts_fixture", "concepts_check",
          "concepts_next", "direction", "build_fixture", "plan_round", "revise_fixture", "measure", "runtime", "review_fixture",
          "content_fixture", "combine", "next_round", "convert", "verify", "handoff", "final")
FIXTURE_ONLY = {"copy_fixture", "concepts_fixture", "build_fixture", "revise_fixture", "review_fixture", "content_fixture"}


def main() -> None:
    global BROWSER, SERVE_HOST
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--pilot", action="store_true", help="fictional trial: provisional direction, never an approval")
    parser.add_argument("--bench", action="store_true",
                        help="benchmark run: fictional brief, the art director's recommended concept, no gates")
    parser.add_argument("--phase", default="draft")
    parser.add_argument("--browser", default=None)
    parser.add_argument("--serve-host", default=None)
    args = parser.parse_args()
    BROWSER = args.browser or BROWSER
    SERVE_HOST = args.serve_host or SERVE_HOST
    if args.stage in FIXTURE_ONLY and not args.fixture:
        raise SystemExit(f"{args.stage} is a fixture-only stage")
    try:
        job = Job(args.workspace, args.fixture, args.pilot, args.bench)
    except ValueError as exc:
        raise SystemExit(f"{args.stage}: {exc}") from None
    raw = os.environ.get("HOMEPAGE_DATA", "")
    methods = {
        "brief": lambda: job.brief(raw), "references": lambda: job.references(raw), "taste": lambda: job.taste(raw),
        "copy_fixture": lambda: job.copy_fixture(args.phase), "copy_check": lambda: job.copy_check(args.phase),
        "copy_next": job.copy_next, "runtime": job.runtime, "content_fixture": job.content_fixture,
        "pairings": job.pairings, "concepts_fixture": job.concepts_fixture, "concepts_check": lambda: job.concepts_check(args.phase),
        "concepts_next": job.concepts_next,
        "direction": lambda: job.direction(raw), "build_fixture": job.build_fixture, "plan_round": job.plan_round,
        "revise_fixture": job.revise_fixture, "measure": job.measure, "review_fixture": job.review_fixture,
        "combine": job.combine, "next_round": job.next_round, "convert": job.convert, "verify": job.verify,
        "handoff": job.handoff, "final": lambda: job.final(raw)}
    started = time.monotonic()
    try:
        result = methods[args.stage]()
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        # Our own messages; never raw HTTP bodies, environment or session data.
        raise SystemExit(f"{args.stage}: {exc}") from None
    result["seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
