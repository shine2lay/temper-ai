"""Where temper may write in Notion, and what answers may read.

Temper writes only to: a target page or a page under one, a row of a target
table, and the pages a run is tied to (the page it was started from). The
Notion connection can see more than that (whatever is shared with it), so
this check is what keeps an agent that reads text written by people from
being talked into editing anything else. Nothing deletes or archives.
"""

from __future__ import annotations

from typing import Any

from temper_ai.integrations.notion.client import NotionClient, NotionError, normalize_id
from temper_ai.integrations.notion.config import NotionConfig

MAX_UP = 8  # how many parents to walk


class NotAllowed(Exception):
    pass


def expand(client: NotionClient, ids: list[str]) -> set[str]:
    """The ids plus, for each table, its data source ids (rows name those)."""
    out = {normalize_id(i) for i in ids if i}
    for i in list(out):
        try:
            for source in client.database(i).get("data_sources") or []:
                out.add(normalize_id(str(source.get("id"))))
        except NotionError:
            pass
    return out


def ancestors(client: NotionClient, page_id: str) -> list[str]:
    """The page and everything above it (pages, blocks, tables, data sources)."""
    chain = [normalize_id(page_id)]
    current: dict[str, Any] | None = None
    try:
        current = client.page(chain[0])
    except NotionError:
        try:
            current = client.get(f"/blocks/{chain[0]}")
        except NotionError:
            return chain
    for _ in range(MAX_UP):
        parent = (current or {}).get("parent") or {}
        kind = str(parent.get("type") or "")
        pid = normalize_id(str(parent.get(kind) or "")) if kind not in ("workspace", "") else ""
        if not pid:
            break
        chain.append(pid)
        if kind == "data_source_id":
            db = normalize_id(str(parent.get("database_id") or ""))
            if db:
                chain.append(db)
        getter = {"page_id": "/pages/", "block_id": "/blocks/", "database_id": "/databases/",
                  "data_source_id": "/data_sources/"}.get(kind)
        if getter is None:
            break
        try:
            current = client.get(f"{getter}{pid}")
        except NotionError:
            break
        if kind == "data_source_id":
            dsp = current.get("parent") or {}
            if dsp.get("type") == "database_id":
                # A data source's parent is its database; go on from there.
                try:
                    current = client.get(f"/databases/{normalize_id(str(dsp.get('database_id')))}")
                except NotionError:
                    break
    return chain


def under(client: NotionClient, page_id: str, ids: set[str]) -> bool:
    return any(a in ids for a in ancestors(client, page_id))


def write_ids(client: NotionClient, cfg: NotionConfig) -> set[str]:
    return expand(client, [t.id for t in cfg.targets.values()])


def why_not(client: NotionClient, cfg: NotionConfig, page_id: str, run_pages: list[str] | None = None) -> str:
    """"" if temper may write to (or comment on) this page, else why not."""
    pid = normalize_id(page_id)
    if pid in {normalize_id(p) for p in run_pages or []}:
        return ""
    if under(client, pid, write_ids(client, cfg)):
        return ""
    return (f"page {pid} is not a configured Notion target, under one, or this run's page "
            f"(targets: {cfg.describe()})")


def check(client: NotionClient, cfg: NotionConfig, page_id: str, run_pages: list[str] | None = None) -> None:
    reason = why_not(client, cfg, page_id, run_pages)
    if reason:
        raise NotAllowed(reason)
