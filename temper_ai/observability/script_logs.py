"""Script agents' saved logs: rows of the events table, of type ``script.log``.

A script agent's script prints while it runs. agent/script_log.py collects that output and saves
it in batches, one row each, so what a script printed can be read while it runs and survives a
refresh, a reconnect, a timeout and a cancel.

A row belongs to one attempt: the script's ``agent.started`` event, which is also the agent's id on
the dashboard. The row's parent_id is that id and its own id is ``<attempt>.log.<seq>``, the batch
number zero-padded, so

- rows sort in order by id, and a page of them is a range of ids;
- a save that is retried after an error, when the first try was stored after all, cannot store the
  batch twice;
- two attempts of one agent (a retry, a resume) or two agents with one name never share a log.

Each row's data:

    attempt_id     the attempt (the parent_id again, for whoever reads a row on its own)
    seq            the batch number: 1, 2, 3 ... with no gaps
    entries        [{stream, t, text}] in the order the output was read. ``stream`` is "stdout" or
                   "stderr"; "temper" marks a note from temper itself, which also has ``kind``:
                   "truncated" (the limit was reached), "lost" (output that could not be saved,
                   with ``lost_bytes``) or "end" (how the attempt ended: ``outcome``, and
                   ``exit_code`` when there was one). ``t`` is when the first piece of the entry
                   was read: ISO 8601, UTC, milliseconds. Order between stdout and stderr is the
                   order they were read in, which is close to, not exactly, the order of writing.
    bytes          UTF-8 bytes of output in this row
    saved_bytes    UTF-8 bytes of output saved up to and including this row
    dropped_bytes  bytes printed after the limit, so never saved (as of this row)
    lost_bytes     bytes that could not be saved for any other reason (as of this row)
    limit          the attempt's limit on saved output (``log_max_bytes``)
    truncated      True from the row that holds the "truncated" note on
    end            the last row only: {outcome, exit_code?}

Live viewers get each row as it is saved; a row with more than LIVE_ROW_MAX_BYTES of output goes
to them without ``entries`` and with ``stub: True`` (never so in the database), and a viewer that
shows that log reads the row back.

Rows are kept as long as the rest of a run's results (observability/trim.py does not touch
them), are not copied into a fork, and are read through the API (`read_script_log`) under the same
access rules as the rest of a run. They are many per agent, so everything that loads a run's
structure, or looks for its latest activity, leaves them out: see SCRIPT_LOG_PREFIX.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from temper_ai.database import get_session
from temper_ai.observability.event_types import EventType
from temper_ai.observability.models import Event

#: ``events.type`` of a log row, and the prefix that readers of a run's structure exclude.
SCRIPT_LOG = EventType.SCRIPT_LOG.value
SCRIPT_LOG_PREFIX = "script."

#: Text in one page of a log, unless the reader asks for another amount (at most MAX_PAGE_BYTES).
DEFAULT_PAGE_BYTES = 256 * 1024
MAX_PAGE_BYTES = 4 * 1024 * 1024
#: Rows in one page, at most, whatever their size.
MAX_PAGE_ROWS = 2000
#: A row is sent to live viewers with its text when it holds this much output at most. A larger
#: one (a script printing as fast as it can) is sent without it, marked ``stub``: a viewer that
#: shows that log reads the text from the database, the others are spared it.
LIVE_ROW_MAX_BYTES = 16 * 1024


def script_log_event_id(attempt_id: str, seq: int) -> str:
    """The id of an attempt's ``seq``-th log row: sorts in seq order within the attempt."""
    return f"{attempt_id}.log.{seq:08d}"


def live_row(row: dict[str, Any]) -> dict[str, Any]:
    """A saved row as sent to the run's live viewers: whole when small, else without its text."""
    if int(row.get("bytes") or 0) <= LIVE_ROW_MAX_BYTES:
        return row
    slim = {k: v for k, v in row.items() if k != "entries"}
    slim["stub"] = True
    return slim


def _seq_of(event_id: str) -> int:
    return int(event_id.rsplit(".", 1)[-1])


def _row_event(execution_id: str | None, attempt_id: str, seq: int, data: dict[str, Any]) -> Event:
    return Event(
        id=script_log_event_id(attempt_id, seq),
        type=EventType.SCRIPT_LOG,
        parent_id=attempt_id,
        execution_id=execution_id,
        data=data,
    )


def save_script_log_row(execution_id: str | None, attempt_id: str, seq: int, data: dict[str, Any]) -> str:
    """Store one log row; raises when it was not stored. Idempotent: a row already there is kept."""
    eid = script_log_event_id(attempt_id, seq)
    try:
        with get_session() as session:
            session.add(_row_event(execution_id, attempt_id, seq, data))
    except IntegrityError:
        # An earlier try reported a failure but was stored after all: the same row, by its id.
        with get_session() as session:
            if session.get(Event, eid) is None:
                raise
    return eid


def save_script_log_rows(
    execution_id: str | None, attempt_id: str, rows: list[tuple[int, dict[str, Any]]],
) -> list[str]:
    """Store log rows, ``[(seq, data), ...]``, in one transaction; raises when they were not all
    stored. Idempotent like :func:`save_script_log_row`: when some are there already (an earlier
    try was stored after all), each is stored on its own and those are kept."""
    if len(rows) == 1:
        seq, data = rows[0]
        return [save_script_log_row(execution_id, attempt_id, seq, data)]
    try:
        with get_session() as session:
            session.add_all([_row_event(execution_id, attempt_id, seq, data) for seq, data in rows])
    except IntegrityError:
        return [save_script_log_row(execution_id, attempt_id, seq, data) for seq, data in rows]
    return [script_log_event_id(attempt_id, seq) for seq, _ in rows]


def read_script_log(
    execution_id: str,
    attempt_id: str,
    *,
    after_seq: int | None = None,
    before_seq: int | None = None,
    max_bytes: int = DEFAULT_PAGE_BYTES,
) -> dict[str, Any] | None:
    """One page of an attempt's saved log, oldest row first.

    With no cursor, the newest rows (what a viewer opens on). ``before_seq``: the rows just before
    that one, for paging back. ``after_seq``: the rows just after it, for catching up. A page holds
    whole rows, at least one when there is one, and about ``max_bytes`` of output at most.

    None when the attempt is not an agent of this run, so a log is only ever read through the run
    it belongs to.
    """
    budget = max(1, min(int(max_bytes), MAX_PAGE_BYTES))
    with get_session() as session:
        attempt = session.get(Event, attempt_id)
        if (attempt is None or attempt.execution_id != execution_id
                or attempt.type != EventType.AGENT_STARTED.value):
            return None
        newest_id = session.exec(
            select(func.max(Event.id)).where(Event.parent_id == attempt_id, Event.type == SCRIPT_LOG)
        ).one()
        newest_seq = _seq_of(newest_id) if newest_id else 0
        ascending = after_seq is not None
        if ascending:
            cursor: str | None = script_log_event_id(attempt_id, max(0, int(after_seq or 0)))
        elif before_seq is not None:
            cursor = script_log_event_id(attempt_id, max(0, int(before_seq)))
        else:
            cursor = None
        rows: list[dict[str, Any]] = []
        size = 0
        batch = 4  # small first: rows are up to ~64 KB each; tiny rows come in larger batches after
        full = False
        while not full and len(rows) < MAX_PAGE_ROWS:
            stmt = select(Event.id, Event.data).where(
                Event.parent_id == attempt_id, Event.type == SCRIPT_LOG,
            )
            if ascending:
                stmt = stmt.where(col(Event.id) > cursor).order_by(col(Event.id).asc())
            else:
                if cursor is not None:
                    stmt = stmt.where(col(Event.id) < cursor)
                stmt = stmt.order_by(col(Event.id).desc())
            got = session.exec(stmt.limit(min(batch, MAX_PAGE_ROWS - len(rows)))).all()
            for eid, data in got:
                data = dict(data or {})
                n = int(data.get("bytes") or 0)
                if rows and size + n > budget:
                    full = True
                    break
                rows.append(data)
                size += n
                cursor = eid
            if len(got) < batch:
                break
            batch = min(batch * 4, 256)
    if not ascending:
        rows.reverse()
    first = rows[0]["seq"] if rows else None
    last = rows[-1]["seq"] if rows else None
    return {
        "execution_id": execution_id,
        "attempt_id": attempt_id,
        "rows": rows,
        "first_seq": first,
        "last_seq": last,
        "newest_seq": newest_seq,
        "has_more_before": bool(first and first > 1),
        "has_more_after": newest_seq > (last if last is not None else int(after_seq or 0)),
        "page_bytes": size,
    }
