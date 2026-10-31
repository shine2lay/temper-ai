"""Admit held cleanup work and release its wait in one commit."""

from __future__ import annotations

import logging

from temper_ai.database import get_session
from temper_ai.runner import holds, queue

logger = logging.getLogger(__name__)


def queue_held_cleanups(execution_id: str, *, by: str) -> dict | None:
    """Return the released hold, or None when another actor already ended it.

    Lock order is hold then run row. Both ordinary and parked resumes commit
    their queue transaction before taking a hold, so they hold no run-row lock
    while asking for this hold. An unsafe workspace or busy row rolls back the
    release too; the deadline and original cleanup paths remain retryable.
    """
    with get_session() as session:
        ended = holds.end_in(session, execution_id, "released", by)
        if ended is None:
            return None
        paths = [str(c["path"]) for c in ended["cleanups"] if c.get("path")]
        if paths:
            queue.queue_run_in(session, execution_id, ended["workflow_name"],
                               ended.get("workspace_path") or None, ended.get("inputs") or {},
                               start="cleanup", extra={"only": paths})
    logger.info("%s: released its held clean-ups with admitted work (by %s, paths=%s)",
                execution_id, by, paths)
    return ended
