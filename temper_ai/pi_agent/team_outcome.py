"""Who ended a team, as its outcome and the Team page show it (M3 E2, E15, E16, E18).

The outcome's ``reason`` is always neutral engine text; who did it is the outcome's ``by``,
shown beside it. ``by`` comes from the API guard's record of the caller (#45), never from a
name the caller gave itself:

* ``owner`` -- one of the owner's own credentials (``owner_callers`` in the team settings);
* the credential's name for any other named caller (``temper-ci``, ``epd-autopilot``...);
  names are not secrets, and no key or hash ever leaves the server;
* ``unknown caller`` when the request carried no key.

``source`` says where the action came from, for display only (``caller.display_source``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

UNKNOWN_CALLER = "unknown caller"
OWNER = "owner"


def by_name(caller: str | None, owners: Iterable[str] | None = None) -> str | None:
    """The ``by`` shown for a recorded caller name (None when nothing was recorded)."""
    if caller is None:
        return None
    name = str(caller).strip()
    if not name or name == "unknown":
        return UNKNOWN_CALLER
    if owners is None:
        from temper_ai.pi_agent.team_config import load_team_config

        owners = load_team_config().owner_callers
    return OWNER if name in set(owners) else name


def cancel_record(run_id: str) -> dict | None:
    """The run's latest cancel as the API guard recorded it: ``{caller, source, words}``, or
    None when no cancel was recorded (yet: the record is written after the run stops)."""
    try:
        from temper_ai.observability.recorder import get_events

        events = get_events(execution_id=run_id, event_type="caller.action",  # type: ignore[arg-type]
                            limit=200)
    except Exception:  # noqa: BLE001 - who cancelled is shown when known, never needed
        logger.warning("run %s: its cancel record could not be read", run_id, exc_info=True)
        return None
    cancels = [e for e in events or [] if (e.get("data") or {}).get("action") == "cancel"]
    if not cancels:
        return None
    data = max(cancels, key=lambda e: e.get("timestamp") or "").get("data") or {}
    return {"caller": data.get("caller"), "source": data.get("caller_source") or "unknown",
            "words": str(data.get("reason") or "").strip() or None}


def _ledger() -> Any | None:
    """The ledger, when the team's outcome table exists (never creates it)."""
    import sqlalchemy as sa

    from temper_ai.database import get_database
    from temper_ai.pi_agent.ledger import Ledger

    engine = get_database().engine
    if not sa.inspect(engine).has_table("pi_team_outcomes"):
        return None
    return Ledger(engine)


def note_cancel(run_id: str, caller: Any, reason: str | None) -> int:
    """After a cancel is recorded (``POST /api/runs/{id}/cancel``): who cancelled and the
    words they gave go onto the run's teams that ended cancelled without them. Switch on
    only; never fails the cancel. Returns how many outcomes it filled."""
    from temper_ai.pi_agent import enabled

    if not enabled():
        return 0
    try:
        from temper_ai.api.caller import display_source

        ledger = _ledger()
        if ledger is None:
            return 0
        return ledger.fill_cancel(run_id, decided_by=getattr(caller, "label", None),
                                  by_source=display_source(caller),
                                  owner_words=str(reason or "").strip() or None)
    except Exception:  # noqa: BLE001 - the cancel happened; the outcome's by is shown later
        logger.warning("run %s: who cancelled could not be put on its teams", run_id,
                       exc_info=True)
        return 0


def settle_cancelled(ledger: Any, run_id: str) -> int:
    """A cancelled run's teams that were still going end cancelled, with who cancelled when
    the cancel is already recorded (a parked run's cancel, the sweep)."""
    try:
        record = cancel_record(run_id) or {}
        return ledger.settle_cancelled_outcomes(
            run_id, decided_by=record.get("caller"), by_source=record.get("source"),
            owner_words=record.get("words"))
    except Exception:  # noqa: BLE001 - the teams ended; their outcome is a view of that
        logger.warning("run %s: its teams' cancelled outcome could not be written", run_id,
                       exc_info=True)
        return 0
