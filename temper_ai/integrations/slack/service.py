"""Temper's Slack side, put together and run by the server.

    socket (Slack -> temper): slash commands, button clicks, mentions, DMs
    notifier (temper -> Slack): gate waiting, stuck, failed, finished

Started from the server's lifespan when both tokens are set and
``TEMPER_SLACK`` is not off. Starting does no network I/O: the socket
connects and the bot looks itself up on their own threads, so a Slack
outage or a bad token never delays or stops the server. Only one process
may hold the socket (Slack gives each envelope to one connection), so a
second server on the same app runs with ``TEMPER_SLACK=0``.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from temper_ai.integrations.slack.client import (
    SlackClient,
    SlackError,
    app_token,
    bot_token,
)
from temper_ai.integrations.slack.config import ConfigWatcher
from temper_ai.integrations.slack.handlers import Handler
from temper_ai.integrations.slack.notifier import Notifier, RunPoster
from temper_ai.integrations.slack.ops import TemperOps
from temper_ai.integrations.slack.socket import SocketMode

logger = logging.getLogger(__name__)

SWITCH_ENV = "TEMPER_SLACK"
OFF = ("0", "false", "off", "no")

_service: SlackService | None = None


def switched_on() -> bool:
    return os.environ.get(SWITCH_ENV, "1").strip().lower() not in OFF


def why_off() -> str | None:
    """None when Slack can start; otherwise the reason it doesn't."""
    if not switched_on():
        return f"{SWITCH_ENV} is off"
    missing = [name for name, value in (("SLACK_BOT_TOKEN", bot_token()), ("SLACK_APP_TOKEN", app_token()))
               if not value]
    if missing:
        return f"{' and '.join(missing)} not set"
    return None


class SlackService:
    def __init__(self, client: SlackClient | None = None, config: ConfigWatcher | None = None,
                 ops: TemperOps | None = None) -> None:
        self.client = client or SlackClient()
        self.config = config or ConfigWatcher()
        self.ops = ops or TemperOps()
        self.poster = RunPoster(self.client)
        self.handler = Handler(self.client, self.config, self.ops, self.poster)
        self.notifier = Notifier(self.poster, self.config, self.ops)
        self.socket = SocketMode(self.client.open_socket_url, self.handler.submit)
        self.bot: dict[str, Any] = {}
        self.auth_error: str | None = None

    def start(self) -> None:
        threading.Thread(target=self._who_am_i, name="slack-auth", daemon=True).start()
        self.socket.start()
        self.notifier.start()

    def _who_am_i(self) -> None:
        try:
            self.bot = self.client.auth_test()
            self.handler.bot_user = str(self.bot.get("user_id") or "")
            logger.info("Slack: signed in as %s in %s", self.bot.get("user"), self.bot.get("team"))
        except (SlackError, OSError) as exc:
            self.auth_error = str(exc)
            logger.warning("Slack: the bot token does not work (%s); notices will fail until it does", exc)

    def stop(self) -> None:
        self.socket.stop()
        self.notifier.stop()
        self.handler.shutdown()

    def status(self) -> dict[str, Any]:
        cfg = self.config.get()
        return {
            "running": True,
            "bot": {k: self.bot.get(k) for k in ("user", "user_id", "team", "team_id")} if self.bot else None,
            "auth_error": self.auth_error,
            "socket": self.socket.status(),
            "notifier": {"last_tick_at": self.notifier.last_tick_at, "sent": self.notifier.sent,
                         "last_error": self.notifier.last_error},
            "handler": {"handled": self.handler.handled, "last_error": self.handler.last_error},
            "config": {"path": cfg.path, "error": self.config.error},
        }


def start_slack() -> SlackService | None:
    """Start Slack if it can; never raises (the server must start either way)."""
    global _service
    reason = why_off()
    if reason:
        logger.info("Slack: off (%s)", reason)
        return None
    try:
        service = SlackService()
        service.start()
    except Exception as exc:  # noqa: BLE001 - a Slack problem must not stop the server
        logger.warning("Slack failed to start: %s", exc)
        return None
    _service = service
    return service


def stop_slack() -> None:
    global _service
    if _service is not None:
        _service.stop()
        _service = None


def status() -> dict[str, Any]:
    if _service is not None:
        return _service.status()
    return {"running": False, "reason": why_off() or "not started in this process"}
