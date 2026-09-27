"""Notion pages and table rows as text, text as Notion blocks, and values
as Notion property values.

Reading turns a page into Markdown-ish text an agent can use: the title,
a row's properties, and the blocks (headings, lists, to-dos, code, quotes,
tables, child pages and tables by title). Writing takes the same kind of
text back: ``#`` headings, ``-``/``*`` bullets, ``1.`` numbers, ``[ ]``
to-dos, ``>`` quotes, fenced code, and paragraphs.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from temper_ai.integrations.notion.client import NotionClient, plain, rich

MAX_BLOCKS = 400
MAX_DEPTH = 3


# ---------------------------------------------------------------- reading

def title_of(obj: dict[str, Any]) -> str:
    """The title of a page, row, database or data source."""
    if obj.get("title"):
        return plain(obj["title"])
    for prop in (obj.get("properties") or {}).values():
        if prop.get("type") == "title":
            return plain(prop.get("title"))
    return ""


def prop_text(prop: dict[str, Any]) -> str:
    """One property value as text."""
    kind = prop.get("type")
    value = prop.get(kind) if kind else None
    if value is None:
        return ""
    if kind in ("title", "rich_text"):
        return plain(value)
    if kind in ("select", "status"):
        return str(value.get("name") or "")
    if kind == "multi_select":
        return ", ".join(str(v.get("name") or "") for v in value)
    if kind in ("number", "checkbox", "url", "email", "phone_number"):
        return str(value).lower() if isinstance(value, bool) else str(value)
    if kind == "date":
        return str(value.get("start") or "") + (f" → {value['end']}" if value.get("end") else "")
    if kind == "people":
        return ", ".join(str(p.get("name") or p.get("id")) for p in value)
    if kind == "relation":
        return ", ".join(str(r.get("id")) for r in value)
    if kind in ("created_time", "last_edited_time"):
        return str(value)
    if kind in ("created_by", "last_edited_by"):
        return str(value.get("name") or value.get("id") or "")
    if kind == "formula":
        return prop_text({"type": value.get("type"), value.get("type"): value.get(value.get("type"))})
    if kind == "unique_id":
        return f"{value.get('prefix') or ''}{'-' if value.get('prefix') else ''}{value.get('number')}"
    if kind == "files":
        return ", ".join(str(f.get("name") or "") for f in value)
    return str(value)[:200]


def properties_text(page: dict[str, Any]) -> dict[str, str]:
    return {name: prop_text(p) for name, p in (page.get("properties") or {}).items()}


def _block_text(block: dict[str, Any]) -> tuple[str, bool]:
    """A block as one line of text, and whether its children are worth reading."""
    kind = block.get("type") or ""
    body = block.get(kind) or {}
    text = plain(body.get("rich_text"))
    if kind.startswith("heading_"):
        return "#" * int(kind[-1]) + " " + text, bool(body.get("is_toggleable"))
    if kind == "paragraph":
        return text, True
    if kind == "bulleted_list_item":
        return f"- {text}", True
    if kind == "numbered_list_item":
        return f"1. {text}", True
    if kind == "to_do":
        return f"- [{'x' if body.get('checked') else ' '}] {text}", True
    if kind == "toggle":
        return f"▸ {text}", True
    if kind == "quote":
        return f"> {text}", True
    if kind == "callout":
        return f"> {text}", True
    if kind == "code":
        return f"```{body.get('language') or ''}\n{text}\n```", False
    if kind == "divider":
        return "---", False
    if kind == "child_page":
        return f"[page: {body.get('title')}] (id {block.get('id')})", False
    if kind == "child_database":
        return f"[table: {body.get('title')}] (id {block.get('id')})", False
    if kind == "bookmark" or kind == "embed" or kind == "link_preview":
        return str(body.get("url") or ""), False
    if kind in ("image", "file", "pdf", "video"):
        caption = plain(body.get("caption"))
        return f"[{kind}{': ' + caption if caption else ''}]", False
    if kind == "equation":
        return str(body.get("expression") or ""), False
    if kind == "table":
        return "", True
    if kind == "table_row":
        return "| " + " | ".join(plain(c) for c in body.get("cells") or []) + " |", False
    if kind in ("column_list", "column", "synced_block"):
        return "", True
    return text, bool(block.get("has_children"))


def blocks_text(client: NotionClient, block_id: str, depth: int = 0, budget: list[int] | None = None) -> list[str]:
    budget = budget if budget is not None else [MAX_BLOCKS]
    lines: list[str] = []
    for block in client.children(block_id, limit=budget[0]):
        if budget[0] <= 0:
            lines.append("… (more not shown)")
            break
        budget[0] -= 1
        line, dive = _block_text(block)
        if line:
            lines.append(("  " * depth) + line)
        if dive and block.get("has_children") and depth < MAX_DEPTH:
            lines.extend(blocks_text(client, block["id"], depth + (1 if line else 0), budget))
    return lines


def page_text(client: NotionClient, page_id: str, with_body: bool = True) -> str:
    """A page or row as text: title, properties (for a row), then the body."""
    page = client.page(page_id)
    out = [f"# {title_of(page) or '(untitled)'}", f"url: {page.get('url')}", f"id: {page.get('id')}"]
    parent = page.get("parent") or {}
    if parent.get("type") in ("data_source_id", "database_id"):
        for name, value in properties_text(page).items():
            if value:
                out.append(f"{name}: {value}")
    if with_body:
        body = blocks_text(client, page["id"])
        if body:
            out.append("")
            out.extend(body)
    return "\n".join(out)


def comments_text(client: NotionClient, page_id: str, bot_id: str = "") -> str:
    """A page's comments, oldest first: who (temper or a person), id, text."""
    from temper_ai.integrations.notion.client import plain

    bot = bot_id or client.bot_id()
    items = client.comments(page_id)
    if not items:
        return "## comments\n(none)"
    out = ["## comments"]
    for c in items:
        who_id = str((c.get("created_by") or {}).get("id") or "")
        who = "Temper" if who_id and who_id == bot else "person"
        out.append(f"- [{c.get('created_time', '')[:16]}] {who} (comment {c.get('id')}): {plain(c.get('rich_text'))}")
    return "\n".join(out)


def table_text(client: NotionClient, data_source_id: str, limit: int = 50) -> str:
    """A table's columns and its rows as text."""
    source = client.data_source(data_source_id)
    props = source.get("properties") or {}
    cols = list(props)
    out = [f"# table: {title_of(source) or '(untitled)'}",
           "columns: " + ", ".join(f"{n} ({p.get('type')})" for n, p in props.items())]
    rows = client.query(data_source_id, limit=limit)
    for row in rows:
        vals = properties_text(row)
        out.append("- " + "; ".join(f"{c}: {vals.get(c, '')}" for c in cols if vals.get(c)) + f" (id {row['id']})")
    if len(rows) >= limit:
        out.append(f"… (first {limit} rows)")
    return "\n".join(out)


# ---------------------------------------------------------------- writing

_FENCE = re.compile(r"^```(\w*)\s*$")


def text_blocks(text: str) -> list[dict[str, Any]]:
    """Markdown-ish text as Notion blocks."""
    blocks: list[dict[str, Any]] = []
    lines = str(text or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        fence = _FENCE.match(line.strip())
        if fence:
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            blocks.append(_block("code", "\n".join(code), language=fence.group(1) or "plain text"))
            i += 1
            continue
        s = line.strip()
        if not s:
            i += 1
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            blocks.append(_block(f"heading_{len(m.group(1))}", m.group(2)))
        elif re.match(r"^[-*]\s+\[( |x|X)\]\s+", s):
            done = s[3] in "xX"
            blocks.append(_block("to_do", s[6:].strip(), checked=done))
        elif re.match(r"^[-*]\s+", s):
            blocks.append(_block("bulleted_list_item", s[2:].strip()))
        elif re.match(r"^\d+[.)]\s+", s):
            blocks.append(_block("numbered_list_item", re.sub(r"^\d+[.)]\s+", "", s)))
        elif s.startswith(">"):
            blocks.append(_block("quote", s.lstrip("> ").strip()))
        elif s in ("---", "***"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        else:
            blocks.append(_block("paragraph", s))
        i += 1
    return blocks


def _block(kind: str, text: str, **extra: Any) -> dict[str, Any]:
    return {"object": "block", "type": kind, kind: {"rich_text": rich(text), **extra}}


class ValueError_(ValueError):
    pass


def property_value(kind: str, value: Any, name: str = "") -> dict[str, Any]:
    """A value as the Notion property value for a property of this type."""
    if value is None or value == "":
        empty: dict[str, Any] = {"title": [], "rich_text": [], "select": None, "status": None, "multi_select": [],
                 "number": None, "url": None, "email": None, "phone_number": None, "date": None,
                 "checkbox": False, "people": [], "relation": []}
        if kind in empty:
            return {kind: empty[kind]}
    if kind in ("title", "rich_text"):
        return {kind: rich(str(value))}
    if kind in ("select", "status"):
        return {kind: {"name": str(value)[:100]}}
    if kind == "multi_select":
        items = value if isinstance(value, list) else [v for v in re.split(r"\s*,\s*", str(value)) if v]
        return {kind: [{"name": str(v)[:100]} for v in items][:100]}
    if kind == "number":
        return {kind: _number(value, name)}
    if kind == "checkbox":
        return {kind: value if isinstance(value, bool) else str(value).strip().lower() in ("true", "yes", "1", "x")}
    if kind in ("url", "email", "phone_number"):
        return {kind: str(value)[:2000]}
    if kind == "date":
        if isinstance(value, dict):
            return {kind: value}
        if isinstance(value, (date, datetime)):
            return {kind: {"start": value.isoformat()}}
        return {kind: {"start": str(value)}}
    if kind == "relation":
        ids = value if isinstance(value, list) else re.split(r"\s*,\s*", str(value))
        return {kind: [{"id": str(v)} for v in ids if v][:100]}
    raise ValueError_(f"{name or 'property'}: temper can't write a {kind} property")


def _number(value: Any, name: str) -> float | int:
    if isinstance(value, bool):
        raise ValueError_(f"{name}: expected a number, got {value!r}")
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "").replace("$", "")
    mult = 1
    if text[-1:].lower() in ("k", "m", "b"):
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[text[-1].lower()]
        text = text[:-1]
    try:
        num = float(text) * mult
    except ValueError:
        raise ValueError_(f"{name}: expected a number, got {value!r}") from None
    return int(num) if num.is_integer() else num


def build_properties(schema: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Property values for a row, checked against the table's schema."""
    out: dict[str, Any] = {}
    lower = {k.lower(): k for k in schema}
    for name, value in values.items():
        real = name if name in schema else lower.get(str(name).lower())
        if real is None:
            raise ValueError_(f"no property {name!r} (the table has: {', '.join(schema)})")
        out[real] = property_value(str(schema[real].get("type")), value, real)
    return out


def key_filter(schema: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    """A query filter that finds rows whose key property equals value."""
    kind = str((schema.get(key) or {}).get("type") or "")
    text = str(value)
    if kind in ("title", "rich_text", "url", "email", "phone_number"):
        return {"property": key, kind: {"equals": text}}
    if kind in ("select", "status"):
        return {"property": key, kind: {"equals": text}}
    if kind == "number":
        return {"property": key, "number": {"equals": _number(value, key)}}
    if kind == "unique_id":
        return {"property": key, "unique_id": {"equals": int(re.sub(r"\D", "", text) or 0)}}
    raise ValueError_(f"key {key!r} is a {kind or 'missing'} property; use a title, text, url, email, "
                      "select or number property")


def upsert(client: NotionClient, data_source_id: str, key: str, values: dict[str, Any],
           schema: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Find the row whose ``key`` equals ``values[key]`` and update it, or
    create it. Returns ("created" | "updated", row). Refuses when several
    rows share the key, rather than guess."""
    schema = schema if schema is not None else (client.data_source(data_source_id).get("properties") or {})
    if key not in schema:
        raise ValueError_(f"key property {key!r} is not in the table (it has: {', '.join(schema)})")
    key_value = next((v for k, v in values.items() if k == key or str(k).lower() == key.lower()), None)
    if key_value in (None, ""):
        raise ValueError_(f"a value for the key {key!r} is required")
    props = build_properties(schema, values)
    found = client.query(data_source_id, filter=key_filter(schema, key, key_value), limit=3)
    if len(found) > 1:
        raise ValueError_(f"{len(found)} rows have {key} = {key_value!r}; fix the table so the key is unique")
    if found:
        return "updated", client.update_page(found[0]["id"], props)
    return "created", client.create_page({"type": "data_source_id", "data_source_id": data_source_id}, props)
