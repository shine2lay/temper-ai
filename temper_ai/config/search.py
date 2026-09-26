"""Find a workflow by what it does.

Temper holds hundreds of workflows, and a person (or an agent picking one
for them) knows what they want done, not what it is called. This matches
the words of a query against each workflow's name, description, and the
names and descriptions of its inputs, and ranks the hits: a word in the
name counts for most, so ``search("linear reply")`` puts ``linear_reply``
first, then workflows that only mention Linear in their description.

It reads the stored configs raw, without resolving ``${VAR}`` references:
a workflow whose config needs an environment variable that is not set is
still findable (reading it through ``ConfigStore.get`` would raise).

Workflows with no description can only be found by name, so every result
set also lists them (``undescribed``): the cue to write one.

The same search backs ``GET /api/workflows/search``, the MCP tool
``search_workflows``, Slack's ``/temper search`` and the workflow @temper
picks from plain words.
"""

from __future__ import annotations

import re
from typing import Any

# Words that say nothing about which workflow is meant.
STOPWORDS = frozenset(
    "a an and are as at be by can could do does for from i in into is it its me my of on or "
    "please should that the them this to up us we what when which with would you your "
    "workflow workflows".split()
)

NAME_WORD = 10.0      # the word is a word of the name (linear in linear_reply)
NAME_PART = 6.0       # the word is inside the name (lin in linear_reply)
DESCRIPTION = 3.0     # the word is in the description
INPUT = 2.0           # the word is an input's name or in its description
ALL_WORDS = 2.0       # bonus: every query word was found somewhere

_WORD = re.compile(r"[a-z0-9]+")


def words(text: Any) -> list[str]:
    """Lowercase alphanumeric words; ``linear_reply``/``LinearReply`` both split."""
    if not text:
        return []
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
    return _WORD.findall(spaced.lower())


def stem(word: str) -> str:
    """Crude English stemming, enough that "reviews" finds "review" and
    "planning" finds "plan"."""
    for suffix in ("ings", "ing", "ies", "ied", "es", "ed", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            base = word[: -len(suffix)]
            if suffix in ("ies", "ied"):
                return base + "y"
            if len(base) > 3 and base[-1] == base[-2]:  # planning -> plann -> plan
                base = base[:-1]
            return base
    return word


def query_words(query: str) -> list[str]:
    seen: list[str] = []
    for w in words(query):
        if w not in STOPWORDS and w not in seen:
            seen.append(w)
    return seen


def _inputs_of(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Declared inputs, modern (mapping of specs) or shorthand (name: type)."""
    inputs: dict[str, dict[str, Any]] = {}
    raw = body.get("inputs") or {}
    if not isinstance(raw, dict):
        return inputs
    for key, spec in raw.items():
        if isinstance(spec, dict):
            inputs[str(key)] = {
                "type": str(spec.get("type", "string")),
                "required": bool(spec.get("required", False)),
                "description": str(spec.get("description") or "").strip(),
            }
            if spec.get("default") is not None:
                inputs[str(key)]["default"] = spec["default"]
        else:
            inputs[str(key)] = {"type": str(spec), "required": False, "description": ""}
    return inputs


def catalog(store: Any = None) -> list[dict[str, Any]]:
    """Every stored workflow: name, description and declared inputs.

    ``store`` is unused beyond telling tests apart from production: the
    rows are read straight from the configs table, in one query.
    """
    from sqlmodel import select

    from temper_ai.config.models import Config
    from temper_ai.database import get_session

    del store
    with get_session() as session:
        rows = session.exec(
            select(Config.name, Config.config).where(Config.type == "workflow").order_by(Config.name)
        ).all()
    entries = []
    for name, raw in rows:
        body = raw.get("workflow", raw) if isinstance(raw, dict) else {}
        if not isinstance(body, dict):
            body = {}
        entries.append({
            "name": str(name),
            "description": str(body.get("description") or "").strip(),
            "inputs": _inputs_of(body),
        })
    return entries


def score(entry: dict[str, Any], qwords: list[str]) -> tuple[int, float, list[str]]:
    """(name-word hits, total score, which words matched where)."""
    name = entry["name"].lower()
    name_words = set(words(entry["name"]))
    name_stems = {stem(w) for w in name_words}
    desc_words = words(entry.get("description"))
    desc_set = set(desc_words) | {stem(w) for w in desc_words}
    input_words: set[str] = set()
    for key, spec in (entry.get("inputs") or {}).items():
        for w in words(key) + words(spec.get("description")):
            input_words.add(w)
            input_words.add(stem(w))

    name_hits = 0
    total = 0.0
    matched: list[str] = []
    found = 0
    for q in qwords:
        s = stem(q)
        hit = False
        if q in name_words or s in name_stems:
            name_hits += 1
            total += NAME_WORD
            matched.append(f"{q}:name")
            hit = True
        elif len(q) >= 3 and q in name:
            total += NAME_PART
            matched.append(f"{q}:name")
            hit = True
        if q in desc_set or s in desc_set:
            total += DESCRIPTION
            matched.append(f"{q}:description")
            hit = True
        if q in input_words or s in input_words:
            total += INPUT
            matched.append(f"{q}:inputs")
            hit = True
        found += hit
    if qwords and found == len(qwords) and total:
        total += ALL_WORDS
    return name_hits, total, matched


def search_workflows(query: str, limit: int = 10, entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Workflows matching ``query``, best first.

    An empty query (or one of stopwords only) returns every workflow, by
    name. Each result carries its score and which words matched where, so
    a caller can say why it was picked.
    """
    entries = catalog() if entries is None else entries
    qwords = query_words(query or "")
    undescribed = sorted(e["name"] for e in entries if not e["description"])
    if not qwords:
        results = [dict(e, score=0.0, matched=[]) for e in sorted(entries, key=lambda e: e["name"])]
    else:
        ranked = []
        for e in entries:
            name_hits, total, matched = score(e, qwords)
            if total > 0:
                ranked.append((name_hits, total, e, matched))
        ranked.sort(key=lambda r: (-r[0], -r[1], r[2]["name"]))
        results = [dict(e, score=round(total, 1), matched=matched) for _, total, e, matched in ranked]
    total_found = len(results)
    return {
        "query": query or "",
        "words": qwords,
        "results": results[: max(int(limit), 1)] if limit else results,
        "total": total_found,
        "undescribed": undescribed,
    }


def first_line(text: str, max_chars: int = 140) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line if len(line) <= max_chars else line[: max_chars - 1].rstrip() + "…"
