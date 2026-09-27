"""Notion: is a delivery really Notion's, is it temper's own doing, and which rules match.

Genuine. When a webhook subscription is made, Notion posts a one-time
``{"verification_token": ...}`` to the URL; the owner pastes it back into
Notion to switch the subscription on. That token is also the key every
later event is signed with: ``X-Notion-Signature`` is ``sha256=`` plus the
hex HMAC-SHA256 of the raw body under it. Temper keeps the token it was
sent (``temper notion check`` shows it) but only checks signatures against
``NOTION_WEBHOOK_SECRET`` in the environment, so a stranger who posts a
fake verification token first cannot choose the key.

What changed. Events only say that something changed (the page's id, and
for property changes which property ids), never the new values, so the
handler reads the page itself before matching (``enrich``).

Temper's own. An event's ``authors`` says who did it; a change whose
authors are all temper's bot user is temper's own, and its comments are
also remembered when posted (notion.store.save_comment).

Matching. A rule's ``on:`` for Notion takes these keys:

    event:       row (a table row was created or its properties changed)
                 or comment (a comment was added to a page). Required.
    table:       a table target name from the Notion config (or its id):
                 only rows of this table, or comments on them.
    property:    with value: the row's property now has this value (a list:
    value:       any of them). For ``row`` events it must also be the property
                 that just changed (or the row is new), so the rule fires once
                 when the value is set, not on every later edit.
    has_run:     true: only pages temper has already worked (a comment
                 continues that work).
    actor_type:  person (default), bot, agent, or a list; temper's own changes
                 never match a rule that ignores them (ignore_self).

Names compare case-insensitively. An unknown key is an error in the rule.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any
from urllib.parse import unquote

from temper_ai.integrations.notion.client import (
    NotionClient,
    NotionError,
    normalize_id,
    plain,
)
from temper_ai.integrations.notion.config import NotionConfig
from temper_ai.integrations.notion.content import properties_text, title_of

logger = logging.getLogger(__name__)

SOURCE = "notion"
SECRET_ENV = "NOTION_WEBHOOK_SECRET"  # noqa: S105 - a variable name, not a secret
ON_KEYS = frozenset({"event", "table", "property", "value", "has_run", "actor_type"})
EVENTS = ("row", "comment")
ROW_TYPES = ("page.created", "page.properties_updated")
COMMENT_TYPES = ("comment.created",)


def signing_secret() -> str | None:
    return os.environ.get(SECRET_ENV, "").strip() or None


def signature(raw: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def verify_signature(raw: bytes, header: str | None, secret: str) -> bool:
    if not header:
        return False
    return hmac.compare_digest(signature(raw, secret), header.strip())


def kind_of(event: dict[str, Any]) -> str:
    """row | comment | "" for the events rules care about."""
    t = str(event.get("type") or "")
    if t in ROW_TYPES:
        return "row"
    if t in COMMENT_TYPES:
        return "comment"
    return ""


def authors(event: dict[str, Any]) -> list[dict[str, str]]:
    return [{"id": normalize_id(str(a.get("id") or "")), "type": str(a.get("type") or "")}
            for a in event.get("authors") or [] if isinstance(a, dict)]


def is_own(event: dict[str, Any], bot_id: str) -> bool:
    who = authors(event)
    me = normalize_id(bot_id)
    return bool(who) and bool(me) and all(a["id"] == me for a in who)


def page_of(event: dict[str, Any]) -> str:
    """The page an event is about."""
    data = event.get("data") or {}
    if kind_of(event) == "comment":
        return normalize_id(str(data.get("page_id") or (data.get("parent") or {}).get("id") or ""))
    entity = event.get("entity") or {}
    return normalize_id(str(entity.get("id") or "")) if entity.get("type") == "page" else ""


def enrich(event: dict[str, Any], client: NotionClient) -> dict[str, Any]:
    """What rules match on and templates render from: the page as it is now
    (and the comment, for a comment event)."""
    ctx: dict[str, Any] = {"event": event, "type": event.get("type"), "kind": kind_of(event),
                           "authors": authors(event)}
    page_id = page_of(event)
    ctx["page"] = {"id": page_id}
    if page_id:
        page = client.page(page_id)
        parent = page.get("parent") or {}
        ctx["page"] = {
            "id": normalize_id(str(page.get("id") or page_id)),
            "url": page.get("url") or "",
            "title": title_of(page),
            "properties": properties_text(page),
            "property_ids": {name: str(p.get("id") or "") for name, p in (page.get("properties") or {}).items()},
            "data_source_id": normalize_id(str(parent.get("data_source_id") or "")),
            "database_id": normalize_id(str(parent.get("database_id") or "")),
        }
    if kind_of(event) == "comment":
        entity = event.get("entity") or {}
        cid = normalize_id(str(entity.get("id") or ""))
        data = event.get("data") or {}
        text = ""
        try:
            text = plain(client.get_comment(cid).get("rich_text"))
        except NotionError as exc:
            logger.warning("Notion: could not read comment %s: %s", cid, exc)
        ctx["comment"] = {"id": cid, "text": text, "discussion_id": str(data.get("discussion_id") or "")}
    return ctx


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(v).strip() for v in items]


def check_on(on: dict[str, Any]) -> None:
    unknown = set(on) - ON_KEYS
    if unknown:
        raise ValueError(f"unknown key(s) in on: {', '.join(sorted(unknown))} ({', '.join(sorted(ON_KEYS))})")
    if str(on.get("event") or "").lower() not in EVENTS:
        raise ValueError(f"on.event must be one of {', '.join(EVENTS)}")
    if ("property" in on) != ("value" in on):
        raise ValueError("on.property and on.value go together")


def table_ids(on: dict[str, Any], cfg: NotionConfig, client: NotionClient | None) -> set[str]:
    name = str(on.get("table") or "").strip()
    target = cfg.target(name)
    raw = target.table if target and target.is_table else normalize_id(name)
    ids = {raw} if raw else set()
    if raw and client is not None:
        try:
            ids |= {normalize_id(str(s.get("id"))) for s in client.database(raw).get("data_sources") or []}
        except NotionError:
            pass
    return ids


def matches(on: dict[str, Any], ctx: dict[str, Any], cfg: NotionConfig,
            client: NotionClient | None = None, has_run: bool = False) -> bool:
    check_on(on)
    if ctx.get("kind") != str(on["event"]).lower():
        return False
    wanted = [a.lower() for a in _as_list(on.get("actor_type", "person"))]
    if not any(a["type"].lower() in wanted for a in ctx.get("authors") or []):
        return False
    page = ctx.get("page") or {}
    if on.get("table"):
        ids = table_ids(on, cfg, client)
        if not ids or not ({page.get("data_source_id"), page.get("database_id")} & ids):
            return False
    if on.get("has_run") and not has_run:
        return False
    if "property" in on:
        prop = str(on["property"])
        props = {k.lower(): v for k, v in (page.get("properties") or {}).items()}
        now = str(props.get(prop.lower(), "")).strip().lower()
        if now not in [v.lower() for v in _as_list(on["value"])]:
            return False
        if ctx.get("type") == "page.properties_updated":
            prop_ids = {k.lower(): v for k, v in (page.get("property_ids") or {}).items()}
            changed = {str(x) for x in ((ctx.get("event") or {}).get("data") or {}).get("updated_properties") or []}
            pid = prop_ids.get(prop.lower())
            # Notion names changed properties by id (url-encoded in places).
            if pid and changed and pid not in changed and unquote(pid) not in {unquote(c) for c in changed}:
                return False
    return True
