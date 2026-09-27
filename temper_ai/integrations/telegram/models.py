"""What temper remembers about Telegram between restarts.

``telegram_threads``: the message a run's notices reply to, per chat, so
every notice about one run hangs off one message there. ``telegram_chats``:
every chat the bot has seen and whether it may talk there.
``telegram_actions``: who did what from Telegram. ``telegram_pending``: a
suggested workflow waiting for its Start press. ``telegram_state``: small
values that must survive a restart (the update offset).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class TelegramThread(SQLModel, table=True):
    __tablename__ = "telegram_threads"
    __table_args__ = (UniqueConstraint("execution_id", "chat_id", name="uq_telegram_thread"),)

    id: int | None = Field(default=None, primary_key=True)
    execution_id: str = Field(index=True)
    chat_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))
    message_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    # Started from this chat (/run, a Start press): its notices come back here.
    origin: bool = False
    created_at: datetime = Field(default_factory=_now)


class TelegramChat(SQLModel, table=True):
    __tablename__ = "telegram_chats"

    chat_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=False))
    type: str = ""                 # private | group | supergroup | channel
    title: str = ""                # a group's title, or a person's name
    status: str = "refused"        # allowed | refused | left
    added_by: str = ""             # who added the bot to a group ("Name (id)")
    detail: str = ""
    tries: int = 0                 # messages it got while refused
    first_seen: datetime = Field(default_factory=_now)
    last_seen: datetime = Field(default_factory=_now)


class TelegramAction(SQLModel, table=True):
    __tablename__ = "telegram_actions"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=_now, index=True)
    user_id: str = ""
    user_name: str = ""
    chat_id: str = ""
    # run | stop | approve | reject | pick | confirm | cancel_pick | ask | leave
    action: str = ""
    execution_id: str | None = Field(default=None, index=True)
    detail: str = ""


class TelegramPending(SQLModel, table=True):
    __tablename__ = "telegram_pending"

    id: int | None = Field(default=None, primary_key=True)
    kind: str = "proposal"
    chat_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    message_id: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0))
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "open"           # open | started | cancelled
    created_at: datetime = Field(default_factory=_now)


class TelegramState(SQLModel, table=True):
    __tablename__ = "telegram_state"

    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: datetime = Field(default_factory=_now)
