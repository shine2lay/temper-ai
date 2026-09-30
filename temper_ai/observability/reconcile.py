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

* Only runs that lived in a server process. With ``inprocess`` execution
  that is every run. With ``external`` the worker starts each run in a box
  of its own that outlives the server, and such a run always has a queued
  or running WorkflowRun row; only a run without one (left from a server
  that ran it itself, before the switch to boxes) is buried. ``subprocess``
  workers are left alone.
* Only runs that started before this process did. A run started by *this*
  server is by definition not an orphan.
* The status used is ``interrupted``, which the read path already
  understands, rather than ``failed`` — the workflow did not fail, it was
  cut off, and a later reader should be able to tell those apart.

Marking is not the end of it: :func:`reconcile_and_report` hands back what it
buried, and ``temper_ai/runner/pickup.py`` decides which of those runs temper
picks back up by itself. Which is why each entry carries the status the run had
*before* it was marked — a run parked at a gate (``waiting``) is not lost and
must not be started again behind the answerer's back.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from temper_ai.shared.clock import as_utc, utcnow

logger = logging.getLogger(__name__)

NON_TERMINAL = ("running", "queued", "waiting")
INTERRUPTED = "interrupted"


def settle_run_event(execution_id: str, status: str, message: str) -> int:
    """End a run's ``workflow.started`` event when its box is gone.

    A run in its own box writes its own end. When the box dies first (killed,
    out of memory, the host restarted) or is killed after a Stop, the reaper
    ends the run's WorkflowRun row, and this does the same for the event the
    dashboard, Slack and the notify loop read. Only an event that is still
    open is changed. Returns how many changed; never raises.
    """
    try:
        from sqlmodel import select

        from temper_ai.database.session import get_session
        from temper_ai.observability.models import Event

        with get_session() as session:
            events: Any = session.exec(
                select(Event).where(
                    Event.type == "workflow.started",
                    Event.execution_id == execution_id,
                    Event.status.in_(NON_TERMINAL),  # type: ignore[union-attr]
                )
            ).all()
            for event in events:
                event.status = status
                data = dict(event.data or {})
                data.setdefault("error", message)
                event.data = data
                session.add(event)
            if events:
                session.commit()
            return len(events)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not end the run event of %s: %s", execution_id, exc)
        return 0


def reconcile_interrupted_runs(started_before: datetime | None = None) -> int:
    """Mark non-terminal runs from a previous process as interrupted.

    Returns the number of runs updated. Never raises: a failure here must not
    stop the server from starting.
    """
    return len(reconcile_and_report(started_before=started_before))


def reconcile_and_report(started_before: datetime | None = None) -> list[dict[str, Any]]:
    """Mark them, and say which runs they were.

    One entry per run: ``execution_id``, ``event_id``, ``workflow_name``,
    ``status_before`` (running / queued / waiting) and ``timestamp`` (when that
    attempt started). Never raises.
    """
    if os.environ.get("TEMPER_RECONCILE_ORPHANS", "1").lower() in ("0", "false", "no"):
        logger.info("Orphan reconciliation disabled by TEMPER_RECONCILE_ORPHANS")
        return []

    mode = os.environ.get("TEMPER_EXECUTION_MODE", "inprocess").lower()
    if mode not in ("inprocess", "external"):
        # A subprocess worker may outlive this process; its runs are not ours to bury.
        logger.info("Orphan reconciliation skipped: execution mode is %s", mode)
        return []

    cutoff = as_utc(started_before) or utcnow()

    try:
        from sqlmodel import select

        from temper_ai.database.session import get_session
        from temper_ai.observability.models import Event

        updated: list[dict[str, Any]] = []
        with get_session() as session:
            rows: Any = session.exec(
                select(Event).where(
                    Event.type == "workflow.started",
                    Event.status.in_(NON_TERMINAL),  # type: ignore[union-attr]
                    Event.timestamp < cutoff,
                )
            ).all()
            if mode == "external":
                # A run in a box goes on without this server: not ours to bury.
                in_boxes = _runs_in_boxes(session, {e.execution_id for e in rows if e.execution_id})
                rows = [e for e in rows if e.execution_id not in in_boxes]

            for event in rows:
                was = event.status or "running"
                event.status = INTERRUPTED
                data = dict(event.data or {})
                data.setdefault(
                    "error",
                    "Interrupted: the server restarted while this run was in progress.",
                )
                event.data = data
                session.add(event)
                updated.append({
                    "execution_id": event.execution_id or event.id,
                    "event_id": event.id,
                    # The run's event calls the workflow "name"; older ones spelled it out.
                    "workflow_name": str(data.get("name") or data.get("workflow_name") or ""),
                    "status_before": was,
                    "timestamp": as_utc(event.timestamp),
                })

            if updated:
                session.commit()

        if updated:
            ids = [str(u["execution_id"]) for u in updated]
            logger.warning(
                "Marked %d interrupted run(s) from a previous process: %s",
                len(updated),
                ", ".join(r[:8] for r in ids[:5]) + (" ..." if len(ids) > 5 else ""),
            )
        return updated
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Orphan reconciliation failed (continuing startup): %s", exc)
        return []


def _runs_in_boxes(session: Any, execution_ids: set[str]) -> set[str]:
    """Which of these runs the worker has queued or started in a box."""
    if not execution_ids:
        return set()
    from sqlmodel import select

    from temper_ai.runner.models import WorkflowRun

    rows: Any = session.exec(
        select(WorkflowRun.execution_id).where(
            WorkflowRun.execution_id.in_(execution_ids),  # type: ignore[attr-defined]
            WorkflowRun.status.in_(("queued", "running")),  # type: ignore[attr-defined]
        )
    ).all()
    return set(rows)
