"""What temper remembers about Notion between restarts.

``notion_runs``: a run started from (or reporting to) a Notion page, so its
notices become comments there, a reply comment reaches it, and only one run
per page goes at a time. ``notion_events``: webhook events seen, what was
done with each (for ``/api/hooks/notion/recent`` and to drop repeats).
``notion_comments``: comments temper posted, so its own comments never start
anything. ``notion_state``: small values (the webhook verification token).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class NotionRun(SQLModel, table=True):
    __tablename__ = "notion_runs"

    id: int | None = Field(default=None, primary_key=True)
    execution_id: str = Field(index=True)
    page_id: str = Field(index=True)
    # Started from this page (a trigger rule): its notices come back here.
    origin: bool = True
    rule: str = ""
    # The comment thread temper's messages about this run go in.
    discussion_id: str = ""
    created_at: datetime = Field(default_factory=_now)


class NotionEvent(SQLModel, table=True):
    __tablename__ = "notion_events"

    id: str = Field(primary_key=True)          # Notion's event id
    at: datetime = Field(default_factory=_now, index=True)
    type: str = ""
    entity_id: str = ""
    page_id: str = ""
    author: str = ""                           # person:<id> | bot:<id>
    outcome: str = ""                          # started <run> | skipped: <why> | answered <run> | ...


class NotionComment(SQLModel, table=True):
    __tablename__ = "notion_comments"

    comment_id: str = Field(primary_key=True)
    page_id: str = Field(index=True)
    execution_id: str = ""
    discussion_id: str = ""
    # A question for a waiting gate: a reply in this discussion answers it.
    question: bool = False
    created_at: datetime = Field(default_factory=_now)


class NotionState(SQLModel, table=True):
    __tablename__ = "notion_state"

    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: datetime = Field(default_factory=_now)
