"""What temper remembers about Slack between restarts.

``slack_threads``: the message a run's thread hangs off, per destination,
so every notice about one run lands in one thread (a channel and a DM each
get their own). ``slack_actions``: who did what from Slack, since anyone in
the workspace may start, stop, approve or reject.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class SlackThread(SQLModel, table=True):
    __tablename__ = "slack_threads"
    __table_args__ = (UniqueConstraint("execution_id", "channel", name="uq_slack_thread"),)

    id: int | None = Field(default=None, primary_key=True)
    execution_id: str = Field(index=True)
    channel: str          # the resolved channel id (a DM's is D…)
    ts: str               # the thread's first message
    # Started from Slack here (/temper run, a confirmed @temper pick): every
    # notice about the run comes here too, whatever the routing says.
    origin: bool = False
    created_at: datetime = Field(default_factory=_now)


class SlackAction(SQLModel, table=True):
    __tablename__ = "slack_actions"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=_now, index=True)
    user_id: str = ""
    user_name: str = ""
    # run | stop | approve | reject | pick | confirm | cancel_pick
    action: str = ""
    execution_id: str | None = Field(default=None, index=True)
    detail: str = ""
