"""The keeper of the deadlines on held clean-ups.

When a run fails, the steps that tear its setup down -- the dev stack, the worktree -- are
held so the failed step can be tried again in the same place. They cannot be held for ever:
each wait has a deadline (24 hours by default). This sweeper is what notices the deadline has
passed and lets them run, by starting the run once more, in its own box, with nothing to do
but those steps.

It runs in the server, next to the other sweepers, and checks every minute. Nothing is lost if
the server is down when a deadline passes: the wait is a row in the database, and the first
sweep after the restart picks it up.
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_EVERY_SECONDS = 60.0

_thread: threading.Thread | None = None
_stop = threading.Event()


def _sweep() -> None:
    from temper_ai.runner import holds
    for hold in holds.due():
        execution_id = hold["execution_id"]
        ended = holds.end(execution_id, "released", by="deadline")
        if ended is None:  # someone got there first (Give up, or a resume taking over)
            continue
        logger.info("%s: the wait on its clean-ups has run out; running them now", execution_id)
        try:
            from temper_ai.api.routes import _queue_cleanup_pass
            _queue_cleanup_pass(ended)
        except Exception:
            logger.error("%s: could not start its held clean-ups", execution_id, exc_info=True)


def _loop() -> None:
    while not _stop.wait(_EVERY_SECONDS):
        try:
            _sweep()
        except Exception:
            logger.error("The sweep of held clean-ups failed", exc_info=True)


def start() -> bool:
    """Start the sweeper. Off with ``TEMPER_CLEANUP_SWEEPER=0``."""
    global _thread
    if os.environ.get("TEMPER_CLEANUP_SWEEPER", "1").strip().lower() in ("0", "false", "off", "no"):
        logger.info("The keeper of clean-up deadlines is off; held clean-ups wait for Give up")
        return False
    if _thread is not None and _thread.is_alive():
        return True
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="cleanup-holds", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()
