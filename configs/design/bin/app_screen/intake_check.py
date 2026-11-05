"""Intake's measured checks: the model's draft held to the sources it was given. Model-free.

check_draft(sources, draft) returns {"verdict": "ok"|"retry", "counts": {...}, "problems": [...]}, each
problem {"check", "where", "problem"}. The checks:

    schema       the draft matches its contract (contracts.SCHEMAS["intake_draft"])
    ids          requirement and question ids unique; every open_questions id is a question
    unsourced    every requirement names a source item that exists; every question is about items that
                 exist; an answered question's answer_source is an item
    not_verbatim owner_words is an exact part of its item's text; an answer is an exact part of its
                 answer_source item's text
    coverage     every source item is in at least one requirement (item) or question (about)
    invented     a requirement's means and maps_to state no number that appears in no source (text,
                 context, source line or the product's description): no answer invented for an open point

outputs(sources, draft) turns a clean draft into requirements.json and questions.json, filling each
source line from the item (the model never writes one).
"""
from __future__ import annotations

import re
from typing import Any

from . import contracts

CHECKS = ("schema", "ids", "unsourced", "not_verbatim", "coverage", "invented")
NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
ITEM_REF = re.compile(r"\b[RQS]\d{1,3}\b")


def numbers(text: str) -> set[str]:
    """The numbers a text states (1,842 and 1842 alike), ignoring item ids such as S3 or Q2."""
    return {n.replace(",", "") for n in NUMBER.findall(ITEM_REF.sub(" ", text or ""))}


def source_numbers(sources: dict) -> set[str]:
    found = numbers(sources.get("description", ""))
    for item in sources.get("items", []):
        for key in ("text", "context", "source"):
            found |= numbers(item.get(key, ""))
    return found


def _dicts(value: Any) -> list[tuple[int, dict]]:
    return [(i, v) for i, v in enumerate(value) if isinstance(v, dict)] if isinstance(value, list) else []


def check_draft(sources: dict, draft: Any) -> dict:
    problems: list[dict] = []

    def add(check: str, where: str, problem: str) -> None:
        problems.append({"check": check, "where": where, "problem": problem})

    for line in contracts.check_json("intake_draft", draft, "draft.json"):
        _, where, reason = (line.split(": ", 2) + ["", ""])[:3]
        add("schema", where, reason)
    items = {item["id"]: item for item in sources["items"]}
    draft = draft if isinstance(draft, dict) else {}
    reqs = _dicts(draft.get("requirements"))
    questions = _dicts(draft.get("questions"))
    question_ids = [q.get("id") for _, q in questions]
    for kind, ids in (("requirement", [r.get("id") for _, r in reqs]), ("question", question_ids)):
        for dup in sorted({i for i in ids if i and ids.count(i) > 1}):
            add("ids", f"{kind}s", f"{kind} id {dup} is used more than once")
    covered: set[str] = set()
    allowed = source_numbers(sources)
    for i, r in reqs:
        where = f"requirements/{i}"
        item = items.get(r.get("item"))
        if item is None:
            add("unsourced", f"{where}/item", f"{r.get('id')}: item {r.get('item')!r} is not a source item "
                f"({', '.join(items)})")
        else:
            covered.add(item["id"])
            words = r.get("owner_words")
            if isinstance(words, str) and words and words not in item["text"]:
                add("not_verbatim", f"{where}/owner_words", f"{r.get('id')}: {words!r} is not an exact part of "
                    f"{item['id']}'s text; copy the words character for character")
        for q in r.get("open_questions") or []:
            if q not in question_ids:
                add("ids", f"{where}/open_questions", f"{r.get('id')}: {q} is not a question")
        stated = " ".join([str(r.get("means") or "")] + [str(m) for m in r.get("maps_to") or []])
        for n in sorted(numbers(stated) - allowed):
            add("invented", f"{where}", f"{r.get('id')}: states {n}, which no source says; ask a question instead")
    for i, q in questions:
        where = f"questions/{i}"
        for ref in q.get("about") or []:
            if ref in items:
                covered.add(ref)
            else:
                add("unsourced", f"{where}/about", f"{q.get('id')}: {ref!r} is not a source item")
        if q.get("status") == "answered":
            src = items.get(q.get("answer_source"))
            if src is None:
                add("unsourced", f"{where}/answer_source", f"{q.get('id')}: answer_source {q.get('answer_source')!r} "
                    "is not a source item")
            else:
                covered.add(src["id"])
                answer = q.get("answer")
                if isinstance(answer, str) and answer and answer not in src["text"]:
                    add("not_verbatim", f"{where}/answer", f"{q.get('id')}: {answer!r} is not an exact part of "
                        f"{src['id']}'s text")
    for missing in [i for i in items if i not in covered]:
        add("coverage", "items", f"{missing} is in no requirement or question: "
            f"{items[missing]['text'][:120]!r}")
    counts = {"items": len(items), "covered": len(covered & set(items)),
              "coverage": round(len(covered & set(items)) / len(items), 3) if items else 0.0,
              "requirements": len(reqs), "questions": len(questions),
              "open": sum(1 for _, q in questions if q.get("status") == "open"),
              "answered": sum(1 for _, q in questions if q.get("status") == "answered"),
              # problems per check; the coverage check's count is "uncovered" ("coverage" is the share covered)
              **{("uncovered" if c == "coverage" else c): sum(1 for p in problems if p["check"] == c) for c in CHECKS}}
    return {"verdict": "retry" if problems else "ok", "counts": counts, "problems": problems}


def outputs(sources: dict, draft: dict) -> tuple[dict, dict]:
    """requirements.json and questions.json from a draft that passed check_draft."""
    items = {item["id"]: item for item in sources["items"]}
    requirements = []
    for r in draft["requirements"]:
        out = {"id": r["id"], "owner_words": r["owner_words"], "source": items[r["item"]]["source"],
               "kind": r["kind"], "maps_to": r["maps_to"], "item": r["item"], "means": r["means"]}
        if r.get("open_questions"):
            out["open_questions"] = r["open_questions"]
        requirements.append(out)
    questions = []
    for q in draft["questions"]:
        out = {"id": q["id"], "question": q["question"], "status": q["status"], "about": q["about"], "why": q["why"]}
        if q.get("choices"):
            out["choices"] = q["choices"]
        if q["status"] == "answered":
            out["answer"] = q["answer"]
            out["answer_source"] = items[q["answer_source"]]["source"]
        questions.append(out)
    return {"product": sources["product"], "items": requirements}, {"questions": questions}
