"""Reading and writing the two Slack tables (see ``models``)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from temper_ai.integrations.slack.models import SlackAction, SlackThread

logger = logging.getLogger(__name__)


def thread_for(execution_id: str, channel: str) -> str | None:
    """The ts of the run's thread in ``channel``, if it has one."""
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.exec(
            select(SlackThread).where(SlackThread.execution_id == execution_id, SlackThread.channel == channel)
        ).first()
        return row.ts if row else None


def threads_of(execution_id: str, origin_only: bool = False) -> list[tuple[str, str]]:
    """Every (channel, ts) the run has a thread in, oldest first."""
    from temper_ai.database import get_session

    with get_session() as session:
        stmt = select(SlackThread).where(SlackThread.execution_id == execution_id)
        if origin_only:
            stmt = stmt.where(SlackThread.origin == True)  # noqa: E712 - SQL, not Python
        rows = session.exec(stmt.order_by(col(SlackThread.id))).all()
        return [(r.channel, r.ts) for r in rows]


def save_thread(execution_id: str, channel: str, ts: str, origin: bool = False) -> str:
    """Remember the run's thread in ``channel``; the first one saved wins.

    Returns the ts that is now the thread (another notice may have raced
    this one to the same channel).
    """
    from temper_ai.database import get_session

    with get_session() as session:
        session.add(SlackThread(execution_id=execution_id, channel=channel, ts=ts, origin=origin))
        try:
            session.commit()
            return ts
        except IntegrityError:
            session.rollback()
    return thread_for(execution_id, channel) or ts


def run_for_thread(channel: str, ts: str) -> str | None:
    """The run whose thread this is, if any."""
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.exec(
            select(SlackThread).where(SlackThread.channel == channel, SlackThread.ts == ts)
        ).first()
        return row.execution_id if row else None


def log_action(user_id: str, user_name: str, action: str, execution_id: str | None = None,
               detail: str = "") -> None:
    """Who did what from Slack. Never fails the action it records."""
    from temper_ai.database import get_session

    try:
        with get_session() as session:
            session.add(SlackAction(user_id=user_id, user_name=user_name, action=action,
                                    execution_id=execution_id, detail=detail[:1000]))
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Slack: could not record %s by %s: %s", action, user_id, exc)
    logger.info("Slack: %s (%s) %s %s %s", user_name, user_id, action, (execution_id or "")[:8], detail[:200])


def actions(limit: int = 50, execution_id: str | None = None) -> list[dict[str, Any]]:
    from temper_ai.database import get_session

    with get_session() as session:
        stmt = select(SlackAction)
        if execution_id:
            stmt = stmt.where(SlackAction.execution_id == execution_id)
        rows = session.exec(stmt.order_by(col(SlackAction.id).desc()).limit(limit)).all()
        return [{"at": r.at.isoformat(), "user_id": r.user_id, "user_name": r.user_name, "action": r.action,
                 "execution_id": r.execution_id, "detail": r.detail} for r in rows]
