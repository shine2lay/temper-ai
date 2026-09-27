"""TelegramSend: an agent posts a message to Telegram, as temper's bot.

It may post only to a place the notify config names in its ``agents:``
list (configs/notify/local/notify.yaml), or to ``origin``: the Telegram
chat the run was started from, as a reply under the run's first message.
Chat ids are never accepted, so an agent that reads text written by people
cannot be talked into messaging anyone else.
"""

from __future__ import annotations

import json
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

MAX_TEXT = 3500
ORIGIN = "origin"


def _fail(error: str) -> ToolResult:
    return ToolResult(success=False, result="", error=error)


class TelegramSend(BaseTool):
    name = "TelegramSend"
    description = ("Send a message in Telegram, as temper's bot, to a place the notify config lets agents use "
                   "(by its name, e.g. \"telegram\"), or to \"origin\": the Telegram chat this run was started "
                   "from, as a reply under the run's first message. Text may use *bold*, `code` and ``` blocks.")
    parameters = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "A place name from the notify config's agents: list, or origin"},
            "text": {"type": "string", "description": "The message"},
        },
        "required": ["to", "text"],
    }
    modifies_state = True
    local_paths = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._execution_context: Any = None

    def bind_context(self, context: Any) -> None:
        """The agent binds its run, so ``origin`` means this run's chat."""
        self._execution_context = context

    def _run_id(self) -> str:
        return str(getattr(self._execution_context, "run_id", "") or "")

    def execute(self, **params: Any) -> ToolResult:
        to = str(params.get("to") or "").strip()
        text = str(params.get("text") or "").strip()
        if not to or not text:
            return _fail("to and text are both required")
        from temper_ai.integrations.notify.config import ConfigWatcher as NotifyWatcher
        from temper_ai.integrations.telegram import store
        from temper_ai.integrations.telegram.client import TelegramClient, bot_token
        from temper_ai.integrations.telegram.render import mrkdwn

        if not bot_token():
            return _fail("TELEGRAM_BOT_TOKEN is not set")
        reply_to: int | None = None
        if to == ORIGIN:
            run_id = self._run_id()
            threads = store.threads_of(run_id, origin_only=True) if run_id else []
            if not threads:
                return _fail("this run was not started from Telegram, so it has no origin chat")
            chat, reply_to = threads[0]
        else:
            places = NotifyWatcher().get().agent_places("telegram")
            if to not in places:
                allowed = ", ".join(sorted(places)) or "none"
                return _fail(f"agents may not send to {to!r}: use origin or a place the notify config's "
                             f"agents: list names (allowed here: {allowed})")
            chat = int(places[to].target)
            run_id = self._run_id()
            reply_to = store.thread_for(run_id, chat) if run_id else None
        try:
            answer = TelegramClient().send(chat, mrkdwn(text[:MAX_TEXT]), reply_to=reply_to)
        except Exception as exc:  # noqa: BLE001 - the agent is told
            return _fail(f"{type(exc).__name__}: {exc}")
        out = {"to": to, "message_id": answer.get("message_id")}
        return ToolResult(success=True, result=json.dumps(out), metadata=out)
