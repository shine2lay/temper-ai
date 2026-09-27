"""Notion tools for agents: search, read, write, upsert a table row, comment.

They act as the "Temper" Notion connection (``NOTION_TOKEN``), so they see
only pages shared with it. Writes and comments go only to the configured
targets (``configs/notion/local/notion.yaml``), pages under a target page,
rows of a target table, and the page this run was started from. There is
no delete or archive.

A target is named ("crm"), or given as a page id or Notion URL. With the
tool option ``scope: answer`` (as repo_answer uses), search and read are
limited to the config's ``answer_from`` pages.
"""

from __future__ import annotations

import json
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

MAX_TEXT = 20000
ORIGIN = "origin"


def _fail(error: str) -> ToolResult:
    return ToolResult(success=False, result="", error=error)


class _NotionTool(BaseTool):
    modifies_state = False
    local_paths = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._execution_context: Any = None

    def bind_context(self, context: Any) -> None:
        self._execution_context = context

    # -- shared helpers --

    def _run_id(self) -> str:
        return str(getattr(self._execution_context, "run_id", "") or "")

    def _run_pages(self) -> list[str]:
        run_id = self._run_id()
        if not run_id:
            return []
        from temper_ai.integrations.notion import store

        try:
            return [p["page_id"] for p in store.pages_of(run_id)]
        except Exception:  # noqa: BLE001 - no DB (tests, CLI): no run pages
            return []

    def _client(self) -> Any:
        from temper_ai.integrations.notion.client import NotionClient

        return NotionClient()

    def _cfg(self) -> Any:
        from temper_ai.integrations.notion.config import ConfigWatcher

        return ConfigWatcher.shared().get()

    def _answer_scope(self) -> bool:
        return str(self.config.get("scope") or "") == "answer"

    def _resolve_page(self, where: str) -> str:
        """A target name, ``origin``, a page id or URL -> a page id."""
        from temper_ai.integrations.notion.client import normalize_id

        where = str(where or "").strip()
        if where == ORIGIN:
            pages = self._run_pages()
            if not pages:
                raise ValueError("this run was not started from a Notion page, so it has no origin")
            return pages[0]
        target = self._cfg().target(where)
        if target is not None:
            if target.is_table:
                raise ValueError(f"{where} is a table; use NotionUpsert for its rows")
            return target.page
        return normalize_id(where)

    def _may_read(self, client: Any, page_id: str) -> str:
        if not self._answer_scope():
            return ""
        ids = self._cfg().answer_ids()
        if ids is None:
            return ""
        from temper_ai.integrations.notion import access

        if access.under(client, page_id, access.expand(client, ids)):
            return ""
        return "that page is not one answers may read (the Notion config's answer_from)"


class NotionSearch(_NotionTool):
    name = "NotionSearch"
    description = ("Search Notion pages and tables shared with temper by title. Returns each match's title, "
                   "kind (page or table), id and url; read one with NotionRead.")
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words in the title (empty lists recent pages)"},
            "kind": {"type": "string", "enum": ["any", "page", "table"], "description": "Only pages or tables"},
            "limit": {"type": "integer", "description": "At most this many (default 10, max 50)"},
        },
        "required": ["query"],
    }

    def execute(self, **params: Any) -> ToolResult:
        from temper_ai.integrations.notion.content import title_of

        query = str(params.get("query") or "").strip()
        kind = {"page": "page", "table": "data_source"}.get(str(params.get("kind") or "any"))
        try:
            limit = max(1, min(int(params.get("limit") or 10), 50))
        except (TypeError, ValueError):
            limit = 10
        try:
            client = self._client()
            results = client.search(query, kind=kind, limit=limit * 3 if self._answer_scope() else limit)
            out = []
            for r in results:
                if self._may_read(client, r["id"]) and r.get("object") == "page":
                    continue
                out.append({"title": title_of(r), "kind": "table" if r.get("object") == "data_source" else "page",
                            "id": r.get("id"), "url": r.get("url")})
                if len(out) >= limit:
                    break
        except Exception as exc:  # noqa: BLE001 - the agent is told
            return _fail(f"{type(exc).__name__}: {exc}")
        return ToolResult(success=True, result=json.dumps(out, ensure_ascii=False), metadata={"count": len(out)})


class NotionRead(_NotionTool):
    name = "NotionRead"
    description = ("Read a Notion page or table row as text (title, row properties, body including tables), "
                   "or a table's columns and rows. `what` is a target name from the Notion config, `origin` "
                   "(the page this run started from), a page/table id, or a Notion URL.")
    parameters = {
        "type": "object",
        "properties": {
            "what": {"type": "string", "description": "Target name, origin, id or URL"},
            "rows": {"type": "integer", "description": "For a table: at most this many rows (default 50)"},
            "comments": {"type": "boolean", "description": "For a page: also list its comments (who, id, text)"},
        },
        "required": ["what"],
    }

    def execute(self, **params: Any) -> ToolResult:
        from temper_ai.integrations.notion.client import NotionError, normalize_id
        from temper_ai.integrations.notion.content import (
            comments_text,
            page_text,
            table_text,
        )

        what = str(params.get("what") or "").strip()
        if not what:
            return _fail("what is required")
        try:
            rows = max(1, min(int(params.get("rows") or 50), 200))
        except (TypeError, ValueError):
            rows = 50
        try:
            client = self._client()
            target = self._cfg().target(what)
            if target is not None and target.is_table:
                text = table_text(client, client.data_source_for(target.table), limit=rows)
            else:
                pid = self._resolve_page(what) if target is None else target.page
                why = self._may_read(client, pid)
                if why:
                    return _fail(why)
                try:
                    text = page_text(client, pid)
                    if params.get("comments") in (True, "true", "True", 1):
                        text += "\n\n" + comments_text(client, pid)
                except NotionError as exc:
                    if not exc.not_found:
                        raise
                    text = table_text(client, client.data_source_for(normalize_id(pid)), limit=rows)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"{type(exc).__name__}: {exc}")
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "\n… (cut)"
        return ToolResult(success=True, result=text, metadata={"chars": len(text)})


class NotionWrite(_NotionTool):
    name = "NotionWrite"
    description = ("Write to Notion as temper: create a new page under a page, or append text to a page. "
                   "`where` is a page target name, `origin`, or a page id/URL that is a target or under one. "
                   "Text is Markdown-ish (# headings, - bullets, 1. numbers, - [ ] to-dos, > quotes, ``` code).")
    parameters = {
        "type": "object",
        "properties": {
            "where": {"type": "string", "description": "Page target name, origin, id or URL"},
            "mode": {"type": "string", "enum": ["new_page", "append"],
                     "description": "new_page: a child page titled `title`; append: add to the page"},
            "title": {"type": "string", "description": "The new page's title (new_page)"},
            "text": {"type": "string", "description": "The content"},
        },
        "required": ["where", "mode", "text"],
    }
    modifies_state = True

    def execute(self, **params: Any) -> ToolResult:
        from temper_ai.integrations.notion import access
        from temper_ai.integrations.notion.client import rich
        from temper_ai.integrations.notion.content import text_blocks

        mode = str(params.get("mode") or "")
        text = str(params.get("text") or "")
        title = str(params.get("title") or "").strip()
        if mode not in ("new_page", "append"):
            return _fail("mode is new_page or append")
        if mode == "new_page" and not title:
            return _fail("a new page needs a title")
        if not text.strip() and mode == "append":
            return _fail("text is required")
        try:
            client = self._client()
            pid = self._resolve_page(str(params.get("where") or ""))
            access.check(client, self._cfg(), pid, self._run_pages())
            blocks = text_blocks(text)
            if mode == "append":
                client.append(pid, blocks)
                out = {"page_id": pid, "appended_blocks": len(blocks)}
            else:
                page = client.create_page({"type": "page_id", "page_id": pid}, {"title": {"title": rich(title)}},
                                          blocks)
                out = {"page_id": page.get("id"), "url": page.get("url"), "blocks": len(blocks)}
        except Exception as exc:  # noqa: BLE001
            return _fail(f"{type(exc).__name__}: {exc}")
        return ToolResult(success=True, result=json.dumps(out), metadata=out)


class NotionUpsert(_NotionTool):
    name = "NotionUpsert"
    description = ("Create or update a row in a Notion table target (e.g. a CRM). The row is found by the "
                   "target's key field: if a row has that key it is updated, otherwise a new row is created, "
                   "so running again never makes duplicates. `values` maps field names (from the config) or "
                   "column names to values; omit a field to leave it as is. With `row` (`origin`, or a row's "
                   "id/URL in that table) that row is updated instead and no key is needed: e.g. move the "
                   "Status of the task this run was started from.")
    parameters = {
        "type": "object",
        "properties": {
            "table": {"type": "string", "description": "A table target name from the Notion config"},
            "values": {"type": "object", "description": "field or column name -> value; must include the key"},
            "row": {"type": "string", "description": "Optional: origin, or a row id/URL of this table, to update"},
            "text": {"type": "string", "description": "Optional text to add to the row's page body"},
        },
        "required": ["table", "values"],
    }
    modifies_state = True

    def execute(self, **params: Any) -> ToolResult:
        from temper_ai.integrations.notion.content import text_blocks, upsert

        name = str(params.get("table") or "").strip()
        values = params.get("values")
        if isinstance(values, str):
            try:
                values = json.loads(values)
            except ValueError:
                return _fail("values must be an object of field -> value")
        if not isinstance(values, dict) or not values:
            return _fail("values must be an object of field -> value")
        cfg = self._cfg()
        target = cfg.target(name)
        if target is None or not target.is_table:
            tables = [t.name for t in cfg.targets.values() if t.is_table]
            return _fail(f"{name!r} is not a table target (tables: {', '.join(tables) or 'none'})")
        mapped = {target.prop(str(k)): v for k, v in values.items()}
        try:
            client = self._client()
            ds = client.data_source_for(target.table)
            if str(params.get("row") or "").strip():
                action, row = "updated", self._update_row(client, ds, str(params["row"]), mapped)
            else:
                action, row = upsert(client, ds, target.key, mapped)
            text = str(params.get("text") or "").strip()
            if text:
                client.append(row["id"], text_blocks(text))
        except Exception as exc:  # noqa: BLE001
            return _fail(f"{type(exc).__name__}: {exc}")
        out = {"action": action, "row_id": row.get("id"), "url": row.get("url"), "key": mapped.get(target.key)}
        return ToolResult(success=True, result=json.dumps(out), metadata=out)

    def _update_row(self, client: Any, ds: str, row: str, values: dict[str, Any]) -> dict[str, Any]:
        from temper_ai.integrations.notion.client import normalize_id
        from temper_ai.integrations.notion.content import build_properties

        pid = self._resolve_page(row)
        page = client.page(pid)
        if normalize_id(str((page.get("parent") or {}).get("data_source_id") or "")) != normalize_id(ds):
            raise ValueError(f"row {pid} is not in this table")
        schema = client.data_source(ds).get("properties") or {}
        return client.update_page(pid, build_properties(schema, values))


class NotionComment(_NotionTool):
    name = "NotionComment"
    description = ("Comment on a Notion page as temper: `origin` (the page this run started from), a page "
                   "target name, or a page id/URL that is a target, under one, or a row of a table target.")
    parameters = {
        "type": "object",
        "properties": {
            "where": {"type": "string", "description": "origin, target name, page id or URL"},
            "text": {"type": "string", "description": "The comment"},
        },
        "required": ["where", "text"],
    }
    modifies_state = True

    def execute(self, **params: Any) -> ToolResult:
        from temper_ai.integrations.notion import access, store

        text = str(params.get("text") or "").strip()
        if not text:
            return _fail("text is required")
        try:
            client = self._client()
            pid = self._resolve_page(str(params.get("where") or ""))
            access.check(client, self._cfg(), pid, self._run_pages())
            made = client.comment(pid, text)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"{type(exc).__name__}: {exc}")
        try:
            store.save_comment(str(made.get("id")), pid, self._run_id(), str(made.get("discussion_id") or ""))
        except Exception:  # noqa: BLE001, S110 - bookkeeping only; the self-skip also checks the author
            pass
        out = {"page_id": pid, "comment_id": made.get("id"), "discussion_id": made.get("discussion_id")}
        return ToolResult(success=True, result=json.dumps(out), metadata=out)
