"""Slack as a place the notify layer sends to.

Every notice about a run goes into that run's thread in each channel or
DM (``store.thread_for``), started by its first notice there. Questions,
failures and quiet runs are also shown in the channel (``reply_broadcast``).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from temper_ai.integrations.notify.notice import Copy, Decision, Notice
from temper_ai.integrations.slack import blocks, store
from temper_ai.integrations.slack.client import SlackClient

logger = logging.getLogger(__name__)

BROADCAST = ("question", "failed", "stuck")
VERDICT_EMOJI = {"approved": ":white_check_mark:", "rejected": ":no_entry:", "resumed": ":arrows_counterclockwise:"}
STOP_VERBS = {"stop": "Stopped", "reject": "Rejected"}


def stopped_by(execution_id: str) -> str:
    """"Stopped in Slack by @x" when someone stopped (or rejected) the run
    from Slack, else ""."""
    try:
        for act in store.actions(limit=20, execution_id=execution_id):
            verb = STOP_VERBS.get(act["action"])
            if verb:
                return f"{verb} in Slack by <@{act['user_id']}>"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Slack: could not look up who stopped %s: %s", execution_id[:8], exc)
    return ""


def gate_info(notice: Notice) -> dict[str, Any]:
    return {"node_name": notice.node, "event_id": notice.event_id, "upstream": notice.upstream,
            "questions": notice.questions}


def render(notice: Notice) -> dict[str, Any]:
    """A notice as a Slack message ({text, blocks})."""
    run = {"id": notice.execution_id, "workflow": notice.workflow, "status": notice.status}
    if notice.kind == "question":
        message = blocks.gate(run, gate_info(notice), notice.url)
        if notice.nudged_after_min:
            note = f":bell: Nobody has answered this for {notice.nudged_after_min} min."
            message = {"text": f"Still waiting: {message['text']}",
                       "blocks": [blocks.context(note)] + message["blocks"]}
        return message
    if notice.kind == "stuck":
        return blocks.stuck(run, notice.idle_min, notice.last_at, notice.active_nodes, notice.url)
    summary = dict(notice.summary)
    if summary.get("status") == "cancelled":
        summary["stopped_by"] = stopped_by(notice.execution_id) or notice.stopped_by
    return blocks.ended(summary, notice.url)


def decision_line(decision: Decision) -> str:
    emoji = VERDICT_EMOJI.get(decision.verdict, ":information_source:")
    line = f"{emoji} {blocks.esc(decision.line())}"
    if decision.reason and decision.verdict in ("approved", "rejected"):
        line += f": {blocks.esc(blocks.clip(decision.reason, 300))}"
    return line


class SlackSender:
    via = "slack"

    def __init__(self, client: SlackClient) -> None:
        self.client = client
        self._resolved: dict[str, str] = {}
        self._lock = threading.Lock()

    def canonical(self, target: str) -> str:
        """A DM's user id, a #name or a channel id, as the channel id."""
        with self._lock:
            if target in self._resolved:
                return self._resolved[target]
        channel = self.client.resolve(target)
        with self._lock:
            self._resolved[target] = channel
        return channel

    def origins(self, execution_id: str) -> list[str]:
        return [channel for channel, _ in store.threads_of(execution_id, origin_only=True)]

    def send(self, notice: Notice, target: str, copy: Copy) -> str:
        message = render(notice)
        channel = self.canonical(target)
        thread = store.thread_for(notice.execution_id, channel)
        answer = self.client.post(channel, message["text"], message.get("blocks"), thread_ts=thread,
                                  broadcast=bool(thread) and notice.kind in BROADCAST)
        ts = str(answer.get("ts") or "")
        if not thread and ts:
            store.save_thread(notice.execution_id, channel, ts)
        return f"{channel}:{ts}"

    def close_question(self, copy: Copy, notice: Notice, decision: Decision) -> None:
        channel, _, ts = copy.ref.partition(":")
        if not ts:
            return
        message = render(Notice(**{**notice.__dict__, "nudged_after_min": 0}))
        self.client.update(channel, ts, f"{message['text']} ({decision.verdict})",
                           blocks.decided(message.get("blocks"), decision_line(decision), decision.verdict))

    def close_stuck(self, copy: Copy, notice: Notice) -> None:
        channel, _, ts = copy.ref.partition(":")
        if not ts:
            return
        status = notice.status or "ended"
        emoji = blocks.STATUS_EMOJI.get(status, ":grey_question:")
        text = f"{notice.workflow} ({blocks.short(notice.execution_id)}) went quiet, then ended ({status})"
        body = [blocks.section(f"{emoji} {blocks.run_header(notice.workflow, notice.execution_id, notice.url)} "
                               f"went quiet for a while; it has since ended (*{blocks.esc(status)}*).")]
        self.client.update(channel, ts, text, body)
