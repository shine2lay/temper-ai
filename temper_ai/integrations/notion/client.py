"""A small Notion API client (https://developers.notion.com/reference).

It acts as the "Temper" internal connection (``NOTION_TOKEN``) and speaks
API version 2025-09-03, where a table ("database") holds one or more data
sources and rows live in a data source.

Rate limits: a 429 or 529 is waited out for ``Retry-After`` seconds (plus
backoff) and tried again, except a 429 whose reason is
``public_api_request_blocked``. 5xx is retried only for reads. The token
is never logged.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
VERSION = "2025-09-03"
TOKEN_ENV = "NOTION_TOKEN"
MAX_ATTEMPTS = 5
RETRY_CAP_S = 60.0
TEXT_MAX = 2000      # one rich-text item
CHILDREN_MAX = 100   # blocks per append


def token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


class NotionError(RuntimeError):
    def __init__(self, what: str, status: int, code: str, message: str) -> None:
        super().__init__(f"{what}: {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message

    @property
    def not_found(self) -> bool:
        """Missing, or not shared with the connection (Notion says 404 for both)."""
        return self.status == 404 or self.code == "object_not_found"


def normalize_id(value: str) -> str:
    """A page/table id from an id or a Notion URL, in 8-4-4-4-12 form."""
    text = str(value or "").strip()
    if "notion.so" in text or "notion.site" in text:
        text = text.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        text = text.rsplit("-", 1)[-1]
    raw = text.replace("-", "")
    if len(raw) == 32 and all(c in "0123456789abcdefABCDEF" for c in raw):
        raw = raw.lower()
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return text


class NotionClient:
    def __init__(self, api_token: str | None = None, http: httpx.Client | None = None,
                 sleep: Any = time.sleep) -> None:
        self._token = api_token or token()
        if not self._token:
            raise RuntimeError(f"{TOKEN_ENV} is not set")
        self._http = http or httpx.Client(timeout=30.0)
        self._sleep = sleep
        self._bot_id: str | None = None

    # -- transport --

    def request(self, method: str, path: str, body: dict[str, Any] | None = None,
                params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}", "Notion-Version": VERSION,
                   "Content-Type": "application/json"}
        what = f"{method} {path.split('?')[0]}"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            resp = self._http.request(method, f"{API}{path}", json=body, params=params, headers=headers)
            if resp.status_code < 400:
                return resp.json() if resp.content else {}
            try:
                data = resp.json()
            except ValueError:
                data = {}
            code = str(data.get("code") or "")
            reason = str((data.get("additional_data") or {}).get("rate_limit_reason") or "")
            limited = resp.status_code in (429, 529) and reason != "public_api_request_blocked"
            flaky_read = method == "GET" and resp.status_code in (500, 502, 503, 504)
            if (limited or flaky_read) and attempt < MAX_ATTEMPTS:
                wait = _retry_after(resp) or min(2 ** attempt, RETRY_CAP_S)
                wait = min(wait, RETRY_CAP_S) + random.uniform(0, 0.5)  # noqa: S311 - jitter
                logger.info("Notion %s: %s, waiting %.1fs (try %d)", what, resp.status_code, wait, attempt)
                self._sleep(wait)
                continue
            raise NotionError(what, resp.status_code, code, str(data.get("message") or resp.text[:200]))
        raise NotionError(what, 429, "rate_limited", "gave up after retries")

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", path, body)

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("PATCH", path, body)

    # -- identity --

    def me(self) -> dict[str, Any]:
        return self.get("/users/me")

    def bot_id(self) -> str:
        if self._bot_id is None:
            self._bot_id = str(self.me().get("id") or "")
        return self._bot_id

    # -- pages, tables, blocks --

    def page(self, page_id: str) -> dict[str, Any]:
        return self.get(f"/pages/{normalize_id(page_id)}")

    def database(self, database_id: str) -> dict[str, Any]:
        return self.get(f"/databases/{normalize_id(database_id)}")

    def data_source(self, data_source_id: str) -> dict[str, Any]:
        return self.get(f"/data_sources/{normalize_id(data_source_id)}")

    def data_source_for(self, table_id: str) -> str:
        """The data source id for a table id (a database id or already a data source id)."""
        tid = normalize_id(table_id)
        try:
            sources = self.database(tid).get("data_sources") or []
        except NotionError as exc:
            if exc.status in (400, 404):
                self.data_source(tid)  # raises if it isn't one either
                return tid
            raise
        if not sources:
            raise NotionError(f"table {tid}", 404, "no_data_source", "the table has no data source")
        return str(sources[0]["id"])

    def query(self, data_source_id: str, filter: dict[str, Any] | None = None,
              limit: int = 100) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(rows) < limit:
            body: dict[str, Any] = {"page_size": min(100, limit - len(rows))}
            if filter:
                body["filter"] = filter
            if cursor:
                body["start_cursor"] = cursor
            data = self.post(f"/data_sources/{normalize_id(data_source_id)}/query", body)
            rows.extend(data.get("results") or [])
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                break
        return rows

    def children(self, block_id: str, limit: int = 500) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(out) < limit:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self.get(f"/blocks/{normalize_id(block_id)}/children", **params)
            out.extend(data.get("results") or [])
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                break
        return out[:limit]

    def append(self, block_id: str, blocks: list[dict[str, Any]]) -> None:
        for i in range(0, len(blocks), CHILDREN_MAX):
            self.patch(f"/blocks/{normalize_id(block_id)}/children", {"children": blocks[i:i + CHILDREN_MAX]})

    def create_page(self, parent: dict[str, Any], properties: dict[str, Any],
                    children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            body["children"] = children[:CHILDREN_MAX]
        page = self.post("/pages", body)
        if children and len(children) > CHILDREN_MAX:
            self.append(page["id"], children[CHILDREN_MAX:])
        return page

    def update_page(self, page_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return self.patch(f"/pages/{normalize_id(page_id)}", {"properties": properties})

    def create_database(self, parent_page_id: str, title: str,
                        properties: dict[str, Any]) -> dict[str, Any]:
        return self.post("/databases", {
            "parent": {"type": "page_id", "page_id": normalize_id(parent_page_id)},
            "title": rich(title),
            "initial_data_source": {"properties": properties},
        })

    def search(self, query: str, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"query": query, "page_size": min(100, limit)}
        if kind in ("page", "data_source"):
            body["filter"] = {"property": "object", "value": kind}
        return (self.post("/search", body).get("results") or [])[:limit]

    # -- comments --

    def comments(self, block_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"block_id": normalize_id(block_id), "page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self.get("/comments", **params)
            out.extend(data.get("results") or [])
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor or len(out) > 1000:
                return out

    def comment(self, page_id: str, text: str, discussion_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"rich_text": rich(text)}
        if discussion_id:
            body["discussion_id"] = discussion_id
        else:
            body["parent"] = {"page_id": normalize_id(page_id)}
        return self.post("/comments", body)

    def get_comment(self, comment_id: str) -> dict[str, Any]:
        return self.get(f"/comments/{normalize_id(comment_id)}")


def rich(text: str) -> list[dict[str, Any]]:
    """Plain text as rich-text items, split at Notion's 2000-character limit."""
    text = str(text or "")
    if not text:
        return []
    return [{"type": "text", "text": {"content": text[i:i + TEXT_MAX]}}
            for i in range(0, len(text), TEXT_MAX)][:100]


def plain(items: list[dict[str, Any]] | None) -> str:
    return "".join(str(i.get("plain_text") or (i.get("text") or {}).get("content") or "") for i in items or [])


def _retry_after(resp: httpx.Response) -> float:
    try:
        return float(resp.headers.get("Retry-After") or 0)
    except ValueError:
        return 0.0
