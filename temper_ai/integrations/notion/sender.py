"""Notion as a place the notify layer sends to: notices become page comments.

A run's comments on a page stay in one discussion (the first comment starts
it; ``store.set_discussion`` remembers it), so a person reads a run's story
top to bottom and replies in the same thread. A question's comment is
remembered with ``question=True``: a person's reply comment in that
discussion answers it (``replies.py``).

Notion's API cannot edit or delete a comment, so an answered question gets a
short follow-up comment saying who answered where, instead of losing its
buttons as in Slack and Telegram.

A place in ``notify:`` settings is ``{notion: <target name or page id>}``;
``origin`` is the page a trigger rule started the run from.
"""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.integrations.notify.notice import Copy, Decision, Notice
from temper_ai.integrations.notion import store
from temper_ai.integrations.notion.client import NotionClient, NotionError, normalize_id
from temper_ai.integrations.notion.config import ConfigWatcher
from temper_ai.integrations.slack.blocks import clip, cost, duration, output_gist

logger = logging.getLogger(__name__)

EMOJI = {"completed": "✅", "failed": "❌", "cancelled": "⏹", "interrupted": "⚠️", "waiting": "❓"}
COMMENT_MAX = 1900


def split_ref(ref: str) -> tuple[str, str] | None:
    page, _, comment = (ref or "").partition(":")
    return (page, comment) if page and comment else None


def header(notice: Notice) -> str:
    return f"temper run {notice.workflow or '?'} {notice.execution_id[:8]}"


def link(notice: Notice) -> str:
    return f"\nOpen in temper: {notice.url}" if notice.url else ""


def answer_text(a: dict[str, Any] | None) -> str:
    if not a:
        return ""
    return ", ".join(x for x in (", ".join(a.get("selected") or []), str(a.get("custom") or "").strip()) if x)


def question_text(notice: Notice) -> str:
    lines = []
    if notice.nudged_after_min:
        lines.append(f"🔔 Nobody has answered this for {notice.nudged_after_min} min.")
    lines.append(f"❓ {header(notice)} is waiting for your OK before {notice.node}.")
    for up in notice.upstream[:2]:
        if isinstance(up, dict):
            words = output_gist(up.get("output"), 600) if isinstance(up.get("output"), (dict, str)) else ""
            if words:
                lines.append(f"{up.get('name') or up.get('node') or 'The previous step'} said: {words}")
    n = len(notice.questions)
    for i, q in enumerate(notice.questions):
        lines.append(f"\n{i + 1}. {clip(q.get('question'), 600)}" + (" (pick any)" if q.get("multiSelect") else ""))
        if q.get("detail"):
            lines.append(f"   {clip(q.get('detail'), 300)}")
        for o in [o for o in (q.get("options") or []) if isinstance(o, dict) and o.get("label")][:10]:
            desc = f": {clip(o['description'], 140)}" if o.get("description") else ""
            lines.append(f"   • {clip(o['label'], 80)}{desc}")
    if n > 1:
        how = "Reply to this comment with one line per question (\"1. …\", \"2. …\")"
    elif n == 1:
        how = "Reply to this comment with your answer (an option's name, or your own words)"
    else:
        how = "Reply to this comment with \"approve\" (and anything the next step should know)"
    lines.append(f"\n{how}. Reply \"reject\" to stop the run.{link(notice)}")
    return fit("\n".join(lines))


def stuck_text(notice: Notice) -> str:
    at = f" in {', '.join(notice.active_nodes)}" if notice.active_nodes else ""
    return fit(f"⚠️ {header(notice)} has had no new event for {notice.idle_min} min{at}.{link(notice)}")


def ended_text(notice: Notice) -> str:
    s = notice.summary
    status = str(s.get("status") or notice.status or "?")
    bits = [b for b in (duration(s.get("duration_seconds")), cost(s.get("total_cost_usd"))) if b]
    lines = [f"{EMOJI.get(status, '☑️')} {header(notice)} {status}" + (f" after {', '.join(bits)}" if bits else "")]
    stopped = notice.stopped_by or s.get("stopped_by")
    if stopped:
        lines.append(str(stopped))
    elif s.get("failure_summary"):
        lines.append(clip(s["failure_summary"], 1000))
    if status == "completed":
        shown = output_gist(s.get("output"), 1200)
        if shown:
            lines.append(shown)
    return fit("\n".join(lines) + link(notice))


def render(notice: Notice) -> str:
    if notice.kind == "question":
        return question_text(notice)
    if notice.kind == "stuck":
        return stuck_text(notice)
    return ended_text(notice)


def fit(text: str) -> str:
    return text if len(text) <= COMMENT_MAX else text[: COMMENT_MAX - 1] + "…"


class NotionSender:
    via = "notion"

    def __init__(self, client: NotionClient, config: ConfigWatcher) -> None:
        self.client = client
        self.config = config

    def canonical(self, target: str) -> str:
        """A target name or page id -> the page id."""
        found = self.config.get().target(target)
        if found is not None:
            if found.is_table:
                raise ValueError(f"Notion target {found.name} is a table; a place is a page")
            return found.page
        pid = normalize_id(target)
        if not pid:
            raise ValueError(f"{target!r} is not a Notion target name or page id")
        return pid

    def origins(self, execution_id: str) -> list[str]:
        return [p["page_id"] for p in store.pages_of(execution_id, origin_only=True)]

    def _discussion(self, execution_id: str, page_id: str) -> str:
        for p in store.pages_of(execution_id):
            if p["page_id"] == page_id and p["discussion_id"]:
                return str(p["discussion_id"])
        return ""

    def post(self, execution_id: str, page_id: str, text: str, question: bool = False) -> dict[str, Any]:
        """A comment in the run's thread on the page (starting it if needed)."""
        discussion = self._discussion(execution_id, page_id)
        try:
            made = self.client.comment(page_id, text, discussion_id=discussion or None)
        except NotionError as exc:
            if not discussion or exc.status not in (400, 404):
                raise
            made = self.client.comment(page_id, text)   # the thread is gone: start a new one
        new_discussion = str(made.get("discussion_id") or "")
        if new_discussion and new_discussion != discussion:
            store.set_discussion(execution_id, page_id, new_discussion)
        store.save_comment(str(made.get("id") or ""), page_id, execution_id, new_discussion, question=question)
        return made

    def send(self, notice: Notice, target: str, copy: Copy) -> str:
        made = self.post(notice.execution_id, target, render(notice), question=notice.kind == "question")
        return f"{target}:{normalize_id(str(made.get('id') or ''))}"

    def close_question(self, copy: Copy, notice: Notice, decision: Decision) -> None:
        where = split_ref(copy.ref)
        if where is None:
            return
        reason = f": {clip(decision.reason, 300)}" if decision.reason and decision.verdict in ("approved", "rejected") else ""
        answers = "".join(f"\n• {q}: {a}" for q, a in decision.answers if a)
        try:
            self.post(copy.execution_id, where[0], fit(f"☑️ {decision.line()}{reason}{answers}"))
        except NotionError as exc:
            logger.warning("Notion: could not say the question on %s was answered: %s", where[0], exc)

    def close_stuck(self, copy: Copy, notice: Notice) -> None:
        # The finished or failed notice that follows says it ended.
        return None
