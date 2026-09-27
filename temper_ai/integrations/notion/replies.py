"""A person's comment that answers a question temper asked on a Notion page.

Notion comments have no buttons, so the answer is the words: a reply in the
question's discussion (or, if the person started a new comment instead, any
comment on a page whose run is waiting on a question posted there).

    reject / no / stop ...      -> the run is stopped
    one question                 -> the reply is its answer (an option's name
                                    picks that option; anything else is typed)
    several questions            -> "1. ..." / "2: ..." lines, one per question;
                                    unnumbered text answers the first
    no questions (a plain OK)    -> approve; the words go to the next step

The gate then goes on exactly as if it was answered in Slack or Telegram,
and every other copy of the question says who answered in Notion.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from temper_ai.integrations.notify import service as notify
from temper_ai.integrations.notify import store as notify_store
from temper_ai.integrations.notify.loop import question_notice
from temper_ai.integrations.notify.notice import Copy, Decision, Notice
from temper_ai.integrations.notion import store
from temper_ai.integrations.notion.client import NotionClient, NotionError, normalize_id

logger = logging.getLogger(__name__)

REJECT = re.compile(r"^\s*(reject|rejected|no|stop|cancel)\b", re.IGNORECASE)
APPROVE_ONLY = re.compile(r"^\s*(approve|approved|yes|ok|okay|go|lgtm)\W*$", re.IGNORECASE)
NUMBERED = re.compile(r"^\s*(\d{1,2})\s*[.:)\-]\s*(.*)$")


def open_question(page_id: str, discussion_id: str) -> Copy | None:
    """The open Notion question this comment may answer."""
    page = normalize_id(page_id)
    run = store.question_in(discussion_id) if discussion_id else None
    found = notify_store.copies(kind="question", via="notion")
    for c in found:
        if run and c.execution_id == run and c.target == page:
            return c
    on_page = [c for c in found if c.target == page]
    return on_page[0] if len(on_page) == 1 else None


def parse(text: str, questions: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], str]:
    """("reject" | "approve", answers in the gate's shape, response words)."""
    text = (text or "").strip()
    if REJECT.match(text):
        return "reject", [], REJECT.sub("", text, count=1).strip(" :,-.")
    if not questions:
        return "approve", [], "" if APPROVE_ONLY.match(text) else text
    given: dict[int, str] = {}
    loose: list[str] = []
    for line in text.splitlines():
        m = NUMBERED.match(line)
        if m and 1 <= int(m.group(1)) <= len(questions) and len(questions) > 1:
            given[int(m.group(1)) - 1] = m.group(2).strip()
        elif line.strip():
            loose.append(line.strip())
    if loose and 0 not in given:
        given[0] = " ".join(loose)
    answers = []
    for i, q in enumerate(questions):
        words = given.get(i, "").strip()
        if not words or (len(questions) == 1 and APPROVE_ONLY.match(words)):
            continue
        labels = [str(o.get("label")) for o in q.get("options") or [] if isinstance(o, dict) and o.get("label")]
        chosen = [lab for lab in labels if lab.lower() == words.lower()]
        if q.get("multiSelect") and not chosen:
            parts = [p.strip().lower() for p in re.split(r"[,;]", words)]
            picked = [lab for lab in labels if lab.lower() in parts]
            if picked and len(picked) == len([p for p in parts if p]):
                chosen = picked
        answers.append({"id": str(q.get("id") or f"q{i + 1}"), "question": str(q.get("question") or ""),
                        "selected": chosen, "custom": "" if chosen else words})
    return "approve", answers, ""


def person_name(client: NotionClient, user_id: str) -> str:
    try:
        return str(client.get(f"/users/{normalize_id(user_id)}").get("name") or "someone")
    except NotionError:
        return "someone"


def answer(copy: Copy, text: str, who: str, ops: Any, notify_cfg: Any) -> str:
    """Answer the gate; returns what happened, in a few words."""
    raw = ops.gate_decision(copy.event_id) if copy.event_id else None
    if raw is None or raw.get("status") != "waiting":
        decision = Decision.from_event(raw)
        notify.close_question(copy.key, decision)
        return "the question was already answered"
    workflow = ""
    try:
        workflow = str(ops.summary(copy.execution_id).get("workflow") or "")
    except Exception:  # noqa: BLE001 - only a name is lost
        pass
    notice: Notice = question_notice(notify_cfg, copy.execution_id, workflow,
                                     {"id": copy.event_id, "data": raw.get("data") or {}})
    verdict, answers, response = parse(text, notice.questions)
    eid, node = copy.execution_id, copy.node or notice.node
    by = f"{who} (Notion)"
    if verdict == "reject":
        ops.cancel(eid, f"Rejected in Notion by {who}" + (f": {response}" if response else ""), by=by)
        decision = Decision("rejected", who, "Notion", response)
    else:
        alive = ops.run_is_alive(eid)
        ops.approve(eid, node, answers, response, by=by)
        if not alive:
            ops.resume(eid)
        pairs = tuple((a["question"] or a["id"], ", ".join(a["selected"]) or a["custom"]) for a in answers)
        decision = Decision("approved" if alive else "resumed", who, "Notion", response, pairs)
    notify.close_question(copy.key, decision)
    return f"{decision.verdict} run {eid[:8]}"
