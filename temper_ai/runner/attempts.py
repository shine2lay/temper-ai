"""A run's attempts: which one is the newest, and which started after a given one.

An attempt is one go of a run: its own ``workflow.started`` event (every resume starts a new
one). Its work hangs under that event through ``stage.started`` events (a stage's graph, a
step), and a Pi step names its attempt by its graph's event id (``context.graph_event_id``):
the run's ``workflow.started`` for a top-level step, the enclosing stage graph's
``stage.started`` for a nested one. These helpers walk such an id up to its attempt's
``workflow.started``.

Used so an attempt that is no longer the run's newest stands down instead of taking a
newer attempt's work over (``stand_down_if_replaced``), and so a take-over never fences a
turn a newer attempt holds (``later_attempts``): SW-84, docs/pi-agent.md ("A replaced
attempt stands down"). An id that can't be placed (no such event, a made-up attempt id)
changes nothing: the caller behaves as it did before.
"""

from __future__ import annotations

#: ``ExecuteResult.status`` of an attempt that stood down for a later one. Never a run's
#: status: the run's row and its status are the newer attempt's, so nothing writes this.
REPLACED_STATUS = "replaced"

# The event types an attempt's tree is made of: workflow.started at the top, stage.started
# for every graph and step below it.
_TREE = ("workflow.", "stage.")


def _starts(execution_id: str) -> dict[str, str]:
    """``{id: timestamp}`` of the run's ``workflow.started`` events: its attempts."""
    from temper_ai.observability.event_types import EventType
    from temper_ai.observability.recorder import get_events

    events = get_events(execution_id=execution_id, event_type=EventType.WORKFLOW_STARTED,
                        limit=None)
    return {e["id"]: e.get("timestamp") or "" for e in events}


def _attempt(parents: dict[str, str | None], starts: dict[str, str],
             event_id: str | None) -> str | None:
    """The ``workflow.started`` id ``event_id`` hangs under; None when it can't be placed."""
    seen: set[str] = set()
    current = event_id
    while current is not None and current not in seen:
        if current in starts:
            return current
        if current not in parents:
            return None
        seen.add(current)
        current = parents[current]
    return None


def attempt_of(execution_id: str, event_id: str | None) -> str | None:
    """The attempt (its ``workflow.started`` id) an event of the run belongs to, or None."""
    from temper_ai.observability.recorder import event_parents

    if not event_id:
        return None
    return _attempt(event_parents(execution_id, _TREE), _starts(execution_id), event_id)


def later_attempts(execution_id: str, attempt_id: str | None) -> frozenset[str]:
    """Every attempt-tree event id of the attempts that started after ``attempt_id``'s.

    A Pi turn records its attempt as such an id, so a take-over leaves the turns in this set
    alone (``Ledger.take_over(newer_attempts=...)``). Ask it after reading the turns: a turn
    is written after its attempt's events, so any turn read belongs to an attempt this sees.
    Empty when ``attempt_id`` can't be placed, or no attempt started after it.
    """
    from temper_ai.observability.recorder import event_parents

    if not attempt_id:
        return frozenset()
    parents = event_parents(execution_id, _TREE)
    starts = _starts(execution_id)
    mine = _attempt(parents, starts, attempt_id)
    if mine is None:
        return frozenset()
    newer = {sid for sid, started in starts.items() if started > starts[mine]}
    if not newer:
        return frozenset()
    return frozenset(eid for eid in {*parents, *starts}
                     if _attempt(parents, starts, eid) in newer)


def stand_down_if_replaced(execution_id: str, attempt_id: str | None, *, where: str) -> None:
    """Raise ``ReplacedByLaterAttempt`` when a later attempt of this run has started.

    Only when ``attempt_id`` can be placed and the run's newest ``workflow.started``
    (``runner.resume.find_latest_workflow_event``) is another attempt's; otherwise it returns
    and the caller carries on as before. ``where`` says what the attempt was about to do.
    """
    from temper_ai.runner.resume import find_latest_workflow_event
    from temper_ai.stage.exceptions import ReplacedByLaterAttempt

    mine = attempt_of(execution_id, attempt_id)
    if mine is None:
        return
    newest = find_latest_workflow_event(execution_id)
    if newest is None or newest.get("id") in (None, mine):
        return
    raise ReplacedByLaterAttempt(
        f"A later attempt of this run ({newest['id']}) has started, so this attempt "
        f"({mine}) stands down {where}"
    )
