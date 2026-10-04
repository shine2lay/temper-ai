#!/usr/bin/env python3
"""signal_grade checker (product role, queue #12): the deterministic half of the quality grade of
one signal_harvest report, and the verifier of the semantic review. Rubric: rubric.md next to
this file (signal_grade/1). Standard library only. Run from the run workspace.

    check_signal.py check [--report-dir state]
        Read the report (shortlist, scorecard, lens files), recompute what can be recomputed
        (every signal cell, weighted total, arithmetic line, overall confidence, the ranking,
        candidate and required-player coverage), trace every figure, quote and URL of the
        scorecard to the lens files, and list the leads the review must resolve. Writes
        state/signal_grade/check.json and check.md.
    check_signal.py verify [--dry-run]
        Verify the review (state/signal_grade/review.json) against the files: a finding counts
        only when every passage it cites is in the file it names; an allegation that something is
        absent is checked by searching for it; a lead dismissed as derived must compute. Merge it
        with the deterministic results into per-criterion pass / revise / unknown and write
        quality.json and quality.md. --dry-run only prints what would not verify, for the
        reviewer to fix before it finishes.
    check_signal.py passage FILE TEXT
        Whether TEXT is in FILE as the verifier reads it.

The grade never rescores, re-weights or re-ranks: the demand formula is checked exactly as the
synthesizer (configs/agents/signal_synthesize.yaml) states it.
"""

from __future__ import annotations

import argparse
import ast
import bisect
import hashlib
import json
import operator
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRADE_DIR = Path("state/signal_grade")
SHORTLIST = GRADE_DIR / "shortlist.txt"
RUBRIC_VERSION = "signal_grade/1"
CRITERIA = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6")
CRITERION_NAMES = {
    "Q1": "Candidate identity and completeness",
    "Q2": "Arithmetic, confidence and ranking reproduce",
    "Q3": "Evidence provenance and attribution",
    "Q4": "Blocked sources and honest unknowns",
    "Q5": "Scope match: buyer, job, population and price",
    "Q6": "Competitors: exact versus adjacent or bundled, and coverage",
}
SIGNALS = ("search", "money", "pain", "competitors")
WEIGHTS = {"search": 0.15, "money": 0.35, "pain": 0.20, "competitors": 0.30}
MULTIPLIER = {"high": 1.0, "med": 0.8, "low": 0.5}
LABEL_OF = {1.0: "high", 0.8: "med", 0.5: "low"}
CONF_RANK = {"low": 0, "med": 1, "high": 2}
TOL = 0.005 + 1e-9
LEAD_CAP = 60  # leads of one type beyond this are listed together, not one by one
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
    text = text.translate(TYPO).replace("\u2026", "...")
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
    """One report file: its lines, its flattened text and where each line starts in it."""

    def __init__(self, path: str, text: str):
        self.path = path
        self.lines = text.split("\n")
        self.flat_lines = [flat(line) for line in self.lines]
        self.starts: list[int] = []
        pos = 0
        parts = []
        for line in self.flat_lines:
            self.starts.append(pos)
            parts.append(line)
            pos += len(line) + 1
        self.text = " ".join(parts)
        self.lower = self.text.lower()

    def line_at(self, offset: int) -> int:
        """1-based line number of an offset into the flattened text."""
        return bisect.bisect_right(self.starts, offset)

    def find(self, passage: str) -> int | None:
        """1-based line where the passage starts, or None. A passage with '...' may skip text
        between its parts, which must then appear in order."""
        wanted = flat(passage).strip(" \"'")
        if not wanted:
            return None
        at = self.text.find(wanted)
        if at >= 0:
            return self.line_at(at)
        parts = [p.strip(" \"'") for p in wanted.split("...")]
        parts = [p for p in parts if p]
        if len(parts) < 2 or any(len(p.split()) < 3 for p in parts):
            return None
        pos, first = 0, None
        for part in parts:
            at = self.text.find(part, pos)
            if at < 0:
                return None
            first = at if first is None else first
            pos = at + len(part)
        return self.line_at(first)


# ---- candidate ids and sections ----------------------------------------------------------------

ID_AT_START = re.compile(r"^(?:Candidate\s+|CANDIDATE\s+|candidate\s+)?(REFERENCE|V\d+|[A-Z]\d?|\d+)(?!\w)")
SHORTLIST_LINE = (
    re.compile(r"^\s*(?:CANDIDATE|Candidate)\s+([A-Z]\d?|\d+)(?!\w)(?:\s*\([^)]*\))?\s*[-:]+\s*(\S.*)$"),
    re.compile(r"^\s*(REFERENCE)(?!\w)(?:\s*\([^)]*\))?\s*[-:]+\s*(\S.*)$"),
    re.compile(r"^\s*(V\d+)\s*[-:]+\s*(\S.*)$"),
)


def shortlist_candidates(doc: Doc) -> list[dict]:
    out, seen = [], set()
    for n, line in enumerate(doc.flat_lines, 1):
        for pattern in SHORTLIST_LINE:
            m = pattern.match(line)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                out.append({"id": m.group(1), "name": m.group(2).strip(), "line": n, "text": doc.lines[n - 1]})
                break
    return out


def section_ids(doc: Doc, known: set[str]) -> list[str | None]:
    """The candidate section of every line: the id of the nearest candidate heading above it, or
    None outside any candidate's section."""
    out: list[str | None] = []
    current, level = None, 0
    for line in doc.lines:
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            depth = len(m.group(1))
            hit = ID_AT_START.match(flat(m.group(2)))
            cid = hit.group(1) if hit and hit.group(1) in known else None
            if cid:
                current, level = cid, depth
            elif current is None or depth <= level:
                current, level = None, 0
        out.append(current)
    return out


def name_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def match_name(name: str, named: list[tuple[str, str]]) -> str | None:
    """The id whose name best matches: equal, a prefix of the other, or most words shared."""
    key = name_key(name)
    if not key:
        return None
    for cid, other in named:
        other_key = name_key(other)
        if other_key and (key == other_key or key.startswith(other_key) or other_key.startswith(key)):
            return cid
    words = set(key.split())
    best, best_score = None, 0.0
    for cid, other in named:
        other_words = set(name_key(other).split())
        if not other_words:
            continue
        score = len(words & other_words) / len(words | other_words)
        if score > best_score:
            best, best_score = cid, score
    return best if best_score >= 0.5 else None


# ---- the scorecard table -------------------------------------------------------------------------

CELL = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*[\u00d7xX]\s*(?:(high|medium|med|low)\s*\(\s*)?(\d+(?:\.\d+)?)\s*\)?\s*=\s*(\d+(?:\.\d+)?)",
    re.I,
)


def split_row(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def is_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|?\s*:?-{2,}", line)) and set(line.replace("|", "").strip()) <= set("-: ")


def header_map(cells: list[str]) -> dict | None:
    cols: dict = {}
    money = None
    for i, cell in enumerate(cells):
        c = low(cell)
        if c.startswith("search"):
            cols["search"] = i
        elif c.startswith("pain"):
            cols["pain"] = i
        elif c.startswith("competitor"):
            cols["competitors"] = i
        elif c.startswith("weighted"):
            cols["weighted"] = i
        elif c.startswith("overall") or c in ("confidence", "overall conf"):
            cols["overall"] = i
        elif c in ("#", "id"):
            cols["id"] = i
        elif c.startswith(("idea", "candidate", "version", "name")):
            cols["label"] = i
        elif "raw" in c and money is None:
            money = (i, c.split()[0].split("(")[0])
    if not {"search", "pain", "competitors", "weighted"} <= set(cols) or money is None:
        return None
    cols["money"] = money[0]
    cols["money_name"] = money[1]
    cols.setdefault("label", 0 if cols.get("id") != 0 else 1)
    return cols


def parse_cell(text: str) -> dict | None:
    m = CELL.match(flat(text))
    if not m:
        return None
    label = (m.group(2) or "").lower() or None
    label = "med" if label == "medium" else label
    return {"raw": float(m.group(1)), "label": label, "mult": float(m.group(3)), "disc": float(m.group(4)),
            "text": flat(text)}


def overall_label(text: str) -> str | None:
    m = re.search(r"[A-Za-z]+", flat(text))
    word = m.group(0).lower() if m else ""
    return {"high": "high", "med": "med", "medium": "med", "low": "low"}.get(word)


def first_number(text: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", flat(text))
    return float(m.group(0)) if m else None


def parse_table(doc: Doc) -> dict | None:
    for i, line in enumerate(doc.lines):
        if not line.lstrip().startswith("|"):
            continue
        cols = header_map(split_row(line))
        if not cols:
            continue
        rows = []
        j = i + 1
        while j < len(doc.lines) and doc.lines[j].lstrip().startswith("|"):
            if not is_separator(doc.lines[j]):
                rows.append(table_row(doc, j, cols))
            j += 1
        return {"header_line": i + 1, "money_name": cols["money_name"], "rows": rows, "end_line": j}
    return None


def table_row(doc: Doc, index: int, cols: dict) -> dict:
    cells = split_row(doc.lines[index])
    get = lambda k: cells[cols[k]] if k in cols and cols[k] < len(cells) else ""  # noqa: E731
    label = flat(get("label"))
    if "id" in cols:
        cid = flat(get("id"))
        name = label
    else:
        m = ID_AT_START.match(label)
        cid = m.group(1) if m else ""
        name = re.sub(r"^\s*[-:]+\s*", "", label[m.end():]) if m else label
    row = {"id": cid, "name": name, "line": index + 1, "text": doc.lines[index], "cells": {}, "problems": []}
    for signal in SIGNALS:
        cell = parse_cell(get(signal))
        if cell is None:
            row["problems"].append({"kind": "unparsed", "detail": f"{signal} cell not read: {flat(get(signal))!r}"})
        row["cells"][signal] = cell
    row["weighted"] = first_number(get("weighted"))
    row["overall"] = overall_label(get("overall")) if "overall" in cols else None
    row["overall_text"] = flat(get("overall"))
    if row["weighted"] is None:
        row["problems"].append({"kind": "unparsed", "detail": "weighted_score not read"})
    if row["overall"] is None:
        row["problems"].append({"kind": "unparsed", "detail": f"overall confidence not read: {row['overall_text']!r}"})
    return row


def fmt(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".") if x is not None else "?"


def check_row(row: dict) -> None:
    """Recompute one row exactly as the synthesizer's formula states it."""
    cells = row["cells"]
    if any(c is None for c in cells.values()):
        return
    for signal, c in cells.items():
        if c["raw"] not in (0, 1, 2, 3):
            row["problems"].append({"kind": "raw", "signal": signal, "detail": f"{signal} raw score {fmt(c['raw'])} is not 0-3"})
        if c["mult"] not in LABEL_OF:
            row["problems"].append({"kind": "multiplier", "signal": signal,
                                    "detail": f"{signal} multiplier {fmt(c['mult'])} is not a confidence discount (1.0, 0.8, 0.5)"})
        elif c["label"] and LABEL_OF[c["mult"]] != c["label"]:
            row["problems"].append({"kind": "multiplier", "signal": signal,
                                    "detail": f"{signal} says {c['label']} but multiplies by {fmt(c['mult'])}"})
        if abs(c["raw"] * c["mult"] - c["disc"]) > TOL:
            row["problems"].append({"kind": "cell", "signal": signal,
                                    "detail": f"{signal} cell {fmt(c['raw'])}\u00d7{fmt(c['mult'])} = {fmt(c['raw'] * c['mult'])}, shown {fmt(c['disc'])}"})
    true_total = sum(WEIGHTS[s] * cells[s]["raw"] * cells[s]["mult"] for s in SIGNALS)
    shown_total = sum(WEIGHTS[s] * cells[s]["disc"] for s in SIGNALS)
    row["computed"] = round(true_total, 4)
    row["computed_from_shown_cells"] = round(shown_total, 4)
    if row["weighted"] is not None and abs(row["weighted"] - true_total) > TOL:
        row["problems"].append({"kind": "total",
                                "detail": f"weighted_score shown {fmt(row['weighted'])}, the signals give {fmt(true_total)}"
                                          + (f" (from the cells as shown {fmt(shown_total)})" if abs(shown_total - true_total) > TOL else "")})
    labels = {s: LABEL_OF.get(cells[s]["mult"]) for s in SIGNALS}
    lows = [s for s in SIGNALS if labels[s] == "low"]
    forced = labels["money"] == "low" or labels["competitors"] == "low" or len(lows) >= 2
    row["confidence_rule"] = {"low_signals": lows, "forced_low": forced,
                              "allowed": ["low"] if forced else ["med", "high"]}
    if row["overall"] in ("med", "high") and forced:
        why = "jobs/money signal low" if labels["money"] == "low" else (
            "competitors low" if labels["competitors"] == "low" else f"{len(lows)} signals low ({', '.join(lows)})")
        row["problems"].append({"kind": "confidence",
                                "detail": f"overall confidence {row['overall']} above the rule: {why} forces low"})
    elif row["overall"] == "low" and not forced:
        row["problems"].append({"kind": "confidence_below", "minor": True,
                                "detail": "overall confidence low although the rule allows med (a conservative label)"})


# ---- arithmetic lines and ranking ------------------------------------------------------------

TERM = re.compile(r"(?<![\d.])0?\.(15|35|20|30)\s*(?:[\u00d7xX]\s*|\(\s*)(\d+(?:\.\d+)?)")
SIGNAL_OF_WEIGHT = {"15": "search", "35": "money", "20": "pain", "30": "competitors"}


def arithmetic_lines(doc: Doc, sections: list, known: set[str]) -> list[dict]:
    out = []
    i = 0
    while i < len(doc.lines):
        text = doc.flat_lines[i]
        terms = TERM.findall(text)
        if len({w for w, _ in terms}) == 4 and "=" in text:
            lines = [i]
            while i + 1 < len(doc.lines) and re.match(r"^\s*=", doc.lines[i + 1]):
                i += 1
                lines.append(i)
            joined = " ".join(doc.flat_lines[k] for k in lines)
            m = re.match(r"^\s*[-+]?\s*(REFERENCE|V\d+|[A-Z]\d?|\d+)\s*:", text)
            cid = m.group(1) if m and m.group(1) in known else sections[lines[0]]
            tail = joined.rsplit("=", 1)[1]
            numbers = re.findall(r"\d+(?:\.\d+)?", tail)
            values = {SIGNAL_OF_WEIGHT[w]: float(v) for w, v in terms[:4]} if len(terms) >= 4 else {}
            out.append({"id": cid, "line": lines[0] + 1, "lines": [k + 1 for k in lines],
                        "text": "\n".join(doc.lines[k] for k in lines), "values": values,
                        "total": float(numbers[-1]) if numbers else None,
                        "computed": round(sum(WEIGHTS[s] * v for s, v in values.items()), 4), "problems": []})
        i += 1
    return out


def check_arithmetic(entry: dict, rows_by_id: dict) -> None:
    if entry["total"] is None:
        entry["problems"].append("its total could not be read")
        return
    if abs(entry["computed"] - entry["total"]) > TOL:
        entry["problems"].append(f"its terms sum to {fmt(entry['computed'])}, it shows {fmt(entry['total'])}")
    rows = rows_by_id.get(entry["id"]) or []
    if not rows:
        return
    row = rows[0]
    for signal, value in entry["values"].items():
        cell = row["cells"].get(signal)
        if cell and abs(cell["disc"] - value) > TOL:
            entry["problems"].append(f"it uses {fmt(value)} for {signal}, the table shows {fmt(cell['disc'])}")
        elif cell and abs(cell["raw"] * cell["mult"] - value) > TOL:
            entry["problems"].append(f"it uses {fmt(value)} for {signal}, but {fmt(cell['raw'])}\u00d7{fmt(cell['mult'])} "
                                     f"= {fmt(cell['raw'] * cell['mult'])}")
    true_total = row.get("computed")
    if true_total is not None and abs(true_total - entry["total"]) > TOL and not entry["problems"]:
        entry["problems"].append(f"its total {fmt(entry['total'])} differs from the signals' {fmt(true_total)}")
    if row["weighted"] is not None and abs(row["weighted"] - entry["total"]) > TOL:
        entry["problems"].append(f"its total {fmt(entry['total'])} differs from the table's {fmt(row['weighted'])}")


def parse_ranking(doc: Doc, named: list[tuple[str, str]], known: set[str]) -> dict | None:
    start = None
    for i, line in enumerate(doc.lines):
        if re.match(r"^#{1,6}\s*(?:\d+\.\s*)?ranking\b", flat(line), re.I):
            start = i
            break
    if start is None:
        return None
    level = len(re.match(r"^(#+)", doc.lines[start]).group(1))
    entries = []
    for i in range(start + 1, len(doc.lines)):
        m = re.match(r"^(#{1,6})\s", doc.lines[i])
        if m and len(m.group(1)) <= level:
            break
        text = doc.flat_lines[i]
        lm = re.match(r"^(\d+)\.\s+(.*)$", text)
        if lm:
            rest = lm.group(2)
            idm = ID_AT_START.match(rest)
            cid = idm.group(1) if idm and idm.group(1) in known else None
            name = re.split(r"\s+-\s+weighted|\s+-\s+", rest[idm.end():] if cid else rest, maxsplit=1)
            name = name[0] if cid is None else (re.split(r"\s+-\s+weighted", rest[idm.end():])[0].strip(" -"))
            cid = cid or match_name(name, named)
            sm = re.search(r"weighted(?:_score)?\s*[:=]?\s*(\d+(?:\.\d+)?)", rest, re.I)
            cm = re.search(r"confidence\s*[:=]?\s*([A-Za-z]+)", rest, re.I)
            entries.append({"rank": int(lm.group(1)), "id": cid, "name": name, "line": i + 1, "text": doc.lines[i],
                            "score": float(sm.group(1)) if sm else None,
                            "confidence": overall_label(cm.group(1)) if cm else None})
        elif text.startswith("|") and not is_separator(doc.lines[i]):
            cells = [flat(c) for c in split_row(doc.lines[i])]
            if not cells or not re.fullmatch(r"\d+", cells[0]) or len(cells) < 3:
                continue
            name = cells[1]
            idm = ID_AT_START.match(name)
            cid = idm.group(1) if idm and idm.group(1) in known and not re.fullmatch(r"\d+", idm.group(1)) else None
            cid = cid or match_name(name, named)
            entries.append({"rank": int(cells[0]), "id": cid, "name": name, "line": i + 1, "text": doc.lines[i],
                            "score": first_number(cells[2]),
                            "confidence": overall_label(cells[3]) if len(cells) > 3 else None})
    return {"line": start + 1, "entries": entries, "problems": []}


def check_ranking(ranking: dict, rows_by_id: dict) -> None:
    previous = None
    for entry in ranking["entries"]:
        rows = rows_by_id.get(entry["id"]) or []
        if not rows:
            continue
        row = rows[0]
        if entry["score"] is not None and row["weighted"] is not None and not any(
                abs(r["weighted"] - entry["score"]) <= TOL for r in rows if r["weighted"] is not None):
            entry.setdefault("problems", []).append(
                f"ranking quotes {fmt(entry['score'])}, the table shows {fmt(row['weighted'])}")
        if entry["confidence"] and row["overall"] and entry["confidence"] != row["overall"]:
            entry.setdefault("problems", []).append(
                f"ranking says confidence {entry['confidence']}, the table says {row['overall']}")
        if previous is not None and row["weighted"] is not None and previous["weighted"] is not None:
            if row["weighted"] > previous["weighted"] + TOL:
                entry.setdefault("problems", []).append(
                    f"ranked below {previous['id']} ({fmt(previous['weighted'])}) with a higher score ({fmt(row['weighted'])})")
            elif abs(row["weighted"] - previous["weighted"]) <= 1e-9:
                key = lambda r: (CONF_RANK.get(r["overall"] or "", -1), r["cells"]["money"]["raw"] if r["cells"].get("money") else -1)  # noqa: E731
                if key(row) > key(previous):
                    entry.setdefault("problems", []).append(
                        f"tied with {previous['id']} on weighted_score but wins the tie-break (confidence, then jobs)")
        previous = row


# ---- required players ----------------------------------------------------------------------------

def required_players(doc: Doc) -> dict | None:
    """The players the shortlist explicitly asks to check (a 'PLAYERS TO CHECK' paragraph)."""
    for i, line in enumerate(doc.lines):
        if "players to check" in line.lower():
            j = i
            while j + 1 < len(doc.lines) and doc.lines[j + 1].strip():
                j += 1
            raw = "\n".join(doc.lines[i:j + 1])
            body = flat(raw).split(":", 1)[1] if ":" in flat(raw) else ""
            body = re.sub(r"([A-Z][\w.&' -]*?)\s*\(([^()]*,[^()]*)\)", lambda m: m.group(2), body)
            names = []
            for part in re.split(r",|;|\band\b", body):
                part = part.strip().strip(".").strip()
                part = re.sub(r"^(?:for\s+\S+\s+also|also|plus|including|e\.g\.)\s+", "", part, flags=re.I)
                part = re.sub(r"'s\b.*$", "", part).strip()
                if not part or re.match(r"^(?:any|others?|plus any|more)\b", part, re.I):
                    continue
                if part not in names:
                    names.append(part)
            return {"line": i + 1, "lines": [i + 1, j + 1], "text": raw, "listed": names}
    return None


def player_keys(name: str) -> list[str]:
    keys = [name]
    words = name.split()
    if len(words) > 1:
        keys.append(" ".join(words[1:]))
        m = re.match(r"(.+?)\s+(?:in|on|inside|within)\s+\S.*$", name)
        if m:
            keys.append(m.group(1))
    return keys


def mentions(text: str, key: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(key) + r"(?![\w])", text, re.I) is not None


# ---- evidence tracing ----------------------------------------------------------------------------

FIGURE = re.compile(
    r"(?P<money>\$\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:[kKmMbB]n?|million|billion|thousand)(?![a-zA-Z]))?\+?)"
    r"|(?P<pct>(?<![\w.])\d+(?:\.\d+)?\s?(?:%|percent\b|per cent\b))"
    r"|(?P<num>(?<![\w.$,=/#?])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d])\+?|(?<![\w.$,=/#?])\d{4,}(?:\.\d+)?(?![\d,])"
    r"|(?<![\w.$,=/#?\-])[1-9]\d{2}(?![\d.,%\-/:])\+?)"
)
URL = re.compile(r"https?://[^\s<>\"'`)\]|]+")
MONEY_RANGE = re.compile(
    r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(?:-|to)\s?\$?(\d[\d,]*(?:\.\d+)?)\s?(k|m|bn?|thousand|million|billion)(?![a-zA-Z])\+?",
    re.I,
)
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def figures(text: str) -> list[dict]:
    """Money amounts, percentages and large counts in a line. '$40-80k' is two amounts,
    $40,000 and $80,000; '$35k' is $35,000; a year (1900-2100) is not a figure."""
    out = []

    def take_range(m):
        scale = SCALE[m.group(3).lower()]
        for group in (1, 2):
            digits = m.group(group)
            out.append({"text": m.group(0), "kind": "num", "value": float(digits.replace(",", "")) * scale,
                        "decimals": len(digits.partition(".")[2]), "start": m.start()})
        return " " * len(m.group(0))

    text = MONEY_RANGE.sub(take_range, URL.sub(lambda m: " " * len(m.group(0)), text))
    for m in FIGURE.finditer(text):
        s = m.group(0).strip()
        if m.group("pct"):
            digits = re.match(r"\d+(?:\.\d+)?", s).group(0)
            out.append({"text": s, "kind": "pct", "value": float(digits), "decimals": len(digits.partition(".")[2]),
                        "start": m.start()})
            continue
        digits = re.search(r"\d[\d,]*(?:\.\d+)?", s).group(0)
        value = float(digits.replace(",", ""))
        if m.group("num") and "," not in s and "+" not in s and 1900 <= value <= 2100 and "." not in digits:
            continue  # a year
        if m.group("money"):
            tail = s.lower()
            if re.search(r"\d\s?k\b|thousand", tail):
                value *= 1e3
            elif re.search(r"\d\s?m\b|million", tail):
                value *= 1e6
            elif re.search(r"\d\s?bn?\b|billion", tail):
                value *= 1e9
        out.append({"text": s, "kind": "num", "value": value, "decimals": len(digits.partition(".")[2]),
                    "start": m.start()})
    return out


def doc_figures(doc: Doc) -> list[tuple[dict, int]]:
    """Every figure of a file with its line, read across line breaks ('36\\npercent')."""
    return [(f, doc.line_at(f["start"])) for f in figures(doc.text)]


def norm_url(url: str) -> str:
    url = url.rstrip(".,;:!?'\"").lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.split("#", 1)[0].rstrip("/")


PARAGRAPH = re.compile(r"(?:[^\n]|\n(?![ \t]*\n))+")


def quote_pairs(text: str, base: int) -> list[tuple[int, int]]:
    marks = [base + m.start() for m in re.finditer('"', text)]
    return list(zip(marks[0::2], marks[1::2], strict=False)) if len(marks) % 2 == 0 else []


def quotes(doc: Doc) -> list[dict]:
    """Quoted passages of five or more words. Quote marks pair up in order within a paragraph;
    a paragraph with an odd number of marks pairs within each of its lines, and a line with an
    odd number is skipped (a stray inch mark must not swap every pairing after it)."""
    out = []
    raw = "\n".join(doc.lines).translate(TYPO)
    for block in PARAGRAPH.finditer(raw):
        pairs = quote_pairs(block.group(0), block.start())
        if not pairs and block.group(0).count('"'):
            pos = block.start()
            for line in block.group(0).split("\n"):
                pairs += quote_pairs(line, pos)
                pos += len(line) + 1
        for start, end in pairs:
            body = raw[start + 1:end]
            if "|" in body or len(flat(body).split()) < 5 or len(body) > 900:
                continue
            out.append({"text": flat(body), "line": raw.count("\n", 0, start) + 1})
    return out


def qnorm(text: str) -> str:
    text = low(text)
    text = re.sub(r"[\"']", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;:-")


def shingles(words: list[str], n: int = 4) -> set:
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


BLOCKED = re.compile(
    r"\b(?:inaccessible|blocked|403|429|rate[- ]?limit\w*|not attempted|zero results|no results|returned "
    r"(?:nothing|no |zero|0 )|could ?n[o']?t (?:be )?(?:fetch|access|reach|load|read|open|verif)\w*|captcha|"
    r"login[- ]?wall\w*|paywall\w*|unreachable|not reachable|timed? ?out|failed to (?:fetch|load|access)|"
    r"snippets? only|snippet-only|not (?:fetched|accessible|reachable)|unverified)\b",
    re.I,
)
ABSENCE = re.compile(
    r"\b(?:no complaints?|none found|no (?:evidence|sign|signs|demand|pain|interest|one is)|absen(?:ce|t)|"
    r"untroubled|not troubled|n[o']t (?:voicing|feel\w*|experienc\w*)|doesn'?t exist|does not exist|found no(?:thing)?|"
    r"zero (?:demand|complaints?|interest)|nobody|no one (?:complains?|mentions?)|confirms? (?:that )?(?:there (?:is|are) )?no)\b",
    re.I,
)
READ_VERB = re.compile(r"\b(?:read|reviewed|checked|searched|scanned|went through|looked at|combed|found no|no complaints?)\b", re.I)
ADJACENT = re.compile(
    r"\b(?:adjacent|one layer up|purpose[- ]built|no (?:direct |exact |dedicated )?(?:vendor|competitor|product|tool|player|incumbent)s?\b"
    r"|general(?:ist)?(?: enterprise)? (?:rcm|platform|tool|software|suite)|bundl\w+|free (?:feature|add-on|tier)|"
    r"built[- ]in|add-ons?|outsourc\w+|not (?:a )?direct|indirect|substitute|horizontal)\b",
    re.I,
)
SCOPE_WORDS = re.compile(
    r"\b(?:all|every|across|market-wide|industry-wide|nationwide|entire|whole|only|exclusively|none of|"
    r"no (?:chains?|staffing|vendors?|employers?)|always|never)\b",
    re.I,
)
CONSUMER = re.compile(r"\b(?:consumers?|b2c|individual (?:users?|travel+ers?)|households?)\b", re.I)
VENUES = ("reddit", "g2", "capterra", "glassdoor", "trustpilot", "vin", "linkedin", "indeed", "ziprecruiter",
          "simplyhired", "quora", "facebook", "twitter", "youtube", "tiktok", "app store", "google play",
          "hacker news", "aapc", "student doctor network", "sdn", "biggerpockets", "tripadvisor", "bls", "yelp",
          "angi", "thumbtack", "product hunt", "crunchbase", "similarweb", "semrush", "google trends",
          "spiceworks", "dentaltown", "fleetowner", "truckersreport", "hostagencyreviews")


def venues_in(text: str) -> set[str]:
    found = {v for v in VENUES if mentions(text, v)}
    found |= {d.lower() for d in re.findall(r"\b[a-z0-9-]+\.(?:com|org|net|gov|io|co)\b", text, re.I)}
    return found


# ---- check -----------------------------------------------------------------------------------

def load_report(report_dir: Path) -> tuple[dict, list[str]]:
    problems = []
    files = {}
    scorecard = report_dir / "signal_scorecard.md"
    if scorecard.is_file():
        files["scorecard"] = str(scorecard)
    else:
        problems.append(f"no scorecard at {scorecard}")
    lens_dir = report_dir / "signal"
    lenses = {p.stem: str(p) for p in sorted(lens_dir.glob("*.md"))} if lens_dir.is_dir() else {}
    if not lenses:
        problems.append(f"no lens files in {lens_dir}")
    files["lenses"] = lenses
    if SHORTLIST.is_file():
        files["shortlist"] = str(SHORTLIST)
    else:
        problems.append(f"no shortlist at {SHORTLIST}")
    return files, problems


def report_paths(files: dict) -> list[str]:
    return [p for p in [files.get("scorecard"), files.get("shortlist"), *files.get("lenses", {}).values()] if p]


def finding(fid, criterion, candidate, kind, claim, problem, passages, severity="material"):
    return {"id": fid, "criterion": criterion, "candidate": candidate, "kind": kind, "severity": severity,
            "claim": claim, "problem": problem, "passages": passages, "source": "check"}


def run_check(report_dir: Path) -> dict:
    files, problems = load_report(report_dir)
    result = {"version": "signal_grade_check/1", "rubric": RUBRIC_VERSION,
              "checker_sha256": sha(Path(__file__)), "files": files, "problems": problems,
              "hashes": {p: sha(Path(p)) for p in report_paths(files)},
              "findings": [], "leads": [], "unknown": {}, "evidence": {}}
    rubric = HERE / "rubric.md"
    result["rubric_sha256"] = sha(rubric) if rubric.is_file() else None
    if "scorecard" not in files:
        for c in CRITERIA:
            result["unknown"][c] = "no scorecard to check"
        result["status"] = "no_report"
        return result

    card = Doc(files["scorecard"], Path(files["scorecard"]).read_text(errors="replace"))
    lens_docs = {name: Doc(path, Path(path).read_text(errors="replace")) for name, path in files["lenses"].items()}
    short = Doc(files["shortlist"], Path(files["shortlist"]).read_text(errors="replace")) if "shortlist" in files else None
    findings, leads = result["findings"], result["leads"]
    fcount = [0]
    lcount = [0]

    def add_finding(*args, **kw):
        fcount[0] += 1
        findings.append(finding(f"C{fcount[0]}", *args, **kw))

    def add_lead(criterion, kind, candidate, path, line, text, detail, **extra):
        lcount[0] += 1
        leads.append({"id": f"L{lcount[0]}", "criterion": criterion, "type": kind, "candidate": candidate or "*",
                      "file": path, "line": line, "text": text, "detail": detail, **extra})

    # Candidates: the shortlist's, the table's, the sections', the ranking's.
    listed = shortlist_candidates(short) if short else []
    table = parse_table(card)
    rows = table["rows"] if table else []
    result["money_signal"] = table["money_name"] if table else None
    if not table:
        result["unknown"]["Q1"] = "no scorecard table with search, jobs/money, pain, competitors and weighted columns"
        result["unknown"]["Q2"] = result["unknown"]["Q1"]
    if not listed:
        result["unknown"].setdefault("Q1", "no candidates read from the shortlist (expected 'CANDIDATE <id> - name', 'REFERENCE - name' or 'V1 - name' lines)")
    known = {c["id"] for c in listed} | {r["id"] for r in rows if r["id"]}
    for row in rows:
        check_row(row)
    rows_by_id: dict[str, list] = {}
    for row in rows:
        rows_by_id.setdefault(row["id"], []).append(row)
    card_sections = section_ids(card, known)
    section_heads = sorted({s for s in card_sections if s})
    named = [(c["id"], c["name"]) for c in listed] + [(r["id"], r["name"]) for r in rows if r["id"]]
    ranking = parse_ranking(card, named, known)
    if ranking:
        check_ranking(ranking, rows_by_id)
    arith = arithmetic_lines(card, card_sections, known)
    for entry in arith:
        check_arithmetic(entry, rows_by_id)
    result["candidates"] = {
        "shortlist": [{k: c[k] for k in ("id", "name", "line")} for c in listed],
        "table": [r["id"] for r in rows],
        "sections": section_heads,
        "ranking": [e["id"] for e in ranking["entries"]] if ranking else None,
    }
    result["rows"] = rows
    result["arithmetic"] = arith
    result["ranking"] = ranking

    # Q1: each shortlist candidate once in the table, a section of its own, one ranking entry.
    if table and listed:
        ranking_ids = [e["id"] for e in ranking["entries"]] if ranking else []
        for cand in listed:
            missing = []
            if cand["id"] not in rows_by_id:
                missing.append("the scorecard table")
            if cand["id"] not in section_heads:
                missing.append("the per-idea sections")
            if ranking is not None and cand["id"] not in ranking_ids:
                missing.append("the ranking")
            if missing:
                add_finding("Q1", cand["id"], "missing_candidate",
                            f"shortlist candidate {cand['id']} ({clip(cand['name'], 80)})",
                            f"not found in {', '.join(missing)}",
                            [{"file": files["shortlist"], "text": cand["text"]}])
        for cid, same in rows_by_id.items():
            if len(same) > 1:
                add_finding("Q1", cid, "duplicate", f"candidate {cid} has {len(same)} table rows",
                            "a candidate must appear exactly once in the table",
                            [{"file": files["scorecard"], "text": r["text"]} for r in same])
        if ranking:
            seen: dict = {}
            for e in ranking["entries"]:
                if e["id"]:
                    seen.setdefault(e["id"], []).append(e)
            for cid, same in seen.items():
                if len(same) > 1:
                    add_finding("Q1", cid, "duplicate", f"candidate {cid} has {len(same)} ranking entries",
                                "a candidate must have exactly one ranking entry",
                                [{"file": files["scorecard"], "text": e["text"]} for e in same])
            for e in ranking["entries"]:
                if not e["id"]:
                    add_lead("Q1", "ranking_entry_unmatched", None, files["scorecard"], e["line"], e["text"],
                             "a ranking entry that matches no candidate by id or name")
        listed_ids = {c["id"] for c in listed}
        for row in rows:
            if row["id"] not in listed_ids:
                add_lead("Q1", "row_not_on_shortlist", row["id"] or None, files["scorecard"], row["line"], row["text"],
                         "a table row that is not a shortlist candidate: is it labelled as such?")
    elif table and not listed:
        for cid, same in rows_by_id.items():
            if len(same) > 1:
                add_finding("Q1", cid, "duplicate", f"candidate {cid} has {len(same)} table rows",
                            "a candidate must appear exactly once in the table",
                            [{"file": files["scorecard"], "text": r["text"]} for r in same])

    # Q2: cells, totals, confidence, arithmetic lines, ranking.
    unparsed = [r for r in rows if any(p["kind"] == "unparsed" for p in r["problems"])]
    if unparsed:
        result["unknown"]["Q2"] = "table rows not fully read: " + "; ".join(
            f"line {r['line']}: " + ", ".join(p["detail"] for p in r["problems"] if p["kind"] == "unparsed") for r in unparsed)
    for row in rows:
        material = [p for p in row["problems"] if p["kind"] in ("raw", "multiplier", "cell", "total", "confidence")]
        if material:
            kinds = sorted({p["kind"] for p in material})
            add_finding("Q2", row["id"] or "*", "arithmetic" if set(kinds) - {"confidence"} else "confidence",
                        f"table row for {row['id']}: " + clip(row["text"], 200),
                        "; ".join(p["detail"] for p in material),
                        [{"file": files["scorecard"], "text": row["text"]}])
        for p in row["problems"]:
            if p.get("minor"):
                add_finding("Q2", row["id"] or "*", "confidence", f"table row for {row['id']}", p["detail"],
                            [{"file": files["scorecard"], "text": row["text"]}], severity="minor")
    for entry in arith:
        if entry["problems"]:
            add_finding("Q2", entry["id"] or "*", "arithmetic", f"arithmetic line for {entry['id']}",
                        "; ".join(entry["problems"]),
                        [{"file": files["scorecard"], "text": card.lines[k - 1]} for k in entry["lines"]])
    if ranking:
        for e in ranking["entries"]:
            if e.get("problems"):
                add_finding("Q2", e["id"] or "*", "ranking", f"ranking entry {e['rank']}: {clip(e['text'], 160)}",
                            "; ".join(e["problems"]), [{"file": files["scorecard"], "text": e["text"]}])
    elif table:
        result["unknown"].setdefault("Q2", "no RANKING section found")

    # Q3: figures, quotes and URLs of the scorecard, traced to the lens files.
    sources = dict(lens_docs)
    if short:
        sources["shortlist"] = short
    index: dict[tuple, list] = {}
    for name, doc in sources.items():
        for f, n in doc_figures(doc):
            index.setdefault((f["kind"], round(f["value"], 4)), []).append((name, n))
    lens_sections = {name: section_ids(doc, known) for name, doc in lens_docs.items()}

    def locate(f, sec):
        hits = index.get((f["kind"], round(f["value"], 4)))
        if hits or f["kind"] != "pct" or not sec:
            return hits
        # A rounded percentage traces only to a figure of the same candidate: '58%' of one
        # candidate is not another candidate's '57.7%'.
        near = []
        for (kind, value), where in index.items():
            if kind == "pct" and round(value, f["decimals"]) == f["value"]:
                near.extend((name, ln) for name, ln in where
                            if name in lens_sections and lens_sections[name][ln - 1] == sec)
        return near or None

    traced_figures = []
    table_lines = set(range(table["header_line"], table["end_line"] + 1)) if table else set()
    arith_lines = {k for e in arith for k in e["lines"]}
    figure_leads = []
    for f, n in doc_figures(card):
        line = card.flat_lines[n - 1]
        if n in table_lines or n in arith_lines:
            continue
        hits = locate(f, card_sections[n - 1])
        if not hits:
            figure_leads.append((n, line, f))
            continue
        name, ln = hits[0]
        where = sources[name]
        traced_figures.append({"figure": f["text"], "line": n, "candidate": card_sections[n - 1] or "*",
                               "card": clip(line, 240), "lens": f"{where.path}:{ln}",
                               "lens_section": lens_sections[name][ln - 1] if name in lens_sections else "shortlist",
                               "lens_text": clip(" ".join(where.flat_lines[ln - 1:ln + 1]), 300)})
    for n, _line, f in figure_leads[:LEAD_CAP]:
        add_lead("Q3", "untraced_figure", card_sections[n - 1], files["scorecard"], n, card.lines[n - 1],
                 f"{f['text']} is in no lens file or the shortlist (under any notation the checker reads): "
                 "unsupported, or derived from the report's own numbers, or restated?",
                 figure=f["text"], value=f["value"], figure_kind=f["kind"], decimals=f["decimals"])
    if len(figure_leads) > LEAD_CAP:
        result["problems"].append(f"{len(figure_leads) - LEAD_CAP} more untraced figures not listed as leads")

    lens_norm = {name: qnorm(doc.text) for name, doc in lens_docs.items()}
    lens_shingles = {name: shingles(text.split()) for name, text in lens_norm.items()}
    traced_quotes = []
    for q in quotes(card):
        target = qnorm(q["text"])
        sec = card_sections[q["line"] - 1]
        where = []
        for name, text in lens_norm.items():
            doc = lens_docs[name]
            parts = [p.strip() for p in target.split("...") if p.strip()]
            parts = [p for p in parts if len(p.split()) >= 3] or [target]
            first = None
            ok = True
            for part in parts:
                at = text.find(part)
                if at < 0:
                    ok = False
                    break
                first = at if first is None else first
            if ok and first is not None:
                # Every occurrence of the first part, for the sections it sits in.
                at = text.find(parts[0])
                while at >= 0:
                    line_no = locate_line(doc, text, at)
                    where.append((name, line_no))
                    at = text.find(parts[0], at + 1)
        if where:
            secs = sorted({lens_sections[name][ln - 1] or "-" for name, ln in where})
            name, ln = where[0]
            item = {"quote": clip(q["text"], 200), "line": q["line"], "candidate": sec or "*",
                    "lens": f"{lens_docs[name].path}:{ln}", "lens_sections": secs,
                    "lens_text": clip(" ".join(lens_docs[name].lines[max(0, ln - 2):ln + 1]), 320)}
            traced_quotes.append(item)
            if sec and sec not in secs and any(s != "-" for s in secs):
                add_lead("Q3", "quote_from_other_candidate", sec, files["scorecard"], q["line"], card.lines[q["line"] - 1],
                         f"this quote sits in {sec}'s section but the lens has it only under {', '.join(s for s in secs if s != '-')} "
                         f"({lens_docs[name].path}:{ln}): moved to another candidate, venue, date or speaker?",
                         quote=q["text"], lens_location=f"{lens_docs[name].path}:{ln}")
            continue
        words = target.split()
        best, best_score = None, 0.0
        for name, sh in lens_shingles.items():
            mine = shingles(words)
            if not mine:
                continue
            score = len(mine & sh) / len(mine)
            if score > best_score:
                best, best_score = name, score
        kind = "near_quote" if best_score >= 0.5 else "untraced_quote"
        detail = (f"close to text in {lens_docs[best].path} ({best_score:.0%} of its 4-word runs) but not verbatim: "
                  "a light paraphrase, or altered so it says something the lens does not?") if kind == "near_quote" else (
            "this quoted text is in no lens file: the report's own framing words, or an unsupported quote?")
        add_lead("Q3", kind, sec, files["scorecard"], q["line"], card.lines[q["line"] - 1], detail, quote=q["text"])

    lens_urls = {norm_url(u) for doc in sources.values() for u in URL.findall(doc.text)}
    for n, line in enumerate(card.flat_lines, 1):
        for u in URL.findall(line):
            key = norm_url(u)
            if key in lens_urls or any(k.startswith(key) or key.startswith(k) for k in lens_urls if len(k) > 12):
                continue
            add_lead("Q3", "untraced_url", card_sections[n - 1], files["scorecard"], n, card.lines[n - 1],
                     f"{u} is in no lens file", url=u)

    # Q4: what the lens files record as blocked, empty or unverified, and the scorecard's absence claims.
    blocked: dict[str, list] = {}
    blocked_venues: dict[str, set] = {}
    for name, doc in lens_docs.items():
        for n, line in enumerate(doc.flat_lines, 1):
            if BLOCKED.search(line):
                cid = lens_sections[name][n - 1] or "*"
                blocked.setdefault(cid, []).append({"file": doc.path, "line": n, "text": clip(line, 260)})
                blocked_venues.setdefault(cid, set()).update(venues_in(line))
    absence_lines = []
    for n, line in enumerate(card.flat_lines, 1):
        if n in table_lines:
            continue
        sec = card_sections[n - 1]
        if ABSENCE.search(line):
            absence_lines.append(n)
            add_lead("Q4", "absence_claim", sec, files["scorecard"], n, card.lines[n - 1],
                     "an absence or no-demand statement: honest about what was searched and what was blocked "
                     "(see the lens records below), or does it present a gap as measured absence?")
        venues = blocked_venues.get(sec or "", set()) | blocked_venues.get("*", set())
        hit = sorted(v for v in venues if mentions(line, v))
        if hit and READ_VERB.search(line) and not BLOCKED.search(line) and n not in absence_lines:
            add_lead("Q4", "blocked_source_described", sec, files["scorecard"], n, card.lines[n - 1],
                     f"names {', '.join(hit)}, which the lens files record as blocked, empty or unverified, next to a "
                     "read/checked verb: presented as read?", venues=hit)

    # Q5: scope words next to a traced figure that its lens passage does not have, and a jobs
    # signal (employers' paid work) counted for a candidate whose buyer is a consumer.
    scope_leads = 0
    for item in traced_figures:
        n = item["line"]
        card_window = " ".join(card.flat_lines[n - 1:n + 1])
        path, ln = item["lens"].rsplit(":", 1)
        doc = next((d for d in sources.values() if d.path == path), None)
        lens_window = " ".join(doc.flat_lines[max(0, int(ln) - 3):int(ln) + 2]).lower() if doc else ""
        extra = sorted({w.lower() for w in SCOPE_WORDS.findall(card_window)} - {
            w.lower() for w in SCOPE_WORDS.findall(lens_window)})
        if extra and scope_leads < LEAD_CAP:
            scope_leads += 1
            add_lead("Q5", "scope_words", item["candidate"], files["scorecard"], n, card.lines[n - 1],
                     f"{item['figure']} comes from {item['lens']}, but the scorecard adds {', '.join(repr(w) for w in extra)} "
                     "near it, which the lens passage does not say: same population, denominator and payer?",
                     figure=item["figure"], lens_location=item["lens"], lens_text=item["lens_text"])
    if result.get("money_signal") == "jobs":
        consumer = {c["id"]: c for c in listed if CONSUMER.search(c["name"])}
        for n, line in enumerate(card.flat_lines, 1):
            cid = card_sections[n - 1]
            if cid in consumer and re.match(r"^[-*\s]*jobs\b", line, re.I):
                add_lead("Q5", "jobs_for_consumer", cid, files["scorecard"], n, card.lines[n - 1],
                         f"{cid}'s buyer is a consumer ({files['shortlist']}:{consumer[cid]['line']}), but the "
                         "jobs signal counts employers' postings and salaries for people who do the task by hand: "
                         "another payer's money. Does this candidate's own scorecard text say the payer differs "
                         "and treat it as a proxy? A shortlist naming those workers, the lens calling the postings "
                         "an exact match, or a report-wide proxy caveat is not that label. Unlabelled and "
                         "supporting the score, confidence or recommendation, it is a material payer_mismatch "
                         "(rubric Q5).")

    # Q6: adjacency wording in the competitors lens next to a competitors score of 2 or 3.
    comp = next((doc for name, doc in lens_docs.items() if name.startswith("compet")), None)
    if comp is not None and rows:
        comp_sections = lens_sections[Path(comp.path).stem]
        for row in rows:
            cell = row["cells"].get("competitors")
            if not cell or cell["raw"] < 2:
                continue
            lines = [n for n, line in enumerate(comp.flat_lines, 1)
                     if comp_sections[n - 1] == row["id"] and ADJACENT.search(line)]
            if lines:
                add_lead("Q6", "adjacent_wording_in_lens", row["id"], files["scorecard"], row["line"], row["text"],
                         f"competitors {fmt(cell['raw'])}\u00d7{fmt(cell['mult'])} for {row['id']}, while its competitors lens "
                         "section calls some players adjacent, general, bundled or not purpose-built: are those counted as "
                         "exact sellers, or labelled?",
                         lens_lines=[{"file": comp.path, "line": n, "text": clip(comp.lines[n - 1], 260)} for n in lines[:6]])

    players = required_players(short) if short else None
    if players:
        searched = [card.text] + ([comp.text] if comp is not None else [])
        covered, missing = {}, []
        for name in players["listed"]:
            where = [k for k in player_keys(name) if any(mentions(t, k) for t in searched)]
            covered[name] = bool(where)
            if not where:
                missing.append(name)
        players.update({"covered": covered, "missing": missing,
                        "searched": [files["scorecard"]] + ([comp.path] if comp is not None else [])})
        if missing:
            add_finding("Q6", "*", "missing_player", f"the shortlist asks to check {len(players['listed'])} players",
                        f"{len(missing)} appear in neither the competitors lens nor the scorecard: {', '.join(missing)}",
                        [{"file": files["shortlist"], "text": players["text"]}])
    result["players"] = players
    result["evidence"] = {"figures": traced_figures, "quotes": traced_quotes, "blocked": blocked,
                          "absence_lines": absence_lines}
    result["status"] = "checked"
    return result


def locate_line(doc: Doc, lowered: str, at: int) -> int:
    """Line of an offset into qnorm(doc.text): qnorm only drops quote marks and edges, so map
    through the share of the text before it."""
    prefix_words = len(lowered[:at].split())
    count = 0
    for n, line in enumerate(doc.flat_lines, 1):
        count += len(qnorm(line).split()) if line else 0
        if count > prefix_words:
            return n
    return len(doc.lines)


# ---- the packet the reviewer reads ---------------------------------------------------------------

def write_packet(result: dict, out: Path) -> None:
    files = result["files"]
    lines = ["# Deterministic check (signal_grade/1)", "",
             "Read this with rubric.md. It proves the arithmetic and the coverage, and traces figures, quotes and",
             "URLs to the lens files by text only: it does NOT prove that cited evidence says what a claim says.", "",
             "## Files (cite passages from these paths only)", ""]
    for p in report_paths(files):
        lines.append(f"- {p}")
    lines += ["", "## Candidates", ""]
    cands = result.get("candidates") or {}
    for c in cands.get("shortlist", []):
        lines.append(f"- {c['id']}: {c['name']} (shortlist line {c['line']})")
    lines += ["", f"Table rows: {', '.join(cands.get('table') or []) or 'none'}; sections: "
              f"{', '.join(cands.get('sections') or []) or 'none'}; ranking: {', '.join(str(x) for x in (cands.get('ranking') or [])) or 'none'}"]
    lines += ["", f"## Recomputed rows (money signal: {result.get('money_signal')})", "",
              "| id | cells (raw x mult = disc) | shown | computed | overall | rule allows |", "|---|---|---|---|---|---|"]
    for r in result.get("rows", []):
        cells = ", ".join(f"{s} {c['text']}" if c else f"{s} ?" for s, c in r["cells"].items())
        rule = r.get("confidence_rule", {})
        lines.append(f"| {r['id']} | {cells} | {fmt(r['weighted'])} | {fmt(r.get('computed'))} | {r['overall']} | "
                     f"{'/'.join(rule.get('allowed', [])) or '?'} |")
    lines += ["", "## Deterministic findings (already counted; do not repeat them)", ""]
    for f in result["findings"]:
        lines.append(f"- {f['id']} {f['criterion']} {f['candidate']} {f['kind']} ({f['severity']}): {f['problem']}")
    if not result["findings"]:
        lines.append("- none")
    if result.get("players"):
        p = result["players"]
        lines += ["", f"Required players ({len(p['listed'])}): {', '.join(p['listed'])}",
                  f"Missing from the competitors lens and the scorecard: {', '.join(p['missing']) or 'none'}"]
    if result["unknown"]:
        lines += ["", "## Not checkable by the script", ""] + [f"- {k}: {v}" for k, v in result["unknown"].items()]
    lines += ["", "## Leads you must resolve, every one (ok with a reason, or a finding)", ""]
    for lead in result["leads"]:
        lines.append(f"- {lead['id']} [{lead['criterion']} {lead['type']}, candidate {lead['candidate']}] "
                     f"{lead['file']}:{lead['line']}: {clip(lead['text'], 300)}")
        lines.append(f"  -> {lead['detail']}")
        for extra in lead.get("lens_lines", []):
            lines.append(f"     lens {extra['file']}:{extra['line']}: {extra['text']}")
    if not result["leads"]:
        lines.append("- none")
    ev = result.get("evidence", {})
    lines += ["", "## Evidence map: scorecard figures and where the lens files have them", "",
              "(Use it for Q3 attribution and Q5 scope: same candidate, payer, population, denominator, date?)", ""]
    for f in ev.get("figures", []):
        lines.append(f"- [{f['candidate']}] card {f['line']}: {f['figure']} | lens {f['lens']} [{f['lens_section'] or '-'}]: {f['lens_text']}")
    lines += ["", "## Quotes traced to the lens files", ""]
    for q in ev.get("quotes", []):
        lines.append(f"- [{q['candidate']}] card {q['line']}: \"{q['quote']}\" | lens {q['lens']} sections {', '.join(q['lens_sections'])}: {q['lens_text']}")
    lines += ["", "## What the lens files record as blocked, empty or unverified", ""]
    for cid, items in sorted(ev.get("blocked", {}).items()):
        lines.append(f"### {cid}")
        for item in items[:25]:
            lines.append(f"- {item['file']}:{item['line']}: {item['text']}")
        if len(items) > 25:
            lines.append(f"- ... {len(items) - 25} more")
    out.write_text("\n".join(lines) + "\n")


def cmd_check(args) -> int:
    report_dir = Path(args.report_dir)
    GRADE_DIR.mkdir(parents=True, exist_ok=True)
    result = run_check(report_dir)
    (GRADE_DIR / "check.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    write_packet(result, GRADE_DIR / "check.md")
    print(json.dumps({"status": result["status"], "check_path": str(GRADE_DIR / "check.md"),
                      "rows": len(result.get("rows", [])), "deterministic_findings": len(result["findings"]),
                      "leads": len(result["leads"]), "players_missing": (result.get("players") or {}).get("missing"),
                      "problems": result["problems"]}))
    return 0


# ---- verify ----------------------------------------------------------------------------------

KINDS_ABSENT = {"unsupported", "missing_player", "missing_candidate"}
NEEDS_EVIDENCE = {"Q3", "Q4", "Q5", "Q6"}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def safe_eval(expression: str) -> float:
    text = expression.replace("\u00d7", "*").replace("\u00f7", "/").replace("%", "")
    if not re.fullmatch(r"[\d.\s+\-*/()]+", text):
        raise ValueError("only numbers and + - * / ( ) are allowed")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        raise ValueError("unsupported expression")

    return ev(ast.parse(text, mode="eval"))


def resolve_file(name: str, files: dict) -> str | None:
    paths = report_paths(files)
    if name in paths:
        return name
    for p in paths:
        if p.endswith("/" + name.lstrip("./")) or Path(p).name == Path(name).name:
            return p
    return None


def canonical_candidate(value, known: set[str]) -> str | None:
    text = flat(str(value or "")).strip()
    if text in ("*", "all", "report", "report-wide", ""):
        return "*"
    m = ID_AT_START.match(text)
    if m and m.group(1) in known:
        return m.group(1)
    return text if text in known else None


def verify_passages(item: dict, files: dict, docs: dict) -> tuple[list, list]:
    good, bad = [], []
    for p in item.get("passages") or []:
        if not isinstance(p, dict) or not p.get("text"):
            bad.append("a passage without text")
            continue
        path = resolve_file(str(p.get("file", "")), files)
        if path is None:
            bad.append(f"file {p.get('file')!r} is not a report file")
            continue
        line = docs[path].find(p["text"])
        if line is None:
            bad.append(f"not found verbatim in {path}: {clip(p['text'], 120)!r}")
        else:
            good.append({"file": path, "line": line, "text": p["text"]})
    return good, bad


def absent_ok(item: dict, check: dict, docs: dict, good: list) -> str | None:
    """None when the alleged absence holds; otherwise why it does not. The report must state what
    is alleged missing from the evidence: a cited scorecard passage holds the figure, quote or URL,
    and a cited shortlist passage names a required player."""
    absent = flat(str(item.get("absent") or ""))
    if not absent:
        return "an absence allegation needs 'absent': the figure, quote, URL, player or candidate that is missing"
    files = check["files"]
    lens = [docs[p] for p in files.get("lenses", {}).values()]
    cited = {name: [flat(p["text"]) for p in good if p["file"] == files.get(name)] for name in ("scorecard", "shortlist")}
    kind = item.get("kind")
    if kind == "missing_player":
        if files.get("shortlist") and not any(mentions(t, k) for t in cited["shortlist"] for k in player_keys(absent)):
            return f"no cited shortlist passage names {absent!r} as a player to check"
        targets = [docs[files["scorecard"]]] + [d for d in lens if Path(d.path).stem.startswith("compet")]
        if any(mentions(d.text, k) for d in targets for k in player_keys(absent)):
            return f"{absent!r} is mentioned in the competitors lens or the scorecard"
        return None
    if kind == "missing_candidate":
        rows = {r["id"] for r in check.get("rows", [])}
        if canonical_candidate(item.get("candidate"), rows) in rows:
            return f"candidate {item.get('candidate')} has a table row"
        return None
    figs = figures(absent)
    if figs and len(absent.split()) <= 3:
        values = {(f["kind"], round(f["value"], 4)) for f in figs}
        if not any(values & {(f["kind"], round(f["value"], 4)) for f in figures(t)} for t in cited["scorecard"]):
            return f"no cited scorecard passage states {absent!r}"
        for d in lens:
            if values & {(f["kind"], round(f["value"], 4)) for f, _ in doc_figures(d)}:
                return f"{absent!r} is in {d.path}"
        return None
    if URL.match(absent):
        key = norm_url(absent)
        if not any(norm_url(u) == key for t in cited["scorecard"] for u in URL.findall(t)):
            return f"no cited scorecard passage holds {absent!r}"
        if any(norm_url(u) == key for d in lens for u in URL.findall(d.text)):
            return f"{absent!r} is in a lens file"
        return None
    target = qnorm(absent)
    if not any(target in qnorm(t) for t in cited["scorecard"]):
        return f"no cited scorecard passage holds {clip(absent, 80)!r}"
    if any(target in qnorm(d.text) for d in lens):
        return f"{clip(absent, 80)!r} is in a lens file"
    return None


def load_review() -> tuple[dict | None, str | None]:
    path = GRADE_DIR / "review.json"
    if not path.is_file():
        return None, "no review.json: the semantic review did not finish"
    text = path.read_text(errors="replace")
    if USAGE_LIMIT.search(text):
        return None, "review.json carries usage-limit text"
    try:
        review = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"review.json is not valid JSON: {exc}"
    if not isinstance(review, dict):
        return None, "review.json is not a JSON object"
    return review, None


def run_verify(check: dict) -> dict:
    files = check["files"]
    docs = {p: Doc(p, Path(p).read_text(errors="replace")) for p in report_paths(files) if Path(p).is_file()}
    known = {c["id"] for c in (check.get("candidates") or {}).get("shortlist", [])} | {
        r["id"] for r in check.get("rows", []) if r.get("id")}
    problems = list(check.get("problems", []))
    integrity = {p: {"before": h, "after": sha(Path(p)) if Path(p).is_file() else None}
                 for p, h in check.get("hashes", {}).items()}
    changed = [p for p, v in integrity.items() if v["before"] != v["after"]]
    review, review_problem = load_review()
    if review_problem:
        problems.append(review_problem)
    review = review or {}

    verified, unverified = [], []
    for f in check.get("findings", []):
        verified.append({**f, "passages": [{**p, "line": docs[p["file"]].find(p["text"])} for p in f["passages"]],
                         "verified": True})
    for raw in review.get("findings") or []:
        if not isinstance(raw, dict):
            continue
        f = {k: raw.get(k) for k in ("id", "criterion", "candidate", "kind", "severity", "claim", "problem", "absent")}
        f["source"] = "review"
        why = []
        if f["criterion"] not in CRITERIA:
            why.append(f"criterion {f['criterion']!r} is not Q1-Q6")
        cand = canonical_candidate(f["candidate"], known)
        if cand is None:
            why.append(f"candidate {f['candidate']!r} is not a candidate id or '*'")
        else:
            f["candidate"] = cand
        if f["severity"] not in ("material", "minor"):
            why.append("severity must be material or minor")
        if not f["claim"] or not f["problem"]:
            why.append("claim and problem are required")
        good, bad = verify_passages(raw, files, docs)
        why += bad
        if not good:
            why.append("no passage verified")
        f["passages"] = good
        if f["kind"] in KINDS_ABSENT:
            reason = absent_ok(f, check, docs, good)
            if reason:
                why.append(reason)
        elif f["criterion"] in NEEDS_EVIDENCE and not any(
                p["file"] != files.get("scorecard") for p in good):
            why.append("a finding against the evidence must cite the lens or shortlist passage it contradicts")
        if why:
            unverified.append({**f, "verified": False, "why": why, "passages": raw.get("passages")})
        else:
            verified.append({**f, "verified": True})
    found_ids = {f["id"] for f in verified if f.get("source") == "review"}

    resolutions = {}
    for r in review.get("leads") or []:
        if isinstance(r, dict) and r.get("id"):
            resolutions[str(r["id"])] = r
    leads_out, unresolved = [], []
    for lead in check.get("leads", []):
        r = resolutions.get(lead["id"])
        state, why = "unresolved", "no resolution in review.json"
        if r:
            res = r.get("resolution")
            if res == "finding":
                fid = str(r.get("finding") or "")
                if fid in found_ids:
                    state, why = "finding", fid
                else:
                    why = f"resolved as finding {fid!r}, which is not a verified finding"
            elif res == "ok":
                reason = r.get("why") or ""
                if not (r.get("note") or reason):
                    why = "ok needs a reason (why and note)"
                elif reason == "derived" and lead["type"] == "untraced_figure":
                    try:
                        value = safe_eval(str(r.get("expression") or ""))
                        tol = 0.5 * 10 ** -lead.get("decimals", 0) + 1e-9
                        target = lead.get("value", 0.0)
                        if abs(value - target) <= tol or (lead.get("figure_kind") == "pct" and abs(value * 100 - target) <= tol):
                            state, why = "ok", f"derived: {r.get('expression')} = {value:.4g}"
                        else:
                            why = f"derived expression gives {value:.4g}, the figure is {lead.get('figure')}"
                    except (ValueError, SyntaxError, ZeroDivisionError) as exc:
                        why = f"derived expression not computable: {exc}"
                else:
                    good, bad = verify_passages(r, files, docs)
                    if bad:
                        why = "; ".join(bad)
                    elif reason == "lens_restated" and not good:
                        why = "lens_restated needs the lens passage that has the figure"
                    else:
                        state, why = "ok", f"{reason}: {flat(str(r.get('note') or ''))}"
            else:
                why = f"resolution {res!r} is not ok or finding"
        out = {**lead, "resolution": state, "resolution_note": why}
        leads_out.append(out)
        if state == "unresolved":
            unresolved.append(out)

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
            if review_problem and c in ("Q3", "Q4", "Q5", "Q6"):
                reasons.append("no semantic review")
            elif not review_problem and said not in ("pass", "revise", "unknown"):
                reasons.append("the review gave no status")
            elif said == "unknown":
                reasons.append("the review could not check it: " + flat(str(claim.get("note") or "")))
            elif said == "revise":
                reasons.append("the review said revise but none of its findings verified")
            status = "unknown" if reasons else "pass"
        criteria[c] = {"name": CRITERION_NAMES[c], "status": status, "material": material, "minor": minor,
                       "unresolved_leads": open_leads, "why_unknown": reasons,
                       "review_note": flat(str(claim.get("note") or ""))}
    if changed:
        problems.append("report files changed during grading: " + ", ".join(changed))
    statuses = [v["status"] for v in criteria.values()]
    overall = "revise" if "revise" in statuses else ("unknown" if "unknown" in statuses else "pass")
    if changed and overall == "pass":
        overall = "unknown"
    limitations = [
        "Works from the report's files only: it never sees the pages behind the lens files, so an error inside a lens "
        "file, or a fabrication consistent across lens files and scorecard, is out of its reach.",
        "Figures, quotes and URLs are traced by text; whether a traced item keeps its meaning, payer, population and "
        "date rests on the semantic review, verified only by its verbatim passages.",
    ] + [flat(str(x)) for x in (review.get("limitations") or []) if x]
    return {"version": "signal_grade_quality/1", "rubric": RUBRIC_VERSION, "rubric_sha256": check.get("rubric_sha256"),
            "checker_sha256": check.get("checker_sha256"), "status": overall, "criteria": criteria,
            "findings": verified, "unverified": unverified, "leads": leads_out,
            "players": check.get("players"), "candidates": check.get("candidates"),
            "integrity": {"unchanged": not changed, "files": integrity},
            "deterministic": {"rows": [{k: r.get(k) for k in ("id", "line", "weighted", "computed", "overall",
                                                              "confidence_rule", "problems")} for r in check.get("rows", [])],
                              "arithmetic": [{k: e[k] for k in ("id", "line", "total", "computed", "problems")}
                                             for e in check.get("arithmetic", [])],
                              "ranking": check.get("ranking")},
            "limitations": limitations, "problems": problems}


def write_quality(q: dict, out: Path) -> None:
    lines = [f"# Signal report quality: {q['status'].upper()}", "",
             f"Rubric {q['rubric']} (sha256 {str(q.get('rubric_sha256'))[:12]}). This grades the report's soundness "
             "against its own evidence, not whether the market is good; it never rescores.", "",
             "| criterion | status | material findings | notes |", "|---|---|---|---|"]
    for c, v in q["criteria"].items():
        note = "; ".join(v["why_unknown"]) or v["review_note"]
        lines.append(f"| {c} {v['name']} | {v['status']} | {', '.join(v['material']) or '-'} | {clip(note, 200) if note else ''} |")
    lines += ["", "## Findings", ""]
    for f in q["findings"]:
        lines.append(f"### {f['id']} {f['criterion']} {f['candidate']} {f['kind']} ({f['severity']}, {f['source']})")
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
            lines.append(f"- {f.get('id')} {f.get('criterion')} {f.get('candidate')}: {flat(str(f.get('problem') or ''))} "
                         f"[{'; '.join(f['why'])}]")
    if q.get("players"):
        p = q["players"]
        lines += ["", f"## Required players: {len(p['listed']) - len(p['missing'])} of {len(p['listed'])} covered",
                  "", f"Missing: {', '.join(p['missing']) or 'none'}"]
    lines += ["", "## Leads", ""]
    for lead in q["leads"]:
        lines.append(f"- {lead['id']} {lead['criterion']} {lead['type']} [{lead['candidate']}] line {lead['line']}: "
                     f"{lead['resolution']} ({clip(lead['resolution_note'], 160)})")
    if not q["leads"]:
        lines.append("None.")
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in q["limitations"]]
    lines += ["", f"Integrity: report files {'unchanged' if q['integrity']['unchanged'] else 'CHANGED'} by grading."]
    if q["problems"]:
        lines += ["", "## Problems", ""] + [f"- {x}" for x in q["problems"]]
    out.write_text("\n".join(lines) + "\n")


def cmd_verify(args) -> int:
    check_path = GRADE_DIR / "check.json"
    if not check_path.is_file():
        print(json.dumps({"status": "completed", "quality_status": "unknown", "quality_path": "",
                          "criteria": {}, "findings": 0, "unverified": 0, "players_missing": None,
                          "problems": ["no check.json: the deterministic check did not run"]}))
        return 0
    check = json.loads(check_path.read_text())
    q = run_verify(check)
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
    print(json.dumps({"status": "completed", "quality_status": q["status"], "quality_path": str(GRADE_DIR / "quality.md"),
                      "criteria": {c: v["status"] for c, v in q["criteria"].items()},
                      "findings": len([f for f in q["findings"] if f["severity"] == "material"]),
                      "unverified": len(q["unverified"]),
                      "players_missing": (q.get("players") or {}).get("missing"), "problems": q["problems"]}))
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
    p = sub.add_parser("check")
    p.add_argument("--report-dir", default="state")
    p = sub.add_parser("verify")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("passage")
    p.add_argument("file")
    p.add_argument("text")
    args = parser.parse_args(argv)
    return {"check": cmd_check, "verify": cmd_verify, "passage": cmd_passage}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
