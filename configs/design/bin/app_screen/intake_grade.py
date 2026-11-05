"""Grade one intake run against a case's answer key (host command grade-intake). Model-free.

A case folder holds sources.json (what the run was given) and expected.json, written before any run:

    {"case": "...", "product": "...", "written": "<when, by whom>",
     "key": [{"id": "K1", "what": "...", "items": ["S1", "S9"], "must": [["buying power"], ["net liq"]]}],
     "questions_needed": [{"id": "N1", "what": "...", "any": ["<regex>", ...], "about": ["S1"]}],
     "min_open_questions": 0,
     "conflicts": [{"id": "X1", "items": ["S2", "S10"], "any": ["simulated"]}],
     "specifics": {"forbidden_terms": ["colour", ...], "maps_to_must": ["settings"]}}

A key point is met when one requirement on one of its items has, in its means and maps_to (never his
quoted words, which would meet it by copying), a term from every must group (case-insensitive parts of
words). A needed question is met by an open question matching one regex (and about those items). A
conflict is asked when an open question is about all its items and names it; a requirement on a conflict
item that does not list that question in open_questions is a silent pick. A specific is a forbidden term
no source says, in a requirement's means or maps_to, or a maps_to without a must word.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import contracts, intake_check
from .workspace import Workspace

BARS = {"coverage": 1.0, "invented": 0, "unsourced": 0, "not_verbatim": 0}


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _distinct(fits: list[list[int]]) -> list[int | None]:
    """Give each needed question a different asked question, as many as can be (small sets: try them all)."""
    best: list[int | None] = [None] * len(fits)

    def walk(i: int, used: set[int], picked: list[int | None]) -> None:
        nonlocal best
        if i == len(fits):
            if sum(p is not None for p in picked) > sum(p is not None for p in best):
                best = list(picked)
            return
        for j in fits[i]:
            if j not in used:
                walk(i + 1, used | {j}, picked + [j])
        walk(i + 1, used, picked + [None])

    walk(0, set(), [])
    return best


def _stated(req: dict) -> str:
    return " ".join([str(req.get("means") or "")] + [str(m) for m in req.get("maps_to") or []]).lower()


def grade(case_dir: Path | str, workspace: Path | str) -> dict:
    case_dir, ws = Path(case_dir), Workspace(workspace)
    expected = _read(case_dir / "expected.json")
    case_sources = _read(case_dir / "sources.json")
    if expected is None or case_sources is None:
        raise ValueError(f"{case_dir}: needs sources.json and expected.json")
    folder = ws.folder("intake")
    misses: list[str] = []
    run_sources = _read(folder / "sources.json")
    if run_sources != case_sources:
        misses.append("the run's 01-request/sources.json is not the case's sources.json")
    draft = _read(folder / "draft.json") or {}
    try:
        contracts.validate("intake", ws)
        final_ok = (folder / "check-final.json").is_file()
    except contracts.ContractError as exc:
        final_ok = False
        misses.append(f"final output: {str(exc)[:300]}")
    if not final_ok:
        misses.append("intake did not write a clean final output")
    found = intake_check.check_draft(case_sources, draft)
    counts = found["counts"]
    for name, bar in BARS.items():
        ok = counts[name] >= bar if name == "coverage" else counts[name] <= bar
        if not ok:
            misses.append(f"{name} {counts[name]} (bar {bar})")
    reqs = [r for r in draft.get("requirements") or [] if isinstance(r, dict)]
    questions = [q for q in draft.get("questions") or [] if isinstance(q, dict)]
    open_qs = [q for q in questions if q.get("status") == "open"]
    key_met = []
    for k in expected.get("key", []):
        hit = any(r.get("item") in k["items"] and all(any(t.lower() in _stated(r) for t in group) for group in k["must"])
                  for r in reqs)
        if hit:
            key_met.append(k["id"])
        else:
            misses.append(f"key {k['id']} not met: {k['what']}")
    needed = expected.get("questions_needed", [])
    fits = [[j for j, q in enumerate(open_qs) if any(re.search(rx, q.get("question", ""), re.I) for rx in n["any"])
             and set(n.get("about", [])) <= set(q.get("about") or [])] for n in needed]
    matched = _distinct(fits)
    needed_met = [n["id"] for n, j in zip(needed, matched, strict=True) if j is not None]
    misses += [f"question {n['id']} not asked (each needed question by a different question): {n['what']}"
               for n, j in zip(needed, matched, strict=True) if j is None]
    if len(open_qs) < expected.get("min_open_questions", 0):
        misses.append(f"open questions {len(open_qs)} (bar {expected['min_open_questions']})")
    conflicts_asked, silent = [], 0
    for c in expected.get("conflicts", []):
        asking = [q["id"] for q in open_qs if set(c["items"]) <= set(q.get("about") or [])
                  and any(t.lower() in q.get("question", "").lower() for t in c["any"])]
        if asking:
            conflicts_asked.append(c["id"])
        else:
            misses.append(f"conflict {c['id']} ({' vs '.join(c['items'])}) not asked as an open question")
        for r in reqs:
            if r.get("item") in c["items"] and not set(r.get("open_questions") or []) & set(asking):
                silent += 1
                misses.append(f"silent pick: {r.get('id')} on {r.get('item')} does not wait for the conflict question")
    specifics = 0
    spec = expected.get("specifics") or {}
    said = " ".join([case_sources.get("description", "")] + [f"{i['text']} {i.get('context', '')}"
                                                             for i in case_sources["items"]]).lower()
    for r in reqs:
        for term in spec.get("forbidden_terms", []):
            if term.lower() in _stated(r) and term.lower() not in said:
                specifics += 1
                misses.append(f"specific: {r.get('id')} states {term!r}, which nobody said")
        for m in r.get("maps_to") or []:
            if spec.get("maps_to_must") and not any(w.lower() in str(m).lower() for w in spec["maps_to_must"]):
                specifics += 1
                misses.append(f"specific: {r.get('id')} maps to {m!r}, a part nobody named")
    measures = {"final_ok": final_ok, "coverage": counts["coverage"], "invented": counts["invented"],
                "unsourced": counts["unsourced"], "not_verbatim": counts["not_verbatim"],
                "requirements": counts["requirements"], "questions": counts["questions"], "open": len(open_qs),
                "key": f"{len(key_met)}/{len(expected.get('key', []))}",
                "questions_needed": f"{len(needed_met)}/{len(expected.get('questions_needed', []))}",
                "conflicts_asked": f"{len(conflicts_asked)}/{len(expected.get('conflicts', []))}",
                "silent_picks": silent, "specifics": specifics,
                "revised": (folder / "draft-first.json").is_file()}
    first = _read(folder / "draft-first.json")
    if first is not None:
        measures["first_draft_problems"] = len(intake_check.check_draft(case_sources, first)["problems"])
    return {"case": expected.get("case", case_dir.name), "pass": not misses, "measures": measures, "misses": misses}
