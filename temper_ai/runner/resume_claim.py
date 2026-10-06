"""One start at a time for a Pi run cut off while it ran (docs/gates.md, "Pi workflows").

A Pi run must never have two copies going: its members' sessions, files and mail belong to one
attempt at a time. A Pi run cut off while it ran (its worker died, the server stopped) is
carried on by Resume: the button, the API, or temper's own pick-up at start-up
(runner/pickup.py), and several of them may ask at the same moment. Checking that nothing is
going and then starting leaves a gap in which every asker of that moment passes the check:
three resumes sent at once started three attempts (L3 F2). So before it starts the next
attempt, an asker claims the run here, with one database write that exactly one asker wins, on
Postgres and on SQLite alike:

* the claim is a row keyed by the run (``resume_claims``) naming the attempt it carries on
  from: the first insert wins, and every other asker's insert fails on the key;
* it holds while its start has yet to write the next attempt down (for ``CLAIM_STARTS_WITHIN``:
  older than that with no next attempt, the start was lost), and then for as long as that
  attempt is going: it ends with the attempt;
* an asker who finds the claim ended takes it over with an update naming the token it read,
  which only one asker can win;
* an asker whose start fails gives the claim back.

The asker that loses is told the run is already being carried on, and starts nothing. A run
parked on a person's answer is claimed on its parked attempt instead (runner/parked.py
``claim``); runs of other workflows are not claimed here.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

from temper_ai.shared.clock import as_utc, utcnow

logger = logging.getLogger(__name__)

#: An attempt's status while it is going: a claim whose attempt has it still holds.
GOING = "running"

# SQLite has no row locks to wait on (and the tests' in-memory database shares one connection
# between threads), so on SQLite one process lock lets one asker through at a time. On
# Postgres the primary key and the row lock do that, across processes too.
_SQLITE_LOCK = threading.Lock()


@dataclass(frozen=True)
class _Held:
    token: str
    from_attempt: str
    claimed_at: datetime | None


def claim(execution_id: str, *, by: str = "") -> str | None:
    """Claim the start of a cut-off Pi run's next attempt: the claim's token, or None when
    another asker holds the claim (the run is already being carried on)."""
    token = uuid.uuid4().hex
    with _one_at_a_time():
        for _try in range(3):
            if _insert(execution_id, _attempt_id(_newest(execution_id)), token, by):
                return token
            held = _read(execution_id)
            if held is None:
                continue  # given back meanwhile: the insert may win now
            # The run's newest attempt, read after the claim was, so whatever the claimed
            # start has done by now counts.
            newest = _newest(execution_id)
            if _still_held(held, newest):
                return None
            # Exactly one asker's update still finds the token it read.
            if _take_over(execution_id, held.token, _attempt_id(newest), token, by):
                return token
            # Another asker took it over first, or it was given back: look again.
    return None


def release(execution_id: str, token: str) -> None:
    """Give a claim back: the start it was taken for did not happen."""
    from temper_ai.database import get_session
    from temper_ai.runner.models import ResumeClaim

    try:
        with _one_at_a_time(), get_session() as session:
            session.exec(  # type: ignore[call-overload]
                sa_delete(ResumeClaim).where(col(ResumeClaim.execution_id) == execution_id,
                                             col(ResumeClaim.token) == token))
    except Exception as exc:  # noqa: BLE001 - logged; the claim ends by itself (CLAIM_STARTS_WITHIN)
        logger.warning("Run %s: could not give back its resume claim: %s", execution_id, exc)


def _newest(execution_id: str) -> dict | None:
    """The run's newest attempt (its latest ``workflow.started`` event)."""
    from temper_ai.runner.resume import find_latest_workflow_event

    return find_latest_workflow_event(execution_id)


def _attempt_id(attempt: dict | None) -> str:
    return str(attempt["id"]) if attempt else ""


def _still_held(held: _Held, newest: dict | None) -> bool:
    """Whether a claim another asker took is still theirs, given the run's newest attempt."""
    from temper_ai.runner.parked import CLAIM_STARTS_WITHIN

    if held.from_attempt == _attempt_id(newest):
        # Its start has not written the next attempt down yet; past CLAIM_STARTS_WITHIN it
        # never will: the start was lost, and the claim with it.
        return held.claimed_at is not None and utcnow() - held.claimed_at < CLAIM_STARTS_WITHIN
    # The claimed start wrote its attempt down: the claim lasts while that attempt is going.
    return newest is not None and str(newest.get("status") or "") == GOING


@contextmanager
def _one_at_a_time() -> Iterator[None]:
    from temper_ai.database import get_database

    sqlite = get_database().engine.dialect.name == "sqlite"
    with _SQLITE_LOCK if sqlite else nullcontext():
        yield


def _insert(execution_id: str, from_attempt: str, token: str, by: str) -> bool:
    from temper_ai.database import get_session
    from temper_ai.runner.models import ResumeClaim

    try:
        with get_session() as session:
            session.add(ResumeClaim(execution_id=execution_id, from_attempt=from_attempt,
                                    token=token, claimed_at=utcnow(), claimed_by=by))
    except IntegrityError:
        return False  # someone holds a claim on this run (it may have ended: see _still_held)
    return True


def _read(execution_id: str) -> _Held | None:
    from temper_ai.database import get_session
    from temper_ai.runner.models import ResumeClaim

    with get_session() as session:
        row = session.get(ResumeClaim, execution_id)
        if row is None:
            return None
        return _Held(token=row.token, from_attempt=row.from_attempt,
                     claimed_at=as_utc(row.claimed_at))


def _take_over(execution_id: str, old_token: str, from_attempt: str, token: str, by: str) -> bool:
    from temper_ai.database import get_session
    from temper_ai.runner.models import ResumeClaim

    with get_session() as session:
        done = session.exec(  # type: ignore[call-overload]
            sa_update(ResumeClaim)
            .where(col(ResumeClaim.execution_id) == execution_id,
                   col(ResumeClaim.token) == old_token)
            .values(from_attempt=from_attempt, token=token, claimed_at=utcnow(), claimed_by=by)
            .execution_options(synchronize_session=False))
        return bool(done.rowcount == 1)
