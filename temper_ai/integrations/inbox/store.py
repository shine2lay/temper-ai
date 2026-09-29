"""Reads and writes of ``inbox_events``.

A row moves new -> handling -> done / skipped / expired, or -> failed and
back to handling at its next try, and after the last try -> gave_up. Rows
waiting for their signing key are ``unverified`` until the sweeper checks
them. Every change of status is one UPDATE guarded by the status it
expects, so two threads can never both take the same event.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from temper_ai.integrations.inbox.models import InboxEvent
from temper_ai.shared.clock import as_utc, utcnow

HELD = "unverified"
FINISHED = ("done", "skipped", "expired", "gave_up")
STATUSES = (HELD, "new", "handling", "failed", *FINISHED)
BACKOFF_S = (60, 300, 1800, 7200)        # the wait after the 1st, 2nd, 3rd and 4th failure
MAX_TRIES = len(BACKOFF_S) + 1           # the 5th failure gives up
KEEP_DAYS = {"done": 14, "skipped": 14, "expired": 14, "failed": 30, "gave_up": 30, HELD: 30}


@dataclass
class Event:
    id: int
    source: str
    delivery: str
    kind: str
    subject: str
    received_at: datetime
    payload: dict[str, Any]
    status: str
    tries: int = 0
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    next_try_at: datetime | None = None
    handled_at: datetime | None = None
    worker: str = ""
    raw: str = ""
    signature: str = ""

    @property
    def started(self) -> list[dict[str, str]]:
        return [dict(s) for s in (self.result or {}).get("started") or [] if isinstance(s, dict)]

    @property
    def outcome(self) -> str:
        return str((self.result or {}).get("outcome") or "")

    def brief(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source, "delivery": self.delivery, "kind": self.kind,
                "subject": self.subject, "received_at": _iso(self.received_at), "status": self.status,
                "tries": self.tries, "outcome": self.outcome, "error": self.error, "started": self.started,
                "next_try_at": _iso(self.next_try_at), "handled_at": _iso(self.handled_at)}

    def full(self) -> dict[str, Any]:
        return {**self.brief(), "payload": self.payload, "result": self.result, "worker": self.worker,
                "held_body_bytes": len(self.raw.encode())}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def snapshot(row: InboxEvent) -> Event:
    return Event(id=int(row.id or 0), source=row.source, delivery=row.delivery, kind=row.kind,
                 subject=row.subject, received_at=as_utc(row.received_at) or utcnow(),
                 payload=dict(row.payload or {}), status=row.status, tries=row.tries, error=row.error,
                 result=dict(row.result or {}), next_try_at=as_utc(row.next_try_at),
                 handled_at=as_utc(row.handled_at), worker=row.worker, raw=row.raw or "",
                 signature=row.signature or "")


def _session():
    from temper_ai.database import get_session

    return get_session()


# -- saving ---------------------------------------------------------------------------------


def save(source: str, delivery: str, *, kind: str = "", subject: str = "", payload: dict[str, Any] | None = None,
         status: str = "new", raw: str = "", signature: str = "", error: str = "",
         received_at: datetime | None = None, result: dict[str, Any] | None = None) -> tuple[Event, bool]:
    """Keep one event; (the row, True) if it is new, (the row already kept, False) if it was sent again."""
    with _session() as session:
        row = InboxEvent(source=source, delivery=delivery, kind=kind[:200], subject=subject[:200],
                         payload=payload or {}, status=status, raw=raw, signature=signature, error=error,
                         result=result or {})
        if status in FINISHED:
            row.handled_at = row.received_at
        if received_at is not None:
            row.received_at = as_utc(received_at) or row.received_at
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            old = session.exec(select(InboxEvent).where(InboxEvent.source == source,
                                                        InboxEvent.delivery == delivery)).first()
            if old is None:
                raise
            return snapshot(old), False
        session.refresh(row)
        return snapshot(row), True


def get(event_id: int) -> Event | None:
    with _session() as session:
        row = session.get(InboxEvent, event_id)
        return snapshot(row) if row else None


def find(source: str, delivery: str) -> Event | None:
    with _session() as session:
        row = session.exec(select(InboxEvent).where(InboxEvent.source == source,
                                                    InboxEvent.delivery == delivery)).first()
        return snapshot(row) if row else None


# -- handling -------------------------------------------------------------------------------


def claim(event_id: int, worker: str, *, now: datetime | None = None) -> Event | None:
    """Take an event to handle it; None if it isn't there to take.

    New and failed events can be taken; so can one left "handling" by a
    server process that is gone (``worker`` differs), which is how an event
    cut off by a restart is picked up again."""
    at = as_utc(now) or utcnow()
    with _session() as session:
        stmt = (update(InboxEvent)
                .where(col(InboxEvent.id) == event_id,
                       (col(InboxEvent.status).in_(("new", "failed")))
                       | ((col(InboxEvent.status) == "handling") & (col(InboxEvent.worker) != worker)))
                .values(status="handling", tries=col(InboxEvent.tries) + 1, worker=worker, updated_at=at,
                        next_try_at=None))
        taken = session.exec(stmt).rowcount == 1  # type: ignore[call-overload]
        session.commit()
        if not taken:
            return None
        row = session.get(InboxEvent, event_id)
        return snapshot(row) if row else None


def _merge(row: InboxEvent, result: dict[str, Any] | None) -> dict[str, Any]:
    merged = {**dict(row.result or {}), **(result or {})}
    started = (row.result or {}).get("started")
    if started:
        merged["started"] = started   # what was noted while handling always stays
    return merged


def finish(event_id: int, status: str, result: dict[str, Any] | None = None, *, error: str = "",
           now: datetime | None = None) -> bool:
    """Close a handled event (done, skipped or expired)."""
    at = as_utc(now) or utcnow()
    with _session() as session:
        row = session.get(InboxEvent, event_id)
        if row is None or row.status != "handling":
            return False
        row.status, row.result, row.error = status, _merge(row, result), error[:2000]
        row.handled_at = row.updated_at = at
        row.next_try_at = None
        session.add(row)
        session.commit()
        return True


def fail(event_id: int, error: str, *, now: datetime | None = None, result: dict[str, Any] | None = None) -> str:
    """Handling failed: try again after a wait, or give up after the last try. Returns the new status."""
    at = as_utc(now) or utcnow()
    with _session() as session:
        row = session.get(InboxEvent, event_id)
        if row is None or row.status != "handling":
            return row.status if row else ""
        if row.tries >= MAX_TRIES:
            row.status, row.next_try_at = "gave_up", None
            row.handled_at = at
        else:
            row.status = "failed"
            row.next_try_at = at + timedelta(seconds=BACKOFF_S[max(row.tries, 1) - 1])
        row.error, row.result, row.updated_at = error[:2000], _merge(row, result), at
        session.add(row)
        session.commit()
        return row.status


def give_up(event_id: int, error: str, *, now: datetime | None = None) -> None:
    at = as_utc(now) or utcnow()
    with _session() as session:
        row = session.get(InboxEvent, event_id)
        if row is None or row.status in FINISHED:
            return
        row.status, row.error, row.next_try_at, row.handled_at, row.updated_at = "gave_up", error[:2000], None, at, at
        session.add(row)
        session.commit()


def note_run(event_id: int, workflow: str, execution_id: str) -> None:
    """Remember a run this event started, at once, so a retry never starts it again."""
    with _session() as session:
        row = session.get(InboxEvent, event_id)
        if row is None:
            return
        result = dict(row.result or {})
        started = [s for s in result.get("started") or [] if isinstance(s, dict)]
        started.append({"workflow": workflow, "execution_id": execution_id})
        result["started"] = started
        row.result = result
        session.add(row)
        session.commit()


def due(worker: str, sources: list[str], *, now: datetime | None = None, new_after_s: float = 120,
        limit: int = 50) -> list[int]:
    """Events to (re)try now: failed ones whose wait is over, ones left "handling"
    by a server process that is gone, and new ones nobody took for a while."""
    if not sources:
        return []
    at = as_utc(now) or utcnow()
    with _session() as session:
        rows = session.exec(
            select(InboxEvent.id)
            .where(col(InboxEvent.source).in_(sources),
                   ((col(InboxEvent.status) == "failed") & (col(InboxEvent.next_try_at) <= at))
                   | ((col(InboxEvent.status) == "handling") & (col(InboxEvent.worker) != worker))
                   | ((col(InboxEvent.status) == "new")
                      & (col(InboxEvent.updated_at) <= at - timedelta(seconds=new_after_s))))
            .order_by(col(InboxEvent.id))
            .limit(limit)).all()
        return [int(r) for r in rows if r is not None]


# -- events waiting for their signing key ----------------------------------------------------------


def held(source: str | None = None, limit: int = 100) -> list[Event]:
    with _session() as session:
        stmt = select(InboxEvent).where(InboxEvent.status == HELD)
        if source:
            stmt = stmt.where(InboxEvent.source == source)
        return [snapshot(r) for r in session.exec(stmt.order_by(col(InboxEvent.id)).limit(limit)).all()]


def count_held() -> int:
    with _session() as session:
        return int(session.exec(select(func.count()).select_from(InboxEvent)
                                .where(InboxEvent.status == HELD)).one())


def verified(event_id: int, *, payload: dict[str, Any], kind: str, subject: str) -> bool:
    """A held event checked out: it becomes an ordinary new event."""
    with _session() as session:
        row = session.get(InboxEvent, event_id)
        if row is None or row.status != HELD:
            return False
        row.payload, row.kind, row.subject = payload, kind[:200], subject[:200]
        row.status, row.raw, row.signature, row.error = "new", "", "", ""
        row.updated_at = utcnow()
        session.add(row)
        session.commit()
        return True


def drop(event_id: int) -> None:
    with _session() as session:
        session.exec(delete(InboxEvent).where(col(InboxEvent.id) == event_id))  # type: ignore[call-overload]
        session.commit()


# -- looking back ------------------------------------------------------------------------------


def listing(*, source: str | None = None, status: str | None = None, since: datetime | None = None,
            subject: str | None = None, limit: int = 50) -> list[Event]:
    """Newest first."""
    with _session() as session:
        stmt = select(InboxEvent)
        if source:
            stmt = stmt.where(InboxEvent.source == source)
        if status:
            stmt = stmt.where(InboxEvent.status == status)
        if subject:
            stmt = stmt.where(InboxEvent.subject == subject)
        if since is not None:
            stmt = stmt.where(col(InboxEvent.received_at) >= as_utc(since))
        rows = session.exec(stmt.order_by(col(InboxEvent.id).desc()).limit(max(1, min(limit, 500)))).all()
        return [snapshot(r) for r in rows]


def replay(event_id: int, *, now: datetime | None = None) -> tuple[bool, str]:
    """Put an event back to be handled again; (False, why) when that would be wrong."""
    at = as_utc(now) or utcnow()
    with _session() as session:
        row = session.get(InboxEvent, event_id)
        if row is None:
            return False, f"there is no event {event_id}"
        if row.status == HELD:
            return False, "it is still waiting for its signing key; it is handled once it is checked"
        if row.status in ("new", "handling"):
            return False, f"it is {row.status} right now"
        started = [s for s in (row.result or {}).get("started") or [] if isinstance(s, dict)]
        if started:
            runs = ", ".join(f"{s.get('workflow')} {str(s.get('execution_id'))[:8]}" for s in started)
            return False, (f"it already started {runs}; an event starts its runs once, so replaying it "
                           "would start nothing (start the workflow yourself to run it again)")
        row.status, row.tries, row.error, row.next_try_at, row.updated_at = "new", 0, "", None, at
        session.add(row)
        session.commit()
        return True, "queued to be handled again"


def prune(now: datetime | None = None) -> int:
    """Delete what is past keeping: finished rows after 14 days, failed and held ones after 30."""
    at = as_utc(now) or utcnow()
    gone = 0
    with _session() as session:
        for status, days in KEEP_DAYS.items():
            stmt = delete(InboxEvent).where(col(InboxEvent.status) == status,
                                            col(InboxEvent.received_at) < at - timedelta(days=days))
            result = session.exec(stmt)  # type: ignore[call-overload]
            gone += int(result.rowcount or 0)
        session.commit()
    return gone


_SINCE = re.compile(r"^\s*(\d+)\s*([mhdw])\s*$")


def parse_since(text: str | None, now: datetime | None = None) -> datetime | None:
    """"30m", "2h", "3d", "1w" or an ISO date/time (UTC unless it says otherwise)."""
    if not text:
        return None
    base = now or utcnow()
    m = _SINCE.match(text.lower())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return base - timedelta(**{{"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[unit]: n})
    try:
        value = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValueError(f"--since takes 30m, 2h, 3d, 1w or a date like 2026-09-27: {text!r}") from exc
    return as_utc(value)
