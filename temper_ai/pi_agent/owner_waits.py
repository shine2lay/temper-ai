"""Asking the owner at a Pi wait: one ``pi_waits`` row, then ``ask_owner`` (R2 B10/B11, PARK P1).

Every owner wait a Pi team or Pi step opens is written first as a ``pi_waits`` row in the
ledger (:meth:`~temper_ai.pi_agent.ledger.Ledger.open_wait` and friends). Only then is it
asked, through :func:`temper_ai.stage.step_waits.ask_owner`, under that row's own
``wait_id``: in a Pi workflow an unanswered wait parks the run (the worker is freed) and the
owner's answer carries it on; the step runs again and finds the answer under the same id.

This is the single bridge from a ``pi_waits`` row to ``ask_owner``. The team runner uses it
for its pause, stalled, recovery and owner waits, and the single Pi step for its own (C7). It
never catches ``RunParked``: a parked run must reach the executor.

The row names its event: before asking, the bridge sets the row's ``gate_name`` to the name
``ask_owner`` files the wait under (``<step path>~ask-<wait id>``), so anything that looks for a
Pi wait's event finds it by that name. The row's ``event_id`` and ``event_recorded`` columns
are not used since C7.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, overload

import sqlalchemy as sa

from temper_ai.pi_agent.ledger import Ledger, waits
from temper_ai.stage.step_waits import OwnerAnswer, ask_owner, wait_name


class WaitNotWritten(LookupError):
    """``ask_owner_for_wait`` was called for a wait with no ``pi_waits`` row."""


class WaitDecided(Exception):
    """The wait's row was decided meanwhile (by another attempt): nothing is asked. Carries
    the row's decision so the caller can go on from it."""

    def __init__(self, wait_id: str, decision: Any, state: str):
        super().__init__(f"wait {wait_id[:12]} was already {state}")
        self.wait_id = wait_id
        self.decision = decision
        self.state = state


def wait_row(ledger: Ledger, wait_id: str) -> dict | None:
    """The ``pi_waits`` row of ``wait_id``, or None."""
    with ledger.engine.connect() as conn:
        row = conn.execute(sa.select(waits).where(waits.c.wait_id == wait_id)).mappings().first()
    return dict(row) if row is not None else None


@overload
def ask_owner_for_wait(context: Any, ledger: Ledger, wait_id: str, *, question: str,
                       header: str = "", detail: str = "", options: Sequence[str] = (),
                       hold: Literal[True] = True, also: tuple[dict, ...] = ()) -> OwnerAnswer: ...


@overload
def ask_owner_for_wait(context: Any, ledger: Ledger, wait_id: str, *, question: str,
                       header: str = "", detail: str = "", options: Sequence[str] = (),
                       hold: bool, also: tuple[dict, ...] = ()) -> OwnerAnswer | None: ...


def ask_owner_for_wait(context: Any, ledger: Ledger, wait_id: str, *, question: str,
                       header: str = "", detail: str = "",
                       options: Sequence[str] = (), hold: bool = True,
                       also: tuple[dict, ...] = ()) -> OwnerAnswer | None:
    """The owner's answer at the open ``pi_waits`` row ``wait_id``, asked under that same id.

    ``context`` is the step's own (``ask_owner`` files the wait under its ``step_path``).
    Raises :class:`WaitNotWritten` when there is no row (a wait is written before it is
    asked, never after) and :class:`WaitDecided` when the row is no longer open; otherwise
    exactly what ``ask_owner`` raises: ``RunParked`` in a Pi workflow while the owner has not
    answered (let it go up), ``CancellationError`` for a stopped run (its
    ``ReplacedByLaterAttempt`` when a later attempt took the wait over). The caller records the
    decision on the row (``Ledger.decide_wait``, compare-and-set) once it has applied it.
    """
    row = wait_row(ledger, wait_id)
    if row is None:
        raise WaitNotWritten(f"wait {wait_id[:12]} has no pi_waits row: a Pi wait is written "
                             "before it is asked")
    if row["state"] != "open":
        raise WaitDecided(wait_id, row["decision"], row["state"])
    path = getattr(context, "step_path", None)
    if path:
        name = wait_name(path, wait_id)
        if row["gate_name"] != name:
            with ledger.engine.begin() as conn:
                conn.execute(waits.update().where(
                    waits.c.wait_id == wait_id, waits.c.state == "open").values(gate_name=name))
    return ask_owner(context, wait_id, question=question, header=header, detail=detail,
                     options=tuple(options), hold=hold, **({"also": also} if also else {}))
