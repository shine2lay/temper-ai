#!/usr/bin/env python3
"""Countable word checks for Design's homepage workflow v2 (hypothesis H7, wave 2 task W4d).

The content critic (design_homepage_content_critic_v2, a model step) reviews the copy deck (node
copy_review) and the built page's words (node content). Some of what it checks can be counted, so
this script checks those parts with fixed rules, and the critic can keep to meaning and tone:

  cta_length      a call to action over 40 characters                              BAR.md A5
  cta_verb        a call to action that does not start with an action verb        BAR.md A5
                  (the curated list configs/design/knowledge/cta-verbs.txt)
  unsourced_name  a proper name that no brief fact and not the product name       BAR.md A5;
                  contains (on the page: nor the approved deck)                    critic 'claims'
  long_paragraph  page only: a paragraph over three lines at 1440 px, that is     critic 'scannability'
                  more than 270 characters at the 90-character measure the
                  workflow allows
  renamed_term    page only: a term from the deck's terms list that the page      critic 'terms',
                  never uses, while a near variant stands in its place             'drift'

RULES below gives each rule's level, grade and the lines it comes from. What copy_contract and
page_copy_problems in design_homepage_v2.py already check (words per field, generic CTAs, numbers
not in the facts, notices, hedges, the deck's headline on the page) is not repeated here.

Usage:
  design_word_checks.py deck --copy homepage/copy/copy.json --brief brief.json [--out FILE]
  design_word_checks.py page --text review/page-text.md --copy homepage/copy/copy.json \\
      --brief brief.json [--out FILE]

--text takes review/page-text.md (the runtime checks' visible text at 1440 px, "- [tag] text"
lines under "## section" headings) or the runtime checks' raw.json (its focus.text list). Without
--out the report goes to stdout. No model, browser or network: the same inputs give byte-identical
output.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design_homepage_v2 as v2  # noqa: E402 - sits next to this script; deck_fields is the deck's shape

VERSION = 1
VERBS_FILE = HERE.parent / "knowledge" / "cta-verbs.txt"

CTA_MAX_CHARS = 40  # BAR.md A5
PARAGRAPH_MAX_LINES = 3  # content critic: "a paragraph over about three lines at 1440 px"
LINE_MAX_CHARS = 90  # craft critic v2 "measure 45-90 characters"; design_measure.js long_lines "> 90"
PARAGRAPH_MAX_CHARS = PARAGRAPH_MAX_LINES * LINE_MAX_CHARS  # 270: over 3 lines at any measure allowed

RULE_ORDER = ("cta_length", "cta_verb", "unsourced_name", "long_paragraph", "renamed_term")
CRITIC = "configs/design/agents/design_homepage_content_critic_v2.yaml"
BAR_A5 = "~/design-lab/homepage-workflow/BAR.md A5"
A5_CTA = "call to action 40 characters or fewer, starting with a verb"

# Each rule: the critic check it takes over, its level and grade, and where they come from. The quotes
# are word for word (tests/test_design_word_checks.py checks the repo files; BAR.md lives on the host).
# Grades follow the design handbook 4.5: Must = a broken spec rule (BAR.md A5) or severity 3-4,
# Should = severity 2, Could = severity 1.
RULES: dict[str, dict[str, Any]] = {
    "cta_length": {
        "check": "cta", "targets": ["deck", "page"], "level": "2", "grade": "Must (breaks BAR.md A5)",
        "rule": f"a call to action over {CTA_MAX_CHARS} characters (spaces collapsed, arrows and other "
                "symbols at either end left out)",
        "sources": [
            {"file": BAR_A5, "quote": A5_CTA},
            {"file": CRITIC, "quote": "2 = slows or confuses some visitors"},
        ],
    },
    "cta_verb": {
        "check": "cta", "targets": ["deck", "page"], "level": "3 on the primary action, 2 on others",
        "grade": "Must (breaks BAR.md A5)",
        "rule": "a call to action whose first word is not in configs/design/knowledge/cta-verbs.txt",
        "sources": [
            {"file": BAR_A5, "quote": A5_CTA},
            {"file": CRITIC, "quote": "cta: a call to action that does not say what happens"},
            {"file": CRITIC, "quote": "3 = most visitors misread or stall (an unexplained label on the main path, "
                                      "a CTA that does not say what happens"},
            {"file": CRITIC, "quote": "2 = slows or confuses some visitors"},
        ],
    },
    "unsourced_name": {
        "check": "claims", "targets": ["deck", "page"], "level": "4", "grade": "Must (breaks BAR.md A5)",
        "rule": "a capitalised word or run of words, not at a sentence start, not a common word or an action "
                "verb and not written in lower case elsewhere, that the brief's facts and product name do not "
                "contain (on the page: nor the approved deck)",
        "sources": [
            {"file": BAR_A5, "quote": "every factual claim maps to a brief fact (script claim list; "
                                      "the content critic for meaning); 0 unsourced claims"},
            {"file": CRITIC, "quote": "claims: a claim, number or name that no brief fact supports."},
            {"file": CRITIC, "quote": "4 = misleads or blocks the main job (an unsupported claim"},
        ],
    },
    "long_paragraph": {
        "check": "scannability", "targets": ["page"], "level": "2", "grade": "Should",
        "rule": f"a body paragraph of the page over {PARAGRAPH_MAX_CHARS} characters "
                f"({PARAGRAPH_MAX_LINES} lines of {LINE_MAX_CHARS} characters), pieces split by a link joined",
        "sources": [
            {"file": CRITIC, "quote": "a paragraph over about three lines at 1440 px"},
            {"file": "configs/design/agents/design_homepage_craft_critic_v2.yaml", "quote": "measure 45-90 characters"},
            {"file": "configs/design/bin/design_measure.js", "quote": "x.chars_per_line > 90"},
            {"file": CRITIC, "quote": "2 = slows or confuses some visitors"},
        ],
    },
    "renamed_term": {
        "check": "drift", "targets": ["page"], "level": "3 in the hero or on a link or button, 2 elsewhere",
        "grade": "Must at 3, Should at 2",
        "rule": "a term from the deck's terms list missing from the page, while a near variant appears outside "
                "quotation marks: in the term's place in a deck sentence, or the term with one word other than its "
                "last changed, in a phrase the deck never writes",
        "sources": [
            {"file": CRITIC, "quote": "terms: one thing named two ways, or one word used for two things."},
            {"file": CRITIC, "quote": "drift (page only): the page departing from the approved deck in a way "
                                      "that hurts (headline not from the deck, a term renamed"},
            {"file": CRITIC, "quote": "3 = most visitors misread or stall (an unexplained label on the main path"},
            {"file": CRITIC, "quote": "2 = slows or confuses some visitors"},
        ],
    },
}

# ---------------------------------------------------------------- words

TOKEN = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*")  # words; hyphens, slashes and dots split them
NAME_TOKEN = re.compile(r"[^\W_]+(?:[-'\u2019][^\W_]+)*")  # words; a hyphenated word stays whole
NUMBER_WORDS = {w: str(n) for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
# Words that never count toward a name: short function words, pronouns, question words, days and months,
# generic acronyms and units, company suffixes, common website labels and emphasis words.
SMALL = frozenset("a an and as at but by for from in into nor of off on onto or out over per so than the to up "
                  "upon via vs with yet".split())
COMMON = SMALL | frozenset(NUMBER_WORDS) | frozenset((
    "i i'm i've i'll i'd me my mine we us our ours you your yours he him his she her hers they them their theirs "
    "it it's its this that these those who whom whose what which when where why how "
    "is are was were be been am do does did has have had can could may might must shall should will would "
    "isn't aren't don't doesn't didn't can't won't "
    "not no yes all any each every some more most many much few other another such own same only just also "
    "now new free here there today tomorrow tonight never always very first second third last "
    "above across after again against ahead along among around away back before behind below beside between "
    "beyond down during even ever except inside near outside past since still through together toward towards "
    "under until while within without "
    "monday tuesday wednesday thursday friday saturday sunday january february march april june july august "
    "september october november december "
    "faq faqs pdf csv url api pm ok id tv usb hd ai pin sms qr gps wi-fi wifi usd eur gbp "
    "inc ltd llc plc co gmbh "
    "about account blog careers contact cookies docs features help home login menu news plans policy pricing "
    "privacy service settings support terms"
).split())
# Lower-case words that may join the words of one name: "Bank of England", "Vincent van Gogh".
BRIDGES = frozenset("of de da di du la le van von der den".split())
QUESTION_WORDS = frozenset("how what why when where who which".split())
# A full stop after these does not end the sentence: "Dr. Ada Lovelace" is one name.
ABBREVIATION = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|St|Mt|Jr|Sr)\.$")
STOP = COMMON  # words that cannot carry a term on their own
QUOTE_TAGS = frozenset({"blockquote", "q"})
CONTROL_TAGS = frozenset({"a", "button"})
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "a", "button", "summary", "label", "legend",
                          "caption", "th", "dt", "option"})
CHROME = ("header", "nav", "footer", "menu")
# Section names the page text falls back to without a data-section: an h1 there does not mark a hero.
GENERIC_SECTIONS = frozenset({"page", "main", "section", "article", "aside", "body"})
NON_PARAGRAPH = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "a", "button", "summary", "label", "legend",
                           "caption", "th", "option", "select", "pre", "img alt"})
SENTENCE_END = re.compile(r"[.!?\u2026][\"'\u201d\u2019)]*\s*$")
SEGMENT_BREAK = re.compile(r"(?<=[.!?\u2026])\s+|:\s+|\n+|[\"\u201c\u201d\u00ab\u00bb\u2018]")


def clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def load_verbs(path: Path = VERBS_FILE) -> frozenset[str]:
    lines = [ln.strip() for ln in path.read_text().splitlines()]
    return frozenset(ln for ln in lines if ln and not ln.startswith("#"))


VERBS = load_verbs()


def _lower(word: str) -> str:
    w = word.lower().replace("\u2019", "'")
    return w[:-2] if w.endswith("'s") else w


def stem(word: str) -> str:
    """Lower case, no possessive, number words as digits, plural to singular (both sides alike)."""
    w = NUMBER_WORDS.get(_lower(word), _lower(word))
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("es") and w[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def tokens(text: str) -> list[str]:
    return [stem(m.group(0)) for m in TOKEN.finditer(text)]


def contains(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def verb_forms(word: str) -> set[str]:
    """The word and the base forms it may be inflected from (saves, saved, saving -> save)."""
    w = _lower(word)
    forms = {w}
    for end in ("s", "es", "d", "ed", "ing"):
        if w.endswith(end) and len(w) - len(end) >= 2:
            base = w[: -len(end)]
            forms |= {base, base + "e"}
            if len(base) > 2 and base[-1] == base[-2]:
                forms.add(base[:-1])  # shopping -> shop, planned -> plan
    return forms


def is_verb(word: str) -> bool:
    return bool(verb_forms(word) & VERBS)


def first_word(label: str) -> str | None:
    """The CTA's first word in the verb list's form: lower case, curly apostrophes made straight."""
    m = NAME_TOKEN.search(label)
    if not m or not any(c.isalpha() for c in m.group(0)):
        return None
    return m.group(0).lower().replace("\u2019", "'")


def starts_with_verb(label: str) -> bool:
    """The first word is on the list, or its part before an apostrophe or hyphen is ("Let's", "Sign-up")."""
    w = first_word(label)
    if w is None:
        return False
    return w in VERBS or w.split("'")[0] in VERBS or w.split("-")[0] in VERBS


# ---------------------------------------------------------------- inputs


PAGE_LINE = re.compile(r"^- \[([^\]]+)\] (.*)$")


def parse_page_md(raw: str) -> list[dict]:
    """[{section, tag, text}] from page-text.md: "- [tag] text" lines under "## section" headings."""
    lines: list[dict] = []
    section = "page"
    for row in raw.splitlines():
        if row.startswith("## "):
            section = clean(row[3:]) or "page"
            continue
        m = PAGE_LINE.match(row)
        if m:
            lines.append({"section": section, "tag": clean(m.group(1)), "text": clean(m.group(2))})
    return [ln for ln in lines if ln["text"]]


def read_page_text(path: Path) -> list[dict]:
    """[{section, tag, text}] from review/page-text.md or the runtime checks' raw.json (focus.text)."""
    path = Path(path)
    raw = path.read_text()
    if path.suffix != ".json":
        return parse_page_md(raw)
    value = json.loads(raw)
    items = value if isinstance(value, list) else ((value.get("focus") or {}).get("text") or [])
    lines = [{"section": clean(item.get("section")) or "page", "tag": clean(item.get("tag")),
              "text": clean(item.get("text"))} for item in items if isinstance(item, dict)]
    return [ln for ln in lines if ln["text"]]


def deck_visible(deck: dict) -> list[tuple[str, str]]:
    """The deck's visitor-facing texts (v2.deck_fields) plus its notices, which also reach the page."""
    out = [(p, t) for p, t in v2.deck_fields(deck) if clean(t)]
    for n in deck.get("notices") or []:
        if isinstance(n, dict) and clean(n.get("text")):
            out.append((f"notices.{n.get('id')}", clean(n.get("text"))))
    return out


def brief_texts(brief: dict) -> list[str]:
    """The brief's words a visitor's language comes from: facts, audience, category, purpose, CTA, disclosure."""
    out = [str(f) for f in brief.get("facts") or []]
    out += [str(brief.get(k)) for k in ("audience", "category", "purpose", "cta", "disclosure") if brief.get(k)]
    return out


# ---------------------------------------------------------------- calls to action


def label_text(label: str) -> str:
    """The CTA's words: spaces collapsed, arrows and other symbols at either end left out (icons, not words)."""
    text = clean(label)
    while text and unicodedata.category(text[0]).startswith("S"):
        text = text[1:].lstrip()
    while text and unicodedata.category(text[-1]).startswith("S"):
        text = text[:-1].rstrip()
    return text


def _cta_problems(label: str, primary: bool) -> list[dict]:
    text = label_text(label)
    out = []
    if len(text) > CTA_MAX_CHARS:
        out.append({"rule": "cta_length", "severity": 2,
                    "evidence": f"{len(text)} characters; A5 allows {CTA_MAX_CHARS} or fewer"})
    if not starts_with_verb(text):
        w = first_word(text)
        said = f"the first word '{w}' is not an action verb" if w else "it has no word"
        out.append({"rule": "cta_verb", "severity": 3 if primary else 2,
                    "evidence": f"{said} (configs/design/knowledge/cta-verbs.txt); A5 asks a call to action to "
                                f"start with a verb" + ("; this is the primary action" if primary else "")})
    return out


def deck_cta_findings(deck: dict) -> list[dict]:
    ctas = deck.get("ctas")
    if not isinstance(ctas, dict):
        return []
    out = []
    for key, label in ctas.items():
        if isinstance(label, str) and clean(label):
            for p in _cta_problems(label, primary=key == "primary"):
                out.append({**p, "field": f"ctas.{key}", "text": clean(label)})
    return out


def _content_words(text: str) -> set[str]:
    return {t for t in tokens(text) if t not in STOP and not t.isdigit()}


def _matches(label: str, ref: str) -> bool:
    """The page's control carries this CTA: it shares at least half of the CTA's content words."""
    want = _content_words(ref)
    return bool(want) and len(want & _content_words(label)) >= max(1, math.ceil(len(want) / 2))


def _inline(lines: list[dict], i: int) -> bool:
    """A link inside a sentence: its label starts in lower case, or the sentence goes on after it."""
    text = lines[i]["text"]
    if text[:1].islower():
        return True
    nxt = lines[i + 1] if i + 1 < len(lines) else None
    return bool(nxt and nxt["section"] == lines[i]["section"] and nxt["tag"] not in CONTROL_TAGS
                and re.match(r"[a-z,.;:!?)]", nxt["text"]))


def hero_section(lines: list[dict]) -> str | None:
    """The section of the first h1, when it is a named section (not a fallback like "page" or "main")."""
    section = next((ln["section"] for ln in lines if ln["tag"] == "h1"), None)
    return None if section is None or section.lower() in GENERIC_SECTIONS else section


def page_ctas(lines: list[dict], deck: dict, brief: dict) -> list[tuple[int, bool]]:
    """(line index, primary) for each line that counts as a call to action.

    A link or button outside the header, navigation and footer, not inside a sentence, not a question
    and not the product's name counts when it carries one of the deck's CTAs or the brief's, starts with
    an action verb, or sits in the hero (the section of the first h1, when it has a name of its own) and does
    not start with a question word ("How it works" there is a way to read on, not an action).
    """
    hero = hero_section(lines)
    ctas = deck.get("ctas") if isinstance(deck.get("ctas"), dict) else {}
    refs = [str(v) for v in ctas.values() if isinstance(v, str) and clean(v)]
    primary_refs = [str(r) for r in (ctas.get("primary"), brief.get("cta")) if isinstance(r, str) and clean(r)]
    refs += [r for r in primary_refs if r not in refs]
    product = tokens(str(brief.get("product", "")))
    found: list[tuple[int, bool, bool]] = []  # index, in hero, carries the primary
    for i, ln in enumerate(lines):
        text = ln["text"]
        if ln["tag"] not in CONTROL_TAGS or any(c in ln["section"].lower() for c in CHROME):
            continue
        if not re.search(r"[^\W\d_]", text) or text.rstrip().endswith("?") or _inline(lines, i):
            continue
        if product and tokens(text) == product:
            continue  # the logo or home link
        in_hero = hero is not None and ln["section"] == hero
        asks = (first_word(text) or "") in QUESTION_WORDS
        if (in_hero and not asks) or any(_matches(text, r) for r in refs) or starts_with_verb(text):
            found.append((i, in_hero, any(_matches(text, r) for r in primary_refs)))
    if not any(p for _, _, p in found):  # nothing carries the primary CTA: the hero's first one stands in
        first_hero = next((i for i, h, _ in found if h), None)
        return [(i, i == first_hero) for i, _, _ in found]
    return [(i, p) for i, _, p in found]


def page_cta_findings(lines: list[dict], deck: dict, brief: dict) -> list[dict]:
    out = []
    for i, primary in page_ctas(lines, deck, brief):
        for p in _cta_problems(lines[i]["text"], primary):
            out.append({**p, "line": i, "text": lines[i]["text"]})
    return out


# ---------------------------------------------------------------- proper names


def _camel(word: str) -> bool:
    return any(a.islower() and b.isupper() for a, b in zip(word, word[1:], strict=False))


def _counts_toward_name(word: str) -> bool:
    if len(word) < 2 or not word[0].isalpha() or not (word[0].isupper() or _camel(word)):
        return False
    low = _lower(word)
    if low in COMMON or ("-" in low and any(part in COMMON for part in low.split("-"))):
        return False
    return not is_verb(word)


def _title_case(segment: str, words: list[str]) -> bool:
    """A heading in title case: no closing stop, two or more words besides small ones, all capitalised."""
    if SENTENCE_END.search(segment):
        return False
    big = [w for w in words if w.lower() not in SMALL]
    return len(big) >= 2 and all(w[0].isupper() for w in big)


def _shouting(words: list[str]) -> bool:
    long = [w for w in words if sum(c.isalpha() for c in w) >= 2]
    return len(long) >= 2 and all(w.upper() == w for w in long)


def segments(text: str) -> list[tuple[str, bool]]:
    """(segment, ends at a colon): sentences and other runs of words that start fresh, after a stop, a colon,
    a line break or a quotation mark. A stop after Dr, Mr, St and the like does not end the sentence."""
    out: list[tuple[str, bool]] = []
    pos = 0
    for brk in SEGMENT_BREAK.finditer(text):
        if not brk.group(0).strip() and ABBREVIATION.search(text[:brk.start()]):
            continue
        out.append((text[pos:brk.start()], brk.group(0).startswith(":")))
        pos = brk.end()
    out.append((text[pos:], False))
    return [(s, label) for s, label in out if s.strip()]


def _runs(segment: str, words: list[re.Match]) -> list[list[int]]:
    """Indexes of the words in each run of name words; a bridge word joins two runs ("Bank of England")."""
    ws = [m.group(0) for m in words]

    def spaced(a: int, b: int) -> bool:  # only spaces between word a and word b
        return not segment[words[a].end():words[b].start()].strip()

    runs: list[list[int]] = []
    cur: list[int] = []
    k = 0
    while k < len(words):
        if _counts_toward_name(ws[k]):
            if cur and not spaced(cur[-1], k):
                runs.append(cur)
                cur = []
            cur.append(k)
            k += 1
            continue
        if cur and ws[k] in BRIDGES:
            nxt = k + 2 if k + 1 < len(words) and ws[k + 1] == "the" else k + 1
            if (nxt < len(words) and _counts_toward_name(ws[nxt])
                    and all(spaced(a, a + 1) for a in range(cur[-1], nxt))):
                cur.extend(range(k, nxt + 1))
                k = nxt + 1
                continue
        if cur:
            runs.append(cur)
        cur = []
        k += 1
    if cur:
        runs.append(cur)
    return runs


def name_runs(text: str, title_like: bool = False) -> list[str]:
    """Capitalised words and runs of them that may be proper names, in order of appearance.

    Left out: one capitalised word starting a sentence, segments in capitals only, and in a heading or label
    written in title case (title_like, or a label before a colon) every run that starts it (after any small
    words like "A") or has one word.
    """
    return [name for name, _ in name_runs_at(text, title_like)]


def _words(segment: str) -> list[re.Match]:
    return [m for m in NAME_TOKEN.finditer(segment) if any(c.isalpha() for c in m.group(0)) and not m.group(0)[0].isdigit()]


def name_runs_at(text: str, title_like: bool = False) -> list[tuple[str, str | None]]:
    """name_runs, each with what follows its first word when the run opens its sentence ("Shortest Cedar" ->
    "Cedar"), else None: a sentence's first word has a capital only because it opens the sentence, so it may
    be an ordinary word joined to a name (W4e screen, the v2.2 morrow deck and page)."""
    out: list[tuple[str, str | None]] = []
    for segment, label in segments(text):
        words = [m for m in NAME_TOKEN.finditer(segment)
                 if any(c.isalpha() for c in m.group(0)) and not m.group(0)[0].isdigit()]
        ws = [m.group(0) for m in words]
        if not words or _shouting(ws):
            continue
        title = (title_like or label) and _title_case(segment, ws)
        lead = next((k for k, w in enumerate(ws) if w.lower() not in SMALL), 0)
        for run in _runs(segment, words):
            named = [k for k in run if ws[k] not in BRIDGES and ws[k] != "the"]
            if title and (run[0] <= lead or len(named) < 2):
                continue
            if run[0] == 0 and len(named) == 1 and not _camel(ws[0]):
                continue
            name = segment[words[run[0]].start():words[run[-1]].end()]
            rest_at = list(run[1:])
            while rest_at and (ws[rest_at[0]] in BRIDGES or ws[rest_at[0]] == "the"):
                rest_at.pop(0)
            rest = (re.sub(r"['\u2019]s$", "", segment[words[rest_at[0]].start():words[run[-1]].end()])
                    if run[0] == 0 and rest_at and not _camel(ws[0]) else None)
            out.append((re.sub(r"['\u2019]s$", "", name), rest))
    return out


def source_names(sources: list[str]) -> set[tuple[str, ...]]:
    """Every run of capitalised words in the sources, wherever it stands (a sentence's first word too)."""
    out: set[tuple[str, ...]] = set()
    for s in sources:
        for segment, _ in segments(clean(s)):
            words = _words(segment)
            for run in _runs(segment, words):
                name = segment[words[run[0]].start():words[run[-1]].end()]
                out.add(tuple(tokens(re.sub(r"['\u2019]s$", "", name))))
    return out


def lowercase_stems(texts: list[str]) -> set[str]:
    """Every word written in lower case somewhere in these texts (stemmed)."""
    return {t for s in texts for m in NAME_TOKEN.finditer(s) if m.group(0).islower() for t in tokens(m.group(0))}


def name_findings(items: list[tuple[Any, str, bool]], sources: list[str], pool: list[str]) -> list[dict]:
    """One finding per name that no source contains. items are (where, text, title_like) in reading order;
    pool holds every text whose lower-case words show which capitalised words are common words."""
    source_tokens = [tokens(s) for s in sources if clean(s)]
    held = source_names(sources)
    lower = lowercase_stems(pool)

    def sourced(part: list[str]) -> bool:
        return any(contains(s, part) for s in source_tokens)

    seen: dict[tuple[str, ...], dict] = {}
    for where, text, title_like in items:
        for name, rest in name_runs_at(text, title_like):
            key = tuple(tokens(name))
            if not key or sourced(list(key)):
                continue
            if rest and tuple(tokens(rest)) in held:
                continue  # "Shortest Cedar is ...": a sentence opening on a word before a name the sources hold
            parts = [tokens(p) for p in re.split(r"\s+(?:of the|of|de|da|di|du|la|le|van|von|der|den)\s+", name)]
            if len(parts) > 1 and all(sourced(p) for p in parts):
                continue  # names the sources hold one by one: "Ada Lovelace of the Bank of England"
            named = [k for k in key if k not in BRIDGES and k != "the"]
            if named and all(k in lower for k in named):
                continue  # each word also written in lower case: common words with capitals, not a name
            if key in seen:
                seen[key]["also"].append(where)
                continue
            seen[key] = {"rule": "unsourced_name", "severity": 4, "where": where, "text": name, "also": []}
    return list(seen.values())


# ---------------------------------------------------------------- paragraphs


def paragraphs(lines: list[dict]) -> list[tuple[int, str]]:
    """(first line, text) of each body paragraph. The page text splits a paragraph at each link inside it
    ("[p] Read the", "[a] tide guide", "[p] before you go."); those pieces are joined again."""
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln["tag"] in NON_PARAGRAPH:
            i += 1
            continue
        text, j = ln["text"], i
        while (j + 2 < len(lines) and lines[j + 1]["tag"] == "a" and lines[j + 2]["tag"] == ln["tag"]
               and lines[j + 1]["section"] == ln["section"] == lines[j + 2]["section"]
               and (not SENTENCE_END.search(lines[j]["text"]) or re.match(r"[a-z,.;:!?)]", lines[j + 2]["text"]))):
            text = f"{text} {lines[j + 1]['text']} {lines[j + 2]['text']}"
            j += 2
        out.append((i, text))
        i = j + 1
    return out


def paragraph_findings(lines: list[dict]) -> list[dict]:
    out = []
    for i, text in paragraphs(lines):
        n = len(text)
        if n > PARAGRAPH_MAX_CHARS:
            lines_at = math.ceil(n / LINE_MAX_CHARS)
            out.append({"rule": "long_paragraph", "severity": 2, "line": i, "text": text,
                        "evidence": f"{n} characters: {lines_at} lines at 1440 px even at {LINE_MAX_CHARS} "
                                    f"characters a line (more than {PARAGRAPH_MAX_LINES})"})
    return out


# ---------------------------------------------------------------- terms


def clauses(text: str) -> list[str]:
    """Sentences, also split at a colon: a term's context does not run across "term: meaning"."""
    return [s for s in re.split(r"(?<=[.!?\u2026])\s+|:\s+|\n+", text) if s.strip()]


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    """Character spans inside quotation marks: double quotes, guillemets and a curly single pair."""
    spans = []
    for pat in (r"\u201c[^\u201d]*\u201d", r"\"[^\"]*\"", r"\u00ab[^\u00bb]*\u00bb", r"\u2018.*?\u2019(?![^\W\d_])"):
        spans += [(m.start(), m.end()) for m in re.finditer(pat, text)]
    return spans


def _line_words(line: dict) -> tuple[list[str], list[tuple[int, int]], list[bool]]:
    text = line["text"]
    spans = _quoted_spans(text)
    ms = list(TOKEN.finditer(text))
    quoted_line = line["tag"] in QUOTE_TAGS
    return ([stem(m.group(0)) for m in ms], [(m.start(), m.end()) for m in ms],
            [quoted_line or any(a <= m.start() < b for a, b in spans) for m in ms])


def _content(words: list[str]) -> bool:
    return any(w not in STOP and not w.isdigit() for w in words)


def _context_variants(term: list[str], deck_sents: list[list[str]], page: list[tuple]) -> list[tuple[int, int, int]]:
    """(line, word, length) of phrases that stand where the term stood in one of the deck's sentences.

    With words on both sides of the term in the deck, the page must keep at least one on each side and
    three in all; with words on one side only, two of them, and the phrase must share a word with the term.
    The kept words must include a content word; the phrase must have one too and be outside quotation marks.
    """
    found = []
    n = len(term)
    own = {w for w in term if w not in STOP and not w.isdigit()}
    for sent in deck_sents:
        for i in range(len(sent) - n + 1):
            if sent[i:i + n] != term:
                continue
            left, right = sent[max(0, i - 3):i], sent[i + n:i + n + 3]
            for li, (words, _, quoted) in enumerate(page):
                for j in range(len(words)):
                    lm = 0
                    while lm < len(left) and j - 1 - lm >= 0 and words[j - 1 - lm] == left[-1 - lm]:
                        lm += 1
                    if left and right and lm == 0:
                        continue
                    for m in range(1, n + 2):
                        if j + m > len(words):
                            break
                        rm = 0
                        while rm < len(right) and j + m + rm < len(words) and words[j + m + rm] == right[rm]:
                            rm += 1
                        x = words[j:j + m]
                        if left and right:
                            anchored = lm >= 1 and rm >= 1 and lm + rm >= 3
                        else:
                            anchored = lm + rm >= 2 and bool(set(x) & own)
                        if (not anchored or not _content(words[j - lm:j] + words[j + m:j + m + rm])
                                or contains(x, term) or any(quoted[j:j + m]) or not _content(x)):
                            continue
                        found.append((li, j, m))
                        break
    return found


def _form_variants(term: list[str], deck_sents: list[list[str]], page: list[tuple],
                   lines: list[dict]) -> list[tuple[int, int, int]]:
    """The term with one content word changed ("slack window" for "tide window"), outside quotation marks,
    where the deck never writes that phrase. The last word stays: a rename most often keeps it ("slack window"
    for "tide window", "law of thirds" for "rule of thirds"), while a phrase with another last word most often
    names another thing ("tide tables", "rule of twelfths"). The changed word is in lower case, or starts a
    sentence, a heading or a label; a capital inside a sentence is more likely a name."""
    n = len(term)
    if n < 2:
        return []
    head = n - 1
    found = []
    for li, (words, spans, quoted) in enumerate(page):
        text = lines[li]["text"]
        heading = lines[li]["tag"] in HEADING_TAGS
        for j in range(len(words) - n + 1):
            x = words[j:j + n]
            diff = [k for k in range(n) if x[k] != term[k]]
            if len(diff) != 1 or any(quoted[j:j + n]):
                continue
            k = diff[0]
            if k == head or not _content([x[k]]) or not _content([term[k]]) or any(contains(s, x) for s in deck_sents):
                continue
            a, b = spans[j + k]
            word = text[a:b]
            start = j + k == 0 or bool(re.search(r"[.!?:\u2026\"\u201c]", text[spans[j + k - 1][1]:a]))
            if word.islower() or ((heading or start) and word[1:].islower()):
                found.append((li, j, n))
    return found


def term_findings(lines: list[dict], deck: dict) -> list[dict]:
    terms = [clean(t.get("term")) for t in deck.get("terms") or [] if isinstance(t, dict) and clean(t.get("term"))]
    page = [_line_words(ln) for ln in lines]
    deck_sents = [tokens(c) for _, t in deck_visible(deck) for c in clauses(t)]
    hero = hero_section(lines)
    out = []
    for term in terms:
        tn = tokens(term)
        if not tn or any(contains(words, tn) for words, _, _ in page):
            continue  # on the page, inside quotation marks or not
        hits = sorted(set(_context_variants(tn, deck_sents, page)) | set(_form_variants(tn, deck_sents, page, lines)))
        covered: set[tuple[int, int]] = set()
        seen: dict[tuple[str, ...], dict] = {}
        for li, j, m in hits:
            if any((li, w) in covered for w in range(j, j + m)):
                continue  # overlaps a phrase already taken
            covered |= {(li, w) for w in range(j, j + m)}
            words, spans, _ = page[li]
            phrase = lines[li]["text"][spans[j][0]:spans[j + m - 1][1]]
            ln = lines[li]
            main = (hero is not None and ln["section"] == hero) or ln["tag"] in CONTROL_TAGS
            entry = seen.setdefault(tuple(words[j:j + m]), {"phrase": phrase, "lines": [], "main": False})
            if li not in entry["lines"]:
                entry["lines"].append(li)
            entry["main"] = entry["main"] or main
        if not seen:
            continue
        variants = list(seen.values())
        first = variants[0]
        others = [f"'{v['phrase']}'" for v in variants[1:]]
        out.append({"rule": "renamed_term", "severity": 3 if any(v["main"] for v in variants) else 2,
                    "line": first["lines"][0], "text": first["phrase"], "term": term,
                    "also_lines": [li for v in variants for li in v["lines"]][1:],
                    "evidence": f"the deck's term '{term}' is not on the page; '{first['phrase']}' stands in its place"
                                + (f" (also {', '.join(others)})" if others else "")})
    return out


# ---------------------------------------------------------------- reports


def _grade(rule: str, level: int) -> str:
    if rule in ("cta_length", "cta_verb", "unsourced_name") or level >= 3:
        return "Must"
    return "Should" if level == 2 else "Could"


def _finish(target: str, findings: list[tuple[int, dict]]) -> dict:
    """Order the findings (reading order, then rule, then text), give them ids and count them."""
    ordered = [f for _, f in sorted(findings, key=lambda pf: (pf[0], RULE_ORDER.index(pf[1]["rule"]), pf[1]["text"]))]
    per_rule: dict[str, int] = {}
    for f in ordered:
        per_rule[f["rule"]] = per_rule.get(f["rule"], 0) + 1
        f.update({"id": f"{target}-{f['rule']}-{per_rule[f['rule']]}", "target": target, "kind": "word",
                  "check": RULES[f["rule"]]["check"], "grade": _grade(f["rule"], f["severity"])})
    return {"version": VERSION, "target": target,
            "limits": {"cta_max_chars": CTA_MAX_CHARS, "paragraph_max_chars": PARAGRAPH_MAX_CHARS,
                       "paragraph_max_lines": PARAGRAPH_MAX_LINES, "line_max_chars": LINE_MAX_CHARS,
                       "cta_verbs": len(VERBS)},
            "counts": {g: sum(1 for f in ordered if f["grade"] == g) for g in ("Must", "Should", "Could")},
            "findings": ordered}


def _title_field(path: str) -> bool:
    return path.startswith(("headlines[", "ctas.")) or path.endswith(".title")


def check_deck(deck: dict, brief: dict) -> dict:
    """Findings on a copy deck (copy.json) against its brief (brief.json): the copy_review node's part."""
    if not isinstance(deck, dict):
        raise ValueError("copy.json is not an object")
    fields = [(p, t) for p, t in v2.deck_fields(deck) if clean(t)]
    order = {p: i for i, (p, _) in enumerate(fields)}
    sources = [str(f) for f in brief.get("facts") or []] + [str(brief.get("product", ""))]
    pool = [t for _, t in deck_visible(deck)] + brief_texts(brief)
    findings: list[tuple[int, dict]] = []
    for f in deck_cta_findings(deck):
        findings.append((order.get(f["field"], len(order)), f))
    for f in name_findings([(p, t, _title_field(p)) for p, t in fields], sources, pool):
        where, also = f.pop("where"), f.pop("also")
        evidence = "not in the brief's facts or the product name"
        if also:
            evidence += f"; also in {', '.join(also)}"
        findings.append((order[where], {**f, "field": where, "evidence": evidence}))
    return _finish("deck", findings)


def _element(line: dict) -> str:
    return f"{line['section']} [{line['tag']}]"


def check_page(lines: list[dict], deck: dict, brief: dict) -> dict:
    """Findings on the built page's text (page-text.md lines) against the approved deck and the brief:
    the content node's part."""
    if not isinstance(deck, dict):
        raise ValueError("copy.json is not an object")
    deck_texts = [t for _, t in deck_visible(deck)]
    sources = [str(f) for f in brief.get("facts") or []] + [str(brief.get("product", ""))] + deck_texts
    pool = [ln["text"] for ln in lines] + deck_texts + brief_texts(brief)
    findings: list[tuple[int, dict]] = []
    first_cta: dict[tuple[str, str], dict] = {}
    for f in page_cta_findings(lines, deck, brief) + paragraph_findings(lines) + term_findings(lines, deck):
        i = f.pop("line")
        also_lines = f.pop("also_lines", None)
        f = {**f, "element": _element(lines[i]), "line": i + 1}
        if also_lines:
            f["evidence"] += "; also at " + ", ".join(f"line {li + 1} ({_element(lines[li])})" for li in also_lines)
        if f["rule"] in ("cta_length", "cta_verb"):  # the same label on several lines: one finding
            key = (f["rule"], f["text"].lower())
            if key in first_cta:
                first = first_cta[key]
                first["severity"] = max(first["severity"], f["severity"])
                first["evidence"] += f"; also at line {f['line']} ({f['element']})"
                continue
            first_cta[key] = f
        findings.append((i, f))
    items = [(i, ln["text"], ln["tag"] in HEADING_TAGS) for i, ln in enumerate(lines)]
    for f in name_findings(items, sources, pool):
        i, also = f.pop("where"), f.pop("also")
        evidence = "not in the brief's facts, the product name or the approved deck"
        if also:
            evidence += "; also at " + ", ".join(f"line {li + 1} ({_element(lines[li])})" for li in also)
        findings.append((i, {**f, "element": _element(lines[i]), "line": i + 1, "evidence": evidence}))
    return _finish("page", findings)


def dump(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="target", required=True)
    for name in ("deck", "page"):
        p = sub.add_parser(name)
        if name == "page":
            p.add_argument("--text", required=True, type=Path, help="review/page-text.md or runtime raw.json")
        p.add_argument("--copy", required=True, type=Path, help="homepage/copy/copy.json")
        p.add_argument("--brief", required=True, type=Path, help="brief.json")
        p.add_argument("--out", type=Path, help="write the report here (default: stdout)")
    args = ap.parse_args(argv)
    try:
        deck = json.loads(args.copy.read_text())
        brief = json.loads(args.brief.read_text())
        if not isinstance(brief, dict):
            raise ValueError("brief.json is not an object")
        report = check_deck(deck, brief) if args.target == "deck" else check_page(read_page_text(args.text), deck, brief)
    except (OSError, ValueError) as e:
        print(f"design_word_checks: {e}", file=sys.stderr)
        return 2
    text = dump(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
