"""Fetch what people send the bot (long polling with getUpdates).

temper asks Telegram for new updates and waits up to 25 s for an answer,
so it needs no public web address. Only one process may do this for a bot
at a time: a second one gets "409 Conflict", which is reported (``temper
telegram check``) and retried slowly rather than fought over.

Each update is saved in the event inbox (``accept``) before temper tells
Telegram it has it (by moving the offset, which is remembered in the
database), and only then handed on. If saving fails, the offset stays put
and Telegram sends the same updates again on the next poll; one already
saved is noticed as a repeat and not handled twice. Messages that waited
more than 10 minutes (temper was down) are kept as skipped rather than
acted on late; being added to or removed from a chat is always handled.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

from temper_ai.integrations.telegram import store
from temper_ai.integrations.telegram.client import TelegramClient, TelegramError

logger = logging.getLogger(__name__)

ALLOWED = ["message", "callback_query", "my_chat_member"]
OFFSET_KEY = "offset"
STALE_S = 600
CONFLICT_WAIT_S = 30.0
POLL_TIMEOUT_S = 25


def _age_s(update: dict[str, Any], now: float) -> float:
    msg = update.get("message")
    if isinstance(msg, dict) and msg.get("date"):
        return now - float(msg["date"])
    return 0.0


class Poller:
    def __init__(self, client: TelegramClient, submit: Any, *, timeout: int = POLL_TIMEOUT_S,
                 clock: Any = time.time, sleep: Any = None, accept: Any = None,
                 skip: Any = None) -> None:
        """``accept(update)`` saves an update and returns what ``submit`` is
        handed (its event id), or None for a repeat; ``skip(update, why)``
        keeps a note of one too old to act on. Without ``accept`` updates
        are handed on as they are."""
        self.client = client
        self.submit = submit
        self.accept = accept
        self.skip = skip
        self.timeout = timeout
        self._clock = clock
        self._stop = threading.Event()
        self._sleep = sleep or self._stop.wait
        self._thread: threading.Thread | None = None
        self.last_poll_at: str | None = None
        self.last_error: str | None = None
        self.conflict = False
        self.received = 0
        self.skipped = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="telegram-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            try:
                self.poll_once()
                backoff = 2.0
            except TelegramError as exc:
                if exc.code == 409:
                    self.conflict = True
                    self.last_error = ("another process is reading this bot's updates (409 Conflict); "
                                       "only one temper server may run the bot")
                    logger.warning("Telegram: %s", self.last_error)
                    self._sleep(CONFLICT_WAIT_S)
                else:
                    self.last_error = str(exc)
                    logger.warning("Telegram: polling failed, retrying in %.0fs: %s", backoff, exc)
                    self._sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
            except Exception as exc:  # noqa: BLE001 - keep polling whatever happens
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Telegram: polling failed")
                self._sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    def poll_once(self) -> int:
        """One getUpdates; returns how many updates were handed on."""
        stored = store.get_state(OFFSET_KEY)
        offset = int(stored) if stored else None
        updates = self.client.get_updates(offset, timeout=self.timeout, allowed=ALLOWED)
        self.last_poll_at = datetime.now(UTC).isoformat()
        self.conflict = False
        if self.last_error and "409" in self.last_error:
            self.last_error = None
        if not updates:
            return 0
        now = self._clock()
        top = max([offset or 0] + [int(u.get("update_id") or 0) + 1 for u in updates])
        # Saved first, then the offset moves, then they are handled: a crash
        # after saving leaves them in the inbox, which picks them up again.
        saved: list[Any] = []
        failed: Exception | None = None
        for update in updates:
            age = _age_s(update, now)
            try:
                if age > STALE_S:
                    self.skipped += 1
                    logger.info("Telegram: skipped update %s (sent %.0f min ago)", update.get("update_id"),
                                age / 60)
                    if self.skip is not None:
                        self.skip(update, f"skipped: sent {age / 60:.0f} min before temper got it")
                    continue
                item = self.accept(update) if self.accept is not None else update
            except Exception as exc:  # noqa: BLE001 - e.g. the database is down: Telegram sends them again
                failed = exc
                break
            if item is not None:
                saved.append(item)
        if failed is None:
            store.set_state(OFFSET_KEY, str(top))
        for item in saved:
            self.submit(item)
        self.received += len(saved)
        if failed is not None:
            raise failed
        return len(saved)
