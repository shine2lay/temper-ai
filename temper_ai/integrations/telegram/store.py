"""Reading and writing the Telegram tables (see ``models``)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from temper_ai.integrations.telegram.models import (
    TelegramAction,
    TelegramChat,
    TelegramPending,
    TelegramState,
    TelegramThread,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


# -- run threads -----------------------------------------------------------------


def thread_for(execution_id: str, chat_id: int) -> int | None:
    """The message the run's notices reply to in this chat, if any."""
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.exec(select(TelegramThread).where(
            TelegramThread.execution_id == execution_id, TelegramThread.chat_id == chat_id)).first()
        return row.message_id if row else None


def threads_of(execution_id: str, origin_only: bool = False) -> list[tuple[int, int]]:
    """Every (chat id, message id) the run has a thread in, oldest first."""
    from temper_ai.database import get_session

    with get_session() as session:
        stmt = select(TelegramThread).where(TelegramThread.execution_id == execution_id)
        if origin_only:
            stmt = stmt.where(TelegramThread.origin == True)  # noqa: E712 - SQL, not Python
        return [(r.chat_id, r.message_id) for r in session.exec(stmt.order_by(col(TelegramThread.id))).all()]


def save_thread(execution_id: str, chat_id: int, message_id: int, origin: bool = False) -> int:
    """Remember the run's thread in this chat; the first one saved wins.
    Returns the message id that is now the thread."""
    from temper_ai.database import get_session

    with get_session() as session:
        session.add(TelegramThread(execution_id=execution_id, chat_id=chat_id, message_id=message_id, origin=origin))
        try:
            session.commit()
            return message_id
        except IntegrityError:
            session.rollback()
    return thread_for(execution_id, chat_id) or message_id


def run_for_message(chat_id: int, message_id: int) -> str | None:
    """The run whose thread starts at this message, if any."""
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.exec(select(TelegramThread).where(
            TelegramThread.chat_id == chat_id, TelegramThread.message_id == message_id)).first()
        return row.execution_id if row else None


def move_chat(old: int, new: int) -> None:
    """A group became a supergroup (a new id): its threads and status move."""
    from temper_ai.database import get_session

    with get_session() as session:
        for row in session.exec(select(TelegramThread).where(TelegramThread.chat_id == old)).all():
            row.chat_id = new
            session.add(row)
        chat = session.get(TelegramChat, old)
        if chat is not None and session.get(TelegramChat, new) is None:
            session.add(TelegramChat(chat_id=new, type="supergroup", title=chat.title, status=chat.status,
                                     added_by=chat.added_by, detail=f"was {old}"))
        session.commit()


# -- chats ------------------------------------------------------------------------


def chat(chat_id: int) -> dict[str, Any] | None:
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.get(TelegramChat, chat_id)
        return _chat_dict(row) if row else None


def _chat_dict(row: TelegramChat) -> dict[str, Any]:
    return {"chat_id": row.chat_id, "type": row.type, "title": row.title, "status": row.status,
            "added_by": row.added_by, "detail": row.detail, "tries": row.tries,
            "first_seen": row.first_seen.isoformat() if row.first_seen else None,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None}


def save_chat(chat_id: int, *, type: str = "", title: str = "", status: str | None = None, added_by: str | None = None,
              detail: str | None = None, tried: bool = False) -> dict[str, Any]:
    """Create or update what is known about a chat; returns it."""
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.get(TelegramChat, chat_id)
        if row is None:
            row = TelegramChat(chat_id=chat_id)
        row.type = type or row.type
        row.title = title or row.title
        if status is not None:
            row.status = status
        if added_by is not None:
            row.added_by = added_by
        if detail is not None:
            row.detail = detail[:500]
        if tried:
            row.tries = (row.tries or 0) + 1
        row.last_seen = _now()
        session.add(row)
        session.commit()
        session.refresh(row)
        return _chat_dict(row)


def chats(status: str | None = None) -> list[dict[str, Any]]:
    from temper_ai.database import get_session

    with get_session() as session:
        stmt = select(TelegramChat)
        if status:
            stmt = stmt.where(TelegramChat.status == status)
        return [_chat_dict(r) for r in session.exec(stmt.order_by(col(TelegramChat.last_seen).desc())).all()]


# -- who did what -------------------------------------------------------------------


def log_action(user_id: Any, user_name: str, action: str, execution_id: str | None = None, detail: str = "",
               chat_id: Any = "") -> None:
    """Who did what from Telegram. Never fails the action it records."""
    from temper_ai.database import get_session

    try:
        with get_session() as session:
            session.add(TelegramAction(user_id=str(user_id), user_name=user_name, chat_id=str(chat_id),
                                       action=action, execution_id=execution_id, detail=detail[:1000]))
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram: could not record %s by %s: %s", action, user_id, exc)
    logger.info("Telegram: %s (%s) in %s %s %s %s", user_name, user_id, chat_id, action,
                (execution_id or "")[:8], detail[:200])


def actions(limit: int = 50, execution_id: str | None = None) -> list[dict[str, Any]]:
    from temper_ai.database import get_session

    with get_session() as session:
        stmt = select(TelegramAction)
        if execution_id:
            stmt = stmt.where(TelegramAction.execution_id == execution_id)
        rows = session.exec(stmt.order_by(col(TelegramAction.id).desc()).limit(limit)).all()
        return [{"at": r.at.isoformat(), "user_id": r.user_id, "user_name": r.user_name, "chat_id": r.chat_id,
                 "action": r.action, "execution_id": r.execution_id, "detail": r.detail} for r in rows]


# -- proposals waiting for Start ------------------------------------------------------


def add_pending(chat_id: int, data: dict[str, Any], kind: str = "proposal") -> int:
    from temper_ai.database import get_session

    with get_session() as session:
        row = TelegramPending(kind=kind, chat_id=chat_id, data=data)
        session.add(row)
        session.commit()
        session.refresh(row)
        return int(row.id or 0)


def set_pending_message(pending_id: int, message_id: int) -> None:
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.get(TelegramPending, pending_id)
        if row is not None:
            row.message_id = message_id
            session.add(row)
            session.commit()


def pending(pending_id: int) -> dict[str, Any] | None:
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.get(TelegramPending, pending_id)
        if row is None:
            return None
        return {"id": row.id, "kind": row.kind, "chat_id": row.chat_id, "message_id": row.message_id,
                "data": dict(row.data or {}), "status": row.status}


def settle_pending(pending_id: int, status: str) -> bool:
    """open -> ``status``, once: False when it was already settled (a
    second press of Start does nothing)."""
    from sqlalchemy import update

    from temper_ai.database import get_session

    with get_session() as session:
        result = session.exec(  # type: ignore[call-overload]
            update(TelegramPending).where(col(TelegramPending.id) == pending_id,
                                          col(TelegramPending.status) == "open").values(status=status))
        session.commit()
        return bool(result.rowcount)


# -- small values ---------------------------------------------------------------------


def get_state(key: str) -> str | None:
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.get(TelegramState, key)
        return row.value if row else None


def set_state(key: str, value: str) -> None:
    from temper_ai.database import get_session

    with get_session() as session:
        row = session.get(TelegramState, key) or TelegramState(key=key)
        row.value = value
        row.updated_at = _now()
        session.add(row)
        session.commit()
