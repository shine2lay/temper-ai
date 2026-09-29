"""The clean-ups a failed run is keeping back: writing them down, and ending the wait.

A run that fails with its clean-ups held leaves one row behind (``CleanupHold``). It is what
makes the wait survive a temper restart, and what the deadline is measured against. Everything
that ends a wait goes through here:

* the run is picked up again and finishes -- the clean-ups ran with it (``done``);
* someone presses Give up, or the deadline passes -- temper starts the run once more, in its
  own box, to run those clean-ups and nothing else (``released``);
* a later attempt takes it over -- a resume of the same run, or a fork of it. Its clean-ups are
  the newer attempt's business now, and the old deadline must not tear down a setup that
  attempt is using (``taken_over``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def _rows(statement: Any) -> list[Any]:
    from temper_ai.database import get_session
    with get_session() as session:
        found = list(session.exec(statement).all())
        for row in found:
            session.expunge(row)
        return found


def record(
    execution_id: str,
    *,
    workflow_name: str,
    workspace_path: str | None,
    inputs: Mapping[str, Any] | None,
    held: Iterable[Mapping[str, Any]],
    deadline: datetime,
    stopped_at: str | None = None,
    stop_reason: str | None = None,
) -> None:
    """Write down the clean-ups this attempt kept back, replacing any earlier wait of its own."""
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import CleanupHold

    paths = [dict(h) for h in held]
    if not paths:
        return
    try:
        with get_session() as session:
            row = session.exec(
                select(CleanupHold).where(CleanupHold.execution_id == execution_id),
            ).first()
            if row is None:
                row = CleanupHold(execution_id=execution_id, workflow_name=workflow_name,
                                  deadline=deadline)
            row.workflow_name = workflow_name
            row.workspace_path = workspace_path or ""
            row.inputs = dict(inputs or {})
            row.node_paths = paths
            row.stopped_at = stopped_at
            row.stop_reason = stop_reason
            row.status = "waiting"
            row.deadline = deadline
            row.created_at = datetime.now(UTC)
            row.ended_at = None
            row.ended_by = None
            session.add(row)
        logger.info("%s: %d clean-up(s) wait until %s so the run can be picked up where it stopped",
                    execution_id, len(paths), deadline.isoformat())
    except Exception:
        logger.error("Could not write down the held clean-ups of %s", execution_id, exc_info=True)


def waiting(execution_id: str) -> dict | None:
    """The wait this run is in, or None. Shown on the page, with its time left."""
    from sqlmodel import select

    from temper_ai.runner.models import CleanupHold
    try:
        found = _rows(select(CleanupHold).where(CleanupHold.execution_id == execution_id))
    except Exception:
        logger.warning("Could not read the held clean-ups of %s", execution_id, exc_info=True)
        return None
    if not found or found[0].status != "waiting":
        return None
    return as_dict(found[0])


def as_dict(row: Any) -> dict:
    deadline = row.deadline
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    left = (deadline - datetime.now(UTC)).total_seconds() if deadline else None
    return {
        "execution_id": row.execution_id,
        "workflow_name": row.workflow_name,
        "workspace_path": row.workspace_path,
        "inputs": dict(row.inputs or {}),
        "status": row.status,
        "cleanups": [dict(p) for p in (row.node_paths or [])],
        "stopped_at": row.stopped_at,
        "stop_reason": row.stop_reason,
        "deadline": deadline.isoformat() if deadline else None,
        "seconds_left": max(0.0, left) if left is not None else None,
    }


def due(now: datetime | None = None) -> list[dict]:
    """Every wait whose deadline has passed and which nobody has ended."""
    from sqlmodel import select

    from temper_ai.runner.models import CleanupHold
    when = now or datetime.now(UTC)
    try:
        found = _rows(select(CleanupHold).where(CleanupHold.status == "waiting"))
    except Exception:
        logger.warning("Could not read the held clean-ups", exc_info=True)
        return []
    out = []
    for row in found:
        deadline = row.deadline
        if deadline is not None and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if deadline is None or deadline <= when:
            out.append(as_dict(row))
    return out


def end(execution_id: str, status: str, by: str) -> dict | None:
    """End a wait, and say what ended it. Returns what was waiting, or None if nothing was.

    Ending is a single step in the database, so two things ending the same wait at once -- the
    deadline coming round while someone presses Give up -- cannot both start the clean-ups.
    """
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import CleanupHold
    try:
        with get_session() as session:
            row = session.exec(
                select(CleanupHold).where(CleanupHold.execution_id == execution_id),
            ).first()
            if row is None or row.status != "waiting":
                return None
            row.status = status
            row.ended_at = datetime.now(UTC)
            row.ended_by = by
            session.add(row)
            session.flush()
            out = as_dict(row)
        logger.info("%s: the wait on its clean-ups ended (%s, by %s)", execution_id, status, by)
        return out
    except Exception:
        logger.error("Could not end the wait on the clean-ups of %s", execution_id, exc_info=True)
        return None


def take_over(execution_id: str, by: str) -> dict | None:
    """A newer attempt takes the wait over: its clean-ups are that attempt's business now."""
    return end(execution_id, "taken_over", by)


def finish(execution_id: str, by: str = "resume") -> dict | None:
    """The run was picked up again and finished: the clean-ups ran with it."""
    return end(execution_id, "done", by)
