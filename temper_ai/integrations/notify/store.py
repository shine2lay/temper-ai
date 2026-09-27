"""Reads and writes of ``notify_copies`` and ``notify_runs``."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from temper_ai.integrations.notify.models import NotifyCopy, NotifyRun
from temper_ai.integrations.notify.notice import Copy

logger = logging.getLogger(__name__)

OPEN = ("sending", "sent", "held")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _utc(value: datetime | None) -> datetime | None:
    """As naive UTC, the way the columns keep it."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def snapshot(row: NotifyCopy) -> Copy:
    return Copy(id=int(row.id or 0), key=row.key, kind=row.kind, execution_id=row.execution_id, node=row.node,
                event_id=row.event_id, via=row.via, target=row.target, ref=row.ref, status=row.status,
                nudge=row.nudge, state=dict(row.state or {}), created_at=_aware(row.created_at))


def claim(key: str, kind: str, execution_id: str, via: str, target: str, *, node: str = "",
          event_id: str = "", status: str = "sending", release_at: datetime | None = None,
          nudge: bool = False, state: dict[str, Any] | None = None, at: datetime | None = None) -> Copy | None:
    """Take one occasion in one place; None if it was already taken.

    Times are kept in UTC (the columns hold no zone). ``at`` is when it
    happened by the loop's clock (default: now)."""
    from temper_ai.database import get_session

    with get_session() as session:
        row = NotifyCopy(key=key, kind=kind, execution_id=execution_id, node=node, event_id=event_id, via=via,
                         target=target, status=status, release_at=_utc(release_at), nudge=nudge,
                         state=state or {})
        if at is not None:
            row.created_at = _utc(at) or row.created_at
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return None
        session.refresh(row)
        return snapshot(row)


def mark(copy_id: int, status: str | None = None, *, ref: str | None = None, detail: str | None = None,
         state: dict[str, Any] | None = None, only_from: Iterable[str] | None = None) -> bool:
    """Update a copy; with ``only_from``, only if its status is one of those
    (so two closers never both edit one message). True if it changed.

    One UPDATE ... WHERE, so the check and the change are one step even
    across processes."""
    from sqlalchemy import update

    from temper_ai.database import get_session

    values: dict[str, Any] = {"updated_at": _now()}
    if status is not None:
        values["status"] = status
    if ref is not None:
        values["ref"] = ref
    if detail is not None:
        values["detail"] = detail[:500]
    if state is not None:
        values["state"] = state
    stmt = update(NotifyCopy).where(col(NotifyCopy.id) == copy_id)
    if only_from is not None:
        stmt = stmt.where(col(NotifyCopy.status).in_(tuple(only_from)))
    with get_session() as session:
        result = session.exec(stmt.values(**values))  # type: ignore[call-overload]
        session.commit()
        return bool(result.rowcount)


def get(copy_id: int) -> Copy | None:
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.get(NotifyCopy, copy_id)
        return snapshot(row) if row is not None else None


def by_ref(via: str, ref: str) -> Copy | None:
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.exec(select(NotifyCopy).where(NotifyCopy.via == via, NotifyCopy.ref == ref)
                           .order_by(col(NotifyCopy.id).desc())).first()
        return snapshot(row) if row is not None else None


def copies(*, key: str | None = None, kind: str | None = None, execution_id: str | None = None,
           via: str | None = None, statuses: Iterable[str] | None = OPEN, limit: int = 500) -> list[Copy]:
    from temper_ai.database import get_session

    query = select(NotifyCopy)
    if key is not None:
        query = query.where(NotifyCopy.key == key)
    if kind is not None:
        query = query.where(NotifyCopy.kind == kind)
    if execution_id is not None:
        query = query.where(NotifyCopy.execution_id == execution_id)
    if via is not None:
        query = query.where(NotifyCopy.via == via)
    if statuses is not None:
        query = query.where(col(NotifyCopy.status).in_(list(statuses)))
    with get_session() as session:
        rows = session.exec(query.order_by(col(NotifyCopy.id).desc()).limit(limit)).all()
        return [snapshot(r) for r in rows]


def has_copies(key: str) -> bool:
    from temper_ai.database import get_session

    with get_session() as session:
        return session.exec(select(NotifyCopy.id).where(NotifyCopy.key == key)).first() is not None


def rekey_question(execution_id: str, node: str, key: str, event_id: str, from_events: Iterable[str]) -> int:
    """Open question copies of this run's gate at ``node`` whose wait is one
    of ``from_events`` (waits nobody answered: the run was resumed after a
    restart) now show the wait ``event_id``, so the run asks nothing twice."""
    from temper_ai.database import get_session

    old = list(from_events)
    if not old:
        return 0
    moved = 0
    with get_session() as session:
        rows = session.exec(select(NotifyCopy).where(
            NotifyCopy.kind == "question", NotifyCopy.execution_id == execution_id, NotifyCopy.node == node,
            col(NotifyCopy.status).in_(list(OPEN)), NotifyCopy.key != key,
            col(NotifyCopy.event_id).in_(old))).all()
        taken = set(session.exec(select(NotifyCopy.via, NotifyCopy.target).where(NotifyCopy.key == key)).all())
        for row in rows:
            if (row.via, row.target) in taken:
                row.status, row.detail = "closed", f"superseded by {key}"
            else:
                row.key, row.event_id = key, event_id
                taken.add((row.via, row.target))
                moved += 1
            row.updated_at = _now()
            session.add(row)
        session.commit()
    return moved


def due_held(now: datetime) -> list[Copy]:
    from temper_ai.database import get_session

    with get_session() as session:
        rows = session.exec(select(NotifyCopy).where(NotifyCopy.status == "held")).all()
        return [snapshot(r) for r in rows if (_aware(r.release_at) or now) <= now]



def run_settings(execution_id: str) -> dict[str, Any] | None:
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.get(NotifyRun, execution_id)
        return dict(row.settings or {}) if row is not None else None


def save_run_settings(execution_id: str, settings: dict[str, Any]) -> None:
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.get(NotifyRun, execution_id) or NotifyRun(execution_id=execution_id)
        row.settings = settings
        session.add(row)
        session.commit()


def counts() -> dict[str, int]:
    from sqlalchemy import func

    from temper_ai.database import get_session

    with get_session() as session:
        rows = session.exec(select(NotifyCopy.status, func.count()).group_by(NotifyCopy.status)).all()
        return {str(status): int(n) for status, n in rows}
