"""Intake's sources: the owner's words as numbered items (S1, S2, ...), each verbatim with where it came from.

Collected on the host, because Temper's workers reach neither the Show&Tell server nor the dialog
records, into one sources document. The workflow gets it as its request_json input (or finds it already
in 01-request/sources.json):

    {"product": "rollcall", "description": "<the product in one line>", "items": [
      {"id": "S1", "kind": "request|comment|answer|history", "text": "<his words, verbatim>",
       "source": "<who said it where and when>", "context": "<what it points at, or the question asked>",
       "ref": {"doc_id": ..., "comment_id": ..., "number": ..., "version": ...}}]}

text is never edited: not trimmed, re-cased or spell-fixed, since every requirement's owner_words must be
an exact part of it. context is someone else's words (the element he commented on, the question Design
asked) and is never quoted as his. Model-free.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import contracts

SHOWTELL = "http://127.0.0.1:8650"
RECORDS = Path.home() / ".pi-web-ui/decisions/records.jsonl"
CONTEXT_LIMIT = 600
SENT_STATES = ("sent", "answered", "resolved")  # a draft comment was never sent, so it is not his yet


class SourcesError(ValueError):
    """The sources cannot be collected or are not a valid sources document; the message says which."""


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= CONTEXT_LIMIT else text[:CONTEXT_LIMIT - 1] + "…"


def _get_json(url: str) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SourcesError(f"cannot read {url}: {exc.__class__.__name__}: {exc}") from None


def request_item(text: str, source: str, context: str | None = None) -> dict:
    if not text or not text.strip():
        raise SourcesError("the request text is empty")
    if not source or not source.strip():
        raise SourcesError("the request needs its source (who asked, where, when)")
    item = {"kind": "request", "text": text, "source": source.strip()}
    if context:
        item["context"] = _clip(context)
    return item


def _anchor_text(anchor: dict | None) -> str:
    anchor = anchor or {}
    element = anchor.get("element") or {}
    text = element.get("text") or anchor.get("exact") or ""
    return text if text.strip() else f"element {element.get('selector') or '(none)'}"


def showtell_items(doc_id: str, versions: list[int] | None = None, base: str = SHOWTELL,
                   fetch: Callable[[str], Any] = _get_json) -> list[dict]:
    """The owner's sent comments on one Show&Tell document (all versions, or the ones named), in order."""
    doc = fetch(f"{base.rstrip('/')}/api/docs/{doc_id}")
    if not isinstance(doc, dict) or not isinstance(doc.get("comments"), list):
        raise SourcesError(f"Show&Tell {doc_id}: no comments list in the document record")
    title = doc.get("title") or doc_id
    picked = [c for c in doc["comments"] if isinstance(c, dict) and c.get("state") in SENT_STATES
              and (not versions or c.get("version") in versions)]
    if not picked:
        raise SourcesError(f"Show&Tell {doc_id}: no sent comments" + (f" on versions {versions}" if versions else ""))
    picked.sort(key=lambda c: (c.get("version") or 0, c.get("number") or 0))
    return [{"kind": "comment", "text": c["body"],
             "source": f"owner's Show&Tell comment #{c.get('number')} on {doc_id} v{c.get('version')}",
             "context": _clip(f'Show&Tell "{title}" v{c.get("version")}, on: "{_anchor_text(c.get("anchor"))}"'),
             "ref": {"doc_id": doc_id, "comment_id": c.get("comment_id"), "number": c.get("number"),
                     "version": c.get("version")}} for c in picked]


def _find_record(record_id: str, records: Path) -> dict:
    if not records.is_file():
        raise SourcesError(f"dialog records {records} not found")
    with records.open(encoding="utf-8") as handle:
        for line in handle:
            if record_id in line:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("id") == record_id:
                    return record
    raise SourcesError(f"dialog record {record_id} not in {records}")


def record_items(record_id: str, records: Path = RECORDS, question_ids: list[str] | None = None) -> list[dict]:
    """The owner's answers in one dialog record: his typed words, or the option labels he picked."""
    record = _find_record(record_id, records)
    if record.get("from") not in (None, "owner"):
        raise SourcesError(f"dialog record {record_id} is from {record.get('from')!r}, not the owner")
    when = record.get("at")
    day = datetime.fromtimestamp(when / 1000, UTC).strftime("%Y-%m-%dT%H:%MZ") if isinstance(when, (int, float)) else "?"
    out = []
    for q in record.get("questions") or []:
        if question_ids and q.get("id") not in question_ids:
            continue
        typed = q.get("typed") or ""
        picked = [p for p in q.get("picked") or [] if p]
        text = typed if typed.strip() else "; ".join(picked)
        if not text.strip():
            continue
        out.append({"kind": "answer", "text": text,
                    "source": f"owner's answer in dialog {record_id} ({q.get('header') or q.get('id')}), {day}",
                    "context": _clip(f'Question asked: "{q.get("question") or ""}"'),
                    "ref": {"record_id": record_id, "question_id": q.get("id"),
                            "picked": bool(picked) and not typed.strip()}})
    if not out:
        raise SourcesError(f"dialog record {record_id}: no answered questions" +
                           (f" among {question_ids}" if question_ids else ""))
    return out


def history_items(product: str, products: Path | None = None) -> list[dict]:
    """Earlier requests kept in the product store (history.json: {"items": [{text, source, context?}]})."""
    if products is None:
        return []
    path = Path(products) / product / "history.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [{"kind": "history", "text": h["text"], "source": h["source"],
             **({"context": _clip(h["context"])} if h.get("context") else {})}
            for h in data.get("items") or []]


def build(product: str, description: str, parts: list[dict]) -> dict:
    """Number the items S1.. in the order given and check the document."""
    doc = {"product": product, "description": description,
           "items": [{"id": f"S{i}", **part} for i, part in enumerate(parts, 1)]}
    return load(doc)


def load(doc: Any) -> dict:
    """A checked sources document; SourcesError names every problem."""
    problems = contracts.check_json("sources", doc, "sources.json")
    if not problems:
        ids = [item["id"] for item in doc["items"]]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            problems.append(f"sources.json: items: duplicate ids {', '.join(dupes)}")
    if problems:
        raise SourcesError(f"{len(problems)} problem(s): " + "; ".join(problems))
    return doc


def from_input(raw: str, product: str) -> dict:
    """The workflow's request_json: a whole sources document, or {"request", "source", "description"}."""
    try:
        data = json.loads(raw)
    except ValueError:
        raise SourcesError("request_json is not JSON: give a sources document or "
                           '{"request": ..., "source": ..., "description": ...}') from None
    if not isinstance(data, dict):
        raise SourcesError("request_json must be a JSON object")
    if "items" not in data:
        unknown = sorted(set(data) - {"request", "source", "description", "context"})
        if unknown:
            raise SourcesError(f"request_json: unknown fields {', '.join(unknown)}")
        if not data.get("description"):
            raise SourcesError("request_json needs description (the product in one line)")
        data = build(product, data["description"],
                     [request_item(data.get("request") or "", data.get("source") or "", data.get("context"))])
    doc = load(data)
    if doc["product"] != product:
        raise SourcesError(f"sources are for {doc['product']!r}, the run is for {product!r}")
    return doc
