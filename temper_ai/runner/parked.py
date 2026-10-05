"""Pi runs that wait on the owner without holding a worker (docs/gates.md, "Pi workflows").

In a Pi workflow a wait does not keep its worker -- a gate's (stage/executor.py,
``_park_at_gate``) or one a step asks from inside its work (stage/step_waits.py, ``ask_owner``),
both through stage/step_waits.py ``park``: it saves where the run is under the wait's own id,
writes the run's attempt down as ``waiting`` with a ``parked`` note, and the worker lets go --
the run's box exits, or its thread ends. Carrying it on runs the waiting step again: a gate
finds its answer and its step runs; a step that asked finds the answer at the same wait id
and goes on from its own record. This module carries such a run on, or ends it:

* The owner's answer carries it on through Resume's own path, in a new box or thread, without
  running again what finished. Three places ask, so the answer is never lost: the approval,
  once its answer is in (when the worker has already let go); the worker that let go, once it
  has (when the answer came first); and the server at start-up (when it stopped in between).
  Whoever asks first claims the parked attempt with a compare-and-set, so the run is carried
  on once.
* A cancel, or a rejection, ends it cancelled, holding what a cancel during a held wait holds.

A parked run never expires, never carries on by itself and never starts a new run. The
start-up pick-up (runner/pickup.py) leaves it alone whatever its age: only an answer moves it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from temper_ai.shared.clock import as_utc, utcnow

logger = logging.getLogger(__name__)

# The attempt's status, and its row's in a box, while it waits on the owner with no worker.
WAITING = "waiting"
PARKED_STATUS = WAITING
# The attempt that waited, once a later attempt carried the run on from where it waited.
CARRIED_ON = "parked"
CANCELLED = "cancelled"
CANCEL_MESSAGE = "Workflow cancelled by user"

# A claimed attempt's next attempt starts within moments (a thread, or a queued box row). A
# claim older than this with nothing after it is one whose start was lost: Resume may retry.
CLAIM_STARTS_WITHIN = timedelta(minutes=2)


class AlreadyCarriedOn(Exception):  # noqa: N818 - a refusal, said as a fact
    """Someone else carried this parked run on first."""

    def __init__(self, execution_id: str):
        super().__init__(f"Execution '{execution_id}' is already being carried on")
        self.execution_id = execution_id


def parked_attempt(execution_id: str) -> dict | None:
    """The run's latest attempt when it is parked waiting on the owner; None otherwise."""
    from temper_ai.runner.resume import find_latest_workflow_event

    latest = find_latest_workflow_event(execution_id)
    if latest is None or latest.get("status") != WAITING:
        return None
    return latest if isinstance(_note(latest), dict) else None


def being_carried_on(execution_id: str) -> bool:
    """Whether someone has just claimed the run's parked attempt and is starting the next one."""
    from temper_ai.runner.resume import find_latest_workflow_event

    latest = find_latest_workflow_event(execution_id)
    if latest is None or latest.get("status") != CARRIED_ON:
        return False
    raw = (_note(latest) or {}).get("carried_on_at")
    try:
        at = as_utc(datetime.fromisoformat(str(raw)))
    except ValueError:
        return False
    return at is not None and utcnow() - at < CLAIM_STARTS_WITHIN


def _note(attempt: dict) -> dict | None:
    note = (attempt.get("data") or {}).get("parked")
    return note if isinstance(note, dict) else None


def parked_waits(attempt: dict) -> list[str]:
    """The event ids of the waits an attempt parked at (one, or several from one batch)."""
    note = _note(attempt) or {}
    ids = [note.get("event_id"), *((w or {}).get("event_id") for w in note.get("also") or [])]
    return [str(i) for i in ids if i]


def answered(execution_id: str, attempt: dict) -> dict | None:
    """The wait the attempt parked at that the owner has approved, if any."""
    from temper_ai.observability.recorder import gate_events
    from temper_ai.stage.gate import APPROVED

    wanted = set(parked_waits(attempt))
    for event in gate_events(execution_id):
        data = event.get("data") or {}
        if (str(event.get("id")) in wanted and event.get("status") == APPROVED
                and not data.get("gate_used_at")):
            return event
    return None


def claim(attempt: dict) -> bool:
    """Take the parked attempt for carrying on; False when someone else already has."""
    from temper_ai.observability.recorder import decide_event

    note = {**(_note(attempt) or {}), "carried_on_at": utcnow().isoformat()}
    won, _ = decide_event(str(attempt["id"]), expect=(WAITING,), status=CARRIED_ON,
                          data={"parked": note})
    return won


def release(attempt: dict) -> None:
    """Put a claimed attempt back to waiting: carrying it on did not start."""
    from temper_ai.observability.recorder import decide_event

    note = {k: v for k, v in (_note(attempt) or {}).items() if k != "carried_on_at"}
    try:
        decide_event(str(attempt["id"]), expect=(CARRIED_ON,), status=WAITING, data={"parked": note})
    except Exception as exc:  # noqa: BLE001 - logged; the run still shows where it waits
        logger.warning("Run %s: could not put its parked attempt back: %s",
                       attempt.get("execution_id"), exc)


def carry_on(execution_id: str, *, start: Callable[[str], Any], by: str) -> bool:
    """Carry a parked run on if the owner has answered where it waits. Returns whether it did.

    ``start`` is Resume's own path (the API's ``resume_run``, or ``queue_resume`` in the
    worker); it claims the attempt first, so two askers never carry the run on twice.
    """
    attempt = parked_attempt(execution_id)
    if attempt is None:
        return False
    answer = answered(execution_id, attempt)
    if answer is None:
        return False
    path = (answer.get("data") or {}).get("gate_path")
    try:
        start(execution_id)
    except Exception as exc:  # noqa: BLE001 - another asker won, or it could not start
        if isinstance(exc, AlreadyCarriedOn) or getattr(exc, "status_code", None) == 409:
            logger.info("Run %s: already carried on (%s): %s", execution_id, by, exc)
        else:
            logger.warning("Run %s: answered at '%s' but could not carry it on (%s): %s",
                           execution_id, path, by, exc)
        return False
    logger.info("Run %s: answered at '%s'; carried on (%s)", execution_id, path, by)
    return True


def cancel_parked(execution_id: str, reason: str | None = None, *, by: str = "cancel") -> bool:
    """End a parked run cancelled, as a cancel during a held wait would. Returns whether it did.

    Rejects any wait still open (with the reason as its answer), ends the attempt and its row,
    and holds the clean-ups the attempt said a cancel owes (worked out when it parked).
    """
    from temper_ai.observability.recorder import decide_event

    attempt = parked_attempt(execution_id)
    if attempt is None:
        return False
    note = _note(attempt) or {}
    message = (reason or "").strip() or CANCEL_MESSAGE
    on_cancel = note.get("on_cancel") or {}
    held = list(on_cancel.get("held") or [])
    stopped = {"path": "the run", "reason": message, "at": utcnow().isoformat(),
               "mode": on_cancel.get("mode"), "held": held}
    won, _ = decide_event(
        str(attempt["id"]), expect=(WAITING,), status=CANCELLED,
        data={"error": message, "cancelled_reason": message, "stopped": stopped},
    )
    if not won:
        return False
    _reject_open_waits(execution_id, reason)
    _end_row(execution_id, CANCELLED)
    _end_pi_teams(execution_id)
    if held and on_cancel.get("mode") == "hold":
        _hold(execution_id, attempt, on_cancel, held, message)
    logger.info("Run %s: cancelled while it waited on you (%s)", execution_id, by)
    return True


def _end_pi_teams(execution_id: str) -> None:
    """The run's Pi teams end with it: what they still held or had pending is recorded
    undelivered, never dropped (R2 C2, B12). Does nothing with the Pi switch off."""
    from temper_ai.pi_agent import end_teams_on_cancel

    try:
        end_teams_on_cancel(execution_id)
    except Exception:  # noqa: BLE001 - the cancel itself has already happened
        logger.exception("Run %s: could not end its Pi teams after the cancel", execution_id)


def end_cancelled_pi_teams() -> int:
    """End the Pi teams of runs that were cancelled but whose teams were not ended: a cancel
    ends the run's row first and its teams after (above), so a process that died between the
    two left them (G-a). Ending is idempotent; this runs at start-up and in the trim sweep
    (and a team's open runs it too). Does nothing with the Pi switch off."""
    from temper_ai.pi_agent import end_cancelled_teams

    try:
        return end_cancelled_teams()
    except Exception:  # noqa: BLE001 - a sweep; the next one tries again
        logger.exception("Could not end the Pi teams of cancelled runs")
        return 0


def _reject_open_waits(execution_id: str, reason: str | None) -> None:
    from temper_ai.observability.recorder import decide_event, gate_events
    from temper_ai.stage.gate import REJECTED

    rejected: dict[str, Any] = {"gate_status": REJECTED, "gate_decided_at": utcnow().isoformat()}
    if reason and reason.strip():
        text = reason.strip()
        rejected["gate_response"] = {"response": text, "answers": [], "text": text}
    for event in gate_events(execution_id):
        if event.get("status") == WAITING:
            decide_event(str(event["id"]), expect=(WAITING,), status=REJECTED, data=rejected)


def _end_row(execution_id: str, status: str) -> None:
    """End the run's box row, if it has one, unless something else ended it already."""
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).first()
        if row is None or row.status not in (WAITING, "running"):
            return
        row.status = status
        row.completed_at = utcnow()
        session.add(row)


def _hold(execution_id: str, attempt: dict, on_cancel: dict, held: list, message: str) -> None:
    from temper_ai.runner import holds
    from temper_ai.stage.failure import FailurePolicy

    data = attempt.get("data") or {}
    policy = FailurePolicy(mode="hold", hold_hours=float(on_cancel.get("hold_hours") or 24.0))
    try:
        holds.record(
            execution_id,
            workflow_name=str(data.get("name") or data.get("workflow_name") or ""),
            workspace_path=data.get("workspace_path"),
            inputs=data.get("input_data") or {},
            held=held,
            deadline=policy.deadline(),
            stopped_at="the run",
            stop_reason=message,
        )
    except Exception as exc:  # noqa: BLE001 - the cancel stands; say what is not held
        logger.warning("Run %s: cancelled, but could not hold its clean-ups: %s", execution_id, exc)


def queue_resume(execution_id: str) -> None:
    """Carry a parked run on in a new box: what Resume does for a run in a box.

    For the worker's reaper, which has no API: claim the attempt, take over anything held,
    and queue the run to start from its checkpoints, as the Resume button would.
    """
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner import holds
    from temper_ai.runner.models import WorkflowRun
    from temper_ai.runner.queue import queue_run

    attempt = parked_attempt(execution_id)
    if attempt is None or not claim(attempt):
        raise AlreadyCarriedOn(execution_id)
    try:
        with get_session() as session:
            row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).first()
            if row is None:
                raise RuntimeError("the run has no box row")
            name, workspace, inputs = row.workflow_name, row.workspace_path, dict(row.inputs or {})
        holds.take_over(execution_id, by=execution_id)
        queue_run(execution_id, name, workspace, inputs, start="resume", extra={"rerun": []})
    except Exception:
        release(attempt)
        raise


def parked_runs() -> list[str]:
    """Every run whose latest attempt is parked waiting on the owner."""
    from sqlmodel import col, select

    from temper_ai.database import get_session
    from temper_ai.observability.event_types import EventType
    from temper_ai.observability.models import Event

    with get_session() as session:
        rows = session.exec(
            select(Event.execution_id, Event.data)
            .where(Event.type == EventType.WORKFLOW_STARTED, col(Event.status) == WAITING)
        ).all()
    found: list[str] = []
    for execution_id, data in rows:
        if execution_id and isinstance((data or {}).get("parked"), dict) and execution_id not in found:
            found.append(str(execution_id))
    return [eid for eid in found if parked_attempt(eid) is not None]


def carry_on_at_startup(start: Callable[[str], Any] | None = None) -> list[str]:
    """Carry on every parked run whose answer came while nothing could act on it.

    Run once as the server starts. A run still waiting is left as it is: no notice, no
    deadline, however long it has waited.
    """
    if start is None:
        from temper_ai.runner.pickup import _resume_through_the_button

        start = _resume_through_the_button
    end_cancelled_pi_teams()
    carried = []
    for execution_id in parked_runs():
        try:
            if carry_on(execution_id, start=start, by="start-up"):
                carried.append(execution_id)
        except Exception as exc:  # noqa: BLE001 - one run must not stop the others
            logger.warning("Run %s: could not look at its parked wait at start-up: %s", execution_id, exc)
    return carried
