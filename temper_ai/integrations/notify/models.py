"""What the notify layer remembers between restarts.

``notify_copies``: one row per message about one occasion in one place
(a question in the owner's Telegram chat, the same question in a Slack
thread, ...). The unique (key, via, target) is the claim that stops a
restart from sending anything twice. ``notify_runs``: a run's own
``notify:`` settings, given when it was started through the API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class NotifyCopy(SQLModel, table=True):
    __tablename__ = "notify_copies"
    __table_args__ = (UniqueConstraint("key", "via", "target", name="uq_notify_copy"),)

    id: int | None = Field(default=None, primary_key=True)
    # q:<waiting event id> | end:<run>@<end time> | stuck:<run>@<last event>
    key: str = Field(index=True)
    kind: str = ""                 # question | stuck | failed | finished
    execution_id: str = Field(default="", index=True)
    node: str = ""                 # a question's gated node
    event_id: str = ""             # a question's waiting event
    via: str = ""                  # slack | telegram
    target: str = ""               # the place: a Slack channel id, a Telegram chat id
    ref: str = ""                  # the message: "C…:ts" / "<chat>:<message id>"
    # sending | sent | held (quiet hours) | closed | failed
    status: str = Field(default="sending", index=True)
    nudge: bool = False            # sent because nobody answered in time
    release_at: datetime | None = None
    state: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    detail: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class NotifyRun(SQLModel, table=True):
    __tablename__ = "notify_runs"

    execution_id: str = Field(primary_key=True)
    settings: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
