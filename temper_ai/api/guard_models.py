"""Tables behind the API write guard (api/caller.py).

Both are new tables, created by ``create_all``: nothing existing changes,
so an older server and a newer one can share the database.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from temper_ai.shared.clock import utcnow


class RunToken(SQLModel, table=True):
    """The key one run's script steps use to start and fork runs.

    Only the sha256 of the key is kept; the key itself lives in the run's own
    process and goes to its script steps (api/run_tokens.py). One row per
    run, removed when the run's process ends.
    """

    __tablename__ = "run_tokens"

    execution_id: str = Field(primary_key=True)
    token_hash: str = Field(index=True)
    workflow_name: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow)


class GuardSeen(SQLModel, table=True):
    """Who has changed things through the API, kept across restarts.

    One row per (caller, action): the record-mode check asks "has anyone
    unnamed written in the last day?" and "has every writer we expect shown
    up under its name?" from here, which survives the deploys a log would not.
    ``caller`` is "" for a caller nobody could name.
    """

    __tablename__ = "api_guard_seen"

    caller: str = Field(primary_key=True)
    action: str = Field(primary_key=True)
    count: int = Field(default=0)
    refused: int = Field(default=0)
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow, index=True)
    last_via: str = Field(default="")
    last_source: str = Field(default="")
    last_run_id: str = Field(default="")
