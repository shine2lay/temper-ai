"""Temper's Telegram bot, put together and run by the server.

    poller (Telegram -> temper): commands, plain messages, button presses,
      being added to groups (handlers.py); each update is saved in the event
      inbox first, so none is lost to a restart or an error
    sender (temper -> Telegram): the notify layer's questions and notices
      (temper_ai/integrations/notify decides what goes where)

Started from the server's lifespan when ``TELEGRAM_BOT_TOKEN`` is set and
``TEMPER_TELEGRAM`` is not off. Starting does no network I/O on the
server's thread: the bot looks itself up on the poller's thread, so a
Telegram outage or a bad token never delays or stops the server. Only one
process may poll a bot, so a second server runs with ``TEMPER_TELEGRAM=0``.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from temper_ai.integrations.inbox import service as inbox
from temper_ai.integrations.notify import service as notify
from temper_ai.integrations.telegram import store
from temper_ai.integrations.telegram.client import (
    TelegramClient,
    TelegramError,
    bot_token,
)
from temper_ai.integrations.telegram.config import ConfigWatcher
from temper_ai.integrations.telegram.handlers import COMMANDS, SOURCE, Handler, describe
from temper_ai.integrations.telegram.poller import Poller
from temper_ai.integrations.telegram.sender import TelegramSender

logger = logging.getLogger(__name__)

SWITCH_ENV = "TEMPER_TELEGRAM"
OFF = ("0", "false", "off", "no")

_service: TelegramService | None = None


def switched_on() -> bool:
    return os.environ.get(SWITCH_ENV, "1").strip().lower() not in OFF


def why_off() -> str | None:
    if not switched_on():
        return f"{SWITCH_ENV} is off"
    if not bot_token():
        return "TELEGRAM_BOT_TOKEN not set"
    return None


class TelegramService:
    def __init__(self, client: TelegramClient | None = None, config: ConfigWatcher | None = None) -> None:
        self.client = client or TelegramClient()
        self.config = config or ConfigWatcher()
        self.sender = TelegramSender(self.client, self.config)
        self.handler: Handler | None = None
        self.poller: Poller | None = None
        self.bot: dict[str, Any] = {}
        self.webhook: str = ""
        self.last_error: str | None = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    def start(self) -> None:
        # Notices can go out at once; the bot's own id is looked up (and
        # polling begins) on another thread.
        notify.register(self.sender)
        self._thread = threading.Thread(target=self._begin, name="telegram-start", daemon=True)
        self._thread.start()

    def _begin(self) -> None:
        delay = 5.0
        while not self._stopped.is_set():
            try:
                self.bot = self.client.get_me()
                self.webhook = str((self.client.get_webhook_info() or {}).get("url") or "")
                break
            except TelegramError as exc:
                self.last_error = f"could not reach Telegram: {exc}"
                logger.warning("Telegram: %s; retrying in %.0fs", self.last_error, delay)
                self._stopped.wait(delay)
                delay = min(delay * 2, 300.0)
        if self._stopped.is_set():
            return
        if self.webhook:
            # getUpdates is refused while a webhook is set; removing it is
            # the owner's call, not temper's.
            self.last_error = ("a webhook is set for this bot, so temper cannot poll it; "
                               "remove it (deleteWebhook) to use the bot from temper")
            logger.warning("Telegram: %s", self.last_error)
            return
        self.last_error = None
        self.handler = Handler(self.client, self.config, bot=self.bot, sender=self.sender)
        try:
            self.client.set_commands(COMMANDS)
        except TelegramError as exc:
            logger.info("Telegram: could not set the command menu: %s", exc)
        inbox.register(SOURCE, self.handler.handle_saved)
        self.poller = Poller(self.client, self.handler.submit, accept=self.save, skip=self.save_skipped)
        self.poller.start()
        logger.info("Telegram: polling as @%s", self.bot.get("username"))

    @staticmethod
    def save(update: dict[str, Any]) -> int | None:
        """Keep an update in the inbox before the offset moves: its event id,
        or None if it was kept before (Telegram sent it again)."""
        kind, chat = describe(update)
        event, new = inbox.receive(SOURCE, str(update.get("update_id")), kind=kind, subject=chat, payload=update)
        return event.id if new else None

    @staticmethod
    def save_skipped(update: dict[str, Any], why: str) -> None:
        kind, chat = describe(update)
        inbox.receive(SOURCE, str(update.get("update_id")), kind=kind, subject=chat, payload=update, skipped=why)

    def stop(self) -> None:
        self._stopped.set()
        notify.unregister(self.sender.via)
        if self.poller is not None:
            self.poller.stop()
        if self.handler is not None:
            inbox.unregister(SOURCE, self.handler.handle_saved)
            self.handler.shutdown()

    def status(self) -> dict[str, Any]:
        cfg = self.config.get()
        p = self.poller
        try:
            chats = store.chats()
        except Exception as exc:  # noqa: BLE001
            chats = []
            logger.warning("Telegram: could not list chats: %s", exc)
        return {
            "running": bool(p and p.running),
            "bot": {"id": self.bot.get("id"), "username": self.bot.get("username"),
                    "reads_all_group_messages": self.bot.get("can_read_all_group_messages")},
            "webhook": bool(self.webhook),
            "last_error": self.last_error or (p.last_error if p else None),
            "poll": {"last_at": p.last_poll_at if p else None, "received": p.received if p else 0,
                     "skipped": p.skipped if p else 0, "conflict": p.conflict if p else False},
            "handler": {"handled": self.handler.handled if self.handler else 0,
                        "last_error": self.handler.last_error if self.handler else None},
            "config": {"path": cfg.path, "error": self.config.error, "owners": len(cfg.owners),
                       "groups": len(cfg.groups), "zone": cfg.zone},
            "chats": {status: [c for c in chats if c["status"] == status]
                      for status in ("allowed", "refused", "left")},
            "notify": "telegram" in (notify.status().get("senders") or []),
        }


def start_telegram() -> TelegramService | None:
    """Start the bot if it can; never raises (the server must start either way)."""
    global _service
    reason = why_off()
    if reason:
        logger.info("Telegram: off (%s)", reason)
        return None
    try:
        service = TelegramService()
        service.start()
    except Exception as exc:  # noqa: BLE001 - a Telegram problem must not stop the server
        logger.warning("Telegram failed to start: %s", exc)
        return None
    _service = service
    return service


def stop_telegram() -> None:
    global _service
    if _service is not None:
        _service.stop()
        _service = None


def status() -> dict[str, Any]:
    if _service is not None:
        return _service.status()
    return {"running": False, "reason": why_off() or "not started in this process"}
