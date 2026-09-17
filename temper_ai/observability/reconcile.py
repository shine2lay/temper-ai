"""Reconcile runs that were interrupted by a process restart.

A run's status lives on its ``workflow.started`` event and is updated when it
finishes. An in-process run therefore has no way to record its own death: if
the server is restarted mid-run, the event stays ``running`` for ever. The
dashboard shows it as live, the list sorts it among real work, and nothing
ever resolves it.

An earlier reading of the data said this was not worth fixing — 997 runs, no
orphans. That sample was taken at a quiet moment, and orphans are *created*
by restarts, which is what deploys do. A day of ordinary work produced two
runs sitting at "running" for nineteen hours.

Scope, deliberately narrow:

* Only ``inprocess`` execution. With an external worker pool the server is
  not the thing running the workflow, so a server restart says nothing about
  whether the run is alive, and marking it dead would be a lie.
* Only runs that started before this process did. A run started by *this*
  server is by definition not an orphan.
* The status used is ``interrupted``, which the read path already
  understands, rather than ``failed`` — the workflow did not fail, it was
  cut off, and a later reader should be able to tell those apart.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

NON_TERMINAL = ("running", "queued", "waiting")
INTERRUPTED = "interrupted"


def reconcile_interrupted_runs(started_before: datetime | None = None) -> int:
    """Mark non-terminal runs from a previous process as interrupted.

    Returns the number of runs updated. Never raises: a failure here must not
    stop the server from starting.
    """
    if os.environ.get("TEMPER_RECONCILE_ORPHANS", "1").lower() in ("0", "false", "no"):
        logger.info("Orphan reconciliation disabled by TEMPER_RECONCILE_ORPHANS")
        return 0

    mode = os.environ.get("TEMPER_EXECUTION_MODE", "inprocess").lower()
    if mode != "inprocess":
        # An external worker outlives this process; its runs are not ours to bury.
        logger.info("Orphan reconciliation skipped: execution mode is %s", mode)
        return 0

    cutoff = started_before or datetime.now(UTC).replace(tzinfo=None)

    try:
        from sqlmodel import select

        from temper_ai.database.session import get_session
        from temper_ai.observability.models import Event

        updated: list[str] = []
        with get_session() as session:
            rows: Any = session.exec(
                select(Event).where(
                    Event.type == "workflow.started",
                    Event.status.in_(NON_TERMINAL),  # type: ignore[union-attr]
                    Event.timestamp < cutoff,
                )
            ).all()

            for event in rows:
                event.status = INTERRUPTED
                data = dict(event.data or {})
                data.setdefault(
                    "error",
                    "Interrupted: the server restarted while this run was in progress.",
                )
                event.data = data
                session.add(event)
                updated.append(event.execution_id or event.id)

            if updated:
                session.commit()

        if updated:
            logger.warning(
                "Marked %d interrupted run(s) from a previous process: %s",
                len(updated),
                ", ".join(r[:8] for r in updated[:5]) + (" ..." if len(updated) > 5 else ""),
            )
        return len(updated)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Orphan reconciliation failed (continuing startup): %s", exc)
        return 0
