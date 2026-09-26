"""Slack tools for agents: post a message, reply in a thread, read a thread.

They act as the temper bot (``SLACK_BOT_TOKEN``), and only where the Slack
config's ``agents:`` list allows (``configs/local/slack.yaml``), so an agent
that reads text written by people cannot be talked into messaging anyone
else. A thread temper opened for a run may also be replied to and read.

``to`` names the place: a channel id (``C…``), ``#name`` from the list, or a
user id (``U…``), which means the bot's DM with that person.
"""

from __future__ import annotations

import json
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

MAX_TEXT = 3500
MAX_READ = 100

_TO = {"type": "string", "description": "Where: a channel id (C…), #channel-name, or a user id (U…) for a DM"}


def _allowed(to: str, thread_ts: str | None = None) -> tuple[bool, str]:
    """Whether an agent may use ``to`` (and the thread), and why not."""
    from temper_ai.integrations.slack.config import ConfigWatcher

    cfg = ConfigWatcher().get()
    if cfg.agent_may_post(to):
        return True, ""
    if thread_ts:
        from temper_ai.integrations.slack import store

        if store.run_for_thread(to, thread_ts):
            return True, ""
    allowed = cfg.agents.describe()
    return False, (f"agents may not use {to} (the Slack config allows: {allowed})" if cfg.agents
                   else "the Slack config lets agents post nowhere (no agents: list)")


def _client() -> Any:
    from temper_ai.integrations.slack.client import SlackClient, bot_token

    if not bot_token():
        raise RuntimeError("SLACK_BOT_TOKEN is not set")
    return SlackClient()


def _fail(error: str) -> ToolResult:
    return ToolResult(success=False, result="", error=error)


class SlackPost(BaseTool):
    name = "SlackPost"
    description = ("Post a new message in Slack, as the temper bot, to a channel or person the Slack config "
                   "allows. Returns the message's channel and ts (use them with SlackReply).")
    parameters = {
        "type": "object",
        "properties": {"to": _TO, "text": {"type": "string", "description": "The message (Slack mrkdwn)"}},
        "required": ["to", "text"],
    }
    modifies_state = True
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        to, text = str(params.get("to") or "").strip(), str(params.get("text") or "").strip()
        if not to or not text:
            return _fail("to and text are both required")
        ok, why = _allowed(to)
        if not ok:
            return _fail(why)
        try:
            client = _client()
            answer = client.post(client.resolve(to), text[:MAX_TEXT])
        except Exception as exc:  # noqa: BLE001 - the agent is told
            return _fail(f"{type(exc).__name__}: {exc}")
        out = {"channel": answer.get("channel"), "ts": answer.get("ts")}
        return ToolResult(success=True, result=json.dumps(out), metadata=out)


class SlackReply(BaseTool):
    name = "SlackReply"
    description = ("Reply in a Slack thread, as the temper bot. The thread is the ts of its first message, in a "
                   "channel or DM the Slack config allows, or a thread temper opened for a run.")
    parameters = {
        "type": "object",
        "properties": {
            "to": _TO,
            "thread_ts": {"type": "string", "description": "The ts of the thread's first message"},
            "text": {"type": "string", "description": "The reply (Slack mrkdwn)"},
        },
        "required": ["to", "thread_ts", "text"],
    }
    modifies_state = True
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        to = str(params.get("to") or "").strip()
        ts = str(params.get("thread_ts") or "").strip()
        text = str(params.get("text") or "").strip()
        if not to or not ts or not text:
            return _fail("to, thread_ts and text are all required")
        try:
            client = _client()
            channel = client.resolve(to)
            ok, why = _allowed(to, ts)
            if not ok and channel != to:
                ok, why = _allowed(channel, ts)
            if not ok:
                return _fail(why)
            answer = client.post(channel, text[:MAX_TEXT], thread_ts=ts)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"{type(exc).__name__}: {exc}")
        out = {"channel": answer.get("channel"), "ts": answer.get("ts"), "thread_ts": ts}
        return ToolResult(success=True, result=json.dumps(out), metadata=out)


class SlackReadThread(BaseTool):
    name = "SlackReadThread"
    description = ("Read a Slack thread (its first message and the replies, oldest first) in a channel or DM "
                   "the Slack config allows, or a thread temper opened for a run.")
    parameters = {
        "type": "object",
        "properties": {
            "to": _TO,
            "thread_ts": {"type": "string", "description": "The ts of the thread's first message"},
            "limit": {"type": "integer", "description": f"At most this many messages (default 50, max {MAX_READ})"},
        },
        "required": ["to", "thread_ts"],
    }
    modifies_state = False
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        to = str(params.get("to") or "").strip()
        ts = str(params.get("thread_ts") or "").strip()
        try:
            limit = max(1, min(int(params.get("limit") or 50), MAX_READ))
        except (TypeError, ValueError):
            limit = 50
        if not to or not ts:
            return _fail("to and thread_ts are both required")
        try:
            client = _client()
            channel = client.resolve(to)
            ok, why = _allowed(to, ts)
            if not ok and channel != to:
                ok, why = _allowed(channel, ts)
            if not ok:
                return _fail(why)
            messages = client.replies(channel, ts, limit=limit)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"{type(exc).__name__}: {exc}")
        out = [{"ts": m.get("ts"), "who": "temper" if m.get("bot_id") else m.get("user"),
                "text": str(m.get("text") or "")[:2000]} for m in messages]
        return ToolResult(success=True, result=json.dumps(out, ensure_ascii=False),
                          metadata={"channel": channel, "count": len(out)})
