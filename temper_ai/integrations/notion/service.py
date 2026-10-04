"""Temper's Notion connection, put together by the server.

    webhook (Notion -> temper): POST /api/hooks/notion (api/hooks.py) hands
      each verified event to ``handle``: a reply to a question answers it,
      otherwise the ``source: notion`` trigger rules decide what starts
    sender (temper -> Notion): notices and questions as page comments
      (temper_ai/integrations/notify decides what goes where)

On when ``NOTION_TOKEN`` is set and ``TEMPER_NOTION`` is not off. Starting
does no network I/O.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from temper_ai.integrations.notify import service as notify
from temper_ai.integrations.notion import replies, store
from temper_ai.integrations.notion.client import NotionClient, token
from temper_ai.integrations.notion.config import ConfigWatcher
from temper_ai.integrations.notion.sender import NotionSender

logger = logging.getLogger(__name__)

SWITCH_ENV = "TEMPER_NOTION"
OFF = ("0", "false", "off", "no")
_ACTIVE = frozenset({"pending", "queued", "running", "waiting"})

_service: NotionService | None = None


def switched_on() -> bool:
    return os.environ.get(SWITCH_ENV, "1").strip().lower() not in OFF


def why_off() -> str | None:
    if not switched_on():
        return f"{SWITCH_ENV} is off"
    if not token():
        return "NOTION_TOKEN not set"
    return None


class NotionService:
    def __init__(self, client: NotionClient | None = None, config: ConfigWatcher | None = None,
                 ops: Any = None, config_dir: str | Path | None = None) -> None:
        self.client = client or NotionClient()
        self.config = config or ConfigWatcher.shared()
        self.sender = NotionSender(self.client, self.config)
        self.config_dir = config_dir
        self._ops = ops
        self._page_lock = threading.Lock()

    @property
    def ops(self) -> Any:
        if self._ops is None:
            from temper_ai.integrations.slack.ops import TemperOps

            self._ops = TemperOps()
        return self._ops

    # -- one event -----------------------------------------------------------------

    def handle(self, event: dict[str, Any]) -> str:
        """Do what one verified event asks; returns the outcome, in a few words."""
        from temper_ai.triggers import notion as rules_notion

        kind = rules_notion.kind_of(event)
        if not kind:
            return f"ignored: {event.get('type')} events start nothing"
        if rules_notion.is_own(event, self.client.bot_id()):
            return "ignored: temper's own change"
        ctx = rules_notion.enrich(event, self.client)
        page = str((ctx.get("page") or {}).get("id") or "")
        if kind == "comment":
            comment = ctx.get("comment") or {}
            if store.is_ours(str(comment.get("id") or "")):
                return "ignored: temper's own comment"
            copy = replies.open_question(page, str(comment.get("discussion_id") or ""))
            if copy is not None:
                who = next((a for a in ctx["authors"] if a["type"] == "person"), None)
                name = replies.person_name(self.client, who["id"]) if who else "someone"
                return "answered: " + replies.answer(copy, str(comment.get("text") or ""), name, self.ops,
                                                     self._notify_config(),
                                                     comment_id=str(comment.get("id") or ""))
        return self.start_rules(ctx)

    def _notify_config(self) -> Any:
        from temper_ai.integrations.notify.config import ConfigWatcher as NotifyWatcher

        n = notify.notifier()
        return (n.config if n else NotifyWatcher()).get()

    def start_rules(self, ctx: dict[str, Any]) -> str:
        from temper_ai.triggers import notion as rules_notion
        from temper_ai.triggers.rules import load_triggers, render_inputs

        cfg = self.config.get()
        page = str((ctx.get("page") or {}).get("id") or "")
        triggers = [t for t in load_triggers(self.config_dir, source=rules_notion.SOURCE) if t.enabled]
        has_run = bool(page and store.runs_for_page(page))
        matched = []
        for t in triggers:
            try:
                if rules_notion.matches(t.on, ctx, cfg, self.client, has_run=has_run):
                    matched.append(t)
            except ValueError as exc:
                logger.warning("Trigger %s (%s): %s", t.name, t.path, exc)
        if not matched:
            return "no trigger matched"
        out = []
        with self._page_lock:
            going = self.still_going(page) if page else None
            if going:
                return f"skipped: run {going[:8]} for this page is still going"
            for t in matched:
                try:
                    eid = self.ops.start(t.workflow, render_inputs(t, ctx))
                except Exception as exc:  # noqa: BLE001 - one rule failing must not stop the others
                    out.append(f"{t.name} failed: {getattr(exc, 'detail', None) or exc}")
                    continue
                if page:
                    store.save_run(eid, page, origin=True, rule=t.name)
                out.append(f"started {t.workflow} {eid[:8]}")
                break   # one run per page: the first rule that matches
        return " / ".join(out)

    def still_going(self, page: str) -> str | None:
        for eid in store.runs_for_page(page)[:5]:
            try:
                status = str(self.ops.summary(eid).get("status") or "").lower()
            except Exception:  # noqa: BLE001 - an unknown run is not going
                continue
            if status in _ACTIVE:
                return eid
        return None


def only_failed(outcome: str) -> bool:
    """True when the rules that matched all failed to start (``start_rules``'s
    outcome), so the event is worth trying again later."""
    parts = [p.strip() for p in outcome.split(" / ")]
    return any(" failed: " in f" {p}" for p in parts) and not any(p.startswith("started ") for p in parts)


def service() -> NotionService | None:
    return _service


def start_notion() -> NotionService | None:
    global _service
    reason = why_off()
    if reason:
        logger.info("Notion: off (%s)", reason)
        return None
    if _service is None:
        _service = NotionService()
        notify.register(_service.sender)
        logger.info("Notion: on (webhook at /api/hooks/notion, notices as page comments)")
    return _service


def stop_notion() -> None:
    global _service
    if _service is not None:
        notify.unregister("notion")
        _service = None
