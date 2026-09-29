"""One clock for every time temper stores.

**Every datetime temper writes carries a time zone, and that zone is UTC.**

Before this, two stores (the event inbox and notify) stripped the zone off on
the way in — "as naive UTC, the way the columns keep it" — and put it back on
the way out. That worked until SQLModel 0.0.4x started mapping every
``datetime`` field to a column type that refuses a naive value:

    ValueError: Datetime values must have timezone information.

105 tests failed on the newest SQLModel because of it, and the notify loop
swallowed the same error live ("notify: questions check failed"). Rather than
pin the library away from the problem, the naive values are gone.

Storing aware UTC is safe on the columns temper already has
(``timestamp without time zone`` in the live database):

* SQLite's DATETIME writes the fields and ignores the offset, so an aware UTC
  value and the naive UTC value it came from are the same eight bytes of text.
* Postgres casts the ``timestamptz`` psycopg2 sends down to the column's
  ``timestamp`` using the session's time zone, which
  :func:`temper_ai.database.engine.create_app_engine` pins to UTC.

So no migration is needed, and a column that is already ``timestamptz``
(SQLModel 0.0.4x creates them that way) is right either way.

Reading is the other half: a naive value out of an old column, or out of
SQLite, means UTC. :func:`as_utc` says so once instead of in eight places.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["utcnow", "as_utc"]


def utcnow() -> datetime:
    """Now, with UTC attached. The only ``now`` stored code should use."""
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """The same moment as an aware UTC datetime; ``None`` stays ``None``.

    A naive value is read as UTC — that is what every naive datetime in
    temper's database and in its own ISO text has always meant.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
