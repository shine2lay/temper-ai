"""A small Telegram Bot API client (https://core.telegram.org/bots/api).

Every method is a POST of JSON to ``https://api.telegram.org/bot<token>/<method>``;
the answer is ``{"ok": true, "result": ...}`` or ``{"ok": false,
"error_code": ..., "description": ..., "parameters": {...}}``.

Flood control answers 429 with ``parameters.retry_after`` seconds: short
waits are waited out and the call is tried again. Text over 4096
characters is split into several messages. The token is never logged:
errors name the method, never the URL, and httpx's own log of each
request (which shows the URL, token and all) has the token taken out.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TEXT_MAX = 4096
RETRY_MAX_S = 30.0

_TOKEN_IN_URL = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")


class HideToken(logging.Filter):
    """httpx logs every request at INFO with its URL, and a Bot API URL holds
    the bot token. Take the token out of such lines, and drop the long-poll
    requests (one every 30 s, all day) altogether."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:  # a broken record: leave it to logging
            return True
        if "/bot" not in text:
            return True
        if "/getUpdates" in text and record.levelno < logging.WARNING:
            return False
        record.msg, record.args = _TOKEN_IN_URL.sub("/bot<token>", text), None
        return True


def hide_token_in_logs() -> None:
    """Put the filter on httpx's loggers (once per process)."""
    for name in ("httpx", "httpcore"):
        target = logging.getLogger(name)
        if not any(isinstance(f, HideToken) for f in target.filters):
            target.addFilter(HideToken())


hide_token_in_logs()


def bot_token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


class TelegramError(RuntimeError):
    def __init__(self, method: str, code: int, description: str, parameters: dict[str, Any] | None = None) -> None:
        super().__init__(f"{method}: {code} {description}")
        self.method = method
        self.code = code
        self.description = description
        self.parameters = parameters or {}

    @property
    def gone(self) -> bool:
        """The message or chat is not there (any more), or the bot may not
        write there: trying again will not help."""
        text = self.description.lower()
        return self.code in (400, 403) and any(s in text for s in (
            "not found", "kicked", "blocked", "deactivated", "not enough rights", "have no rights",
            "chat not found", "message to edit not found", "can't be edited"))

    @property
    def unchanged(self) -> bool:
        return self.code == 400 and "message is not modified" in self.description.lower()


def split_text(text: str, limit: int = TEXT_MAX) -> list[str]:
    """Pieces of at most ``limit`` characters, cut at a line break where one
    is near. (Only for plain text: a cut could break an HTML tag, so HTML
    messages are built short enough instead.)"""
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", limit // 2, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return parts


class TelegramClient:
    def __init__(self, token: str | None = None, *, api: str = API, timeout: float = 15.0,
                 http: httpx.Client | None = None) -> None:
        self.token = token if token is not None else bot_token()
        self.api = api.rstrip("/")
        self._http = http or httpx.Client(timeout=timeout)

    def call(self, method: str, http_timeout: float | None = None, **params: Any) -> Any:
        if not self.token:
            raise TelegramError(method, 0, f"{TOKEN_ENV} is not set")
        body = {k: v for k, v in params.items() if v is not None}
        for attempt in range(3):
            try:
                response = self._http.post(f"{self.api}/bot{self.token}/{method}", json=body,
                                           timeout=http_timeout if http_timeout is not None
                                           else httpx.USE_CLIENT_DEFAULT)
            except httpx.HTTPError as exc:
                # The URL holds the token: never let it reach a log.
                raise TelegramError(method, 0, type(exc).__name__) from None
            try:
                answer = response.json()
            except ValueError:
                raise TelegramError(method, response.status_code, "the answer was not JSON") from None
            if answer.get("ok"):
                return answer.get("result")
            code = int(answer.get("error_code") or response.status_code)
            parameters = answer.get("parameters") or {}
            wait = float(parameters.get("retry_after") or 0)
            if code == 429 and wait and wait <= RETRY_MAX_S and attempt < 2:
                logger.info("Telegram: %s rate-limited, waiting %ss", method, wait)
                time.sleep(wait)
                continue
            raise TelegramError(method, code, str(answer.get("description") or ""), parameters)
        raise TelegramError(method, 429, "still rate-limited")

    # -- the calls temper makes ---------------------------------------------------

    def get_me(self) -> dict[str, Any]:
        return self.call("getMe")

    def get_webhook_info(self) -> dict[str, Any]:
        return self.call("getWebhookInfo")

    def get_updates(self, offset: int | None, timeout: int = 25, allowed: list[str] | None = None) -> list[dict]:
        return self.call("getUpdates", http_timeout=timeout + 10, offset=offset, timeout=timeout,
                         allowed_updates=allowed) or []

    def send(self, chat_id: int | str, text: str, *, reply_to: int | None = None,
             keyboard: list[list[dict[str, Any]]] | None = None, force_reply: str | None = None,
             html: bool = True, quiet: bool = False) -> dict[str, Any]:
        """Send a message (several, if plain text is too long); returns the
        last one. ``keyboard`` goes on the last piece."""
        pieces = [text] if html else split_text(text)
        answer: dict[str, Any] = {}
        for i, piece in enumerate(pieces):
            last = i == len(pieces) - 1
            markup: dict[str, Any] | None = None
            if last and keyboard is not None:
                markup = {"inline_keyboard": keyboard}
            elif last and force_reply is not None:
                markup = {"force_reply": True, "selective": True}
                if force_reply:
                    markup["input_field_placeholder"] = force_reply[:64]
            answer = self.call(
                "sendMessage", chat_id=chat_id, text=piece or " ", parse_mode="HTML" if html else None,
                reply_parameters={"message_id": reply_to, "allow_sending_without_reply": True} if reply_to else None,
                reply_markup=markup, link_preview_options={"is_disabled": True},
                disable_notification=True if quiet else None)
        return answer

    def edit_text(self, chat_id: int | str, message_id: int, text: str,
                  keyboard: list[list[dict[str, Any]]] | None = None) -> dict[str, Any] | bool:
        """Change a message's text and buttons (no ``keyboard``: none)."""
        try:
            return self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text or " ",
                             parse_mode="HTML", link_preview_options={"is_disabled": True},
                             reply_markup={"inline_keyboard": keyboard or []})
        except TelegramError as exc:
            if exc.unchanged:
                return True
            raise

    def edit_markup(self, chat_id: int | str, message_id: int,
                    keyboard: list[list[dict[str, Any]]] | None = None) -> dict[str, Any] | bool:
        try:
            return self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                             reply_markup={"inline_keyboard": keyboard or []})
        except TelegramError as exc:
            if exc.unchanged:
                return True
            raise

    def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text[:200] or None,
                      show_alert=alert or None)
        except TelegramError as exc:
            # Too late (over ~15 s) or answered twice: the button already
            # did its work, only the little notice is lost.
            logger.info("Telegram: could not answer a button press: %s", exc)

    def leave_chat(self, chat_id: int | str) -> None:
        self.call("leaveChat", chat_id=chat_id)

    def get_chat(self, chat_id: int | str) -> dict[str, Any]:
        return self.call("getChat", chat_id=chat_id)

    def get_chat_member(self, chat_id: int | str, user_id: int | str) -> dict[str, Any]:
        return self.call("getChatMember", chat_id=chat_id, user_id=user_id)

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        self.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in commands])
