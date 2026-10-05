#!/usr/bin/env python3
"""positioning_grade checker (Product marketing): the deterministic half of the grade of one
positioning document (FORMAT.md, positioning/1) and the verifier of the semantic review.
Rubric: rubric.md next to this file (positioning_grade/1). Standard library only. Run from the
run workspace.

    check_positioning.py check --doc FILE [--json FILE] --evidence DIR
        Check the document against the format and its evidence with no model: the sections and
        their order, the label lines, the hierarchy's shape, every citation's file and verbatim
        quote, the numbers in cited lines, hype words, sentence length, and positioning.json
        against section 6. List the leads the review must resolve. Writes
        state/positioning_grade/check.json and check.md.
    check_positioning.py verify [--dry-run]
        Verify the review (state/positioning_grade/review.json): a finding counts only when every
        passage it cites is verbatim in the file it names and one passage is from the document; a
        lead is resolved only with a note or a counted finding. Merge it with the checker's
        findings into pass / revise / unknown per criterion P1-P8 and overall, and write
        quality.json and quality.md. --dry-run only prints what would not verify.
    check_positioning.py passage FILE TEXT
        Whether TEXT is in FILE as the verifier reads it.
    check_positioning.py lint --doc FILE [--json FILE] --evidence DIR
        Print the checker's findings and leads for a document; write nothing.

The grade never rewrites the document: it hashes the document, positioning.json and the
evidence when it checks and again when it verifies.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRADE_DIR = Path("state/positioning_grade")
RUBRIC_VERSION = "positioning_grade/1"
FORMAT_VERSION = "positioning/1"
CRITERIA = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")
CRITERION_NAMES = {
    "P1": "Competitive alternatives are what best-fit users really do instead",
    "P2": "Unique attributes are true today",
    "P3": "Each attribute leads to a value, with the strongest proof",
    "P4": "One specific best-fit segment and why it cares",
    "P5": "Market category style named and making the value obvious",
    "P6": "Messaging hierarchy shape; pillars are benefits",
    "P7": "Every claim traced to a quote that resolves, numbers match, limits stated",
    "P8": "Plain words",
}
SECTIONS = (
    ("1", "Competitive alternatives", "P1"),
    ("2", "Unique attributes", "P2"),
    ("3", "Value and proof", "P3"),
    ("4", "Best-fit customers", "P4"),
    ("5", "Market category", "P5"),
    ("6", "Messaging hierarchy", "P6"),
    ("7", "What it doesn't do", "P7"),
    ("8", "Assumptions and open questions", "P7"),
)
SECTION_CRITERION = {number: criterion for number, _, criterion in SECTIONS}
STYLES = ("head-to-head", "subsegment", "new category")
MAX_WORDS = 30
PILLARS = (3, 4)
PROOFS = (3, 5)
LEAD_CAP = 40
MAX_EVIDENCE_BYTES = 1_000_000
USAGE_LIMIT = re.compile(r"hit your (?:session|usage) limit|usage limit reached|rate limit exceeded", re.I)

# ---- text --------------------------------------------------------------------------------------

TYPO = str.maketrans({
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2018": "'", "\u2019": "'", "\u2032": "'",
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2011": "-", "\u2010": "-",
    "\u00a0": " ", "\u2009": " ", "\u202f": " ",
})


def flat(text: str) -> str:
    """Text as the verifier compares it: typographic quotes and dashes made plain, markdown
    emphasis and code marks removed, whitespace collapsed. Case is kept."""
    text = str(text).translate(TYPO).replace("\u2026", "...")
    text = re.sub(r"[*`]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def low(text: str) -> str:
    return flat(text).lower()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clip(text: str, n: int = 260) -> str:
    text = flat(text)
    return text if len(text) <= n else text[: n - 3] + "..."


class Doc:
    """One file: its lines, its flattened lower-case text and where each line starts in it."""

    def __init__(self, path: str, text: str):
        self.path = path
        self.lines = text.split("\n")
        self.starts: list[int] = []
        pos = 0
        parts = []
        for line in self.lines:
            line_flat = low(line)
            self.starts.append(pos)
            parts.append(line_flat)
            pos += len(line_flat) + 1
        self.lower = " ".join(parts)

    def line_at(self, offset: int) -> int:
        """1-based line number of an offset into the flattened text."""
        return bisect.bisect_right(self.starts, offset)

    def locate(self, passage: str) -> tuple[int | None, bool]:
        """(1-based line where the passage starts or None, whether it matched only by skipping
        text at '...'). Case and whitespace don't matter. Each part kept around a '...' needs at
        least three words, and the parts must appear in order."""
        wanted = low(passage).strip(" \"'")
        if not wanted:
            return None, False
        at = self.lower.find(wanted)
        if at >= 0:
            return self.line_at(at), False
        parts = [p.strip(" \"'") for p in wanted.split("...")]
        parts = [p for p in parts if p]
        if len(parts) < 2 or any(len(p.split()) < 3 for p in parts):
            return None, False
        pos, first = 0, None
        for part in parts:
            at = self.lower.find(part, pos)
            if at < 0:
                return None, False
            first = at if first is None else first
            pos = at + len(part)
        return self.line_at(first if first is not None else 0), True

    def find(self, passage: str) -> int | None:
        return self.locate(passage)[0]


# ---- numbers -----------------------------------------------------------------------------------

NUMBER = re.compile(r"(?<![\w.])[$\u20ac\u00a3]?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:%|x\b|k\b)?(?![\w])")
WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "thousand": 1000, "dozen": 12,
}
NUMBER_WORD = re.compile(r"\b(" + "|".join(WORDS) + r")\b", re.I)


def number_key(whole: str, fraction: str | None) -> str:
    value = str(int(whole.replace(",", "")))
    digits = (fraction or ".")[1:].rstrip("0")
    return f"{value}.{digits}" if digits else value


def numbers_in(text: str, words: bool = False) -> list[str]:
    """The numbers in a text, normalised (1,200 -> 1200, 7.90 -> 7.9, $49 -> 49, 12% -> 12)."""
    found = [number_key(m.group(1), m.group(2)) for m in NUMBER.finditer(flat(text))]
    if words:
        found += [str(WORDS[m.group(1).lower()]) for m in NUMBER_WORD.finditer(text)]
    return found


# ---- the document ------------------------------------------------------------------------------

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SECTION_HEADING = re.compile(r"^(\d+)\s*[.)]\s*(.+)$")
PILLAR_HEADING = re.compile(r"^pillar\s+(\d+)\s*[:.-]\s*(.*)$", re.I)
CITATION = re.compile(r'\[\s*([^\[\]":]+?)\s*:\s*"(.*?)"\s*\]')
TAG = re.compile(r"\(\s*assumption\s*\)", re.I)
LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
LABEL = re.compile(r"^\s*(?:[-*+]\s+)?(segment|style|category|reason|evidence)\s*:\s*(.*)$", re.I)
INLINE_QUOTE = re.compile(r'"[^"]*"')
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def claim_text(line: str) -> str:
    """A line as the claim it makes: no citations, no assumption tag, no list mark."""
    text = CITATION.sub(" ", line.translate(TYPO))
    text = TAG.sub(" ", text)
    text = LIST_MARK.sub("", text)
    return flat(text)


def sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_END.split(flat(text)) if s.strip()]


def word_count(sentence: str) -> int:
    return len([w for w in sentence.split() if re.search(r"[A-Za-z0-9]", w)])


def hype_words(rubric_text: str) -> list[str]:
    """The list under '## Hype words' in the rubric, one '- word' per line."""
    words, inside = [], False
    for line in rubric_text.split("\n"):
        if line.startswith("## "):
            inside = line.strip().lower() == "## hype words"
            continue
        if inside:
            m = re.match(r"^\s*-\s+(\S.*?)\s*$", line)
            if m:
                words.append(m.group(1).lower())
    return words


def hype_pattern(words: list[str]) -> re.Pattern | None:
    if not words:
        return None
    alternatives = sorted({r"[-\s]?".join(re.escape(part) for part in re.split(r"[-\s]+", w)) for w in words},
                          key=len, reverse=True)
    return re.compile(r"(?<![\w-])(" + "|".join(alternatives) + r")(?![\w-])", re.I)


def parse_document(text: str) -> dict:
    """Split the document into its title, sections and lines; classify each line."""
    title = None
    sections: list[dict] = []
    lines: list[dict] = []
    current = "0"
    sub = None  # within section 6: "vp", ("pillar", index) or None
    pillars: list[dict] = []
    vp: dict = {"heading_line": None, "lines": []}
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.translate(TYPO).rstrip()
        if not line.strip():
            continue
        heading = HEADING.match(line)
        record = {"n": n, "raw": raw.rstrip(), "flat": flat(raw), "section": current}
        if heading:
            level, words = len(heading.group(1)), heading.group(2).strip()
            record.update(kind="heading", level=level, text=flat(words))
            if level == 1 and title is None and current == "0":
                record["kind"] = "title"
                title = {"n": n, "text": flat(words)}
            elif level == 2:
                m = SECTION_HEADING.match(words)
                number = m.group(1) if m else None
                current = number if number in SECTION_CRITERION else "?"
                sections.append({"n": n, "text": flat(words), "number": number,
                                 "title": flat(m.group(2)) if m else flat(words)})
                record.update(kind="section", section=current)
                sub = None
            elif level == 3 and current == "6":
                pm = PILLAR_HEADING.match(words)
                if words.strip().lower() == "value proposition":
                    record["kind"] = "vp_heading"
                    vp["heading_line"] = n
                    sub = "vp"
                elif pm:
                    record["kind"] = "pillar_heading"
                    pillars.append({"n": n, "number": int(pm.group(1)), "benefit": flat(pm.group(2)),
                                    "raw": record["raw"], "proofs": []})
                    sub = ("pillar", len(pillars) - 1)
                else:
                    record["kind"] = "stray_heading"
                    sub = None
            lines.append(record)
            continue
        label = LABEL.match(line)
        name = label.group(1).lower() if label else None
        citations = [{"file": m.group(1).strip(), "quote": m.group(2)} for m in CITATION.finditer(line)]
        text_of_claim = claim_text(line)
        tagged = bool(TAG.search(line))
        record.update(citations=citations, assumption=tagged, text=text_of_claim)
        exempt_label = (name == "evidence" and current == "0") or (name == "segment" and current == "4") or (
            name in ("style", "category") and current == "5")
        if exempt_label:
            record.update(kind="label", label=name, value=flat(label.group(2)) if label else "")
        else:
            record["kind"] = "claim"
            if name == "reason" and current == "5":
                record["label"] = "reason"
                record["value"] = claim_text(label.group(2)) if label else text_of_claim
            if current == "6":
                if sub == "vp":
                    record["role"] = "value_proposition"
                    vp["lines"].append(record)
                elif isinstance(sub, tuple):
                    record["role"] = "proof_point"
                    pillars[sub[1]]["proofs"].append(record)
        lines.append(record)
    return {"title": title, "sections": sections, "lines": lines, "vp": vp, "pillars": pillars}


def product_of(title: dict | None) -> str:
    if not title:
        return ""
    return re.sub(r"\s+positioning\s*$", "", title["text"], flags=re.I).strip()


# ---- evidence ----------------------------------------------------------------------------------

LIMIT = re.compile(
    r"\b(?:not|no|none|cannot|can't|don't|doesn't|isn't|aren't|won't|without|only|planned|plan to|"
    r"coming|roadmap|beta|later this year|must|requires?|limited|weak|unless)\b", re.I)
QUESTION = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?q\s*:", re.I)


def load_evidence(folder: Path) -> tuple[dict[str, Doc], list[str]]:
    """Every readable file under the evidence folder, by its path inside the folder."""
    docs: dict[str, Doc] = {}
    problems = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        if path.stat().st_size > MAX_EVIDENCE_BYTES:
            problems.append(f"evidence file {rel} is over {MAX_EVIDENCE_BYTES} bytes and was not read")
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            problems.append(f"evidence file {rel} is not readable text")
            continue
        docs[rel] = Doc(rel, text)
    return docs, problems


def evidence_key(name: str, evidence: dict[str, Doc], evidence_dir: str) -> str | None:
    """The evidence file a citation names: its path inside the folder (a leading ./ or the
    folder's own path is tolerated)."""
    name = name.strip().replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    if name.startswith("/") or ".." in name.split("/"):
        return None
    if name in evidence:
        return name
    prefix = evidence_dir.rstrip("/") + "/"
    if evidence_dir not in ("", ".") and name.startswith(prefix) and name[len(prefix):] in evidence:
        return name[len(prefix):]
    tail = Path(evidence_dir).name + "/"
    if name.startswith(tail) and name[len(tail):] in evidence:
        return name[len(tail):]
    return None


def limit_statements(evidence: dict[str, Doc]) -> list[dict]:
    """Evidence sentences that state a limit, a requirement or a plan: what the review checks the
    document's attributes and section 7 against."""
    found = []
    for rel, doc in evidence.items():
        for n, line in enumerate(doc.lines, 1):
            if not line.strip() or line.lstrip().startswith("#") or QUESTION.match(line):
                continue  # headings and an interviewer's questions state no limit
            for sentence in sentences(line):
                if LIMIT.search(sentence):
                    found.append({"file": rel, "line": n, "text": clip(sentence, 300)})
    return found


# ---- the check ---------------------------------------------------------------------------------


def finding(fid: str, criterion: str, kind: str, line: dict | None, problem: str, doc_path: str,
            claim: str | None = None) -> dict:
    passages = [{"file": doc_path, "text": line["flat"], "line": line["n"]}] if line else []
    return {"id": fid, "criterion": criterion, "kind": kind, "severity": "material", "source": "checker",
            "claim": claim if claim is not None else (line["flat"] if line else ""), "problem": problem,
            "passages": passages, "verified": True}


def run_check(doc_path: Path, json_path: Path, evidence_dir: Path) -> dict:
    doc_text = doc_path.read_text(errors="replace")
    parsed = parse_document(doc_text)
    evidence, problems = load_evidence(evidence_dir)
    if not evidence:
        problems.append(f"the evidence folder {evidence_dir} holds no readable files")
    rubric_path = HERE / "rubric.md"
    hype = hype_pattern(hype_words(rubric_path.read_text())) if rubric_path.is_file() else None
    if hype is None:
        problems.append("no hype word list: rubric.md is missing next to the checker or has no '## Hype words'")
    doc_name = str(doc_path)
    ev_name = str(evidence_dir)
    findings: list[dict] = []
    leads: list[dict] = []

    def add(criterion, kind, line, problem, claim=None):
        findings.append(finding(f"S{len(findings) + 1}", criterion, kind, line, problem, doc_name, claim))

    lines = parsed["lines"]
    by_n = {r["n"]: r for r in lines}
    title = parsed["title"]
    anchor = by_n[title["n"]] if title else next(iter(lines), None)

    # Title and sections.
    if not title:
        add("P6", "no_title", anchor, "the document has no '# <Product> positioning' title line")
    seen: dict[str, dict] = {}
    order = []
    for s in parsed["sections"]:
        record = by_n[s["n"]]
        if s["number"] not in SECTION_CRITERION:
            add("P6", "unexpected_section", record, f"'{s['text']}' is not one of the eight sections of FORMAT.md")
            continue
        criterion = SECTION_CRITERION[s["number"]]
        expected = dict((n, t) for n, t, _ in SECTIONS)[s["number"]]
        if s["number"] in seen:
            add(criterion, "duplicate_section", record, f"section {s['number']} appears twice")
            continue
        seen[s["number"]] = s
        order.append(s["number"])
        if low(s["title"]) != low(expected):
            add(criterion, "section_title", record, f"section {s['number']} should be titled '{expected}'")
    for number, name, criterion in SECTIONS:
        if number not in seen:
            add(criterion, "missing_section", anchor, f"section {number} '{name}' is missing")
    if order != sorted(order, key=int):
        first_wrong = next(n for i, n in enumerate(order) if i and int(n) < int(order[i - 1]))
        add(SECTION_CRITERION[first_wrong], "section_order", by_n[seen[first_wrong]["n"]],
            f"the sections are out of order: {', '.join(order)}")

    claims = [r for r in lines if r["kind"] == "claim"]
    for number, name, criterion in SECTIONS[:7]:
        if number in seen and not [r for r in claims if r["section"] == number]:
            if number == "6":
                continue  # the hierarchy's own checks below say what is missing
            add(criterion, "empty_section", by_n[seen[number]["n"]], f"section {number} '{name}' says nothing")

    # Label lines.
    segment = [r for r in lines if r.get("label") == "segment"]
    if "4" in seen:
        if not segment:
            add("P4", "no_segment_line", by_n[seen["4"]["n"]], "section 4 has no 'Segment:' line")
        elif len(segment) > 1:
            add("P4", "several_segments", segment[1], "section 4 has more than one 'Segment:' line")
        elif not segment[0]["value"]:
            add("P4", "empty_segment", segment[0], "the 'Segment:' line is empty")
    if "5" in seen:
        heading5 = by_n[seen["5"]["n"]]
        style = [r for r in lines if r.get("label") == "style"]
        category = [r for r in lines if r.get("label") == "category"]
        reason = [r for r in lines if r.get("label") == "reason"]
        if len(style) != 1:
            add("P5", "style_line", style[1] if style else heading5, "section 5 needs exactly one 'Style:' line")
        elif low(style[0]["value"]).rstrip(".") not in STYLES:
            add("P5", "style_value", style[0], "Style must be head-to-head, subsegment or new category")
        if len(category) != 1 or not category[0]["value"]:
            add("P5", "category_line", category[1] if len(category) > 1 else heading5,
                "section 5 needs exactly one non-empty 'Category:' line")
        if not reason:
            add("P5", "no_reason", heading5, "section 5 has no 'Reason:' line")

    # Every claim line ends with its source; citations resolve; numbers match their quotes.
    elided_leads = []
    for r in claims:
        if r["section"] == "8":
            pass
        elif not r["citations"] and not r["assumption"]:
            add("P7", "uncited", r, "the line cites no evidence and is not marked (assumption)")
        quote_numbers: set[str] = set()
        for c in r["citations"]:
            key = evidence_key(c["file"], evidence, ev_name)
            quote_numbers.update(numbers_in(c["quote"], words=True))
            c["resolved_file"] = key
            if key is None:
                c["line"] = None
                add("P7", "missing_file", r, f"cites {c['file']}, which is not in the evidence folder {ev_name}")
                continue
            if not c["quote"].strip():
                c["line"] = None
                add("P7", "empty_quote", r, f"a citation of {c['file']} has an empty quote")
                continue
            line_no, elided = evidence[key].locate(c["quote"])
            c["line"] = line_no
            c["elided"] = elided
            if line_no is None:
                add("P7", "quote_not_found", r, f"the quote \"{clip(c['quote'], 160)}\" is not in {c['file']}")
            elif elided:
                elided_leads.append({"criterion": "P7", "type": "elided_quote", "file": f"{ev_name}/{key}",
                                     "line": line_no, "doc_line": r["n"],
                                     "text": f"doc line {r['n']} quotes {key} with words skipped: \"{clip(c['quote'], 220)}\" "
                                             "- do the skipped words change what the quote says?"})
        if r["citations"] and not r["assumption"]:
            missing = sorted({x for x in numbers_in(r["text"]) if x not in quote_numbers}, key=lambda x: float(x))
            if missing:
                add("P7", "number_mismatch", r,
                    f"the number(s) {', '.join(missing)} in this line appear in none of its quotes")

    # Plain words: hype words outside quotes, sentence length.
    for r in lines:
        if r["kind"] in ("title", "section"):
            continue
        words_text = INLINE_QUOTE.sub(" ", r.get("text", ""))
        if r["kind"] == "label":
            words_text = INLINE_QUOTE.sub(" ", r.get("value", ""))
        if hype:
            hits = sorted({m.group(1).lower() for m in hype.finditer(words_text)})
            if hits:
                add("P8", "hype_word", r, f"hype word(s) outside a quote: {', '.join(hits)}")
        if r["kind"] in ("claim", "label"):
            long_ones = [s for s in sentences(r.get("text", "")) if word_count(s) > MAX_WORDS]
            if long_ones:
                add("P8", "long_sentence", r,
                    f"a sentence of {word_count(long_ones[0])} words (at most {MAX_WORDS}, citations not counted)")

    # The messaging hierarchy.
    vp, pillars = parsed["vp"], parsed["pillars"]
    heading6 = by_n[seen["6"]["n"]] if "6" in seen else anchor
    for r in lines:
        if r["kind"] == "stray_heading":
            add("P6", "stray_heading", r, "section 6 holds only '### Value proposition' and '### Pillar N: <benefit>' headings")
    if vp["heading_line"] is None:
        add("P6", "no_value_proposition", heading6, "section 6 has no '### Value proposition'")
    elif len(vp["lines"]) != 1:
        add("P6", "value_proposition_lines", by_n[vp["heading_line"]],
            f"the value proposition is {len(vp['lines'])} lines; it is one sentence on one line")
    elif len(sentences(vp["lines"][0]["text"])) != 1:
        add("P6", "value_proposition_sentences", vp["lines"][0], "the value proposition is more than one sentence")
    if "6" in seen:
        if not PILLARS[0] <= len(pillars) <= PILLARS[1]:
            add("P6", "pillar_count", heading6, f"{len(pillars)} pillars; the hierarchy has {PILLARS[0]} or {PILLARS[1]}")
        if [p["number"] for p in pillars] != list(range(1, len(pillars) + 1)):
            add("P6", "pillar_numbering", by_n[pillars[0]["n"]] if pillars else heading6,
                "pillars are numbered 1, 2, 3 (and 4) in order")
        for p in pillars:
            if not p["benefit"]:
                add("P6", "empty_pillar", by_n[p["n"]], "a pillar heading names no benefit")
            if not PROOFS[0] <= len(p["proofs"]) <= PROOFS[1]:
                add("P6", "proof_count", by_n[p["n"]],
                    f"pillar {p['number']} has {len(p['proofs'])} proof points; it needs {PROOFS[0]} to {PROOFS[1]}")

    # positioning.json mirrors section 6.
    mirror = json_mirror(json_path, parsed, product_of(title))
    for problem, line_no in mirror:
        add("P6", "json_mismatch", by_n.get(line_no) if line_no else heading6, problem)

    # Leads: elided quotes, then the evidence's limits and plans.
    limits = limit_statements(evidence)
    for item in elided_leads:
        leads.append(item)
    for item in limits[:LEAD_CAP]:
        leads.append({"criterion": "P7", "type": "evidence_limit", "file": f"{ev_name}/{item['file']}",
                      "line": item["line"], "doc_line": None,
                      "text": f"{item['file']}:{item['line']} \"{item['text']}\" - does the document contradict "
                              "it, or leave out a limit a reader would assume away?"})
    for i, lead in enumerate(leads, 1):
        lead["id"] = f"L{i}"
    more_limits = limits[LEAD_CAP:]

    files = {"doc": doc_name, "json": str(json_path), "evidence": ev_name,
             "evidence_files": [f"{ev_name}/{k}" for k in evidence]}
    hashes = {doc_name: sha(doc_path)}
    if json_path.is_file():
        hashes[str(json_path)] = sha(json_path)
    for k in evidence:
        hashes[f"{ev_name}/{k}"] = sha(evidence_dir / k)
    checker = Path(__file__).resolve()
    return {
        "version": "positioning_grade_check/1", "rubric": RUBRIC_VERSION, "format": FORMAT_VERSION,
        "rubric_sha256": sha(rubric_path) if rubric_path.is_file() else None,
        "format_sha256": sha(HERE / "FORMAT.md") if (HERE / "FORMAT.md").is_file() else None,
        "checker_sha256": sha(checker), "status": "checked", "files": files, "hashes": hashes,
        "product": product_of(title),
        "sections": [{k: s[k] for k in ("n", "number", "title")} for s in parsed["sections"]],
        "hierarchy": {"value_proposition": [r["n"] for r in vp["lines"]],
                      "pillars": [{"n": p["n"], "number": p["number"], "benefit": p["benefit"],
                                   "proofs": [r["n"] for r in p["proofs"]]} for p in pillars]},
        "segment": segment[0]["value"] if segment else None,
        "claims": [{k: r.get(k) for k in ("n", "section", "text", "citations", "assumption", "role", "label")}
                   for r in claims],
        "findings": findings, "leads": leads, "more_limits": more_limits, "unknown": {}, "problems": problems,
    }


def citation_key(c: dict) -> tuple[str, str]:
    return (flat(c.get("file", "")).lstrip("./"), low(c.get("quote", "")))


def json_mirror(json_path: Path, parsed: dict, product: str) -> list[tuple[str, int | None]]:
    """Where positioning.json differs from section 6: (problem, document line or None)."""
    vp, pillars = parsed["vp"], parsed["pillars"]
    if not json_path.is_file():
        return [(f"{json_path} is missing: it mirrors section 6", None)]
    try:
        data = json.loads(json_path.read_text())
    except ValueError as exc:
        return [(f"{json_path} is not valid JSON ({exc})", None)]
    if not isinstance(data, dict):
        return [(f"{json_path} is not a JSON object", None)]
    out: list[tuple[str, int | None]] = []
    if data.get("format") not in (None, FORMAT_VERSION):
        out.append((f"positioning.json format is {data.get('format')!r}, not {FORMAT_VERSION}", None))
    if product and low(str(data.get("product", ""))) != low(product):
        out.append((f"positioning.json product {data.get('product')!r} is not the title's {product!r}",
                    parsed["title"]["n"] if parsed["title"] else None))

    def same(item, record, what) -> None:
        if not isinstance(item, dict):
            out.append((f"positioning.json {what} is not an object", record["n"]))
            return
        if low(str(item.get("text", ""))) != low(record["text"]):
            out.append((f"positioning.json {what} text differs from the document line", record["n"]))
        cites = item.get("citations") or []
        if not isinstance(cites, list) or [citation_key(c) for c in cites if isinstance(c, dict)] != [
                citation_key(c) for c in record["citations"]]:
            out.append((f"positioning.json {what} citations differ from the document line", record["n"]))
        if bool(item.get("assumption")) != record["assumption"]:
            out.append((f"positioning.json {what} assumption flag differs from the document line", record["n"]))

    vpj = data.get("value_proposition")
    if len(vp["lines"]) == 1:
        same(vpj, vp["lines"][0], "value_proposition")
    pj = data.get("pillars")
    if not isinstance(pj, list):
        out.append(("positioning.json has no pillars list", None))
        return out
    if len(pj) != len(pillars):
        out.append((f"positioning.json has {len(pj)} pillars; the document has {len(pillars)}",
                    pillars[0]["n"] if pillars else None))
    for i, (pjson, pdoc) in enumerate(zip(pj, pillars, strict=False), 1):
        if not isinstance(pjson, dict):
            out.append((f"positioning.json pillar {i} is not an object", pdoc["n"]))
            continue
        if low(str(pjson.get("benefit", ""))) != low(pdoc["benefit"]):
            out.append((f"positioning.json pillar {i} benefit differs from the document", pdoc["n"]))
        proofs = pjson.get("proof_points")
        if not isinstance(proofs, list) or len(proofs) != len(pdoc["proofs"]):
            out.append((f"positioning.json pillar {i} proof points differ in number from the document", pdoc["n"]))
            continue
        for j, (item, record) in enumerate(zip(proofs, pdoc["proofs"], strict=False), 1):
            same(item, record, f"pillar {i} proof point {j}")
    return out


def write_check_md(result: dict, out: Path) -> None:
    files = result["files"]
    lines = [f"# Positioning check: {result['product'] or '(no title)'}", "",
             f"Rubric {result['rubric']}; format {result['format']}. No model ran this. Everything below is "
             "settled except the leads, which the review resolves.", "",
             "## Files (cite passages with these paths)", "",
             f"- document: {files['doc']}", f"- positioning.json: {files['json']}",
             f"- evidence folder: {files['evidence']}"]
    lines += [f"  - {name}" for name in files["evidence_files"]]
    h = result["hierarchy"]
    lines += ["", "## Shape", "",
              "- sections found: " + (", ".join(f"{s['number'] or '?'} {s['title']} (line {s['n']})"
                                                for s in result["sections"]) or "none"),
              f"- segment: {result['segment'] or '(none)'}",
              f"- value proposition line(s): {', '.join(map(str, h['value_proposition'])) or 'none'}"]
    for p in h["pillars"]:
        lines.append(f"- pillar {p['number']} (line {p['n']}): {p['benefit']} - {len(p['proofs'])} proof points")
    lines += ["", f"## Checker findings ({len(result['findings'])}; already counted, do not repeat them)", ""]
    for f in result["findings"]:
        where = f"line {f['passages'][0]['line']}" if f["passages"] else "document"
        lines.append(f"- {f['id']} {f['criterion']} {f['kind']} ({where}): {f['problem']}")
    if not result["findings"]:
        lines.append("None.")
    lines += ["", f"## Leads to resolve ({len(result['leads'])})", ""]
    for lead in result["leads"]:
        lines.append(f"- {lead['id']} {lead['criterion']} {lead['type']}: {lead['text']}")
    if not result["leads"]:
        lines.append("None.")
    if result["more_limits"]:
        lines += ["", "More limit statements (not leads; read them with the evidence):", ""]
        lines += [f"- {x['file']}:{x['line']} \"{x['text']}\"" for x in result["more_limits"]]
    lines += ["", "## Evidence map (each claim line, its citations and where each quote sits)", ""]
    for c in result["claims"]:
        tag = " (assumption)" if c["assumption"] else ""
        lines.append(f"- line {c['n']} [section {c['section']}]{tag}: {clip(c['text'], 200)}")
        for cite in c["citations"]:
            where = f"{cite.get('resolved_file')}:{cite.get('line')}" if cite.get("line") else "NOT FOUND"
            lines.append(f"  - {cite['file']} -> {where}{' (words skipped)' if cite.get('elided') else ''}")
    if result["problems"]:
        lines += ["", "## Problems", ""] + [f"- {x}" for x in result["problems"]]
    out.write_text("\n".join(lines) + "\n")


def cmd_check(args) -> int:
    doc, evidence = Path(args.doc), Path(args.evidence)
    json_path = Path(args.json) if args.json else doc.with_name("positioning.json")
    problems = []
    if not doc.is_file():
        problems.append(f"no document at {doc}")
    if not evidence.is_dir():
        problems.append(f"no evidence folder at {evidence}")
    if problems:
        print(json.dumps({"status": "not_checked", "check_path": "", "findings": 0, "leads": 0, "problems": problems}))
        return 0
    result = run_check(doc, json_path, evidence)
    GRADE_DIR.mkdir(parents=True, exist_ok=True)
    (GRADE_DIR / "check.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    write_check_md(result, GRADE_DIR / "check.md")
    print(json.dumps({"status": result["status"], "check_path": str(GRADE_DIR / "check.md"),
                      "findings": len(result["findings"]), "leads": len(result["leads"]),
                      "problems": result["problems"]}))
    return 0


def cmd_lint(args) -> int:
    doc, evidence = Path(args.doc), Path(args.evidence)
    json_path = Path(args.json) if args.json else doc.with_name("positioning.json")
    result = run_check(doc, json_path, evidence)
    for f in result["findings"]:
        line = f["passages"][0]["line"] if f["passages"] else "-"
        print(f"{f['id']} {f['criterion']} {f['kind']} line {line}: {f['problem']}")
    print(f"{len(result['findings'])} findings, {len(result['leads'])} leads")
    return 1 if result["findings"] else 0


# ---- verification of the review ----------------------------------------------------------------


def load_review() -> tuple[dict | None, str | None]:
    path = GRADE_DIR / "review.json"
    if not path.is_file():
        return None, "no review.json: the semantic review did not finish"
    text = path.read_text(errors="replace")
    if USAGE_LIMIT.search(text[:2000]):
        return None, "the review hit a usage limit"
    try:
        review = json.loads(text)
    except ValueError as exc:
        return None, f"review.json is not valid JSON ({exc})"
    if not isinstance(review, dict):
        return None, "review.json is not a JSON object"
    return review, None


def load_files(check: dict) -> dict[str, Doc]:
    docs = {}
    names = [check["files"]["doc"], check["files"]["json"], *check["files"]["evidence_files"]]
    for name in names:
        path = Path(name)
        if path.is_file():
            docs[name] = Doc(name, path.read_text(errors="replace"))
    return docs


def resolve_name(name: str, check: dict, docs: dict[str, Doc]) -> str | None:
    name = flat(str(name or "")).replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    if name in docs:
        return name
    evidence_dir = check["files"]["evidence"].rstrip("/")
    joined = f"{evidence_dir}/{name}"
    if joined in docs:
        return joined
    matches = [k for k in docs if k.endswith("/" + name)]
    return matches[0] if len(matches) == 1 else None


def run_verify(check: dict) -> dict:
    docs = load_files(check)
    doc_name = check["files"]["doc"]
    problems = list(check.get("problems", []))
    integrity = {p: {"before": h, "after": sha(Path(p)) if Path(p).is_file() else None}
                 for p, h in check.get("hashes", {}).items()}
    changed = [p for p, v in integrity.items() if v["before"] != v["after"]]
    review, review_problem = load_review()
    if review_problem:
        problems.append(review_problem)
    review = review or {}

    verified = [dict(f) for f in check.get("findings", [])]
    unverified = []
    for raw in review.get("findings") or []:
        if not isinstance(raw, dict):
            continue
        f = {k: raw.get(k) for k in ("id", "criterion", "kind", "severity", "claim", "problem", "absent")}
        f["source"] = "review"
        why = []
        if not f["id"] or str(f["id"]).startswith(("S", "L")):
            why.append("a review finding needs its own id (R1, R2, ...)")
        if f["criterion"] not in CRITERIA:
            why.append(f"criterion {f['criterion']!r} is not P1-P8")
        if f["severity"] not in ("material", "minor"):
            why.append("severity must be material or minor")
        if not f["claim"] or not f["problem"]:
            why.append("claim and problem are required")
        passages = []
        for p in raw.get("passages") or []:
            if not isinstance(p, dict) or not str(p.get("text") or "").strip():
                why.append("a passage needs a file and a text")
                continue
            name = resolve_name(p.get("file"), check, docs)
            if name is None:
                why.append(f"{p.get('file')!r} is not the document, positioning.json or an evidence file")
                continue
            line = docs[name].find(str(p["text"]))
            if line is None:
                why.append(f"passage not found in {name}: \"{clip(str(p['text']), 120)}\"")
                continue
            passages.append({"file": name, "text": str(p["text"]), "line": line})
        if not any(p["file"] == doc_name for p in passages):
            why.append(f"no verified passage from the document {doc_name}")
        absent = str(f.get("absent") or "").strip()
        if absent and doc_name in docs and docs[doc_name].find(absent) is not None:
            why.append(f"says the document lacks \"{clip(absent, 80)}\", but the document has it")
        f["passages"] = passages
        if why:
            unverified.append({**f, "why": why})
        else:
            verified.append({**f, "verified": True})
    counted = {f["id"] for f in verified}

    raw_leads = {str(x.get("id")): x for x in review.get("leads") or [] if isinstance(x, dict)}
    leads_out, unresolved = [], []
    for lead in check.get("leads", []):
        got = raw_leads.get(lead["id"]) or {}
        resolution, note = got.get("resolution"), flat(str(got.get("note") or got.get("why") or ""))
        if resolution == "ok" and note:
            status = "ok"
        elif resolution == "finding" and got.get("finding") in counted:
            status, note = "finding", f"finding {got.get('finding')}" + (f": {note}" if note else "")
        else:
            status = "unresolved"
            note = ("no resolution" if not got else
                    "resolution 'ok' needs a note" if resolution == "ok" else
                    f"names finding {got.get('finding')!r}, which did not verify" if resolution == "finding" else
                    f"unknown resolution {resolution!r}")
            unresolved.append(lead)
        leads_out.append({**lead, "resolution": status, "resolution_note": note})

    criteria = {}
    stated = review.get("criteria") if isinstance(review.get("criteria"), dict) else {}
    for c in CRITERIA:
        material = [f["id"] for f in verified if f["criterion"] == c and f["severity"] == "material"]
        minor = [f["id"] for f in verified if f["criterion"] == c and f["severity"] == "minor"]
        open_leads = [lead["id"] for lead in unresolved if lead["criterion"] == c]
        claim = stated.get(c) if isinstance(stated.get(c), dict) else {}
        said = claim.get("status")
        reasons = []
        if material:
            status = "revise"
        else:
            if c in check.get("unknown", {}):
                reasons.append(check["unknown"][c])
            if open_leads:
                reasons.append(f"leads not resolved: {', '.join(open_leads)}")
            if review_problem:
                reasons.append("no semantic review")
            elif said not in ("pass", "revise", "unknown"):
                reasons.append("the review gave no status")
            elif said == "unknown":
                reasons.append("the review could not settle it: " + flat(str(claim.get("note") or "")))
            elif said == "revise":
                reasons.append("the review said revise but none of its material findings verified")
            status = "unknown" if reasons else "pass"
        criteria[c] = {"name": CRITERION_NAMES[c], "status": status, "material": material, "minor": minor,
                       "unresolved_leads": open_leads, "why_unknown": reasons,
                       "review_note": flat(str(claim.get("note") or ""))}
    if changed:
        problems.append("files changed during grading: " + ", ".join(changed))
    statuses = [v["status"] for v in criteria.values()]
    overall = "revise" if "revise" in statuses else ("unknown" if "unknown" in statuses else "pass")
    if changed and overall == "pass":
        overall = "unknown"
    limitations = [
        "Works from the evidence folder only: a claim true in the world but not in the evidence is unproven here, "
        "and an error inside an evidence file is out of reach.",
        "Grades soundness, not appeal: whether the market will buy is a message test's question.",
    ] + [flat(str(x)) for x in (review.get("limitations") or []) if x]
    return {"version": "positioning_grade_quality/1", "rubric": RUBRIC_VERSION,
            "rubric_sha256": check.get("rubric_sha256"), "format_sha256": check.get("format_sha256"),
            "checker_sha256": check.get("checker_sha256"), "product": check.get("product"),
            "files": check.get("files"), "status": overall, "criteria": criteria, "findings": verified,
            "unverified": unverified, "leads": leads_out,
            "integrity": {"unchanged": not changed, "files": integrity},
            "limitations": limitations, "problems": problems}


def write_quality(q: dict, out: Path) -> None:
    lines = [f"# Positioning quality: {q['status'].upper()}", "",
             f"{q.get('product') or 'The document'}, graded under rubric {q['rubric']} "
             f"(sha256 {str(q.get('rubric_sha256'))[:12]}). Soundness against its own evidence, not appeal; "
             "the grade never rewrites the document.", "",
             "| criterion | status | material findings | notes |", "|---|---|---|---|"]
    for c, v in q["criteria"].items():
        note = "; ".join(v["why_unknown"]) or v["review_note"]
        lines.append(f"| {c} {v['name']} | {v['status']} | {', '.join(v['material']) or '-'} | "
                     f"{clip(note, 200).replace('|', '/') if note else ''} |")
    lines += ["", "## Findings", ""]
    for f in q["findings"]:
        lines.append(f"### {f['id']} {f['criterion']} {f.get('kind') or ''} ({f['severity']}, {f['source']})")
        lines.append(f"- Claim: {flat(str(f.get('claim') or ''))}")
        lines.append(f"- Problem: {flat(str(f.get('problem') or ''))}")
        for p in f["passages"]:
            lines.append(f"- {p['file']}:{p.get('line')}: \"{clip(p['text'], 400)}\"")
        lines.append("")
    if not q["findings"]:
        lines.append("None.")
    if q["unverified"]:
        lines += ["", "## Unverified (not counted)", ""]
        for f in q["unverified"]:
            lines.append(f"- {f.get('id')} {f.get('criterion')}: {flat(str(f.get('problem') or ''))} [{'; '.join(f['why'])}]")
    lines += ["", "## Leads", ""]
    for lead in q["leads"]:
        lines.append(f"- {lead['id']} {lead['criterion']} {lead['type']}: {lead['resolution']} "
                     f"({clip(lead['resolution_note'], 160)})")
    if not q["leads"]:
        lines.append("None.")
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in q["limitations"]]
    lines += ["", f"Integrity: graded files {'unchanged' if q['integrity']['unchanged'] else 'CHANGED'} by grading."]
    if q["problems"]:
        lines += ["", "## Problems", ""] + [f"- {x}" for x in q["problems"]]
    out.write_text("\n".join(lines) + "\n")


def summary(q: dict) -> dict:
    return {"status": "completed", "quality_status": q["status"], "quality_path": str(GRADE_DIR / "quality.md"),
            "criteria": {c: v["status"] for c, v in q["criteria"].items()},
            "findings": len([f for f in q["findings"] if f["severity"] == "material"]),
            "unverified": len(q["unverified"]), "problems": q["problems"]}


def cmd_verify(args) -> int:
    check_path = GRADE_DIR / "check.json"
    if not check_path.is_file():
        print(json.dumps({"status": "completed", "quality_status": "unknown", "quality_path": "", "criteria": {},
                          "findings": 0, "unverified": 0,
                          "problems": ["no check.json: the deterministic check did not run"]}))
        return 0
    q = run_verify(json.loads(check_path.read_text()))
    if args.dry_run:
        print("Dry run: nothing written.")
        for f in q["unverified"]:
            print(f"UNVERIFIED {f.get('id')}: " + "; ".join(f["why"]))
        for lead in q["leads"]:
            if lead["resolution"] == "unresolved":
                print(f"UNRESOLVED {lead['id']}: {lead['resolution_note']}")
        for c, v in q["criteria"].items():
            print(f"{c} {v['status']}" + (f" ({'; '.join(v['why_unknown'])})" if v["why_unknown"] else ""))
        print(f"overall {q['status']}; {len(q['findings'])} findings counted, {len(q['unverified'])} unverified")
        return 0
    (GRADE_DIR / "quality.json").write_text(json.dumps(q, indent=1, ensure_ascii=False))
    write_quality(q, GRADE_DIR / "quality.md")
    print(json.dumps(summary(q)))
    return 0


def cmd_passage(args) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"no such file: {path}")
        return 1
    line = Doc(str(path), path.read_text(errors="replace")).find(args.text)
    print(f"found at line {line}" if line else "NOT FOUND (copy the text exactly; a long passage may skip text with ...)")
    return 0 if line else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("check", "lint"):
        p = sub.add_parser(name)
        p.add_argument("--doc", required=True)
        p.add_argument("--json", default="")
        p.add_argument("--evidence", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("passage")
    p.add_argument("file")
    p.add_argument("text")
    args = parser.parse_args(argv)
    return {"check": cmd_check, "lint": cmd_lint, "verify": cmd_verify, "passage": cmd_passage}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
