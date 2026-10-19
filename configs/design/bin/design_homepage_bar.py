#!/usr/bin/env python3
"""design_homepage_bar (Design, queues #78 and #91): the homepage A-bar meter, version 2. No model (AGENTS rule 17).

Measures one built homepage against the script-measurable A bars of
~/design-lab/homepage-workflow/BAR.md at 1440x900, 1024x768, 768x1024, 390x844 and 320x568, and
writes bars.json and bars.md (one row per bar, check and width). Every definition is in
docs/design-homepage-bar.md; limits are BAR.md's, word for word.

    design_homepage_bar.py --site DIR [--page index.html] --brief brief.json --out DIR \
        [--browser URL] [--serve-host HOST] [--raw-only | --from-raw DIR]
    design_homepage_bar.py --fixture-proof --out DIR [--record] [--browser URL] [--serve-host HOST]

The browser is temper's playwright-mcp service. The site folder is served over HTTP by
design_capture.serve. In the page: design_homepage_bar.js (raw measurements), design_measure.js
(text contrast, WCAG 2.5.8 targets), axe-core with design_capture's AXE_TAGS, and design_page_checks
(text over an image, measured from the pixels behind it). The scorer (score) is pure: raw JSON in,
rows out; every limit is applied there. Version 2 (queue #91, H3b) reads six of BAR.md's definitions
more exactly and adds two rows (A5 cta-wording, A7 word-split); the doc's v2 section lists each change.
"""

import argparse
import asyncio
import hashlib
import json
import pathlib
import re
import statistics
import sys
import urllib.parse
from decimal import Decimal, InvalidOperation

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

METER = "design_homepage_bar"
VERSION = 2
REPO = HERE.parent.parent.parent
JS = HERE / "design_homepage_bar.js"
FIXTURES = HERE.parent / "testpages" / "bar-v1"
FIXTURES_V2 = HERE.parent / "testpages" / "bar-v2"
VERBS = FIXTURES / "verbs.txt"
PLACEHOLDERS = FIXTURES / "placeholders.txt"
SIZES = [(1440, 900), (1024, 768), (768, 1024), (390, 844), (320, 568)]
WIDTHS = [f"{w}x{h}" for w, h in SIZES]
FIRST = ["1440x900", "390x844"]
MIN_WORDS = 8

# (bar, check, widths, limit). widths: "5" every width, "2" 1440 and 390, "1440", "all".
# The limit strings are BAR.md's words (docs/design-homepage-bar.md, the limit column).
CHECKS = [
    ("A1", "product-name", "2", "product name in the first viewport"),
    ("A1", "h1-words", "2", "12 words or fewer"),
    ("A1", "cta-in-view", "2", "one fully visible primary call to action"),
    ("A1", "visual-anchor", "2", "at least one visual anchor"),
    ("A2", "one-h1", "2", "exactly 1"),
    ("A2", "h1-largest", "2", "H1 is the largest text on the first screen"),
    ("A2", "primary-per-window", "5", "1 or fewer per viewport"),
    ("A2", "font-sizes", "5", "7 or fewer"),
    ("A2", "section-sizes", "5", "4 or fewer per section"),
    ("A2", "section-colours", "5", "3 or fewer per section"),
    ("A2", "spacing-grid", "5", "90% or more"),
    ("A2", "rhythm", "2", "at least 2x the median gap inside a section"),
    ("A3", "body-size", "5", "16 px or more"),
    ("A3", "line-height", "5", "1.2 to 1.5"),
    ("A3", "measure", "1440", "90% or more"),
    ("A3", "fk-grade", "1440", "grade 9 or below"),
    ("A4", "axe", "2", "0 violations"),
    ("A4", "text-contrast", "5", "every text node meets 4.5:1 (3:1 large), including over images"),
    ("A4", "targets", "5", "24x24 or spaced (2.5.8)"),
    ("A4", "no-hscroll", "5", "no horizontal scroll at any width"),
    ("A4", "headings", "2", "one h1, no skipped heading levels"),
    ("A4", "landmarks", "2", "landmarks"),
    ("A4", "lang", "2", "lang set"),
    ("A4", "img-alt", "2", "every meaningful image has alt"),
    ("A4", "svg-names", "2", "every decorative one is hidden"),
    ("A5", "cta-length", "all", "40 characters or fewer"),
    ("A5", "cta-verb", "all", "starting with a verb"),
    ("A5", "disclosure", "all", "fictional products carry the disclosure line"),
    ("A5", "placeholders", "all", "no placeholder text"),
    ("A5", "numbers", "all", "0 unsourced claims"),
    ("A5", "cta-wording", "all", "the brief's call to action, normalised"),
    ("A7", "overlap", "5", "no text box overlaps another"),
    ("A7", "clipped", "5", "no clipped text"),
    ("A7", "word-split", "5", "no word split across two lines without a hyphen"),
]
# The rows version 2 added (queue #91). bar-v1/expected.json predates them; bar-v2/expected.json keys them
# for bar-v1's pages (its "bar-v1" section).
ADDED = {("A5", "cta-wording"), ("A7", "word-split")}


def widths_of(spec: str) -> list[str]:
    return {"5": WIDTHS, "2": FIRST, "1440": ["1440x900"], "all": ["all"]}[spec]


# ---------------------------------------------------------------- small pure helpers (unit-tested)

def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def syllables(word: str) -> int:
    """The built-in syllable rule (docs/design-homepage-bar.md, A3 fk-grade)."""
    w = "".join(ch for ch in word.lower() if ch.isalpha())
    if not w or len(w) <= 3:
        return 1
    vowels = "aeiouy"
    if w.endswith(("es", "ed")):
        w = w[:-2]
    elif w.endswith("e") and not w.endswith(("ee", "ye")) and not (w.endswith("le") and len(w) >= 3 and w[-3] not in vowels):
        w = w[:-1]
    return max(1, len(re.findall(r"[aeiouy]+", w)))


def words_of(text: str) -> list[str]:
    """Runs of letters, digits and apostrophes holding a letter or digit."""
    return [w for w in re.findall(r"[\w'\u2019]+", text or "") if re.search(r"[^\W_]", w)]


def sentences_of(text: str) -> int:
    """Sentence ends in one element's text: . ! or ? before a space or the end; the element ends one."""
    t = norm(text)
    if not t:
        return 0
    n = len(re.findall(r"[.!?](?=\s|$)", t))
    return n if re.search(r"[.!?]$", t) else n + 1


def fk_grade(texts: list[str]) -> float | None:
    """Flesch-Kincaid grade of the joined texts (each text ends a sentence), or None without words."""
    words = [w for t in texts for w in words_of(t)]
    sents = sum(sentences_of(t) for t in texts if words_of(t))
    if not words or not sents:
        return None
    syll = sum(syllables(w) for w in words)
    return 0.39 * len(words) / sents + 11.8 * syll / len(words) - 15.59


def load_verbs(path: pathlib.Path = VERBS) -> set[str]:
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line.lower())
    return out


def load_patterns(path: pathlib.Path = PLACEHOLDERS) -> list[re.Pattern]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            out.append(re.compile(line.rstrip("\n")))
    return out


def cta_verb_ok(text: str, verbs: set[str]) -> bool:
    first = norm(text).split(" ")[0] if norm(text) else ""
    word = "".join(ch for ch in first.lower() if ch.isalpha())
    return bool(word) and word in verbs


NUM_RE = re.compile(r"(?<![\w.,])([$£€]?)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")
YEAR_RE = re.compile(r"(?<![\w.,$£€])(19|20)\d\d(?![\w%×])")


def number_tokens(text: str) -> list[tuple[str, str, str, str]]:
    """Number tokens as (shown, currency, number, suffix); number without commas, normalised."""
    out = []
    for m in NUM_RE.finditer(text or ""):
        cur, whole, dec = m.group(1), m.group(2), m.group(3)
        end = m.end()
        suffix = ""
        if end < len(text) and text[end] in "%x×k":
            after = text[end + 1] if end + 1 < len(text) else ""
            if not after.isalpha():
                suffix = text[end]
                end += 1
        raw = whole.replace(",", "") + ("." + dec if dec else "")
        try:
            num = str(Decimal(raw).normalize())
        except InvalidOperation:
            num = raw
        if "E" in num:
            num = str(int(Decimal(raw)))
        out.append((text[m.start():end], cur, num, suffix))
    return out


UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
NUMBER_WORDS = {w: i for i, w in enumerate(UNITS)} | TENS
WORD_NUM_RE = re.compile(r"(?<![A-Za-z])([A-Za-z]+)(?:-([A-Za-z]+))?(?![A-Za-z])")


def number_words(text: str) -> list[int]:
    """v2 (queue #91): the numbers a text writes as words: zero to nineteen, the tens, and hyphened compounds
    such as twenty-one; 'one-hour' gives 1 and 'ten-year' 10."""
    out = []
    for m in WORD_NUM_RE.finditer(text or ""):
        a, b = m.group(1).lower(), (m.group(2) or "").lower()
        if a in TENS and 1 <= NUMBER_WORDS.get(b, 0) <= 9:
            out.append(TENS[a] + NUMBER_WORDS[b])
            continue
        out += [NUMBER_WORDS[x] for x in (a, b) if x in NUMBER_WORDS]
    return out


def fact_token_list(facts: list[str]) -> list[tuple[str, str, str, str]]:
    """Every number the brief's facts hold, fact by fact: its numerals, then (v2) its number words as plain
    numbers, so a page that restates 'seven days' as '7 days' is sourced."""
    out = []
    for f in facts:
        out += number_tokens(f)
        out += [(str(v), "", str(v), "") for v in number_words(f)]
    return out


def fact_tokens(facts: list[str]) -> list[tuple[str, str, str]]:
    return [(c, n, s) for _, c, n, s in fact_token_list(facts)]


def is_sourced(tok: tuple[str, str, str, str], known: list[tuple[str, str, str]]) -> bool:
    """A page number is sourced by a known number of the same value whose marks cover the page's marks."""
    _, cur, num, suf = tok
    return any(n == num and (not cur or c == cur) and (not suf or s == suf) for c, n, s in known)


def unsourced_numbers(page_text: str, facts: list[str], extra: list[tuple[str, str, str]] | None = None) -> list[str]:
    """Page number tokens without a brief fact token of the same number (and the same marks)."""
    known = fact_tokens(facts) + list(extra or [])
    out = []
    for tok in number_tokens(page_text):
        if not is_sourced(tok, known) and tok[0] not in out:
            out.append(tok[0])
    return out


def page_number_tokens(text: str, claims: dict | None) -> list[tuple[str, str, str, str]]:
    """v2 (queue #91): the page text's numbers that are claims. claims (measured in the page) lists the
    numbers that are not: step labels, and the text of pictures exposed as an image (drop); each dropped
    number takes out one page number shown the same way. Those pictures' accessible names are checked as
    text instead (names). Without claims (a version 1 raw file) every number counts, as in version 1."""
    toks = number_tokens(text)
    if not claims:
        return toks
    for d in claims.get("drop") or []:
        for t in number_tokens(norm(d.get("text", ""))):
            k = next((k for k, x in enumerate(toks) if x[0] == t[0]), None)
            if k is not None:
                del toks[k]
    for nm in claims.get("names") or []:
        toks += number_tokens(norm(nm.get("text", "")))
    return toks


DERIV_OPS = {"add": "+", "subtract": "-", "multiply": "x", "divide": "/"}


def num_text(v: Decimal) -> str:
    return format(v.normalize(), "f")


def apply_op(op: str, vals: list[Decimal]) -> Decimal | None:
    acc = vals[0]
    for v in vals[1:]:
        if op == "add":
            acc += v
        elif op == "subtract":
            acc -= v
        elif op == "multiply":
            acc *= v
        elif v == 0:
            return None
        else:
            acc /= v
    return acc


def check_derivation(d: dict, facts: list[str]) -> tuple[bool, str]:
    """v2 (queue #91): one derivations.json entry ({shown, operation, operands, facts}). It sources its shown
    number only when every listed fact is a brief fact word for word, each operand is one number a listed
    fact holds (the same marks; number words count), the shown number's marks are on an operand, and
    recomputing left to right gives exactly the shown number. Returns (valid, why not)."""
    shown = number_tokens(str(d.get("shown", "")))
    if len(shown) != 1:
        return False, "derivations.json: shown is not one number"
    s = shown[0]
    op = d.get("operation")
    if op not in DERIV_OPS:
        return False, f"derivations.json: {s[0]} has no known operation"
    listed = d.get("facts") or []
    if not listed or any(f not in facts for f in listed):
        return False, f"derivations.json: {s[0]} lists a fact not in the brief"
    held = fact_tokens(listed)
    ops = []
    for o in d.get("operands") or []:
        t = number_tokens(str(o))
        if len(t) != 1 or (t[0][1], t[0][2], t[0][3]) not in held:
            return False, f"derivations.json: operand {o} is not in its facts"
        ops.append(t[0])
    if len(ops) < 2:
        return False, f"derivations.json: {s[0]} needs 2 or more operands"
    if (s[1] and not any(t[1] == s[1] for t in ops)) or (s[3] and not any(t[3] == s[3] for t in ops)):
        return False, f"derivations.json: no operand carries {s[0]}'s mark"
    val = apply_op(op, [Decimal(t[2]) for t in ops])
    if val is None or val != Decimal(s[2]):
        got = "nothing" if val is None else s[1] + num_text(val) + s[3]
        return False, f"derivations.json: {op} gives {got}, not {s[0]}"
    return True, ""


def possible_derivation(tok: tuple[str, str, str, str], fact_toks: list, page_toks: list) -> str | None:
    """v2 (queue #91), evidence only: the first way to reach an unsourced number from two numbers, at least
    one of them a brief fact's, as text such as '$36 = 2 x $18'. Tries x, +, - then /; x and / take one
    number with the shown currency and one without (none when the shown number has none), + and - two with
    it; 0 and 1 are not used with x or /, nor 0 with + or -. A derivation sources the number only when the
    page folder's derivations.json lists it (check_derivation)."""
    shown, cur, num, suf = tok
    if suf:
        return None
    target = Decimal(num)
    pool, seen, facts = [], set(), set()
    for k, t in enumerate(list(fact_toks) + list(page_toks)):
        key = (t[1], t[2], t[3])
        if t[3] or key in seen or key == (cur, num, suf):
            continue
        seen.add(key)
        pool.append(t)
        if k < len(fact_toks):
            facts.add(key)

    def dv(t):
        return Decimal(t[2])

    def fact(a, b):
        return (a[1], a[2], a[3]) in facts or (b[1], b[2], b[3]) in facts

    plain = [t for t in pool if not t[1]]
    marked = [t for t in pool if t[1] == cur] if cur else plain
    for a in plain:
        for b in marked:
            if a is b or (not cur and pool.index(b) < pool.index(a)) or dv(a) in (0, 1) or dv(b) in (0, 1):
                continue
            if dv(a) * dv(b) == target and fact(a, b):
                return f"{shown} = {a[0]} x {b[0]}"
    for i, a in enumerate(marked):
        for b in marked[i + 1:]:
            if dv(a) != 0 and dv(b) != 0 and dv(a) + dv(b) == target and fact(a, b):
                return f"{shown} = {a[0]} + {b[0]}"
    for a in marked:
        for b in marked:
            if a is not b and dv(b) != 0 and dv(a) - dv(b) == target and fact(a, b):
                return f"{shown} = {a[0]} - {b[0]}"
    for a in marked:
        for b in plain:
            if a is not b and dv(b) not in (0, 1) and dv(a) / dv(b) == target and fact(a, b):
                return f"{shown} = {a[0]} / {b[0]}"
    return None


def srgb_to_oklab(rgb: list[float]) -> tuple[float, float, float]:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(float(v)) for v in rgb[:3])
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (x ** (1 / 3) for x in (l_, m_, s_))
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def oklab_distance(a: list[float], b: list[float]) -> float:
    pa, pb = srgb_to_oklab(a), srgb_to_oklab(b)
    return sum((x - y) ** 2 for x, y in zip(pa, pb, strict=True)) ** 0.5


def window_max(centres: list[float], view_h: float, page_h: float) -> tuple[int, float]:
    """Windows one viewport high from 0, stepping half a viewport, until one starts below the page.
    Returns the most centres in one window and that window's top."""
    best, top = 0, 0.0
    start, k = 0.0, 0
    while start < max(page_h, 1):
        n = sum(1 for c in centres if start <= c < start + view_h)
        if n > best:
            best, top = n, start
        k += 1
        start = k * view_h / 2
    return best, top


# ---------------------------------------------------------------- the scorer

def ev(sel: str, text: str = "", box=None) -> dict:
    return {"selector": sel, "text": norm(text)[:80], "box": [int(round(v)) for v in (box or [0, 0, 0, 0])]}


def solid(c: dict) -> bool:
    return (c["tag"] in ("a", "button") or c.get("role") == "button") and c["bg"][3] >= 1 and c["bg_ratio"] >= 3


def cta_norm(text: str) -> str:
    """v2 (queue #91): call-to-action wording without case, extra whitespace, arrows (\u2193 \u2192 \u203a >) at
    either end, or trailing punctuation (\u2026 . !)."""
    t, prev = norm(text).lower(), None
    while t != prev:
        prev = t
        t = re.sub(r"[\s\u2193\u2192\u203a>\u2026.!]+$", "", re.sub(r"^[\s\u2193\u2192\u203a>]+", "", t))
    return t


def in_first_screen(c: dict, h: float) -> bool:
    return 0 <= c["box"][1] + c["box"][3] / 2 <= h


def pick_cta(m: dict, brief: dict) -> tuple[dict | None, str]:
    """The primary call to action and the rule that picked it (v2, queue #91): the first control in the first
    screen whose wording is the brief's after cta_norm; else the most prominent filled button in the first
    screen (solid: background 3:1 or more against its surroundings; the largest area wins); else, as in
    version 1, the brief's wording anywhere, then the largest filled button on the page."""
    want = cta_norm(brief.get("cta", ""))
    h = m["viewport"][1]
    named = [c for c in m["controls"] if want and cta_norm(c["text"]) == want]
    inview = [c for c in named if in_first_screen(c, h)]
    if inview:
        return inview[0], "brief wording"

    def largest(cs):
        return max(cs, key=lambda c: (c["box"][2] * c["box"][3], -c["i"]))

    solids = [c for c in m["controls"] if solid(c)]
    first = [c for c in solids if in_first_screen(c, h)]
    if first:
        return largest(first), "most prominent filled button in the first screen"
    if named:
        return named[0], "brief wording, outside the first screen"
    if solids:
        return largest(solids), "largest filled button on the page"
    return None, ""


def primary_cta(m: dict, brief: dict) -> dict | None:
    return pick_cta(m, brief)[0]


def pct(cells: list[int]) -> str:
    on, total = cells
    return str(round(100 * on / total)) if total else "0"


def in_first(t: dict, w: float, h: float) -> bool:
    return any(0 <= q[1] + q[3] / 2 <= h and q[0] < w and q[0] + q[2] > 0 for q in t["lines"])


def tbox(t: dict) -> list[float]:
    x0 = min(q[0] for q in t["lines"])
    y0 = min(q[1] for q in t["lines"])
    x1 = max(q[0] + q[2] for q in t["lines"])
    y1 = max(q[1] + q[3] for q in t["lines"])
    return [x0, y0, x1 - x0, y1 - y0]


def half(v: float) -> float:
    return round(v * 2) / 2


def fmt(v: float, nd: int = 2) -> str:
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def check_width(check: str, view: dict, brief: dict) -> tuple:
    """One (value, pass, evidence) for a per-width check."""
    m = view["bar"]
    w, h = m["viewport"]
    texts = m["texts"]
    if check == "product-name":
        name = re.sub(r"\s+", "", brief.get("product", "")).lower()
        first = [t for t in texts if in_first(t, w, h)]
        joined = re.sub(r"\s+", "", " ".join(t["text"] for t in first)).lower()
        if name and name in joined:
            hit = next((t for t in first if name in re.sub(r"\s+", "", t["text"]).lower()), first[0] if first else None)
            return "found in text", True, [ev(hit["sel"], hit["text"], tbox(hit))] if hit else []
        for p in m["pictures"]:
            b = p["box"]
            if p.get("alt") and name and name in re.sub(r"\s+", "", p["alt"]).lower() and b[1] < h and b[1] + b[3] > 0:
                return "found in img alt", True, [ev(p["sel"], p["alt"], b)]
        return "not found", False, [ev(t["sel"], t["text"], tbox(t)) for t in first[:3]]
    if check == "h1-words":
        if not m["h1"]:
            return "no h1", False, []
        n = len(m["h1"]["text"].split())
        return n, n <= 12, [ev(m["h1"]["sel"], m["h1"]["text"], m["h1"]["box"])]
    if check == "cta-in-view":
        c, rule = pick_cta(m, brief)
        if not c:
            return "no primary CTA", False, []
        x, y, bw, bh = c["box"]
        ok = x >= 0 and y >= 0 and x + bw <= w and y + bh <= h
        return (f"box {fmt(x)},{fmt(y)} {fmt(bw)}x{fmt(bh)} in {w}x{h}", ok,
                [ev(c["sel"], c["text"], c["box"]), ev("(picked by)", rule)])
    if check == "visual-anchor":
        need = 120 if w >= 1440 else 96

        def fits(box) -> bool:
            x, y, bw, bh = box
            if bw < need or bh < need:
                return False
            inside = max(0.0, min(y + bh, h) - max(y, 0.0)) * max(0.0, min(x + bw, w) - max(x, 0.0))
            return inside >= 0.5 * bw * bh

        good = [k for k, p in enumerate(m["pictures"]) if fits(p["box"])]
        # v2 (queue #91): a picture built in HTML counts when it is exposed as an image (role=img with a name,
        # or a figure with a figcaption or aria-labelledby) and a third or more of its box is painted by
        # non-text boxes, at the same size and place as any anchor. One anchor counts once: an HTML picture
        # holding a counted picture, or inside a counted HTML picture, adds nothing.
        htmls = m.get("html_pictures") or []
        ok_html = [k for k, p in enumerate(htmls) if p["exposed"] and 3 * p["cells"][0] >= p["cells"][1] and fits(p["box"])]
        hgood = [htmls[k] for k in ok_html if not set(htmls[k]["pics"]) & set(good) and not set(htmls[k]["anc"]) & set(ok_html)]
        if good or hgood:
            evid = [ev(m["pictures"][k]["sel"], m["pictures"][k]["kind"], m["pictures"][k]["box"]) for k in good]
            evid += [ev(p["sel"], f"html picture ({p['kind']}), painted {pct(p['cells'])}%", p["box"]) for p in hgood]
            return len(good) + len(hgood), True, evid[:5]
        near = []
        for p in htmls:
            x, y, bw, bh = p["box"]
            if not (y < h and y + bh > 0 and x < w and x + bw > 0):
                continue
            if not p["exposed"]:
                why = f"not exposed as an image: {p['why']}"
            elif 3 * p["cells"][0] < p["cells"][1]:
                why = f"painted {pct(p['cells'])}% of its box, needs a third"
            else:
                why = f"{fmt(bw)}x{fmt(bh)}, needs {need}x{need} with half in the first screen"
            near.append(ev(p["sel"], why, p["box"]))
        return 0, False, near[:5]
    if check == "one-h1":
        h1s = [x for x in m["headings"] if x["level"] == 1]
        return len(h1s), len(h1s) == 1, [ev(x["sel"], x["text"], x["box"]) for x in h1s[:5]]
    if check == "h1-largest":
        first = [t for t in texts if in_first(t, w, h)]
        mine = [t for t in first if t["in_h1"]]
        if not mine:
            return "h1 not in the first viewport", False, [ev(m["h1"]["sel"], m["h1"]["text"], m["h1"]["box"])] if m["h1"] else []
        top = max(t["size"] for t in mine)
        others = [t for t in first if not t["in_h1"]]
        big = max(others, key=lambda t: t["size"]) if others else None
        bigger = [t for t in others if t["size"] > top]
        value = f"h1 {fmt(top)}px, largest other {fmt(big['size']) if big else 0}px"
        return value, not bigger, [ev(t["sel"], t["text"], tbox(t)) for t in bigger[:5]]
    if check == "primary-per-window":
        c = primary_cta(m, brief)
        if not c or not solid(c):
            return 0, True, []
        prim = [b for b in m["controls"] if solid(b) and oklab_distance(b["bg"], c["bg"]) < 0.02]
        n, top = window_max([b["box"][1] + b["box"][3] / 2 for b in prim], h, m["page_height"])
        inwin = [b for b in prim if top <= b["box"][1] + b["box"][3] / 2 < top + h]
        return n, n <= 1, [ev(b["sel"], b["text"], b["box"]) for b in inwin[:5]] if n > 1 else []
    if check in ("font-sizes", "section-sizes", "section-colours"):
        solid_ids = {c["i"] for c in m["controls"] if solid(c)}
        if check == "font-sizes":
            sizes = sorted({half(t["size"]) for t in texts})
            return len(sizes), len(sizes) <= 7, ([ev(next(t["sel"] for t in texts if half(t["size"]) == s), f"{fmt(s)}px")
                                                 for s in sizes[:5]] if len(sizes) > 7 else [])
        worst, worst_sec, worst_vals = 0, None, []
        for i, sec in enumerate(m["sections"]):
            own = [t for t in texts if t["sec"] == i and not (t["ctl"] >= 0 and t["ctl"] in solid_ids)]
            vals = sorted({half(t["size"]) for t in own}) if check == "section-sizes" else sorted({tuple(t["color"]) for t in own})
            if len(vals) > worst:
                worst, worst_sec, worst_vals = len(vals), sec, vals
        limit = 4 if check == "section-sizes" else 3
        shown = ", ".join(fmt(v) + "px" if check == "section-sizes" else "rgb({},{},{})".format(*v) for v in worst_vals)
        evid = [ev(worst_sec["sel"], shown)] if worst_sec and worst > limit else []
        return worst, worst <= limit, evid
    if check == "spacing-grid":
        counts = m["spacing"]["counts"]
        total = sum(counts.values())
        if not total:
            return "no spacing values", None, []
        on = sum(n for v, n in counts.items() if abs(float(v) / 4 - round(float(v) / 4)) * 4 <= 0.5)
        share = round(100 * on / total, 1)
        off = sorted(((n, v) for v, n in counts.items() if abs(float(v) / 4 - round(float(v) / 4)) * 4 > 0.5), reverse=True)
        return share, share >= 90, ([ev("(spacing values)", ", ".join(f"{v}px x{n}" for n, v in off[:6]))] if share < 90 else [])
    if check == "rhythm":
        inside, between = [], []
        prev = None
        for i, boxes in enumerate(m["content_boxes"]):
            if not boxes:
                continue
            low = None
            for top, bottom, _ in boxes:
                if low is not None and top - low > 0:
                    inside.append(top - low)
                low = bottom if low is None else max(low, bottom)
            first_top = min(b[0] for b in boxes)
            # v2 (queue #91): the gap under the page header (the banner) is not a gap between sections.
            if prev is not None and not m["sections"][prev[0]].get("banner"):
                between.append((first_top - prev[1], prev[0], i))
            prev = (i, max(b[1] for b in boxes))
        if not inside or not between:
            return "not enough sections or boxes", None, []
        med = statistics.median(inside)
        gap, a, b = min(between)
        ok = all(g >= 2 * med for g, _, _ in between)
        bad = [x for x in between if x[0] < 2 * med]
        evid = [ev(f"{m['sections'][x[1]]['sel']} | {m['sections'][x[2]]['sel']}", f"gap {fmt(x[0])}px") for x in bad[:5]]
        return f"smallest gap between sections {fmt(gap)}px, median inside {fmt(med)}px", ok, evid
    body = m["body"]
    if check == "body-size":
        if not body:
            return "no body text", True, []
        low = min(body, key=lambda b: b["size"])
        bad = [b for b in body if b["size"] < 16]
        return low["size"], low["size"] >= 16, [ev(b["sel"], b["text"], b["box"]) for b in bad[:5]]
    if check == "line-height":
        if not body:
            return "no body text", True, []
        ratios = []
        for b in body:
            if b["line_height_px"] is not None:
                r = b["line_height_px"] / b["size"]
            else:
                r = b["content_height"] / max(1, b["lines"]) / b["size"]
            ratios.append((round(r, 3), b))
        bad = [(r, b) for r, b in ratios if not 1.2 <= r <= 1.5]
        lo, hi = min(r for r, _ in ratios), max(r for r, _ in ratios)
        return f"{fmt(lo)}-{fmt(hi)}", not bad, [ev(b["sel"], f"{fmt(r)}: {b['text']}", b["box"]) for r, b in bad[:5]]
    if check == "measure":
        if any("blocks" in b for b in body):
            # v2 (queue #91): running text only, block by block: text blocks of 2 or more lines, or of 60 or
            # more characters. A one-line block counts its one line; labels and one-character cells drop out.
            paras = [k for b in body for k in b.get("blocks") or [] if k["lines"] >= 2 or sum(k["line_chars"]) >= 60]
            if not paras:
                return "no running text", True, []
        else:
            paras = [b for b in body if b["lines"] >= 2 and b.get("line_chars") and len(b["line_chars"]) >= 2]
            if not paras:
                return "no paragraphs of 2 or more lines", True, []
        avgs = [(sum(b["line_chars"][:-1]) / (len(b["line_chars"]) - 1) if len(b["line_chars"]) >= 2
                 else float(sum(b["line_chars"])), b) for b in paras]
        good = [a for a, _ in avgs if 45 <= a <= 90]
        share = round(100 * len(good) / len(avgs), 1)
        bad = [(a, b) for a, b in avgs if not 45 <= a <= 90]
        return share, share >= 90, [ev(b["sel"], f"{fmt(a, 1)} chars/line: {b['text']}", b["box"]) for a, b in bad[:5]]
    if check == "fk-grade":
        g = fk_grade([b["text"] for b in body])
        if g is None:
            return "no body text", None, []
        g = round(g, 1)
        return g, g <= 9, ([ev(b["sel"], b["text"], b["box"]) for b in body[:3]] if g > 9 else [])
    if check == "axe":
        axe = view.get("axe")
        if axe is None:
            return "axe did not run", None, []
        evid = [ev(n.get("target", ""), f"{v['id']}: {v.get('help', '')}") for v in axe for n in v.get("nodes", [])[:1]]
        return len(axe), not axe, evid[:5]
    if check == "text-contrast":
        meas = view.get("measure") or {}
        fails = meas.get("contrast_failures") or []
        over = {c["sel"]: c for c in view.get("overlays") or []}
        pixels = view.get("pixels") or {}
        bad, unknown, replaced = [], [], 0
        for f in fails:
            c = over.get(f["sel"])
            if c is not None:
                px = pixels.get(str(c["id"]))
                if px:
                    replaced += 1
                    continue
                unknown.append(f)
                continue
            bad.append((f["contrast"], f["needs"], f["sel"], f["text"], f["box"]))
        for c in view.get("overlays") or []:
            px = pixels.get(str(c["id"]))
            if px and px["ratio"] < c["needs"]:
                same = next((t for t in texts if t["sel"] == c["sel"]), None)
                bad.append((px["ratio"], c["needs"], c["sel"], c["text"], tbox(same) if same else None))
        evid = [ev(s, f"{fmt(r)}:1 needs {fmt(n)}:1 \"{tx}\"", b) for r, n, s, tx, b in bad[:5]]
        if bad:
            return len(bad), False, evid
        if unknown or (len(fails) >= 25 and replaced == len(fails)):
            return "could not measure", None, [ev(f["sel"], f["text"], f["box"]) for f in unknown[:5]]
        return 0, True, []
    if check == "targets":
        small = (view.get("measure") or {}).get("small_targets") or []
        return len(small), not small, [ev(s["sel"], s.get("name", ""), s.get("box")) for s in small[:5]]
    if check == "no-hscroll":
        return f"scrollWidth {m['scroll_width']} / innerWidth {m['inner_width']}", m["scroll_width"] <= m["inner_width"], []
    if check == "headings":
        hs = m["headings"]
        h1 = sum(1 for x in hs if x["level"] == 1)
        skips = [(a, b) for a, b in zip(hs, hs[1:], strict=False) if b["level"] - a["level"] > 1]
        value = f"{h1} h1, {len(skips)} skipped level(s)"
        evid = [ev(b["sel"], f"h{a['level']} -> h{b['level']}: {b['text']}", b["box"]) for a, b in skips[:5]]
        return value, h1 == 1 and not skips, evid
    if check == "landmarks":
        lm = m["landmarks"]
        missing = [k for k in ("main", "header_or_nav", "footer") if not lm[k]]
        return ("all present" if not missing else "missing " + ", ".join(missing)), not missing, []
    if check == "lang":
        lang = (m.get("lang") or "").strip()
        return (lang or "not set"), bool(lang), []
    if check == "img-alt":
        bad = m["images"]["no_alt"]
        return len(bad), not bad, [ev(b["sel"], b["text"], b["box"]) for b in bad[:5]]
    if check == "svg-names":
        bad = [s for s in m["svgs"] if max(s["w"], s["h"]) >= 48 and not s["hidden"] and not (s["role"] == "img" and s["name"])]
        return len(bad), not bad, [ev(s["sel"], s["name"], s["box"]) for s in bad[:5]]
    if check == "overlap":
        pairs = []
        for i, a in enumerate(texts):
            for b in texts[i + 1:]:
                if b["i"] in a["anc"] or a["i"] in b["anc"]:
                    continue
                if any(min(p[0] + p[2], q[0] + q[2]) - max(p[0], q[0]) > 2 and min(p[1] + p[3], q[1] + q[3]) - max(p[1], q[1]) > 2
                       for p in a["bands"] for q in b["bands"]):
                    pairs.append((a, b))
        evid = [ev(f"{a['sel']} | {b['sel']}", f"{a['text'][:38]} | {b['text'][:38]}", tbox(a)) for a, b in pairs[:5]]
        return len(pairs), not pairs, evid
    if check == "clipped":
        bad = []
        for o in m["overflowing"]:
            x = o["overflow_x"] != "visible" and o["scroll_width"] - o["client_width"] > 1 and (o["own_text"] or o["text_past_x"] > 1)
            y = o["overflow_y"] != "visible" and o["scroll_height"] - o["client_height"] > 1 and (o["own_text"] or o["text_past_y"] > 1)
            e = o["ellipsis"] and o["scroll_width"] - o["client_width"] >= 1
            if x or y or e:
                bad.append(o)
        return len(bad), not bad, [ev(o["sel"], o["text"], o["box"]) for o in bad[:5]]
    if check == "word-split":
        # v2 (queue #91): words whose glyphs sit on two lines with no hyphen drawn at the break.
        splits = m.get("word_splits")
        if splits is None:
            return "not measured", None, []
        return len(splits), not splits, [ev(x["sel"], x["text"], x["box"]) for x in splits[:5]]
    raise KeyError(check)


def check_all(check: str, raw: dict, brief: dict, verbs: set[str], patterns: list[re.Pattern]) -> tuple:
    views = {wk: v for wk, v in raw["widths"].items() if v.get("bar")}
    if check in ("cta-length", "cta-verb", "cta-wording"):
        c, rule = None, ""
        for wk in ("1440x900", "390x844"):
            if wk in views:
                c, rule = pick_cta(views[wk]["bar"], brief)
                if c:
                    break
        if not c:
            return "no primary CTA", None, []
        if check == "cta-wording":
            # v2 (queue #91): the primary call to action says what the brief's says, after cta_norm.
            want = brief.get("cta", "")
            if not cta_norm(want):
                return "brief has no call to action", None, []
            ok = cta_norm(c["text"]) == cta_norm(want)
            return norm(c["text"]), ok, [ev(c["sel"], c["text"], c["box"]), ev("(picked by)", rule), ev("(brief)", want)]
        if check == "cta-length":
            n = len(norm(c["text"]))
            return n, n <= 40, [ev(c["sel"], c["text"], c["box"])]
        ok = cta_verb_ok(c["text"], verbs)
        return (norm(c["text"]).split(" ")[0] if norm(c["text"]) else ""), ok, [ev(c["sel"], c["text"], c["box"])]
    if len(views) < len(WIDTHS):
        return "not measured at every width", None, []
    if check == "disclosure":
        if not brief.get("fictional"):
            return "not fictional", True, []
        line = norm(brief.get("disclosure", ""))
        if not line:
            return "brief has no disclosure line", None, []
        have = [wk for wk in WIDTHS if line in norm(views[wk]["bar"]["page_text"])]
        return f"present at {len(have)}/{len(WIDTHS)} widths", len(have) == len(WIDTHS), []
    if check == "placeholders":
        hits = []
        for wk in WIDTHS:
            for ln in views[wk]["bar"]["page_text"].splitlines():
                for p in patterns:
                    mt = p.search(ln)
                    if mt and (mt.group(0), ln) not in [(a, b) for a, b, _ in hits]:
                        hits.append((mt.group(0), ln, p.pattern))
        return len(hits), not hits, [ev("(page text)", f"{a}: {b}") for a, b, _ in hits[:5]]
    if check == "numbers":
        line = norm(brief.get("disclosure", ""))
        facts = brief.get("facts") or []
        known = fact_tokens(facts)
        rejected = {}
        for d in (raw.get("derivations") or {}).get("items") or []:
            ok, why = check_derivation(d, facts)
            s = number_tokens(str(d.get("shown", "")))
            if ok:
                known.append((s[0][1], s[0][2], s[0][3]))
            elif len(s) == 1:
                rejected.setdefault((s[0][1], s[0][2], s[0][3]), why)
        found, page_toks = [], []
        for wk in WIDTHS:
            bar = views[wk]["bar"]
            text = bar["page_text"]
            foot = bar.get("footer_text") or ""
            if foot and foot in text:
                text = text.replace(foot, YEAR_RE.sub(" ", foot))
            text = norm(text)
            if line:
                text = text.replace(line, " ")
            for tok in page_number_tokens(text, bar.get("claims")):
                if tok[0] not in [t[0] for t in page_toks]:
                    page_toks.append(tok)
                if not is_sourced(tok, known) and tok[0] not in [t[0] for t in found]:
                    found.append(tok)
        evid = []
        for tok in found[:5]:
            txt = possible_derivation(tok, fact_token_list(facts), page_toks) or tok[0]
            why = rejected.get((tok[1], tok[2], tok[3]))
            evid.append(ev("(page text)", f"{txt} ({why})" if why else txt))
        return len(found), not found, evid
    raise KeyError(check)


def score(raw: dict, brief: dict, verbs: set[str] | None = None, patterns: list[re.Pattern] | None = None) -> list[dict]:
    """Raw measurements to rows, in the fixed (bar, check, width) order. Pure: no browser, no files."""
    verbs = load_verbs() if verbs is None else verbs
    patterns = load_patterns() if patterns is None else patterns
    rows = []
    for bar, check, spec, limit in CHECKS:
        for wk in widths_of(spec):
            if wk == "all":
                value, ok, evid = check_all(check, raw, brief, verbs, patterns)
            else:
                view = raw["widths"].get(wk) or {}
                if not view.get("bar"):
                    value, ok, evid = "could not measure: " + str(view.get("error", "no measurements"))[:120], None, []
                else:
                    value, ok, evid = check_width(check, view, brief)
            rows.append({"bar": bar, "check": check, "width": wk, "value": value, "limit": limit, "pass": ok, "evidence": evid})
    return rows


def failing(rows: list[dict]) -> set[tuple[str, str, str]]:
    return {(r["bar"], r["check"], r["width"]) for r in rows if r["pass"] is not True}


def bars_doc(raw: dict, rows: list[dict], brief_path: str) -> dict:
    return {"meter": METER, "version": VERSION, "page": raw["page"], "page_sha256": raw["page_sha256"], "brief": brief_path,
            "widths": WIDTHS, "rows": rows}


def bars_md(doc: dict) -> str:
    def cell(v):
        return str(v).replace("|", "\\|").replace("\n", " ")
    out = [f"# {doc['meter']} v{doc['version']}: {doc['page']}", "", f"page sha256 `{doc['page_sha256']}`; brief `{doc['brief']}`", "",
           "## Per bar", "", "| bar | met | rows passing | failing checks |", "|---|---|---|---|"]
    for bar in sorted({r["bar"] for r in doc["rows"]}):
        rs = [r for r in doc["rows"] if r["bar"] == bar]
        ok = [r for r in rs if r["pass"] is True]
        bad = sorted({r["check"] for r in rs if r["pass"] is not True}, key=[c[1] for c in CHECKS].index)
        out.append(f"| {bar} | {'met' if len(ok) == len(rs) else 'not met'} | {len(ok)}/{len(rs)} | {', '.join(bad) or '-'} |")
    out += ["", "A bar is met only when every one of its rows passes; a pass of \"?\" means \"could not measure\" and counts as not met.",
            "", "## Rows", "", "| bar | check | width | value | limit | pass |", "|---|---|---|---|---|---|"]
    for r in doc["rows"]:
        p = {True: "pass", False: "FAIL", None: "?"}[r["pass"]]
        out.append(f"| {r['bar']} | {r['check']} | {r['width']} | {cell(r['value'])} | {cell(r['limit'])} | {p} |")
    fails = [r for r in doc["rows"] if r["pass"] is not True and r["evidence"]]
    if fails:
        out += ["", "## Evidence for failing rows", ""]
        for r in fails:
            out.append(f"- {r['bar']} {r['check']} {r['width']}: " + "; ".join(
                f"`{e['selector']}` \"{e['text']}\" at {e['box']}" for e in r["evidence"]))
    return "\n".join(out) + "\n"


def write_outputs(out: pathlib.Path, raw: dict, brief: dict, brief_path: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    doc = bars_doc(raw, score(raw, brief), brief_path)
    (out / "bars.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "bars.md").write_text(bars_md(doc), encoding="utf-8")
    return doc


# ---------------------------------------------------------------- the browser driver

SETTLE = (
    "async (page) => await page.evaluate(async () => { for (const a of document.getAnimations()) { try { "
    "const t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null; "
    "if (t && t.endTime === Infinity) { a.pause(); a.currentTime = 0; } else { a.finish(); } } catch (e) {} } "
    "window.scrollTo(0, 0); if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); "
    "await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); return true; })"
)


async def measure_width(s, url: str, w: int, h: int, srcs: dict) -> dict:
    import design_capture as dc
    import design_page_checks as pc
    view: dict = {}
    await dc.run(s, f"async (page) => {{ await page.setViewportSize({{width: {w}, height: {h}}}); "
                    "await page.emulateMedia({colorScheme: 'light', reducedMotion: 'no-preference'}); "
                    f"await page.goto({json.dumps(url)}, {{waitUntil: 'networkidle'}}); "
                    "await page.evaluate(() => document.fonts.ready.then(() => true)); return true; }")
    await dc.run(s, SETTLE)
    opts = {"min_words": MIN_WORDS, "chars": w == 1440}
    bar = await dc.run(s, "async (page) => await page.evaluate(" + json.dumps(f"({srcs['bar']})({json.dumps(opts)})") + ")")
    if not isinstance(bar, dict):
        return {"error": f"bar measurements: {str(bar)[:300]}"}
    view["bar"] = bar
    meas = await dc.run(s, "async (page) => await page.evaluate(" + json.dumps(srcs["measure"]) + ")")
    meas = meas if isinstance(meas, dict) else {}
    view["measure"] = {k: meas.get(k) for k in ("contrast_failures", "small_targets")}
    if f"{w}x{h}" in FIRST:
        try:
            view["axe"] = await dc.run(
                s, "async (page) => { await page.evaluate(" + json.dumps(srcs["axe"]) + "); "
                "return await page.evaluate(async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values: "
                + json.dumps(dc.AXE_TAGS) + "}, resultTypes: ['violations']}); return r.violations.map(v => ({id: v.id, impact: v.impact, "
                "help: v.help, nodes: v.nodes.slice(0, 5).map(n => ({target: n.target.join(' ')}))})); }); }")
        except Exception as exc:  # noqa: BLE001 - recorded; the row becomes "could not measure"
            view["axe"] = None
            view["axe_error"] = f"{exc.__class__.__name__}: {str(exc)[:300]}"
    t = pc.thresholds()
    checks = await dc.run(s, "async (page) => await page.evaluate(" + json.dumps(pc.source(t, "", copy=False, columns=False, visuals=False)) + ")")
    checks = checks if isinstance(checks, dict) else {}
    view["overlays"] = [{k: c.get(k) for k in ("id", "sel", "text", "size", "weight", "needs", "kind", "declared")}
                        for c in checks.get("overlays") or []]
    view["pixels"] = {}
    if checks.get("overlays"):
        try:
            view["pixels"] = await dc.run(s, pc.pixel_code(checks["overlays"], t)) or {}
        except Exception as exc:  # noqa: BLE001 - recorded; overlay text without pixels is "could not measure"
            view["pixels_error"] = f"{exc.__class__.__name__}: {str(exc)[:300]}"
    view["pixels"] = {str(k): v for k, v in sorted(view["pixels"].items(), key=lambda kv: int(kv[0]))}
    return view


async def measure_pages(site: pathlib.Path, pages: list[str], browser: str, serve_host: str | None) -> dict[str, dict]:
    import design_capture as dc
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    srcs = {"bar": JS.read_text(encoding="utf-8"), "measure": dc.MEASURE.read_text(encoding="utf-8"),
            "axe": dc.AXE.read_text(encoding="utf-8")}
    base, srv = dc.serve(site.resolve(), serve_host or urllib.parse.urlparse(browser).hostname)
    out = {}
    try:
        async with streamablehttp_client(browser) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                for page in pages:
                    views = {}
                    for (vw, vh), wk in zip(SIZES, WIDTHS, strict=True):
                        try:
                            views[wk] = await measure_width(s, base + "/" + page.lstrip("/"), vw, vh, srcs)
                        except Exception as exc:  # noqa: BLE001 - one width failing leaves its rows "could not measure"
                            views[wk] = {"error": f"{exc.__class__.__name__}: {str(exc)[:300]}"}
                    out[page] = views
                await s.call_tool("browser_close", {})
    finally:
        srv.shutdown()
    return out


def page_raw(site: pathlib.Path, page: str, views: dict, label: str | None = None) -> dict:
    f = site / page
    raw = {"meter": METER, "version": VERSION, "page": label or str(f.resolve()),
           "page_sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "widths": views}
    # v2 (queue #91): the page folder's derivations.json, when there is one (A5 numbers).
    d = f.parent / "derivations.json"
    if d.is_file():
        data = d.read_bytes()
        raw["derivations"] = {"file": "derivations.json", "sha256": hashlib.sha256(data).hexdigest(),
                              "items": json.loads(data).get("derivations") or []}
    return raw


def load_keys() -> tuple[dict, dict]:
    """bar-v1/expected.json (part 1's key) and bar-v2/expected.json (version 2's cases and added rows)."""
    return (json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8")),
            json.loads((FIXTURES_V2 / "expected.json").read_text(encoding="utf-8")))


def raw_name(page: str) -> str:
    """bar-v1/clean.html -> clean; bar-v2/c-derived-ok/index.html -> c-derived-ok-index."""
    return "-".join(pathlib.PurePosixPath(page).with_suffix("").parts[1:])


def page_brief(page: str, key1: dict, key2: dict) -> str:
    return key2["pages"][page]["brief"] if page in key2["pages"] else key1["brief"]


def key_match(page: str, rows: list[dict], key1: dict, key2: dict) -> dict:
    """One fixture page's rows against its key. A bar-v1 page: bar-v1/expected.json for the rows it covers,
    plus bar-v2/expected.json's bar-v1 section for the rows version 2 added. A bar-v2 page: its exact failing
    set, and each keyed row's pass, value and evidence items."""
    got = failing(rows)
    notes = []
    if page in key2["pages"]:
        k = key2["pages"][page]
        want = {tuple(x) for x in k["failing"]}
        by = {(r["bar"], r["check"], r["width"]): r for r in rows}
        for spec in k["rows"]:
            where = f"{spec['bar']} {spec['check']} {spec['width']}"
            r = by.get((spec["bar"], spec["check"], spec["width"]))
            if r is None:
                notes.append(f"{where}: no such row")
                continue
            if r["pass"] is not spec["pass"]:
                notes.append(f"{where}: pass {r['pass']}, key {spec['pass']}")
            if "value" in spec and r["value"] != spec["value"]:
                notes.append(f"{where}: value {r['value']!r}, key {spec['value']!r}")
            for e in spec.get("evidence") or []:
                if not any(("selector" not in e or x["selector"] == e["selector"])
                           and ("text" not in e or x["text"] == e["text"])
                           and ("text_has" not in e or e["text_has"] in x["text"]) for x in r["evidence"]):
                    notes.append(f"{where}: no evidence like {e}")
    else:
        added = {tuple(x) for x in key2["bar-v1"]["checks"]}
        want = {tuple(x) for x in key1["pages"][page] if (x[0], x[1]) not in added}
        want |= {tuple(x) for x in key2["bar-v1"]["pages"][page]}
    missing, extra = sorted(want - got), sorted(got - want)
    return {"match": not missing and not extra and not notes, "failing": len(got), "missing": missing, "extra": extra,
            "rows": notes}


def fixture_proof(out: pathlib.Path, browser: str, serve_host: str | None, record: bool) -> dict:
    """Measure every bar-v1 and bar-v2 fixture page in one browser session; compare each with its key."""
    key1, key2 = load_keys()
    site = REPO / key1["site"]
    pages = list(key1["pages"]) + list(key2["pages"])
    measured = asyncio.run(measure_pages(site, pages, browser, serve_host))
    result = {"pages": {}, "match": True}
    for page in pages:
        name = raw_name(page)
        brief_path = site / page_brief(page, key1, key2)
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        raw = page_raw(site, page, measured[page], label=str((site / page).relative_to(REPO)))
        text = json.dumps(raw, indent=1, ensure_ascii=False) + "\n"
        (out / name).mkdir(parents=True, exist_ok=True)
        (out / name / "raw.json").write_text(text, encoding="utf-8")
        if record:
            folder = (FIXTURES_V2 if page in key2["pages"] else FIXTURES) / "raw"
            folder.mkdir(exist_ok=True)
            (folder / f"{name}.json").write_text(text, encoding="utf-8")
        doc = write_outputs(out / name, raw, brief, str(brief_path.relative_to(REPO)))
        res = key_match(page, doc["rows"], key1, key2)
        result["pages"][page] = res
        result["match"] = result["match"] and res["match"]
    (out / "fixture-proof.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", help="the built site folder")
    ap.add_argument("--page", default="index.html")
    ap.add_argument("--brief", help="the brief.json (product, cta, facts, fictional, disclosure)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--browser", default="http://playwright-mcp:8931/mcp")
    ap.add_argument("--serve-host", default=None, help="the browser's address, to pick the address the site is served at")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--raw-only", action="store_true")
    mode.add_argument("--from-raw", help="score DIR/raw.json with no browser")
    ap.add_argument("--fixture-proof", action="store_true",
                    help="measure every bar-v1 and bar-v2 page and compare with their expected.json keys")
    ap.add_argument("--record", action="store_true", help="with --fixture-proof: save the raw files to bar-v1/raw/ and bar-v2/raw/")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.fixture_proof:
        res = fixture_proof(out, a.browser, a.serve_host, a.record)
        print(json.dumps(res, indent=1))
        return 0 if res["match"] else 1
    if not a.brief:
        ap.error("give --brief")
    brief_path = pathlib.Path(a.brief).resolve()
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    if a.from_raw:
        raw = json.loads((pathlib.Path(a.from_raw) / "raw.json").read_text(encoding="utf-8"))
    else:
        if not a.site:
            ap.error("give --site (or --from-raw)")
        site = pathlib.Path(a.site)
        views = asyncio.run(measure_pages(site, [a.page], a.browser, a.serve_host))[a.page]
        raw = page_raw(site, a.page, views)
        (out / "raw.json").write_text(json.dumps(raw, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        if a.raw_only:
            print(json.dumps({"ok": True, "raw": str(out / "raw.json")}))
            return 0
    doc = write_outputs(out, raw, brief, str(brief_path))
    bad = sorted(failing(doc["rows"]))
    print(json.dumps({"ok": True, "out": str(out), "rows": len(doc["rows"]), "failing": len(bad),
                      "bars_not_met": sorted({b for b, _, _ in bad})}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
