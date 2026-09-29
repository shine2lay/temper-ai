"""What the event inbox keeps: one row per event temper received.

``inbox_events``: a Linear or Notion webhook delivery, a Slack envelope, a
Telegram update. The row is written before temper says "got it" to the
sender, and handled from the row, so a restart or a crash in the middle
loses nothing: the sweeper picks up what was left (service.py). The unique
(source, delivery) is what makes a re-sent event a duplicate rather than a
second piece of work.

Times carry UTC, like every other time temper stores (shared/clock.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from temper_ai.shared.clock import utcnow

__all__ = ["InboxEvent", "utcnow"]


class InboxEvent(SQLModel, table=True):
    __tablename__ = "inbox_events"
    __table_args__ = (UniqueConstraint("source", "delivery", name="uq_inbox_delivery"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)            # linear | notion | slack | telegram
    delivery: str = ""                         # the source's own id for this delivery
    kind: str = ""                             # Issue.create | page.properties_updated | command /temper | message
    subject: str = Field(default="", index=True)  # what it is about: an issue, a page, a chat
    received_at: datetime = Field(default_factory=utcnow, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # Kept only while the event waits for its signing key (status unverified):
    # the exact body and the signature header that came with it.
    raw: str = ""
    signature: str = ""
    # unverified | new | handling | done | skipped | failed | gave_up | expired
    status: str = Field(default="new", index=True)
    tries: int = 0
    worker: str = ""                           # the server process that last took it
    next_try_at: datetime | None = None        # a failed event's next try
    error: str = ""
    # {"outcome": "...", "started": [{"workflow", "execution_id"}], ...}
    result: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    handled_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)
