"""The notify loop, run by the server, and the places registered with it.

Slack and Telegram each register a sender when they start; the loop sends
to whichever are on. ``TEMPER_NOTIFY=0`` turns the loop off (a second
server on the same database must not send the same notices).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from temper_ai.integrations.notify import store
from temper_ai.integrations.notify.loop import Notifier
from temper_ai.integrations.notify.notice import Decision, Sender

logger = logging.getLogger(__name__)

SWITCH_ENV = "TEMPER_NOTIFY"
OFF = ("0", "false", "off", "no")

_notifier: Notifier | None = None
_pending: dict[str, Sender] = {}


def switched_on() -> bool:
    return os.environ.get(SWITCH_ENV, "1").strip().lower() not in OFF


def notifier() -> Notifier | None:
    return _notifier


def start_notify() -> Notifier | None:
    """Start the loop if it may run; never raises."""
    global _notifier
    if not switched_on():
        logger.info("notify: off (%s is off)", SWITCH_ENV)
        return None
    if _notifier is not None:
        return _notifier
    try:
        n = Notifier()
        for sender in _pending.values():
            n.register(sender)
        n.start()
    except Exception as exc:  # noqa: BLE001 - a notify problem must not stop the server
        logger.warning("notify failed to start: %s", exc)
        return None
    _notifier = n
    return n


def stop_notify() -> None:
    global _notifier
    if _notifier is not None:
        _notifier.stop()
        _notifier = None


def register(sender: Sender) -> None:
    """A place is on; the loop sends there from its next tick."""
    _pending[sender.via] = sender
    if _notifier is not None:
        _notifier.register(sender)


def unregister(via: str) -> None:
    _pending.pop(via, None)
    if _notifier is not None:
        _notifier.unregister(via)


def close_question(key: str, decision: Decision, skip: int | None = None) -> int:
    """Close a question everywhere right after it was answered in a chat
    (the loop would do it on its next tick anyway)."""
    if _notifier is None:
        return 0
    try:
        return _notifier.close_question(key, decision, skip=skip)
    except Exception as exc:  # noqa: BLE001 - the loop closes it later
        logger.warning("notify: closing %s now failed (the loop will retry): %s", key, exc)
        return 0


def status() -> dict[str, Any]:
    n = _notifier
    if n is None:
        return {"running": False, "reason": f"{SWITCH_ENV} is off" if not switched_on() else "not started",
                "senders": sorted(_pending)}
    cfg = n.config.get()
    try:
        counts = store.counts()
    except Exception as exc:  # noqa: BLE001
        counts = {"error": str(exc)}  # type: ignore[dict-item]
    return {
        "running": True,
        "senders": sorted(n.senders),
        "last_tick_at": n.last_tick_at,
        "last_error": n.last_error,
        "sent": n.sent,
        "held": n.held,
        "copies": counts,
        "config": {"path": cfg.path, "error": n.config.error, "places": sorted(cfg.places)},
    }
