"""Telegram as a place the notify layer sends to.

Every notice about a run replies to that run's first message in the chat
(``store.thread_for``), so a run's messages stay together. A copy's ref is
``"<chat id>:<message id>"``; a question's answers so far live in its
copy's ``state`` (see handlers.py).
"""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.integrations.notify.notice import Copy, Decision, Notice
from temper_ai.integrations.telegram import render, store
from temper_ai.integrations.telegram.client import TelegramClient, TelegramError
from temper_ai.integrations.telegram.config import ConfigWatcher

logger = logging.getLogger(__name__)

# These ping; a finished run arrives without a sound.
LOUD = ("question", "failed", "stuck")


def split_ref(ref: str) -> tuple[int, int] | None:
    chat, _, message = (ref or "").partition(":")
    try:
        return int(chat), int(message)
    except ValueError:
        return None


def link_row(notice: Notice) -> list[list[dict[str, Any]]]:
    return [[render.link_button("Open in temper", notice.url)]] if notice.url else []


class TelegramSender:
    via = "telegram"

    def __init__(self, client: TelegramClient, config: ConfigWatcher) -> None:
        self.client = client
        self.config = config

    @property
    def zone(self) -> str:
        return self.config.get().zone

    def canonical(self, target: str) -> str:
        return str(int(str(target).strip()))

    def origins(self, execution_id: str) -> list[str]:
        return [str(chat) for chat, _ in store.threads_of(execution_id, origin_only=True)]

    def keyboard(self, notice: Notice, copy: Copy) -> list[list[dict[str, Any]]]:
        if notice.kind == "question":
            return render.question_keyboard(copy.id, notice, copy.state)
        if notice.kind == "stuck":
            return render.stuck_keyboard(copy.id, notice)
        return link_row(notice)

    def send(self, notice: Notice, target: str, copy: Copy) -> str:
        chat = int(target)
        text = render.question_text(notice, self.zone, copy.state) if notice.kind == "question" \
            else render.render(notice, self.zone)
        try:
            answer = self._send(chat, notice, text, copy)
        except TelegramError as exc:
            moved = (exc.parameters or {}).get("migrate_to_chat_id")
            if not moved:
                raise
            # The group became a supergroup: it has a new id from now on.
            store.move_chat(chat, int(moved))
            chat = int(moved)
            answer = self._send(chat, notice, text, copy)
        message_id = int(answer.get("message_id") or 0)
        if message_id and store.thread_for(notice.execution_id, chat) is None:
            store.save_thread(notice.execution_id, chat, message_id)
        return f"{chat}:{message_id}"

    def _send(self, chat: int, notice: Notice, text: str, copy: Copy) -> dict[str, Any]:
        return self.client.send(chat, text, reply_to=store.thread_for(notice.execution_id, chat),
                                keyboard=self.keyboard(notice, copy), quiet=notice.kind not in LOUD)

    def close_question(self, copy: Copy, notice: Notice, decision: Decision) -> None:
        where = split_ref(copy.ref)
        if where is None:
            return
        state = {k: v for k, v in (copy.state or {}).items() if k != "confirm_reject"}
        text = render.question_text(Notice(**{**notice.__dict__, "nudged_after_min": 0}), self.zone,
                                    state, decision)
        self._edit(where, text, link_row(notice))

    def close_stuck(self, copy: Copy, notice: Notice) -> None:
        where = split_ref(copy.ref)
        if where is None:
            return
        self._edit(where, render.stuck_text(notice, self.zone, ended=notice.status or "ended"), link_row(notice))

    def _edit(self, where: tuple[int, int], text: str, keyboard: list[list[dict[str, Any]]]) -> None:
        try:
            self.client.edit_text(where[0], where[1], text, keyboard)
        except TelegramError as exc:
            if exc.gone:
                logger.info("Telegram: message %s/%s is gone; nothing to update", *where)
                return
            raise
