"""What the trigger scheduler remembers across restarts.

``TriggerFire`` is one decision about one occasion: a schedule's due time,
a finished run, a stuck run. The (trigger, key) pair is unique, so the
same occasion can never start two runs, even if two ticks overlap or the
server restarts halfway through one. Skips are recorded too, with the
reason, which is what the history endpoint shows.

``TriggerState`` is per rule: when temper first saw it (a new rule does
not fire for runs that finished before it existed) and when it last
checked it (a schedule that fell due while temper was down is noticed,
and skipped, on the way back up).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class TriggerFire(SQLModel, table=True):
    __tablename__ = "trigger_fires"
    __table_args__ = (UniqueConstraint("trigger", "key", name="uq_trigger_fire"),)

    id: int | None = Field(default=None, primary_key=True)
    trigger: str = Field(index=True)
    key: str
    at: datetime = Field(default_factory=_now, index=True)
    # started | skipped | failed
    outcome: str = "started"
    detail: str = ""
    execution_id: str | None = None


class TriggerState(SQLModel, table=True):
    __tablename__ = "trigger_state"

    trigger: str = Field(primary_key=True)
    first_seen: datetime = Field(default_factory=_now)
    checked_at: datetime | None = None
